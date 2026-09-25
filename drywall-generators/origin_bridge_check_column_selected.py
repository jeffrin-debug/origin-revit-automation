# origin_bridge_check_column_selected.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms the currently-selected column (or the last-reported one, 387249) now has generated
# DP-*/ST-* DirectShapes tagged HOST=<eid> after running the column generator.
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
target_eid = None
if ids:
    e = doc.GetElement(ids[0])
    if e is not None:
        try:
            target_eid = int(ids[0].Value)
        except Exception:
            target_eid = int(ids[0].IntegerValue)
if target_eid is None:
    target_eid = 387249

tag = "HOST=K{}".format(target_eid)
out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or tag not in comments:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = ds.get_BoundingBox(None)
    out.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })
out.sort(key=lambda r: r["mark"] or "")

OUT = {"target_eid": target_eid, "count": len(out), "elements": out}
