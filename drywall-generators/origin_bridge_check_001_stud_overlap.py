# origin_bridge_check_001_stud_overlap.py - run via the ORIGIN Bridge. READ-ONLY.
# DP-001-003B/007B (wall "001", host eid 374947) genuinely overlap 6/3 of their OWN wall's studs
# by a consistent ~0.004 cf each - a same-host board-vs-stud conflict, different from the
# track-width issue. Dumps the board and stud bboxes plus the wall's own geometry to find the
# exact Y-offset mechanics.
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

TARGETS = ["DP-001-003A", "DP-001-003B", "DP-001-007A", "DP-001-007B",
          "ST-001-001", "ST-001-012", "ST-001-013", "ST-001-014",
          "ST-001-015", "ST-001-016", "ST-001-017", "ST-001-018", "ST-001-019"]

out = []
host_eid = None
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
    if comments and "WALL=W" in comments and host_eid is None:
        for tok in comments.split("|"):
            tok = tok.strip()
            if tok.startswith("WALL=W"):
                try:
                    host_eid = int(tok.replace("WALL=W", ""))
                except Exception:
                    pass
    bb = ds.get_BoundingBox(None)
    out.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })
out.sort(key=lambda r: r["mark"])

wall_info = None
if host_eid is not None:
    w = doc.GetElement(ElementId(host_eid))
    if isinstance(w, Wall):
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        wall_info = {
            "eid": host_eid, "width_in": round(w.Width * 12.0, 3),
            "p0": [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)],
            "p1": [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)],
        }

OUT = {"elements": out, "wall_info": wall_info}
