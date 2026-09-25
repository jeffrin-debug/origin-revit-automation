# origin_bridge_check_ceiling_outline.py - run via the ORIGIN Bridge. READ-ONLY.
# Extracts the soffit Ceiling element's OWN real boundary polygon (bottom face loops) directly via
# the Revit API, and tests whether the "missing" region (X:[-33.6883,-27.6883], Y:[15.7901,
# 17.7901]) actually falls inside it - if the real Ceiling sketch doesn't cover that area at all,
# no wall-clip logic could ever produce drywall there; this would mean the gap is a modeling
# characteristic, not a script bug.
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

CEILING_EID = 516965
TEST_POINTS = [
    (-30.0, 16.5),   # inside the "missing" rectangle
    (-30.0, 14.0),   # inside a known-covered board (DP-S001-006)
    (-30.0, 19.0),   # inside a known-covered board (DP-S001-003)
]

ceiling = doc.GetElement(ElementId(CEILING_EID))
out = {"ceiling_found": ceiling is not None}

if ceiling is not None:
    opt = Options()
    opt.ComputeReferences = False
    geo = ceiling.get_Geometry(opt)
    loops_found = []
    if geo is not None:
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                for face in g.Faces:
                    try:
                        n = face.ComputeNormal(UV(0.5, 0.5))
                    except Exception:
                        continue
                    if n.Z > -0.9:   # only the downward-facing (bottom) face
                        continue
                    for loop in face.GetEdgesAsCurveLoops():
                        pts = []
                        for c in loop:
                            pts.append((round(c.GetEndPoint(0).X, 4), round(c.GetEndPoint(0).Y, 4)))
                        loops_found.append(pts)
    out["bottom_face_loops"] = loops_found

    def point_in_poly(px, py, poly):
        inside = False
        n = len(poly)
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    test_results = []
    for (tx, ty) in TEST_POINTS:
        in_any = False
        for loop in loops_found:
            if point_in_poly(tx, ty, loop):
                in_any = True
                break
        test_results.append({"point": [tx, ty], "inside_ceiling_outline": in_any})
    out["test_points"] = test_results

    try:
        bb = ceiling.get_BoundingBox(None)
        out["ceiling_bbox"] = {"min": [round(bb.Min.X,4), round(bb.Min.Y,4), round(bb.Min.Z,4)],
                                "max": [round(bb.Max.X,4), round(bb.Max.Y,4), round(bb.Max.Z,4)]}
    except Exception:
        pass

OUT = out
