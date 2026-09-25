# origin_bridge_check_wall023_faceB_layout.py - run via the ORIGIN Bridge. READ-ONLY.
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
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "WALL=W401091" not in comments:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    rec = {"mark": mark, "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)],
           "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)], "comments": comments}
    if mark.startswith("DP-") and mark.endswith("B"):
        boards.append(rec)
    elif mark.startswith("ST-"):
        studs.append(rec)

boards.sort(key=lambda r: r["x"][0])
studs.sort(key=lambda r: r["x"][0])
OUT = {"boards_faceB": boards, "studs": studs}
