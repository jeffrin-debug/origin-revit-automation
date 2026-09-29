# Offline test of the column stud wrap (origin_column_assembly_v1.py, 2026-09-28).
#
# plan_column() touches no Revit API - it works on plain boxes - so the whole layout can be
# checked outside Revit: the generator file is exec'd with ORIGIN_COLUMN_OFFLINE set and the
# Revit imports stubbed. Geometry is C9's real columns and walls (read live 2026-09-28), plus a
# wall running straight through a column and a free-standing column.

import os
import sys
import types

for name in ("clr", "Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB",
             "RevitServices", "RevitServices.Persistence", "RevitServices.Transactions"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["clr"].AddReference = lambda *a: None
sys.modules["RevitServices.Persistence"].DocumentManager = None
sys.modules["RevitServices.Transactions"].TransactionManager = None

GEN = os.path.join(os.path.expanduser("~"), "Downloads", "origin_revit_drywall_scripts_v2_two_faces",
                   "origin_column_assembly_v1.py")
g = {"__name__": "origin_column_assembly_v1", "ORIGIN_COLUMN_OFFLINE": True}
exec(compile(open(GEN, encoding="utf-8").read(), GEN, "exec"), g)

plan_column = g["plan_column"]
overlap = g["box_overlap_volume"]
S, T, t = g["WRAP_FRAME_FT"], g["WRAP_T_FT"], g["DRYWALL_T_FT"]
F = 1.0 / 12.0
EPS = 1e-6

fails = []


def check(cond, label, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label,
                              ("  [" + str(extra) + "]") if extra and not cond else ""))


def box_in(x0, x1, y0, y1, z0=0.0, z1=120.0):
    return (x0 * F, y0 * F, z0 * F, x1 * F, y1 * F, z1 * F)


# ---- C9, live 2026-09-28 (inches) ---------------------------------------------------------------
WALLS = {
    "W377257": box_in(-589.77, -438.77, 217.83, 221.83),
    "W391497": box_in(-592.77, -586.77, 231.33, 252.83),
    "W403602": box_in(-592.77, -586.77, 200.58, 231.33),
    "W404937": box_in(-606.77, -586.77, 194.58, 200.58),
    "W377840": box_in(-603.77, -580.77, 72.33, 78.33),
    "W391329": box_in(-606.77, -600.77, 84.33, 111.33),
    "W402100": box_in(-580.77, -558.77, 72.33, 78.33),
    "W402215": box_in(-606.77, -600.77, 72.33, 84.33),
    "W401103": box_in(-287.27, -164.77, 79.58, 85.58),
    "W401948": box_in(-290.27, -284.27, 78.33, 85.58),
}
COLS = {
    "K388930": box_in(-586.77, -580.77, 221.83, 231.33),
    "K389316": box_in(-586.77, -580.77, 194.58, 217.83),
    "K390611": box_in(-600.77, -580.77, 78.33, 84.33),
    "K390751": box_in(-290.27, -266.27, 85.58, 97.58),
}
CEIL_96 = lambda f, a, b: 96.0 * F


def obstacles_for(cid, walls=WALLS, cols=COLS):
    obs = [{"id": k, "box": v} for k, v in walls.items()]
    obs += [{"id": k, "box": v} for k, v in cols.items() if k != cid]
    return obs


def run(cid, walls=WALLS, cols=COLS, cap=CEIL_96):
    b = cols[cid]
    return plan_column((b[0], b[1], b[3], b[4]), b[2], b[5], obstacles_for(cid, walls, cols), cap)


def exposed_faces(plan):
    return sorted(f for f in "NESW" if plan["faces"][f]["exposed"])


