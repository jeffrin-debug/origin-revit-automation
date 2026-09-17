# probe_why_merged.py
# ============================================================
# One region swallows several rooms. Two possible explanations, and they need opposite fixes:
#
#   A) partitions EXIST inside that region but fail to divide it -> find out why (not room
#      bounding / not present at the computation plane / gaps at both ends)
#   B) there are no partitions there at all -> the space genuinely is open-plan, and splitting
#      it means deciding where, which is a modelling question, not a bug
#
# Seals the perimeter, places rooms, finds the largest one, and reports every wall lying INSIDE
# it. All inside a rolled-back transaction.
# ============================================================

import clr
import math
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def point_in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def dist_to_poly(px, py, poly):
    best = None
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-12:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if best is None or d < best:
            best = d
    return best


def bottom_loops(e):
    opt = Options()
    opt.ComputeReferences = False
    best, bz = None, None
    try:
        for g in e.get_Geometry(opt):
            if not isinstance(g, Solid) or g.Volume <= 0:
                continue
            for f in g.Faces:
                if isinstance(f, PlanarFace) and f.FaceNormal.Z < -0.9:
                    if best is None or f.Origin.Z < bz:
                        best, bz = f, f.Origin.Z
    except Exception:
        return None
    if best is None:
        return None
    loops = []
    try:
        for cl in best.GetEdgesAsCurveLoops():
            pts = []
            for c in cl:
                try:
                    tess = c.Tessellate()
                except Exception:
                    tess = [c.GetEndPoint(0), c.GetEndPoint(1)]
                for p in tess:
                    if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                        pts.append((p.X, p.Y))
            if len(pts) >= 3:
                loops.append(pts)
    except Exception:
        return None
    if not loops:
        return None
    loops.sort(key=poly_area, reverse=True)
    return loops


res = {"doc": doc.Title}

levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)
counts = {}
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        counts[eid_value(w.LevelId)] = counts.get(eid_value(w.LevelId), 0) + 1
    except Exception:
        continue
best_lid = sorted(counts.items(), key=lambda kv: -kv[1])[0][0] if counts else None
base_lv = levels[0]
for lv in levels:
    if eid_value(lv.Id) == best_lid:
        base_lv = lv
        break
res["storey"] = base_lv.Name

plane_ft = base_lv.Elevation
try:
    p = base_lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
    plane_ft = base_lv.Elevation + (p.AsDouble() if p else 0.0)
except Exception:
    pass

plan_view = None
for v in FilteredElementCollector(doc).OfClass(ViewPlan):
    try:
        if (not v.IsTemplate) and v.GenLevel is not None \
                and eid_value(v.GenLevel.Id) == eid_value(base_lv.Id):
            plan_view = v
            break
    except Exception:
        continue

foot, best_a = None, 0.0
for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
    loops = bottom_loops(fl)
    if loops and poly_area(loops[0]) > best_a:
        best_a, foot = poly_area(loops[0]), loops[0]
if foot is None:
    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        loops = bottom_loops(c)
        if loops and poly_area(loops[0]) > best_a:
            best_a, foot = poly_area(loops[0]), loops[0]
res["footprint_sf"] = round(best_a, 1)

t = None
try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, "ORIGIN why-merged probe (rolled back)")
    fho = t.GetFailureHandlingOptions()
    try:
        fho.SetForcedModalHandling(False)
        fho.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    t.Start()

    if foot is not None and plan_view is not None:
        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
            XYZ.BasisZ, XYZ(0, 0, plane_ft)))
        for i in range(len(foot)):
            a, b = foot[i], foot[(i + 1) % len(foot)]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.01:
                continue
            try:
                arr = CurveArray()
                arr.Append(Line.CreateBound(XYZ(a[0], a[1], plane_ft),
                                            XYZ(b[0], b[1], plane_ft)))
                doc.Create.NewRoomBoundaryLines(sp, arr, plan_view)
            except Exception:
                continue
    doc.Regenerate()

    ph = None
    try:
        phs = doc.Phases
        ph = phs.get_Item(phs.Size - 1)
    except Exception:
        pass
    try:
        doc.Create.NewRooms2(base_lv, ph) if ph is not None else doc.Create.NewRooms2(base_lv)
    except Exception:
        doc.Create.NewRooms2(base_lv)
    doc.Regenerate()

    opts = SpatialElementBoundaryOptions()
    try:
        opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
    except Exception:
        pass

    biggest, biggest_area, all_rooms = None, 0.0, []
    for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        try:
            if not r.Area or r.Area <= 0:
                continue
            all_rooms.append(round(r.Area, 1))
            if r.Area > biggest_area:
                biggest_area, biggest = r.Area, r
        except Exception:
            continue
    all_rooms.sort(reverse=True)
    res["rooms"] = all_rooms
    res["largest_room_sf"] = round(biggest_area, 1)

    poly = None
    if biggest is not None:
        loops = biggest.GetBoundarySegments(opts)
        cand = []
        for loop in (loops or []):
            pts = []
            for seg in loop:
                try:
                    for p in seg.GetCurve().Tessellate():
                        if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                            pts.append((p.X, p.Y))
                except Exception:
                    continue
            if len(pts) >= 3:
                cand.append(pts)
        cand.sort(key=poly_area, reverse=True)
        poly = cand[0] if cand else None

    inside_walls = []
    if poly is not None:
        for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            try:
                loc = w.Location
                crv = loc.Curve if isinstance(loc, LocationCurve) else None
                if crv is None:
                    continue
                a = crv.GetEndPoint(0)
                b = crv.GetEndPoint(1)
                mx, my = (a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0
                if not point_in_polygon(mx, my, poly):
                    continue
                # ignore walls that merely form the room's own boundary
                if dist_to_poly(mx, my, poly) < 0.35:
                    continue
                bb = w.get_BoundingBox(None)
                rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
                inside_walls.append({
                    "id": eid_value(w.Id),
                    "length_mm": round(a.DistanceTo(b) * 304.8, 0),
                    "base_mm": None if bb is None else round(bb.Min.Z * 304.8, 1),
                    "top_mm": None if bb is None else round(bb.Max.Z * 304.8, 1),
                    "room_bounding": None if rb is None else rb.AsInteger(),
                    "at_plane": (bb is not None
                                 and bb.Min.Z <= plane_ft + 1e-6 <= bb.Max.Z + 1e-6),
                    "type": w.Name,
                })
            except Exception:
                continue
    inside_walls.sort(key=lambda r: -(r["length_mm"] or 0))
    res["walls_inside_largest_room"] = len(inside_walls)
    res["inside_walls"] = inside_walls[:25]
    res["verdict"] = ("A: partitions exist inside the merged region - they are failing to divide it"
                      if inside_walls else
                      "B: no partitions inside it - the space genuinely is open-plan")
except Exception:
    res["error"] = traceback.format_exc()
finally:
    try:
        if t is not None and t.HasStarted() and not t.HasEnded():
            t.RollBack()
    except Exception:
        pass
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

OUT = res
