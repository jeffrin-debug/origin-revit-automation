# corner_end_studs.py - keep an L-corner's end studs out of the other wall's space.
#
# stud_lines() centres an end stud on run_lo/run_hi, and corner_pullbacks() sets those at an
# L-corner to: through wall - its own end (flush with the other wall's outer face, when the walls
# are drawn that way); butting wall - the through wall's near face. So half of each end stud's
# flange (FLANGE_FT/2 = 5/8in) pokes past the line it should stop at:
#
#   * the through wall's stud pokes past the corner, into the space the BUTTING wall's outer-face
#     board needs (corner_lap.py runs that board on to the back of the lapping board).
#     trim_drywall_from_neighbor_studs() then cuts the board back to the through wall's core, the
#     stud end is left exposed, and the corner-infill pass patches it with 5/8in strips.
#     C9 2026-09-29: ST-004-001 cut DP-002-001A/002A back 3in; strips DP-004-004A/004B.
#   * the butting wall's stud pokes 5/8in into the through wall's core, where the through wall's
#     end stud sits once it is moved in (ST-002-003 x ST-004-001, 0.68 cu in).
#
# User direction 2026-09-29: "those 2 has to meet by attaching their ends". So at an L-corner:
#   through wall: framing stops behind the butting board - end stud's outer flange at
#                 (other wall's outer face + t) - so the butting board runs to the lap;
#   butting wall: framing stops at the through wall's near face with the end stud's flange flush
#                 there, not centred on it.
# T-joins and free ends keep the generator's centred end stud (the infill / end-stud widening
# passes are built around it).
#
# Applied to the generator's source string only; the repository file is not modified.

import traceback

_OLD = "                pull = (s + wO / 2.0) if butt else (s - wO / 2.0)\n"
_NEW = ("                # corner_end_studs.py (pipeline): the end stud lies wholly inside the run -\n"
        "                # through wall's behind the butting board, butting wall's flush at the face.\n"
        "                pull = ((s + wO / 2.0 + FLANGE_FT / 2.0) if butt else\n"
        "                        (s - wO / 2.0 + DRYWALL_THICKNESS_STD_FT + FLANGE_FT / 2.0))\n")


def apply_to_source(src):
    info = {"applied": False}
    try:
        n = src.count(_OLD)
        if n != 1:
            info["skipped"] = "expected the L-corner pull-back once, found {}".format(n)
            return src, info
        src = src.replace(_OLD, _NEW, 1)
        info["applied"] = True
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info
