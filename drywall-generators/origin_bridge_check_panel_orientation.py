# origin_bridge_check_panel_orientation.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms whether ceiling DRYWALL panels are now oriented with their long (8ft) edge along Y
# after flipping FURRING_RUN_NS, by dumping real bboxes for a sample of DP-C* ceiling board marks.
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

out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-C"):
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    xspan = round(bb.Max.X - bb.Min.X, 3)
    yspan = round(bb.Max.Y - bb.Min.Y, 3)
    out.append({
        "mark": mark, "x_span_ft": xspan, "y_span_ft": yspan,
        "cut": ("cut=1" in comments) if comments else None,
    })
out.sort(key=lambda r: r["mark"])

OUT = {"count": len(out), "boards": out}
