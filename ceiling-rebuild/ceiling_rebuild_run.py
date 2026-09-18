# ceiling_rebuild_run.py
# ============================================================
# Rebuild per-room ceilings. Each env is opened as a BACKGROUND document, rebuilt inside one
# transaction, verified, and only then SaveAs'd into out\. If verification fails the
# transaction is rolled back and the document closed without saving - so out\ contains only
# verified files, by construction, and the source .rvt is never written to (proved per file
# by comparing its mtime before and after).
#
# Set SAVE = False for a dry run: everything runs and is verified, nothing is written.
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

ROOT = _paths["CEILING_ROOT"]
CORE = os.path.join(ROOT, "origin_ceiling_rebuild_core.py")
OUT_DIR = os.path.join(ROOT, "out")
REPORT_DIR = os.path.join(OUT_DIR, "_reports")

SAVE = True
DELETE_UNMATCHED = True

# Also lay drywall boards, furring and carrying channels onto the new ceilings, using the
# drywall repo's ceiling generator. Since 2026-09-16 that generator staggers courses like the
# wall script (MAXIMIZE_WHOLE_PANELS = False), so ceilings and walls now share one layout logic.
#
# It is exec'd with ORIGIN_TARGET_DOC set to the background document - the generator checks for
# that global and uses it instead of the UI document. It takes its ceilings from IN[0], so no
# selection is needed, and it manages its own transaction through Dynamo's TransactionManager,
# which commits lazily - hence the ForceCloseTransaction either side.
PANELISE = True
GENERATOR = os.path.join(_paths["DRYWALL_REPO"], "origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py")

# Where to look for envs. Set FILES explicitly to override discovery.
INPUT_DIR = _paths["INPUT_DIR"]
MAX_MB = 50.0          # the 148-695 MB models in Downloads are architecture references, not envs
# Set to a list of paths to process exactly those; None = discover everything in INPUT_DIR.
FILES = [os.path.join(_paths["INPUT_DIR"], "B1-a.rvt")]


def discover(folder):
    """Env .rvt files, excluding Revit's numbered auto-backups (name.0001.rvt) and the large
    reference models. Downloads is full of both, and a naive glob would process the same
    building six times."""
    import re
    out = []
    backup = re.compile(r"\.\d{4}\.rvt$", re.IGNORECASE)
    for n in sorted(os.listdir(folder)):
        if not n.lower().endswith(".rvt"):
            continue
        if backup.search(n):
            continue
        p = os.path.join(folder, n)
        try:
            if os.path.getsize(p) / (1024.0 * 1024.0) > MAX_MB:
                continue
        except Exception:
            continue
        out.append(p)
    return out

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

for d in (OUT_DIR, REPORT_DIR):
    if not os.path.exists(d):
        os.makedirs(d)

core = {"__name__": "origin_ceiling_rebuild_core"}
core["__file__"] = CORE
exec(compile(open(CORE).read(), CORE, "exec"), core)

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

targets = FILES if FILES else discover(INPUT_DIR)
rows = []

# --- dialog suppression -------------------------------------------------------------
# FailureHandlingOptions only covers Revit FAILURE messages raised inside a transaction.
# Plain task dialogs - the ones OpenDocumentFile and SaveAs can raise - are not failures, so
# they sail past it and block the batch with nobody at the keyboard to click OK. Twice this
# froze a run at zero CPU. This answers them instead.
dialogs_seen = []


def _on_dialog(sender, args):
    try:
        dialogs_seen.append(str(args.DialogId))
    except Exception:
        dialogs_seen.append("<unknown dialog>")
    try:
        args.OverrideResult(1)          # IDOK / default affirmative
    except Exception:
        pass


dialog_hooked = False
try:
    uiapp.DialogBoxShowing += _on_dialog
    dialog_hooked = True
except Exception:
    pass

