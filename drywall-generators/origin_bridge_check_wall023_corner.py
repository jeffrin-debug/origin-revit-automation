# origin_bridge_check_wall023_corner.py - run via the ORIGIN Bridge. READ-ONLY.
# Wall 023's face-B drywall boundary stops 1.25in short of covering its own end stud
# (ST-023-001) at the P0 end. Checks every OTHER wall whose endpoint lands near wall 023's P0,
# including whether any is COLLINEAR (which would trigger corner_face_extents' collinear-clamp).
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

WALL_EID = 401091
w = doc.GetElement(ElementId(WALL_EID))
curve = w.Location.Curve
p0 = curve.GetEndPoint(0)
p1 = curve.GetEndPoint(1)
d = (p1 - p0).Normalize()
length = p0.DistanceTo(p1)

out = {"p0": [round(p0.X, 4), round(p0.Y, 4)], "p1": [round(p1.X, 4), round(p1.Y, 4)],
       "d": [round(d.X, 4), round(d.Y, 4)], "length": round(length, 4),
       "width_in": round(w.Width * 12.0, 3)}

neighbors = []
tol = 1.0
for other in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    oid = other.Id.Value if hasattr(other.Id, "Value") else other.Id.IntegerValue
    if oid == WALL_EID:
        continue
    try:
        oc = other.Location.Curve
        op0 = oc.GetEndPoint(0)
        op1 = oc.GetEndPoint(1)
    except Exception:
        continue
    od = (op1 - op0).Normalize()
    for (myend, mylabel) in ((p0, "P0"), (p1, "P1")):
        for (oend, olabel) in ((op0, "P0"), (op1, "P1")):
            dist = ((myend.X - oend.X) ** 2 + (myend.Y - oend.Y) ** 2) ** 0.5
            if dist <= tol:
                collinear = abs(d.X * od.X + d.Y * od.Y) > 0.95
                try:
                    mk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                    omark = mk.AsString() if mk else None
                except Exception:
                    omark = None
                neighbors.append({
                    "my_end": mylabel, "other_end": olabel, "gap_ft": round(dist, 4),
                    "other_mark": omark, "other_eid": oid, "collinear": bool(collinear),
                    "other_p0": [round(op0.X, 4), round(op0.Y, 4)],
                    "other_p1": [round(op1.X, 4), round(op1.Y, 4)],
                    "other_width_in": round(other.Width * 12.0, 3),
                })
out["neighbors"] = neighbors

# Also: any wall whose own span is COLLINEAR with wall 023 (regardless of endpoint proximity),
# to check the specific "onear/ofar" clamp logic in corner_face_extents.
collinear_walls = []
for other in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    oid = other.Id.Value if hasattr(other.Id, "Value") else other.Id.IntegerValue
    if oid == WALL_EID:
        continue
    try:
        oc = other.Location.Curve
        op0 = oc.GetEndPoint(0)
        op1 = oc.GetEndPoint(1)
    except Exception:
        continue
    od = (op1 - op0).Normalize()
    if abs(d.X * od.X + d.Y * od.Y) <= 0.95:
        continue
    # project onto wall 023's own local x axis
    lp0 = (op0.X - p0.X) * d.X + (op0.Y - p0.Y) * d.Y
    lp1 = (op1.X - p0.X) * d.X + (op1.Y - p0.Y) * d.Y
    try:
        mk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        omark = mk.AsString() if mk else None
    except Exception:
        omark = None
    collinear_walls.append({
        "other_mark": omark, "other_eid": oid,
        "local_p0": round(lp0, 4), "local_p1": round(lp1, 4),
        "other_p0": [round(op0.X, 4), round(op0.Y, 4)], "other_p1": [round(op1.X, 4), round(op1.Y, 4)],
    })
out["collinear_walls"] = collinear_walls

OUT = out
