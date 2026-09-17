# ceiling_rebuild_current_doc.py
# ============================================================
# Rebuild per-room ceilings on the document CURRENTLY OPEN IN THE REVIT UI, so the result is
# visible on screen immediately. Nothing is saved - the change is committed into the open
# session only, and Ctrl+Z in Revit undoes the whole thing in one step.
#
# Use this to eyeball a new env before trusting the batch on it. If verification fails the
# transaction is rolled back, so a bad result never even appears.
#
# DRY_RUN = True  -> classify and report only; the model is not touched at all.
# DRY_RUN = False -> actually delete the blankets and build the missing ceilings.
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

ROOT = r"C:\Users\Origoncad\origin_ceiling_rebuild"
CORE = os.path.join(ROOT, "origin_ceiling_rebuild_core.py")
REPORT_DIR = os.path.join(ROOT, "out", "_reports")

DRY_RUN = False

if not os.path.exists(REPORT_DIR):
    os.makedirs(REPORT_DIR)

core = {"__name__": "origin_ceiling_rebuild_core"}
exec(compile(open(CORE).read(), CORE, "exec"), core)

uiapp = DocumentManager.Instance.CurrentUIApplication
doc = DocumentManager.Instance.CurrentDBDocument

res = {"doc": doc.Title, "path": doc.PathName, "dry_run": DRY_RUN, "saved": False}
t = None
t0 = time.time()

try:
    # Dynamo keeps a transaction open across a graph run; take it over with a raw one so a
    # failed rebuild can be rolled back instead of half-applied.
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

    report = core["run_on_document"](
        doc,
        delete_unmatched=(not DRY_RUN),
        create_missing=(not DRY_RUN),
        remove_temp_rooms=True,
    )

    stem = "".join(ch for ch in doc.Title if ch.isalnum() or ch in "-_ ").strip() or "current"
    rp = os.path.join(REPORT_DIR, stem + "_live.json")
    f = open(rp, "w")
    try:
        json.dump(report, f, indent=2, default=str)
    finally:
        f.close()

    if DRY_RUN:
        t.RollBack()
        res["committed"] = False
    elif report.get("ok"):
        t.Commit()
        res["committed"] = True
    else:
        t.RollBack()
        res["committed"] = False

    res.update({
        "regions": report.get("regions_total"),
        "rooms_created_to_fill_gaps": report.get("rooms_created_to_fill_gaps"),
        "rooms_remaining": report.get("rooms_remaining"),
        "kept": report.get("plan_summary", {}).get("ceilings_keep"),
        "authored_rooms": report.get("plan_summary", {}).get("regions_authored"),
        "bare_area_sf": report.get("plan_summary", {}).get("bare_area_sf"),
        "to_delete": report.get("plan_summary", {}).get("ceilings_delete"),
        "deleted": report.get("deleted", {}).get("actually_deleted"),
        "collateral": len(report.get("deleted", {}).get("collateral") or []),
        "created": len(report.get("created") or []),
        "height": report.get("height_by_level"),
        "ceiling_type": report.get("type_by_level"),
        "verify_ok": report.get("verify", {}).get("ok"),
        "failures": report.get("verify", {}).get("failures"),
        "fail_reasons": report.get("fail_reasons"),
        "ambiguities": report.get("ambiguities"),
        "per_region": report.get("verify", {}).get("per_region"),
        "report": rp,
    })
    res["result"] = ("model changed - look at it now, Ctrl+Z undoes it"
                     if res.get("committed") else
                     ("dry run - model untouched" if DRY_RUN
                      else "verification FAILED - rolled back, model untouched"))
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

res["sec"] = round(time.time() - t0, 2)
OUT = res
