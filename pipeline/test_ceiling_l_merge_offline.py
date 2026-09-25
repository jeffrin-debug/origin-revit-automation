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

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
