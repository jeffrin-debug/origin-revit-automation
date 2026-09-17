# origin_ceiling_rebuild_core.py
# ============================================================
# Pure logic for the per-room ceiling rebuild. Every function takes `doc` as an argument, so
# this behaves identically on the live UI document and on a background document opened by the
# batch driver. Nothing here reads DocumentManager.
#
# Loaded by the bridge scripts with exec(compile(open(path).read(), path, "exec"), ns) rather
# than `import` - Dynamo caches sys.modules across ticks and a stale module is a silent,
# expensive class of bug.
#
# Geometry helpers (poly_area / poly_bbox / point_in_polygon / eid_value / get_ceiling_loops)
# are copied from origin_ceiling_assembly_v1.py rather than imported, to keep this standalone.
# ============================================================

import math
import traceback

from Autodesk.Revit.DB import *
from System.Collections.Generic import List as NetList

# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

CFG = {
    # A region smaller than this is reported as a tiny_region but still gets a ceiling.
    "MIN_REGION_SF": 1.0,
    # A ceiling counts as "already correct" for a region when it covers exactly that region
    # and its area agrees within max(ABS, PCT * region area).
    "AREA_MATCH_ABS_SF": 0.02,
    "AREA_MATCH_PCT": 0.005,
    # Probe points per region used for both matching and the final coverage proof.
    "PROBE_GRID": 5,
    "PROBE_TARGET": 9,
    # The blanket is frequently modelled as a Ceiling element in the "Roof Soffits" category
    # (12M_FR_11's 602 sf one is). Treating those as untouchable leaves the bug in place, so
    # they are candidates for matching and deletion like any other ceiling. They are still
    # never used as a TYPE source for new ceilings - that category swap silently no-ops.
    "INCLUDE_SOFFIT_CATEGORY": True,
    # Used only when an env has NO already-correct ceiling to copy a height from, and its
    # blanket sits at a level elevation (slab/roof) so is useless as a reference. 2743.2 mm
    # (9 ft) is the ceiling height in 10C-Env_14, 12M_FR_11, 13e, Project8 and Project11.
    "DEFAULT_CEILING_HEIGHT_MM": 2743.2,
    # Preferred type when an env has no ceiling of its own to copy one from. A "Generic"
    # CeilingType has no compound structure, so it builds a zero-thickness ceiling with no
    # downward face - invisible to geometry reads and useless to the drywall pipeline.
    "PREFERRED_CEILING_TYPE_NAMES": ["GWB on Mtl. Stud", "Compound Ceiling", "GWB"],
    # Bounds on what counts as a doorway header worth tracing down to the room computation
    # plane. Too loose and ordinary upper wall segments get traced too, flooding the model with
    # separation lines and sliver regions.
    "MAX_DOOR_HEAD_MM": 2600.0,
    "MAX_OPENING_WIDTH_MM": 2500.0,

    # --- authored-ceiling mode (2026-09-17) -----------------------------------------------
    # A ceiling sitting more than this far below ITS OWN room's wall top was dropped there
    # deliberately by whoever modelled the env, and is kept exactly as it is. Anything nearer
    # the wall top than this is part of the top layer - modelling noise, not design intent.
    "AUTHORED_DROP_MIN_MM": 50.0,
    # How to reduce the tops of the walls bounding one room to a single number:
    #   "modal" - most common top, so one odd wall cannot skew the room (default)
    #   "max"   - the highest wall, so the ceiling is never below any of them
    #   "min"   - flush with the lowest wall
    "ROOM_WALL_TOP_RULE": "modal",
    # How close a created ceiling must land to its room's wall top, and how far below it is
    # allowed to sit at all ("it should not be below the wall level").
    "WALL_TOP_TOL_MM": 1.0,
}

FT_PER_MM = 1.0 / 304.8


# ------------------------------------------------------------
# Portability helpers
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


def elem_name(doc, eid):
    """Element.Name resolves inconsistently across Dynamo's Python engines for ElementTypes,
    so fall back to the name parameter rather than reporting '?'."""
    try:
        e = doc.GetElement(eid)
    except Exception:
        return "?"
    if e is None:
        return "?"
    try:
        n = e.Name
        if n:
            return n
    except Exception:
        pass
    for bip in (BuiltInParameter.SYMBOL_NAME_PARAM, BuiltInParameter.ALL_MODEL_TYPE_NAME):
        try:
            p = e.get_Parameter(bip)
            if p is not None:
                s = p.AsString()
                if s:
                    return s
        except Exception:
            continue
    return "?"


# ------------------------------------------------------------
# 2D polygon helpers (world X-Y, feet)
# ------------------------------------------------------------

def poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def point_in_polygon(px, py, poly):
    """Ray-casting point-in-polygon. poly = list of (x, y)."""
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


def rects_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def point_in_region(px, py, outer, holes):
    if not point_in_polygon(px, py, outer):
        return False
    for h in (holes or []):
        if point_in_polygon(px, py, h):
            return False
    return True


def probe_points(outer, holes, grid=None, target=None):
    """Points guaranteed strictly inside a region, used both to match existing ceilings and to
    prove coverage afterwards. Centroid first (when it is actually inside - it is not, for an
    L-shaped room), then a grid sampled across the bbox, filtered through the real polygon."""
    grid = grid or CFG["PROBE_GRID"]
    target = target or CFG["PROBE_TARGET"]
    x0, y0, x1, y1 = poly_bbox(outer)
    pts = []

    cx = sum(p[0] for p in outer) / float(len(outer))
    cy = sum(p[1] for p in outer) / float(len(outer))
    if point_in_region(cx, cy, outer, holes):
        pts.append((cx, cy))

    for gi in (grid, grid * 3):
        for i in range(gi):
            for j in range(gi):
                px = x0 + (x1 - x0) * (i + 0.5) / gi
                py = y0 + (y1 - y0) * (j + 0.5) / gi
                if point_in_region(px, py, outer, holes):
                    pts.append((px, py))
                    if len(pts) >= target:
                        return pts
        if len(pts) >= 3:
            break
    return pts


# ------------------------------------------------------------
# Levels, phases, types
# ------------------------------------------------------------

def collect_levels(doc):
    levels = list(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType())
    levels.sort(key=lambda lv: lv.Elevation)
    return levels


def level_info(doc, lv):
    row = {"id": eid_value(lv.Id), "name": lv.Name,
           "elev_ft": round(lv.Elevation, 4), "elev_mm": round(lv.Elevation * 304.8, 1)}
    try:
        p = lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
        row["room_computation_height_mm"] = round(p.AsDouble() * 304.8, 1) if p else None
    except Exception:
        row["room_computation_height_mm"] = None
    return row


def pick_phase(doc, level):
    """Rooms must sit in a phase where the bounding walls exist. Take the most common
    CreatedPhaseId over that level's room-bounding walls; fall back to the last phase.
    The ActiveView-based lookup is unavailable on a background document."""
    counts = {}
    try:
        for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            try:
                if eid_value(w.LevelId) != eid_value(level.Id):
                    continue
                rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
                if rb is not None and rb.AsInteger() != 1:
                    continue
                pid = eid_value(w.CreatedPhaseId)
                counts[pid] = counts.get(pid, 0) + 1
            except Exception:
                continue
    except Exception:
        pass
    if counts:
        best = sorted(counts.items(), key=lambda kv: -kv[1])[0][0]
        try:
            ph = doc.GetElement(ElementId(best))
            if ph is not None:
                return ph, "wall CreatedPhaseId (n={})".format(counts[best])
        except Exception:
            pass
    try:
        phs = doc.Phases
        return phs.get_Item(phs.Size - 1), "last phase"
    except Exception:
        return None, "none"


def modal_top_mm(tops):
    """Reduce a set of wall-top elevations (mm) to the single one to build against.

    5 mm buckets absorb modelling noise, but the value RETURNED is the exact most-common
    elevation inside the winning bucket, never the bucket centre - ceilings get built at this
    number and a 2 mm rounding error would be baked into the model.

    Returns (modal_exact_mm, members_of_that_bucket) or (None, []) for an empty input.
    """
    if not tops:
        return None, []
    buckets = {}
    for t in tops:
        k = round(t / 5.0) * 5.0
        buckets.setdefault(k, []).append(t)
    modal_key, modal_vals = sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0]
    counts = {}
    for v in modal_vals:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0], modal_vals


def wall_top_stats(doc, level):
    """Where the walls on a level actually end, in absolute mm. Taken from each wall's model
    bounding box rather than base offset + unconnected height, so it is correct regardless of
    top constraints, joins, or how the wall was constrained."""
    tops = []
    lid = eid_value(level.Id)
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            if eid_value(w.LevelId) != lid:
                continue
            bb = w.get_BoundingBox(None)
            if bb is None:
                continue
            tops.append(round(bb.Max.Z * 304.8, 1))
        except Exception:
            continue
    if not tops:
        return {"wall_count": 0}
    modal_exact, modal_vals = modal_top_mm(tops)
    return {
        "wall_count": len(tops),
        "min_mm": min(tops),
        "max_mm": max(tops),
        "modal_top_mm": modal_exact,
        "modal_share": round(100.0 * len(modal_vals) / len(tops), 1),
        "modal_top_above_level_mm": round(modal_exact - level.Elevation * 304.8, 1),
        "distinct_tops_mm": sorted(set(tops)),
    }


def floor_plan_vft_id(doc):
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if vft.ViewFamily == ViewFamily.FloorPlan:
                return vft.Id
        except Exception:
            continue
    return None


