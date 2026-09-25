# Open issues and known limits

As of 2026-09-25, measured on 1F. Each has where to look.

## Defects

- **Generator stud-trim cuts a board in two** — wall 003 face B: every board has a 0.04 in slot
  (y ≈ 364.95–364.99 in) leaving a separate 0.5 in strip. Comes from the wall generator's
  `trim_drywall_from_neighbor_studs()` against wall 004's stud. Not fixed; `wall_narrow_merge`
  carries the split along rather than adding one.
- **Soffit side boards run into the ceiling slab** where the soffit's own Revit wall does
  (before the raise: 4¼ in into C001). Hidden, but extra material.

## Limits (by design, reported each run)

- **Narrow wall boards that cannot be helped** — bounded by an opening and a wall end/partition
  on both sides with no joint, and no neighbour that keeps one 4×8 sheet
  (1F: 013-004A, 013-003B, 014-003B, 016-004B, 016-005B). Listed in the run report under
  `wall_narrow_merge.left`.
- **Narrow ceiling COURSES** (a ripped last 4 ft row against a wall — 1F: DP-C001-004 10 in,
  DP-C003-005/006 3 in). The 16 in rule covers joints along a course, not the course width.
  Candidate next rule: shift the course start so both end courses are ≥ 16 in.
- **Fire-rated two-layer walls**: `door_head_courses` re-lays only the room-facing layer; the
  second layer keeps its 2 ft stagger, so both layers can share a 6 ft joint. No rated walls in
  1F.
- **Soffit-end sample in the fit check**: `diag_wall_ceiling_fit.py` flags one sample at x = 0 on
  soffit walls 006/007 — the junction with wall 005/006, covered by that wall's boards.
- **Ceiling rule is level-wide** when `FOLLOW_LOWER_AUTHORED_CEILING` is on (a 7 ft closet would
  pull every created ceiling on the level to 7 ft). Off by default now.
- The published copy of stage 1 in this repo is the one the pipeline uses; there is no separate
  "working copy" to keep in sync once this repo is the source.
