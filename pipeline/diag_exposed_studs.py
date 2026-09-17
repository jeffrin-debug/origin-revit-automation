# diag_exposed_studs.py - READ-ONLY.
# For each SELECTED framing member, decide whether drywall actually covers it, on each face,
# and if not, say what is nearest and how far away.
#
# Coverage is tested with real geometry, not bboxes: a thin probe slab is built just outside the
# member's own face position, spanning its along-wall extent and its Z extent, and intersected
# with every nearby board solid. A board that merely shares bounding-box space does not count.
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

APP_ID = "ORIGIN_ASSEMBLY_V4"
PROBE_T = 0.08          # probe slab thickness (ft) - thicker than a board face tolerance
SEARCH_FT = 3.0         # how far around the member to look for boards


def eidv(e):
    return e.IntegerValue if hasattr(e, "IntegerValue") else e.Value


def comment_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def mark_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return p.AsString() if p else None
    except Exception:
        return None


def solids_of(e):
    out = []
    try:
        geo = e.get_Geometry(Options())
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
            else:
                try:
                    inst = g.GetInstanceGeometry()
                    if inst:
                        for h in inst:
                            if isinstance(h, Solid) and h.Volume > 1e-9:
                                out.append(h)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def box(e):
    bb = e.get_BoundingBox(None)
    if bb is None:
        return None
    return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)


def make_box(x0, y0, z0, x1, y1, z1):
    try:
        pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[CurveLoop]()
        loops.Add(loop)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)
    except Exception:
        return None


# ---- collect every generated board once -------------------------------------------------------
boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    c = comment_of(ds)
    if not c.startswith(APP_ID + " |") or "| DRYWALL" not in c:
        continue
    b = box(ds)
    if b is None:
        continue
    boards.append({"el": ds, "mark": mark_of(ds), "box": b, "comment": c})

ids = []
try:
    ids = list(uidoc.Selection.GetElementIds())
except Exception:
    pass

items = []
for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    c = comment_of(e)
    rec = {"id": eidv(eid), "mark": mark_of(e), "comment": c}
    b = box(e)
    if b is None:
        rec["error"] = "no bounding box"
        items.append(rec)
        continue
    rec["bbox"] = [round(v, 3) for v in b]
    rec["size_ft"] = [round(b[3] - b[0], 3), round(b[4] - b[1], 3), round(b[5] - b[2], 3)]

    # host wall + its orientation, so "which face" is meaningful
    host_eid = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL=W"):
            try:
                host_eid = int(tok[len("WALL=W"):])
            except Exception:
                pass
    rec["host_wall"] = host_eid
    nx = ny = None
    if host_eid is not None:
        w = doc.GetElement(ElementId(host_eid))
        if w is not None:
            try:
                o = w.Orientation
                nx, ny = o.X, o.Y
                rec["wall_orientation"] = [round(o.X, 3), round(o.Y, 3)]
                rec["wall_type"] = w.Name
                rec["wall_width_in"] = round(w.WallType.Width * 12.0, 2)
                crv = w.Location.Curve
                rec["wall_len_ft"] = round(crv.Length, 3)
            except Exception:
                pass

    # nearby boards
    near = []
    for bd in boards:
        bb2 = bd["box"]
        if (bb2[3] < b[0] - SEARCH_FT or bb2[0] > b[3] + SEARCH_FT or
                bb2[4] < b[1] - SEARCH_FT or bb2[1] > b[4] + SEARCH_FT or
                bb2[5] < b[2] - 0.5 or bb2[2] > b[5] + 0.5):
            continue
        near.append(bd)
    rec["boards_within_3ft"] = len(near)

    # probe each side of the member along the wall normal
    if nx is None:
        rec["coverage"] = "unknown - no host wall orientation"
    else:
        cx = (b[0] + b[3]) / 2.0
        cy = (b[1] + b[4]) / 2.0
        half = 0.5 * math.hypot(b[3] - b[0], b[4] - b[1])
        sides = {}
        for side_name, sgn in (("exterior(+normal)", 1.0), ("interior(-normal)", -1.0)):
            # step just outside the member on this side
            for dist in (0.10, 0.20, 0.35):
                px = cx + nx * sgn * (dist)
                py = cy + ny * sgn * (dist)
                # a slab spanning the member's own Z range, thin across the wall
                probe = make_box(px - PROBE_T, py - PROBE_T, b[2] + 0.05,
                                 px + PROBE_T, py + PROBE_T, b[5] - 0.05)
                if probe is None:
                    continue
                hit = None
                for bd in near:
                    for s in solids_of(bd["el"]):
                        try:
                            inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                                probe, s, BooleanOperationsType.Intersect)
                        except Exception:
                            continue
                        if inter is not None and inter.Volume > 1e-9:
                            hit = bd["mark"]
                            break
                    if hit:
                        break
                if hit:
                    sides[side_name] = {"covered_by": hit, "at_offset_ft": dist}
                    break
            if side_name not in sides:
                # nothing there - report the nearest board on that side for context
                best = None
                for bd in near:
                    bb2 = bd["box"]
                    mx = (bb2[0] + bb2[3]) / 2.0
                    my = (bb2[1] + bb2[4]) / 2.0
                    proj = (mx - cx) * nx * sgn + (my - cy) * ny * sgn
                    if proj <= 0:
                        continue
                    d = math.hypot(mx - cx, my - cy)
                    if best is None or d < best[1]:
                        best = (bd["mark"], d)
                sides[side_name] = {"covered_by": None,
                                    "nearest_board": (best[0] if best else None),
                                    "nearest_dist_ft": (round(best[1], 3) if best else None)}
        rec["coverage"] = sides
    items.append(rec)

OUT = {"doc": doc.Title, "selected": len(ids), "generated_boards_in_model": len(boards),
       "items": items}
