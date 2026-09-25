# origin_bridge_check_all_ceiling_board_sizes.py - run via the ORIGIN Bridge. READ-ONLY.
# Verifies every DP-* ceiling/soffit board's short/long dimension against the 4x8ft standard
# sheet limit, across ALL ceiling hosts.
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

PANEL_WIDTH_FT = 4.0
PANEL_LENGTH_FT = 8.0
TOL = 1e-3

violations = []
all_boards = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-C") and not mark.startswith("DP-S"):
        continue
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "DRYWALL" not in comments:
        continue
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    xs = bb.Max.X - bb.Min.X
    ys = bb.Max.Y - bb.Min.Y
    short = min(xs, ys)
    long_ = max(xs, ys)
    rec = {"mark": mark, "short_ft": round(short, 3), "long_ft": round(long_, 3),
           "area_sf": round(xs * ys, 2)}
    all_boards.append(rec)
    if short > PANEL_WIDTH_FT + TOL or long_ > PANEL_LENGTH_FT + TOL:
        violations.append(rec)

OUT = {"total_boards": len(all_boards), "violation_count": len(violations),
       "violations": violations}
