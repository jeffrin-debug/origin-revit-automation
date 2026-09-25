# Offline test of door_head_courses.py against the REAL wall generator source. No Revit.
#
# Applies the patch to the generator's source string, checks it still compiles, then pulls the
# row / cut functions out of the patched source and runs them on the door cases that matter:
#   8'-0" door on a 10 ft wall  -> 4 + 2 + 4, head inside the top sheet
#   7'-0" door on a 10 ft wall  -> unchanged 4 + 4 + 2
#   8'-0" door under a 9 ft ceiling -> 4 + 2 + 3
#   no door / window only / second layer -> unchanged
#
#   python test_door_head_courses_offline.py

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")

_d = {"__name__": "door_head_courses", "__file__": os.path.join(HERE, "door_head_courses.py")}
exec(compile(open(_d["__file__"]).read(), _d["__file__"], "exec"), _d)

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("\n          " + extra) if extra else ""))


raw = open(GEN, encoding="utf-8").read()
src, info = _d["apply_to_source"](raw)
check("patch applied to the generator source", info.get("applied"), str(info))
check("generator file on disk untouched", open(GEN, encoding="utf-8").read() == raw)
try:
    compile(src, GEN, "exec")
    compiled = True
except SyntaxError as ex:
    compiled = str(ex)
check("patched generator compiles", compiled is True, "" if compiled is True else compiled)
check("old row call gone, new one present once",
      _d["_CALL"] not in src and src.count(_d["_NEW_CALL"]) == 1)

# Pull just the pure functions + constants they need out of the PATCHED source.
tree = ast.parse(src)
FUNCS = {"generate_courses", "_origin_door_head_courses", "cut_sheet_single_opening", "rect_intersection"}
CONSTS = {"IN_FT", "PANEL_HEIGHT_FT", "MIN_PIECE_HEIGHT_FT", "MIN_PIECE_WIDTH_FT",
          "OPENING_CLEARANCE_FT", "DRYWALL_OPENING_REVEAL_FT",
          "_ORIGIN_HEAD_JOINT_CLEAR_FT", "_ORIGIN_ALT_COURSE_HEIGHTS_FT", "_ORIGIN_DOOR_HEAD_ROWS"}
g = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in CONSTS:
        exec(compile(ast.Module([node], []), GEN, "exec"), g)
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        exec(compile(ast.Module([node], []), GEN, "exec"), g)

CL = g["OPENING_CLEARANCE_FT"]
RV = g["DRYWALL_OPENING_REVEAL_FT"]
TRIM = 0.25


def door(height_ft, width_ft=3.0, x=4.0):
    """(framing rect, drywall cut) the generator would build for a door with 3 in trim."""
    x0, x1, top = x, x + width_ft + 2 * TRIM, height_ft + TRIM
    return (x0 - CL, 0.0, x1 + CL, top + CL), (x0 - RV, 0.0, x1 + RV, top + RV)


def rows(face_h, rects, li=0):
    return [(round(a, 3), round(b, 3)) for (a, b, r) in
            g["_origin_door_head_courses"](face_h, li * 2.0, rects, li, 1, "FACE_A_INTERIOR")]


def pieces(face_h, rect, cut):
    out = []
    for (a, b) in rows(face_h, [rect]):
        out.append((a, b, [s[0] for s in g["cut_sheet_single_opening"]((0.0, a, 16.0, b), cut)]))
    return out


print("8'-0\" door, 10 ft wall")
r8, c8 = door(8.0)
got = rows(10.0, [r8])
check("rows are 0-4, 4-6, 6-10", got == [(0.0, 4.0), (4.0, 6.0), (6.0, 10.0)], str(got))
p = pieces(10.0, r8, c8)
check("rows below the head split either side of the door, top row is ONE notched board",
      [x[2] for x in p] == [["rect", "rect"], ["rect", "rect"], ["poly"]], str(p))
check("head sits >= 1.5 ft inside the top sheet", c8[3] - 6.0 >= 1.5, "head {:.2f}".format(c8[3]))

print("7'-0\" door, 10 ft wall (current layout is correct - must not change)")
r7, c7 = door(7.0)
got = rows(10.0, [r7])
check("rows stay 0-4, 4-8, 8-10", got == [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)], str(got))
check("head is ~0.7 ft clear of the 8 ft joint", 8.0 - r7[3] > 0.5, "head {:.2f}".format(r7[3]))

print("8'-0\" door under a 9 ft ceiling")
got = rows(9.0, [r8])
check("rows are 0-4, 4-6, 6-9", got == [(0.0, 4.0), (4.0, 6.0), (6.0, 9.0)], str(got))

print("things that must be left alone")
check("no openings -> default", rows(10.0, []) == [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)])
win = (4.0, 3.0, 7.0, 8.2)
check("a window whose top is near 8 ft -> default (doors only)",
      rows(10.0, [win]) == [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)])
check("second layer of a rated wall keeps its own stagger",
      rows(10.0, [r8], li=1) == [(0.0, 2.0), (2.0, 6.0), (6.0, 10.0)], str(rows(10.0, [r8], li=1)))
check("7 ft and 8 ft doors on one wall -> 4 + 2 + 4 (both heads clear of 4 and 6)",
      rows(10.0, [r7, door(8.0, x=10.0)[0]]) == [(0.0, 4.0), (4.0, 6.0), (6.0, 10.0)])
check("re-laid faces are recorded for the report", len(g["_ORIGIN_DOOR_HEAD_ROWS"]) >= 1)

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
