# origin_bridge_identify_selection2.py - run via the ORIGIN Bridge. READ-ONLY.
# Dumps mark/comments/bbox for every currently-selected DirectShape, to identify what the user
# means by "these meshes should be a single drywall panel."
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

ids = list(uidoc.Selection.GetElementIds())
out = []
for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        out.append({"element_id": None, "type": "None"})
        continue
    entry = {"type": type(e).__name__}
    try:
        entry["element_id"] = int(eid.Value)
    except Exception:
        try:
            entry["element_id"] = int(eid.IntegerValue)
        except Exception:
            entry["element_id"] = None
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        entry["mark"] = mk.AsString() if mk else None
    except Exception:
        entry["mark"] = None
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        entry["comments"] = cm.AsString() if cm else None
    except Exception:
        entry["comments"] = None
    try:
        bb = e.get_BoundingBox(None)
        entry["bbox"] = None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}
    except Exception:
        entry["bbox"] = None
    out.append(entry)

OUT = {"selection_count": len(ids), "elements": out}
