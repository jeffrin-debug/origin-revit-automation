# origin_bridge_check_visible_multi.py - run via the ORIGIN Bridge. READ-ONLY.
# Checks EVERY currently-selected DirectShape's surroundings for real (non-DirectShape) elements
# that are NOT actually hidden in the "ORIGIN Assembly" view, to see whether the per-element
# force-hide fix left any gaps across multiple hosts (001, 003, 023), not just the one already
# re-checked.
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

ids = list(uidoc.Selection.GetElementIds())
selected = [doc.GetElement(eid) for eid in ids]
selected = [e for e in selected if e is not None]

if not selected:
    out["no_selection"] = True
else:
    lo = None
    hi = None
    for e in selected:
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        if lo is None:
            lo = XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z)
            hi = XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z)
        else:
            lo = XYZ(min(lo.X, bb.Min.X), min(lo.Y, bb.Min.Y), min(lo.Z, bb.Min.Z))
            hi = XYZ(max(hi.X, bb.Max.X), max(hi.Y, bb.Max.Y), max(hi.Z, bb.Max.Z))
    pad = 5.0
    lo = XYZ(lo.X - pad, lo.Y - pad, lo.Z - pad)
    hi = XYZ(hi.X + pad, hi.Y + pad, hi.Z + pad)
    out["search_bbox"] = {"min": [round(lo.X, 2), round(lo.Y, 2), round(lo.Z, 2)],
                          "max": [round(hi.X, 2), round(hi.Y, 2), round(hi.Z, 2)]}

    outline = Outline(lo, hi)
    bbfilter = BoundingBoxIntersectsFilter(outline)
    nearby = FilteredElementCollector(doc).WherePasses(bbfilter).WhereElementIsNotElementType().ToElements()

    selected_ids = set((e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue) for e in selected)

    hits = []
    for e in nearby:
        try:
            eid_val = e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue
        except Exception:
            eid_val = None
        if eid_val in selected_ids:
            continue
        try:
            cat = e.Category
            cat_name = cat.Name if cat else None
        except Exception:
            cat_name = None
        if cat_name in ("Generic Models", "Electrical Fixtures", None):
            continue
        try:
            is_hidden = e.IsHidden(view) if view is not None else None
        except Exception:
            is_hidden = "error"
        if is_hidden is True:
            continue
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        hits.append({
            "element_id": eid_val, "type": type(e).__name__, "category": cat_name,
            "mark": mark, "is_hidden_in_view": is_hidden,
        })
    out["still_visible_non_generic"] = hits
    out["still_visible_count"] = len(hits)

OUT = out
