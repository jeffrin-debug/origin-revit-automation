# origin_bridge_check_st001017_003004.py - run via the ORIGIN Bridge. READ-ONLY.
# User selected ST-001-017 and ST-003-004 (the two studs that got corner-infill patches earlier)
# and reports a "vacuum" (gap) between them. Dumps both studs, their infill boards, and every
# nearby DP-/ST- element to see the real geometry.
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

targets = ["ST-001-017", "ST-003-004", "DP-001-011A", "DP-001-011B", "DP-003-004A", "DP-003-005B"]
found = {}
all_nearby = []

for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    if mark in targets:
        bb = e.get_BoundingBox(None)
        try:
            cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        found[mark] = {
            "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
            "comments": comments,
            "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)] if bb else None,
            "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)] if bb else None,
            "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)] if bb else None,
        }

# Broader nearby scan around ST-001-017/ST-003-004's location.
if "ST-001-017" in found:
    tx = found["ST-001-017"]["x"]
    ty = found["ST-001-017"]["y"]
    pad = 3.0
    rx0, rx1 = tx[0] - pad, tx[1] + pad
    ry0, ry1 = ty[0] - pad, ty[1] + pad
    for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if not mark or not (mark.startswith("DP-") or mark.startswith("ST-")):
            continue
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        if bb.Max.X < rx0 or bb.Min.X > rx1 or bb.Max.Y < ry0 or bb.Min.Y > ry1:
            continue
        all_nearby.append({
            "mark": mark, "x": [round(bb.Min.X, 3), round(bb.Max.X, 3)],
            "y": [round(bb.Min.Y, 3), round(bb.Max.Y, 3)], "z": [round(bb.Min.Z, 3), round(bb.Max.Z, 3)],
        })

OUT = {"found": found, "nearby": all_nearby}
