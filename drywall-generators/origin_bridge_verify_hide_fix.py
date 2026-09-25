# origin_bridge_verify_hide_fix.py - run via the ORIGIN Bridge. READ-ONLY.
# Direct re-check of the specific elements found visible before the category-discovery fix:
# the 4 real walls, and the Roof Soffits ceiling (406965), to confirm the fix actually applies now.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

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

TARGETS = [374947, 376531, 377065, 401091, 406965]

out = {"view_found": view is not None}
if view is not None:
    try:
        cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_RoofSoffit)
        out["roof_soffits_category_hidden"] = view.GetCategoryHidden(cat.Id) if cat else None
    except Exception as ex:
        out["roof_soffits_category_error"] = str(ex)

    results = {}
    for eid in TARGETS:
        e = doc.GetElement(ElementId(eid))
        try:
            results[eid] = e.IsHidden(view) if e else "not found"
        except Exception as ex:
            results[eid] = "error: {}".format(ex)
    out["elements_is_hidden"] = results

OUT = out
