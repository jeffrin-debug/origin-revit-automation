# Offline test of ceiling_end_joints.py against the REAL ceiling generator source. No Revit.
#
#   python test_ceiling_end_joints_offline.py

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py")
mod = {"__name__": "ceiling_end_joints", "__file__": os.path.join(HERE, "ceiling_end_joints.py")}
exec(compile(open(mod["__file__"]).read(), mod["__file__"], "exec"), mod)

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


raw = open(GEN, encoding="utf-8").read()
src, info = mod["apply_to_source"](raw)
check("patch applies to the ceiling generator", info.get("applied"), str(info))
compile(src, GEN, "exec")
check("patched generator compiles", True)
check("generator file on disk untouched", open(GEN, encoding="utf-8").read() == raw)

g = {}
tree = ast.parse(src)
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
            "IN_FT", "PANEL_LENGTH_FT", "FURRING_SPACING_FT", "FURRING_RUN_NS",
            "_ORIGIN_MIN_END_FT", "_ORIGIN_END_JOINTS"):
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in ("_origin_row_intervals", "_origin_span_cells"):
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
g["FURRING_RUN_NS"] = False            # 1F: courses step in Y, sheets run along X
cells = g["_origin_span_cells"]
IN = 1.0 / 12.0


def rect(x0, y0, x1, y1):
    return [(x0 * IN, y0 * IN), (x1 * IN, y0 * IN), (x1 * IN, y1 * IN), (x0 * IN, y1 * IN)]


def inch(cs):
    return [(round(a / IN, 2), round(b / IN, 2)) for (a, b) in cs]


# C007's course y = 340.7..388.7 in: room from x = -446.47 (wall 008) to -343.97 (wall 014)
room = rect(-446.47, 196.7, -343.97, 423.19)
print("1F C007, the selected course")
got = inch(cells(-446.47 * IN, -343.97 * IN, 0.0, 340.7 * IN, 388.7 * IN, room, [], "C428922"))
check("96 + 6.5 becomes 80 + 22.5 (joint moved one 16 in bay, onto the furring at -366.47)",
      got == [(-446.47, -366.47), (-366.47, -343.97)], str(got))
rec = g["_ORIGIN_END_JOINTS"][-1]
check("the move is recorded with where it happened",
      rec["moved"] and rec["joint_was_in"] == -350.47 and rec["joint_now_in"] == -366.47 and
      rec["end_piece_was_in"] == 6.5 and rec["end_piece_now_in"] == 22.5, str(rec))

print("the staggered course next to it (4 ft shift) already has a proper end piece")
got = inch(cells(-446.47 * IN, -343.97 * IN, 4.0, 292.7 * IN, 340.7 * IN, room, [], "C428922"))
check("48 + 54.5 left alone", got == [(-446.47, -398.47), (-398.47, -343.97)], str(got))

print("short piece at the START of a course (stagger)")
got = inch(cells(0.0, 200 * IN, 90 * IN, 0.0, 48 * IN, rect(0, 0, 200, 48), [], "X"))
# row_shift 90 in -> first joint at 6 in: a 6 in piece against the start wall
check("first joint moved from 6 in to 22 in off the wall", got[0] == (0.0, 22.0), str(got))

print("a notched course: the real wall is where the room ends, not the ceiling's bbox")
notched = [(0, 0), (130 * IN, 0), (130 * IN, 24 * IN), (110 * IN, 24 * IN), (110 * IN, 48 * IN), (0, 48 * IN)]
got = inch(cells(0.0, 130 * IN, 0.0, 24 * IN, 48 * IN, notched, [], "N"))
check("course upper half ends at x=110 -> 96 + 14 becomes 80 + 30", got[0] == (0.0, 80.0), str(got))

print("cannot fix without breaking a sheet -> reported, not moved")
g["_ORIGIN_END_JOINTS"][:] = []
got = inch(cells(0.0, 106 * IN, 0.0, 0.0, 48 * IN, rect(0, 0, 106, 48), [], "T"))
check("106 in room: 96 + 10 -> 80 + 26", got == [(0.0, 80.0), (80.0, 106.0)], str(got))
got = inch(cells(0.0, 20 * IN, 0.0, 0.0, 48 * IN, rect(0, 0, 20, 48), [], "S"))
check("a 20 in room is one piece - no joint, nothing to move", got == [(0.0, 20.0)], str(got))
got = inch(cells(0.0, 108 * IN, 88 * IN, 0.0, 48 * IN, rect(0, 0, 108, 48), [], "U"))
check("8 + 96 + 4 in: both ends short but only 108 in to share -> moves only where it can",
      all(b - a <= 96.01 for (a, b) in got), str(got))

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
