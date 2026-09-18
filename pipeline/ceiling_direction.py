# ceiling_direction.py
# ============================================================
# ONE rule for ceiling panel direction, for every env.
#
# The problem it fixes: origin_ceiling_assembly_v1's FURRING_RUN_NS is a module-level constant -
# a single value for the whole document, chosen by hand. Nothing in the generator looks at the
# building, so the direction is right on the envs that happen to suit the hard-coded value and
# 90 degrees wrong on the rest.
#
# The rule (user's, 2026-09-17):
#
#     Furring runs ALONG the direction you walk in through the site's main/exit door.
#     Boards therefore run ACROSS it - boards always cross their framing, so fixing one fixes
#     both.
#
# Finding the main door:
#   1. Every OST_Doors instance in the document. These envs really do carry them - 13e has 12,
#      Project7 has 8, and the wall generator already names them DR-<wall><letter>.
#   2. A door is EXTERIOR when it sits within EXTERIOR_BAND_M of the building footprint
#      boundary. The main entrance is at the edge of the site by definition.
#   3. Of the exterior doors, the WIDEST one wins - the main entrance is the widest door on the
#      perimeter.
#   4. Its FacingOrientation is the walk-in direction. Snapped to the nearer world axis, because
#      the generator's whole layout core (board grid, wall clipping, wall-severing splits, mains)
#      assumes axis-aligned rectangles. `off_axis_deg` in the result says how far the real door
#      was from that axis, so it is visible when a site would need a truly rotated grid.
#
# This module only DECIDES. stage2_panels.py applies it, by patching the FURRING_RUN_NS
# assignment in the generator's source string before exec - the repo file is never modified.
# ============================================================

import math
import re
import traceback

from Autodesk.Revit.DB import *

FT_PER_M = 1.0 / 0.3048
FT_PER_MM = 1.0 / 304.8

CFG = {
    # Absolute ceiling on how far in from the footprint boundary can still count as "at the edge
    # of the site". This ALONE is not enough: 1F's whole plate is 25 x 20 ft, so a flat 2 m band
    # swallowed the entire building and all five of its doors read as exterior - including the
    # one sitting in the middle of the plan, which then won on width.
    "EXTERIOR_BAND_M": 2.0,
    # So the band is really adaptive: exterior means "as close to the boundary as the closest
    # door is, plus this". A door in an exterior wall is a few centimetres from the boundary; the
    # next one in is typically a wall-depth or more away, and that gap is what separates them at
    # any building size. 1F: nearest 0.095 m, next 0.633 m.
    "EDGE_CLUSTER_M": 0.30,
    # If even the nearest door is further in than this, nothing is really in the perimeter and
    # the pick is a guess - say so rather than deciding quietly.
    "NO_PERIMETER_DOOR_M": 1.0,
    # Anything narrower than this is a cupboard or a hatch, not a way in.
    "MIN_DOOR_WIDTH_FT": 2.0,

    # --- fallback for envs with no Door elements (2026-09-18) ------------------------------
    # Six of the envs model a doorway as a bare GAP in the wall with a short header wall above
    # it, and carry no OST_Doors element at all (409 x3, PH2A x2, Project2 - PH1 B). Those
    # headers sit exactly over the openings, so they carry the same two facts a door does: how
    # wide the opening is, and which way you walk through it.
    "HEADER_FALLBACK": True,
    # Bounds on what counts as a doorway header rather than an ordinary upper wall segment.
    # Same numbers the ceiling rebuild uses in close_openings_above_plane, for the same reason:
    # too loose and every upper wall segment is swept up.
    "MAX_DOOR_HEAD_MM": 2600.0,
    "MAX_OPENING_WIDTH_MM": 2500.0,
}


# ------------------------------------------------------------
# Small geometry helpers (world X-Y, feet) - kept local so this module stands alone
# ------------------------------------------------------------

def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        pass
    try:
        return eid.IntegerValue
    except Exception:
        return -1


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _dist_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / L2
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def dist_to_boundary(px, py, poly):
    """Unsigned distance to the polygon's edge. Unsigned on purpose: a door sits in the wall, so
    depending on where the footprint came from it can read as just inside or just outside it."""
    best = None
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        d = _dist_point_segment(px, py, ax, ay, bx, by)
        if best is None or d < best:
            best = d
    return best


def _bottom_loop(e):
    """Largest downward-facing planar face of an element, as a plan polygon."""
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
    return loops[0]