def is_ceiling_category(e):
    """True only for the real Ceilings category. OfClass(Ceiling) also returns Roof Soffits
    elements; a type from that category can never be assigned to a Ceilings element (the set
    silently no-ops), so this gates TYPE selection."""
    try:
        return eid_value(e.Category.Id) == int(BuiltInCategory.OST_Ceilings)
    except Exception:
        try:
            return e.Category.Name == "Ceilings"
        except Exception:
            return False


def is_candidate_ceiling(row, cfg=None):
    """Whether an element participates in matching/deletion at all - broader than
    is_ceiling_category, because the blanket is often a Roof Soffit."""
    cfg = cfg or CFG
    if row.get("is_ceiling_category"):
        return True
    return bool(cfg.get("INCLUDE_SOFFIT_CATEGORY"))


# ------------------------------------------------------------
# Ceiling geometry
# ------------------------------------------------------------

def get_ceiling_loops(doc, ceiling, warnings):
    """(loops, z) with the LARGEST-area loop first (outer) and the rest holes; z = bottom-face
    elevation. Read from the downward-facing planar face of the ceiling solid."""
    opt = Options()
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False
    try:
        opt.DetailLevel = ViewDetailLevel.Medium
    except Exception:
        pass

    best_face = None
    best_z = None
    try:
        geo = ceiling.get_Geometry(opt)
        for g in geo:
            solid = g if isinstance(g, Solid) else None
            if solid is None or solid.Volume <= 0:
                continue
            for face in solid.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                if face.FaceNormal.Z < -0.9:          # downward-facing = room-side bottom face
                    z = face.Origin.Z
                    if best_face is None or z < best_z:
                        best_face = face
                        best_z = z
    except Exception as ex:
        warnings.append("Ceiling {}: geometry read failed ({})".format(eid_value(ceiling.Id), ex))
        return None, None

    if best_face is None:
        return None, None

    loops = []
    try:
        for cl in best_face.GetEdgesAsCurveLoops():
            pts = []
            for c in cl:
                try:
                    tess = c.Tessellate()
                except Exception:
                    tess = [c.GetEndPoint(0), c.GetEndPoint(1)]
                for p in tess:
                    if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                        pts.append((p.X, p.Y))
            if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                pts = pts[:-1]
            if len(pts) >= 3:
                loops.append(pts)
    except Exception as ex:
        warnings.append("Ceiling {}: loop extraction failed ({})".format(eid_value(ceiling.Id), ex))
        return None, None

    if not loops:
        return None, None
    loops.sort(key=poly_area, reverse=True)
    return loops, best_z


def collect_ceilings(doc, warnings):
    """Every Ceiling-class element with its plan polygon and the two independent area numbers.
    HOST_AREA_COMPUTED is Revit's own; poly_area is ours. Disagreement means the element is not
    a plain flat ceiling (sloped, multi-region, self-overlapping sketch) - quarantine, not guess."""
    out = []
    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        row = {"id": eid_value(c.Id), "is_ceiling_category": is_ceiling_category(c)}
        try:
            row["category"] = c.Category.Name
        except Exception:
            row["category"] = "?"
        try:
            row["type_id"] = eid_value(c.GetTypeId())
            row["type"] = elem_name(doc, c.GetTypeId())
        except Exception:
            row["type_id"], row["type"] = -1, "?"
        try:
            row["level_id"] = eid_value(c.LevelId)
        except Exception:
            row["level_id"] = -1
        try:
            p = c.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)
            row["area_sf"] = round(p.AsDouble(), 4) if p else None
        except Exception:
            row["area_sf"] = None
        try:
            p = c.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
            row["offset_ft"] = round(p.AsDouble(), 5) if p else None
            row["offset_mm"] = round(p.AsDouble() * 304.8, 1) if p else None
        except Exception:
            row["offset_ft"], row["offset_mm"] = None, None
        try:
            row["is_sketch_based"] = eid_value(c.SketchId) > 0
        except Exception:
            row["is_sketch_based"] = None

        loops, z = get_ceiling_loops(doc, c, warnings)
        if loops:
            row["outer"] = loops[0]
            row["holes"] = loops[1:]
            row["poly_area_sf"] = round(poly_area(loops[0]) - sum(poly_area(h) for h in loops[1:]), 4)
            row["bbox"] = poly_bbox(loops[0])
            row["bottom_z_ft"] = round(z, 5)
            row["loop_count"] = len(loops)
            if row["area_sf"]:
                d = abs(row["poly_area_sf"] - row["area_sf"])
                row["area_disagreement_pct"] = round(100.0 * d / max(row["area_sf"], 1e-9), 3)
        else:
            row["outer"], row["holes"] = None, []
            row["poly_area_sf"] = None
        try:
            deps = list(c.GetDependentElements(None))
            hosted = []
            for did in deps:
                de = doc.GetElement(did)
                if isinstance(de, FamilyInstance):
                    try:
                        hosted.append({"id": eid_value(did), "category": de.Category.Name})
                    except Exception:
                        hosted.append({"id": eid_value(did), "category": "?"})
            row["hosted_family_instances"] = hosted
        except Exception:
            row["hosted_family_instances"] = []
        out.append(row)
    return out


# ------------------------------------------------------------
# Regions (rooms -> outer regions)
# ------------------------------------------------------------

def room_regions(doc, room, warnings):
    """A room's boundary at FINISH faces, split into disjoint OUTER regions each with its holes.
    'Largest loop is outer, rest are holes' is wrong when a room has two disjoint parts, so
    loops are classified by containment instead."""
    opts = SpatialElementBoundaryOptions()
    try:
        opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
    except Exception:
        pass
    try:
        loops = room.GetBoundarySegments(opts)
    except Exception as ex:
        warnings.append("Room {}: GetBoundarySegments failed ({})".format(eid_value(room.Id), ex))
        return []

    polys = []
    for loop in (loops or []):
        pts = []
        # The elements PRODUCING this boundary - the walls the room actually stops against.
        # Kept so the ceiling height can be measured from this room's own walls rather than
        # from every wall on the level; separation lines land here too and are filtered out
        # later by class, not by id.
        bounding = set()
        for seg in loop:
            try:
                for p in seg.GetCurve().Tessellate():
                    if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                        pts.append((p.X, p.Y))
            except Exception:
                continue
            try:
                bid = eid_value(seg.ElementId)
                if bid > 0:
                    bounding.add(bid)
            except Exception:
                pass
        if len(pts) >= 3 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) >= 3:
            polys.append((pts, bounding))
    if not polys:
        return []

    polys.sort(key=lambda pb: poly_area(pb[0]), reverse=True)
    outers = []          # list of [outer, [holes...], bounding_ids]
    for p, bounding in polys:
        cx = sum(q[0] for q in p) / float(len(p))
        cy = sum(q[1] for q in p) / float(len(p))
        placed = False
        for grp in outers:
            if point_in_polygon(cx, cy, grp[0]) and point_in_polygon(p[0][0], p[0][1], grp[0]):
                grp[1].append(p)
                grp[2] |= bounding
                placed = True
                break
        if not placed:
            outers.append([p, [], set(bounding)])

    regions = []
    for outer, holes, bounding in outers:
        area = poly_area(outer) - sum(poly_area(h) for h in holes)
        regions.append({
            "room_id": eid_value(room.Id),
            "room_name": _room_name(room),
            "room_number": _safe(lambda: room.Number, ""),
            "level_id": _safe(lambda: eid_value(room.LevelId), -1),
            "room_area_sf": round(_safe(lambda: room.Area, 0.0), 4),
            "outer": outer,
            "holes": holes,
            "bounding_element_ids": sorted(bounding),
            "poly_area_sf": round(area, 4),
            "bbox": poly_bbox(outer),
        })
    return regions


def _room_name(room):
    """Room.Name resolves inconsistently under Dynamo's Python engines; the parameter does not."""
    for bip in (BuiltInParameter.ROOM_NAME, BuiltInParameter.ROOM_NUMBER):
        try:
            p = room.get_Parameter(bip)
            if p is not None:
                s = p.AsString()
                if s:
                    return s
        except Exception:
            continue
    return "Room {}".format(eid_value(room.Id))


def _safe(fn, default):
    try:
        v = fn()
        return v if v is not None else default
    except Exception:
        return default


def collect_regions(doc, warnings):
    """All outer regions in the document, from whatever Rooms are currently placed."""
    regions = []
    for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
              .WhereElementIsNotElementType()):
        try:
            if r.Area is None or r.Area <= 0.0:
                warnings.append("Room {} skipped: not enclosed / zero area".format(eid_value(r.Id)))
                continue
        except Exception:
            continue
        regions.extend(room_regions(doc, r, warnings))
    # A room can yield several disjoint outer regions, so room_id is not a key. Everything
    # downstream is keyed on this index instead.
    for i, r in enumerate(regions):
        r["idx"] = i
    return regions


