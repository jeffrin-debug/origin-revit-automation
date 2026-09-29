# Offline test of ceiling_l_merge.candidates() on 1F's own C007 boards. No Revit.
#
#   python test_ceiling_l_merge_offline.py

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ns = {"__name__": "ceiling_l_merge", "__file__": os.path.join(HERE, "ceiling_l_merge.py")}
exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
candidates = ns["candidates"]

IN = 1.0 / 12.0


def board(mark, x0, y0, x1, y1):
    return {"mark": mark, "layer": "L0", "box": (x0 * IN, y0 * IN, x1 * IN, y1 * IN, 96 * IN, 96.5 * IN)}


def wall(x0, y0, x1, y1):
    return (x0 * IN, y0 * IN, x1 * IN, y1 * IN)


# C007 around the soffit corner, exactly as generated (inches)
B = [board("DP-C007-004", -446.47, 244.70, -384.71, 292.70),
     board("DP-C007-005", -446.47, 292.70, -398.47, 340.70),
     board("DP-C007-006", -398.47, 307.44, -343.97, 340.70),
     board("DP-C007-007", -398.47, 292.70, -384.71, 307.44),
     board("DP-C007-008", -446.47, 340.70, -350.47, 388.70),
     board("DP-C007-009", -350.47, 340.70, -343.97, 388.70)]
W006 = wall(-384.71, 220.70, -379.97, 307.44)      # soffit walls - both reach the 8 ft ceiling
W007 = wall(-382.34, 302.70, -339.22, 307.44)

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


pairs = [(B[i]["mark"], B[j]["mark"]) for (i, j, e) in candidates(B, [W006, W007])]
print("1F C007")
check("DP-C007-006 + DP-C007-007 merge (the needless seam at y=307.44)",
      ("DP-C007-006", "DP-C007-007") in pairs, str(pairs))
check("...and it is the ONLY pair", len(pairs) == 1, str(pairs))
check("007 is not folded into 005 across the butt joint at x=-398.47 (stepped joint)",
      ("DP-C007-005", "DP-C007-007") not in pairs)
check("005 + 006 not merged: 102.5in long, over one 8 ft sheet",
      ("DP-C007-005", "DP-C007-006") not in pairs)
check("006 + 009 not merged: 54.5 x 81in, both sides over 4 ft",
      ("DP-C007-006", "DP-C007-009") not in pairs)

print("a wall on the seam keeps the split")
across = wall(-400.0, 306.0, -390.0, 309.0)        # a wall running over part of the seam
pairs = [(B[i]["mark"], B[j]["mark"]) for (i, j, e) in candidates(B, [W006, W007, across])]
check("wall crossing the shared edge -> no merge", ("DP-C007-006", "DP-C007-007") not in pairs, str(pairs))

print("partial touch is not one sheet")
P = [board("A", 0, 0, 48, 48), board("B", 48, 30, 70, 60)]    # B's edge only half on A
check("boards touching along only part of the smaller edge -> no merge", not candidates(P, []))

print("plain rectangle split still merges")
R = [board("A", 0, 0, 40, 48), board("B", 40, 0, 90, 48)]
check("two halves of one 4x8 cell", len(candidates(R, [])) == 1)

print("C9 C394105 - a board that only STOPS at a wall on the seam line is no joint (2026-09-28)")
C9 = [board("DP-C009-018", -360.77, 78.34, -312.77, 155.33),
      board("DP-C009-019", -312.77, 85.58, -264.77, 126.34),
      board("DP-C009-020", -312.77, 78.34, -290.27, 85.58),
      board("DP-C009-021", -312.77, 126.34, -264.77, 155.33),
      board("DP-C009-023", -264.77, 85.58, -216.77, 155.33),
      board("DP-C009-025", -216.77, 85.58, -198.28, 126.34),
      board("DP-C009-026", -216.77, 126.34, -198.28, 184.33)]
W401103 = wall(-287.27, 79.58, -164.77, 85.58)     # 023 / 025 stop on its face, y = 85.58
W401948 = wall(-290.27, 78.33, -284.27, 85.58)     # ends at y = 85.58 - why the cell was cut there
pairs = [(C9[i]["mark"], C9[j]["mark"]) for (i, j, e) in candidates(C9, [W401103, W401948])]
check("DP-C009-019 + DP-C009-020 merge (48 x 48in, one sheet)",
      ("DP-C009-019", "DP-C009-020") in pairs, str(pairs))
check("...and otherwise only the plain 019 + 021 rectangle join it already made",
      sorted(pairs) == [("DP-C009-019", "DP-C009-020"), ("DP-C009-019", "DP-C009-021")], str(pairs))

print("a real butt joint on the seam line still blocks")
J = [board("A", 0, 10, 48, 48), board("B", 0, 0, 22, 10),       # A + B would be an L
     board("C", 48, 10, 96, 48), board("D", 48, 0, 96, 10)]     # C and D butt each other on y=10
pairs = [(J[i]["mark"], J[j]["mark"]) for (i, j, e) in candidates(J, [])]
check("A + B not merged: C / D butt on the same line", ("A", "B") not in pairs, str(pairs))

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