def building_footprint(doc):
    """Outer plan polygon of the site. Floor slabs first (they define the plate), then the
    largest ceiling, then the model's plan bounding box as a rectangle of last resort."""
    best, best_a = None, 0.0
    for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
        loop = _bottom_loop(fl)
        if not loop:
            continue
        a = poly_area(loop)
        if a > best_a:
            best_a, best = a, loop
    if best is not None:
        return best, "largest floor slab ({} sf)".format(round(best_a, 1))

    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        loop = _bottom_loop(c)
        if not loop:
            continue
        a = poly_area(loop)
        if a > best_a:
            best_a, best = a, loop
    if best is not None:
        return best, "largest ceiling ({} sf)".format(round(best_a, 1))

    xs, ys = [], []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            bb = w.get_BoundingBox(None)
            if bb is None:
                continue
            xs.extend([bb.Min.X, bb.Max.X])
            ys.extend([bb.Min.Y, bb.Max.Y])
        except Exception:
            continue
    if xs and ys:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        return ([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                "wall bounding box (no slab or ceiling to read)")
    return None, "none"


# ------------------------------------------------------------
# Doors
# ------------------------------------------------------------

def _door_width_ft(e):
    """Clear width of the opening. The instance parameter wins when it is set (a door can be
    resized per instance); otherwise the type's, otherwise the plan bounding box."""
    for src in (e, None):
        holder = e if src is not None else None
        if holder is None:
            continue
        for bip in (BuiltInParameter.DOOR_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM,
                    BuiltInParameter.GENERIC_WIDTH):
            try:
                p = holder.get_Parameter(bip)
                if p is not None and p.HasValue:
                    v = p.AsDouble()
                    if v and v > 1e-6:
                        return v
            except Exception:
                continue
    try:
        sym = e.Symbol
        for bip in (BuiltInParameter.DOOR_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM,
                    BuiltInParameter.GENERIC_WIDTH):
            p = sym.get_Parameter(bip)
            if p is not None and p.HasValue:
                v = p.AsDouble()
                if v and v > 1e-6:
                    return v
    except Exception:
        pass
    try:
        bb = e.get_BoundingBox(None)
        if bb is not None:
            return max(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y)
    except Exception:
        pass
    return 0.0


def _facing(e):
    """Walk-in direction: the way the door faces. For a wall-hosted door this is already
    perpendicular to the wall. Falls back to the host wall's own normal."""
    try:
        f = e.FacingOrientation
        if f is not None and (abs(f.X) > 1e-9 or abs(f.Y) > 1e-9):
            return (f.X, f.Y), "FacingOrientation"
    except Exception:
        pass
    try:
        host = e.Host
        crv = host.Location.Curve
        a = crv.GetEndPoint(0)
        b = crv.GetEndPoint(1)
        dx, dy = b.X - a.X, b.Y - a.Y
        L = math.hypot(dx, dy)
        if L > 1e-9:
            return (-dy / L, dx / L), "host wall normal"
    except Exception:
        pass
    return None, "none"


def collect_doors(doc, footprint, cfg=None):
    cfg = cfg or CFG
    band_ft = cfg["EXTERIOR_BAND_M"] * FT_PER_M
    out = []
    for e in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors)
              .WhereElementIsNotElementType()):
        row = {"id": eid_value(e.Id)}
        try:
            row["name"] = e.Symbol.Family.Name
        except Exception:
            row["name"] = "?"
        try:
            loc = e.Location
            p = loc.Point
            row["x"], row["y"] = round(p.X, 4), round(p.Y, 4)
        except Exception:
            try:
                bb = e.get_BoundingBox(None)
                row["x"] = round((bb.Min.X + bb.Max.X) / 2.0, 4)
                row["y"] = round((bb.Min.Y + bb.Max.Y) / 2.0, 4)
            except Exception:
                continue
        try:
            row["host_wall_id"] = eid_value(e.Host.Id)
        except Exception:
            row["host_wall_id"] = -1

        w = _door_width_ft(e)
        row["width_ft"] = round(w, 4)
        row["width_mm"] = round(w * 304.8, 1)

        facing, how = _facing(e)
        row["facing"] = None if facing is None else (round(facing[0], 6), round(facing[1], 6))
        row["facing_source"] = how

        if footprint:
            d = dist_to_boundary(row["x"], row["y"], footprint)
            row["dist_to_edge_ft"] = round(d, 3)
            row["dist_to_edge_m"] = round(d / FT_PER_M, 3)
            row["exterior"] = d <= band_ft
        else:
            row["dist_to_edge_ft"] = None
            row["exterior"] = False

        row["usable"] = (facing is not None and w >= cfg["MIN_DOOR_WIDTH_FT"])
        out.append(row)
    return out


