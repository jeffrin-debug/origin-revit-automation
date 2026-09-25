# origin_bridge_sweep_column_corner.py - run via the ORIGIN Bridge. READ-ONLY.
# Broad sweep: every DirectShape within 3 ft of the K001 column's centroid, real boolean overlap
# AND real minimum gap distance against every one of the column's own 4 boards - catches any
# defect against a wall/board this session hasn't already named/checked.
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

COLUMN_MARKS = ["DP-K001-001", "DP-K001-003", "DP-K001-005", "DP-K001-007"]
RADIUS_FT = 3.0


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
    """Real closest-approach gap along whichever single axis actually separates the two boxes
    (0 if they overlap/touch on every axis) - this is a true bbox-to-bbox proximity test, NOT
    centroid distance, so it correctly catches near-contact with long/large boards whose centroid
    sits far from their actual near edge (a centroid-distance filter missed a KNOWN real 0.000079
    cf overlap against a 6.67ft-wide board in an earlier pass - fixed here)."""
    gaps = []
    for lo1, hi1, lo2, hi2 in [(b1.Min.X, b1.Max.X, b2.Min.X, b2.Max.X),
                                (b1.Min.Y, b1.Max.Y, b2.Min.Y, b2.Max.Y),
                                (b1.Min.Z, b1.Max.Z, b2.Min.Z, b2.Max.Z)]:
        gaps.append(max(lo1 - hi2, lo2 - hi1, 0.0))
    return max(gaps)


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

col_boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in COLUMN_MARKS:
        col_boards.append((ds, mark))

results = []
for (cds, cmark) in col_boards:
    cbb = cds.get_BoundingBox(None)
    # Expanded test box (RADIUS_FT margin on every side) - an element only needs to come within
    # this margin of the column board's REAL EXTENT, not its centroid, to be considered "close."
    exp = (cbb.Min.X - RADIUS_FT, cbb.Min.Y - RADIUS_FT, cbb.Min.Z - RADIUS_FT,
           cbb.Max.X + RADIUS_FT, cbb.Max.Y + RADIUS_FT, cbb.Max.Z + RADIUS_FT)
    csolids = solids_of(cds)
    findings = []
    for ds in all_ds:
        if ds.Id == cds.Id:
            continue
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            omark = mk.AsString() if mk else None
        except Exception:
            omark = None
        if omark in COLUMN_MARKS:
            continue  # skip the column's own sibling boards, already checked separately
        obb = ds.get_BoundingBox(None)
        if obb is None:
            continue
        if (obb.Max.X < exp[0] or obb.Min.X > exp[3] or obb.Max.Y < exp[1] or obb.Min.Y > exp[4]
                or obb.Max.Z < exp[2] or obb.Min.Z > exp[5]):
            continue
        gap_ft = min_face_gap(cbb, obb)
        osolids = solids_of(ds)
        max_ov = 0.0
        if osolids and gap_ft < 0.05:  # only run the expensive boolean when genuinely close
            for s1 in csolids:
                for s2 in osolids:
                    try:
                        inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                            s1, s2, BooleanOperationsType.Intersect)
                        if inter is not None and inter.Volume > max_ov:
                            max_ov = inter.Volume
                    except Exception:
                        continue
        if gap_ft < 0.05 or max_ov > 1e-9:
            findings.append({
                "other_mark": omark, "gap_in": round(gap_ft * 12.0, 4),
                "real_overlap_cf": round(max_ov, 6),
            })
    findings.sort(key=lambda f: (-f["real_overlap_cf"], f["gap_in"]))
    results.append({"column_board": cmark, "close_neighbors": findings})

OUT = {"results": results}
