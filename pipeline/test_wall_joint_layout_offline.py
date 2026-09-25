# Offline test of the corrected wall board layout.
#
# Reproduces the two ways the current generator puts joints off the studs, then shows the
# replacement holds in the same situations. Pure geometry - no Revit.
#
#   python test_wall_joint_layout_offline.py

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_ns = {"__name__": "wall_joint_layout", "__file__": os.path.join(HERE, "wall_joint_layout.py")}
exec(compile(open(_ns["__file__"], encoding="utf-8").read(), _ns["__file__"], "exec"), _ns)

course_cells_on_studs = _ns["course_cells_on_studs"]
verify_on_studs = _ns["verify_on_studs"]
joints_of = _ns["joints_of"]
quantise_shift = _ns["quantise_shift"]
nudge_candidates_in_bays = _ns["nudge_candidates_in_bays"]

IN = 1.0 / 12.0
STUD = 16.0 * IN
PANEL = 8.0

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    line = "  {}  {}".format("PASS" if cond else "FAIL", label)
    if extra:
        line += "\n          {}".format(extra)
    print(line)


def stud_lines(run_lo, run_hi, jambs=()):
    """The generator's own rule: 16 in OC from run_lo, an end stud at run_hi, one at each jamb."""
    xs = []
    x = run_lo
    while x <= run_hi + 0.001:
        xs.append(x)
        x += STUD
    if abs(xs[-1] - run_hi) > 0.1:
        xs.append(run_hi)
    for j in jambs:
        xs.append(j)
    return sorted(set(round(v, 9) for v in xs))


def old_layout(flo, fhi, row_shift):
    """What the generator does today: pure arithmetic, studs never consulted."""
    cells = []
    x = flo - row_shift
    while x < fhi - 1e-4:
        cells.append((max(flo, x), min(fhi, x + PANEL)))
        x += PANEL
    return cells


# ----------------------------------------------------------------------------------
print("CAUSE 1 - a course nudged off an opening jamb  (the middle-row symptom)")
# 24 ft wall, studs from 0, a door at 7..10 ft.
studs = stud_lines(0.0, 24.0, jambs=(7.0, 10.0))
# The generator's nudge list: only the last is a whole stud bay, and it is tried last.
for label, nudge_in in (("+6 in  (JOINT_CLEAR*1.5)", 6.0),
                        ("+12 in (JOINT_CLEAR*3.0)", 12.0),
                        ("+24 in (PANEL*0.25)", 24.0)):
    bad = verify_on_studs(old_layout(0.0, 24.0, nudge_in * IN), studs)
    check("OLD, nudged {:<26} -> {} joint(s) off-stud".format(label, len(bad)),
          len(bad) > 0, bad[0] if bad else "")
for label, nudge_in in (("+6 in", 6.0), ("+12 in", 12.0), ("+24 in", 24.0)):
    cells, info = course_cells_on_studs(0.0, 24.0, nudge_in * IN, studs)
    bad = verify_on_studs(cells, studs)
    check("NEW, same nudge {:<10} -> every joint on a stud".format(label), not bad,
          "" if not bad else str(bad))

print()
print("  and the nudge list itself is now whole bays:")
cands = nudge_candidates_in_bays()
allbays = all(abs((c / STUD) - round(c / STUD)) < 1e-9 for c in cands)
check("every nudge candidate is a whole stud bay", allbays,
      "{} in".format([round(c * 12, 1) for c in cands]))
check("quantise_shift snaps 24 in (mid-bay) to a bay boundary",
      abs(quantise_shift(24.0 * IN) * 12 - 32.0) < 1e-6,
      "24 in -> {} in".format(round(quantise_shift(24.0 * IN) * 12, 1)))

