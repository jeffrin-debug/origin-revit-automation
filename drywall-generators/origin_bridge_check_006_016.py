# origin_bridge_check_006_016.py - run via the ORIGIN Bridge. READ-ONLY.
# Full dump + real overlap check for the DP-006-*B vs DP-016-*B conflict found by the overlap
# sweep, plus their host walls' own geometry, to find the root cause before fixing.
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

TARGET_MARKS = ["DP-006-001B", "DP-006-002B", "DP-006-003B", "DP-016-001B", "DP-016-002B", "DP-016-003B"]

out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGET_MARKS:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    out.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })
out.sort(key=lambda r: r["mark"])

# Also get the two host walls' real geometry (006 = W407836, 016 = W380595)
wall_info = []
for eid in (407836, 380595):
    w = doc.GetElement(ElementId(eid))
    if isinstance(w, Wall):
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        wall_info.append({
            "eid": eid, "width_in": round(w.Width * 12.0, 3),
            "p0": [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)],
            "p1": [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)],
        })

OUT = {"elements": out, "wall_info": wall_info}
