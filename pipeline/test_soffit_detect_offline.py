# Offline test of soffit_detect.classify() - no Revit. Numbers are 1F's own (feet).
#
#   python test_soffit_detect_offline.py

import os
import sys
import types

for name in ("Autodesk", "Autodesk.Revit", "Autodesk.Revit.DB", "RevitServices",
             "RevitServices.Transactions", "System", "System.Collections", "System.Collections.Generic"):
    sys.modules.setdefault(name, types.ModuleType(name))
clr = types.ModuleType("clr")
clr.AddReference = lambda *a: None
sys.modules["clr"] = clr
sys.modules["RevitServices.Transactions"].TransactionManager = object
sys.modules["System.Collections.Generic"].List = object

HERE = os.path.dirname(os.path.abspath(__file__))
ns = {"__name__": "soffit_detect", "__file__": os.path.join(HERE, "soffit_detect.py")}
exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
classify = ns["classify"]

IN = 1.0 / 12.0


def wall(i, x, y, z, typ="Interior - 4 3/4\" Partition (1-hr) 2", inserts=0, straight=True):
    return {"id": i, "type": typ, "straight": straight, "inserts": inserts, "level_z": 0.0,
            "x": (x[0] * IN, x[1] * IN), "y": (y[0] * IN, y[1] * IN), "z": (z[0] * IN, z[1] * IN)}


def ceiling(i, x, y, bottom_in):
    return {"id": i, "bottom_z": bottom_in * IN, "x": (x[0] * IN, x[1] * IN), "y": (y[0] * IN, y[1] * IN)}


# 1F as it stands after the ceilings were lowered to 8 ft
W005 = wall(381037, (-384.71, -379.97), (196.20, 221.32), (0, 108))       # full height, collinear
W006 = wall(385838, (-384.71, -379.97), (220.70, 307.44), (84, 100.25))   # the soffit band
W007 = wall(385912, (-382.34, -339.22), (302.70, 307.44), (84, 100.25))   # the soffit band
W014 = wall(416757, (-343.97, -339.22), (306.94, 375.19), (0, 108))       # full height, 007 butts in
C001 = ceiling(384804, (-380.0, -303.2), (196.7, 302.7), 96.0)
C007 = ceiling(430824, (-446.5, -344.0), (196.7, 423.2), 96.0)

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


print("1F")
s, r = classify([W005, W006, W007, W014], [C001, C007])
ids = sorted(x["id"] for x in s)
check("walls 006 and 007 are recognised as soffits", ids == [385838, 385912], str(ids))
check("full-height walls 005 / 014 are not candidates at all", not r, str(r))
check("the ceiling that meets 006 is recorded",
      next(x for x in s if x["id"] == 385838)["ceiling_id"] in (384804, 430824))

print("near misses - look like a soffit but are not")
s, r = classify([wall(1, (0, 4.75), (0, 60), (84, 100.25), inserts=1)], [C007])
check("hosts a window -> rejected with reason", not s and "insert" in r[0]["why"], str(r))
s, r = classify([wall(2, (0, 4.75), (0, 60), (84, 100.25)),
                 wall(3, (0, 4.75), (0, 60), (0, 84))], [ceiling(9, (-20, 20), (-10, 80), 96.0)])
check("a wall stands under it (a header over a wall) -> rejected",
      not s and "stands under" in r[0]["why"], str(r))
s, r = classify([wall(4, (0, 4.75), (0, 60), (84, 100.25))], [ceiling(9, (100, 200), (0, 60), 96.0)])
check("no ceiling within reach -> rejected", not s and r[0]["why"] == "no ceiling meets it", str(r))
s, r = classify([wall(5, (0, 4.75), (0, 60), (84, 100.25))], [ceiling(9, (-20, 20), (-10, 80), 130.0)])
check("a ceiling more than the 2 ft raise limit above it does not count",
      not s and r[0]["why"] == "no ceiling meets it")
s, r = classify([wall(11, (0, 4.75), (0, 60), (84, 100.25))], [ceiling(9, (-20, 20), (-10, 80), 108.0)])
check("a soffit with a 7.75 in GAP below its only ceiling is still a soffit (to be raised)",
      [x["id"] for x in s] == [11], str(r))
s, r = classify([wall(6, (0, 4.75), (0, 60), (84, 108), typ="Generic - 2'")], [ceiling(9, (-20, 20), (-10, 80), 96.0)])
check("the generator's own soffit band type is left to it", not s and "band" in r[0]["why"])

print("not candidates at all")
s, r = classify([wall(7, (0, 4.75), (0, 60), (0, 108))], [C007])
check("an ordinary floor-to-ceiling wall", not s and not r)
s, r = classify([wall(8, (0, 4.75), (0, 60), (48, 100))], [C007])
check("a raised wall starting at 4 ft (below the 6 ft floor)", not s and not r)
s, r = classify([wall(10, (0, 4.75), (0, 60), (84, 132))], [C007])
check("a raised band taller than 3 ft", not s and not r)

print("raise to the ceiling (decide_raise)")
decide = ns["decide_raise"]
a, d, why = decide(84 * IN, 100.25 * IN, [96 * IN, 108 * IN])
check("1F 006/007: C001 (8 ft) touches, C007 (9 ft) is 7.75 in above -> raise 7.75 in",
      a == "raise" and abs(d * 12 - 7.75) < 1e-6, why)
check("...its bottom (7'-7.75\") stays below the 8 ft ceiling beside it", (84 + 7.75) < 96 - 1)
a, d, why = decide(84 * IN, 100.25 * IN, [96 * IN])
check("only a ceiling it already reaches -> touches, just panelise", a == "touches" and d == 0, why)
a, d, why = decide(84 * IN, 100.25 * IN, [100.3 * IN])
check("a 0.05 in difference counts as touching", a == "touches", why)
a, d, why = decide(84 * IN, 100.25 * IN, [130 * IN])
check("gap over the 2 ft limit -> kept, reported", a == "keep" and "limit" in why, why)
a, d, why = decide(84 * IN, 100.25 * IN, [90 * IN, 108 * IN])
check("raising would push its bottom into a ceiling beside it -> kept, reported",
      a == "keep" and "into the ceiling" in why, why)
a, d, why = decide(84 * IN, 100.25 * IN, [])
check("no ceiling beside it -> kept", a == "keep")

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
