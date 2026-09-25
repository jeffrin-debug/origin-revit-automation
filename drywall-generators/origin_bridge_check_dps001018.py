# origin_bridge_check_dps001018.py - run via the ORIGIN Bridge. READ-ONLY.
# Investigates DP-S001-018 (a soffit drywall board the user selected) and its nearby neighbors,
# to understand its current orientation and context within the soffit's zone-tiled layout before
# changing anything.
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

target = None
all_boards = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-S001-"):
        continue
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    rec = {
        "mark": mark, "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "comments": comments,
        "x": [round(bb.Min.X, 3), round(bb.Max.X, 3)],
        "y": [round(bb.Min.Y, 3), round(bb.Max.Y, 3)],
        "z": [round(bb.Min.Z, 3), round(bb.Max.Z, 3)],
        "x_span": round(bb.Max.X - bb.Min.X, 3), "y_span": round(bb.Max.Y - bb.Min.Y, 3),
    }
    rec["long_axis"] = "X" if rec["x_span"] >= rec["y_span"] else "Y"
    all_boards.append(rec)
    if mark == "DP-S001-018":
        target = rec

nearby = []
if target is not None:
    pad = 2.0
    tx0, tx1 = target["x"]
    ty0, ty1 = target["y"]
    for b in all_boards:
        if b["mark"] == "DP-S001-018":
            continue
        bx0, bx1 = b["x"]
        by0, by1 = b["y"]
        if bx1 < tx0 - pad or bx0 > tx1 + pad or by1 < ty0 - pad or by0 > ty1 + pad:
            continue
        nearby.append(b)

OUT = {"target": target, "nearby": nearby, "all_boards_count": len(all_boards)}
