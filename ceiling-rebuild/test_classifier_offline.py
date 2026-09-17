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

plan = match(regions, ceilings, CFG)

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


def check(label, cond):
    fails.append(bool(cond))
    print("  {}  {}".format("PASS" if cond else "FAIL", label))


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

s = plan["summary"]
print("\nSUMMARY  regions={} authored={} kept={} create={} bare={} sf  keep={} delete={}".format(
    s["regions_total"], s["regions_authored"], s["regions_kept"], s["regions_to_create"],
    s["bare_area_sf"], s["ceilings_keep"], s["ceilings_delete"]))

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