# ------------------------------------------------------------
# The decision
# ------------------------------------------------------------

def _lowest_storey_plane(doc):
    """The elevation Revit measures rooms at, on the lowest level that actually has walls.

    Every env in this set is single-storey (the ceiling rebuild's storey classifier skips the
    upper levels on all of them), so one plane is enough. On a genuine multi-storey model this
    would only find the ground floor's doorways - acceptable, since the site's main entrance is
    on the ground floor by definition.
    """
    levels = list(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType())
    levels.sort(key=lambda lv: lv.Elevation)
    counts = {}
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            lid = eid_value(w.LevelId)
            counts[lid] = counts.get(lid, 0) + 1
        except Exception:
            continue
    for lv in levels:
        if counts.get(eid_value(lv.Id), 0) > 0:
            try:
                p = lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
                return lv.Elevation + (p.AsDouble() if p else 0.0), lv.Name
            except Exception:
                return lv.Elevation, lv.Name
    return None, None


def collect_header_openings(doc, footprint, cfg=None):
    """Doorways in envs that carry no Door element, found by their header walls.

    These models cut a real GAP in the wall and put a short header wall above it. At the height
    Revit measures rooms there is simply nothing in the opening - which is why the ceiling
    rebuild has to trace those headers down to close them. The same header tells us what a door
    would have: it is exactly as long as the opening and sits exactly over it.

    A candidate is a header when it starts ABOVE the room computation plane, its underside is
    below MAX_DOOR_HEAD_MM (a door head, not high up the storey), it is no longer than
    MAX_OPENING_WIDTH_MM, and the plane underneath it is EMPTY. That last test is what makes it
    an opening rather than an ordinary wall stacked on another wall.

    Returns rows in exactly the shape collect_doors returns, so the same decision runs on both.
    """
    cfg = cfg or CFG
    plane_ft, level_name = _lowest_storey_plane(doc)
    if plane_ft is None:
        return []

    head_cap_ft = plane_ft + cfg["MAX_DOOR_HEAD_MM"] * FT_PER_MM
    max_len_ft = cfg["MAX_OPENING_WIDTH_MM"] * FT_PER_MM
    band_ft = cfg["EXTERIOR_BAND_M"] * FT_PER_M

    walls = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            bb = w.get_BoundingBox(None)
            if bb is None:
                continue
            walls.append((w, bb))
        except Exception:
            continue

    # Walls that DO exist at the plane. A candidate sitting over one of these is an ordinary
    # wall above a wall, not an opening.
    at_plane = []
    for (w, bb) in walls:
        if bb.Min.Z <= plane_ft + 1e-6 <= bb.Max.Z + 1e-6:
            at_plane.append((bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y))

    def _covered(mx, my):
        pad = 0.05
        for (x0, y0, x1, y1) in at_plane:
            if x0 - pad <= mx <= x1 + pad and y0 - pad <= my <= y1 + pad:
                return True
        return False

    out = []
    for (w, bb) in walls:
        try:
            rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
            if rb is not None and rb.AsInteger() != 1:
                continue
            if not (bb.Min.Z > plane_ft + 1e-6 and bb.Min.Z < head_cap_ft - 1e-6):
                continue
            loc = w.Location
            crv = loc.Curve if isinstance(loc, LocationCurve) else None
            if crv is None:
                continue
            a = crv.GetEndPoint(0)
            b = crv.GetEndPoint(1)
            span = a.DistanceTo(b)
            if span < 0.01 or span > max_len_ft:
                continue
            mx, my = (a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0
            if _covered(mx, my):
                continue

            # You walk through an opening perpendicular to the wall it is cut into.
            dx, dy = b.X - a.X, b.Y - a.Y
            L = math.hypot(dx, dy)
            if L < 1e-9:
                continue
            facing = (-dy / L, dx / L)

            row = {
                "id": eid_value(w.Id),
                "name": "doorway header (no Door element)",
                "x": round(mx, 4), "y": round(my, 4),
                "host_wall_id": eid_value(w.Id),
                "width_ft": round(span, 4),
                "width_mm": round(span * 304.8, 1),
                "facing": (round(facing[0], 6), round(facing[1], 6)),
                "facing_source": "header wall normal",
                "header_underside_mm": round(bb.Min.Z * 304.8, 1),
            }
            if footprint:
                d = dist_to_boundary(mx, my, footprint)
                row["dist_to_edge_ft"] = round(d, 3)
                row["dist_to_edge_m"] = round(d / FT_PER_M, 3)
                row["exterior"] = d <= band_ft
            else:
                row["dist_to_edge_ft"] = None
                row["exterior"] = False
            row["usable"] = span >= cfg["MIN_DOOR_WIDTH_FT"]
            out.append(row)
        except Exception:
            continue
    return out


def decide_from_doors(doors, cfg=None):
    """The decision itself, given door rows: which way does the ceiling framing run.

    Pure - no Revit, no document. Split out from resolve_direction precisely so this can be
    exercised offline against synthetic sites, which is the only way to check the rule holds
    across many envs without opening each one.
    """
    cfg = cfg or CFG
    res = {"ok": False, "furring_run_ns": None, "warnings": []}
    res["doors_total"] = len(doors)

    if not doors:
        res["reason"] = ("no OST_Doors elements in this document - the doorways are probably "
                         "modelled as bare gaps with a header wall above")
        return res

    usable = [d for d in doors if d["usable"]]
    if not usable:
        res["reason"] = "no door is both wide enough and has a readable facing direction"
        return res

    # Which doors are in the perimeter. Adaptive, not a fixed band: take the closest door to the
    # boundary and keep everything clustered with it. On a small plate a fixed band is the whole
    # building, and the widest INTERIOR door then wins - which is exactly how 1F went wrong.
    known = [d for d in usable if d.get("dist_to_edge_m") is not None]
    if known:
        nearest = min(d["dist_to_edge_m"] for d in known)
        band = min(cfg["EXTERIOR_BAND_M"], nearest + cfg["EDGE_CLUSTER_M"])
        res["edge_band_m"] = round(band, 3)
        res["nearest_door_m"] = round(nearest, 3)
        for d in usable:
            dm = d.get("dist_to_edge_m")
            d["exterior"] = (dm is not None and dm <= band + 1e-9)
        if nearest > cfg["NO_PERIMETER_DOOR_M"]:
            res["warnings"].append(
                "closest door is {} m from the footprint edge - none of them is really in an "
                "exterior wall, so the main door is a guess".format(round(nearest, 2)))

    exterior = [d for d in usable if d.get("exterior")]
    pool, pool_name = exterior, "exterior"
    if not pool:
        pool, pool_name = usable, "all (none within the edge band)"
        res["warnings"].append(
            "no door within {} m of the footprint edge - falling back to the widest door "
            "anywhere, which may not be the main entrance".format(cfg["EXTERIOR_BAND_M"]))

    # Widest wins among the perimeter doors; distance breaks a tie between equal widths, so two
    # identical doors in the same outer wall still give a stable, repeatable answer.
    pool = sorted(pool, key=lambda d: (-d["width_ft"], d.get("dist_to_edge_m") or 0.0))
    main = pool[0]
    res["main_door"] = main
    res["candidates"] = pool[:5]
    res["pool"] = pool_name

    fx, fy = main["facing"]
    # Snap to the nearer world axis. The generator's layout core works in axis-aligned
    # rectangles throughout, so these are the only two answers it can actually build.
    axis = "x" if abs(fx) >= abs(fy) else "y"
    res["walk_in_axis"] = axis

    # How far the real door was from that axis - 0 means perfectly aligned, 45 means the snap
    # was a coin toss and this site would need a genuinely rotated grid.
    ang = math.degrees(math.atan2(abs(fy), abs(fx)))
    res["off_axis_deg"] = round(ang if axis == "x" else 90.0 - ang, 2)
    if res["off_axis_deg"] > 20.0:
        res["warnings"].append(
            "main door faces {} deg off the {} axis - the snapped grid is a poor fit and this "
            "site would need a rotated layout".format(res["off_axis_deg"], axis.upper()))

    # Furring runs ALONG the walk-in direction (user's rule, 2026-09-17), so the boards - which
    # always cross their framing - run across it.
    #   FURRING_RUN_NS True  -> furring along X  (boards' long edge along Y)
    #   FURRING_RUN_NS False -> furring along Y  (boards' long edge along X)
    res["furring_run_ns"] = (axis == "x")
    res["furring_runs_along"] = axis.upper()
    res["boards_long_edge_along"] = "Y" if axis == "x" else "X"
    res["ok"] = True
    res["reason"] = ("widest {} door: {} mm wide, {} m from the edge, facing ({}, {}) -> walk-in "
                     "along {}".format(pool_name, main["width_mm"], main.get("dist_to_edge_m"),
                                       round(fx, 3), round(fy, 3), axis.upper()))
    return res


def resolve_direction(doc, cfg=None):
    """Which way the ceiling framing should run in THIS document.

    `furring_run_ns` is the value to patch into the generator, and is None when no door could
    decide it - the caller then leaves the generator's own default alone.
    """
    cfg = cfg or CFG
    footprint, fsrc = building_footprint(doc)

    doors = collect_doors(doc, footprint, cfg)
    res = decide_from_doors(doors, cfg)
    res["source"] = "Door elements"
    res["doors"] = doors

    # No usable Door element: try the doorway HEADERS instead. Six envs model every doorway as
    # a bare gap with a header above and carry no Door at all, and those headers hold the same
    # two facts - how wide the opening is and which way you walk through it.
    if not res.get("ok") and cfg.get("HEADER_FALLBACK", True):
        headers = collect_header_openings(doc, footprint, cfg)
        if headers:
            alt = decide_from_doors(headers, cfg)
            alt["source"] = "doorway headers (this model has no Door elements)"
            alt["doors"] = headers
            alt["door_attempt"] = res.get("reason")
            if alt.get("ok"):
                alt["footprint_source"] = fsrc
                if not footprint:
                    alt["warnings"].append(
                        "no footprint could be built - every opening counts as interior")
                return alt
            # Neither worked; report the header attempt too rather than only the door one.
            res["header_attempt"] = alt.get("reason")
            res["headers_found"] = len(headers)

    res["footprint_source"] = fsrc
    if not footprint:
        res["warnings"].append("no footprint could be built - every door counts as interior")
    return res


def apply_to_source(doc, src, cfg=None):
    """Rewrite FURRING_RUN_NS in the ceiling generator's SOURCE STRING for this document.

    The single place the rule is applied, so every route into the generator gets it: stage 2,
    the origin CLI, the standalone ceiling batch and the live wrapper. Before this existed the
    rule lived in stage2_panels only, and the two routes that exec the generator directly kept
    the hard-coded default.

    The generator file on disk is NEVER modified - it belongs to a separate repository. Only the
    string about to be compiled is touched.

    Returns (src, info). When the direction cannot be resolved, src comes back unchanged and the
    generator's own default applies: a model with no doorway to read must not stop the panels.
    """
    info = {"applied": False}
    try:
        res = resolve_direction(doc, cfg)
        # The full opening list can be long; keep the decision and the runners-up.
        info["decision"] = dict((k, v) for k, v in res.items() if k != "doors")
        info["summary"] = describe(res)

        want = res.get("furring_run_ns")
        if want is None:
            info["skipped"] = res.get("reason")
            return src, info

        pat = re.compile(r"^(FURRING_RUN_NS)\s*=\s*[^\n#]+", re.MULTILINE)
        m = pat.search(src)
        if m is None:
            info["skipped"] = "no FURRING_RUN_NS assignment found in the generator"
            return src, info

        info["was"] = m.group(0).split("=", 1)[1].strip()
        info["now"] = str(want)
        src = pat.sub("FURRING_RUN_NS = " + str(want), src, count=1)
        info["applied"] = True
    except Exception:
        # Never let direction resolution take a panel run down with it.
        info["error"] = traceback.format_exc()[-800:]
    return src, info


def describe(res):
    if not res.get("ok"):
        msg = "ceiling direction: UNRESOLVED - {}".format(res.get("reason"))
        if res.get("header_attempt"):
            msg += " (and {} doorway header(s): {})".format(
                res.get("headers_found"), res["header_attempt"])
        return msg
    src = res.get("source") or "Door elements"
    return ("ceiling direction: furring along {}, boards' long edge along {} "
            "(FURRING_RUN_NS={}) - via {} - {}".format(
                res["furring_runs_along"], res["boards_long_edge_along"],
                res["furring_run_ns"], src, res["reason"]))
