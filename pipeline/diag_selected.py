# diag_selected.py - full anatomy of whatever is SELECTED in Revit right now.
#
# Saves the round-trip of asking for a Mark: the user clicked the offending thing, so read it.
# Reports what it is, its exact solid geometry, and everything touching it, so the shape that
# looks wrong can be identified without guessing from a screenshot.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

TOUCH_IN = 1.0          # "touching" = bboxes within this

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
res = {"doc": doc.Title}


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def IN(v):
    return round(v * 12.0, 2)


try:
    ids = list(uidoc.Selection.GetElementIds())
except Exception as ex:
    ids = []
    res["selection_error"] = str(ex)

res["selected_count"] = len(ids)
if not ids:
    res["hint"] = "nothing selected - click the shape in Revit and re-run"
    OUT = res
else:
    items = []
    for eid in ids:
        e = doc.GetElement(eid)
        if e is None:
            continue
        m = par(e, BuiltInParameter.ALL_MODEL_MARK)
        cm = par(e, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        try:
            cat = e.Category.Name if e.Category is not None else "?"
        except Exception:
            cat = "?"
        row = {"id": eid.IntegerValue if hasattr(eid, "IntegerValue") else eid.Value,
               "mark": m, "category": cat, "class": type(e).__name__,
               "comments": cm[:220],
               "corner_infill": "CORNERINFILL=1" in cm}

        opt = Options()
        opt.ComputeReferences = False
        opt.DetailLevel = ViewDetailLevel.Fine
        sol = []
        try:
            for g in e.get_Geometry(opt):
                if isinstance(g, Solid) and g.Volume > 1e-9:
                    sol.append(g)
        except Exception:
            pass
        row["solid_count"] = len(sol)
        row["solids"] = []
        for s in sol:
            xs = []; ys = []; zs = []
            for ed in s.Edges:
                for p in (ed.AsCurve().GetEndPoint(0), ed.AsCurve().GetEndPoint(1)):
                    xs.append(p.X); ys.append(p.Y); zs.append(p.Z)
            row["solids"].append({
                "volume_cuin": round(s.Volume * 1728.0, 3),
                "faces": s.Faces.Size, "edges": s.Edges.Size,
                "dx_in": IN(max(xs) - min(xs)), "dy_in": IN(max(ys) - min(ys)),
                "dz_in": IN(max(zs) - min(zs)),
                "x": [IN(min(xs)), IN(max(xs))],
                "y": [IN(min(ys)), IN(max(ys))],
                "z": [IN(min(zs)), IN(max(zs))]})

        bb = e.get_BoundingBox(None)
        if bb is not None:
            row["bbox"] = {"x": [IN(bb.Min.X), IN(bb.Max.X)],
                           "y": [IN(bb.Min.Y), IN(bb.Max.Y)],
                           "z": [IN(bb.Min.Z), IN(bb.Max.Z)],
                           "dx": IN(bb.Max.X - bb.Min.X),
                           "dy": IN(bb.Max.Y - bb.Min.Y),
                           "dz": IN(bb.Max.Z - bb.Min.Z)}
            # is it a sliver? which dimension is degenerate
            dims = sorted([row["bbox"]["dx"], row["bbox"]["dy"], row["bbox"]["dz"]])
            row["is_sliver"] = dims[1] < 6.0        # two small dimensions = a shard, not a sheet

            pad = TOUCH_IN / 12.0
            touching = []
            for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
                if ds.Id == eid:
                    continue
                ob = ds.get_BoundingBox(None)
                if ob is None:
                    continue
                if (ob.Min.X > bb.Max.X + pad or ob.Max.X < bb.Min.X - pad or
                        ob.Min.Y > bb.Max.Y + pad or ob.Max.Y < bb.Min.Y - pad or
                        ob.Min.Z > bb.Max.Z + pad or ob.Max.Z < bb.Min.Z - pad):
                    continue
                om = par(ds, BuiltInParameter.ALL_MODEL_MARK)
                touching.append({"mark": om,
                                 "kind": ("panel" if om.startswith("DP-") else
                                          "framing" if om.startswith("ST-") else
                                          "doorframe" if om.startswith("DF-") else "other"),
                                 "x": [IN(ob.Min.X), IN(ob.Max.X)],
                                 "y": [IN(ob.Min.Y), IN(ob.Max.Y)],
                                 "z": [IN(ob.Min.Z), IN(ob.Max.Z)]})
            touching.sort(key=lambda r: r["mark"])
            row["touching"] = touching
            row["touching_count"] = len(touching)
        items.append(row)
    res["selected"] = items
    OUT = res