def region_wall_top_ft(doc, region, cfg=None):
    """Absolute elevation (ft) of the top of the walls bounding ONE room.

    This is where a ceiling cut out of the blanket sits: flush with the end of that room's own
    walls, never below them. Measured per room rather than per level because a perimeter room's
    exterior wall runs to the roof while the partitions around an interior room stop at ceiling
    height - a single number for the whole floor cannot be right for both, and taking the
    level-wide modal value is what previously buried ceilings in the roof slab.

    Tops come from the wall's model bounding box, same as wall_top_stats: correct regardless of
    top constraint, join, or how the wall was drawn. Room separation lines are among the
    bounding elements and are skipped by class - they are not walls and have no top.

    Returns (z_ft, info); z_ft is None when no real wall bounds the room at all.
    """
    cfg = cfg or CFG
    tops = []
    for bid in (region.get("bounding_element_ids") or []):
        try:
            e = doc.GetElement(ElementId(bid))
        except Exception:
            continue
        if not isinstance(e, Wall):
            continue
        try:
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            tops.append(round(bb.Max.Z * 304.8, 1))
        except Exception:
            continue

    if not tops:
        return None, {"bounding_walls": 0, "reason": "room is bounded by no real wall"}

    rule = cfg_val(cfg, "ROOM_WALL_TOP_RULE", "modal")
    if rule == "max":
        pick = max(tops)
        members = [t for t in tops if t == pick]
    elif rule == "min":
        pick = min(tops)
        members = [t for t in tops if t == pick]
    else:
        pick, members = modal_top_mm(tops)

    return pick * FT_PER_MM, {
        "bounding_walls": len(tops),
        "rule": rule,
        "wall_top_mm": pick,
        "agreeing_walls": len(members),
        "distinct_tops_mm": sorted(set(tops)),
    }


def annotate_region_wall_tops(doc, regions, cfg=None):
    """Stamp every region with the top of its own bounding walls before anything is classified.

    Both new rules key off this number: whether an existing ceiling counts as one a person
    dropped deliberately (it sits below this) or as part of the top layer (it sits at it), and
    the elevation any newly cut ceiling is built at.
    """
    for r in regions:
        z, info = region_wall_top_ft(doc, r, cfg)
        r["wall_top_ft"] = z
        r["wall_top_mm"] = None if z is None else round(z * 304.8, 1)
        r["wall_top_info"] = info
    return regions


def building_footprint(doc, level, ceilings, warnings):
    """Outer plan polygon of the building on this level. Preferred source is the floor slab
    whose top sits at the level; failing that, the largest existing ceiling (the blanket covers
    the whole plate by definition)."""
    best, best_a = None, 0.0
    fallback, fallback_a = None, 0.0
    for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
        loops, z = _bottom_loops(fl, warnings)
        if not loops:
            continue
        a = poly_area(loops[0])
        if a > fallback_a:
            fallback_a, fallback = a, loops[0]
        # The slab that forms THIS level's floor has its top face at the level elevation.
        try:
            bb = fl.get_BoundingBox(None)
            at_level = bb is not None and abs(bb.Max.Z - level.Elevation) <= 0.5
        except Exception:
            at_level = False
        if at_level and a > best_a:
            best_a, best = a, loops[0]
    if best is not None:
        return best, "floor slab at level ({} sf)".format(round(best_a, 1))

    # Fall back to the blanket ceiling: it covers the whole plate by definition. Project1 has
    # no floor slab at all, so without this nothing gets sealed and only the few fully-walled
    # rooms are found (2 rooms / 24 sf across a 90-wall building).
    #
    # Phantom storeys are NOT prevented here - walls_based_at_level() is the guard for that,
    # and restricting these fallbacks to the same level as well was an over-correction.
    on_level = [c for c in ceilings
                if c.get("outer") and c.get("level_id") == eid_value(level.Id)]
    if on_level:
        big = sorted(on_level, key=lambda c: -(poly_area(c["outer"])))[0]
        return big["outer"], "largest ceiling on level ({} sf)".format(
            round(poly_area(big["outer"]), 1))

    anywhere = [c for c in ceilings if c.get("outer")]
    if anywhere:
        big = sorted(anywhere, key=lambda c: -(poly_area(c["outer"])))[0]
        return big["outer"], "largest ceiling in model ({} sf)".format(
            round(poly_area(big["outer"]), 1))

    if fallback is not None:
        return fallback, "largest floor slab in model ({} sf)".format(round(fallback_a, 1))

    warnings.append("Level {}: no footprint source at all - perimeter cannot be sealed, so "
                    "only fully-walled rooms will be found".format(level.Name))
    return None, "none"


def _bottom_loops(e, warnings):
    """Downward-facing planar face of an element as plan polygons, largest first."""
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
        return None, None
    if best is None:
        return None, None
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
        return None, None
    if not loops:
        return None, None
    loops.sort(key=poly_area, reverse=True)
    return loops, bz


def find_or_create_plan_view(doc, level, created_views, warnings):
    """Room separation lines need a plan view to be drawn in. Reuse one if the level has it."""
    lid = eid_value(level.Id)
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        try:
            if v.IsTemplate:
                continue
            gl = v.GenLevel
            if gl is not None and eid_value(gl.Id) == lid:
                return v
        except Exception:
            continue
    vft = floor_plan_vft_id(doc)
    if vft is None:
        warnings.append("Level {}: no FloorPlan view family type".format(level.Name))
        return None
    try:
        v = ViewPlan.Create(doc, vft, level.Id)
        created_views.append(v.Id)
        return v
    except Exception as ex:
        warnings.append("Level {}: could not create a plan view ({})".format(level.Name, ex))
        return None


def seal_perimeter(doc, level, plane_ft, plan_view, footprint, warnings):
    """Trace the building outline with temporary Room Separation Lines.

    Without this, these envs' interiors leak out through the perimeter and Revit refuses to
    enclose anything large: 13e (2) found 11 rooms totalling 159 sf of a 1002 sf plate. With
    it, 13 rooms totalling 945 sf (94% of the plate). Where a real wall exists it still wins
    the boundary, so rooms keep stopping at wall finish faces - these lines only close the
    gaps the model leaks through.

    Returns the created line ids so they can be removed again.
    """
    if plan_view is None or not footprint:
        return []
    try:
        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
            XYZ.BasisZ, XYZ(0, 0, plane_ft)))
    except Exception as ex:
        warnings.append("Level {}: sketch plane failed ({})".format(level.Name, ex))
        return []

    made = []
    n = len(footprint)
    for i in range(n):
        a = footprint[i]
        b = footprint[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.01:
            continue
        try:
            arr = CurveArray()
            arr.Append(Line.CreateBound(XYZ(a[0], a[1], plane_ft),
                                        XYZ(b[0], b[1], plane_ft)))
            for mc in doc.Create.NewRoomBoundaryLines(sp, arr, plan_view):
                made.append(mc.Id)
        except Exception:
            continue
    return made


def classify_storeys(doc):
    """Which levels are real storeys that should get rooms and ceilings.

    Neither obvious test is sufficient. Revit's Building Story flag is set on datum levels too
    (Project1's "Door Level" at 2133.6 mm carries it), and a wall count alone does not separate
    them either, because door headers ARE walls based on that level. What does separate them is
    the PROPORTION: 11 walls against 79 on the real floor. Get this wrong and the level gets a
    duplicate set of rooms stacked over the real ones in plan.

    Returns {level_id: (is_storey, reason)}.
    """
    levels = collect_levels(doc)
    wall_counts = {}
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            lid = eid_value(w.LevelId)
            wall_counts[lid] = wall_counts.get(lid, 0) + 1
        except Exception:
            continue

    slab_at = {}
    for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
        try:
            bb = fl.get_BoundingBox(None)
            if bb is None:
                continue
            for lv in levels:
                if abs(bb.Max.Z - lv.Elevation) <= 0.5:
                    slab_at[eid_value(lv.Id)] = True
        except Exception:
            continue

    max_walls = max(wall_counts.values()) if wall_counts else 0
    lowest_with_walls = None
    for lv in levels:
        if wall_counts.get(eid_value(lv.Id), 0) > 0:
            lowest_with_walls = eid_value(lv.Id)
            break

    out = {}
    for lv in levels:
        lid = eid_value(lv.Id)
        n = wall_counts.get(lid, 0)
        if n == 0:
            out[lid] = (False, "no walls based on this level")
        elif slab_at.get(lid):
            out[lid] = (True, "floor slab at this level")
        elif lid == lowest_with_walls:
            out[lid] = (True, "lowest level with walls ({} walls)".format(n))
        elif max_walls and n >= 0.25 * max_walls:
            out[lid] = (True, "{} of {} walls based here".format(n, max_walls))
        else:
            out[lid] = (False, "only {} of {} walls - datum level, not a storey".format(
                n, max_walls))
    return out


def is_building_story(level):
    """Revit's own storey/datum distinction. A level like "Door Level" exists only to host door
    heads - header walls ARE based on it, so a wall count cannot tell it apart from a real
    storey, but its Building Story flag is off. Treating it as a storey builds a second set of
    ceilings stacked over the first (Project1: a 670 sf ceiling at 4876.8 mm over a 529 sf one
    at 2743.2 mm)."""
    try:
        p = level.get_Parameter(BuiltInParameter.LEVEL_IS_BUILDING_STORY)
        if p is not None:
            return p.AsInteger() == 1
    except Exception:
        pass
    return True          # parameter unavailable - assume it is a storey


def walls_based_at_level(doc, level):
    """Walls whose BASE constraint is this level - the test for whether a storey exists here.
    Walls spanning 0 to 3048 belong to Level 1 even though their tops touch Level 2's plane."""
    lid = eid_value(level.Id)
    n = 0
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            if eid_value(w.LevelId) == lid:
                n += 1
        except Exception:
            continue
    return n


def cfg_val(cfg, key, default):
    try:
        return (cfg or CFG).get(key, default)
    except Exception:
        return default


def close_openings_above_plane(doc, level, plane_ft, plan_view, storeys, warnings, cfg=None):
    """Close doorway openings by projecting the header walls down to the room computation plane.

    These envs model a doorway as a real GAP in the wall, with a short header wall above it
    (Project1: five walls 813-1016 mm long, from 2133.6 mm to 3048 mm, based on "Door Level").
    At the computation plane there is simply nothing there, so Revit sees one connected space
    and reports 529 sf where there are three rooms.

    The header walls are exactly as long as the openings and sit exactly over them, so tracing
    them at the plane closes each doorway precisely. Guessing from loose wall ends does not
    work - the nearest end to a doorway jamb is usually a perpendicular wall 50 mm away, not
    the jamb 900 mm opposite.

    Returns the created line ids.
    """
    if plan_view is None:
        return []

    # A header sits above a door head, not high up the storey. Capping at the next level was far
    # too loose: in 13e (2) it swept up most upper wall segments, flooded the model with
    # separation lines and spawned masses of sliver regions - the run ground on for 7 minutes.
    head_cap_ft = plane_ft + (cfg_val(cfg, "MAX_DOOR_HEAD_MM", 2600.0)) * FT_PER_MM
    for lv in collect_levels(doc):
        if lv.Elevation <= level.Elevation + 1e-6:
            continue
        ok_storey, _why = storeys.get(eid_value(lv.Id), (True, ""))
        if ok_storey:
            head_cap_ft = min(head_cap_ft, lv.Elevation)
            break
    max_len_ft = cfg_val(cfg, "MAX_OPENING_WIDTH_MM", 2500.0) * FT_PER_MM

    # Walls that DO exist at the plane - a candidate sitting over one of these is an ordinary
    # wall above a wall, not an opening.
    at_plane = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            bb = w.get_BoundingBox(None)
            if bb is None or not (bb.Min.Z <= plane_ft + 1e-6 <= bb.Max.Z + 1e-6):
                continue
            at_plane.append((bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y))
        except Exception:
            continue

    def _covered_at_plane(mx, my):
        pad = 0.05
        for (x0, y0, x1, y1) in at_plane:
            if x0 - pad <= mx <= x1 + pad and y0 - pad <= my <= y1 + pad:
                return True
        return False

    headers = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
            if rb is not None and rb.AsInteger() != 1:
                continue
            bb = w.get_BoundingBox(None)
            if bb is None:
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
            # Only bridge where the plane is actually empty - that is what makes it an opening.
            if _covered_at_plane((a.X + b.X) / 2.0, (a.Y + b.Y) / 2.0):
                continue
            headers.append((a, b))
        except Exception:
            continue

    if not headers:
        return []

    try:
        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
            XYZ.BasisZ, XYZ(0, 0, plane_ft)))
    except Exception as ex:
        warnings.append("Level {}: sketch plane for openings failed ({})".format(level.Name, ex))
        return []

    made = []
    for (a, b) in headers:
        try:
            arr = CurveArray()
            arr.Append(Line.CreateBound(XYZ(a.X, a.Y, plane_ft), XYZ(b.X, b.Y, plane_ft)))
            for mc in doc.Create.NewRoomBoundaryLines(sp, arr, plan_view):
                made.append(mc.Id)
        except Exception:
            continue
    return made


