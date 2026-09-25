# origin_bridge_debug_soffit_sketch_hide.py - run via the ORIGIN Bridge. TRANSACTION.
# Element 406965 (Ceiling, category "Roof Soffits") and several ModelLine/<Sketch> elements
# remain visible in "ORIGIN Assembly" despite the force-hide fix. Checks CanBeHidden(),
# the category's own CategoryType/CanCategoryBeHidden, and tries HideElements() directly with
# full exception detail to see exactly what's blocking them.
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

TARGETS = [406965, 392331, 392399]

out = {"view_found": view is not None}
if view is not None:
    details = {}
    for eid in TARGETS:
        e = doc.GetElement(ElementId(eid))
        entry = {"exists": e is not None}
        if e is not None:
            entry["type"] = type(e).__name__
            try:
                cat = e.Category
                entry["category_name"] = cat.Name if cat else None
                entry["category_type"] = str(cat.CategoryType) if cat else None
                try:
                    entry["can_category_be_hidden"] = view.CanCategoryBeHidden(cat.Id) if cat else None
                    entry["category_hidden"] = view.GetCategoryHidden(cat.Id) if cat else None
                except Exception:
                    entry["category_check_error"] = traceback.format_exc()
            except Exception:
                entry["category_error"] = traceback.format_exc()
            try:
                entry["can_be_hidden"] = e.CanBeHidden(view)
            except Exception:
                entry["can_be_hidden_error"] = traceback.format_exc()
            try:
                entry["is_hidden_before"] = e.IsHidden(view)
            except Exception:
                entry["is_hidden_before_error"] = traceback.format_exc()
        details[eid] = entry
    out["before"] = details

    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        ids = NetList[ElementId]()
        for eid in TARGETS:
            ids.Add(ElementId(eid))
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
    for eid in TARGETS:
        e = doc.GetElement(ElementId(eid))
        try:
            after[eid] = e.IsHidden(view) if e else None
        except Exception:
            after[eid] = "error"
    out["after"] = after

OUT = out
