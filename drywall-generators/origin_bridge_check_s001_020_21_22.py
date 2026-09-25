# origin_bridge_check_s001_020_21_22.py - run via the ORIGIN Bridge. READ-ONLY.
# User named 3 specific ceiling boards (DP-S001-020/021/022) and asked why they can't be one
# panel. Ground-truths their exact bboxes/adjacency, and checks whether any REAL wall footprint
# genuinely sits in the gap(s) between them, or whether they're artificially split with nothing
# real separating them (a zone-tiling/grid-anchoring artifact rather than a true room boundary).
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

TARGET_MARKS = ["DP-S001-020", "DP-S001-021", "DP-S001-022"]

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
boards = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in TARGET_MARKS:
        bb = ds.get_BoundingBox(None)
        boards[mark] = {
            "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                     "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
        }

out = {"boards": boards}

if boards:
    xs0 = min(v["bbox"]["min"][0] for v in boards.values())
    ys0 = min(v["bbox"]["min"][1] for v in boards.values())
    xs1 = max(v["bbox"]["max"][0] for v in boards.values())
    ys1 = max(v["bbox"]["max"][1] for v in boards.values())
    zs0 = min(v["bbox"]["min"][2] for v in boards.values())
    zs1 = max(v["bbox"]["max"][2] for v in boards.values())
    out["combined_union_bbox"] = {"min": [xs0, ys0, zs0], "max": [xs1, ys1, zs1]}

    # Any real wall whose bbox overlaps this small combined region (with a little padding)?
    pad = 0.3
    nearby_walls = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        wbb = w.get_BoundingBox(None)
        if wbb is None:
            continue
        if (wbb.Max.X < xs0 - pad or wbb.Min.X > xs1 + pad or
                wbb.Max.Y < ys0 - pad or wbb.Min.Y > ys1 + pad):
            continue
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            wtag = mk.AsString() if mk else None
        except Exception:
            wtag = None
        nearby_walls.append({
            "wall_tag": wtag,
            "bbox_xy": {"min": [round(wbb.Min.X, 4), round(wbb.Min.Y, 4)],
                        "max": [round(wbb.Max.X, 4), round(wbb.Max.Y, 4)]},
        })
    out["nearby_walls_within_0.3ft"] = nearby_walls

OUT = out
