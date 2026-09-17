# ceiling_audit_batch.py
# ============================================================
# STAGE 1 - audit sample envs. READ-ONLY: each file is opened as a background document, rooms
# are placed inside a transaction purely to discover the enclosed regions, the reconciliation
# is dry-run, and then the whole transaction is ROLLED BACK and the document closed WITHOUT
# saving. No file on disk is modified.
#
# Full per-file detail goes to out\_reports\<env>.json; OUT stays slim enough to read back.
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
REPORT_DIR = os.path.join(ROOT, "out", "_reports")

FILES = [
    os.path.join(_paths["INPUT_DIR"], "B1-a.rvt"),
    os.path.join(_paths["INPUT_DIR"], "409_Testing.rvt"),
    os.path.join(_paths["INPUT_DIR"], "Project8.rvt"),
    os.path.join(_paths["INPUT_DIR"], "12M_FR_11.rvt"),
    os.path.join(_paths["INPUT_DIR"], "A-1a.rvt"),
]

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)

# Load the core fresh from disk every run - a bare import would be cached in sys.modules
# across bridge ticks and silently run stale code.
core = {"__name__": "origin_ceiling_rebuild_core"}
core["__file__"] = CORE
exec(compile(open(CORE).read(), CORE, "exec"), core)

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

rows = []

for path in FILES:
    row = {"file": os.path.basename(path), "status": "pending"}
    t0 = time.time()

    if not os.path.exists(path):
        row["status"] = "missing"
        rows.append(row)
        continue
    if os.path.splitext(os.path.basename(path))[0] in open_titles:
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

        t = Transaction(nd, "ORIGIN ceiling audit (rolled back)")
        fho = t.GetFailureHandlingOptions()
        try:
            fho.SetForcedModalHandling(False)
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        t.Start()

        report = core["audit_document"](nd)
        report["source_path"] = path

        rp = os.path.join(REPORT_DIR, os.path.splitext(os.path.basename(path))[0] + ".json")
        f = open(rp, "w")
        try:
            json.dump(report, f, indent=2, default=str)
        finally:
            f.close()

        s = report["plan"]["summary"]
        row.update({
            "status": "ok",
            "levels": len(report["levels"]),
            "rooms_pre_existing": report["rooms_pre_existing"],
            "rooms_created_to_fill_gaps": report["rooms_created_to_fill_gaps"],
            "regions": report["regions_total"],
            "ceilings_total": s["ceilings_total"],
            "keep": s["ceilings_keep"],
            "delete": s["ceilings_delete"],
            "create": s["regions_to_create"],
            "ambiguities": s["ambiguities"],
            "has_origin_assembly": report["has_origin_assembly"],
            "per_level": report["per_level"],
            "report": rp,
        })
    except Exception:
        row["status"] = "error"
        row["error"] = traceback.format_exc()
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

    # Prove we did not touch the original.
    try:
        row["source_unmodified"] = (os.path.getmtime(path) == mtime_before)
    except Exception:
        row["source_unmodified"] = None
    row["sec"] = round(time.time() - t0, 2)
    rows.append(row)

OUT = {
    "files": rows,
    "totals": {
        "ok": len([r for r in rows if r.get("status") == "ok"]),
        "not_ok": len([r for r in rows if r.get("status") != "ok"]),
    },
    "report_dir": REPORT_DIR,
}
