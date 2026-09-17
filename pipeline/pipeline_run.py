# pipeline_run.py
# ============================================================
# ORIGIN env pipeline - the part that runs INSIDE Revit, driven by the bridge.
#
# Reads _run_config.json (written by pipeline.ps1), then for each env, in ONE background open:
#
#     stage 1  ceilings   origin_ceiling_rebuild_core.run_on_document
#                         -> verified, then SaveAs 01_ceiling_done\<env>.rvt
#     stage 2  panels     stage2_panels.run_on_document
#                         -> SaveAs 02_panels_done\<env>.rvt
#
# Either stage can be run on its own. Stage 2 only ever runs on a document whose stage 1
# verified, so a ceiling failure can never be papered over with drywall.
#
# The source .rvt is never written to; that is asserted per file by comparing its mtime.
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
CONFIG_PATH = os.path.join(ROOT, "_run_config.json")

cfg = json.load(open(CONFIG_PATH))

FILES = cfg.get("files") or []
STAGES = cfg.get("stages") or ["ceiling", "panels"]
SAVE = bool(cfg.get("save", True))
DELETE_UNMATCHED = bool(cfg.get("delete_unmatched", True))
OUT_CEILING = cfg.get("out_ceiling") or os.path.join(ROOT, "01_ceiling_done")
OUT_PANELS = cfg.get("out_panels") or os.path.join(ROOT, "02_panels_done")
REPORT_DIR = cfg.get("reports") or os.path.join(ROOT, "_reports")

for d in (OUT_CEILING, OUT_PANELS, REPORT_DIR):
    if not os.path.exists(d):
        os.makedirs(d)

# --- load the two stage modules fresh from disk, exactly as the bridge loads this file ------
core = {"__name__": "origin_ceiling_rebuild_core"}
core_path = os.path.join(CEILING_ROOT, "origin_ceiling_rebuild_core.py")
core["__file__"] = core_path
exec(compile(open(core_path).read(), core_path, "exec"), core)

stage2 = {"__name__": "stage2_panels"}
stage2_path = os.path.join(ROOT, "stage2_panels.py")
stage2["__file__"] = stage2_path
exec(compile(open(stage2_path).read(), stage2_path, "exec"), stage2)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

# --- dialog suppression ---------------------------------------------------------------------
# Plain task dialogs (the kind OpenDocumentFile and SaveAs raise) are not Revit "failures", so
# FailureHandlingOptions never sees them; unanswered, they freeze the batch at zero CPU with
# nobody at the keyboard. Answer them instead.
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


def _save_as(nd, dst):
    # Belt and braces: a document with any transaction still open refuses to save, with a
    # message ("Unable to close all open transaction phases!") that says nothing about which
    # stage left it open. Each stage closes its own, so this is normally a no-op.
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    sao = SaveAsOptions()
    try:
        sao.OverwriteExistingFile = True
        sao.Compact = True
        sao.MaximumBackups = 1
    except Exception:
        pass
    nd.SaveAs(ModelPathUtils.ConvertUserVisiblePathToModelPath(dst), sao)
    return dst


rows = []

for path in FILES:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    row = {"file": name, "source": path, "status": "pending", "ceiling": None, "panels": None}
    detail = {"file": name, "source": path}
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

        # ---------------- stage 1: ceilings ----------------
        if "ceiling" in STAGES:
            t = Transaction(nd, "ORIGIN rebuild per-room ceilings")
            fho = t.GetFailureHandlingOptions()
            try:
                fho.SetForcedModalHandling(False)
                fho.SetClearAfterRollback(True)
                t.SetFailureHandlingOptions(fho)
            except Exception:
                pass
            t.Start()

            rep = core["run_on_document"](nd, delete_unmatched=DELETE_UNMATCHED)
            rep["source_path"] = path
            detail["ceiling"] = rep

            if rep.get("ok"):
                t.Commit()
                row["ceiling"] = "ok"
                if SAVE:
                    row["ceiling_saved_to"] = _save_as(nd, os.path.join(OUT_CEILING, name))
            else:
                t.RollBack()
                row["ceiling"] = "failed verification"
                row["fail_reasons"] = rep.get("fail_reasons")
                row["status"] = "ceiling failed - rolled back, not saved"
                rows.append(row)
                continue
            t = None

        # ---------------- stage 2: panels ----------------
        # The generators manage their own transactions, so nothing of ours may be open here.
        if "panels" in STAGES:
            try:
                TransactionManager.Instance.ForceCloseTransaction()
            except Exception:
                pass

            mdir = os.path.join(REPORT_DIR, stem + "_manifests")
            if not os.path.exists(mdir):
                os.makedirs(mdir)

            prep = stage2["run_on_document"](nd, manifest_dir=mdir)
            detail["panels"] = prep
            row["counts"] = prep.get("counts")

            gen_fatals = [g for g, v in (prep.get("generators") or {}).items()
                          if isinstance(v, dict) and "FATAL" in v]
            if prep.get("ok"):
                row["panels"] = "ok"
                if SAVE:
                    row["panels_saved_to"] = _save_as(nd, os.path.join(OUT_PANELS, name))
            else:
                row["panels"] = "failed"
                row["panel_fatals"] = gen_fatals
                row["panels_error"] = prep.get("error")
                row["status"] = "panels failed - not saved"
                rows.append(row)
                continue

        row["status"] = "ok" if SAVE else "ok (dry run, not saved)"

    except Exception:
        tb = traceback.format_exc()
        # A file saved by a newer Revit cannot be opened by this host. Known outcome, not a crash.
        if "later version of Revit" in tb or "CorruptModelException" in tb:
            row["status"] = "quarantined (saved in a newer Revit)"
            row["note"] = "open that Revit version and run the pipeline there"
        else:
            row["status"] = "error"
            row["error"] = tb
            detail["error"] = tb
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

    rp = os.path.join(REPORT_DIR, stem + "_pipeline.json")
    try:
        f = open(rp, "w")
        try:
            json.dump(detail, f, indent=2, default=str)
        finally:
            f.close()
        row["report"] = rp
    except Exception:
        pass

    rows.append(row)

# Always unhook - the bridge re-execs this file every run and stacked handlers would answer
# each dialog once per registration.
if dialog_hooked:
    try:
        uiapp.DialogBoxShowing -= _on_dialog
    except Exception:
        pass

OUT = {
    "stages": STAGES,
    "save": SAVE,
    "requested": len(FILES),
    "dialogs_auto_answered": dialogs_seen,
    "out_ceiling": OUT_CEILING,
    "out_panels": OUT_PANELS,
    "totals": {
        "ok": len([r for r in rows if str(r.get("status", "")).startswith("ok")]),
        "ceiling_failed": len([r for r in rows if r.get("ceiling") == "failed verification"]),
        "panels_failed": len([r for r in rows if r.get("panels") == "failed"]),
        "errors": len([r for r in rows if r.get("status") == "error"]),
        "quarantined": len([r for r in rows if "quarantined" in str(r.get("status", ""))]),
        "skipped": len([r for r in rows if "skipped" in str(r.get("status", ""))]),
    },
    "files": rows,
}
