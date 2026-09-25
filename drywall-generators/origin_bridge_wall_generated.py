# origin_bridge_wall_generated.py - run via the ORIGIN Bridge. READ-ONLY.
# Dumps every ST-*/DP-* DirectShape tagged WALL=W<eid> for a hardcoded list of wall ids, for the
# wall-by-wall review (selection gets cleared/changed by run scripts, so this looks up by id).
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

TARGET_EIDS = [380854, 392686, 407836]
tags = ["WALL=W" + str(e) for e in TARGET_EIDS]

out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or not any(t in comments for t in tags):
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = ds.get_BoundingBox(None)
    rec = {"mark": mark, "comments": comments}
    if bb is not None:
        rec["size_ft"] = [round(bb.Max.X - bb.Min.X, 3), round(bb.Max.Y - bb.Min.Y, 3), round(bb.Max.Z - bb.Min.Z, 3)]
        rec["bbox"] = {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                        "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}
    out.append(rec)
out.sort(key=lambda r: r["mark"] or "")
OUT = {"target_eids": TARGET_EIDS, "count": len(out), "elements": out}