for path in targets:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    row = {"file": name, "status": "pending"}
    t0 = time.time()

    if not os.path.exists(path):
        row["status"] = "missing"
        rows.append(row)
        continue
    if stem in open_titles:
        row["status"] = "skipped (open in UI)"
        rows.append(row)
        continue

    nd = None
    t = None
    mtime_before = os.path.getmtime(path)
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(mp, oo)

        t = Transaction(nd, "ORIGIN rebuild per-room ceilings")
        fho = t.GetFailureHandlingOptions()
        try:
            fho.SetForcedModalHandling(False)
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        t.Start()

        report = core["run_on_document"](nd, delete_unmatched=DELETE_UNMATCHED)
        report["source_path"] = path

        rp = os.path.join(REPORT_DIR, stem + "_rebuild.json")
        f = open(rp, "w")
        try:
            json.dump(report, f, indent=2, default=str)
        finally:
            f.close()

        row.update({
            "regions": report.get("regions_total"),
            "rooms_created_to_fill_gaps": report.get("rooms_created_to_fill_gaps"),
            "rooms_remaining": report.get("rooms_remaining"),
            "kept": report.get("plan_summary", {}).get("ceilings_keep"),
            "authored_rooms": report.get("plan_summary", {}).get("regions_authored"),
            "bare_area_sf": report.get("plan_summary", {}).get("bare_area_sf"),
            "deleted": report.get("deleted", {}).get("actually_deleted"),
            "collateral": len(report.get("deleted", {}).get("collateral") or []),
            "created": len(report.get("created") or []),
            "height": report.get("height_by_level"),
            "verify_ok": report.get("verify", {}).get("ok"),
            "failures": report.get("verify", {}).get("failures"),
            "fail_reasons": report.get("fail_reasons"),
            "report": rp,
        })

        if report.get("ok"):
            t.Commit()

            if PANELISE:
                pr = {"generator": os.path.basename(GENERATOR)}
                try:
                    ceilings = list(FilteredElementCollector(nd).OfClass(Ceiling)
                                    .WhereElementIsNotElementType())
                    pr["ceilings_passed_in"] = len(ceilings)

                    def _shapes():
                        n = 0
                        for ds in (FilteredElementCollector(nd).OfClass(DirectShape)
                                   .WhereElementIsNotElementType()):
                            try:
                                if "ORIGIN_CEILING" in (ds.ApplicationId or ""):
                                    n += 1
                            except Exception:
                                continue
                        return n

                    pr["shapes_before"] = _shapes()
                    TransactionManager.Instance.ForceCloseTransaction()
                    gsrc = open(GENERATOR).read()
                    # Panel DIRECTION from this env's own main doorway. Resolved against the
                    # BACKGROUND document (nd), not the UI one - the whole point of this batch
                    # is that each env decides for itself.
                    try:
                        _cd = {"__name__": "ceiling_direction"}
                        _cdp = os.path.join(_paths["PIPELINE_ROOT"], "ceiling_direction.py")
                        _cd["__file__"] = _cdp
                        exec(compile(open(_cdp).read(), _cdp, "exec"), _cd)
                        gsrc, _dinfo = _cd["apply_to_source"](nd, gsrc)
                        pr["direction"] = _dinfo.get("summary")
                        pr["direction_applied"] = _dinfo.get("applied")
                        if _dinfo.get("skipped"):
                            pr["direction_skipped"] = _dinfo["skipped"]
                    except Exception:
                        pr["direction_error"] = traceback.format_exc()[-400:]
                    gns = {
                        "ORIGIN_TARGET_DOC": nd,          # generator honours this over the UI doc
                        "IN": [ceilings] + [None] * 9,
                        "OUT": None,
                        "__name__": "__main__",
                        "__file__": GENERATOR,
                    }
                    exec(compile(gsrc, GENERATOR, "exec"), gns)
                    # TransactionTaskDone does not commit - Dynamo defers that to the end of a
                    # graph run, which never happens here. Force it before SaveAs or the panels
                    # would not be in the saved file.
                    TransactionManager.Instance.ForceCloseTransaction()
                    nd.Regenerate()

                    pr["shapes_after"] = _shapes()
                    pr["shapes_created"] = pr["shapes_after"] - pr["shapes_before"]
                    gout = gns.get("OUT")
                    if isinstance(gout, dict):
                        for k in ("ceilings_processed", "boards_created", "cut_boards",
                                  "furring_created", "mains_created", "splice_joints"):
                            pr[k] = gout.get(k)
                        w = gout.get("warnings") or []
                        pr["warnings"] = w[:5] if isinstance(w, list) else str(w)[:200]
                    pr["ok"] = pr["shapes_created"] > 0
                except Exception:
                    pr["ok"] = False
                    pr["error"] = traceback.format_exc()[-600:]
                    try:
                        TransactionManager.Instance.ForceCloseTransaction()
                    except Exception:
                        pass
                row["panels"] = pr

            if SAVE:
                dst = os.path.join(OUT_DIR, name)
                sao = SaveAsOptions()
                try:
                    sao.OverwriteExistingFile = True
                    sao.Compact = True
                    sao.MaximumBackups = 1
                except Exception:
                    pass
                nd.SaveAs(ModelPathUtils.ConvertUserVisiblePathToModelPath(dst), sao)
                row["saved_to"] = dst
                row["status"] = "ok"
            else:
                row["status"] = "ok (dry run, not saved)"
        else:
            t.RollBack()
            row["status"] = "failed verification - rolled back, not saved"
    except Exception:
        tb = traceback.format_exc()
        # A file saved by a newer Revit cannot be opened by this host. That is a known,
        # decided outcome - quarantine and report it, do not treat it as a crash.
        if "later version of Revit" in tb or "CorruptModelException" in tb:
            row["status"] = "quarantined (saved in a newer Revit)"
            row["note"] = "open in Revit 2027 and re-run there"
        else:
            row["status"] = "error"
            row["error"] = tb
    finally:
        try:
            if t is not None and t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            row["rollback_error"] = traceback.format_exc()
        try:
            if nd is not None:
                nd.Close(False)
        except Exception:
            row["close_error"] = traceback.format_exc()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

    try:
        row["source_unmodified"] = (os.path.getmtime(path) == mtime_before)
    except Exception:
        row["source_unmodified"] = None
    row["sec"] = round(time.time() - t0, 2)
    rows.append(row)

# Always unhook: the bridge re-execs this file every run, and a stacked handler would answer
# each dialog once per registration.
if dialog_hooked:
    try:
        uiapp.DialogBoxShowing -= _on_dialog
    except Exception:
        pass

OUT = {
    "save": SAVE,
    "dialogs_auto_answered": dialogs_seen,
    "input_dir": INPUT_DIR if not FILES else "explicit list",
    "discovered": len(targets),
    "out_dir": OUT_DIR,
    "totals": {
        "ok": len([r for r in rows if str(r.get("status", "")).startswith("ok")]),
        "failed_verification": len([r for r in rows if "failed" in str(r.get("status", ""))]),
        "errors": len([r for r in rows if r.get("status") == "error"]),
        "quarantined": len([r for r in rows if "quarantined" in str(r.get("status", ""))]),
        "skipped": len([r for r in rows if "skipped" in str(r.get("status", ""))]),
    },
    "files": rows,
}
