# Offline test of absorb_thin_pieces() in the ceiling generator (2026-09-28).
#
# C9 ceiling 394087: the corner of walls 017/042 sat 2.5in past a sheet edge, the cell was cut at
# the wall's end line into a 48in x 2.5in strip, the part beyond was cut again at the wall face,
# merge_small_pieces() found no same-width neighbour, and the emit loop's 3in floor dropped the
# strip - a gap under the furring. The two helpers are pure Python, so they are lifted straight
# out of the generator file and run here on the real piece coordinates.

import ast
import os
import sys

GEN = os.path.join(os.path.expanduser("~"), "Downloads", "origin_revit_drywall_scripts_v2_two_faces",
                   "origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py")
src = open(GEN, encoding="utf-8").read()
tree = ast.parse(src)
ns = {}
for node in tree.body:
    if (isinstance(node, ast.FunctionDef) and node.name in ("merge_small_pieces", "absorb_thin_pieces",
                                                             "course_bands")) or             (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "END_COURSE_MIN_FT"):
        exec(compile(ast.Module(body=[node], type_ignores=[]), GEN, "exec"), ns)
merge, absorb = ns["merge_small_pieces"], ns["absorb_thin_pieces"]

F = 1.0 / 12.0
MIN = 0.25          # MIN_PIECE_WIDTH_FT / MIN_PIECE_HEIGHT_FT
fails = []


def check(cond, label, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label,
                              ("  [" + str(extra) + "]") if extra and not cond else ""))


def r(x0, y0, x1, y1):
    return (x0 * F, y0 * F, x1 * F, y1 * F)


def area(ps):
    return sum((p[2] - p[0]) * (p[3] - p[1]) for p in ps)


def inch(ps):
    return sorted(tuple(round(v * 12, 2) for v in p) for p in ps)


print("C9 ceiling 394087, course x -493.77..-445.77, cell y 269.83..329.83")
strip = r(-493.77, 269.83, -445.77, 272.33)
left = r(-493.77, 272.33, -470.77, 329.83)       # became DP-C008-007
notch = r(-470.77, 272.33, -445.77, 329.83)      # outside the ceiling - clipped away
pieces = merge([strip, left, notch], 0.5)
check(strip in pieces, "merge_small_pieces alone keeps the strip (the bug's precondition)")
dropped = [p for p in pieces if (p[2] - p[0]) < MIN or (p[3] - p[1]) < MIN]
check(dropped == [strip], "...which the emit loop's 3in floor would drop", inch(dropped))

out = absorb(pieces, MIN, MIN)
check(not [p for p in out if (p[2] - p[0]) < MIN or (p[3] - p[1]) < MIN],
      "after absorb: no piece left under 3in", inch(out))
check(abs(area(out) - area([strip, left, notch])) < 1e-9, "no area lost or doubled")
check(inch(out) == [(-493.77, 269.83, -470.77, 329.83), (-470.77, 269.83, -445.77, 329.83)],
      "both pieces above now start at the sheet edge 269.83", inch(out))
check(all((p[3] - p[1]) <= 8.0 + 1e-9 and (p[2] - p[0]) <= 4.0 + 1e-9 for p in out),
      "each still fits one 4x8 sheet")

print("\nPieces with nothing thin are left exactly as they were")
plain = [r(0, 0, 48, 48), r(0, 48, 48, 96)]
check(absorb(plain, MIN, MIN) == plain, "untouched")

print("\nA thin strip with nothing along its long edge is kept (never deleted here)")
lone = [r(0, 0, 48, 2)]
check(absorb(lone, MIN, MIN) == lone, "kept as it was")

print("\nA thin strip only partly covered keeps its uncovered remainder")
p2 = absorb([r(0, 0, 48, 2), r(0, 2, 20, 50)], MIN, MIN)
check(inch(p2) == [(0.0, 0.0, 20.0, 50.0), (20.0, 0.0, 48.0, 2.0)], "covered part absorbed, rest kept", inch(p2))

print("\nA thin strip in X (vertical) is absorbed sideways")
p3 = absorb([r(0, 0, 2, 48), r(2, 0, 50, 48)], MIN, MIN)
check(inch(p3) == [(0.0, 0.0, 50.0, 48.0)], "neighbour stretched left over it", inch(p3))

print("\n2C ceiling C001 - a last COURSE too thin to board (live 2026-09-28)")
bands = ns["course_bands"]
lo, hi = 188.016 * F, 332.886 * F                  # C001, courses step in Y (FURRING_RUN_NS=False)
old = [(round(a * 12, 3), round(b * 12, 3)) for (a, b, r) in bands(lo, hi, lo, 4.0, 0.0)]
check(old[-1] == (332.016, 332.886), "without the rule the last course is the 0.87in gap", old)
new = bands(lo, hi, lo, 4.0, MIN)
newi = [(round(a * 12, 3), round(b * 12, 3)) for (a, b, r) in new]
check(newi == [(188.016, 236.016), (236.016, 284.016), (284.016, 316.886), (316.886, 332.886)],
      "48 + 48 + 32.87 + 16in, nothing left to drop", newi)
check([r for (a, b, r) in new] == [1, 2, 3, 4], "row numbers (odd-row stagger) unchanged")
check(abs(new[0][0] - lo) < 1e-9 and abs(new[-1][1] - hi) < 1e-9 and
      all(abs(new[i][1] - new[i + 1][0]) < 1e-9 for i in range(len(new) - 1)),
      "courses still cover the ceiling end to end")
same = bands(0.0, 10.0, 0.0, 4.0, MIN)
check([(a, b) for (a, b, r) in same] == [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)],
      "a normal last course (2 ft) is left alone")
tiny = bands(0.0, 4.1, 0.0, 4.0, MIN)
check([(round(a * 12, 2), round(b * 12, 2)) for (a, b, r) in tiny] == [(0.0, 33.2), (33.2, 49.2)],
      "a 4ft + 1.2in ceiling becomes 33.2 + 16in")
narrow = bands(0.0, 1.0 + 1.0 / 12, 0.0, 1.0, MIN)
check([(round(a * 12, 2), round(b * 12, 2)) for (a, b, r) in narrow] == [(0.0, 12.0), (12.0, 13.0)],
      "left as it was when the course before would drop under 16in")

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
