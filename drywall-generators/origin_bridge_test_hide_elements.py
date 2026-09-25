# origin_bridge_test_hide_elements.py - run via the ORIGIN Bridge. TRANSACTION.
# Tests whether view.HideElements() can force-hide specific real walls that are individually
# unhidden despite their category being hidden at the view level - confirms the fix approach
# before committing it to the shared ensure_export_view() functions.
import clr
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List as NetList

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

view = None
for v in FilteredElementCollector(doc).OfClass(View):
    try:
        if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
            view = v
            break
    except Exception:
        pass

TARGET_EIDS = [374947, 376531, 377065, 401091]

out = {"view_found": view is not None}
if view is not None:
    before = {}
    for eid in TARGET_EIDS:
        e = doc.GetElement(ElementId(eid))
        try:
            before[eid] = e.IsHidden(view) if e else None
        except Exception:
            before[eid] = "error"
    out["before"] = before

    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        ids = NetList[ElementId]()
        for eid in TARGET_EIDS:
            e = doc.GetElement(ElementId(eid))
            if e is not None and e.CanBeHidden(view):
                ids.Add(e.Id)
        out["hideable_count"] = ids.Count
        if ids.Count > 0:
            view.HideElements(ids)
            out["hide_call"] = "ok"
    except Exception:
        out["hide_error"] = traceback.format_exc()
    TransactionManager.Instance.TransactionTaskDone()

    try:
        doc.Regenerate()
    except Exception:
        pass

    after = {}
    for eid in TARGET_EIDS:
        e = doc.GetElement(ElementId(eid))
        try:
            after[eid] = e.IsHidden(view) if e else None
        except Exception:
            after[eid] = "error"
    out["after"] = after

OUT = out
