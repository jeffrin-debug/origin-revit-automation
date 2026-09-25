# origin_bridge_verify_column_cutout_flush.py - run via the ORIGIN Bridge. READ-ONLY.
# After tightening COLUMN_BEAM_CLEARANCE_FT to match DRYWALL_T_FT, confirms the ceiling/soffit
# board's actual cutout hole boundary (not just its overall bbox, which never shows a notch)
# lines up flush with the column's own board outer faces - the real test of "every panel should
# exactly meet after a cut."
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


def mark_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return p.AsString() if p else None
    except Exception:
        return None


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
ceiling_ds = None
column_boards = {}
for ds in all_ds:
    mk = mark_of(ds)
    if mk == CEILING_MARK:
        ceiling_ds = ds
    if mk in COLUMN_MARKS:
        column_boards[mk] = ds

out = {"ceiling_found": ceiling_ds is not None,
       "column_boards_found": list(column_boards.keys())}

if ceiling_ds is not None:
    out["column_board_bboxes"] = {}
    for mk, ds in column_boards.items():
        bb = ds.get_BoundingBox(None)
        out["column_board_bboxes"][mk] = {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)],
        }

    # The column sits at/near the panel's own corner, so the cutout is a NOTCH bitten out of the
    # panel's outer boundary (a concave loop), not a separate hole loop. Find the panel's largest
    # horizontal face, walk its single outer loop, and keep only the vertices that fall near the
    # column's own footprint - that sub-path traces the actual cut edge by the column.
    cbb0 = min(v["min"][0] for v in out["column_board_bboxes"].values()) - 1.0
    cbb1 = min(v["min"][1] for v in out["column_board_bboxes"].values()) - 1.0
    cbb2 = max(v["max"][0] for v in out["column_board_bboxes"].values()) + 1.0
    cbb3 = max(v["max"][1] for v in out["column_board_bboxes"].values()) + 1.0

    opt = Options()
    geo = ceiling_ds.get_Geometry(opt)
    notch_pts = []
    if geo is not None:
        for g in geo:
            if not isinstance(g, Solid) or g.Volume < 1e-9:
                continue
            best_face, best_area = None, -1.0
            for f in g.Faces:
                if not isinstance(f, PlanarFace):
                    continue
                n = f.FaceNormal
                if abs(n.Z) < 0.9:
                    continue
                if f.Area > best_area:
                    best_area, best_face = f.Area, f
            if best_face is None:
                continue
            for loop in best_face.GetEdgesAsCurveLoops():
                for curve in loop:
                    for pt in (curve.GetEndPoint(0), curve.GetEndPoint(1)):
                        if cbb0 <= pt.X <= cbb2 and cbb1 <= pt.Y <= cbb3:
                            notch_pts.append((round(pt.X, 4), round(pt.Y, 4)))
    notch_pts = sorted(set(notch_pts))
    out["notch_vertices_near_column"] = [{"x": p[0], "y": p[1]} for p in notch_pts]
    if notch_pts:
        nx0 = min(p[0] for p in notch_pts)
        ny0 = min(p[1] for p in notch_pts)
        nx1 = max(p[0] for p in notch_pts)
        ny1 = max(p[1] for p in notch_pts)
        out["notch_bbox_xy"] = {"min": [round(nx0, 4), round(ny0, 4)], "max": [round(nx1, 4), round(ny1, 4)]}
    uniq = [(nx0, ny0, nx1, ny1)] if notch_pts else []

    # For each hole, compute the gap/overlap against the union bbox of the column boards.
    if column_boards:
        cxs0 = min(v["min"][0] for v in out["column_board_bboxes"].values())
        cys0 = min(v["min"][1] for v in out["column_board_bboxes"].values())
        cxs1 = max(v["max"][0] for v in out["column_board_bboxes"].values())
        cys1 = max(v["max"][1] for v in out["column_board_bboxes"].values())
        out["column_boards_union_xy"] = {"min": [round(cxs0, 4), round(cys0, 4)],
                                          "max": [round(cxs1, 4), round(cys1, 4)]}
        comparisons = []
        for b in uniq:
            hx0, hy0, hx1, hy1 = b
            comparisons.append({
                "hole_bbox": {"min": [round(hx0, 4), round(hy0, 4)], "max": [round(hx1, 4), round(hy1, 4)]},
                "delta_in": {
                    "min_x": round((hx0 - cxs0) * 12.0, 4),
                    "min_y": round((hy0 - cys0) * 12.0, 4),
                    "max_x": round((hx1 - cxs1) * 12.0, 4),
                    "max_y": round((hy1 - cys1) * 12.0, 4),
                },
            })
        out["hole_vs_column_delta"] = comparisons

OUT = out