def common_checks(label, cid, plan, walls=WALLS, cols=COLS):
    col = cols[cid]
    pcs = plan["pieces"]
    # nothing of the wrap enters the column, a wall, or another column
    bad = [(p["kind"], p["face"]) for p in pcs if overlap(p["box"], col) > EPS]
    check(not bad, "{}: no wrap piece enters the column itself".format(label), bad[:3])
    hits = []
    for p in pcs:
        for k, wb in list(walls.items()) + [(k, v) for k, v in cols.items() if k != cid]:
            if overlap(p["box"], wb) > EPS:
                hits.append((p["kind"], p["face"], k))
    check(not hits, "{}: no wrap piece enters any wall or other column".format(label), hits[:3])
    # the wrap's own pieces do not overlap each other (a stud sits inside its track's U, and a
    # C/U profile's BOX is not its solid, so stud-vs-track is the one pair allowed to share a box)
    boards = [p for p in pcs if p["kind"] == "GWB"]
    frame = [p for p in pcs if p["kind"] != "GWB"]
    bb = [(i, j) for i in range(len(boards)) for j in range(i + 1, len(boards))
          if overlap(boards[i]["box"], boards[j]["box"]) > EPS]
    check(not bb, "{}: boards do not overlap each other".format(label), bb[:3])
    bf = [(b["face"], f["kind"], f["face"]) for b in boards for f in frame
          if overlap(b["box"], f["box"]) > EPS]
    check(not bf, "{}: boards do not overlap framing".format(label), bf[:3])
    ss = [(i, j) for i in range(len(frame)) for j in range(i + 1, len(frame))
          if frame[i]["kind"] == frame[j]["kind"] and overlap(frame[i]["box"], frame[j]["box"]) > EPS]
    check(not ss, "{}: studs do not overlap studs, tracks not tracks".format(label), ss[:3])
    # wall-sized pieces: boards <= 8 ft x 4 ft, 1/2" thick; studs <= 16" OC
    big = []
    for p in boards:
        b = p["box"]
        dims = sorted([b[3] - b[0], b[4] - b[1]])
        if abs(dims[0] - t) > 1e-6 and not p.get("end_cap"):
            big.append(("thickness", dims[0] * 12))
        if dims[1] > 8.0 + 1e-6 or (b[5] - b[2]) > 4.0 + 1e-6:
            big.append(("size", dims[1], b[5] - b[2]))
    check(not big, "{}: every board is 1/2in and within one 4x8 sheet".format(label), big[:3])
    gaps = []
    for f in "NESW":
        xs = sorted(p["along"] for p in pcs if p["kind"] == "STUD" and p["face"] == f)
        for a, b in zip(xs, xs[1:]):
            if b - a > 16.0 * F + 1e-6:
                gaps.append((f, round((b - a) * 12, 2)))
    check(not gaps, "{}: studs at 16in OC or closer".format(label), gaps)


print("C9 K390751 - the column the user selected (24x12, back against wall 401103)")
p = run("K390751")
check(exposed_faces(p) == ["E", "N", "W"], "front + two sides wrapped, back left alone",
      exposed_faces(p))
check(p["faces"]["S"]["covered_by"] == ["W401103", "W401948"], "back covered by walls 401103 + 401948",
      p["faces"]["S"]["covered_by"])
w_run, e_run = p["faces"]["W"]["runs"][0], p["faces"]["E"]["runs"][0]
check(w_run["end_caps"][0] is not None,
      "west wrap gets a return board where it ends past wall 401948's face", w_run["end_caps"])
check(e_run["end_caps"][0] is None, "east wrap needs none - wall 401103 runs on past it", e_run["end_caps"])
check(all(abs(r["z_top"] - 8.0) < 1e-9 for f in "NEW" for r in p["faces"][f]["runs"]),
      "wrap stops at the 8 ft ceiling underside")
x0, y0, x1, y1 = -290.27 * F, 85.58 * F, -266.27 * F, 97.58 * F
nb = [q["box"] for q in p["pieces"] if q["kind"] == "GWB" and q["face"] == "N"]
eb = [q["box"] for q in p["pieces"] if q["kind"] == "GWB" and q["face"] == "E"]
check(abs(min(b[0] for b in nb) - (x0 - S)) < 1e-9 and abs(max(b[3] for b in nb) - (x1 + S)) < 1e-9,
      "north board butts between the east/west boards")
