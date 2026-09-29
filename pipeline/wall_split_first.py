# wall_split_first.py - lay a wall course out in sheets BETWEEN its splits, not across them.
#
# emit_drywall() tiles every course across the whole face first (course_cells_on_studs: from
# each joint, run to the furthest stud within one sheet) and only then breaks each cell at the
# course's splits - partition tees, and the ceiling-height breaks wall_ceiling_profile.py adds.
# A split already ends the board, but the sheet joint laid out before it is kept too, so a span
# between a split and the face end that would fit ONE sheet still comes out as two boards.
#
# C9 2026-09-29, wall 037 face A, 0-48in course: joint at 96in (the furthest stud from 3in),
# tee split at 31.5in -> 31.5-96 + 96-125.5, although 31.5-125.5 is only 94in. The K004 column
# trim then cut the second board to a 1.37in sliver (DP-037-003A). User: "it can be a single
# panel".
#
# The patch: course_cells_on_studs() becomes a wrapper that first cuts [flo, fhi] at this
# course's splits (the generator's own split_interval + merge_small_segments, so the same
# confetti rule applies) and runs the original layout inside each span. The loop's own split
# afterwards is then a no-op. With no splits it is exactly the original. The course's splits are
# handed over through _ORIGIN_COURSE_SPLITS, set on the line before the call - the call line itself
# is left alone because wall_end_joints.py anchors on it. wall_end_joints.py never moves a joint
# that is one of these splits.
#
# Applied to the generator's source string only; the repository file is not modified.

import traceback

_DEF = "def course_cells_on_studs(flo, fhi, row_shift, stud_xs):\n"
_DEF_NEW = "def _origin_cells_one_span(flo, fhi, row_shift, stud_xs):\n"

_CALL_ANCHOR = "                # Cells come from the STUDS now, not from stepping 8 ft at a time, so every butt\n"
_CALL_NEW = ("                _ORIGIN_COURSE_SPLITS[:] = course_splits     # wall_split_first.py (pipeline)\n"
             + _CALL_ANCHOR)

_HELPER = '''
# ---- injected by origin_pipeline/wall_split_first.py (not part of this file on disk) ----
_ORIGIN_COURSE_SPLITS = []        # this course's split positions, set just before the call


def course_cells_on_studs(flo, fhi, row_shift, stud_xs):
    """The original layout run separately in each span between this course's splits, so no
    sheet joint is laid out in a span that a split has already made short enough for one sheet."""
    splits = [p for p in _ORIGIN_COURSE_SPLITS if flo + 1e-4 < p < fhi - 1e-4]
    if not splits:
        return _origin_cells_one_span(flo, fhi, row_shift, stud_xs)
    cells, off = [], 0
    for (a, b) in merge_small_segments(split_interval(flo, fhi, splits), MIN_SAFE_SEGMENT_FT):
        c, o = _origin_cells_one_span(a, b, row_shift, stud_xs)
        cells.extend(c)
        off += o
    return cells, off


def _origin_is_course_split(x):
    return any(abs(x - p) <= 1e-4 for p in _ORIGIN_COURSE_SPLITS)
# ---- end injection ----

'''


def apply_to_source(src):
    info = {"applied": False}
    try:
        for label, old in (("course_cells_on_studs def", _DEF), ("course cell call", _CALL_ANCHOR)):
            n = src.count(old)
            if n != 1:
                info["skipped"] = "expected the {} once, found {}".format(label, n)
                return src, info
        anchor = "\ndef generate_courses("
        i = src.find(anchor)
        if i < 0:
            info["skipped"] = "no generate_courses() to insert before"
            return src, info
        # rename the original first - the helper carries a def line of the same name
        src = src.replace(_DEF, _DEF_NEW, 1)
        src = src.replace(_CALL_ANCHOR, _CALL_NEW, 1)
        i = src.find(anchor)
        src = src[:i + 1] + _HELPER + src[i + 1:]
        info["applied"] = True
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info
