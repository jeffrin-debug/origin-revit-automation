# Offline test of the wall generator's corner_face_extents() collinear clamp (2026-09-28).
#
# The clamp that stops a corner wrap running into a wall on the SAME line only checked that the
# other wall was parallel, so any parallel wall whose end lined up with a corner cancelled the
# wrap. 2C: wall 003 (40in away) stopped DP-027-001A 1.87in short of DP-028-001B. The function is
# lifted from the generator with corner_lap.py's patch applied (as stage 2 runs it) and fed 2C's
# real walls. No Revit.

import ast
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")
src = open(GEN, encoding="utf-8").read()
cl = {"__name__": "corner_lap"}
exec(compile(open(os.path.join(HERE, "corner_lap.py")).read(), "corner_lap.py", "exec"), cl)
src, info = cl["apply_to_source"](src)


class XYZ(object):
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = x, y, z


ns = {"XYZ": XYZ, "math": math}
FUNCS = {"corner_face_extents", "_line_intersect_2d", "dot", "xyz_mul", "xyz_sub", "safe_normalize"}
CONSTS = {"IN_FT", "DRYWALL_THICKNESS_STD_FT", "FLANGE_FT", "MIN_SAFE_SEGMENT_FT", "CORNER_JOIN_TOL_FT",
          "CORNER_OVERSHOOT_MAX_FT", "CORNER_END_TOL_FT", "DRYWALL_CORNER_WRAP_BY_FACE"}
tree = ast.parse(src)
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) in CONSTS:
        exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), ns)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), ns)


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


ns["get_wall_curve_data"] = curve
ns["get_wall_width"] = lambda w: w.width
ns["eid_value"] = lambda e: e.Value
extents = ns["corner_face_extents"]

fails = []


def check(cond, label, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label,
                              ("  [" + str(extra) + "]") if extra and not cond else ""))


def ext_in(w, walls):
    e = extents(w, [(o, curve(o), o.width) for o in walls])
    return dict((k, (round(v[0] * 12, 3), round(v[1] * 12, 3))) for k, v in e.items())


check(info.get("applied"), "corner_lap patch applies to the generator", info)

# 2C, live 2026-09-28 (inches)
W027 = Wall(434571, (-431.096, 322.635), (-431.096, 251.887), 4.747, (1.0, 0.0))
W028 = Wall(434933, (-431.096, 322.635), (-327.351, 322.635), 4.747, (0.0, 1.0))
W003 = Wall(376337, (-391.104, 322.635), (-391.104, 512.757), 4.747, (-1.0, 0.0))   # parallel, 40in off
W009 = Wall(380373, (-355.849, 251.887), (-355.849, 187.14), 4.747, (1.0, 0.0))     # parallel, 75in off
W034 = Wall(438865, (-431.096, 251.887), (-327.351, 251.887), 4.747, (0.0, 1.0))
LAP = 4.747 / 2.0 - 0.5                                                             # hwO - t

print("2C outside corner 027 / 028")
walls = [W027, W028, W003, W009, W034]
e = ext_in(W027, walls)
check(abs(e["interior"][0] - (-LAP)) < 1e-3,
      "DP-027-001A's face runs 1.87in past the corner, to the back of DP-028-001B", e["interior"])
e28 = ext_in(W028, walls)
check(abs(e28["exterior"][0] - (-4.747 / 2.0)) < 1e-3,
      "wall 028 (the through wall) still laps to 027's outer face", e28["exterior"])
alone = ext_in(W027, [W027, W028, W034])
check(e["interior"] == alone["interior"],
      "walls 003 / 009 (parallel, other lines) no longer change 027 at all", (e, alone))

print("\na real collinear neighbour still clamps the wrap")
# a jamb stub on 027's own line, starting 1in past 027's end - the case the clamp exists for
STUB = Wall(900001, (-431.096, 323.635), (-431.096, 340.0), 4.747, (1.0, 0.0))
ec = ext_in(W027, [W027, W028, W034, STUB])
check(ec["interior"][0] >= -1.0 - 1e-3, "wrap stops at the stub on the same line", ec["interior"])
OFF = Wall(900002, (-431.096 + 4.9, 323.635), (-431.096 + 4.9, 340.0), 4.747, (1.0, 0.0))
eo = ext_in(W027, [W027, W028, W034, OFF])
check(abs(eo["interior"][0] - (-LAP)) < 1e-3,
      "a parallel wall just clear of 027's thickness does not", eo["interior"])

print("\na T whose through wall is two collinear pieces is a T, not an L (2C)")
# 008 tees into 034 + the 2.37in stub 026: both faces butt at the through wall's north face
W008 = Wall(379222, (-327.351, 344.01), (-327.351, 251.887), 4.747, (1.0, 0.0))
W026 = Wall(434148, (-327.351, 251.887), (-324.978, 251.887), 4.747, (0.0, 1.0))
e = ext_in(W008, [W008, W026, W034])
face_y = 251.887 + 4.747 / 2.0                                  # 034 / 026 north face
want = round(344.01 - face_y, 3)
check(e["interior"][1] == want and e["exterior"][1] == want,
      "wall 008: both faces butt at 034/026's face - no wrap into 034", e)
# 012 tees into 013 (4.75in) + 029 (7.25in, centerline 1.25in off): each face butts ITS piece
W012 = Wall(383828, (-531.854, 512.757), (-531.854, 183.14), 4.747, (1.0, 0.0))
W013 = Wall(384037, (-573.104, 183.14), (-531.854, 183.14), 4.747, (0.0, 1.0))
W029 = Wall(435687, (-495.105, 184.391), (-531.854, 184.391), 7.25, (0.0, -1.0))
e = ext_in(W012, [W012, W013, W029])
check(abs(e["exterior"][1] - (512.757 - (184.391 + 3.625))) < 1e-2,
      "wall 012's east face butts the 7.25in piece 029 on its side", e["exterior"])
check(abs(e["interior"][1] - (512.757 - (183.14 + 4.747 / 2.0))) < 1e-2,
      "wall 012's west face butts the 4.75in piece 013 on its side", e["interior"])
# 018 tees into 011 + 033, split 2in beside 018's end
W018 = Wall(386129, (-241.48, 122.766), (-209.48, 122.766), 4.0, (0.0, 1.0))
W011 = Wall(381426, (-207.105, 399.95), (-207.105, 124.766), 4.747, (1.0, 0.0))
W033 = Wall(438415, (-207.105, 124.766), (-207.105, 113.516), 4.747, (1.0, 0.0))
e = ext_in(W018, [W018, W011, W033])
check(abs(e["interior"][1] - 32.0) < 1e-2 and abs(e["exterior"][1] - 32.0) < 1e-2,
      "wall 018: both faces butt at 011/033's face", e)
print("\na real outside L corner is still an L")
e = ext_in(W027, [W027, W028, W034, W026, W008])
check(abs(e["interior"][0] - (-LAP)) < 1e-3, "027/028 still laps with the T walls present", e["interior"])

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
