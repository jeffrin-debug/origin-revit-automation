# wall_joint_layout.py
# ============================================================
# Board joints that land on studs, by construction.
#
# THE BUG THIS REPLACES
#
# origin_wall_assembly_v4's board layout never looks at the studs. STUD_SPACING_FT appears once
# in the whole generator, inside stud_lines(); emit_drywall() lays boards out as
#
#     x = flo - row_shift;  while x < fhi:  cell = (x, x + PANEL_LENGTH_FT);  x += PANEL_LENGTH_FT
#
# and `stud_xs`, which IS passed in, is used only to place screws. Joints land on studs purely
# because the numbers happen to divide: an 8 ft sheet is 6 stud bays and both staggers are 4 ft
# = 3 bays. Nothing enforces it, so anything that perturbs the run breaks it silently:
#
#   1. adjust_row_shift() nudges a course away from an opening jamb using offsets of 6, 12, 24
#      and 48 inches. Only 48 is a whole number of 16 in bays - and it is tried LAST, so five
#      off-grid candidates get a chance first. It runs PER COURSE, which is why one row floats
#      between two correct ones.
#   2. A face at an OUTSIDE corner wraps past the wall end (corner_face_extents: "values may be
#      <0 or >length where a face wraps"), while the framing does not (same docstring: "Framing
#      keeps using corner_pullbacks (butt only)"). The two grids then start half an inch apart
#      and EVERY joint on that face is off-stud - the face-with-nothing-behind-it case.
#
# THE RULE
#
# A butt joint between two boards must land on a stud: that is the only thing holding the two
# sheet ends. The face's outer edges are not joints - at a wrapped corner the sheet deliberately
# hangs past the wall end to cover the adjacent wall's drywall - so only INTERNAL boundaries are
# constrained.
#
# THE METHOD
#
# Stop deriving joints from arithmetic and derive them from the stud lines themselves: from each
# joint, run to the FURTHEST stud still within one stock length. That is what an installer does,
# it can never produce an over-length board, and it is correct whatever offset the two grids
# start with.
# ============================================================

# Pure functions, no Revit. Kept importable-by-exec like everything else here.

DEFAULT_PANEL_LENGTH_FT = 8.0
DEFAULT_STUD_SPACING_FT = 16.0 / 12.0
# A board shorter than this is a sliver; the generator already merges these away elsewhere.
MIN_BOARD_FT = 0.5


def quantise_shift(shift, stud_spacing_ft=DEFAULT_STUD_SPACING_FT,
                   panel_length_ft=DEFAULT_PANEL_LENGTH_FT):
    """Round a course stagger to a whole number of stud bays, wrapped into [0, panel_length).

    The stagger exists to stop joints stacking row-to-row. Any whole number of bays does that
    just as well as an arbitrary offset, and keeps the course on the framing.
    """
    bays = round(float(shift) / stud_spacing_ft)
    s = bays * stud_spacing_ft
    while s < 0.0:
        s += panel_length_ft
    while s >= panel_length_ft:
        s -= panel_length_ft
    return s


def nudge_candidates_in_bays(stud_spacing_ft=DEFAULT_STUD_SPACING_FT, max_bays=3):
    """Offsets to try when a joint has to move off an opening jamb.

    Whole stud bays only, nearest first. Replaces the generator's (6, -6, 12, -12, 24, 48) inch
    list, of which only the last was on the grid - and which was tried last.
    """
    out = []
    for b in range(1, max_bays + 1):
        out.append(b * stud_spacing_ft)
        out.append(-b * stud_spacing_ft)
    return out


def course_cells_on_studs(flo, fhi, row_shift, stud_xs,
                          panel_length_ft=DEFAULT_PANEL_LENGTH_FT,
                          min_board_ft=MIN_BOARD_FT, tol=1e-6):
    """Board cells across one course, every INTERNAL joint on a stud line.

    flo/fhi  this face's own along-wall extent. May sit outside [0, wall_length] where the face
             wraps a corner - that is intended and those two outer edges are never joints.
    stud_xs  the stud lines from stud_lines(), same coordinate system.
    row_shift  the course stagger. Only shifts where the FIRST joint falls; every joint after it
             is decided by the studs.

    Returns (cells, info). cells is a list of (x0, x1) covering flo..fhi exactly.
    info["off_stud_joints"] counts joints that could not be placed on a stud - which happens
    only where the studs genuinely do not reach, and is reported rather than hidden.
    """
    if fhi - flo <= tol:
        return [], {"joints": 0, "off_stud_joints": 0, "boards": 0}

    studs = sorted(set(float(s) for s in (stud_xs or [])))
    cells = []
    info = {"joints": 0, "off_stud_joints": 0, "boards": 0, "max_board_ft": 0.0}

    # The first board starts at the face edge. row_shift pulls the FIRST joint in, so a
    # staggered course breaks in a different bay from the one above it.
    x = flo
    first_limit = x + panel_length_ft - (row_shift or 0.0)
    limit = first_limit

    while True:
        if fhi - x <= panel_length_ft + tol:
            cells.append((x, fhi))          # last board reaches the face edge
            break

        # Furthest stud we can still reach without exceeding one stock length, and far enough
        # past the current joint to leave a real board rather than a sliver.
        reach = min(limit, x + panel_length_ft)
        usable = [s for s in studs if x + min_board_ft <= s <= reach + tol]
        if usable:
            nxt = usable[-1]
        else:
            # No stud in range - the studs do not cover here. Fall back to a plain step so the
            # wall still gets boarded, and say so.
            nxt = reach
            info["off_stud_joints"] += 1

        if nxt <= x + tol or nxt >= fhi - tol:
            cells.append((x, fhi))
            break

        cells.append((x, nxt))
        info["joints"] += 1
        x = nxt
        limit = x + panel_length_ft      # stagger applies to the first joint only

    info["boards"] = len(cells)
    info["max_board_ft"] = round(max((b - a) for (a, b) in cells), 6) if cells else 0.0
    return cells, info


def joints_of(cells):
    """The internal boundaries only - the two outer edges are face extents, not joints."""
    return [b for (a, b) in cells[:-1]] if len(cells) > 1 else []


def verify_on_studs(cells, stud_xs, tol=1e-6):
    """Every internal joint sits on a stud line. The check the generator never had."""
    studs = sorted(set(float(s) for s in (stud_xs or [])))
    bad = []
    for j in joints_of(cells):
        if not any(abs(j - s) <= tol for s in studs):
            nearest = min(studs, key=lambda s: abs(s - j)) if studs else None
            bad.append({"joint_ft": round(j, 6),
                        "nearest_stud_ft": None if nearest is None else round(nearest, 6),
                        "off_by_in": None if nearest is None else round(abs(j - nearest) * 12.0, 3)})
    return bad
