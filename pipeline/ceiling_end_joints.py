# ceiling_end_joints.py - no ceiling-board joint closer to a wall than one 16 in framing bay.
#
# The ceiling generator lays each 4 ft course as full 8 ft sheets from one side of the room and
# leaves whatever is left at the other side. Nothing limits that leftover, so a course can end in
# a sliver: 1F ceiling C007, course y = 340.7..388.7 in, is 102.5 in wide -> DP-C007-008 (96 in,
# a full sheet) + DP-C007-009 (6.5 in) against wall 014. A joint 6.5 in off the wall is two seams
# almost on top of each other once taped, and a 6.5 in strip has barely one furring line to fix to.
#
# Rule (user direction 2026-09-25): the joint and the end wall must be at least one full 16 in bay
# apart. For every course, on each stretch where it actually crosses the room (from the room
# outline, so notched and L-shaped rooms are right), if the piece at either end is shorter than
# MIN_END_IN, the joint next to it moves toward the middle by whole furring bays (16 in - the
# board grid and the furring grid share an origin, so a moved joint is still on a channel) until
# the end piece is at least MIN_END_IN. A move is made only if every sheet stays within 8 ft and
# the piece on the other side of the joint is also at least MIN_END_IN; otherwise the spot is
# reported and left. For C007 that turns 96 + 6.5 into 80 + 22.5.
#
# Applied to the generator's source string only; the repository file is not modified.

import traceback

MIN_END_IN = 16.0

_OLD = ("            s = span_lo - row_shift\n"
        "            col = 0\n"
        "            while s < span_hi - 1e-4:\n"
        "                rs0 = max(span_lo, s)\n"
        "                rs1 = min(span_hi, s + PANEL_LENGTH_FT)\n"
        "                s += PANEL_LENGTH_FT\n"
        "                col += 1\n")
_NEW = ("            col = 0\n"
        "            for (rs0, rs1) in _origin_span_cells(span_lo, span_hi, row_shift, cc0, cc1,\n"
        "                                                 outer, holes, ceiling_id):\n"
        "                col += 1\n")

_HELPER = '''
# ---- injected by origin_pipeline/ceiling_end_joints.py (not part of this file on disk) ----
_ORIGIN_MIN_END_FT = __MIN_END__ / 12.0
_ORIGIN_END_JOINTS = []


def _origin_row_intervals(outer, holes, c_mid, span_along_x):
    """Where the line through the middle of a course crosses the room: [(a, b), ...] along the
    span axis (x when span_along_x). Holes split it like any other boundary."""
    hits = []
    for poly in [outer] + list(holes or []):
        n = len(poly)
        for i in range(n):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
            if span_along_x:
                c1, s1, c2, s2 = y1, x1, y2, x2
            else:
                c1, s1, c2, s2 = x1, y1, x2, y2
            if (c1 <= c_mid < c2) or (c2 <= c_mid < c1):
                hits.append(s1 + (c_mid - c1) / (c2 - c1) * (s2 - s1))
    hits.sort()
    return [(hits[i], hits[i + 1]) for i in range(0, len(hits) - 1, 2) if hits[i + 1] - hits[i] > 1e-4]


def _origin_span_cells(span_lo, span_hi, row_shift, cc0, cc1, outer, holes, ceiling_id):
    """The generator's own 8 ft cells for one course, with any joint that lands closer than
    _ORIGIN_MIN_END_FT to where the course meets a wall moved inward by whole furring bays."""
    joints = []
    s = span_lo - row_shift + PANEL_LENGTH_FT
    while s < span_hi - 1e-4:
        if s > span_lo + 1e-4:
            joints.append(s)
        s += PANEL_LENGTH_FT
    mn, bay, tol = _ORIGIN_MIN_END_FT, FURRING_SPACING_FT, 1e-4
    ivs = _origin_row_intervals(outer, holes, (cc0 + cc1) / 2.0, not FURRING_RUN_NS) or [(span_lo, span_hi)]

    def neighbours(k):
        left = joints[k - 1] if k > 0 else span_lo
        right = joints[k + 1] if k + 1 < len(joints) else span_hi
        return left, right

    for (a, b) in ivs:
        inside = [k for k, j in enumerate(joints) if a + tol < j < b - tol]
        if not inside:
            continue
        for end in ("far", "near"):
            k = inside[-1] if end == "far" else inside[0]
            j = joints[k]
            piece = (b - j) if end == "far" else (j - a)
            if piece >= mn - tol:
                continue
            steps = 1
            while piece + steps * bay < mn - tol:
                steps += 1
            nj = j - steps * bay if end == "far" else j + steps * bay
            left, right = neighbours(k)
            if end == "far":
                other = nj - max(a, left)                   # piece left behind on the inside
                grown = right - nj                          # the sheet that now reaches the wall
            else:
                other = min(b, right) - nj
                grown = nj - left
            rec = {"ceiling": ceiling_id, "course_in": [round(cc0 * 12, 2), round(cc1 * 12, 2)],
                   "wall_at_in": round((b if end == "far" else a) * 12, 2),
                   "joint_was_in": round(j * 12, 2), "end_piece_was_in": round(piece * 12, 2)}
            if other >= mn - tol and grown <= PANEL_LENGTH_FT + tol:
                joints[k] = nj
                rec.update({"moved": True, "joint_now_in": round(nj * 12, 2),
                            "end_piece_now_in": round((piece + steps * bay) * 12, 2),
                            "bays": steps})
            else:
                rec.update({"moved": False,
                            "why": "moving it would leave a {:.1f} in piece or a {:.1f} in sheet".format(
                                other * 12, grown * 12)})
            _ORIGIN_END_JOINTS.append(rec)
    joints.sort()
    edges = [span_lo] + joints + [span_hi]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] - edges[i] > tol]
# ---- end injection ----

'''


def apply_to_source(src):
    info = {"applied": False}
    try:
        n = src.count(_OLD)
        if n != 1:
            info["skipped"] = "expected the course span loop once, found {}".format(n)
            return src, info
        anchor = "\ndef emit_drywall("
        i = src.find(anchor)
        if i < 0:
            info["skipped"] = "no emit_drywall() to insert before"
            return src, info
        src = src[:i + 1] + _HELPER.replace("__MIN_END__", repr(MIN_END_IN)) + src[i + 1:]
        src = src.replace(_OLD, _NEW, 1)
        info["applied"] = True
        info["min_end_in"] = MIN_END_IN
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info


def collect(ns, info):
    rows = ns.get("_ORIGIN_END_JOINTS")
    if rows is not None:
        info["moved"] = [r for r in rows if r.get("moved")]
        info["could_not_move"] = [r for r in rows if not r.get("moved")]
    return info
