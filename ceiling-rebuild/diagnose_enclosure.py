# diagnose_enclosure.py
# ============================================================
# The big spaces are not enclosed - a Room placed in them comes back with Area 0. This finds
# WHY, by looking for the two things that make a boundary leak:
#
#   1. Dangling wall ends - a wall endpoint that touches no other wall, i.e. a hole in the
#      perimeter at the room-boundary plane.
#   2. Walls that do not exist at the room computation plane - base above it or top below it,
#      so Revit sees no wall there even though one is visible in 3D.
#
# Read-only. Nothing is modified.
# ============================================================

import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

JOIN_TOL = 0.08          # ft (~25 mm) - how close two wall ends must be to count as joined


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
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return dist(p, a) <= tol
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    if t < 0.0 or t > 1.0:
        return False
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= tol


res = {"doc": doc.Title, "join_tol_mm": round(JOIN_TOL * 304.8, 1)}

# --- computation plane ---------------------------------------------------------------
levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)
lv_rows = []
for lv in levels:
    row = {"name": lv.Name, "elev_mm": round(lv.Elevation * 304.8, 1)}
    try:
        p = lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
        row["computation_height_mm"] = round(p.AsDouble() * 304.8, 1) if p else None
        row["computation_plane_abs_mm"] = round((lv.Elevation + (p.AsDouble() if p else 0.0)) * 304.8, 1)
    except Exception:
        row["computation_height_mm"] = None
    lv_rows.append(row)
res["levels"] = lv_rows

base_lv = levels[0] if levels else None
plane_abs_ft = 0.0
if base_lv is not None:
    try:
        p = base_lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
        plane_abs_ft = base_lv.Elevation + (p.AsDouble() if p else 0.0)
    except Exception:
        plane_abs_ft = base_lv.Elevation
res["computation_plane_abs_mm"] = round(plane_abs_ft * 304.8, 1)

# --- gather walls --------------------------------------------------------------------
segs = []
not_at_plane = []
curved = 0
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    wid = eid_value(w.Id)
    try:
        loc = w.Location
        crv = loc.Curve if isinstance(loc, LocationCurve) else None
        if crv is None:
            continue
        a = crv.GetEndPoint(0)
        b = crv.GetEndPoint(1)
        if not isinstance(crv, Line):
            curved += 1
    except Exception:
        continue

    try:
        bb = w.get_BoundingBox(None)
        zlo = bb.Min.Z if bb else None
        zhi = bb.Max.Z if bb else None
    except Exception:
        zlo = zhi = None

    spans = (zlo is not None and zhi is not None
             and zlo <= plane_abs_ft + 1e-6 and zhi >= plane_abs_ft - 1e-6)
    if not spans:
        not_at_plane.append({
            "id": wid,
            "base_mm": None if zlo is None else round(zlo * 304.8, 1),
            "top_mm": None if zhi is None else round(zhi * 304.8, 1),
        })

    try:
        rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
        bounding = (rb is None or rb.AsInteger() == 1)
    except Exception:
        bounding = True

    segs.append({"id": wid, "a": (a.X, a.Y), "b": (b.X, b.Y),
                 "spans_plane": spans, "bounding": bounding})

res["wall_count"] = len(segs)
res["curved_walls"] = curved
res["walls_not_at_computation_plane"] = {
    "count": len(not_at_plane), "sample": not_at_plane[:15]}

# --- dangling ends -------------------------------------------------------------------
# Only walls that actually exist at the computation plane can bound a room.
active = [s for s in segs if s["spans_plane"] and s["bounding"]]
res["walls_bounding_at_plane"] = len(active)

dangling = []
for s in active:
    for key in ("a", "b"):
        p = s[key]
        joined = False
        for o in active:
            if o["id"] == s["id"]:
                continue
            if dist(p, o["a"]) <= JOIN_TOL or dist(p, o["b"]) <= JOIN_TOL:
                joined = True
                break
            if point_on_segment(p, o["a"], o["b"], JOIN_TOL):
                joined = True
                break
        if not joined:
            dangling.append({"wall_id": s["id"], "end": key,
                             "xy_ft": [round(p[0], 2), round(p[1], 2)]})

res["dangling_wall_ends"] = {"count": len(dangling), "points": dangling[:40]}

# --- how far is the nearest neighbour for each dangling end? -------------------------
gaps = []
for d in dangling:
    p = (d["xy_ft"][0], d["xy_ft"][1])
    best, best_id = None, None
    for o in active:
        if o["id"] == d["wall_id"]:
            continue
        for q in (o["a"], o["b"]):
            dd = dist(p, q)
            if best is None or dd < best:
                best, best_id = dd, o["id"]
    if best is not None:
        gaps.append({"wall_id": d["wall_id"], "xy_ft": d["xy_ft"],
                     "nearest_wall": best_id,
                     "gap_mm": round(best * 304.8, 1)})
gaps.sort(key=lambda g: g["gap_mm"])
res["nearest_neighbour_gaps"] = gaps[:40]

res["room_separation_lines"] = (FilteredElementCollector(doc)
                                .OfCategory(BuiltInCategory.OST_RoomSeparationLines)
                                .WhereElementIsNotElementType().GetElementCount())

OUT = res
