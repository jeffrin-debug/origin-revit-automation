# origin_bridge_check_c002_layout.py - run via the ORIGIN Bridge. READ-ONLY.
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

boards = []
studs = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "CEILING=C393587" not in comments:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = e.get_BoundingBox(None)
    if bb is None or not mark:
        continue
    rec = {"mark": mark, "x": [round(bb.Min.X, 3), round(bb.Max.X, 3)],
           "y": [round(bb.Min.Y, 3), round(bb.Max.Y, 3)]}
    if mark.startswith("DP-"):
        boards.append(rec)
    elif mark.startswith("ST-"):
        studs.append(rec)

OUT = {"boards": boards, "studs": studs}
