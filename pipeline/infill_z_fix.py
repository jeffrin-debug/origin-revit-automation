# infill_z_fix.py - the wall generator's corner-infill pass counts a wall's base offset twice.
#
# emit_corner_infill_for_exposed_studs() lifts the wall start by its Base Offset (wstart.Z) and
# then builds each candidate patch with make_rect_solid(layer_origin, ..., (lx0, lz0, lx1, f_lz1)),
# where lz0 / f_lz1 are the stud's WORLD Z. make_rect_solid measures its rect's y from the
# origin, which already sits at wstart.Z - so the patch lands wstart.Z too high.
#
# On a wall at the floor (level 0, no offset) wstart.Z is 0 and nothing shows. On walls 006/007
# in 1F - header strips from 7'-0" to 8'-4 1/4" - it put every candidate at 14-15 ft, where no
# board covers it, so the pass "found" all 22 of their studs exposed and emitted 22 strips
# floating 6 ft above the walls (seen 2026-09-25, after the ceilings were lowered to 8 ft). The
# same error would hit every wall on an upper level.
#
# The fix measures the patch from the origin: (lz0 - wstart.Z, f_lz1 - wstart.Z). Applied to the
# generator's source string only - the file on disk belongs to another repository.

import traceback

_OLD = "(lx0, lz0, lx1, f_lz1), t, mat_id, gs_id)"
_NEW = "(lx0, lz0 - wstart.Z, lx1, f_lz1 - wstart.Z), t, mat_id, gs_id)"


def apply_to_source(src):
    info = {"applied": False}
    try:
        n = src.count(_OLD)
        if n != 1:
            info["skipped"] = "expected the infill candidate line once, found {}".format(n)
            return src, info
        src = src.replace(_OLD, _NEW, 1)
        info["applied"] = True
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info
