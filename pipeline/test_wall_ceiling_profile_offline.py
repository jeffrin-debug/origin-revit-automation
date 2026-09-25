# Offline test of wall_ceiling_profile.py against the REAL wall generator source. No Revit.
#
# Patches the generator source (together with the other stage-2 patches), checks it compiles,
# then runs the injected helpers with a stub ceiling_z_at_point() laid out like 1F wall 008
# face A: 8 ft ceiling (C002) over the first stretch, 9 ft (C003) over the next, nothing after.
#
#   python test_wall_ceiling_profile_offline.py

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")


def load(name):
    ns = {"__name__": name, "__file__": os.path.join(HERE, name + ".py")}
    exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
    return ns


fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


raw = open(GEN, encoding="utf-8").read()
src = raw
for mod in ("infill_z_fix", "corner_lap", "wall_ceiling_profile", "door_head_courses"):
    src, info = load(mod)["apply_to_source"](src)
    check("{} applies".format(mod), info.get("applied"), str(info))
compile(src, GEN, "exec")
check("patched generator compiles (all four patches together)", True)
check("generator file on disk untouched", open(GEN, encoding="utf-8").read() == raw)

tree = ast.parse(src)
want = {"_origin_face_cap_profile", "_origin_cap_breaks", "_origin_cap_at"}
g = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and \
            node.targets[0].id in ("_ORIGIN_FACE_PROFILES", "_ORIGIN_PROBE_STEP_FT", "_ORIGIN_BISECT_STEPS",
                                   "_ORIGIN_NONE_MIN_FT",
                                   "CEILING_PROBE_OFFSET_FT", "CEILING_MIN_CAP_FT"):
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in want:
        exec(compile(ast.Module([node], []), GEN, "exec"), g)


class P(object):
    def __init__(self, x, y, z=0.0):
        self.X, self.Y, self.Z = x, y, z


# wall 008 runs along +Y from y=16.08 ft; face A probes at x - 0.75 ft
START, U, N = P(-37.40, 16.08, 0.0), P(0.0, 1.0), P(-1.0, 0.0)


def fake_ceiling(px, py, planes):
    if 16.39 <= py <= 21.73:
        return 8.0                         # C002
    if 22.12 <= py <= 30.37:
        return 9.0                         # C003
    return None                            # past the rooms


g["ceiling_z_at_point"] = fake_ceiling
warn = []
top = g["_origin_face_cap_profile"](START, U, N, 19.39, ["planes"], "W413119", warn, "interior")
segs = g["_ORIGIN_FACE_PROFILES"][("W413119", "interior")]
print("wall 008 face A")
print("   profile:", [(round(a, 2), round(b, 2), c) for (a, b, c) in segs])
check("profile has the 8 ft and 9 ft stretches",
      [c for (_, _, c) in segs if c is not None] == [8.0, 9.0], str(segs))
b1 = [s for s in segs if s[2] == 8.0][0][1] + START.Y
check("8 ft -> 9 ft change located within 0.5 in of the real edge (21.73..22.12 ft)",
      21.73 - 0.04 <= b1 <= 22.12 + 0.04, "{:.3f} ft".format(b1))
check("course tiling runs full height (a stretch has no ceiling)", top is None)
check("the 4-8 ft course is NOT broken (both ceilings are above it)",
      g["_origin_cap_breaks"]("W413119", "interior", 8.0) == [])
br = g["_origin_cap_breaks"]("W413119", "interior", 9.0)
check("the 8-9 ft course IS broken where the ceiling changes", len(br) >= 1, str(br))
mid8 = (segs[0][0] + segs[0][1]) / 2.0 if segs[0][2] == 8.0 else None
x8 = [((a + b) / 2.0) for (a, b, c) in segs if c == 8.0][0]
x9 = [((a + b) / 2.0) for (a, b, c) in segs if c == 9.0][0]
check("a board under C002 stops at 8 ft", g["_origin_cap_at"]("W413119", "interior", x8, 9.0) == 8.0)
check("a board under C003 runs to 9 ft", g["_origin_cap_at"]("W413119", "interior", x9, 9.0) == 9.0)
check("the change is reported in the warnings", any("ceiling stretches" in w for w in warn))

check("the 0.31 ft 'no ceiling' sliver at the wall start is absorbed (probe past the corner)",
      segs[0][2] == 8.0 and segs[0][0] == 0.0, str(segs[0]))
check("the 5 ft stretch with no ceiling at the far end is real and stays open",
      segs[-1][2] is None and segs[-1][1] - segs[-1][0] > 4.0, str(segs[-1]))

print("single ceiling over the whole face")
g["ceiling_z_at_point"] = lambda px, py, planes: 8.0
top = g["_origin_face_cap_profile"](START, U, N, 19.39, ["planes"], "W1", [], "interior")
check("returns that ceiling, like the old cap", abs(top - 8.0) < 1e-9)
check("no course breaks", g["_origin_cap_breaks"]("W1", "interior", 9.0) == [])

print("soffit band (base 7 ft, ceiling 1 ft above it) keeps the generator's sanity floor")
START2 = P(-32.06, 18.39, 7.0)
g["ceiling_z_at_point"] = lambda px, py, planes: 8.0
top = g["_origin_face_cap_profile"](START2, U, N, 7.2, ["planes"], "W385838", [], "interior")
check("cap ignored -> None, boards unchanged", top is None and
      g["_origin_cap_at"]("W385838", "interior", 3.0, 1.354) == 1.354)

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
