# diag_board.py - read-only anatomy of one ORIGIN board, by Mark.
#
# Answers: is the protruding bit part of THIS element's geometry (a tab left by a boolean, or a
# corner wrap), or is it a separate element sitting against it? And if it is part of it, where
# exactly does it stick out and by how much.

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

TARGET_MARK = "DP-016-005B"
NEIGHBOUR_RADIUS_FT = 0.75      # report other ORIGIN elements whose bbox comes this close

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
else:
    res["element_id"] = target.Id.IntegerValue if hasattr(target.Id, "IntegerValue") else target.Id.Value
    res["comments"] = par(target, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)

    opt = Options()
    opt.ComputeReferences = False
    opt.DetailLevel = ViewDetailLevel.Fine

    solids = []
    try:
        for g in target.get_Geometry(opt):
            if isinstance(g, Solid) and g.Volume > 1e-9:
                solids.append(g)
            elif hasattr(g, "GetInstanceGeometry"):
                try:
                    for gg in g.GetInstanceGeometry():
                        if isinstance(gg, Solid) and gg.Volume > 1e-9:
                            solids.append(gg)
                except Exception:
                    pass
    except Exception as ex:
        res["geometry_error"] = str(ex)

    res["solid_count"] = len(solids)
    rows = []
    for s in solids:
        xs = [];  ys = [];  zs = []
        for e in s.Edges:
            for p in (e.AsCurve().GetEndPoint(0), e.AsCurve().GetEndPoint(1)):
                xs.append(p.X); ys.append(p.Y); zs.append(p.Z)
        rows.append({
            "volume_cuft": round(s.Volume, 5),
            "faces": s.Faces.Size,
            "edges": s.Edges.Size,
            "bbox_in": {"dx": IN(max(xs) - min(xs)), "dy": IN(max(ys) - min(ys)),
                        "dz": IN(max(zs) - min(zs))},
            "x_in": [IN(min(xs)), IN(max(xs))],
            "y_in": [IN(min(ys)), IN(max(ys))],
            "z_in": [IN(min(zs)), IN(max(zs))],
        })
    res["solids"] = rows

    # A clean rectangular sheet is a box: 6 faces, 12 edges. More than that means the shape has
    # steps in it - a tab, a notch, or a boolean remainder.
    res["is_plain_box"] = all(r["faces"] == 6 and r["edges"] == 12 for r in rows) if rows else None

    bb = target.get_BoundingBox(None)
    if bb is not None:
        res["element_bbox_in"] = {
            "x": [IN(bb.Min.X), IN(bb.Max.X)],
            "y": [IN(bb.Min.Y), IN(bb.Max.Y)],
            "z": [IN(bb.Min.Z), IN(bb.Max.Z)],
            "dx": IN(bb.Max.X - bb.Min.X), "dy": IN(bb.Max.Y - bb.Min.Y),
            "dz": IN(bb.Max.Z - bb.Min.Z),
        }

        # Anything else of ours sitting right against it.
        near = []
        for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
            if ds.Id == target.Id:
                continue
            m = par(ds, BuiltInParameter.ALL_MODEL_MARK)
            if not m:
                continue
            ob = ds.get_BoundingBox(None)
            if ob is None:
                continue
            r = NEIGHBOUR_RADIUS_FT
            if (ob.Min.X > bb.Max.X + r or ob.Max.X < bb.Min.X - r or
                    ob.Min.Y > bb.Max.Y + r or ob.Max.Y < bb.Min.Y - r or
                    ob.Min.Z > bb.Max.Z + r or ob.Max.Z < bb.Min.Z - r):
                continue
            near.append({
                "mark": m,
                "kind": ("panel" if m.startswith("DP-") else
                         "framing" if m.startswith("ST-") else "other"),
                "corner_infill": "CORNERINFILL=1" in par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS),
                "x": [IN(ob.Min.X), IN(ob.Max.X)],
                "y": [IN(ob.Min.Y), IN(ob.Max.Y)],
                "z": [IN(ob.Min.Z), IN(ob.Max.Z)],
            })
        near.sort(key=lambda r: r["mark"])
        res["neighbours_within_9in"] = near
        res["neighbour_count"] = len(near)

OUT = res
