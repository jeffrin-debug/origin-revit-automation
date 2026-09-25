# origin_bridge_cleanup_stale_soffit.py - run via the ORIGIN Bridge. TRANSACTION (when DRY_RUN=False).
# Ceiling 396998 (the mismodeled "Roof Soffit" element) was deleted and recreated as a real
# Ceiling; the separate soffit script confirmed "No ceilings found" on its next run (0 soffits
# left in the model). Its OWN previous output (DP-S001-*/ST-S001-* DirectShapes, tied to the now-
# deleted host) was never cleaned up because that run exited before reaching delete_previous.
# These stale elements now physically overlap the new ceiling's boards covering the same space.
# DRY_RUN=True only reports what would be deleted; set False to actually delete.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

DRY_RUN = False

targets = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark and ("-S001-" in mark or mark.startswith("ST-S001-") or mark.startswith("DP-S001-")):
        targets.append((ds.Id, mark))
targets.sort(key=lambda t: t[1])

result = {"dry_run": DRY_RUN, "count": len(targets), "marks": [m for (_, m) in targets]}

if not DRY_RUN:
    TransactionManager.Instance.EnsureInTransaction(doc)
    deleted = 0
    try:
        for (eid, mark) in targets:
            try:
                doc.Delete(eid)
                deleted += 1
            except Exception:
                pass
    finally:
        TransactionManager.Instance.TransactionTaskDone()
    result["deleted"] = deleted

OUT = result
