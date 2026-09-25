# origin_bridge_check_s001_area_full.py - run via the ORIGIN Bridge. READ-ONLY.
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

RX0, RX1 = -51.0, -45.0
RY0, RY1 = 5.0, 16.5

boards = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "CEILING=C406965" not in comments or "DRYWALL" not in comments:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    if bb.Max.X < RX0 or bb.Min.X > RX1 or bb.Max.Y < RY0 or bb.Min.Y > RY1:
        continue
    boards.append({
        "mark": mark, "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)],
        "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)],
    })

boards.sort(key=lambda r: r["y"][0])
OUT = {"boards": boards}
