# Layout rules — what they do, their numbers, and why

Each rule states the **user's direction** that set it. Flags live at the top of
`pipeline/stage2_panels.py` unless noted. Numbers are the defaults; each module keeps them as
named constants at its top.

---

## Ceilings

### Ceiling height = the room's own height
`ceiling-rebuild/origin_ceiling_rebuild_core.py`, `CFG["FOLLOW_LOWER_AUTHORED_CEILING"] = False`

- A ceiling a person dropped (> 50 mm below its room's wall top) is **kept** exactly as authored.
- Every ceiling the script creates sits at **its own room's bounding-wall top** (modal).
- Created ceilings are tagged `ORIGIN_CEILING_REBUILD created` in Comments. A tagged ceiling is
  never mistaken for an authored drop, and is recut if its room's target height changes.
- *Why*: "height per room" (2026-09-25). The alternative — every created ceiling follows the
  level's lowest authored ceiling — is still available (`FOLLOW_LOWER_AUTHORED_CEILING = True`)
  and was used for part of that day; see `DECISIONS.md`.

### Ceiling panel direction — from the main door
`ceiling_direction.py` (`CEILING_DIRECTION_FROM_DOOR`). Furring runs along the walk-in direction
through the widest perimeter door (or header opening, for door-less envs); boards run across it.

### No ceiling joint within 16 in of a wall — `ceiling_end_joints.py` (`END_JOINT_MIN_BAY`)
In each 4 ft course, where the course actually meets the room outline (so notches and L-rooms
count), an end piece shorter than **16 in** moves its joint inward by whole **16 in furring bays**
(the board grid and furring grid share an origin, so joints stay on a channel). Only if every
sheet stays ≤ 8 ft and the piece on the other side is ≥ 16 in; otherwise reported.
*Why*: 96 + 6.5 in in C007 put two taped seams almost on top of each other (2026-09-25).

### Rejoin needless seams, L-shapes allowed — `ceiling_l_merge.py` (`CEILING_L_MERGE`)
Two boards of one ceiling merge when they touch along the smaller board's **whole** edge, no wall
reaching the ceiling crosses the seam, the result fits **one 4 × 8 ft sheet**, and the union is
one solid. An L-merge never crosses a line where two other boards **butt each other** (a real
joint — would leave a stepped joint); a board that merely *ends* on the line at a wall face or the
ceiling outline does not block it (2026-09-28, C9: DP-C009-019 + -020 were kept apart only by
boards stopping at wall 401103's face). The generator's narrow-soffit boards (`DP-S…`) are left
alone.
*Why*: "we can have even L shaped panel where needed" — the wall-end split rule sliced C007
across the whole cell where soffit wall 006 ended (2026-09-25).

### No ceiling piece dropped for being thin — ceiling generator (`absorb_thin_pieces`, `course_bands`)
- A strip under the generator's 3 in floor is absorbed into the pieces along its long edge instead
  of being dropped (C9 C394087: a 48 × 2.5 in strip at the 017/042 wall corner was a hole).
- A last course under 3 in takes one 16 in bay from the course before it (`END_COURSE_MIN_FT`;
  2C C001: 48 + 48 + 48 left 0.87 in at wall 020 → 48 + 48 + 32.87 + 16).

### Every ceiling proven fully boarded — `ceiling_coverage_check.py` (`CEILING_COVERAGE_CHECK`)
Read-only, after any run that touches ceilings/soffits/columns/beams: each ceiling is sampled on a
**1 in** grid and any point no room-facing (L0) board covers is reported as a gap (walls reaching
the ceiling, columns + wraps, beams, hosted fixtures and soffit ceilings are left out by design).
Shown as `! CEILING GAPS` in the summary and in review; a warning, not a failure.
*Why*: the generator's "too small, drop it" paths each left holes the user found by eye
(2026-09-28); this is the net under the next cause.

### A narrow authored drop is kept even when the room's probes miss it — stage 1
`match_ceilings_to_regions`: a ceiling that overlaps no region by the room's own probes is probed
from its own outline before being called a stray. *Why*: C9 C393197, a 25 in × 10 ft bulkhead in
a 377 sf room, fell between the room's 9 probes and was deleted (2026-09-28).

### Stale ceiling assemblies are purged — `_purge_orphan_ceiling_assemblies`
Ceiling-generator output whose `CEILING=C<eid>` no longer exists is deleted before the ceiling
generator runs. *Why*: stage 1 recuts ceilings with new ids; 58 old boards were left floating.

---

## Walls

### Board rows 4 + 4 + … from the floor; 4 + 2 + 4 near a door head — `door_head_courses.py`
Default rows are 4 ft from the floor (7 ft door: head inside the 4–8 row — correct). If any door
head (with trim + clearance) lands within **0.5 ft** of a row joint, that face is hung
**4 + 2 + 4 (+4…)** ft so the head sits inside a full sheet. Doors only; room-facing layer only.
*Why*: 8 ft door's head was 3.6 in above the 8 ft joint (2026-09-25).

### Wall boards follow the ceiling above each stretch — `wall_ceiling_profile.py` (`WALL_CAP_PER_STRETCH`)
Each face's ceiling is probed every 0.5 ft (0.75 ft off the face, the generator's own probe) and
each change located by bisection. The top course breaks where the height changes and every board
stops at the ceiling over **its own** stretch. A no-ceiling stretch shorter than 1 ft (probe past a
corner) takes its neighbours' lower height. The generator's "ceiling < 1 ft above base = bad data"
floor still applies, except on soffit walls.
*Why*: the generator capped a whole face at its lowest ceiling — wall 008 face A had bare studs
8–9 ft under the 9 ft ceiling (2026-09-25).

### Outside corners: one board laps, one butts — `corner_lap.py` (`OUTSIDE_CORNER_LAP`)
The through wall (higher ElementId — the generator's tiebreak) laps **hwO** past the corner to
the other wall's outer face; the other butts **hwO − t** against its back. Zero overlap.
*Why*: "both has to be meetable panels" — both ended at the centreline, leaving 2⅜ / 1⅞ in open.
This replaced the generator's 2026-08-07 rule "both end where they touch"; the overlap scan
(`diag_board_overlaps.py`) is the guard against the old t-sized overlap returning.
In the generator (2026-09-28): the collinear-wall clamp only applies to a wall **on the same line**
(not any parallel wall — 2C wall 003, 40 in away, cancelled 14 corner wraps), and two collinear
walls both ending at a crossing from opposite sides are treated as **one through wall** (a T),
each face butting the piece on its side.

### L-corner end studs sit inside their own run — `corner_end_studs.py` (`CORNER_END_STUDS_INSET`)
The generator centres an end stud on the run end, so half a flange (**⅝ in**) poked past it. At an
L-corner framing now stops: through wall — end stud's outer flange **t (½ in)** behind the other
wall's outer face, so the butting board runs on to the lap; butting wall — end stud flush at the
through wall's near face. T-joins and free ends keep the centred stud. Moves the through wall's
16 in grid by 1⅛ in.
*Why*: C9 wall 004 × 002 (2026-09-29) — ST-004-001's overhang made the stud-trim cut DP-002-001A/002A
back 3 in, exposing the stud; "those 2 has to meet by attaching their ends".

### No wall joint within 16 in of an end — `wall_end_joints.py` + `wall_end_joint_fix.py`
- During layout: if the piece at either face end is < **16 in**, its joint moves to the nearest
  **stud line** that leaves it ≥ 16 in, the other piece ≥ 16 in, the sheet ≤ 8 ft, and the joint
  ≥ **4 in** from a door/window jamb. A course split (tee / ceiling break) is never moved.
- After layout, on finished boards: same rule where the "end" is a wall butting in, an opening,
  or an end board the generator later trimmed. The strip moves from neighbour to short board by
  booleans; both must stay single solids.
*Why*: same seam-too-close problem as ceilings, "also suit for walls" (2026-09-25).

### Sheets are laid out between splits, not across them — `wall_split_first.py` (`WALL_SPLIT_FIRST`)
Each course is cut at its splits (partition tees, ceiling-height breaks) first — same ≥ 6 in
confetti merge as the generator — then `course_cells_on_studs` lays sheets out in each span. A span
that fits one 8 ft sheet is one board. No splits → exactly the generator's layout.
*Why*: C9 wall 037 face A (2026-09-29) tiled 3–96 + 96–125.5 in, then split at the 31.5 in tee,
so 31.5–125.5 (94 in) came out as two boards; the K004 column then cut the second to 1.37 in.
"it can be a single panel".

### Narrow boards with no joint → merge into a neighbour — `wall_narrow_merge.py`
A board < 16 in with nothing to move merges with a **same-plane** neighbour (same row, the board
above/below — e.g. over a door — or a board on a collinear wall) that touches its whole edge, if
the result fits **one 4 × 8 sheet**; smallest result wins. One merge per board per round, geometry
re-checked before each merge, rounds repeat until stable. A seam that Revit's union will not fuse
is bridged by a 0.02 in slab that must add no volume.
*Why*: "can we merge them whole with the neighbour panel which doesn't go more than 8 feet".

### Corner-infill strips — `infill_merge.py` (`MERGE_CORNER_INFILL`)
The generator patches exposed studs with stud-shaped strips (`CORNERINFILL=1`). The pipeline
deletes strips that sit ≥ 50 % inside other drywall (redundant / doubled), and folds the rest into
the coplanar board beside them (extending it) when that board covers the strip's full height.
*Why*: "why do we need a separate part for it, can't we hide it with the drywall panel".

### Corner-infill height bug — `infill_z_fix.py` (always on)
The generator built infill candidates `wstart.Z` too high on any wall with a base offset; fixed by
measuring the patch rect from the origin. *Why*: 22 strips floated at 14–15 ft over walls 006/007.

---

## Columns — `drywall-generators/origin_column_assembly_v1.py`

Every column face exposed to a room gets a **stud wrap** — 3⅝ in C studs at 16 in OC between
tracks, ½ in board in 4 ft courses, joints on studs: the wall generator's rules, set outside the
column (the column is never changed). Faces flush against a wall/column are not wrapped. E/W faces
run through the corner, N/S butt; a return board closes a wrap end a wall does not hide. The wrap
stops at the ceiling over it (framing too). Wall and ceiling pieces intruding into a column or its
wrap are cut back to it, pieces wholly inside removed; wall boards flat against a covered column
face stop at the wrap's outer face. Columns run after walls and ceilings — re-running those alone
puts the overlap back until columns run again. *Why*: user direction 2026-09-28 (C9, B5 K002).

---

## Soffits — `soffit_detect.py` (`DETECT_SOFFIT_WALLS`)

### Detection by shape, not name
A wall is a soffit when: base ≥ **6 ft** above its level, height ≤ **3 ft**, no door/window, no
wall under > 20 % of its footprint, and a ceiling's underside lies between its base and top — or
up to the **2 ft** raise limit above it. The generator's own `Generic - 2'` band walls are left to
its soffit flow. *Why*: "in upcoming envs those kind of soffit should be recognisable without
saying it" — 1F's soffit was two ordinary partitions.

### Raise to touch the ceiling
If a ceiling beside a soffit (either face) sits above its top, the wall is **moved up** (base
offset, and top offset if the top is level-constrained) by the gap. Only if its bottom stays ≥ 1 in
below every neighbouring ceiling and the move is ≤ 2 ft. Previous offsets are in the report.
*Why*: "if any soffit doesn't touch the ceiling and forms some gap we need to move the soffit up".

### Panelise
Each soffit face stops at its own ceiling; one underside board spans outer face to outer face
(cut against the other soffit at a corner and neighbouring walls' framing); side boards tagged
`SOFFIT=1`.
