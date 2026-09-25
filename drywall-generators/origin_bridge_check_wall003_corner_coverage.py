# origin_bridge_check_wall003_corner_coverage.py - run via the ORIGIN Bridge. READ-ONLY.
# ST-023-001 (wall 023's own end stud at its corner with wall 003) has zero drywall coverage from
# EITHER host. Wall 003 is the real perpendicular neighbor sharing this same physical corner post.
# Checks wall 003's own studs/boards near the corner point to see whether the corner post is
# covered from wall 003's side instead, or whether it's genuinely exposed from all sides.
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

CORNER_PT = (-28.7737, 1.6626)
RADIUS = 1.0

boards = []
studs = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "WALL=W377065" not in comments:   # wall 003
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
           "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)], "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)]}
    if mark.startswith("DP-"):
        boards.append(rec)
    elif mark.startswith("ST-"):
        studs.append(rec)

boards.sort(key=lambda r: r["y"][0])
studs.sort(key=lambda r: r["y"][0])
OUT = {"wall003_boards": boards, "wall003_studs_near_corner": [s for s in studs if s["y"][0] < CORNER_PT[1] + RADIUS]}
