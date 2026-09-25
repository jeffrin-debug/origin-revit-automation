# Offline test of wall_end_joints.py against the REAL wall generator source. No Revit.
#
#   python test_wall_end_joints_offline.py

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
for m in ("infill_z_fix", "corner_lap", "wall_ceiling_profile", "wall_end_joints", "door_head_courses"):
    src, info = load(m)["apply_to_source"](src)
    check("{} applies".format(m), info.get("applied"), str(info))
compile(src, GEN, "exec")
check("patched generator compiles (all five wall patches together)", True)
check("generator file on disk untouched", open(GEN, encoding="utf-8").read() == raw)

g = {}
for node in ast.parse(src).body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
            "IN_FT", "PANEL_LENGTH_FT", "STUD_SPACING_FT", "JOINT_CLEAR_FT", "MIN_SAFE_SEGMENT_FT",
            "_ORIGIN_WALL_MIN_END_FT", "_ORIGIN_WALL_END_JOINTS"):
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
for node in ast.parse(src).body:
    if isinstance(node, ast.FunctionDef) and node.name in ("course_cells_on_studs", "_origin_wall_end_cells"):
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
IN = 1.0 / 12.0


def studs(length_in):
    xs = [k * 16 * IN for k in range(int(length_in // 16) + 1)]
    if abs(xs[-1] - length_in * IN) > 1e-6:
        xs.append(length_in * IN)
    return xs


def run(length_in, shift_in=0.0, openings=()):
    flo, fhi = 0.0, length_in * IN
    sx = studs(length_in) + [o[0] for o in openings] + [o[2] for o in openings]
    cells, _ = g["course_cells_on_studs"](flo, fhi, shift_in * IN, sx)
    before = [(round(a / IN, 2), round(b / IN, 2)) for (a, b) in cells]
    after = g["_origin_wall_end_cells"](cells, flo, fhi, sx, list(openings), "W1", "interior", 0.0, 4.0)
    return before, [(round(a / IN, 2), round(b / IN, 2)) for (a, b) in after]


print("102.5 in face (the ceiling case, on a wall)")
b, a = run(102.5)
check("generator alone leaves 96 + 6.5", b == [(0.0, 96.0), (96.0, 102.5)], str(b))
check("fixed to 80 + 22.5, joint on the stud at 80 in", a == [(0.0, 80.0), (80.0, 102.5)], str(a))

print("short piece at the START (staggered course)")
b, a = run(200, shift_in=88)
check("generator alone starts with an 8 in piece", b[0] == (0.0, 8.0), str(b))
check("first joint moved to the stud at 16 in", a[0] == (0.0, 16.0) and a[1][0] == 16.0, str(a))

print("a jamb right where the joint wants to go")
door = (78 * IN, 0.0, 114 * IN, 7.3)             # a door whose jamb is at 78 in
b, a = run(102.5, openings=[door])
check("stud at 80 is 2 in from the jamb -> joint goes to the stud at 64 instead",
      a == [(0.0, 64.0), (64.0, 102.5)], str(a))

print("nothing to fix / cannot fix")
b, a = run(120)
check("96 + 24: already fine, untouched", a == b == [(0.0, 96.0), (96.0, 120.0)], str(a))
b, a = run(20)
check("20 in face is one piece", a == [(0.0, 20.0)], str(a))
g["_ORIGIN_WALL_END_JOINTS"][:] = []
cells = [(0.0, 90 * IN), (90 * IN, 100 * IN)]            # studs only at 0, 90, 100 in
a = g["_origin_wall_end_cells"](cells, 0.0, 100 * IN, [0.0, 90 * IN, 100 * IN], [], "W1", "interior", 0.0, 4.0)
rep = g["_ORIGIN_WALL_END_JOINTS"][-1:]
check("no stud can take the joint -> left as is, and reported",
      a == cells and rep and not rep[0]["moved"] and rep[0]["end_piece_was_in"] == 10.0, str(rep))
b, a = run(300)
check("no sheet over 8 ft anywhere", all(y - x <= 96.01 for (x, y) in a), str(a))

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
