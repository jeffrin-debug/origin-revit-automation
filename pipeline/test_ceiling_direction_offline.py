# Offline test of the ceiling panel direction rule.
#
# decide_from_doors() and the geometry helpers touch no Revit API, so the rule can be checked
# against synthetic sites without opening a single model. That matters here: the whole point of
# this change is that ONE rule has to hold across many envs, and stepping through them all in
# Revit is not a practical way to find out.
#
#   python test_ceiling_direction_offline.py

import sys, types, math

import os

# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

for name in ("Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB"):
    sys.modules.setdefault(name, types.ModuleType(name))

MOD = os.path.join(_paths["PIPELINE_ROOT"], "ceiling_direction.py")
m = {"__name__": "ceiling_direction"}
exec(compile(open(MOD, encoding="utf-8").read(), MOD, "exec"), m)

decide = m["decide_from_doors"]
dist_to_boundary = m["dist_to_boundary"]
poly_area = m["poly_area"]
CFG = m["CFG"]

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    line = "  {}  {}".format("PASS" if cond else "FAIL", label)
    if extra:
        line += "   [{}]".format(extra)
    print(line)


def door(w_mm, facing, exterior=True, name="D", edge_m=None):
    if edge_m is None:
        edge_m = 0.15 if exterior else 12.0
    return {"id": abs(hash((w_mm, facing, exterior, name, edge_m))) % 100000, "name": name,
            "x": 0.0, "y": 0.0, "host_wall_id": 1,
            "width_ft": w_mm / 304.8, "width_mm": w_mm,
            "facing": facing, "facing_source": "FacingOrientation",
            "dist_to_edge_ft": edge_m * 3.28084,
            "dist_to_edge_m": edge_m,
            "exterior": exterior,
            "usable": (facing is not None and (w_mm / 304.8) >= CFG["MIN_DOOR_WIDTH_FT"])}


print("GEOMETRY")
site = [(0, 0), (100, 0), (100, 60), (0, 60)]
check("area of a 100x60 plate", abs(poly_area(site) - 6000.0) < 1e-6)
check("door in the south wall reads as 0 ft from the edge",
      abs(dist_to_boundary(50, 0, site)) < 1e-9)
check("door 1 ft inside the south wall reads 1 ft",
      abs(dist_to_boundary(50, 1, site) - 1.0) < 1e-9)
check("door in the middle of the plate is far from any edge",
      abs(dist_to_boundary(50, 30, site) - 30.0) < 1e-9)
check("a point just OUTSIDE the wall still reads ~0 (unsigned)",
      abs(dist_to_boundary(50, -0.5, site) - 0.5) < 1e-9)

print("\nTHE RULE - furring runs ALONG the walk-in direction")
# A door in the SOUTH wall faces north: you walk in along +Y.
r = decide([door(3000, (0.0, 1.0))])
check("door facing +Y -> walk-in along Y", r["walk_in_axis"] == "y", r.get("reason", "")[:40])
check("  -> furring along Y -> FURRING_RUN_NS = False", r["furring_run_ns"] is False)
check("  -> boards' long edge along X", r["boards_long_edge_along"] == "X")

# A door in the WEST wall faces east: you walk in along +X.
r = decide([door(3000, (1.0, 0.0))])
check("door facing +X -> walk-in along X", r["walk_in_axis"] == "x")
check("  -> furring along X -> FURRING_RUN_NS = True", r["furring_run_ns"] is True)
check("  -> boards' long edge along Y", r["boards_long_edge_along"] == "Y")

# Which WAY along the axis is irrelevant - a run axis has no sign.
r_pos = decide([door(3000, (1.0, 0.0))])
r_neg = decide([door(3000, (-1.0, 0.0))])
check("facing -X gives the same answer as +X (a run axis has no direction)",
      r_pos["furring_run_ns"] == r_neg["furring_run_ns"] is True)

print("\nPICKING THE MAIN DOOR")
doors = [
    door(900, (1.0, 0.0), exterior=True, name="side entrance"),
    door(3000, (0.0, 1.0), exterior=True, name="MAIN entrance"),
    door(2100, (1.0, 0.0), exterior=False, name="interior double"),
]
r = decide(doors)
check("widest EXTERIOR door wins", r["main_door"]["name"] == "MAIN entrance",
      "{} mm".format(r["main_door"]["width_mm"]))
check("  a wider interior door does not steal it", r["furring_run_ns"] is False)
check("  pool is the exterior set", r["pool"] == "exterior")

doors = [
    door(4000, (1.0, 0.0), exterior=False, name="big interior"),
    door(2500, (0.0, 1.0), exterior=False, name="other interior"),
]
r = decide(doors)
check("no exterior door -> falls back to widest anywhere", r["main_door"]["name"] == "big interior")
check("  and says so in a warning",
      any("edge" in w for w in r["warnings"]), (r["warnings"] or [""])[0][:50])

print("\n1F REGRESSION - real numbers off the live model, 2026-09-17")
# 25 x 20 ft plate. A flat 2 m band covered the whole building, every door read as exterior,
# and the WIDEST one - sitting in the middle of the plan at 1.969 m - won. The real entrance is
# the 813 mm door 0.095 m from the south boundary, facing +Y.
f1 = [
    door(914.4, (-1.0, 0.0), name="381894 mid-plan", edge_m=1.969),
    door(914.4, (-1.0, 0.0), name="382148", edge_m=1.165),
    door(812.8, (0.0, -1.0), name="381965", edge_m=0.633),
    door(812.8, (-1.0, 0.0), name="381995", edge_m=1.267),
    door(812.8, (0.0, 1.0), name="382055 REAL entrance", edge_m=0.095),
]
r = decide(f1)
check("1F: picks the door in the exterior wall, not the widest interior one",
      r["main_door"]["name"].startswith("382055"), r["main_door"]["name"])
