# origin_bridge_measure_wall008_vs_column.py - run via the ORIGIN Bridge. READ-ONLY.
# Measures the real boolean overlap between wall 008's boards (DP-008-002B, DP-008-006A, 006B) and
# the K001 corner column's own drywall boards (DP-K001-003, DP-K001-007) - user report: wall
# drywall is intruding a small amount ("maybe 0.2 inches") into the column panels.
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

WALL_MARKS = ["DP-008-002B", "DP-008-006A", "DP-008-006B"]
COLUMN_MARKS = ["DP-K001-001", "DP-K001-003", "DP-K001-005", "DP-K001-007"]


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


def min_face_gap(b1, b2):
    gaps = []
    for lo1, hi1, lo2, hi2 in [(b1.Min.X, b1.Max.X, b2.Min.X, b2.Max.X),
                                (b1.Min.Y, b1.Max.Y, b2.Min.Y, b2.Max.Y),
                                (b1.Min.Z, b1.Max.Z, b2.Min.Z, b2.Max.Z)]:
        gaps.append(max(lo1 - hi2, lo2 - hi1, 0.0))
    return max(gaps)


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
wall_boards = {}
column_boards = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in WALL_MARKS:
        wall_boards[mark] = ds
    if mark in COLUMN_MARKS:
        column_boards[mark] = ds

out = {
    "wall_boards_found": list(wall_boards.keys()),
    "column_boards_found": list(column_boards.keys()),
    "pairs": [],
}

for wmark, wds in wall_boards.items():
    wbb = wds.get_BoundingBox(None)
    wsolids = solids_of(wds)
    for cmark, cds in column_boards.items():
        cbb = cds.get_BoundingBox(None)
        gap_ft = min_face_gap(wbb, cbb)
        max_ov = 0.0
        csolids = solids_of(cds)
        for s1 in wsolids:
            for s2 in csolids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if gap_ft < 0.5 or max_ov > 1e-9:
            out["pairs"].append({
                "wall_board": wmark, "column_board": cmark,
                "bbox_gap_in": round(gap_ft * 12.0, 4),
                "real_overlap_cf": round(max_ov, 8),
                "wall_bbox": {"min": [round(wbb.Min.X, 4), round(wbb.Min.Y, 4), round(wbb.Min.Z, 4)],
                              "max": [round(wbb.Max.X, 4), round(wbb.Max.Y, 4), round(wbb.Max.Z, 4)]},
                "column_bbox": {"min": [round(cbb.Min.X, 4), round(cbb.Min.Y, 4), round(cbb.Min.Z, 4)],
                                 "max": [round(cbb.Max.X, 4), round(cbb.Max.Y, 4), round(cbb.Max.Z, 4)]},
            })

OUT = out
