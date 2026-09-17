# probe_bridge_gaps.py
# ============================================================
# HYPOTHESIS: the big spaces are unenclosed because wall ends do not meet - 65 dangling ends
# with 24-71 mm gaps. If we bridge those gaps with temporary Room Separation Lines, Revit
# should be able to enclose the rooms.
#
# This tests exactly that, inside a transaction that is ALWAYS ROLLED BACK:
#   1. find dangling wall ends (same logic as diagnose_enclosure.py)
#   2. draw a Room Separation Line from each to its nearest neighbouring wall end
#   3. run NewRooms2 and report how many rooms come back and their total area
#   4. roll everything back
#
# Success = total room area jumps from ~160 sf towards the ~1002 sf footprint.
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

JOIN_TOL = 0.08        # ft - ends closer than this already count as joined
MAX_BRIDGE_FT = 1.0    # ft (~305 mm) - never bridge a gap wider than a real doorway
MIN_LINE_FT = 0.01     # ft - below Revit's short-curve tolerance nothing can be drawn


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


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


res = {"doc": doc.Title}

levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)
base_lv = levels[0]
plane_ft = base_lv.Elevation
try:
    p = base_lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
    plane_ft = base_lv.Elevation + (p.AsDouble() if p else 0.0)
except Exception:
    pass

# a plan view is needed to host room separation lines
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

# --- walls active at the computation plane ------------------------------------------
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

# --- dangling ends and the bridges that would close them -----------------------------
bridges = []
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
        if best is None or best > MAX_BRIDGE_FT or best < MIN_LINE_FT:
            continue
        key2 = tuple(sorted([(round(p[0], 4), round(p[1], 4)),
                             (round(bq[0], 4), round(bq[1], 4))]))
        if key2 in seen:
            continue
        seen.add(key2)
        bridges.append((p, bq, round(best * 304.8, 1)))

res["bridges_planned"] = len(bridges)
res["bridge_gaps_mm"] = sorted(set(b[2] for b in bridges))[:20]

rooms_before = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms) \
    .WhereElementIsNotElementType().GetElementCount()
res["rooms_before"] = rooms_before

t = None
try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, "ORIGIN bridge-gaps probe (rolled back)")
    fho = t.GetFailureHandlingOptions()
    try:
        fho.SetForcedModalHandling(False)
        fho.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    t.Start()

    made = 0
    if plan_view is not None and bridges:
        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
            XYZ.BasisZ, XYZ(0, 0, plane_ft)))
        for (p, q, gap_mm) in bridges:
            try:
                arr = CurveArray()
                arr.Append(Line.CreateBound(XYZ(p[0], p[1], plane_ft),
                                            XYZ(q[0], q[1], plane_ft)))
                doc.Create.NewRoomBoundaryLines(sp, arr, plan_view)
                made += 1
            except Exception:
                continue
    res["separation_lines_created"] = made
    doc.Regenerate()

    ph = None
    try:
        phs = doc.Phases
        ph = phs.get_Item(phs.Size - 1)
    except Exception:
        pass
    try:
        ids = doc.Create.NewRooms2(base_lv, ph) if ph is not None else doc.Create.NewRooms2(base_lv)
    except Exception:
        ids = doc.Create.NewRooms2(base_lv)
    doc.Regenerate()

    areas = []
    for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        try:
            if r.Area and r.Area > 0:
                areas.append(round(r.Area, 2))
        except Exception:
            continue
    areas.sort(reverse=True)
    res["rooms_after"] = len(areas)
    res["total_room_area_sf"] = round(sum(areas), 1)
    res["room_areas_sf"] = areas[:30]
    res["verdict"] = ("BRIDGING WORKS" if sum(areas) > 400 else
                      "still leaking - bridging wall ends is not enough")
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
