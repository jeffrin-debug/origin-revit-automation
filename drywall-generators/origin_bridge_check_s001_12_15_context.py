# origin_bridge_check_s001_12_15_context.py - run via the ORIGIN Bridge. READ-ONLY.
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

RX0, RX1 = -31.5, -25.5
RY0, RY1 = 0.5, 11.0

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
    try:
        is_curtain = w.WallType.Kind == WallKind.Curtain
    except Exception:
        is_curtain = None
    wbb = w.get_BoundingBox(None)
    walls_near.append({
        "mark": mark, "eid": w.Id.Value if hasattr(w.Id, "Value") else w.Id.IntegerValue,
        "p0": [round(p0.X, 4), round(p0.Y, 4)], "p1": [round(p1.X, 4), round(p1.Y, 4)],
        "width_in": round(w.Width * 12.0, 3), "is_curtain": is_curtain,
        "z": [round(wbb.Min.Z, 3), round(wbb.Max.Z, 3)] if wbb else None,
    })

# Also check for fixtures/openings and column/beam footprints that might explain the notch.
fixtures_near = []
for e in FilteredElementCollector(doc).OfClass(FamilyInstance):
    try:
        cat = e.Category.Name if e.Category else None
    except Exception:
        cat = None
    if cat not in ("Columns", "Structural Columns", "Structural Framing", "Mechanical Equipment",
                    "Plumbing Fixtures", "Lighting Fixtures"):
        continue
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    if bb.Max.X < RX0 or bb.Min.X > RX1 or bb.Max.Y < RY0 or bb.Min.Y > RY1:
        continue
    fixtures_near.append({
        "category": cat, "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "x": [round(bb.Min.X, 3), round(bb.Max.X, 3)], "y": [round(bb.Min.Y, 3), round(bb.Max.Y, 3)],
        "z": [round(bb.Min.Z, 3), round(bb.Max.Z, 3)],
    })

OUT = {"walls_near": walls_near, "fixtures_near": fixtures_near}
