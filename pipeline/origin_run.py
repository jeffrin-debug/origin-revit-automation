# origin_run.py
# ============================================================
# ORIGIN - the one runner behind every `origin` command, for the model OPEN IN THE REVIT UI.
#
# origin.ps1 writes _origin_cli.json, then sends this file through the pipeline bridge:
#
#     {"steps": ["ceiling", "walls", "ceilings", "soffits", "columns", "beams"]}
#
# Whatever subset is asked for, it runs in CANONICAL order, never the order it was typed:
# the ceiling/wall separation has to happen before anything is panelled (the panel generators
# read the ceilings it builds), and walls come before the rest because they own the corner and
# butt logic every other generator measures against.
#
# NOTHING IS SAVED. The change lands in the open session; you look at it and save it yourself.
# That is deliberate - this is the interactive flow, not the batch. `pipeline.cmd` is still the
# batch, and it is the only thing that writes .rvt files.
#
# The ceiling step runs in its own transaction and is ROLLED BACK if verification fails. When
# it fails, no panel step runs at all, so drywall can never be laid over a ceiling layout that
# did not verify.
# ============================================================

import clr
import json
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

ROOT = _paths["PIPELINE_ROOT"]
CEILING_ROOT = _paths["CEILING_ROOT"]
CONFIG = os.path.join(ROOT, "_origin_cli.json")
REPORT_DIR = os.path.join(ROOT, "_reports", "live")

PANEL_STEPS = ["walls", "ceilings", "soffits", "columns", "beams"]
ORDER = ["ceiling"] + PANEL_STEPS

if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)


def _stem(title):
    s = "".join(ch for ch in title if ch.isalnum() or ch in "-_ ").strip()
    return s or "current"


cfg = {}
try:
    f = open(CONFIG)
    try:
        cfg = json.load(f)
    finally:
        f.close()
except Exception:
    pass

asked = cfg.get("steps") or []
steps = [s for s in ORDER if s in asked]
unknown = [s for s in asked if s not in ORDER]

doc = DocumentManager.Instance.CurrentDBDocument
stamp = time.strftime("%Y%m%d_%H%M%S")
detail_path = os.path.join(REPORT_DIR, "{}_{}.json".format(_stem(doc.Title), stamp))

res = {
    "doc": doc.Title,
    "requested": asked,
    "running": steps,
    "saved": False,
    "note": "nothing was saved - use File > Save As in Revit to keep this",
    "ok": False,
}
if unknown:
    res["unknown_steps"] = unknown

detail = {"doc": doc.Title, "steps": steps}
t_all = time.time()

if not steps:
    res["error"] = "no steps requested - _origin_cli.json had {}".format(asked)
    OUT = res
else:
    ceiling_ok = True

    # ---------------- ceiling / wall separation (stage 1) ----------------
    if "ceiling" in steps:
        t0 = time.time()
        row = {}
        t = None
        try:
            core = {"__name__": "origin_ceiling_rebuild_core"}
            core_path = os.path.join(CEILING_ROOT, "origin_ceiling_rebuild_core.py")
            core["__file__"] = core_path
            exec(compile(open(core_path).read(), core_path, "exec"), core)

            # Dynamo's periodic node may still be holding a transaction against this document;
            # a raw Transaction cannot start underneath it, and we need a raw one so a failed
            # rebuild can be rolled back rather than half-applied.
            TransactionManager.Instance.ForceCloseTransaction()
            t = Transaction(doc, "ORIGIN ceiling/wall separation")
            fho = t.GetFailureHandlingOptions()
            try:
                fho.SetForcedModalHandling(False)
                fho.SetClearAfterRollback(True)
                t.SetFailureHandlingOptions(fho)
            except Exception:
                pass
            t.Start()

            rep = core["run_on_document"](doc)
            detail["ceiling"] = rep

            if rep.get("ok"):
                t.Commit()
                t = None
                row["committed"] = True
            else:
                t.RollBack()
                t = None
                row["committed"] = False
                ceiling_ok = False

            ps = rep.get("plan_summary") or {}
            row.update({
                "ok": bool(rep.get("ok")),
                "regions": rep.get("regions_total"),
                "authored_rooms": ps.get("regions_authored"),
                "kept_ceilings": ps.get("ceilings_keep"),
                "created": len(rep.get("created") or []),
                "deleted": (rep.get("deleted") or {}).get("actually_deleted"),
                "collateral": len((rep.get("deleted") or {}).get("collateral") or []),
                "bare_area_sf": ps.get("bare_area_sf"),
                "heights": rep.get("height_by_level"),
                "verify_failures": (rep.get("verify") or {}).get("failures"),
                "fail_reasons": rep.get("fail_reasons"),
            })
        except Exception:
            row["ok"] = False
            row["error"] = traceback.format_exc()[-1500:]
            ceiling_ok = False
            detail["ceiling_error"] = traceback.format_exc()
        finally:
            try:
                if t is not None and t.HasStarted() and not t.HasEnded():
                    t.RollBack()
            except Exception:
                pass
            try:
                TransactionManager.Instance.ForceCloseTransaction()
            except Exception:
                pass
        row["sec"] = round(time.time() - t0, 2)
        res["ceiling"] = row

    # ---------------- panels ----------------
    panel_steps = [s for s in steps if s in PANEL_STEPS]
    if panel_steps and not ceiling_ok:
        res["panels"] = {"ok": False,
                         "skipped": "ceiling/wall separation failed - not panelling over a "
                                    "ceiling layout that did not verify"}
    elif panel_steps:
        t0 = time.time()
        row = {}
        try:
            stage2 = {"__name__": "stage2_panels"}
            stage2_path = os.path.join(ROOT, "stage2_panels.py")
            stage2["__file__"] = stage2_path
            exec(compile(open(stage2_path).read(), stage2_path, "exec"), stage2)

            # The generators each open their own transaction, so none of ours may be open.
            TransactionManager.Instance.ForceCloseTransaction()
            prep = stage2["run_on_document"](doc, manifest_dir=None, only=panel_steps)
            detail["panels"] = prep

            gens = {}
            for label, v in (prep.get("generators") or {}).items():
                if not isinstance(v, dict):
                    gens[label] = {"out": str(v)[:200]}
                    continue
                slim = {}
                for k, val in v.items():
                    if isinstance(val, list):
                        slim[k] = val[:5]
                    elif isinstance(val, str) and len(val) > 400:
                        slim[k] = val[-400:]
                    else:
                        slim[k] = val
                gens[label] = slim
            cd = prep.get("ceiling_direction") or {}
            row.update({
                "ok": bool(prep.get("ok")),
                "counts": prep.get("counts"),
                "generators": gens,
                "direction": cd.get("summary"),
                "direction_applied": cd.get("applied"),
                "direction_skipped": cd.get("skipped"),
                "direction_warnings": ((cd.get("decision") or {}).get("warnings") or [])[:3],
                "error": prep.get("error"),
            })
        except Exception:
            row["ok"] = False
            row["error"] = traceback.format_exc()[-1500:]
            try:
                TransactionManager.Instance.ForceCloseTransaction()
            except Exception:
                pass
        row["sec"] = round(time.time() - t0, 2)
        res["panels"] = row

    res["ok"] = all(res.get(k, {}).get("ok", True) for k in ("ceiling", "panels"))

    try:
        f = open(detail_path, "w")
        try:
            json.dump(detail, f, indent=2, default=str)
        finally:
            f.close()
        res["report"] = detail_path
    except Exception:
        res["report_error"] = traceback.format_exc()[-300:]

    res["sec"] = round(time.time() - t_all, 2)
    OUT = res
