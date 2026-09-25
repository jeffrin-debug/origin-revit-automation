# origin_bridge_probe_selection_studs.py - run via the ORIGIN Bridge. READ-ONLY.
# Reports mark/host/bbox for the currently selected element(s), plus their host wall's own eid -
# for identifying which walls a set of user-selected "exposed stud" elements belong to.
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

ids = uidoc.Selection.GetElementIds()
out = []
for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    host_eid = None
    if comments:
        for tok in comments.split("|"):
            tok = tok.strip()
            if tok.startswith("WALL=W"):
                try:
                    host_eid = int(tok[6:])
                except Exception:
                    pass
    bb = e.get_BoundingBox(None)
    out.append({
        "mark": mark, "comments": comments, "host_eid": host_eid,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })

OUT = {"count": len(out), "elements": out}
