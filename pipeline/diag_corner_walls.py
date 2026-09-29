# diag_corner_walls.py - read-only: the Revit walls meeting at wall 004's west end (C9 corner
# with wall 002), their location lines, widths, and every wall whose line passes near that corner.
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
PX, PY = -448.4 / 12.0, 424.0 / 12.0
R = 30.0 / 12.0
out = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        c = w.Location.Curve
    except Exception:
        continue
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    def dist(p):
        return ((p.X - PX) ** 2 + (p.Y - PY) ** 2) ** 0.5
    near = min(dist(p0), dist(p1))
    try:
        near = min(near, c.Distance(XYZ(PX, PY, p0.Z)))
    except Exception:
        pass
    if near > R:
        continue
    o = w.Orientation
    out.append({"id": w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value,
                "type": w.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM).AsValueString(), "width_in": round(w.Width * 12, 3),
                "p0": [round(p0.X * 12, 2), round(p0.Y * 12, 2)],
                "p1": [round(p1.X * 12, 2), round(p1.Y * 12, 2)],
                "orient": [round(o.X, 3), round(o.Y, 3)],
                "near_in": round(near * 12, 2)})
OUT = {"walls": out}