def computation_plane(doc, level):
    try:
        p = level.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
        return level.Elevation + (p.AsDouble() if p else 0.0)
    except Exception:
        return level.Elevation


def place_missing_rooms(doc, level, phase, warnings):
    """NewRooms2 places a room in every enclosed region that does NOT already contain one, so
    what it returns is exactly the set of regions the model was missing. Requires an open
    transaction. Returns the created ElementIds so we can delete precisely those again."""
    try:
        ids = doc.Create.NewRooms2(level, phase) if phase is not None else doc.Create.NewRooms2(level)
    except Exception:
        try:
            ids = doc.Create.NewRooms2(level)
        except Exception as ex:
            warnings.append("NewRooms2 failed on level {}: {}".format(level.Name, ex))
            return []
    out = []
    for i in (ids or []):
        out.append(i)
    # Stamp them so a crashed run leaves a greppable trail.
    for i in out:
        try:
            e = doc.GetElement(i)
            p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if p is not None and not p.IsReadOnly:
                p.Set("ORIGIN_TMP_ROOM")
        except Exception:
            continue
    return out


# ------------------------------------------------------------
# The keep / create / delete classifier
# ------------------------------------------------------------

def match_ceilings_to_regions(regions, ceilings, cfg=None):
    """Decide which existing ceilings a person authored (keep), which regions still need one
    cut out of the blanket (create), and which ceilings are blanket / top-layer / stray (delete).

    Two tiers, split by how far a ceiling sits below ITS OWN room's wall top:

      * more than AUTHORED_DROP_MIN_MM below it - a ceiling somebody dropped on purpose. Kept
        exactly as it is, whether it covers the whole room or only part of it.
      * at the wall top - part of the top layer. Kept only when it already IS that room's
        ceiling and that room has no authored drop; otherwise deleted so the room can be recut.

    A ceiling touching more than one region is the blanket and is always deleted: one element
    cannot be kept over the room that authored a drop and recut over the room next door.

    A room with an authored drop gets NOTHING created - the drop is that room's ceiling, and
    whatever area it leaves uncovered stays bare by design.

    Requires annotate_region_wall_tops() to have run.
    """
    cfg = cfg or CFG
    for i, r in enumerate(regions):
        r.setdefault("idx", i)
        r["_probes"] = probe_points(r["outer"], r["holes"])

    usable = [c for c in ceilings if c.get("outer") and is_candidate_ceiling(c, cfg)]

    # coverage[ci][ri] = how many of region ri's probes fall inside ceiling ci
    coverage = {}
    for c in usable:
        cid = c["id"]
        coverage[cid] = {}
        cb = c["bbox"]
        for r in regions:
            if not rects_overlap(cb, r["bbox"]):
                coverage[cid][r["idx"]] = 0
                continue
            n = 0
            for (px, py) in r["_probes"]:
                if point_in_region(px, py, c["outer"], c.get("holes")):
                    n += 1
            coverage[cid][r["idx"]] = n

    ambiguities = []
    ceiling_status = {}
    drop_min_ft = cfg_val(cfg, "AUTHORED_DROP_MIN_MM", 50.0) * FT_PER_MM

    # --- pass 1: blankets, strays, and the authored drops --------------------------------
    # Every authored drop has to be known before any top-layer ceiling is judged, because a
    # top-layer ceiling over a room that HAS a drop is deleted even when it fits that room
    # exactly - that is the whole point of the new rule.
    single = []                  # (ceiling, region, is_full) - decided in pass 2
    region_authored = {}         # region idx -> [ceiling id, ...]

    for c in usable:
        cid = c["id"]
        full, partial = [], []
        for r in regions:
            n = coverage[cid][r["idx"]]
            total = len(r["_probes"])
            if total and n == total:
                full.append(r)
            elif n > 0:
                partial.append(r)

        c["spans_room_ids"] = [r["room_id"] for r in full]
        c["partial_room_ids"] = [r["room_id"] for r in partial]

        if len(full) + len(partial) > 1:
            ceiling_status[cid] = "delete"
            c["delete_reason"] = ("blanket: spans {} whole and {} partial region(s)"
                                  .format(len(full), len(partial)))
            continue

        if not full and not partial:
            ceiling_status[cid] = "delete"
            c["delete_reason"] = "stray: overlaps no region at all"
            continue

        r = full[0] if full else partial[0]
        wt = r.get("wall_top_ft")
        cz = c.get("bottom_z_ft")
        drop_ft = None if (wt is None or cz is None) else (wt - cz)
        c["drop_below_wall_top_mm"] = None if drop_ft is None else round(drop_ft * 304.8, 1)

        if drop_ft is not None and drop_ft > drop_min_ft:
            ceiling_status[cid] = "keep"
            c["keep_reason"] = ("authored drop: {} mm below room {}'s wall top"
                                .format(round(drop_ft * 304.8, 1), r["room_id"]))
            region_authored.setdefault(r["idx"], []).append(cid)
            continue

        single.append((c, r, bool(full)))

    # --- pass 2: the top layer -------------------------------------------------------------
    region_top_exact = {}        # region idx -> ceiling id
    for (c, r, is_full) in single:
        cid = c["id"]
        if region_authored.get(r["idx"]):
            ceiling_status[cid] = "delete"
            c["delete_reason"] = ("top layer over room {}, which already has an authored "
                                  "ceiling".format(r["room_id"]))
            continue
        if is_full:
            ca = c.get("poly_area_sf")
            ra = r["poly_area_sf"]
            tol = max(cfg["AREA_MATCH_ABS_SF"], cfg["AREA_MATCH_PCT"] * max(ra, 1e-9))
            if ca is not None and abs(ca - ra) <= tol:
                if r["idx"] in region_top_exact:
                    ambiguities.append({"region_idx": r["idx"], "room_id": r["room_id"],
                                        "reason": "two ceilings both fit this room exactly",
                                        "ceiling_ids": [region_top_exact[r["idx"]], cid]})
                ceiling_status[cid] = "keep"
                c["keep_reason"] = "already this room's ceiling, at the wall top"
                region_top_exact[r["idx"]] = cid
                continue
            ceiling_status[cid] = "delete"
            c["delete_reason"] = ("top layer: covers room {} but area differs ({} vs {} sf) - "
                                  "recut to the room outline".format(r["room_id"], ca, ra))
            continue
        ceiling_status[cid] = "delete"
        c["delete_reason"] = ("top layer: lies inside room {} without covering it - recut to "
                              "the room outline".format(r["room_id"]))

    for c in ceilings:
        cid = c["id"]
        if not c.get("outer"):
            ceiling_status[cid] = "quarantine (no readable plan polygon)"
            ambiguities.append({"ceiling_id": cid, "reason": "no readable plan polygon"})
        elif not is_candidate_ceiling(c, cfg):
            ceiling_status[cid] = "leave (excluded category)"
        ceiling_status.setdefault(cid, "delete")

    result = {"regions": [], "ceilings": [], "ambiguities": ambiguities}
    area_by_id = dict((c["id"], c.get("poly_area_sf") or 0.0) for c in ceilings)

    for r in regions:
        authored = region_authored.get(r["idx"], [])
        top_exact = region_top_exact.get(r["idx"])
        if authored:
            status = "authored"
        elif top_exact:
            status = "kept"
        else:
            status = "create"

        # Area an authored drop leaves uncovered. Bare BY DESIGN now, but it is exactly what
        # the drywall stage will not board, so it is reported rather than left to be discovered
        # in Revit. Approximate: authored ceilings all lie inside this one region, so the
        # shortfall is the region minus their areas - it does not account for two drops
        # overlapping each other, which V3 fails separately.
        bare = 0.0
        if authored:
            bare = max(0.0, r["poly_area_sf"] - sum(area_by_id.get(i, 0.0) for i in authored))

        result["regions"].append({
            "idx": r["idx"],
            "room_id": r["room_id"],
            "room_name": r["room_name"],
            "level_id": r["level_id"],
            "area_sf": r["poly_area_sf"],
            "probe_count": len(r["_probes"]),
            "status": status,
            "authored_ceiling_ids": authored,
            "kept_ceiling_id": top_exact,
            "bare_area_sf": round(bare, 4),
            "wall_top_mm": r.get("wall_top_mm"),
            "wall_top_info": r.get("wall_top_info"),
            "tiny_region": r["poly_area_sf"] < cfg["MIN_REGION_SF"],
        })

    for c in ceilings:
        result["ceilings"].append({
            "id": c["id"],
            "category": c.get("category"),
            "type": c.get("type"),
            "level_id": c.get("level_id"),
            "area_sf": c.get("area_sf"),
            "poly_area_sf": c.get("poly_area_sf"),
            "offset_mm": c.get("offset_mm"),
            "drop_below_wall_top_mm": c.get("drop_below_wall_top_mm"),
            "status": ceiling_status.get(c["id"]),
            "reason": c.get("delete_reason") or c.get("keep_reason"),
            "spans_room_ids": c.get("spans_room_ids"),
            "hosted_family_instances": c.get("hosted_family_instances"),
        })

    rr = result["regions"]
    result["summary"] = {
        "regions_total": len(regions),
        "regions_authored": len([r for r in rr if r["status"] == "authored"]),
        "regions_kept": len([r for r in rr if r["status"] == "kept"]),
        "regions_to_create": len([r for r in rr if r["status"] == "create"]),
        "bare_area_sf": round(sum(r["bare_area_sf"] for r in rr), 2),
        "ceilings_total": len(ceilings),
        "ceilings_keep": len([c for c in result["ceilings"] if c["status"] == "keep"]),
        "ceilings_delete": len([c for c in result["ceilings"] if c["status"] == "delete"]),
        "ambiguities": len(ambiguities),
    }
    return result


