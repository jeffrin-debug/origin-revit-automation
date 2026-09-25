# Offline test of the new ceiling classifier.
#
# match_ceilings_to_regions() touches no Revit API at all - it works on plain dicts - so the
# whole decision table can be exercised outside Revit by stubbing the two imports the core
# module makes at load time.

import sys, types

import os

# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

for name in ("Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB",
             "System", "System.Collections", "System.Collections.Generic"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["System.Collections.Generic"].List = object

CORE = os.path.join(_paths["CEILING_ROOT"], "origin_ceiling_rebuild_core.py")
core = {"__name__": "origin_ceiling_rebuild_core"}
exec(compile(open(CORE, encoding="utf-8").read(), CORE, "exec"), core)

CFG = core["CFG"]
MM = core["FT_PER_MM"]
poly_area = core["poly_area"]
poly_bbox = core["poly_bbox"]
match = core["match_ceilings_to_regions"]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def region(idx, name, poly, wall_top_mm):
    return {
        "idx": idx, "room_id": 1000 + idx, "room_name": name, "level_id": 1,
        "outer": poly, "holes": [], "bbox": poly_bbox(poly),
        "poly_area_sf": round(poly_area(poly), 4),
        "wall_top_ft": wall_top_mm * MM, "wall_top_mm": wall_top_mm,
        "wall_top_info": {"bounding_walls": 4, "rule": "modal",
                          "wall_top_mm": wall_top_mm, "agreeing_walls": 4},
    }


def ceiling(cid, poly, bottom_mm):
    return {
        "id": cid, "is_ceiling_category": True, "category": "Ceilings",
        "type": "GWB on Mtl. Stud", "type_id": 7, "level_id": 1,
        "outer": poly, "holes": [], "bbox": poly_bbox(poly),
        "poly_area_sf": round(poly_area(poly), 4),
        "area_sf": round(poly_area(poly), 4),
        "bottom_z_ft": bottom_mm * MM, "offset_mm": bottom_mm,
        "hosted_family_instances": [],
    }


# --- the model -----------------------------------------------------------------------------
A = rect(0, 0, 10, 10)          # 100 sf, walls end 3000
B = rect(12, 0, 24, 10)         # 120 sf, walls end 3000
C = rect(26, 0, 34, 10)         # 80 sf,  walls end 2800  <- interior partitions stop lower
D = rect(0, 20, 10, 30)         # 100 sf, walls end 3000
E = rect(12, 20, 32, 30)        # 200 sf, walls end 3000
F = rect(0, 40, 10, 50)         # 100 sf, walls end 3000
G = rect(12, 40, 22, 50)        # 100 sf, walls end 3000
H = rect(24, 40, 34, 50)        # 100 sf, walls end 3000

regions = [
    region(0, "A drop + blanket", A, 3000.0),
    region(1, "B blanket only", B, 3000.0),
    region(2, "C blanket only, lower walls", C, 2800.0),
    region(3, "D drop + exact top ceiling", D, 3000.0),
    region(4, "E partial drop", E, 3000.0),
    region(5, "F exact top ceiling only", F, 3000.0),
    region(6, "G top ceiling 30mm under", G, 3000.0),
    region(7, "H top ceiling 60mm under", H, 3000.0),
]

ceilings = [
    ceiling(101, rect(-1, -1, 35, 11), 3000.0),   # the blanket over A + B + C
    ceiling(102, A, 2700.0),                      # authored drop, whole of room A
    ceiling(103, D, 2700.0),                      # authored drop, whole of room D
    ceiling(104, D, 3000.0),                      # top ceiling fitting D exactly -> must go
    ceiling(105, rect(13, 21, 23, 27), 2700.0),   # authored drop over PART of room E (60 sf)
    ceiling(106, F, 3000.0),                      # already correct at the wall top
    ceiling(107, G, 2970.0),                      # 30 mm under -> noise, not a drop
    ceiling(108, H, 2940.0),                      # 60 mm under -> a real drop
]

# The decision table below is the "each room at its own wall top" rule, so it runs with the
# lower-ceiling rule OFF. That rule has its own checks at the end.
CFG_WALLTOP = dict(CFG, FOLLOW_LOWER_AUTHORED_CEILING=False)
plan = match(regions, ceilings, CFG_WALLTOP)

status = dict((c["id"], c["status"]) for c in plan["ceilings"])
reason = dict((c["id"], c["reason"]) for c in plan["ceilings"])
rstat = dict((r["idx"], r) for r in plan["regions"])

EXPECT_C = {
    101: ("delete", "blanket spanning A+B+C"),
    102: ("keep", "authored drop in A"),
    103: ("keep", "authored drop in D"),
    104: ("delete", "top ceiling over D, which already has a drop"),
    105: ("keep", "partial authored drop in E"),
    106: ("keep", "already correct at the wall top"),
    107: ("keep", "30 mm under = noise, kept as the top ceiling"),
    108: ("keep", "60 mm under = a real drop"),
}
EXPECT_R = {
    0: ("authored", None),
    1: ("create", 3000.0),
    2: ("create", 2800.0),
    3: ("authored", None),
    4: ("authored", None),
    5: ("kept", None),
    6: ("kept", None),
    7: ("authored", None),
}

fails = []

print("CEILINGS")
for cid in sorted(EXPECT_C):
    want, why = EXPECT_C[cid]
    got = status.get(cid)
    ok = got == want
    fails.append(ok)
    print("  {}  {:<8} want {:<8} {}  [{}]".format(
        "PASS" if ok else "FAIL", got, want, why, (reason.get(cid) or "")[:64]))

print("\nREGIONS")
for idx in sorted(EXPECT_R):
    want, want_h = EXPECT_R[idx]
    r = rstat[idx]
    ok = r["status"] == want
    fails.append(ok)
    line = "  {}  {:<20} {:<9} want {:<9} area={:>6.1f} bare={:>5.1f} wall_top={}".format(
        "PASS" if ok else "FAIL", r["room_name"][:20], r["status"], want,
        r["area_sf"], r["bare_area_sf"], r["wall_top_mm"])
    print(line)

print("\nTARGETED ASSERTIONS")


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra and not cond else ""))