check("1F: adaptive band excludes the mid-plan doors",
      abs(r["edge_band_m"] - 0.395) < 1e-6, "band {} m".format(r.get("edge_band_m")))
check("1F: only the perimeter door survives the band",
      len([d for d in f1 if d["exterior"]]) == 1)
check("1F: -> walk-in along Y -> FURRING_RUN_NS = False (the 90 deg flip)",
      r["walk_in_axis"] == "y" and r["furring_run_ns"] is False)
check("1F: no spurious 'guess' warning - 0.095 m really is in the wall",
      not any("guess" in w for w in r["warnings"]))

# Several doors genuinely in the perimeter: width is then the right tie-break again.
r = decide([
    door(900, (0.0, 1.0), name="side", edge_m=0.10),
    door(1800, (1.0, 0.0), name="MAIN double", edge_m=0.12),
    door(850, (0.0, -1.0), name="back", edge_m=0.08),
])
check("several doors at the perimeter -> widest still wins",
      r["main_door"]["name"] == "MAIN double" and r["furring_run_ns"] is True)

# Nothing near the boundary at all - decide, but say it is a guess.
r = decide([door(1000, (1.0, 0.0), name="deep inside", edge_m=4.0)])
check("no door anywhere near the edge -> warns that the pick is a guess",
      any("guess" in w for w in r["warnings"]), (r["warnings"] or [""])[0][:55])

print("\nREJECTIONS AND EDGE CASES")
r = decide([])
check("no doors at all -> unresolved, generator keeps its own default",
      r["furring_run_ns"] is None and not r["ok"])
check("  and the reason names the gap-modelled doorway case",
      "gap" in (r.get("reason") or ""), (r.get("reason") or "")[:60])

r = decide([door(500, (1.0, 0.0))])
check("a 500 mm cupboard door is not a way in",
      r["furring_run_ns"] is None and not r["ok"])

r = decide([door(3000, None)])
check("a door with no readable facing is ignored", r["furring_run_ns"] is None)

r = decide([door(900, (1.0, 0.0)), door(3000, None), door(2400, (0.0, 1.0))])
check("unusable doors are skipped, the widest USABLE one wins",
      r["ok"] and r["main_door"]["width_mm"] == 2400 and r["furring_run_ns"] is False)

print("\nROTATED SITES (snapped to nearest axis)")
for deg, want_axis, want_off in ((0, "x", 0.0), (10, "x", 10.0), (44, "x", 44.0),
                                 (46, "y", 44.0), (80, "y", 10.0), (90, "y", 0.0)):
    rad = math.radians(deg)
    r = decide([door(3000, (math.cos(rad), math.sin(rad)))])
    ok = (r["walk_in_axis"] == want_axis and abs(r["off_axis_deg"] - want_off) < 0.01)
    check("door at {:2d} deg -> axis {} , off-axis {:.0f} deg".format(deg, want_axis.upper(), want_off), ok,
          "got {} / {}".format(r["walk_in_axis"], r["off_axis_deg"]))

r = decide([door(3000, (math.cos(math.radians(40)), math.sin(math.radians(40))))])
check("a badly-rotated site warns that snapping fits poorly",
      any("rotated" in w for w in r["warnings"]))
r = decide([door(3000, (math.cos(math.radians(5)), math.sin(math.radians(5))))])
check("a nearly axis-aligned site does NOT warn",
      not any("rotated" in w for w in r["warnings"]))

print("\nHEADER FALLBACK - envs with no Door elements (409, PH2A, Project2 - PH1 B)")
# collect_header_openings derives facing from the header wall's NORMAL: for a wall running
# (dx,dy) the opening is walked through at (-dy,dx). The geometry read needs Revit; this checks
# the relationship it depends on, and that header rows decide exactly like door rows.
import math as _m


def header(span_mm, wall_dx, wall_dy, edge_m=0.1, name="hdr"):
    L = _m.hypot(wall_dx, wall_dy)
    facing = (-wall_dy / L, wall_dx / L)          # same expression as the resolver
    return door(span_mm, facing, name=name, edge_m=edge_m)


r = decide([header(900, 1.0, 0.0, name="header in an E-W wall")])
check("header in a wall running X -> you walk through along Y",
      r["walk_in_axis"] == "y" and r["furring_run_ns"] is False)

r = decide([header(900, 0.0, 1.0, name="header in a N-S wall")])
check("header in a wall running Y -> you walk through along X",
      r["walk_in_axis"] == "x" and r["furring_run_ns"] is True)

# A whole door-less env: several headers, the widest one in the perimeter wins, exactly as
# doors do - the fallback reuses decide_from_doors rather than duplicating the rule.
env = [
    header(800, 1.0, 0.0, edge_m=2.4, name="interior header"),
    header(1200, 0.0, 1.0, edge_m=0.08, name="MAIN opening"),
    header(900, 1.0, 0.0, edge_m=0.9, name="side header"),
]
r = decide(env)
check("door-less env: widest perimeter opening wins",
      r["main_door"]["name"] == "MAIN opening", r["main_door"]["name"])
check("  -> walk-in along X -> FURRING_RUN_NS = True",
      r["walk_in_axis"] == "x" and r["furring_run_ns"] is True)
check("  the adaptive band still excludes the deeper headers",
      len([d for d in env if d["exterior"]]) == 1)

# A header too narrow to be a doorway is rejected by the same width floor doors use.
r = decide([header(400, 1.0, 0.0)])
check("a 400 mm header is not a doorway", r["furring_run_ns"] is None)

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
