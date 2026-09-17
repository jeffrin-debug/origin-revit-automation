# probe_split_rooms.py
# ============================================================
# One region is swallowing several real rooms: Project1 gives a single 529 sf space where
# there should be room A / room B / room C. Cause is interior walls that do not quite meet -
# the space bleeds between them, so Revit sees one connected region.
#
# Perimeter sealing alone does not fix that; it only stops the leak to the outside. This tests
# ALSO bridging the interior gaps, at several thresholds, so we can see how the room count
# responds and pick one on evidence rather than taste.
#
#   threshold too small -> gaps stay open, rooms stay merged
#   threshold too large -> genuine open archways get closed, splitting rooms that are really
#                          one space
#
# Everything runs inside rolled-back SubTransactions. Nothing is modified.
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

JOIN_TOL = 0.08                       # ft - ends closer than this already count as joined
THRESHOLDS_MM = [0, 150, 350, 700, 1100, 1500]   # 0 = perimeter sealing only, as the baseline


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def point_on_segment(p, a, b, tol):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return dist(p, a) <= tol
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2
    if t < 0.0 or t > 1.0:
        return False
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)) <= tol


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


res = {"doc": doc.Title, "results": []}

levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)

# the storey = the level with the most walls based on it
counts = {}
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        counts[eid_value(w.LevelId)] = counts.get(eid_value(w.LevelId), 0) + 1
    except Exception:
        continue
best_lid = sorted(counts.items(), key=lambda kv: -kv[1])[0][0] if counts else None
base_lv = None
for lv in levels:
    if eid_value(lv.Id) == best_lid:
        base_lv = lv
        break
if base_lv is None:
    base_lv = levels[0]
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
        if v.IsTemplate:
            continue
        gl = v.GenLevel
        if gl is not None and eid_value(gl.Id) == eid_value(base_lv.Id):
            plan_view = v
            break
    except Exception:
        continue
res["plan_view"] = plan_view.Name if plan_view is not None else None

# footprint: floor slab, else largest ceiling
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

# walls present at the computation plane
active = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        loc = w.Location
        crv = loc.Curve if isinstance(loc, LocationCurve) else None
        if crv is None:
            continue
        bb = w.get_BoundingBox(None)
        if bb is None or not (bb.Min.Z <= plane_ft + 1e-6 <= bb.Max.Z + 1e-6):
            continue
        rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
        if rb is not None and rb.AsInteger() != 1:
            continue
        a = crv.GetEndPoint(0)
        b = crv.GetEndPoint(1)
        active.append({"id": eid_value(w.Id), "a": (a.X, a.Y), "b": (b.X, b.Y)})
    except Exception:
        continue
res["walls_active"] = len(active)

# every dangling end paired with its nearest neighbouring end
pairs = []
seen = set()
for s in active:
    for key in ("a", "b"):
        p = s[key]
        joined = False
        for o in active:
            if o["id"] == s["id"]:
                continue
            if dist(p, o["a"]) <= JOIN_TOL or dist(p, o["b"]) <= JOIN_TOL \
                    or point_on_segment(p, o["a"], o["b"], JOIN_TOL):
                joined = True
                break
        if joined:
            continue
        best, bq = None, None
        for o in active:
            if o["id"] == s["id"]:
                continue
            for q in (o["a"], o["b"]):
                d = dist(p, q)
                if best is None or d < best:
                    best, bq = d, q
        if best is None:
            continue
        k = tuple(sorted([(round(p[0], 4), round(p[1], 4)),
                          (round(bq[0], 4), round(bq[1], 4))]))
        if k in seen:
            continue
        seen.add(k)
        pairs.append((p, bq, best))
res["dangling_pairs"] = len(pairs)
res["pair_gaps_mm"] = sorted(set(round(g * 304.8, 1) for (_, _, g) in pairs))[:40]

t = None
try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, "ORIGIN split-rooms probe (rolled back)")
    fho = t.GetFailureHandlingOptions()
    try:
        fho.SetForcedModalHandling(False)
        fho.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    t.Start()

    ph = None
    try:
        phs = doc.Phases
        ph = phs.get_Item(phs.Size - 1)
    except Exception:
        pass

    for thr_mm in THRESHOLDS_MM:
        st = SubTransaction(doc)
        row = {"bridge_threshold_mm": thr_mm}
        try:
            st.Start()
            sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
                XYZ.BasisZ, XYZ(0, 0, plane_ft)))

            def _line(a, b):
                arr = CurveArray()
                arr.Append(Line.CreateBound(XYZ(a[0], a[1], plane_ft),
                                            XYZ(b[0], b[1], plane_ft)))
                doc.Create.NewRoomBoundaryLines(sp, arr, plan_view)

            n_perim = 0
            if foot is not None and plan_view is not None:
                for i in range(len(foot)):
                    a, b = foot[i], foot[(i + 1) % len(foot)]
                    if dist(a, b) < 0.01:
                        continue
                    try:
                        _line(a, b)
                        n_perim += 1
                    except Exception:
                        continue

            n_bridge = 0
            thr_ft = thr_mm / 304.8
            if thr_mm > 0 and plan_view is not None:
                for (p, q, g) in pairs:
                    if g <= thr_ft and g >= 0.01:
                        try:
                            _line(p, q)
                            n_bridge += 1
                        except Exception:
                            continue

            doc.Regenerate()
            try:
                doc.Create.NewRooms2(base_lv, ph) if ph is not None else doc.Create.NewRooms2(base_lv)
            except Exception:
                doc.Create.NewRooms2(base_lv)
            doc.Regenerate()

            areas = []
            for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                      .WhereElementIsNotElementType()):
                try:
                    if r.Area and r.Area > 0:
                        areas.append(round(r.Area, 1))
                except Exception:
                    continue
            areas.sort(reverse=True)
            row.update({
                "perimeter_lines": n_perim,
                "bridge_lines": n_bridge,
                "rooms": len(areas),
                "total_area_sf": round(sum(areas), 1),
                "largest_room_sf": areas[0] if areas else 0,
                "areas_sf": areas[:25],
            })
        except Exception:
            row["error"] = traceback.format_exc()[-400:]
        finally:
            try:
                st.RollBack()
            except Exception:
                pass
        res["results"].append(row)
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
