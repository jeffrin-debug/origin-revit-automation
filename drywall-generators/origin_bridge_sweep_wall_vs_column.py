# origin_bridge_sweep_wall_vs_column.py - run via the ORIGIN Bridge. READ-ONLY.
# Broad sweep: every DP-* board (any wall) whose real bbox comes within RADIUS_FT of the K001
# column's own drywall boards, with real boolean-solid overlap AND per-axis bbox overlap width
# (not just gap) - to find the genuine intrusion regardless of which exact wall board it is.
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
RADIUS_FT = 2.0


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


def axis_overlap(lo1, hi1, lo2, hi2):
    return min(hi1, hi2) - max(lo1, lo2)


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
column_boards = {}
other_boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    if mark in COLUMN_MARKS:
        column_boards[mark] = ds
    elif mark.startswith("DP-"):
        other_boards.append((mark, ds))

# Expand the union bbox of the column boards by RADIUS_FT to define the search window.
cxs0 = min(v.get_BoundingBox(None).Min.X for v in column_boards.values())
cys0 = min(v.get_BoundingBox(None).Min.Y for v in column_boards.values())
czs0 = min(v.get_BoundingBox(None).Min.Z for v in column_boards.values())
cxs1 = max(v.get_BoundingBox(None).Max.X for v in column_boards.values())
cys1 = max(v.get_BoundingBox(None).Max.Y for v in column_boards.values())
czs1 = max(v.get_BoundingBox(None).Max.Z for v in column_boards.values())
wx0, wy0, wz0 = cxs0 - RADIUS_FT, cys0 - RADIUS_FT, czs0 - RADIUS_FT
wx1, wy1, wz1 = cxs1 + RADIUS_FT, cys1 + RADIUS_FT, czs1 + RADIUS_FT

out = {"column_union_bbox": {"min": [round(cxs0, 4), round(cys0, 4), round(czs0, 4)],
                              "max": [round(cxs1, 4), round(cys1, 4), round(czs1, 4)]},
       "candidates": []}

for mark, ds in other_boards:
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    if bb.Max.X < wx0 or bb.Min.X > wx1 or bb.Max.Y < wy0 or bb.Min.Y > wy1 or bb.Max.Z < wz0 or bb.Min.Z > wz1:
        continue
    wsolids = solids_of(ds)
    for cmark, cds in column_boards.items():
        cbb = cds.get_BoundingBox(None)
        ox = axis_overlap(bb.Min.X, bb.Max.X, cbb.Min.X, cbb.Max.X)
        oy = axis_overlap(bb.Min.Y, bb.Max.Y, cbb.Min.Y, cbb.Max.Y)
        oz = axis_overlap(bb.Min.Z, bb.Max.Z, cbb.Min.Z, cbb.Max.Z)
        if ox <= -0.02 or oy <= -0.02 or oz <= -0.02:
            continue  # clearly separated on at least one axis, not worth a boolean call
        max_ov = 0.0
        err = None
        for s1 in wsolids:
            for s2 in solids_of(cds):
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception as ex:
                    err = str(ex)
        if max_ov > 1e-9 or (ox > 0 and oy > 0 and oz > 0):
            out["candidates"].append({
                "wall_board": mark, "column_board": cmark,
                "axis_overlap_in": {"x": round(ox * 12.0, 4), "y": round(oy * 12.0, 4), "z": round(oz * 12.0, 4)},
                "real_overlap_cf": round(max_ov, 8),
                "boolean_error": err,
            })

OUT = out
