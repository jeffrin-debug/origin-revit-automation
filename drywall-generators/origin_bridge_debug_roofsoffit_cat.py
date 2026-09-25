# origin_bridge_debug_roofsoffit_cat.py - run via the ORIGIN Bridge. TRANSACTION.
# ensure_export_view()'s category loop should have hidden "Roof Soffits" (CategoryType.Model,
# CanCategoryBeHidden=True) but GetCategoryHidden came back False. Iterates doc.Settings.Categories
# exactly like that loop does, with full exception detail (no swallowing), to see whether
# "Roof Soffits" even appears in that enumeration and what SetCategoryHidden actually does.
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
    found_in_enum = False
    enum_error = None
    match_entry = None
    try:
        for cat in doc.Settings.Categories:
            try:
                nm = cat.Name
            except Exception:
                nm = None
            if nm == "Roof Soffits":
                found_in_enum = True
                entry = {"name": nm}
                try:
                    entry["category_type"] = str(cat.CategoryType)
                except Exception:
                    entry["category_type_error"] = traceback.format_exc()
                try:
                    entry["id"] = int(cat.Id.Value) if hasattr(cat.Id, "Value") else int(cat.Id.IntegerValue)
                except Exception:
                    pass
                match_entry = entry
    except Exception:
        enum_error = traceback.format_exc()
    out["found_in_doc_settings_categories"] = found_in_enum
    out["enum_error"] = enum_error
    out["match_entry"] = match_entry

    # Now try the direct BuiltInCategory lookup + hide, with full exception detail.
    direct = {}
    try:
        cat2 = doc.Settings.Categories.get_Item(BuiltInCategory.OST_RoofSoffit)
        direct["get_item_ok"] = cat2 is not None
        if cat2 is not None:
            direct["name"] = cat2.Name
            direct["category_type"] = str(cat2.CategoryType)
            try:
                direct["can_be_hidden"] = view.CanCategoryBeHidden(cat2.Id)
            except Exception:
                direct["can_be_hidden_error"] = traceback.format_exc()
            TransactionManager.Instance.EnsureInTransaction(doc)
            try:
                view.SetCategoryHidden(cat2.Id, True)
                direct["set_hidden_call"] = "ok"
            except Exception:
                direct["set_hidden_error"] = traceback.format_exc()
            TransactionManager.Instance.TransactionTaskDone()
            try:
                direct["hidden_after"] = view.GetCategoryHidden(cat2.Id)
            except Exception:
                direct["hidden_after_error"] = traceback.format_exc()
    except Exception:
        direct["outer_error"] = traceback.format_exc()
    out["direct_builtincategory_lookup"] = direct

OUT = out
