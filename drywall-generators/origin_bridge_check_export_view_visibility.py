# origin_bridge_check_export_view_visibility.py - run via the ORIGIN Bridge. READ-ONLY.
# The curtain-wall exclusion only stops OUR script from generating drywall on glass walls - it
# never touches the real Wall elements themselves. Whether they show up in an OBJ/Omniverse
# export depends entirely on whether the "ORIGIN Assembly" export view actually displays the
# Walls category (and curtain-specific subcategories) or hides it to isolate just the generated
# content. Checks that view's real visibility settings plus the curtain walls' own hidden state.
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

out = {}

view = None
for v in FilteredElementCollector(doc).OfClass(View):
    try:
        if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
            view = v
            break
    except Exception:
        pass

out["view_found"] = view is not None
if view is None:
    OUT = out
else:
    out["view_id"] = int(view.Id.Value) if hasattr(view.Id, "Value") else int(view.Id.IntegerValue)
    out["view_type"] = str(view.ViewType)

    cats_to_check = [
        ("Walls", BuiltInCategory.OST_Walls),
        ("Curtain Wall Mullions", BuiltInCategory.OST_CurtainWallMullions),
        ("Curtain Wall Panels", BuiltInCategory.OST_CurtainWallPanels),
        ("Generic Models", BuiltInCategory.OST_GenericModel),
    ]
    cat_vis = {}
    for name, bic in cats_to_check:
        try:
            cat = doc.Settings.Categories.get_Item(bic)
            hidden = view.GetCategoryHidden(cat.Id)
            cat_vis[name] = {"hidden_in_view": hidden}
        except Exception as ex:
            cat_vis[name] = {"error": str(ex)}
    out["category_visibility"] = cat_vis

    for eid in (373548, 373575):
        e = doc.GetElement(ElementId(eid))
        entry = {}
        try:
            entry["element_hidden_in_view"] = e.IsHidden(view)
        except Exception as ex:
            entry["element_hidden_in_view_error"] = str(ex)
        try:
            entry["is_visible_in_all_views"] = e.get_Parameter(BuiltInParameter.VIEW_VISIBLE).AsInteger() if e.get_Parameter(BuiltInParameter.VIEW_VISIBLE) else None
        except Exception:
            pass
        out["wall_{}".format(eid)] = entry

    try:
        out["view_default_hidden_categories"] = "n/a (checked per-category above)"
    except Exception:
        pass

    OUT = out
