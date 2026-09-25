# origin_bridge_check_hidden_cats.py - run via the ORIGIN Bridge. READ-ONLY.
# The "ORIGIN Assembly" view is supposed to hide the real Revit Wall/Ceiling/Door/Window
# categories so only generated Generic Models show. On a BRAND NEW file this view had to be
# freshly created - checks whether that category-hide actually took effect, since an un-hidden
# raw Wall (often no render material) would show as a flat, textureless dark surface - exactly
# matching the user's "black panel, no drywall" report.
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

v = None
for view in FilteredElementCollector(doc).OfClass(View3D):
    if view.Name == "ORIGIN Assembly" and not view.IsTemplate:
        v = view
        break

out = {"view_found": v is not None}
if v is not None:
    check_cats = [BuiltInCategory.OST_Walls, BuiltInCategory.OST_Ceilings, BuiltInCategory.OST_Doors,
                  BuiltInCategory.OST_Windows, BuiltInCategory.OST_Roofs, BuiltInCategory.OST_GenericModel]
    cat_status = {}
    for bic in check_cats:
        try:
            cat = Category.GetCategory(doc, bic)
            if cat is None:
                cat_status[str(bic)] = "category not found in this doc"
                continue
            hidden = v.GetCategoryHidden(cat.Id)
            cat_status[str(bic)] = {"hidden": hidden}
        except Exception as ex:
            cat_status[str(bic)] = "ERR: {}".format(ex)
    out["category_hidden_status"] = cat_status

OUT = out
