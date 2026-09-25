# origin_bridge_check_s001_003_004_context.py - run via the ORIGIN Bridge. READ-ONLY.
# DP-S001-003 (X:[-49.77,-46.02]) and DP-S001-004 (X:[-50.02,-46.02]) share a Y-seam at 12.0284
# but differ in X-extent by 0.25ft, and 004 has 8 faces (notched) vs 003's clean 6. Checks nearby
# real walls and the soffit's own furring/studs in this exact zone to find the real cause.
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

# Region of interest around both boards, generously padded.
RX0, RX1 = -51.0, -45.0
RY0, RY1 = 9.0, 16.5

walls_near = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
    except Exception:
        continue
    if (max(p0.X, p1.X) < RX0 or min(p0.X, p1.X) > RX1 or
            max(p0.Y, p1.Y) < RY0 or min(p0.Y, p1.Y) > RY1):
        continue
    try:
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    walls_near.append({
        "mark": mark, "eid": w.Id.Value if hasattr(w.Id, "Value") else w.Id.IntegerValue,
        "p0": [round(p0.X, 4), round(p0.Y, 4)], "p1": [round(p1.X, 4), round(p1.Y, 4)],
        "width_in": round(w.Width * 12.0, 3),
    })

# Studs/furring belonging to CEILING=C406965 near this region.
studs_near = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "CEILING=C406965" not in comments:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("ST-"):
        continue
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    if (bb.Max.X < RX0 or bb.Min.X > RX1 or bb.Max.Y < RY0 or bb.Min.Y > RY1):
        continue
    studs_near.append({
        "mark": mark, "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)],
        "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)],
    })

OUT = {"walls_near": walls_near, "studs_near": studs_near}
