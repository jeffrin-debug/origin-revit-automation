# origin_bridge_check_visible_near_023.py - run via the ORIGIN Bridge. READ-ONLY.
# The user's screenshot shows a large diagonal wireframe shape crossing near DP-023-001B in the
# "ORIGIN Assembly" view - too big/wrong-shaped to be the tiny track hairline already fixed. Since
# that view hides every Model category except Generic Models/Electrical Fixtures, this finds any
# element (of ANY category, real Revit or DirectShape) whose bbox is near DP-023-001B AND is not
# actually hidden in that view - plus checks for Model categories where CanCategoryBeHidden
# returned False (so our isolation setup couldn't have hidden them even if it tried).
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

out = {"view_found": view is not None}

target = None
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark == "DP-023-001B":
        target = ds
        break

if target is not None:
    bb = target.get_BoundingBox(None)
    pad = 5.0   # generous - the diagonal shape in the screenshot extends well past the panel
    lo = XYZ(bb.Min.X - pad, bb.Min.Y - pad, bb.Min.Z - pad)
    hi = XYZ(bb.Max.X + pad, bb.Max.Y + pad, bb.Max.Z + pad)
    out["search_bbox"] = {"min": [round(lo.X, 2), round(lo.Y, 2), round(lo.Z, 2)],
                          "max": [round(hi.X, 2), round(hi.Y, 2), round(hi.Z, 2)]}

    outline = Outline(lo, hi)
    bbfilter = BoundingBoxIntersectsFilter(outline)
    nearby = FilteredElementCollector(doc).WherePasses(bbfilter).WhereElementIsNotElementType().ToElements()

    hits = []
    for e in nearby:
        try:
            if e.Id == target.Id:
                continue
        except Exception:
            pass
        try:
            cat = e.Category
            cat_name = cat.Name if cat else None
        except Exception:
            cat_name = None
        try:
            is_hidden = e.IsHidden(view) if view is not None else None
        except Exception:
            is_hidden = "error"
        if view is not None and is_hidden is True:
            continue   # confirmed hidden in this view - not what the user is seeing
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        hits.append({
            "element_id": (int(e.Id.Value) if hasattr(e.Id, "Value") else int(e.Id.IntegerValue)),
            "type": type(e).__name__, "category": cat_name, "mark": mark,
            "is_hidden_in_view": is_hidden,
        })
    out["visible_nearby_elements"] = hits
    out["visible_nearby_count"] = len(hits)
else:
    out["target_not_found"] = True

# Categories that CAN'T be hidden per-view (our isolation setup would have silently skipped these)
if view is not None:
    cant_hide = []
    gm_id = ElementId(BuiltInCategory.OST_GenericModel)
    ef_id = ElementId(BuiltInCategory.OST_ElectricalFixtures)
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != CategoryType.Model or cat.Id == gm_id or cat.Id == ef_id:
                continue
            if not view.CanCategoryBeHidden(cat.Id):
                cant_hide.append(cat.Name)
        except Exception:
            pass
    out["model_categories_that_cannot_be_hidden"] = cant_hide

OUT = out
