# origin_bridge_measure_ceiling_column_gap.py - run via the ORIGIN Bridge. READ-ONLY.
# Measures the real gap between DP-S001-004 (the ceiling/soffit board with a cutout for the K001
# column) and the column's own boards DP-K001-005/007 - to confirm whether the gap matches the
# existing COLUMN_BEAM_CLEARANCE_FT margin used when punching the column hole in ceiling boards.
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

CEILING_MARK = "DP-S001-004"
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

ceiling_ds = None
column_boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark == CEILING_MARK:
        ceiling_ds = ds
    if mark in COLUMN_MARKS:
        column_boards.append((ds, mark))

out = {"ceiling_found": ceiling_ds is not None, "column_boards_found": [m for (_, m) in column_boards]}

if ceiling_ds is not None:
    cbb = ceiling_ds.get_BoundingBox(None)
    out["ceiling_bbox"] = {"min": [round(cbb.Min.X,4), round(cbb.Min.Y,4), round(cbb.Min.Z,4)],
                            "max": [round(cbb.Max.X,4), round(cbb.Max.Y,4), round(cbb.Max.Z,4)]}
    csolids = solids_of(ceiling_ds)
    pairs = []
    for (kds, kmark) in column_boards:
        kbb = kds.get_BoundingBox(None)
        gap_ft = min_face_gap(cbb, kbb)
        max_ov = 0.0
        ksolids = solids_of(kds)
        for s1 in csolids:
            for s2 in ksolids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        pairs.append({
            "column_board": kmark, "gap_in": round(gap_ft * 12.0, 4),
            "real_overlap_cf": round(max_ov, 6),
            "column_bbox": {"min": [round(kbb.Min.X,4), round(kbb.Min.Y,4), round(kbb.Min.Z,4)],
                             "max": [round(kbb.Max.X,4), round(kbb.Max.Y,4), round(kbb.Max.Z,4)]},
        })
    out["pairs"] = pairs

OUT = out
