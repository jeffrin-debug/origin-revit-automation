# Offline test of ceiling_joints_on_furring's pure geometry on C9's own C007 boards. No Revit.
#
#   python test_ceiling_joints_on_furring_offline.py

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ns = {"__name__": "ceiling_joints_on_furring",
      "__file__": os.path.join(HERE, "ceiling_joints_on_furring.py")}
exec(compile(open(ns["__file__"]).read(), ns["__file__"], "exec"), ns)
survey, plan_move, furring_lines = ns["survey"], ns["plan_move"], ns["furring_lines"]

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    print("  {}  {}{}".format("PASS" if cond else "FAIL", label, ("  [" + extra + "]") if extra else ""))


def board(mark, x0, y0, x1, y1):
    return {"mark": mark, "layer": "L0", "box": (x0, y0, x1, y1)}


def channels(y_lo, y_hi, x0, x1, step=16.0, face=2.5):
    out, y = [], y_lo
    while y <= y_hi + 1e-6:
        out.append((x0, y - face / 2.0, x1, y + face / 2.0))
        y += step
    return out


# C9 C007, 2026-09-29, exactly as generated (inches). Channels run along X on y = 333.83 + 16k.
B = [board("DP-C007-003", -541.77, 333.83, -493.77, 429.83),
     board("DP-C007-004", -541.77, 429.83, -493.77, 449.83),
     board("DP-C007-005", -493.77, 333.83, -445.77, 423.83),     # ends on wall 002's start line
     board("DP-C007-006", -493.77, 423.83, -447.77, 449.83)]
F = channels(333.83, 445.83, -589.77, -387.77)

print("C9 C007 - the joint the user selected")
axis, lines, rows = survey(B, F)
check("channels along X -> butt joints are edges at constant y", axis == "y", str(axis))
by = dict(((r["a"], r["b"]), r) for r in rows)
check("003 / 004 at y=429.83 is on a channel", by[("DP-C007-003", "DP-C007-004")]["on"])
r56 = by.get(("DP-C007-005", "DP-C007-006"))
check("005 / 006 at y=423.83 is found OFF channel", r56 is not None and not r56["on"], str(r56))
check("...6 in from the nearest channel", r56 and abs(r56["off_by_in"] - 6.0) < 0.05, str(r56 and r56["off_by_in"]))
check("side-by-side boards (003 | 005) are not butt joints", ("DP-C007-003", "DP-C007-005") not in by)
mv, why = plan_move(B, r56["joint"], axis, lines)
check("moves to the nearest channel, y=429.83", mv and abs(mv["to"] - 429.83) < 0.01, str(mv or why))
check("...005 grows to one 96 in sheet, 006 keeps 20 in",
      mv and B[mv["grow"]]["mark"] == "DP-C007-005" and B[mv["shrink"]]["mark"] == "DP-C007-006")

print("nearest channel illegal -> the other way")
# 006 only 10 in past the channel above: 429.83 would leave it 4 in, so go down to 413.83.
B2 = [board("A", 0, 333.83, 48, 423.83), board("B", 0, 423.83, 48, 433.83)]
axis, lines, rows = survey(B2, channels(333.83, 445.83, -10, 60))
mv, why = plan_move(B2, rows[0]["joint"], axis, lines)
check("joint goes down to 413.83 (B grows to 20 in, A keeps 80 in)",
      mv and abs(mv["to"] - 413.83) < 0.01 and B2[mv["grow"]]["mark"] == "B", str(mv or why))

print("no legal channel -> reported, not forced")
B3 = [board("A", 0, 0, 48, 10), board("B", 0, 10, 48, 20)]       # a 20 in strip, channels at 0 / 16
axis, lines, rows = survey(B3, channels(0, 16, -10, 60))
mv, why = plan_move(B3, rows[0]["joint"], axis, lines)
check("10 + 10 in strip: every channel leaves a sub-16 in piece",
      mv is None and why, str(why))

print("a channel line with no steel under the joint does not count")
F4 = channels(0, 96, 100, 200)                                   # steel only at x 100..200
axis, lines, rows = survey([board("A", 0, 0, 48, 48), board("B", 0, 48, 48, 96)], F4)
check("joint at y=48 on the grid but channel does not reach it -> off", rows and not rows[0]["on"])

print("channels along Y -> joints are edges at constant x")
FX = [(x - 1.25, 0, x + 1.25, 200) for x in (0, 16, 32, 48, 64, 80, 96, 112)]
axis, lines, rows = survey([board("A", 0, 0, 90, 48), board("B", 90, 0, 120, 48)], FX)
check("axis x, joint at x=90 off, moves to 96",
      axis == "x" and rows and not rows[0]["on"]
      and abs(plan_move([board("A", 0, 0, 90, 48), board("B", 90, 0, 120, 48)],
                        rows[0]["joint"], axis, lines)[0]["to"] - 96) < 0.01)

print("\n{} / {} passed".format(sum(fails), len(fails)))
raise SystemExit(0 if all(fails) else 1)
