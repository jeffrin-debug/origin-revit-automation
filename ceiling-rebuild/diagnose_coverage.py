# diagnose_coverage.py
# ============================================================
# Why do large areas end up with no ceiling?
#
# Works on the CURRENT UI document in its present state. Takes the floor slab as the building
# footprint, grids it, and classifies every sample point: under a ceiling / inside a wall /
# an open gap. Then, for the biggest gaps, it test-places a Room at that point inside a
# ROLLED-BACK transaction and reports the resulting Area - a Room with Area 0 proves the space
# is not enclosed, which is why NewRooms2 refuses to put a room there.
#
# Also counts walls with Room Bounding switched OFF, the usual cause of rooms leaking.
# Nothing is committed.
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

GRID_FT = 0.75          # ~230 mm sample spacing
MAX_GAP_CLUSTERS = 8


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


def bottom_face_loops(e):
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
    loops.sort(key=poly_area, reverse=True)
    return loops


res = {"doc": doc.Title}

# --- walls: room bounding ------------------------------------------------------------
total_walls, non_bounding, wall_rects = 0, 0, []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    total_walls += 1
    try:
        p = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
        if p is not None and p.AsInteger() != 1:
            non_bounding += 1
    except Exception:
        pass
    try:
        bb = w.get_BoundingBox(None)
        if bb is not None:
            wall_rects.append((bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y))
    except Exception:
        pass
res["walls"] = {"total": total_walls, "room_bounding_off": non_bounding}

# --- ceilings ------------------------------------------------------------------------
ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    loops = bottom_face_loops(c)
    if not loops:
        continue
    try:
        cat = c.Category.Name
    except Exception:
        cat = "?"
    ceilings.append({"id": eid_value(c.Id), "cat": cat, "outer": loops[0], "holes": loops[1:]})
res["ceiling_count"] = len(ceilings)
res["ceiling_area_sf"] = round(sum(poly_area(c["outer"]) for c in ceilings), 1)

# --- footprint from the floor slab ----------------------------------------------------
foot = None
best_a = 0.0
for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
    loops = bottom_face_loops(fl)
    if not loops:
        continue
    a = poly_area(loops[0])
    if a > best_a:
        best_a, foot = a, loops[0]
res["footprint_area_sf"] = round(best_a, 1)

if foot is None:
    res["error"] = "no floor slab found to use as a footprint"
    OUT = res
else:
    xs = [p[0] for p in foot]
    ys = [p[1] for p in foot]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    under_ceiling = in_wall = gap = 0
    gap_pts = []
    y = y0
    while y <= y1:
        x = x0
        while x <= x1:
            if point_in_polygon(x, y, foot):
                hit = False
                for c in ceilings:
                    if point_in_polygon(x, y, c["outer"]):
                        hit = True
                        break
                if hit:
                    under_ceiling += 1
                else:
                    inw = False
                    for (ax0, ay0, ax1, ay1) in wall_rects:
                        if ax0 <= x <= ax1 and ay0 <= y <= ay1:
                            inw = True
                            break
                    if inw:
                        in_wall += 1
                    else:
                        gap += 1
                        gap_pts.append((x, y))
            x += GRID_FT
        y += GRID_FT

    cell = GRID_FT * GRID_FT
    total = under_ceiling + in_wall + gap
    res["sampling"] = {
        "grid_ft": GRID_FT,
        "samples_in_footprint": total,
        "under_ceiling_sf": round(under_ceiling * cell, 1),
        "inside_wall_sf": round(in_wall * cell, 1),
        "OPEN_GAP_sf": round(gap * cell, 1),
        "pct_covered": round(100.0 * under_ceiling / max(total, 1), 1),
    }

    # cluster the gap points so the report names places, not thousands of dots
    clusters = []
    unassigned = list(gap_pts)
    reach = GRID_FT * 1.6
    while unassigned and len(clusters) < 200:
        seed = unassigned.pop()
        comp = [seed]
        frontier = [seed]
        while frontier:
            fx, fy = frontier.pop()
            still = []
            for p in unassigned:
                if abs(p[0] - fx) <= reach and abs(p[1] - fy) <= reach:
                    comp.append(p)
                    frontier.append(p)
                else:
                    still.append(p)
            unassigned = still
        cxs = [p[0] for p in comp]
        cys = [p[1] for p in comp]
        clusters.append({
            "approx_area_sf": round(len(comp) * cell, 1),
            "centroid": [round(sum(cxs) / len(cxs), 2), round(sum(cys) / len(cys), 2)],
            "bbox_ft": [round(min(cxs), 1), round(min(cys), 1), round(max(cxs), 1), round(max(cys), 1)],
        })
    clusters.sort(key=lambda c: -c["approx_area_sf"])
    res["gap_clusters"] = clusters[:MAX_GAP_CLUSTERS]

    # --- are those gaps enclosed at all? test-place a room, then roll everything back ---
    probes = []
    t = None
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        t = Transaction(doc, "ORIGIN gap probe (rolled back)")
        fho = t.GetFailureHandlingOptions()
        try:
            fho.SetForcedModalHandling(False)
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        t.Start()

        levels = sorted(FilteredElementCollector(doc).OfClass(Level)
                        .WhereElementIsNotElementType(), key=lambda l: l.Elevation)
        lv = levels[0] if levels else None
        for cl in res["gap_clusters"]:
            row = {"centroid": cl["centroid"], "approx_area_sf": cl["approx_area_sf"]}
            try:
                r = doc.Create.NewRoom(lv, UV(cl["centroid"][0], cl["centroid"][1]))
                doc.Regenerate()
                row["room_created"] = r is not None
                row["room_area_sf"] = round(r.Area, 2) if r is not None else None
                row["enclosed"] = bool(r is not None and r.Area and r.Area > 0)
            except Exception as ex:
                row["room_created"] = False
                row["error"] = str(ex)[:200]
            probes.append(row)
    except Exception:
        res["probe_error"] = traceback.format_exc()
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
    res["gap_probes"] = probes

    OUT = res