# ------------------------------------------------------------
# Audit
# ------------------------------------------------------------

def audit_document(doc, cfg=None):
    """Read-only picture of one env plus a DRY-RUN of the reconciliation. The caller must have
    an open transaction it will ROLL BACK - rooms are placed here to discover regions and are
    never meant to survive."""
    cfg = cfg or CFG
    warnings = []
    out = {"doc": doc.Title, "path": doc.PathName, "warnings": warnings}

    levels = collect_levels(doc)
    out["levels"] = [level_info(doc, lv) for lv in levels]

    ceilings = collect_ceilings(doc, warnings)

    rooms_before = len(list(FilteredElementCollector(doc)
                            .OfCategory(BuiltInCategory.OST_Rooms)
                            .WhereElementIsNotElementType()))
    created_total = []
    for lv in levels:
        ph, why = pick_phase(doc, lv)
        created = place_missing_rooms(doc, lv, ph, warnings)
        created_total.extend(created)
    doc.Regenerate()

    out["rooms_pre_existing"] = rooms_before
    out["rooms_created_to_fill_gaps"] = len(created_total)

    regions = collect_regions(doc, warnings)
    annotate_region_wall_tops(doc, regions, cfg)
    out["regions_total"] = len(regions)

    plan = match_ceilings_to_regions(regions, ceilings, cfg)

    # Per-level roll-up, including the fingerprint of the single-blanket pattern.
    per_level = {}
    for lv in levels:
        lid = eid_value(lv.Id)
        lr = [r for r in regions if r["level_id"] == lid]
        lc = [c for c in ceilings if c.get("level_id") == lid and is_candidate_ceiling(c, cfg)]
        areas = [c.get("poly_area_sf") or 0.0 for c in lc]
        room_area = sum(r["poly_area_sf"] for r in lr)
        # Absolute bottom-face elevation is the number that matters for "where the walls end" -
        # an offset is meaningless without knowing which level it hangs from.
        abs_z = sorted(set(round(c["bottom_z_ft"] * 304.8, 1) for c in lc
                           if c.get("bottom_z_ft") is not None))
        per_level[lv.Name] = {
            "regions": len(lr),
            "ceilings": len(lc),
            "total_region_area_sf": round(room_area, 2),
            "max_ceiling_area_sf": round(max(areas), 2) if areas else 0.0,
            "sum_ceiling_area_sf": round(sum(areas), 2),
            "giant_ratio": round(max(areas) / room_area, 3) if (areas and room_area > 0) else None,
            "dominance_ratio": round(max(areas) / sum(areas), 3) if (areas and sum(areas) > 0) else None,
            "distinct_offsets_mm": sorted(set(c.get("offset_mm") for c in lc
                                              if c.get("offset_mm") is not None)),
            "ceiling_bottom_abs_mm": abs_z,
            "walls": wall_top_stats(doc, lv),
        }
    out["per_level"] = per_level
    out["plan"] = plan

    def _count_cat(bic):
        try:
            return (FilteredElementCollector(doc).OfCategory(bic)
                    .WhereElementIsNotElementType().GetElementCount())
        except Exception:
            return -1

    out["counts"] = {
        "walls": FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType().GetElementCount(),
        "room_separation_lines": _count_cat(BuiltInCategory.OST_RoomSeparationLines),
        "revit_links": FilteredElementCollector(doc).OfClass(RevitLinkInstance).WhereElementIsNotElementType().GetElementCount(),
        "direct_shapes": FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType().GetElementCount(),
        "lighting_fixtures": _count_cat(BuiltInCategory.OST_LightingFixtures),
        "air_terminals": _count_cat(BuiltInCategory.OST_DuctTerminal),
    }
    out["has_origin_assembly"] = out["counts"]["direct_shapes"] > 0
    return out


# ------------------------------------------------------------
# Height and type resolution
# ------------------------------------------------------------

def resolve_ceiling_height(doc, level, ceilings, plan, warnings, cfg=None):
    """Absolute elevation (ft) for new ceilings: the height this env's OWN correct ceilings
    already sit at.

    Deliberately NOT the wall top - walls run up to the roof/slab, not to the ceiling. Using
    the wall top put new ceilings at 3048 mm inside the roof in 13e/Project8/12M_FR_11, while
    those models' real ceilings sit at 2743.2 mm. The blanket's own elevation is no better: it
    is a true ceiling height in B1-a/A-1a (2438.4 mm) but sits at slab level in the others.

    Heights are ranked by total KEPT AREA, not by count, so two small dropped ceilings in
    closets cannot set the height for a large living room.
    """
    by_id = dict((c["id"], c) for c in ceilings)
    kept = [by_id[p["id"]] for p in plan["ceilings"]
            if p.get("status") == "keep" and p["id"] in by_id]

    lid = eid_value(level.Id)
    same_level = [c for c in kept
                  if c.get("level_id") == lid and c.get("bottom_z_ft") is not None]
    pool = same_level or [c for c in kept if c.get("bottom_z_ft") is not None]

    if pool:
        groups = {}
        for c in pool:
            z = round(c["bottom_z_ft"], 5)
            groups.setdefault(z, []).append(c.get("poly_area_sf") or 0.0)
        best = sorted(groups.items(), key=lambda kv: (-sum(kv[1]), -len(kv[1])))[0][0]
        return (best, "existing correct ceilings ({} of {} at {} mm, {} sf)".format(
            len(groups[best]), len(pool), round(best * 304.8, 1), round(sum(groups[best]), 1)))

    # The blanket is only a usable reference if it is NOT sitting on a level elevation. In
    # Lab_01/409/PH2A/Testing_Env it sits at 3048 mm = roof level, which is what produced
    # ceilings buried in the slab.
    level_elevs_mm = [l.Elevation * 304.8 for l in collect_levels(doc)]

    def _at_a_level(z_mm):
        return any(abs(z_mm - e) <= 1.0 for e in level_elevs_mm)

    deleted = [by_id[p["id"]] for p in plan["ceilings"]
               if p.get("status") == "delete" and p["id"] in by_id]
    deleted = [c for c in deleted if c.get("bottom_z_ft") is not None]
    if deleted:
        biggest = sorted(deleted, key=lambda c: -(c.get("poly_area_sf") or 0.0))[0]
        z_mm = biggest["bottom_z_ft"] * 304.8
        if not _at_a_level(z_mm):
            return (biggest["bottom_z_ft"],
                    "no ceiling kept; largest deleted ceiling at {} mm".format(round(z_mm, 1)))

    default_mm = (cfg or CFG)["DEFAULT_CEILING_HEIGHT_MM"]
    z_ft = level.Elevation + default_mm * FT_PER_MM
    warnings.append("Level {}: nothing in this env to copy a ceiling height from; using the "
                    "{} mm default".format(level.Name, default_mm))
    return z_ft, "library default {} mm above {}".format(default_mm, level.Name)


