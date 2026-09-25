# origin_bridge_check_ceiling_good_bad.py - run via the ORIGIN Bridge. READ-ONLY.
# User named specific GOOD/BAD elements to derive the real ceiling stud-vs-drywall orientation
# rule empirically. Dumps bbox (X/Y/Z spans), comments (kind/host), and long-axis direction for
# each, so the horizontal-vs-vertical relationship can be read directly from real geometry.
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

TARGETS = ["DP-C004-001", "DP-C004-002", "ST-S001-019", "ST-S001-014", "ST-C004-003", "ST-C004-006"]

results = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGETS:
        continue
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = e.get_BoundingBox(None)
    entry = {
        "mark": mark,
        "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "comments": comments,
    }
    if bb is not None:
        xs = round(bb.Max.X - bb.Min.X, 4)
        ys = round(bb.Max.Y - bb.Min.Y, 4)
        zs = round(bb.Max.Z - bb.Min.Z, 4)
        entry["bbox_min"] = [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)]
        entry["bbox_max"] = [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]
        entry["x_span_ft"] = xs
        entry["y_span_ft"] = ys
        entry["z_span_ft"] = zs
        # long axis = whichever of X/Y is largest (Z is the ceiling's own thickness/depth axis
        # for a horizontal ceiling plane, so X vs Y tells us the RUN direction on the plane)
        entry["long_axis"] = "X" if xs >= ys else "Y"
        entry["short_axis"] = "Y" if xs >= ys else "X"
    results.append(entry)

results.sort(key=lambda r: TARGETS.index(r["mark"]))
OUT = {"found": len(results), "elements": results}
