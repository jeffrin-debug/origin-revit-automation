# origin_bridge_verify_curtain_excluded.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms walls 373548/373575 (the curtain wall / storefront glass) have ZERO generated
# DP-*/ST-* DirectShapes tagged WALL=W<eid> after the curtain-wall exclusion fix.
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

TARGETS = ["WALL=W373548", "WALL=W373575"]

out = {t: [] for t in TARGETS}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments:
        continue
    for t in TARGETS:
        if t in comments:
            try:
                mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                mark = mk.AsString() if mk else None
            except Exception:
                mark = None
            try:
                eid_val = int(ds.Id.Value) if hasattr(ds.Id, "Value") else int(ds.Id.IntegerValue)
            except Exception:
                eid_val = None
            out[t].append({"mark": mark, "element_id": eid_val, "comments": comments})

OUT = {t: {"count": len(v), "items": v} for t, v in out.items()}
