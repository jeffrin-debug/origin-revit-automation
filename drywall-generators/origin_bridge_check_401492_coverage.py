# origin_bridge_check_401492_coverage.py - run via the ORIGIN Bridge. READ-ONLY.
# New "COVERAGE GAP WALL=W401492" warning appeared after the same-host-track trim fix. Checks
# whether this is the SAME known "fully redundant, deleted, framing still exists" pattern seen
# before (a degenerate ~1in sliver wall) or a genuine new regression - by dumping the wall's own
# real length/width and whatever framing it still has.
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

WALL_EID = 401492
w = doc.GetElement(ElementId(WALL_EID))
out = {"exists": w is not None}
if w is not None:
    try:
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        length_ft = ((p1.X - p0.X) ** 2 + (p1.Y - p0.Y) ** 2) ** 0.5
        out["length_ft"] = round(length_ft, 4)
        out["width_in"] = round(w.Width * 12.0, 3)
    except Exception as ex:
        out["geom_error"] = str(ex)

elements = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "WALL=W{}".format(WALL_EID) not in comments:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    elements.append({"mark": mark, "comments": comments})
elements.sort(key=lambda r: r["mark"] or "")
out["current_elements"] = elements

OUT = out
