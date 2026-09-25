# wall_end_joints.py - no wall-board joint closer to the end of a face than one 16 in stud bay.
#
# Same rule as ceiling_end_joints.py, for walls (user direction 2026-09-25: "these are also suit
# for walls"). The wall generator's course_cells_on_studs() runs full sheets along a course and
# puts each joint on the furthest stud within one sheet length - so whatever is left at the end of
# the face, at a corner or a wall end, is whatever it is, and can be a few inches.
#
# For every course, if the piece at either end of the face is shorter than MIN_END_IN, the joint
# next to it moves to the nearest STUD LINE that leaves the end piece at least MIN_END_IN. A move
# is made only if the piece on the other side of the joint is also at least MIN_END_IN, no sheet
# goes over 8 ft, and the new joint is at least JOINT_CLEAR_FT from a door/window jamb (the
# generator's own jamb rule). Otherwise the spot is reported and left.
#
# Applied to the generator's source string only; the repository file is not modified.

import traceback

MIN_END_IN = 16.0

_OLD = "                _cells, _off_stud = course_cells_on_studs(flo, fhi, row_shift, stud_xs)\n"
_NEW = ("                _cells, _off_stud = course_cells_on_studs(flo, fhi, row_shift, stud_xs)\n"
        "                _cells = _origin_wall_end_cells(_cells, flo, fhi, stud_xs, opening_rects,\n"
        "                                                wall_id, face_config[\"side\"], cy0, cy1)\n")

_HELPER = '''
# ---- injected by origin_pipeline/wall_end_joints.py (not part of this file on disk) ----
_ORIGIN_WALL_MIN_END_FT = __MIN_END__ / 12.0
_ORIGIN_WALL_END_JOINTS = []


def _origin_wall_end_cells(cells, flo, fhi, stud_xs, opening_rects, wall_id, side, cy0, cy1):
    """course_cells_on_studs() output with a too-short end piece fixed by moving its joint to a
    stud line further in. Cells stay contiguous from flo to fhi."""
    if len(cells) < 2:
        return cells
    cells = list(cells)
    mn, tol = _ORIGIN_WALL_MIN_END_FT, 1e-4
    studs = sorted(set(float(s) for s in (stud_xs or [])))

    def clear_of_jambs(s):
        for (ox0, oy0, ox1, oy1) in (opening_rects or []):
            if abs(s - ox0) < JOINT_CLEAR_FT or abs(s - ox1) < JOINT_CLEAR_FT:
                return False
        return True

    def rec(end, j, piece, nj):
        r = {"wall": wall_id, "side": side, "course_ft": [round(cy0, 2), round(cy1, 2)],
             "end": end, "joint_was_ft": round(j, 3), "end_piece_was_in": round(piece * 12, 2)}
        if nj is None:
            r.update({"moved": False, "why": "no stud line leaves both pieces >= {:.0f} in within one "
                                             "sheet, clear of jambs".format(mn * 12)})
        else:
            r.update({"moved": True, "joint_now_ft": round(nj, 3),
                      "end_piece_now_in": round(((fhi - nj) if end == "far" else (nj - flo)) * 12, 2)})
        _ORIGIN_WALL_END_JOINTS.append(r)

    # far end of the face
    j = cells[-1][0]
    piece = fhi - j
    if piece < mn - tol:
        start = cells[-2][0]
        cand = [s for s in studs if start + mn - tol <= s <= fhi - mn + tol and s < j
                and fhi - s <= PANEL_LENGTH_FT + tol and clear_of_jambs(s)]
        nj = max(cand) if cand else None
        if nj is not None:
            cells[-2] = (start, nj)
            cells[-1] = (nj, fhi)
        rec("far", j, piece, nj)
    # near end of the face
    j = cells[0][1]
    piece = j - flo
    if piece < mn - tol and len(cells) >= 2:
        stop = cells[1][1]
        cand = [s for s in studs if flo + mn - tol <= s <= stop - mn + tol and s > j
                and s - flo <= PANEL_LENGTH_FT + tol and clear_of_jambs(s)]
        nj = min(cand) if cand else None
        if nj is not None:
            cells[0] = (flo, nj)
            cells[1] = (nj, stop)
        rec("near", j, piece, nj)
    return cells
# ---- end injection ----

'''


def apply_to_source(src):
    info = {"applied": False}
    try:
        n = src.count(_OLD)
        if n != 1:
            info["skipped"] = "expected the course cell call once, found {}".format(n)
            return src, info
        anchor = "\ndef generate_courses("
        i = src.find(anchor)
        if i < 0:
            info["skipped"] = "no generate_courses() to insert before"
            return src, info
        src = src[:i + 1] + _HELPER.replace("__MIN_END__", repr(MIN_END_IN)) + src[i + 1:]
        src = src.replace(_OLD, _NEW, 1)
        info["applied"] = True
        info["min_end_in"] = MIN_END_IN
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info


def collect(ns, info):
    rows = ns.get("_ORIGIN_WALL_END_JOINTS")
    if rows is not None:
        info["moved"] = [r for r in rows if r.get("moved")]
        info["could_not_move"] = [r for r in rows if not r.get("moved")]
    return info
