# Offline test of wall_split_first.py (2026-09-29).
#
# C9 wall 037 face A, 0-48in course: the generator tiled 3-96 + 96-125.5in across the face and then
# split at wall 034's tee (31.5in), giving 31.5-96 + 96-125.5 where one 94in sheet fits. The
# course layout is lifted from the generator with every stage-2 wall patch applied, and run the
# way emit_drywall() runs it: cells, then the loop's own split of each cell. No Revit.

import ast
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_p = {"__name__": "origin_paths", "__file__": os.path.join(HERE, "origin_paths.py")}
exec(compile(open(_p["__file__"]).read(), _p["__file__"], "exec"), _p)
GEN = os.path.join(_p["DRYWALL_REPO"], "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")
raw = open(GEN, encoding="utf-8").read()
IN = 1.0 / 12.0
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
for mod in ("infill_z_fix", "wall_ceiling_profile", "corner_lap", "corner_end_studs", "wall_split_first",
            "door_head_courses", "wall_end_joints"):
    src, info = load(mod)["apply_to_source"](src)
    check(info.get("applied"), "{} applies".format(mod), info)
compile(src, GEN, "exec")
check(True, "patched generator compiles (all wall patches together)")
check(open(GEN, encoding="utf-8").read() == raw, "generator file on disk untouched")


def lift(source, funcs):
    g = {}
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
                "IN_FT", "PANEL_LENGTH_FT", "STUD_SPACING_FT", "JOINT_CLEAR_FT", "MIN_SAFE_SEGMENT_FT",
                "_ORIGIN_COURSE_SPLITS", "_ORIGIN_WALL_MIN_END_FT", "_ORIGIN_WALL_END_JOINTS"):
            exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), g)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in funcs:
            exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), g)
    return g


FUNCS = {"course_cells_on_studs", "_origin_cells_one_span", "_origin_is_course_split",
         "_origin_wall_end_cells", "split_interval", "merge_small_segments", "unique_sorted"}
new = lift(src, FUNCS)
old = lift(raw, FUNCS)


def boards(g, flo, fhi, shift, studs, splits, patched):
    """cells as emit_drywall builds them, then each cell split at the course's splits."""
    if patched:
        g["_ORIGIN_COURSE_SPLITS"][:] = splits
    cells, _ = g["course_cells_on_studs"](flo, fhi, shift, studs)
    if patched:
        cells = g["_origin_wall_end_cells"](cells, flo, fhi, studs, [], "W", "interior", 0.0, 4.0)
    out = []
    for (a, b) in cells:
        out.extend(g["merge_small_segments"](g["split_interval"](a, b, splits), g["MIN_SAFE_SEGMENT_FT"]))
    return [(round(a * 12, 2), round(b * 12, 2)) for (a, b) in out]


# wall 037: run 0-119.5in, studs 16in OC from 0 + end stud + the tee's stud line
studs = sorted(set([i * 16 * IN for i in range(8)] + [119.5 * IN, 31.5 * IN]))
flo, fhi = 3.0 * IN, 125.5 * IN

print("C9 wall 037 face A, 0-48in course")
b_old = boards(old, flo, fhi, 0.0, studs, [31.5 * IN], False)
check(b_old == [(3.0, 31.5), (31.5, 96.0), (96.0, 125.5)], "generator as-is: three boards (the defect)", b_old)
b_new = boards(new, flo, fhi, 0.0, studs, [31.5 * IN], True)
check(b_new == [(3.0, 31.5), (31.5, 125.5)], "split first: 3-31.5 + one 94in board", b_new)

print("\na span longer than one sheet still gets joints on studs, <= 8 ft each")
st = [i * 16 * IN for i in range(20)]
b = boards(new, 0.0, 300 * IN, 0.0, st, [40 * IN], True)
check(all(y - x <= 96.0 + 1e-6 for (x, y) in b), "no board over 8 ft", b)
check(all(any(abs(x - s * 12) < 1e-3 for s in st + [40 * IN]) for (x, _y) in b[1:]),
      "every joint on a stud line (or the tee)", b)
check(any(abs(x - 40.0) < 1e-3 for (x, _y) in b), "the tee still ends a board", b)

print("\nno splits -> exactly the generator's layout")
random.seed(7)
same = True
for _ in range(300):
    lo = random.uniform(-1, 2)
    hi = lo + random.uniform(0.5, 40)
    stx = sorted(set([lo + i * 16 * IN for i in range(int((hi - lo) / (16 * IN)) + 2)]))
    sh = random.choice([0.0, 16 * IN, 32 * IN, 4.0])
    new["_ORIGIN_COURSE_SPLITS"][:] = []
    if new["course_cells_on_studs"](lo, hi, sh, stx) != old["course_cells_on_studs"](lo, hi, sh, stx):
        same = False
        break
check(same, "300 random courses identical with no splits")

print("\nwall_end_joints never moves a split")
# a 10in piece between a tee and the face end: bounded by the tee, nothing to move
new["_ORIGIN_COURSE_SPLITS"][:] = [110 * IN]
cells, _ = new["course_cells_on_studs"](0.0, 120 * IN, 0.0, [i * 16 * IN for i in range(8)] + [110 * IN])
fixed = new["_origin_wall_end_cells"](cells, 0.0, 120 * IN, [i * 16 * IN for i in range(8)] + [110 * IN],
                                      [], "W", "interior", 0.0, 4.0)
check(any(abs(a - 110 * IN) < 1e-6 for (a, _b) in fixed), "the tee at 110in stays a board edge",
      [(round(a * 12, 2), round(b * 12, 2)) for (a, b) in fixed])

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