def region_ceiling_height(doc, region, level, ceilings, plan, warnings, cfg=None):
    """Absolute elevation (ft) for the ceiling cut out of the blanket for ONE room.

    The rule is the room's own bounding walls: the ceiling ends where those walls end, and
    never below them. That is measured per room on purpose - a perimeter room's exterior wall
    runs to the roof while the partitions around an interior room stop lower, so one number for
    the whole level is wrong for one of them either way.

    Ladder for a room bounded entirely by room separation lines, with no wall to measure: the
    level's modal wall top, then the older "copy this env's own correct ceilings" rule as a
    last resort, so a file is never abandoned for want of a number.
    """
    cfg = cfg or CFG
    z = region.get("wall_top_ft")
    if z is not None:
        info = region.get("wall_top_info") or {}
        return z, "room's own bounding walls ({} of {} at {} mm)".format(
            info.get("agreeing_walls"), info.get("bounding_walls"), info.get("wall_top_mm"))

    stats = wall_top_stats(doc, level)
    if stats.get("modal_top_mm") is not None:
        warnings.append("Room {}: bounded by no wall of its own; using level {}'s modal wall "
                        "top".format(region.get("room_id"), level.Name))
        return (stats["modal_top_mm"] * FT_PER_MM,
                "level modal wall top ({} mm, {}% of {} walls)".format(
                    stats["modal_top_mm"], stats.get("modal_share"), stats.get("wall_count")))

    z, why = resolve_ceiling_height(doc, level, ceilings, plan, warnings, cfg)
    return z, "fallback - " + why


def _type_thickness_ft(doc, tid):
    """A ceiling type with no compound structure builds nothing - zero thickness, no bottom
    face. Lab_01/409/PH2A all picked up a 'Generic' type like that and produced ceilings that
    existed as elements but had no geometry at all."""
    try:
        t = doc.GetElement(tid)
        cs = t.GetCompoundStructure()
        if cs is None:
            return 0.0
        return cs.GetWidth()
    except Exception:
        return 0.0


def pick_ceiling_type_id(doc, ceilings, level_id, warnings, cfg=None):
    """A type for the new ceilings. Only real Ceilings-category elements may donate one - a
    Roof Soffit type cannot be assigned to a Ceiling (the set silently no-ops) - and the type
    must have real thickness."""
    cfg = cfg or CFG
    cands = [c for c in ceilings
             if c.get("is_ceiling_category") and (c.get("type_id") or -1) > 0]
    pool = [c for c in cands if c.get("level_id") == level_id] or cands
    if pool:
        groups = {}
        for c in pool:
            groups.setdefault(c["type_id"], []).append(c.get("poly_area_sf") or 0.0)
        for best, areas in sorted(groups.items(), key=lambda kv: (-len(kv[1]), -sum(kv[1]))):
            tid = ElementId(best)
            if _type_is_ceiling(doc, tid) and _type_thickness_ft(doc, tid) > 1e-6:
                return tid, "most common Ceilings type in model ({})".format(elem_name(doc, tid))

    # No ceiling of its own to copy: prefer a known-good compound type by name.
    all_types = [t for t in FilteredElementCollector(doc).OfClass(CeilingType)
                 if _type_is_ceiling(doc, t.Id)]
    for want in cfg["PREFERRED_CEILING_TYPE_NAMES"]:
        for t in all_types:
            nm = elem_name(doc, t.Id)
            if want.lower() in nm.lower() and _type_thickness_ft(doc, t.Id) > 1e-6:
                return t.Id, "preferred type by name ({})".format(nm)

    thick = [(t, _type_thickness_ft(doc, t.Id)) for t in all_types]
    thick = [(t, w) for (t, w) in thick if w > 1e-6]
    if thick:
        t = sorted(thick, key=lambda tw: -tw[1])[0][0]
        return t.Id, "thickest CeilingType in document ({})".format(elem_name(doc, t.Id))

    try:
        tid = doc.GetDefaultElementTypeId(ElementTypeGroup.CeilingType)
        if tid is not None and eid_value(tid) > 0 and _type_is_ceiling(doc, tid):
            warnings.append("Only a zero-thickness CeilingType is available")
            return tid, "document default CeilingType (no compound structure)"
    except Exception:
        pass
    warnings.append("No usable CeilingType found")
    return None, "none"


def _type_is_ceiling(doc, tid):
    try:
        t = doc.GetElement(tid)
        return t is not None and eid_value(t.Category.Id) == int(BuiltInCategory.OST_Ceilings)
    except Exception:
        return False


# ------------------------------------------------------------
# Profile construction
# ------------------------------------------------------------

WELD_TOL_FT = 0.005      # 1.5 mm - above ShortCurveTolerance (~0.8 mm), below any real feature
COLLINEAR_TOL = 1e-7


def weld_and_close(pts):
    """Clean a tessellated boundary into a polygon Ceiling.Create will accept. Rebuilding every
    curve from this shared point list is what makes contiguity true by construction, instead of
    fighting Revit's vertex tolerance on the segments it handed us."""
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > WELD_TOL_FT:
            out.append(p)
    while len(out) >= 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= WELD_TOL_FT:
        out.pop()
    if len(out) < 3:
        return None

    cleaned = []
    n = len(out)
    for i in range(n):
        a, b, c = out[i - 1], out[i], out[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) > COLLINEAR_TOL:
            cleaned.append(b)
    if len(cleaned) < 3:
        cleaned = out
    return cleaned if len(cleaned) >= 3 else None


def _ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])


def _seg_intersect(p1, p2, p3, p4):
    d1 = _ccw(p3, p4, p1)
    d2 = _ccw(p3, p4, p2)
    d3 = _ccw(p1, p2, p3)
    d4 = _ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


MAX_SIMPLICITY_CHECK_VERTS = 400


