# origin_bridge_dump_soffit_boards.py - run via the ORIGIN Bridge. READ-ONLY.
# Dumps every DP-S001-* board's bbox, dimensions, and Comments (cut flag) for the current soffit,
# to see the full panel layout around the one column in this model.
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
    if not mark or not mark.startswith("DP-S"):
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    dims = None
    if bb is not None:
        dims = [round(bb.Max.X - bb.Min.X, 3), round(bb.Max.Y - bb.Min.Y, 3)]
    out.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)],
        },
        "dims_xy": dims,
    })
out.sort(key=lambda r: r["mark"])
OUT = {"count": len(out), "boards": out}
