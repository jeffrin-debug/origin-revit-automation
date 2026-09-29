# Offline test of corner_end_studs.py (2026-09-29).
#
# C9 wall 004 (W376331, through) x wall 002 (W375946, butting), an outside L-corner drawn with
# 004's end flush with 002's outer face. The generator's corner_pullbacks() and
# corner_face_extents() are lifted with the stage-2 wall patches applied and fed the two real
# walls; the end studs (centred on run_lo/run_hi, FLANGE_FT wide) must then stay clear of the
# boards the corner is hung with. No Revit.

import ast
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")
raw = open(GEN, encoding="utf-8").read()

fails = []


def check(cond, label, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label,
                              ("  [" + str(extra) + "]") if extra and not cond else ""))


def load(mod):
    g = {"__name__": mod}
    p = os.path.join(HERE, mod + ".py")
    exec(compile(open(p).read(), p, "exec"), g)
    return g


src = raw
for mod in ("infill_z_fix", "corner_lap", "corner_end_studs", "wall_ceiling_profile",
            "wall_end_joints", "door_head_courses"):
    src, info = load(mod)["apply_to_source"](src)
    check(info.get("applied"), "{} applies".format(mod), info)
compile(src, GEN, "exec")
check(True, "patched generator compiles (all wall patches together)")
check(open(GEN, encoding="utf-8").read() == raw, "generator file on disk untouched")


class XYZ(object):
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = x, y, z


def build(source):
    ns = {"XYZ": XYZ, "math": math}
    funcs = {"corner_pullbacks", "corner_face_extents", "_line_intersect_2d", "dot", "xyz_mul",
             "xyz_sub", "safe_normalize"}
    consts = {"IN_FT", "DRYWALL_THICKNESS_STD_FT", "FLANGE_FT", "MIN_SAFE_SEGMENT_FT",
              "CORNER_JOIN_TOL_FT", "CORNER_OVERSHOOT_MAX_FT", "CORNER_END_TOL_FT",
              "DRYWALL_CORNER_WRAP_BY_FACE", "HANDLE_CORNERS"}
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in consts:
            exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), ns)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in funcs:
            exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), ns)
    ns["get_wall_curve_data"] = curve
    ns["get_wall_width"] = lambda w: w.width
    ns["eid_value"] = lambda e: e.Value
    ns["_joined_walls_at"] = lambda w, end: []
    return ns


class Id(object):
    def __init__(self, v):
        self.Value = v

    def __eq__(self, o):
        return self.Value == o.Value

    def __ne__(self, o):
        return self.Value != o.Value


F = 1.0 / 12.0


class Wall(object):
    def __init__(self, eid, p0, p1, width_in, orient):
        self.Id = Id(eid)
        self.p0 = XYZ(p0[0] * F, p0[1] * F)
        self.p1 = XYZ(p1[0] * F, p1[1] * F)
        self.width = width_in * F
        self.Orientation = XYZ(*orient)


def curve(w):
    L = math.hypot(w.p1.X - w.p0.X, w.p1.Y - w.p0.Y)
    return w.p0, w.p1, XYZ((w.p1.X - w.p0.X) / L, (w.p1.Y - w.p0.Y) / L), L


# C9, live 2026-09-29 (inches)
W002 = Wall(375946, (-445.77, 452.83), (-445.77, 423.83), 4.0, (1.0, 0.0))    # butting, runs south
W004 = Wall(376331, (-447.77, 423.83), (-389.77, 423.83), 4.0, (0.0, 1.0))    # through, runs east
walls = [W002, W004]
cands = [(w, curve(w), w.width) for w in walls]
HALF = 1.25 / 2.0
T = 0.5


def studs(ns, w):
    du0, du1 = ns["corner_pullbacks"](w, [], cands)
    L = curve(w)[3]
    return du0 * 12, (L - du1) * 12, L * 12


print("generator as-is (corner_lap only): the C9 defect")
old = build(load("corner_lap")["apply_to_source"](raw)[0])
lo4, _, _ = studs(old, W004)
check(abs((lo4 - HALF) - (-HALF)) < 1e-3,
      "wall 004's end stud pokes 5/8in past its end (into DP-002-001A's space)", lo4)

ns = build(src)
print("\nwith corner_end_studs")
lo4, hi4, L4 = studs(ns, W004)
lo2, hi2, L2 = studs(ns, W002)
e2 = ns["corner_face_extents"](W002, cands)
e4 = ns["corner_face_extents"](W004, cands)
# wall 004: along-wall 0 = x -447.77 (002's outer face). 002's west board occupies [0, t] there.
check(abs((lo4 - HALF) - T) < 1e-3, "004's end stud starts behind 002's board (at t = 0.5in)", lo4 - HALF)
check(abs(e4["interior"][0] * 12 - 0.0) < 1e-3,
      "004's outer-face board still laps to 002's outer face", e4["interior"])
# wall 002: along-wall L2 = y 423.83 (004's centerline); 004's near (north) face is 2in before it.
check(abs((hi2 + HALF) - (L2 - 2.0)) < 1e-3,
      "002's end stud's flange stops flush at 004's north face", (hi2 + HALF, L2 - 2.0))
west_hi = max(e2["interior"][1], e2["exterior"][1]) * 12
check(abs(west_hi - (L2 + 2.0 - T)) < 1e-3,
      "002's outer-face board runs on to the back of 004's lapping board", west_hi)
# the two end studs no longer share any plan space: 002's stud ends at y 425.83, 004's core ends there
s4_y = (423.83 - 1.5, 423.83 + 1.5)                       # 004's 3in core
s2_y_lo = 452.83 - (hi2 + HALF)                           # 002's stud, south edge
check(s2_y_lo >= s4_y[1] + 0.5 - 1e-3, "002's end stud clears 004's core and north board", s2_y_lo)

print("\nfree ends and T-joins keep the centred end stud")
_, hi4f, _ = studs(ns, W004)
check(abs(hi4f - L4) < 1e-3, "004's far (free) end is unchanged", hi4f)
STEM = Wall(900001, (-420.0, 500.0), (-420.0, 423.83), 4.0, (1.0, 0.0))        # tees into 004 (to its centerline)
c2 = cands + [(STEM, curve(STEM), STEM.width)]
du0, du1 = ns["corner_pullbacks"](STEM, [], c2)
check(abs(du1 * 12 - 2.0) < 1e-3, "a T stem still butts at the through wall's face (no inset)", du1 * 12)

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
