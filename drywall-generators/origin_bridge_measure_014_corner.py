# origin_bridge_measure_014_corner.py - run via the ORIGIN Bridge. READ-ONLY.
# Wall 014 is full-height (Z 0-10); walls 026/068/069 converging at its end are elevated bands
# (Z 7-10 only). Measures the REAL boolean gap/overlap between wall 014's top-course boards and
# every DP-*/ST-* element of 026/068/069 at that shared Z-band, to find the exact visible gap.
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

WALL014_MARKS = ["DP-014-003A", "DP-014-003B", "ST-014-001", "ST-014-004", "ST-014-005"]
OTHER_WALL_MARKS = ["DP-026-001A", "DP-026-001B", "ST-026-002", "ST-026-003", "ST-026-004",
                     "ST-026-005", "ST-026-006",
                     "DP-068-001A", "DP-068-001B", "ST-068-001", "ST-068-002", "ST-068-004", "ST-068-005",
                     "ST-069-001", "ST-069-002"]


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
by_mark = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark:
        by_mark[mark] = ds

pairs = []
for m1 in WALL014_MARKS:
    ds1 = by_mark.get(m1)
    if ds1 is None:
        continue
    bb1 = ds1.get_BoundingBox(None)
    for m2 in OTHER_WALL_MARKS:
        ds2 = by_mark.get(m2)
        if ds2 is None:
            continue
        bb2 = ds2.get_BoundingBox(None)
        # only bother with real boolean check if within 6 inches
        gap_ft = min_face_gap(bb1, bb2)
        if gap_ft > 0.5:
            continue
        max_ov = 0.0
        for s1 in solids_of(ds1):
            for s2 in solids_of(ds2):
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        pairs.append({
            "a": m1, "b": m2, "bbox_gap_in": round(gap_ft * 12.0, 4),
            "real_overlap_cf": round(max_ov, 8),
            "a_bbox": {"min": [round(bb1.Min.X, 4), round(bb1.Min.Y, 4), round(bb1.Min.Z, 4)],
                       "max": [round(bb1.Max.X, 4), round(bb1.Max.Y, 4), round(bb1.Max.Z, 4)]},
            "b_bbox": {"min": [round(bb2.Min.X, 4), round(bb2.Min.Y, 4), round(bb2.Min.Z, 4)],
                       "max": [round(bb2.Max.X, 4), round(bb2.Max.Y, 4), round(bb2.Max.Z, 4)]},
        })

OUT = {"pairs": pairs}
