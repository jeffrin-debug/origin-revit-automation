# Offline test of wall_narrow_merge.pick() with 1F's own numbers. No Revit.
#
#   python test_wall_narrow_merge_offline.py

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
ns = {"__name__": "wall_narrow_merge", "__file__": os.path.join(HERE, "wall_narrow_merge.py")}
exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
pick = ns["pick"]

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


def b(mark, a0, z0, a1, z1):
    return {"mark": mark, "r": (a0, z0, a1, z1)}


print("a 3.69 in face in three rows (wall 003 B)")
r1, r2, r3 = b("R1", 0, 0, 3.69, 48), b("R2", 0, 48, 3.69, 96), b("R3", 0, 96, 3.69, 108)
c, m = pick(r1, [r2, r3])
check("bottom row joins the row above: one 3.69 x 96 strip", c is r2 and m == (0, 0, 3.69, 96), str(m))
c, m = pick(b("R12", 0, 0, 3.69, 96), [r3])
check("the 96 in strip cannot also take the top 12 in (108 in > 8 ft)", c is None, str(m))

print("strip beside a door joins the board over the door")
side = b("S", 0, 0, 3, 48)                          # 3 in between a partition and the door
over = b("O", 0, 48, 46, 96)                        # board over the door, 46 in wide
c, m = pick(side, [over])
check("merged into one notched sheet 46 x 96 in", c is over and m == (0, 0, 46, 96), str(m))
wide = b("W", 0, 48, 60, 96)
c, m = pick(side, [wide])
check("board over the door 60 in wide -> 60 x 96 is not one sheet, refused", c is None)

print("same course neighbour")
c, m = pick(b("N", 90.19, 48, 100, 96), [b("L", 60.75, 48, 90.19, 96)])
check("9.81 in joins its 29.44 in neighbour -> 39.25 x 48", c is not None and round(m[2] - m[0], 2) == 39.25, str(m))

print("must touch the narrow board's WHOLE edge")
c, m = pick(b("P", 0, 0, 6, 48), [b("Q", 6, 24, 40, 72)])
check("neighbour covering only half its height -> no merge", c is None)
c, m = pick(b("P", 0, 0, 6, 48), [b("Q", 6.2, 0, 40, 48)])
check("0.2 in gap (not touching) -> no merge", c is None)

print("smallest merged board wins")
c, m = pick(b("P", 0, 0, 6, 48), [b("BIG", 6, 0, 90, 48), b("UP", 0, 48, 20, 96)])
check("prefers the 20 x 96 over the 90 x 48? no - smaller AREA wins: 20x96=1920 < 90x48=4320",
      c["mark"] == "UP", str(m))

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
