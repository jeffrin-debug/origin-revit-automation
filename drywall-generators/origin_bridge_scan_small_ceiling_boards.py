# origin_bridge_scan_small_ceiling_boards.py - run via the ORIGIN Bridge. READ-ONLY.
# Lists every DP-C*/DP-S* ceiling/soffit drywall board whose plan bbox has a short dimension under
# 2ft, to find a live example of an undersized panel sitting next to a normal one - the "small
# small panels instead of one resized panel" pattern the user is describing.
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

boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-C") or mark.startswith("DP-S")):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    short = min(dx, dy)
    boards.append({
        "mark": mark, "dims_xy": [round(dx, 3), round(dy, 3)], "short_dim_ft": round(short, 3),
        "bbox": {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                 "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
    })

small = sorted([b for b in boards if b["short_dim_ft"] < 2.0], key=lambda b: b["short_dim_ft"])
OUT = {"total_ceiling_boards": len(boards), "small_count": len(small), "small_boards": small[:40]}
