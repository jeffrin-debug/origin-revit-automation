# origin_bridge_probe_selection2.py - run via the ORIGIN Bridge. READ-ONLY.
# Reports whatever is currently selected in the live Revit UI - marks, category, bbox - to
# ground-truth exactly which elements the user means, rather than guessing from typed marks.
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
out = {"count": len(ids), "elements": []}
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
    bb = e.get_BoundingBox(None)
    rec = {"id": eid.IntegerValue if hasattr(eid, "IntegerValue") else int(str(eid)),
           "category": e.Category.Name if e.Category else None,
           "mark": mark, "comments": comments}
    if bb is not None:
        rec["bbox"] = {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                        "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}
    out["elements"].append(rec)

OUT = out