# ----------------------------------------------------------------------------------
print("\nCAUSE 2 - a face that wraps an outside corner  (the no-room-behind face)")
# Drywall wraps 0.5 in past the wall start; framing does not.
flo, fhi = -0.5 * IN, 24.0
studs = stud_lines(0.0, 24.0)
old = old_layout(flo, fhi, 0.0)
bad_old = verify_on_studs(old, studs)
check("OLD: every internal joint is off-stud on a wrapped face",
      len(bad_old) == len(joints_of(old)) and len(bad_old) > 0,
      "{} of {} joints off, each by {} in".format(
          len(bad_old), len(joints_of(old)), bad_old[0]["off_by_in"] if bad_old else "-"))
cells, info = course_cells_on_studs(flo, fhi, 0.0, studs)
check("NEW: all joints on studs despite the wrap", not verify_on_studs(cells, studs),
      "joints at {} ft".format([round(j, 3) for j in joints_of(cells)]))
check("NEW: the wrapped outer edge is preserved, not snapped away",
      abs(cells[0][0] - flo) < 1e-9 and abs(cells[-1][1] - fhi) < 1e-9)

# ----------------------------------------------------------------------------------
print("\nNO BOARD EVER EXCEEDS STOCK LENGTH")
import random
random.seed(11)
worst = 0.0
overs = 0
for _ in range(3000):
    lo = -random.uniform(0, 1.0) * IN * 12
    hi = lo + random.uniform(4.0, 60.0)
    rl = lo + random.uniform(-0.5, 0.5)
    st = stud_lines(rl, hi, jambs=tuple(sorted(random.sample(
        [round(lo + random.uniform(1, max(1.5, hi - lo - 1)), 3) for _ in range(4)], 2))))
    cells, info = course_cells_on_studs(lo, hi, random.choice([0, STUD, 2 * STUD, 4.0]), st)
    for (a, b) in cells:
        worst = max(worst, b - a)
        if b - a > PANEL + 1e-6:
            overs += 1
check("3000 random walls: no board over 8 ft", overs == 0,
      "longest board {:.4f} ft".format(worst))

# Coverage must be exact - no gaps, no overlaps.
gaps = 0
for _ in range(1000):
    lo = -random.uniform(0, 1.0) * IN * 12
    hi = lo + random.uniform(4.0, 40.0)
    st = stud_lines(lo + random.uniform(-0.5, 0.5), hi)
    cells, _i = course_cells_on_studs(lo, hi, random.choice([0, STUD, 2 * STUD]), st)
    if abs(cells[0][0] - lo) > 1e-9 or abs(cells[-1][1] - hi) > 1e-9:
        gaps += 1
    for i in range(len(cells) - 1):
        if abs(cells[i][1] - cells[i + 1][0]) > 1e-9:
            gaps += 1
check("1000 random walls: cells tile the face exactly, no gap or overlap", gaps == 0)

# ----------------------------------------------------------------------------------
print("\nSTAGGER STILL WORKS - joints must not stack row to row")
studs = stud_lines(0.0, 32.0)
r0 = joints_of(course_cells_on_studs(0.0, 32.0, 0.0, studs)[0])
r1 = joints_of(course_cells_on_studs(0.0, 32.0, 4.0, studs)[0])
check("adjacent courses do not share a joint position",
      not (set(round(v, 6) for v in r0) & set(round(v, 6) for v in r1)),
      "row0 {}  row1 {}".format([round(v, 2) for v in r0], [round(v, 2) for v in r1]))
check("both rows are still fully on studs",
      not verify_on_studs(course_cells_on_studs(0.0, 32.0, 0.0, studs)[0], studs)
      and not verify_on_studs(course_cells_on_studs(0.0, 32.0, 4.0, studs)[0], studs))

# ----------------------------------------------------------------------------------
print("\nDEGENERATE INPUT")
cells, info = course_cells_on_studs(0.0, 3.0, 0.0, stud_lines(0.0, 3.0))
check("a wall shorter than one board gives exactly one board", len(cells) == 1)
cells, info = course_cells_on_studs(0.0, 40.0, 0.0, [])
check("no studs at all: still boards the wall, and says so",
      len(cells) > 1 and info["off_stud_joints"] > 0,
      "{} joints, {} off-stud".format(info["joints"], info["off_stud_joints"]))

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