check("blanket deleted, not kept for any single room",
      status[101] == "delete")
check("room D's top-height ceiling removed because D has an authored drop",
      status[104] == "delete" and "already has an authored ceiling" in (reason[104] or ""))
check("no ceiling is created for any authored room",
      all(rstat[i]["status"] == "authored" for i in (0, 3, 4, 7)))
check("E keeps only the person's 60 sf piece; the other 140 sf stays bare",
      abs(rstat[4]["bare_area_sf"] - 140.0) < 0.01)
check("B and C are both cut, at DIFFERENT heights (3000 vs 2800)",
      rstat[1]["wall_top_mm"] == 3000.0 and rstat[2]["wall_top_mm"] == 2800.0)
check("fully covered rooms report no bare area",
      rstat[0]["bare_area_sf"] == 0.0 and rstat[3]["bare_area_sf"] == 0.0)
check("50 mm drop threshold splits 30 mm (noise) from 60 mm (authored)",
      rstat[6]["status"] == "kept" and rstat[7]["status"] == "authored")
check("no ambiguities raised", plan["ambiguities"] == [])

# --- the lower authored ceiling wins (FOLLOW_LOWER_AUTHORED_CEILING, 2026-09-25) ------------
# Same model with the rule ON: the lowest authored drop on the level (2700 mm, ceilings 102/103/
# 105) becomes the height every cut ceiling follows, and the top-layer ceilings above it
# (F 3000, G 2970) are recut down to it instead of kept.
print("\nLOWER CEILING WINS")
for c in ceilings:
    for k in ("spans_room_ids", "partial_room_ids", "drop_below_wall_top_mm",
              "keep_reason", "delete_reason"):
        c.pop(k, None)