check(abs(max(b[4] for b in eb) - (y1 + T)) < 1e-9, "east board wraps the NE corner over the north board's edge")
courses = sorted(set((round(b[2] * 12, 2), round(b[5] * 12, 2)) for b in nb))
check(courses == [(0.0, 48.0), (48.0, 96.0)], "two 4 ft courses up to the ceiling", courses)
check(any(overlap(c, (x0, y0, 0, x1, y1, 10)) > 0 for c in p["cutters"]),
      "wall cutters include the column footprint")
check(all(overlap(c, WALLS["W401103"]) <= EPS for c in p["cutters"] if c != (x0, y0, 0.0, x1, y1, 10.0)),
      "wrap cutters leave wall 401103's board behind the column alone")
wrapcut = [c for c in p["cutters"] if c != (x0, y0, 0.0, x1, y1, 10.0)]
check(all(abs(c[5] - 10.0) < 1e-9 for c in wrapcut),
      "wrap cutters run past the ceiling to the column top, so the ceiling board is cut to the wrap")
common_checks("K390751", "K390751", p)

print("\nC9 K390611 - corner column")
p = run("K390611")
check(exposed_faces(p) == ["E", "N"], "only the two room faces wrapped", exposed_faces(p))
common_checks("K390611", "K390611", p)

print("\nC9 K388930 / K389316 - pilasters on wall 403602, either side of wall 377257")
for cid in ("K388930", "K389316"):
    p = run(cid)
    check(exposed_faces(p) == (["E", "N"] if cid == "K388930" else ["E", "S"]),
          "{}: its two room faces wrapped".format(cid), exposed_faces(p))
    common_checks(cid, cid, p)

print("\nWall running straight through a 24x24 column")
walls = {"W1": box_in(-200, 200, -3, 3)}
cols = {"K1": box_in(-12, 12, -12, 12)}
p = run("K1", walls, cols, cap=None)
check(exposed_faces(p) == ["E", "N", "S", "W"], "all four faces have room-side stretches", exposed_faces(p))
check(len(p["faces"]["E"]["exposed"]) == 2 and len(p["faces"]["W"]["exposed"]) == 2,
      "east / west faces split either side of the wall")
caps = [c for f in "EW" for r in p["faces"][f]["runs"] for c in r["end_caps"] if c is not None]
check(not caps, "no return boards where the wrap meets the wall - the wall hides the end", caps)
wall = walls["W1"]
inside = [c for c in p["cutters"] if overlap(c, wall) > EPS]
check(inside, "cutters reach into the wall where it passes through the column")
check(all(abs(c[1]) <= 12 * F + T + 1e-9 and abs(c[4]) <= 12 * F + T + 1e-9 for c in p["cutters"]),
      "cutters stay within the column + its wrap")
common_checks("through-wall", "K1", p, walls, cols)

print("\nFree-standing 24x24 column, no ceiling")
p = run("K1", {}, cols, cap=None)
check(exposed_faces(p) == ["E", "N", "S", "W"], "all four faces wrapped")
bx = [q["box"] for q in p["pieces"] if q["kind"] == "GWB"]
env = (min(b[0] for b in bx), min(b[1] for b in bx), max(b[3] for b in bx), max(b[4] for b in bx))
want = (-12 * F - T, -12 * F - T, 12 * F + T, 12 * F + T)
check(all(abs(a - b) < 1e-9 for a, b in zip(env, want)), "board skin closes to the column + 4-1/8in each side")
check(abs(sum((b[3] - b[0]) * (b[4] - b[1]) * (b[5] - b[2]) for b in bx)
          - 10.0 * ((want[2] - want[0]) * (want[3] - want[1]) - (24 * F + 2 * S) ** 2)) < 1e-6,
      "board skin has no gaps or double layers (volume = outer shell minus inner)")
