# door_head_courses.py - keep the wall board rows clear of a door head.
#
# The wall generator hangs its 4 ft rows from the floor: 0-4, 4-8, 8-top. For a 7'-0" door that
# is right - the head (7.30 ft with trim + clearance) sits inside the 4-8 row, so both head corners
# are inside one notched board and the 8 ft joint is ~0.7 ft above the head. For an 8'-0" door it
# is wrong: the head lands at 8.30 ft, 0.30 ft above the 8 ft joint, so the whole side of the door
# is two stacked boards and the row above it is a 3 in notch - a joint right at the head corners,
# which is where drywall cracks.
#
# Rule (user direction, 2026-09-25): when a door head lands within HEAD_JOINT_CLEAR_FT of a row
# joint, that wall face is hung 4 ft + 2 ft + 4 ft (+ 4 ft ...) from the floor instead. On a 10 ft
# wall with an 8 ft door that gives 0-4, 4-6, 6-10: the head is inside the top sheet, 2.3 ft up
# from its bottom edge, and no joint is within 1.7 ft of it. A 7 ft door does not trigger it.
#
# The generator belongs to a separate repository and is NEVER modified on disk. apply_to_source()
# rewrites the one row-generation call in the source string just before it is compiled, the same
# way ceiling_direction.apply_to_source() handles FURRING_RUN_NS.

import re
import traceback

DOOR_HEAD_COURSES = True
HEAD_JOINT_CLEAR_FT = 0.5            # a row joint closer than this to a door head triggers the rule
ALT_COURSE_HEIGHTS_FT = (4.0, 2.0)   # first rows of the alternate layout; 4 ft rows after that

# The call being replaced, exactly as it appears in the per-face loop of emit_drywall().
_CALL = "for (cy0, cy1, row) in generate_courses(face_height, v_start):"
_NEW_CALL = ("for (cy0, cy1, row) in _origin_door_head_courses("
             "face_height, v_start, opening_rects, li, wall_id, face_name):")

# Injected ahead of generate_courses(). Uses the generator's own PANEL_HEIGHT_FT and
# MIN_PIECE_HEIGHT_FT so the alternate rows obey the same floors as the standard ones.
_HELPER = '''
# ---- injected by origin_pipeline/door_head_courses.py (not part of this file on disk) ----
_ORIGIN_HEAD_JOINT_CLEAR_FT = {clear!r}
_ORIGIN_ALT_COURSE_HEIGHTS_FT = {alt!r}
_ORIGIN_DOOR_HEAD_ROWS = []


def _origin_door_head_courses(face_height, v_start, opening_rects, li, wall_id, face_name):
    """generate_courses(), unless a door head lands within _ORIGIN_HEAD_JOINT_CLEAR_FT of one of
    its row joints - then rows of _ORIGIN_ALT_COURSE_HEIGHTS_FT followed by full courses. Only
    the room-facing layer (li == 0) is re-laid; a rated wall's second layer keeps its stagger."""
    std = generate_courses(face_height, v_start)
    if li != 0 or not opening_rects:
        return std
    heads = [oy1 for (ox0, oy0, ox1, oy1) in opening_rects
             if oy0 <= 0.05 and oy1 < face_height - 0.05]
    if not heads:
        return std

    def clash(rows):
        joints = [cy1 for (cy0, cy1, r) in rows[:-1]]
        return [(round(j, 3), round(h, 3)) for j in joints for h in heads
                if abs(j - h) < _ORIGIN_HEAD_JOINT_CLEAR_FT]

    hit = clash(std)
    if not hit:
        return std

    alt = []
    y = 0.0
    row = 0
    while y < face_height - 1e-4:
        h = (_ORIGIN_ALT_COURSE_HEIGHTS_FT[row] if row < len(_ORIGIN_ALT_COURSE_HEIGHTS_FT)
             else PANEL_HEIGHT_FT)
        y1 = min(face_height, y + h)
        if (y1 - y) >= MIN_PIECE_HEIGHT_FT:
            alt.append((y, y1, row))
        y = y1
        row += 1
    if clash(alt):
        return std                    # the alternate is no better for this door - keep the default

    _ORIGIN_DOOR_HEAD_ROWS.append({{
        "wall": wall_id, "face": face_name,
        "door_heads_ft": [round(h, 3) for h in heads],
        "default_joint_hits": hit,
        "rows_ft": [[round(a, 3), round(b, 3)] for (a, b, r) in alt]}})
    return alt
# ---- end injection ----

'''


def apply_to_source(src):
    """Return (src, info). src comes back unchanged, with the reason in info, if the generator no
    longer has the exact call this patch targets - a layout rule must never stop the panels."""
    info = {"applied": False}
    if not DOOR_HEAD_COURSES:
        info["skipped"] = "DOOR_HEAD_COURSES is False"
        return src, info
    try:
        n = src.count(_CALL)
        if n != 1:
            info["skipped"] = "expected 1 row-generation call in the generator, found {}".format(n)
            return src, info
        m = re.search(r"^def generate_courses\(", src, re.MULTILINE)
        if m is None:
            info["skipped"] = "no generate_courses() definition found"
            return src, info
        helper = _HELPER.format(clear=HEAD_JOINT_CLEAR_FT, alt=tuple(ALT_COURSE_HEIGHTS_FT))
        src = src[:m.start()] + helper + src[m.start():]
        src = src.replace(_CALL, _NEW_CALL, 1)
        info["applied"] = True
        info["clear_ft"] = HEAD_JOINT_CLEAR_FT
        info["alt_rows_ft"] = list(ALT_COURSE_HEIGHTS_FT)
    except Exception:
        info["error"] = traceback.format_exc()[-800:]
    return src, info


def collect(ns, info):
    """After the generator has run in namespace ns: which wall faces were re-laid, and how."""
    rows = ns.get("_ORIGIN_DOOR_HEAD_ROWS")
    if rows is not None:
        info["faces_relaid"] = len(rows)
        info["relaid"] = rows[:40]
    return info
