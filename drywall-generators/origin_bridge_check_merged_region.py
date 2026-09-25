# origin_bridge_check_merged_region.py - run via the ORIGIN Bridge. READ-ONLY.
# Checks the exact spatial region formerly occupied by DP-S001-020/021/022 (X:[-44.2391,-37.5433],
# Y:[-18.4289,-14.4289]) to confirm the merge fix produced ONE board there instead of three.
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

RX0, RY0, RX1, RY1 = -44.2391, -18.4289, -37.5433, -14.4289
pad = 0.1

out = {"boards_in_region": []}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-S001"):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    if (bb.Max.X < RX0 - pad or bb.Min.X > RX1 + pad or
            bb.Max.Y < RY0 - pad or bb.Min.Y > RY1 + pad):
        continue
    out["boards_in_region"].append({
        "mark": mark,
        "size_ft": [round(bb.Max.X - bb.Min.X, 4), round(bb.Max.Y - bb.Min.Y, 4)],
        "bbox_xy": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4)],
                    "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4)]},
    })

OUT = out