tops = sorted(set(round(b[5] * 12, 2) for b in bx))
check(tops == [48.0, 96.0, 120.0], "courses 4 + 4 + 2 ft to the column top", tops)
common_checks("free-standing", "K1", p, {}, cols)

print("\nWall boards stop where the column's panels meet them (B5 K002, live 2026-09-28)")
applies = g["board_cut_applies"]
B5W = {"W017": box_in(-715.65, -431.15, 160.37, 166.37),
       "W016": box_in(-715.65, -709.65, 163.37, 186.37),
       "W015": box_in(-715.65, -709.65, 186.37, 416.87)}
B5C = {"K381288": box_in(-709.65, -697.65, 166.37, 186.37)}
p = run("K381288", B5W, B5C)
check(exposed_faces(p) == ["E", "N"], "K002 wrapped on its two room faces", exposed_faces(p))
bcs = p["board_cutters"]
check(sorted(b["face"] for b in bcs) == ["S", "W"], "board cut zones on the two faces walls cover",
      [b["face"] for b in bcs])


def after_cut(board):
    """Along-axis stretches of a board left once every applicable cut zone is taken out (the zones
    span the board's full thickness and height, so the cut is an interval subtraction)."""
    ax = 0 if (board[3] - board[0]) > (board[4] - board[1]) else 1
    segs = [(board[ax], board[ax + 3])]
    for bc in bcs:
        if not applies(board, bc):
            continue
        c0, c1 = bc["box"][ax], bc["box"][ax + 3]
        segs = g["subtract_intervals"](segs[0][0], segs[0][1], [(c0, c1)]) if segs else []
    return [(round(a * 12, 2), round(b * 12, 2)) for (a, b) in segs]


b017 = box_in(-710.15, -632.65, 165.87, 166.37, 0, 48)       # DP-017-001B, the selected board
b016 = box_in(-710.15, -709.65, 166.37, 185.74, 0, 48)       # DP-016-001B, wholly behind K002
b015 = box_in(-710.15, -709.65, 185.74, 272.87, 0, 48)       # DP-015-004B, runs on past it
b016a = box_in(-715.65, -715.15, 160.87, 185.74, 0, 48)      # DP-016-001A, far face of wall 016
e_wrap_out = round((-697.65 * F + T) * 12, 2)
n_wrap_out = round((186.37 * F + T) * 12, 2)
check(after_cut(b017) == [(e_wrap_out, -632.65)],
      "DP-017-001B now starts flush with the east wrap's outer face", after_cut(b017))
check(after_cut(b016) == [], "DP-016-001B (wholly behind the column) goes", after_cut(b016))
check(after_cut(b015) == [(n_wrap_out, 272.87)],
      "DP-015-004B now starts flush with the north wrap's outer face", after_cut(b015))
check(after_cut(b016a) == [(160.87, 185.74)], "wall 016's far-side board is untouched", after_cut(b016a))
stud = box_in(-697.6, -696.35, 160.87, 165.87, 0, 120)
check(not any(applies(stud, bc) for bc in bcs),
      "wall 017's studs behind the column are never board-cut (only flat DRYWALL pieces are)")

print("\nA wall meeting a column END-ON keeps its boards (C9 K390751 / wall 401948)")
p = run("K390751")
end_on = box_in(-290.27, -289.77, 78.33, 85.58, 0, 48)        # 401948's face board, ends at the column
check(not any(applies(end_on, bc) for bc in p["board_cutters"]),
      "its board ends at the column face and is not cut")
behind = box_in(-287.27, -260.77, 85.08, 85.58, 0, 48)        # DP-037-003A, behind the column
check(any(applies(behind, bc) for bc in p["board_cutters"]),
      "the board flat behind the column IS cut (the new rule)")

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