def polygon_is_simple(pts):
    """Reject a self-intersecting boundary in Python so the failure has a name, instead of
    surfacing as an opaque Revit exception 80 files into a batch.

    This is O(n^2) with a Python-level call per pair, so it is skipped above a vertex count -
    a large open-plan region's boundary can run to thousands of points and the check then takes
    minutes. Skipping only costs a nicer error message: Ceiling.Create validates the loop
    itself and its failure is caught and reported per region either way.
    """
    n = len(pts)
    if n < 4:
        return True
    if n > MAX_SIMPLICITY_CHECK_VERTS:
        return True
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1:
                continue
            if i == 0 and j == n - 1:
                continue
            if _seg_intersect(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return False
    return True


def points_to_curveloop(pts, z):
    loop = CurveLoop()
    n = len(pts)
    for i in range(n):
        p0 = XYZ(pts[i][0], pts[i][1], z)
        p1 = XYZ(pts[(i + 1) % n][0], pts[(i + 1) % n][1], z)
        loop.Append(Line.CreateBound(p0, p1))
    return loop


def build_profile(region, z, warnings):
    """Outer loop CCW first, hole loops CW after it."""
    outer = weld_and_close(region["outer"])
    if not outer:
        return None, "outer loop collapsed after welding"
    if not polygon_is_simple(outer):
        return None, "outer loop self-intersects"

    loops = NetList[CurveLoop]()
    ol = points_to_curveloop(outer, z)
    try:
        if not ol.IsCounterclockwise(XYZ.BasisZ):
            ol.Flip()
    except Exception:
        pass
    loops.Add(ol)

    for h in (region.get("holes") or []):
        hp = weld_and_close(h)
        if not hp or not polygon_is_simple(hp):
            warnings.append("Room {}: dropped an unusable hole loop".format(region["room_id"]))
            continue
        hl = points_to_curveloop(hp, z)
        try:
            if hl.IsCounterclockwise(XYZ.BasisZ):
                hl.Flip()
        except Exception:
            pass
        loops.Add(hl)
    return loops, None


def create_ceiling_for_region(doc, region, type_id, level, abs_z_ft, warnings):
    """Sketch at the level elevation and carry the height in the offset parameter - correct
    whether Ceiling.Create derives its plane from the loop Z or from the level."""
    offset_ft = abs_z_ft - level.Elevation
    loops, err = build_profile(region, level.Elevation, warnings)
    if loops is None:
        return None, err
    try:
        c = Ceiling.Create(doc, loops, type_id, level.Id)
    except Exception as ex:
        return None, "Ceiling.Create failed: {}".format(ex)
    try:
        p = c.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
        if p is not None and not p.IsReadOnly:
            p.Set(offset_ft)
    except Exception as ex:
        warnings.append("Room {}: height offset not set ({})".format(region["room_id"], ex))
    return c, None


# ------------------------------------------------------------
# Rebuild + verify
# ------------------------------------------------------------

def run_on_document(doc, cfg=None, delete_unmatched=True, create_missing=True,
                    remove_temp_rooms=True):
    """Full rebuild on an open document. The CALLER owns the transaction and must roll it back
    when report["ok"] is False - that is what guarantees a failed file never reaches disk."""
    cfg = cfg or CFG
    warnings = []
    report = {"doc": doc.Title, "ok": False, "warnings": warnings,
              "created": [], "deleted": {}, "verify": {}, "fail_reasons": []}

    levels = collect_levels(doc)
    level_by_id = dict((eid_value(lv.Id), lv) for lv in levels)
    ceilings_before = collect_ceilings(doc, warnings)

    # --- discover every enclosed region -------------------------------------
    temp_rooms, temp_lines, temp_views = [], [], []
    seal_info = {}
    storeys = classify_storeys(doc)
    for lv in levels:
        # Non-storey levels produce phantom rooms stacked over the real ones in plan.
        ok_storey, why_storey = storeys.get(eid_value(lv.Id), (True, "unclassified"))
        if not ok_storey:
            seal_info[lv.Name] = {"skipped": why_storey}
            continue
        foot, foot_src = building_footprint(doc, lv, ceilings_before, warnings)
        pv = find_or_create_plan_view(doc, lv, temp_views, warnings)
        plane = computation_plane(doc, lv)
        lines = seal_perimeter(doc, lv, plane, pv, foot, warnings)
        temp_lines.extend(lines)
        # Doorways are modelled as gaps with a header wall above; without closing them at the
        # plane, adjoining rooms merge into one region and get one shared ceiling.
        openings = close_openings_above_plane(doc, lv, plane, pv, storeys, warnings, cfg)
        temp_lines.extend(openings)
        seal_info[lv.Name] = {"footprint_source": foot_src,
                              "perimeter_lines": len(lines),
                              "doorway_lines": len(openings)}
        ph, _why = pick_phase(doc, lv)
        temp_rooms.extend(place_missing_rooms(doc, lv, ph, warnings))
    doc.Regenerate()
    report["sealing"] = seal_info
    # Regions are captured as plain Python polygons here, so the temporary rooms, separation
    # lines and views can all be removed later without invalidating anything downstream.
    regions = collect_regions(doc, warnings)
    # Must run before the classifier: the authored/top-layer split and every created ceiling's
    # elevation are both measured against each room's own wall top.
    annotate_region_wall_tops(doc, regions, cfg)
    region_by_idx = dict((r["idx"], r) for r in regions)
    report["rooms_created_to_fill_gaps"] = len(temp_rooms)
    report["regions_total"] = len(regions)

    plan = match_ceilings_to_regions(regions, ceilings_before, cfg)
    report["plan_summary"] = plan["summary"]
    report["ambiguities"] = plan["ambiguities"]

    # --- delete first: creating over an existing ceiling raises Revit's overlap
    #     warning on every single call ---------------------------------------
    to_delete = [c["id"] for c in plan["ceilings"] if c["status"] == "delete"]
    report["deleted"] = {"requested": len(to_delete), "actually_deleted": 0, "collateral": []}
    if delete_unmatched and to_delete:
        ids = NetList[ElementId]()
        for i in to_delete:
            ids.Add(ElementId(i))
        try:
            got = set(eid_value(g) for g in doc.Delete(ids))
            report["deleted"]["actually_deleted"] = len(got)
            # doc.Delete returns everything it actually removed - the difference is ground
            # truth for collateral (hosted lights, diffusers, tags), not a guess.
            report["deleted"]["collateral"] = sorted(got - set(to_delete))
        except Exception as ex:
            warnings.append("delete failed: {}".format(ex))
            report["fail_reasons"].append("delete failed: {}".format(ex))
        doc.Regenerate()

    # --- cut one ceiling per uncovered region, at that room's OWN wall top -----------------
    # Rooms whose status is "authored" are skipped entirely: the ceiling somebody dropped there
    # is that room's ceiling, and any area it leaves uncovered stays bare by design.
    height_by_level = {}
    type_by_level = {}
    if create_missing:
        for lv in levels:
            lid = eid_value(lv.Id)
            need = [pr for pr in plan["regions"]
                    if pr["status"] == "create" and pr["level_id"] == lid]
            if not need:
                continue
            type_id, why_t = pick_ceiling_type_id(doc, ceilings_before, lid, warnings, cfg)
            type_by_level[lv.Name] = why_t
            if type_id is None:
                report["fail_reasons"].append("level {}: unresolved ceiling type".format(lv.Name))
                continue
            heights, sources = [], {}
            for pr in need:
                r = region_by_idx.get(pr["idx"])
                if r is None:
                    continue
                abs_z, why_z = region_ceiling_height(doc, r, lv, ceilings_before, plan,
                                                     warnings, cfg)
                if abs_z is None:
                    report["fail_reasons"].append(
                        "region {} (room {}): no ceiling height could be resolved"
                        .format(pr["idx"], pr["room_id"]))
                    continue
                c, err = create_ceiling_for_region(doc, r, type_id, lv, abs_z, warnings)
                if c is None:
                    report["fail_reasons"].append(
                        "region {} (room {}): {}".format(pr["idx"], pr["room_id"], err))
                    continue
                target_mm = round(abs_z * 304.8, 1)
                heights.append(target_mm)
                sources[why_z] = sources.get(why_z, 0) + 1
                report["created"].append({"idx": pr["idx"], "room_id": pr["room_id"],
                                          "ceiling_id": eid_value(c.Id),
                                          "level": lv.Name,
                                          "target_area_sf": pr["area_sf"],
                                          "target_mm": target_mm,
                                          "wall_top_mm": r.get("wall_top_mm"),
                                          "height_source": why_z})
            # Height is per ROOM now, so a level no longer has "the" height - it has a set.
            height_by_level[lv.Name] = {"distinct_mm": sorted(set(heights)),
                                        "ceilings": len(heights),
                                        "sources": sources}
        doc.Regenerate()
    report["height_by_level"] = height_by_level
    report["type_by_level"] = type_by_level

    # --- remove everything we introduced: rooms, separation lines, temp views ----
    if remove_temp_rooms:
        scratch = list(temp_rooms) + list(temp_lines) + list(temp_views)
        if scratch:
            ids = NetList[ElementId]()
            for i in scratch:
                ids.Add(i)
            try:
                doc.Delete(ids)
                doc.Regenerate()
            except Exception as ex:
                warnings.append("scratch cleanup failed: {}".format(ex))
        report["cleanup"] = {"rooms": len(temp_rooms), "separation_lines": len(temp_lines),
                             "temp_views": len(temp_views)}
    report["rooms_remaining"] = (FilteredElementCollector(doc)
                                 .OfCategory(BuiltInCategory.OST_Rooms)
                                 .WhereElementIsNotElementType().GetElementCount())
    report["separation_lines_remaining"] = (FilteredElementCollector(doc)
                                            .OfCategory(BuiltInCategory.OST_RoomSeparationLines)
                                            .WhereElementIsNotElementType().GetElementCount())

    report["verify"] = verify_document(doc, regions, plan, report, cfg, level_by_id)
    report["ok"] = (report["verify"].get("ok", False) and not report["fail_reasons"])
    return report


def verify_document(doc, regions, plan, report, cfg, level_by_id):
    """Proof, read back from the live elements after Regenerate - never from the handles or
    numbers we submitted."""
    cfg = cfg or CFG
    v = {"checks": {}, "failures": [], "per_region": []}
    warnings = []
    all_final = collect_ceilings(doc, warnings)
    final = [c for c in all_final if c.get("outer")]
    # "authored" regions keep somebody's dropped ceiling and are allowed to be partly bare, so
    # several checks below have to know which kind of region they are looking at.
    status_by_idx = dict((p["idx"], p["status"]) for p in plan["regions"])
    tol_mm = cfg_val(cfg, "WALL_TOP_TOL_MM", 1.0)

    # V0 - a ceiling with no readable plan geometry must be a NAMED failure. Silently dropping
    # it made a zero-thickness type look like three unrelated problems: "kept+created !=
    # regions", "covered by no ceiling" and "area check failed".
    unreadable = [c["id"] for c in all_final if not c.get("outer")]
    v_unreadable = unreadable

    kept_ids = set(c["id"] for c in plan["ceilings"] if c["status"] == "keep")
    new_ids = set(r["ceiling_id"] for r in report["created"])
    expected = kept_ids | new_ids
    present = set(c["id"] for c in final)

    v["checks"]["V0_readable_geometry"] = {"unreadable_ceiling_ids": v_unreadable,
                                           "ok": not v_unreadable}
    if v_unreadable:
        v["failures"].append(
            "V0: {} ceiling(s) have no readable plan geometry - the ceiling type probably has "
            "no compound structure (zero thickness)".format(len(v_unreadable)))

    # V1 - every region ended up with the ceiling(s) planned for it. A plain count no longer
    # works: one room can hold two authored drops, and an authored room is deliberately given
    # nothing new, so kept+created == regions is simply not the invariant any more.
    created_by_idx = {}
    for row in report["created"]:
        created_by_idx.setdefault(row["idx"], []).append(row["ceiling_id"])

    unaccounted = []
    for pr in plan["regions"]:
        idx = pr["idx"]
        got = [i for i in created_by_idx.get(idx, []) if i in present]
        if pr["status"] == "create":
            if len(got) != 1:
                unaccounted.append({"idx": idx, "room_id": pr["room_id"],
                                    "status": pr["status"], "created": len(got)})
            continue
        own = [i for i in ((pr.get("authored_ceiling_ids") or []) +
                           ([pr["kept_ceiling_id"]] if pr.get("kept_ceiling_id") else []))
               if i in present]
        # An authored/kept room must still have its own ceiling, and must NOT have been given
        # a second one on top of it - that would be the bug this rule exists to prevent.
        if not own or got:
            unaccounted.append({"idx": idx, "room_id": pr["room_id"], "status": pr["status"],
                                "own_ceilings_present": len(own), "created": len(got)})

    v["checks"]["V1_count"] = {
        "regions": len(regions),
        "authored": len([p for p in plan["regions"] if p["status"] == "authored"]),
        "kept": len(kept_ids & present),
        "created": len(new_ids & present),
        "total_final_ceilings": len(final),
        "unaccounted_regions": unaccounted,
        "ok": not unaccounted,
    }
    if unaccounted:
        v["failures"].append("V1: {} region(s) did not end with the ceiling(s) planned for them"
                             .format(len(unaccounted)))

    leftovers = sorted(present - expected)
    v["checks"]["V1b_no_leftovers"] = {"unexpected_ceiling_ids": leftovers, "ok": not leftovers}
    if leftovers:
        v["failures"].append("V1b: {} unexpected ceiling(s) survived".format(len(leftovers)))

    # V3 - coverage. A region that was CUT must be fully covered by exactly one ceiling. A
    # region whose ceiling somebody authored may be partly bare - that is the new rule, not a
    # defect - so only the "two ceilings over the same point" half applies there.
    by_id = dict((c["id"], c) for c in final)
    uncovered, multi, bare_probes = 0, 0, 0
    for r in regions:
        status = status_by_idx.get(r["idx"], "create")
        probes = r.get("_probes") or probe_points(r["outer"], r["holes"])
        hit_counts = []
        for (px, py) in probes:
            n = 0
            for c in final:
                if not rects_overlap(c["bbox"], r["bbox"]):
                    continue
                if point_in_region(px, py, c["outer"], c.get("holes")):
                    n += 1
            hit_counts.append(n)
        n_zero = len([h for h in hit_counts if h == 0])
        n_multi = len([h for h in hit_counts if h > 1])
        if status == "authored":
            bare_probes += n_zero
        else:
            uncovered += n_zero
        multi += n_multi

        # V2 - area agreement for whatever ceiling now covers this region. `probes` is required
        # to be non-empty: all() over an empty list is True, which would otherwise hand this
        # region the first ceiling whose bbox happened to overlap it.
        cov = None
        for c in final:
            if not rects_overlap(c["bbox"], r["bbox"]):
                continue
            if probes and all(point_in_region(px, py, c["outer"], c.get("holes"))
                              for (px, py) in probes):
                cov = c
                break
        delta = None
        if cov is not None and cov.get("poly_area_sf") is not None:
            delta = round(cov["poly_area_sf"] - r["poly_area_sf"], 4)
        tol = max(cfg["AREA_MATCH_ABS_SF"], cfg["AREA_MATCH_PCT"] * max(r["poly_area_sf"], 1e-9))
        if status == "authored":
            ok = (n_multi == 0)
        else:
            ok = (cov is not None and n_zero == 0 and n_multi == 0
                  and delta is not None and abs(delta) <= tol)
        row = {
            "idx": r["idx"], "room_id": r["room_id"], "room_name": r["room_name"],
            "status": status,
            "region_area_sf": r["poly_area_sf"],
            "wall_top_mm": r.get("wall_top_mm"),
            "ceiling_id": cov["id"] if cov else None,
            "ceiling_area_sf": cov.get("poly_area_sf") if cov else None,
            "delta_sf": delta,
            "probes": len(probes), "probes_uncovered": n_zero, "probes_multi": n_multi,
            "ok": ok,
        }
        if status == "authored":
            row["bare_by_design"] = n_zero > 0
        if cov is not None:
            row["ceiling_bottom_abs_mm"] = (None if cov.get("bottom_z_ft") is None
                                            else round(cov["bottom_z_ft"] * 304.8, 1))
        v["per_region"].append(row)

    v["checks"]["V3_coverage"] = {
        "probes_uncovered": uncovered,
        "probes_in_multiple": multi,
        "probes_bare_under_authored_ceiling": bare_probes,
        "ok": uncovered == 0 and multi == 0,
    }
    if uncovered:
        v["failures"].append("V3: {} probe point(s) in a recut room covered by no ceiling"
                             .format(uncovered))
    if multi:
        v["failures"].append("V3: {} probe point(s) covered by more than one ceiling".format(multi))

    bad_area = [r for r in v["per_region"] if not r["ok"]]
    v["checks"]["V2_area"] = {"regions_failing": len(bad_area), "ok": not bad_area}
    if bad_area:
        v["failures"].append("V2: {} region(s) failed area/coverage".format(len(bad_area)))

    # V5 - each cut ceiling landed on the height resolved for ITS OWN room. The target is per
    # region now, so it is read off the created row rather than off a single per-level number.
    hv = []
    for row in report["created"]:
        c = by_id.get(row["ceiling_id"])
        if c is None:
            continue
        target = row.get("target_mm")
        got = None if c.get("bottom_z_ft") is None else round(c["bottom_z_ft"] * 304.8, 1)
        ok = (target is not None and got is not None and abs(got - target) <= tol_mm)
        hv.append({"ceiling_id": row["ceiling_id"], "room_id": row.get("room_id"),
                   "target_mm": target, "actual_mm": got,
                   "source": row.get("height_source"), "ok": ok})
    v["checks"]["V5_height"] = {"rows": hv, "ok": all(h["ok"] for h in hv) if hv else True}
    if hv and not v["checks"]["V5_height"]["ok"]:
        v["failures"].append("V5: a cut ceiling did not land on the height resolved for its room")

    # V8 - "it should not be below the wall level". A cut ceiling ends where its room's walls
    # end; sitting under them means the room was dropped when nobody asked for a drop. Sitting
    # ABOVE is not checked here - that is V6's job.
    below = []
    for row in report["created"]:
        c = by_id.get(row["ceiling_id"])
        wt = row.get("wall_top_mm")
        if c is None or wt is None or c.get("bottom_z_ft") is None:
            continue
        got = round(c["bottom_z_ft"] * 304.8, 1)
        if wt - got > tol_mm:
            below.append({"ceiling_id": row["ceiling_id"], "room_id": row.get("room_id"),
                          "wall_top_mm": wt, "actual_mm": got, "below_by_mm": round(wt - got, 1)})
    v["checks"]["V8_not_below_wall_top"] = {"hits": below, "ok": not below}
    if below:
        v["failures"].append("V8: {} cut ceiling(s) sit below the top of their room's walls"
                             .format(len(below)))

    # V6 - a new ceiling sitting exactly at another level's elevation is buried in that slab or
    # roof, not hanging in the room. This is what the wall-top height rule produced on 13e (2):
    # ceilings at 3048 mm, which is Roof Level, invisible inside the roof.
    # Scope: this guards the FALLBACK height paths only. It cannot apply when the height came
    # from a measurement of real walls: a perimeter room's walls genuinely run to the roof, so
    # a ceiling flush with them genuinely sits at Roof Level, and that is now the intent rather
    # than the bug. It also cannot apply when the height was copied from the env's own correct
    # ceilings - Project5 has a datum "Level 3" at 2387.6 mm which is exactly where that
    # model's real ceilings sit, and V6 was failing the file for matching them.
    EXEMPT_HEIGHT_SOURCES = ("room's own bounding walls", "level modal wall top",
                             "existing correct ceilings")
    slab_hits = []
    for row in report["created"]:
        c = by_id.get(row["ceiling_id"])
        if c is None or c.get("bottom_z_ft") is None:
            continue
        src = str(row.get("height_source") or "")
        if any(src.startswith(p) for p in EXEMPT_HEIGHT_SOURCES):
            continue
        z_mm = c["bottom_z_ft"] * 304.8
        for l2 in level_by_id.values():
            if eid_value(l2.Id) == c.get("level_id"):
                continue
            if abs(z_mm - l2.Elevation * 304.8) <= 1.0:
                slab_hits.append({"ceiling_id": row["ceiling_id"], "at_mm": round(z_mm, 1),
                                  "coincides_with_level": l2.Name})
    v["checks"]["V6_not_at_slab_level"] = {"hits": slab_hits, "ok": not slab_hits}
    if slab_hits:
        v["failures"].append(
            "V6: {} new ceiling(s) sit exactly at another level's elevation - buried in the "
            "slab/roof".format(len(slab_hits)))

    # V7 - the blanket we deleted covered the whole plate, so the rooms we found should account
    # for most of it. Grossly less means room detection under-detected and large areas are left
    # with no ceiling at all - which looks like "the script did nothing" (Project1: 24 sf of
    # rooms against a plate-wide blanket, because there was no footprint to seal the perimeter).
    deleted_areas = [c.get("poly_area_sf") or 0.0 for c in plan["ceilings"]
                     if c.get("status") == "delete"]
    blanket = max(deleted_areas) if deleted_areas else 0.0
    covered = sum(r["poly_area_sf"] for r in regions)
    ratio = (covered / blanket) if blanket > 0 else None
    v["checks"]["V7_plate_coverage"] = {
        "largest_deleted_ceiling_sf": round(blanket, 1),
        "total_region_area_sf": round(covered, 1),
        "ratio": None if ratio is None else round(ratio, 3),
        "ok": ratio is None or ratio >= 0.6,
    }
    if ratio is not None and ratio < 0.6:
        v["failures"].append(
            "V7: rooms cover only {}% of the deleted ceiling's area ({} of {} sf) - room "
            "detection under-detected, large areas would be left bare".format(
                round(100.0 * ratio, 1), round(covered, 1), round(blanket, 1)))

    v["ok"] = not v["failures"] and not plan["ambiguities"]
    if plan["ambiguities"]:
        v["failures"].append("{} ambiguity(ies) in classification".format(len(plan["ambiguities"])))
    return v
