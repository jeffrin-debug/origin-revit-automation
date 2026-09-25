# origin_bridge_debug_hide_walls.py - run via the ORIGIN Bridge. TRANSACTION.
# ensure_export_view()'s category-hide loop has a bare "except: pass" around SetCategoryHidden,
# which could be silently swallowing a real failure. Directly calls CanCategoryBeHidden and
# SetCategoryHidden for the Walls category (and Floors, Doors) with full exception detail, to see
# exactly what's happening in this Revit 2027 environment.
import clr
import traceback

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

view = None
for v in FilteredElementCollector(doc).OfClass(View):
    try:
        if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
            view = v
            break
    except Exception:
        pass

out = {"view_found": view is not None}
if view is not None:
    TransactionManager.Instance.EnsureInTransaction(doc)
    results = {}
    for bic_name, bic in [("Walls", BuiltInCategory.OST_Walls),
                          ("Floors", BuiltInCategory.OST_Floors),
                          ("Doors", BuiltInCategory.OST_Doors)]:
        entry = {}
        try:
            cat = doc.Settings.Categories.get_Item(bic)
            entry["category_found"] = cat is not None
            if cat is not None:
                try:
                    entry["can_be_hidden"] = view.CanCategoryBeHidden(cat.Id)
                except Exception:
                    entry["can_be_hidden_error"] = traceback.format_exc()
                try:
                    entry["hidden_before"] = view.GetCategoryHidden(cat.Id)
                except Exception:
                    entry["hidden_before_error"] = traceback.format_exc()
                try:
                    view.SetCategoryHidden(cat.Id, True)
                    entry["set_hidden_call"] = "ok"
                except Exception:
                    entry["set_hidden_error"] = traceback.format_exc()
                try:
                    entry["hidden_after"] = view.GetCategoryHidden(cat.Id)
                except Exception:
                    entry["hidden_after_error"] = traceback.format_exc()
        except Exception:
            entry["outer_error"] = traceback.format_exc()
        results[bic_name] = entry
    TransactionManager.Instance.TransactionTaskDone()
    out["results"] = results

OUT = out
