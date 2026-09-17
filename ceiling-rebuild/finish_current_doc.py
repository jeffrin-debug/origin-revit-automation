# finish_current_doc.py
# ============================================================
# Finish the model open in the Revit UI: re-run the rebuild (idempotent - rooms that already
# have a correct ceiling are simply kept), verify it, and only then SaveAs into out\.
#
# The rebuild is re-run rather than trusting whatever is already in the session, so the file
# written to disk carries the same guarantee as every batch output: it passed all checks in
# the same transaction that produced it.
#
# NOTE: SaveAs switches the open Revit session to the new file in out\. The original in its
# source folder is left exactly as it was - that is the point - but after this runs, the
# document you are looking at IS the out\ copy.
# ============================================================

import clr
import json
import os
import time
import traceback

clr.AddReference('RevitAPI')
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

for d in (OUT_DIR, REPORT_DIR):
    if not os.path.exists(d):
        os.makedirs(d)

core = {"__name__": "origin_ceiling_rebuild_core"}
core["__file__"] = CORE
exec(compile(open(CORE).read(), CORE, "exec"), core)

doc = DocumentManager.Instance.CurrentDBDocument
src = doc.PathName
res = {"doc": doc.Title, "source_path": src, "saved": False}

mtime_before = None
try:
    if src and os.path.exists(src):
        mtime_before = os.path.getmtime(src)
except Exception:
    pass

t = None
t0 = time.time()
try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, "ORIGIN rebuild per-room ceilings")
    fho = t.GetFailureHandlingOptions()
    try:
        fho.SetForcedModalHandling(False)
        fho.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    t.Start()

    report = core["run_on_document"](doc)

    stem = "".join(ch for ch in doc.Title if ch.isalnum() or ch in "-_ ").strip() or "current"
    rp = os.path.join(REPORT_DIR, stem + "_final.json")
    f = open(rp, "w")
    try:
        json.dump(report, f, indent=2, default=str)
    finally:
        f.close()

    res.update({
        "regions": report.get("regions_total"),
        "kept": report.get("plan_summary", {}).get("ceilings_keep"),
        "created": len(report.get("created") or []),
        "deleted": report.get("deleted", {}).get("actually_deleted"),
        "height": report.get("height_by_level"),
        "verify_ok": report.get("verify", {}).get("ok"),
        "failures": report.get("verify", {}).get("failures"),
        "rooms_remaining": report.get("rooms_remaining"),
        "report": rp,
        "per_region": report.get("verify", {}).get("per_region"),
    })

    if report.get("ok"):
        t.Commit()
        dst = os.path.join(OUT_DIR, (os.path.basename(src) if src else doc.Title + ".rvt"))
        sao = SaveAsOptions()
        try:
            sao.OverwriteExistingFile = True
            sao.Compact = True
            sao.MaximumBackups = 1
        except Exception:
            pass
        doc.SaveAs(ModelPathUtils.ConvertUserVisiblePathToModelPath(dst), sao)
        res["saved"] = True
        res["saved_to"] = dst
        res["status"] = "ok - verified and saved"
    else:
        t.RollBack()
        res["status"] = "verification FAILED - rolled back, not saved"
except Exception:
    res["error"] = traceback.format_exc()
    try:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
    except Exception:
        pass
finally:
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

# Prove the original was not written to.
try:
    if mtime_before is not None and os.path.exists(src):
        res["source_unmodified"] = (os.path.getmtime(src) == mtime_before)
except Exception:
    res["source_unmodified"] = None

res["sec"] = round(time.time() - t0, 2)
OUT = res
