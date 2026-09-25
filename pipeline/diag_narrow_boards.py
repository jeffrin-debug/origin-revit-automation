# diag_narrow_boards.py - read-only: wall and ceiling boards narrower than 16 in along their run.
#
# Walls: width measured along the host wall. Ceilings: width along the sheet's long axis (X when
# the courses step in Y, which is how the ceiling generator lays them in 1F) - a narrow ripped
# COURSE (the other axis) is not an end-joint issue and is reported separately. Corner-infill
# strips and soffit undersides are excluded - they are narrow by design.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
MIN_IN = 16.0


def par(e, b):
    p = e.get_Parameter(b)
    return (p.AsString() or "") if p else ""


walls = {}
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        c = w.Location.Curve
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        walls["W{}".format(w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value)] = (
            p0, XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize(), par(w, BuiltInParameter.ALL_MODEL_MARK))
    except Exception:
        pass

wall_rows, ceil_rows, ceil_course = [], [], []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    cm = par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if "| DRYWALL |" not in cm or "CORNERINFILL=1" in cm or "SOFFIT_UNDERSIDE" in cm:
        continue
    bb = ds.get_BoundingBox(None)
    mk = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if cm.startswith("ORIGIN_ASSEMBLY_V4"):
        h = [t.strip()[5:] for t in cm.split("|") if t.strip().startswith("WALL=")]
        if not h or h[0] not in walls:
            continue
        p0, u, wm = walls[h[0]]
        a = [XYZ(x, y, 0).Subtract(XYZ(p0.X, p0.Y, 0)).DotProduct(u)
             for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        wid = (max(a) - min(a)) * 12.0
        if wid < MIN_IN:
            wall_rows.append({"board": mk, "wall": wm, "width_in": round(wid, 2),
                              "z_in": [round(bb.Min.Z * 12, 1), round(bb.Max.Z * 12, 1)]})
    elif cm.startswith("ORIGIN_CEILING_V1"):
        dx, dy = (bb.Max.X - bb.Min.X) * 12.0, (bb.Max.Y - bb.Min.Y) * 12.0
        if dx < MIN_IN:
            ceil_rows.append({"board": mk, "along_in": round(dx, 2), "course_in": round(dy, 2),
                              "x_in": [round(bb.Min.X * 12, 2), round(bb.Max.X * 12, 2)],
                              "y_in": [round(bb.Min.Y * 12, 2), round(bb.Max.Y * 12, 2)]})
        elif dy < MIN_IN:
            ceil_course.append({"board": mk, "course_in": round(dy, 2)})
OUT = {"wall_boards_under_16in": sorted(wall_rows, key=lambda r: r["width_in"]),
       "ceiling_boards_under_16in_along": ceil_rows,
       "ceiling_narrow_courses": ceil_course}