plan2 = match(regions, ceilings, dict(CFG, FOLLOW_LOWER_AUTHORED_CEILING=True))
st2 = dict((c["id"], c["status"]) for c in plan2["ceilings"])
rs2 = dict((r["idx"], r) for r in plan2["regions"])
ref = plan2["follow_z_by_level"].get(1)
check("level reference = the lowest authored drop, 2700 mm",
      ref is not None and abs(ref["z_ft"] / MM - 2700.0) < 0.01)
check("authored drops are still kept", all(st2[i] == "keep" for i in (102, 103, 105, 108)))
check("F (3000) and G (2970) top-layer ceilings are recut down, not kept",
      st2[106] == "delete" and st2[107] == "delete" and
      rs2[5]["status"] == "create" and rs2[6]["status"] == "create")
check("D's top ceiling still goes for the original reason",
      st2[104] == "delete" and "already has an authored ceiling" in
      (dict((c["id"], c["reason"]) for c in plan2["ceilings"])[104] or ""))

# region_ceiling_height() is where the height is actually chosen for a cut ceiling
rch = core["region_ceiling_height"]
for idx, wt in ((1, 3000.0), (2, 2800.0), (5, 3000.0)):
    r = next(x for x in regions if x["idx"] == idx)
    z, why = rch(None, r, None, [], plan2, [], dict(CFG, FOLLOW_LOWER_AUTHORED_CEILING=True))
    check("room {} (walls {} mm) is cut at 2700 mm, source '{}'".format(
        r["room_name"][:1], wt, why[:34]),
        abs(z / MM - 2700.0) < 0.01 and why.startswith(core["FOLLOW_SOURCE"]))
z, why = rch(None, next(x for x in regions if x["idx"] == 1), None, [], plan, [], CFG_WALLTOP)
check("rule OFF: room B is cut at its own wall top again (3000 mm)", abs(z / MM - 3000.0) < 0.01)

# --- height per room (default since 2026-09-25) + the created-by-script tag -------------------
# A ceiling THIS script cut at 2700 mm (under the old lower-ceiling rule) looks exactly like a
# person's drop. Tagged, it must be recut to its room's own wall top, not kept as "authored".
print("\nHEIGHT PER ROOM + CREATED TAG")
check("default config is height per room", core["CFG"]["FOLLOW_LOWER_AUTHORED_CEILING"] is False)
X = rect(40, 0, 50, 10)
rx = region(8, "X ours at 2700", X, 3000.0)
ours = ceiling(201, X, 2700.0)
ours["created_by_script"] = True
theirs = ceiling(202, rect(40, 20, 50, 30), 2700.0)          # same height, a person's drop
ry = region(9, "Y person's drop", rect(40, 20, 50, 30), 3000.0)
plan3 = match([rx, ry], [ours, theirs], core["CFG"])
st3 = dict((c["id"], (c["status"], c["reason"])) for c in plan3["ceilings"])
rs3 = dict((r["idx"], r["status"]) for r in plan3["regions"])
check("our 2700 mm ceiling is recut, not treated as authored",
      st3[201][0] == "delete" and "created by this script" in (st3[201][1] or "") and rs3[8] == "create",
      str(st3[201]))
check("a person's identical 2700 mm drop is still kept as authored",
      st3[202][0] == "keep" and rs3[9] == "authored")
z, why = rch(None, rx, None, [], plan3, [], core["CFG"])
check("room X is recut at its own wall top (3000 mm)", abs(z / MM - 3000.0) < 0.01, why)
ours_ok = ceiling(203, X, 3000.0)
ours_ok["created_by_script"] = True
plan4 = match([rx], [ours_ok], core["CFG"])
check("our ceiling already at the room's height is kept (no churn on reruns)",
      plan4["ceilings"][0]["status"] == "keep" and plan4["regions"][0]["status"] == "kept")

s = plan["summary"]
print("\nSUMMARY  regions={} authored={} kept={} create={} bare={} sf  keep={} delete={}".format(
    s["regions_total"], s["regions_authored"], s["regions_kept"], s["regions_to_create"],
    s["bare_area_sf"], s["ceilings_keep"], s["ceilings_delete"]))

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
