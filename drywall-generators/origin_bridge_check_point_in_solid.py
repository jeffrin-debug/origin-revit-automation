# origin_bridge_check_point_in_solid.py - run via the ORIGIN Bridge. READ-ONLY.
# The 8 pairs from the wall run's "boolean probe failed" warnings error out on Intersect, Union,
# AND Intersect-after-shrink alike - pointing at a genuinely degenerate solid (a tiny sliver
# fragment) rather than mere face coincidence. Sidestep the solid-solid boolean engine entirely:
# for each pair, test whether the SMALLER solid's centroid point actually lies inside the larger
# solid, using Solid.IntersectWithCurve (curve-vs-solid, a different/more robust code path) with a
# ray cast straight up from the point. If the ray's first inside-segment starts exactly at the
# point, the point is inside the solid - real overlap. If not, they're at most touching.
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


def solids_of(e):
    out = []
    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    out.append(g2)
    return out


def find_by_mark(mark):
    for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = mk.AsString() if mk else None
        except Exception:
            m = None
        if m == mark:
            return e
    return None


def bbox_center(solid):
    bb = solid.GetBoundingBox()
    local = XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)
    return bb.Transform.OfPoint(local)


def point_in_solid(solid, pt, length=500.0):
    far = XYZ(pt.X, pt.Y, pt.Z + length)
    try:
        line = Line.CreateBound(pt, far)
    except Exception as ex:
        return ("error", str(ex).splitlines()[0])
    opts = SolidCurveIntersectionOptions()
    try:
        sci = solid.IntersectWithCurve(line, opts)
    except Exception as ex:
        return ("error", str(ex).splitlines()[0])
    if sci is None or sci.SegmentCount == 0:
        return (False, None)
    seg0 = sci.GetCurveSegment(0)
    p0 = seg0.GetEndPoint(0)
    return (p0.DistanceTo(pt) < 1e-6, round(p0.DistanceTo(pt), 6))


PAIRS = [
    ("DP-004-001B", "ST-028-003"),
    ("DP-004-004B", "ST-028-004"),
    ("DP-014-001A", "ST-049-003"),
    ("DP-014-003A", "ST-049-004"),
    ("DP-044-001B", "ST-046-003"),
    ("DP-044-003B", "ST-046-004"),
    ("DP-028-001A", "DP-004-001B"),
    ("DP-046-001A", "DP-044-001B"),
]

results = []
for m1, m2 in PAIRS:
    e1 = find_by_mark(m1)
    e2 = find_by_mark(m2)
    rec = {"a": m1, "b": m2}
    if e1 is None or e2 is None:
        rec["error"] = "not found"
        results.append(rec)
        continue
    s1 = solids_of(e1)
    s2 = solids_of(e2)
    vol1 = sum(s.Volume for s in s1)
    vol2 = sum(s.Volume for s in s2)
    # smaller solid's centroid tested against the larger solid
    if vol2 <= vol1:
        small_solids, small_mark, big_solids, big_mark = s2, m2, s1, m1
    else:
        small_solids, small_mark, big_solids, big_mark = s1, m1, s2, m2
    tests = []
    for ssm in small_solids:
        c = bbox_center(ssm)
        for bsol in big_solids:
            res, extra = point_in_solid(bsol, c)
            tests.append({"centroid_of": small_mark, "tested_in": big_mark,
                          "point": [round(c.X, 4), round(c.Y, 4), round(c.Z, 4)],
                          "inside": res, "detail": extra})
    rec["vol_a"] = round(vol1, 6)
    rec["vol_b"] = round(vol2, 6)
    rec["tests"] = tests
    results.append(rec)

OUT = {"results": results}
