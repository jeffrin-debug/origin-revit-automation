# corner_lap.py - make the two boards at an OUTSIDE corner meet.
#
# corner_face_extents() in the wall generator ends BOTH boards of an outside (convex) L-corner at
# the crossing of the two location lines (`val = Xp`). The corner is then open by half the other
# wall's thickness on one face and that plus a board thickness on the other - 2 3/8in and 1 7/8in
# for the 4 3/4in partitions in 1F (DP-006-001A / DP-007-001B, the 7 ft soffit band). The corner
# infill pass does not close it, because no stud sits in the opening.
#
# User direction 2026-09-25: "both has to be meetable panels". So the corner is hung the way it is
# on site - one board LAPS, the other BUTTS behind it:
#
#   through wall (the higher ElementId - the generator's existing tiebreak, so both walls agree):
#       runs past the crossing by hwO, to the other wall's outer finished face;
#   butting wall:
#       runs past the crossing by hwO - t, stopping against the back of the lapping board.
#
# The two boards touch along one face and share no volume. This replaces the 2026-08-07 "both end
# where they touch" rule, which was chosen because an earlier wrap overlapped by t in 409_Testing;
# stage 2's own overlap scan (diag_board_overlaps.py) is the guard that it does not come back.
#
# Applied to the generator's source string only; the repository file is not modified.

import traceback

_OLD = ("                    val = Xp\n"
        "            if ei == 0:\n"
        "                ext[side][0] = val")
_NEW = ("                    # corner_lap.py (pipeline): lap the through wall to the other wall's\n"
        "                    # outer face, butt the other one against its back - they meet.\n"
        "                    _lap = hwO if role_through else (hwO - t)\n"
        "                    val = (Xp - _lap) if ei == 0 else (Xp + _lap)\n"
        "            if ei == 0:\n"
        "                ext[side][0] = val")


def apply_to_source(src):
    info = {"applied": False}
    try:
        n = src.count(_OLD)
        if n != 1:
            info["skipped"] = "expected the outside-corner branch once, found {}".format(n)
            return src, info
        src = src.replace(_OLD, _NEW, 1)
        info["applied"] = True
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info
