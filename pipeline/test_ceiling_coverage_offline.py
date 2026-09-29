# Offline test of ceiling_coverage_check.py's scan (2026-09-28). No Revit.
#
# The two ceiling gaps found by eye today must both be caught, the fixed layouts must pass, and
# the places a ceiling is bare by design (walls, columns, holes) must never be reported.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ns = {"__name__": "ceiling_coverage_check", "__file__": os.path.join(HERE, "ceiling_coverage_check.py")}
exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
scan, patches = ns["scan"], ns["patches"]

F = 1.0 / 12.0
GRID, PAD = 1.0 * F, 0.12 * F
fails = []


def check(cond, label, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label,
                              ("  [" + str(extra) + "]") if extra and not cond else ""))


def rect(x0, y0, x1, y1):
    return [(x0 * F, y0 * F), (x1 * F, y0 * F), (x1 * F, y1 * F), (x0 * F, y1 * F)]


def board(x0, y0, x1, y1):
    return ((x0 * F, y0 * F, x1 * F, y1 * F), [rect(x0, y0, x1, y1)])


def run(outline, boards, obstacles=(), bbox=None):
    xs = [p[0] for lp in outline for p in lp]
    ys = [p[1] for lp in outline for p in lp]
    bbox = bbox or (min(xs), min(ys), max(xs), max(ys))
    obs = [(a * F, b * F, c * F, d * F) for (a, b, c, d) in obstacles]
    return patches(scan(outline, boards, obs, bbox, GRID, PAD))


print("2C ceiling C001 - 0.87in last course at wall 020")
c001 = [rect(-529.48, 188.016, -504.48, 332.886)]
before = [board(-529.48, 188.016, -504.48, 236.016), board(-529.48, 236.016, -504.48, 284.016),
          board(-529.48, 284.016, -504.48, 332.016)]
p = run(c001, before)
check(len(p) == 1, "the gap is found, as one patch", len(p))
ys = [q[1] * 12 for q in p[0]] if p else []
check(p and 332.016 <= min(ys) and max(ys) <= 332.886 and len(p[0]) == 25,
      "it is the 25 x 0.87in strip along the wall", (len(p[0]) if p else 0, min(ys) if ys else None))
after = before[:2] + [board(-529.48, 284.016, -504.48, 332.886)]
check(run(c001, after) == [], "the fixed layout passes")

print("\nC9 ceiling C394087 - 48 x 2.5in strip at the corner of walls 017 / 042")
c087 = [[(-586.77 * F, 324.83 * F), (-586.77 * F, 329.83 * F), (-470.77 * F, 329.83 * F),
         (-470.77 * F, 272.33 * F), (-442.77 * F, 272.33 * F), (-442.77 * F, 221.83 * F),
         (-586.77 * F, 221.83 * F), (-586.77 * F, 252.83 * F), (-589.77 * F, 252.83 * F),
         (-589.77 * F, 324.83 * F)]]
b087 = [board(-589.77, 221.83, -541.77, 269.83), board(-589.77, 269.83, -541.77, 329.83),
        board(-541.77, 221.83, -493.77, 301.83), board(-541.77, 301.83, -493.77, 329.83),
        board(-493.77, 221.83, -445.77, 269.83), board(-493.77, 272.33, -470.77, 329.83),
        board(-445.77, 221.83, -442.77, 272.33)]
p = run(c087, b087)
check(len(p) == 1, "the gap is found, as one patch", len(p))
xs = [q[0] * 12 for q in p[0]] if p else []
check(p and -493.77 <= min(xs) and max(xs) <= -445.77 and len(p[0]) in (96, 144),
      "it is the 48in strip between the sheet edge and the notch", len(p[0]) if p else 0)
fixed = b087[:4] + [board(-493.77, 221.83, -445.77, 269.83), board(-493.77, 269.83, -470.77, 329.83),
                    board(-470.77, 269.83, -445.77, 272.33), b087[6]]
check(run(c087, fixed) == [], "the fixed layout passes")

print("\nbare by design is never a gap")
room = [rect(0, 0, 96, 48)]
cut_col = [board(0, 0, 40, 48), board(52, 0, 96, 48), board(40, 0, 52, 20), board(40, 32, 52, 48)]
check(run(room, cut_col, obstacles=[(40, 20, 52, 32)]) == [],
      "boards cut around a column footprint: the hole is not reported")
check(len(run(room, cut_col)) == 1, "...but the same hole with no column there IS reported")
check(run(room, [board(0, 0, 96, 48)]) == [], "a fully boarded ceiling passes")
holed = [rect(0, 0, 96, 48), rect(40, 20, 52, 32)]     # a ceiling with its own opening
check(run(holed, cut_col) == [], "an opening in the ceiling itself is not reported")

print("\npatches are grouped")
two = run(room, [board(0, 0, 30, 48), board(34, 0, 60, 48), board(64, 0, 96, 48)])
check(len(two) == 2 and all(len(p) == 4 * 48 for p in two), "two separate 4in strips -> two patches",
      [len(p) for p in two])

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
