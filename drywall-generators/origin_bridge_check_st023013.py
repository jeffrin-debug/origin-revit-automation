# origin_bridge_check_st023013.py - run via the ORIGIN Bridge. READ-ONLY.
# ST-023-013 (this wall's OWN bottom track) has a real, confirmed boolean overlap with its OWN
# wall's drywall boards DP-023-001B/002B - same-host, which our safety net doesn't even check
# (same-host geometry is assumed self-consistent by construction). Dumps its full bbox plus the
# other tracks/studs on this host for comparison, to find exactly what's different about it.
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

TARGETS = ["ST-023-013", "ST-023-014", "ST-023-001", "DP-023-001B", "DP-023-002B", "DP-023-001A"]

out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGETS:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    entry = {
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    }
    out.append(entry)
out.sort(key=lambda r: r["mark"])

OUT = {"elements": out}
