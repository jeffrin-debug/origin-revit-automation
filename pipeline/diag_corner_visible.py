# diag_corner_visible.py - what is ACTUALLY VISIBLE at one corner, per view.
#
# FilteredElementCollector(doc, view.Id) returns only what that view shows, so this settles what
# the protruding shape is rather than inferring it from the model. Runs over every ORIGIN 3D
# view and reports everything visible inside a box around the target board.

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

TARGET_MARK = "DP-009-002B"
PAD_FT = 0.5            # look this far beyond the board's own bbox

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "target": TARGET_MARK}


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def IN(v):
    return round(v * 12.0, 2)


target = None
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    if par(ds, BuiltInParameter.ALL_MODEL_MARK) == TARGET_MARK:
        target = ds
        break

if target is None:
    res["error"] = "mark not found"
    OUT = res
else:
    tb = target.get_BoundingBox(None)
    res["board_bbox_in"] = {"x": [IN(tb.Min.X), IN(tb.Max.X)],
                            "y": [IN(tb.Min.Y), IN(tb.Max.Y)],
                            "z": [IN(tb.Min.Z), IN(tb.Max.Z)]}

    lo = XYZ(tb.Min.X - PAD_FT, tb.Min.Y - PAD_FT, tb.Min.Z - PAD_FT)
    hi = XYZ(tb.Max.X + PAD_FT, tb.Max.Y + PAD_FT, tb.Max.Z + PAD_FT)
    outline = Outline(lo, hi)
    bbfilter = BoundingBoxIntersectsFilter(outline)

    views = []
    for v in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if not v.IsTemplate:
                views.append(v)
        except Exception:
            continue

    per_view = {}
    for v in views:
        rows = []
        try:
            for e in FilteredElementCollector(doc, v.Id).WherePasses(bbfilter):
                try:
                    if e.Id == target.Id:
                        continue
                    cat = e.Category.Name if e.Category is not None else "?"
                except Exception:
                    cat = "?"
                m = par(e, BuiltInParameter.ALL_MODEL_MARK)
                try:
                    ob = e.get_BoundingBox(v)
                    if ob is None:
                        ob = e.get_BoundingBox(None)
                except Exception:
                    ob = None
                row = {"id": e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value,
                       "mark": m, "category": cat,
                       "class": type(e).__name__}
                if ob is not None:
                    row["x"] = [IN(ob.Min.X), IN(ob.Max.X)]
                    row["y"] = [IN(ob.Min.Y), IN(ob.Max.Y)]
                    row["z"] = [IN(ob.Min.Z), IN(ob.Max.Z)]
                    # does it stick out past the board on the +X side (the right edge)?
                    row["past_right_edge_in"] = round((ob.Max.X - tb.Max.X) * 12.0, 2)
                    # does it cross the board's own 0.5 in thickness?
                    row["crosses_board_plane"] = (ob.Min.Y < tb.Max.Y - 1e-9
                                                  and ob.Max.Y > tb.Min.Y + 1e-9)
                if "CORNERINFILL=1" in par(e, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS):
                    row["corner_infill"] = True
                rows.append(row)
        except Exception as ex:
            per_view[v.Name] = {"error": str(ex)}
            continue
        rows.sort(key=lambda r: (r.get("mark") or "zz", r["id"]))
        per_view[v.Name] = {
            "visible_count": len(rows),
            "framing_visible": [r for r in rows if (r.get("mark") or "").startswith("ST-")],
            "panels_visible": [r for r in rows if (r.get("mark") or "").startswith("DP-")],
            "other_visible": [r for r in rows if not (r.get("mark") or "").startswith(("ST-", "DP-"))],
        }
    res["per_view"] = per_view
    OUT = res
