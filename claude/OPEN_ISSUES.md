# Open issues and known limits

As of 2026-09-29 (1F, then C9); 2026-10-07 architecture review added below. Each has where to look.

## Found in the 2026-10-07 architecture review

First hit on a hand-built sim-ready room (`layout-bridge/`), run with `origin all`:

- **Wall generator deletes plain wall Openings** — `REMOVE_MANUAL_CUTOUTS = True`
  (`get_opening_rects`). A 3–7 ft window band cut as an Opening was deleted and the wall boarded
  full height. Candidate: treat Openings as openings instead of deleting them.
- **Stage 1 deleted an authored ceiling and dropped its holes** — the ceiling sat at the wall
  tops (drop 0 < 50 mm, so "top layer") and its three 2×2 diffuser holes made the net area 12 sf
  short of the room (tolerance 1.5 sf). The recut has no holes; 67 cascaded elements (sketches,
  Openings) were only logged as `collateral`. Candidates: compare outer area / treat probes in
  holes as covered, carry holes into the recut, fail on collateral Openings / FamilyInstances,
  provenance-based "authored" rule.
- **Stage 1 leaks SketchPlanes** (`seal_perimeter`, doorway closing) into committed models, and
  matching is 2D with no level filter (stacked storeys can turn one ceiling into a "blanket").
- **Soffit step undoes the ceiling fixes** — `origin_soffit_assembly_v1.py` re-collects
  soffit-named ceilings, deletes the ceiling generator's output (shared APP_ID) and rebuilds with
  the pre-08-06 logic (parallel furring, no curtain exclusion, no merges).
- **Silent patch skips** — any anchor-text change in a generator turns a patch into `skipped`
  and the run still succeeds; fix-pass exceptions do not fail the run either.
- **Ceiling board outside its ceiling** — per-room path emits whole boards "fully inside the
  room" without clipping to the ceiling outline (`board_fully_inside`), so a room under two
  ceilings at different heights gets sheets outside the ceiling.
- **Hardcoded env patch** in the wall generator (walls `008` / `010`, ~L5213) and C9 one-off
  scripts in `pipeline/` keyed to marks / element ids.
- **Legacy ceiling generators** (`origin_ceiling_assembly_v1.py`, `_noscrews.py`) share the
  live APP_ID; running an old Dynamo graph silently replaces live output.

## Defects

- **Generator stud-trim cuts a board in two** — wall 003 face B: every board has a 0.04 in slot
  (y ≈ 364.95–364.99 in) leaving a separate 0.5 in strip. Comes from the wall generator's
  `trim_drywall_from_neighbor_studs()` against wall 004's stud. Not fixed; `wall_narrow_merge`
  carries the split along rather than adding one.
- **Soffit side boards run into the ceiling slab** where the soffit's own Revit wall does
  (before the raise: 4¼ in into C001). Hidden, but extra material.
- **Column trim can leave a wall sliver** — columns run after `wall_narrow_merge`, so a board
  the column step cuts down to a few inches is never merged (C9 DP-037-003A, fixed by hand).
  `wall_split_first` removes the case where the joint was needless; a real joint just before a
  column can still leave one. Candidate: re-run `wall_narrow_merge` after columns.
- **T-stem end studs are still centred** on the through wall's face, so ⅝ in of flange sits in the
  through wall's board and core; the stud-trim notches that board (hidden inside the joint).
  `corner_end_studs` only changes L-corners.
- **C9 exposed studs** — `scan_exposed_studs.py` finds 15 on 10 walls (worst 403602: 4),
  2026-09-29, none yet looked at.
- **Generator changes of 2026-09-29 not yet run live** — `corner_end_studs` and
  `wall_split_first` are tested offline only; the next walls run on C9 replaces the hand fixes
  there with the generator's own output and shifts joints on faces with tees / ceiling breaks.

## Limits (by design, reported each run)

- **Narrow wall boards that cannot be helped** — bounded by an opening and a wall end/partition
  on both sides with no joint, and no neighbour that keeps one 4×8 sheet
  (1F: 013-004A, 013-003B, 014-003B, 016-004B, 016-005B). Listed in the run report under
  `wall_narrow_merge.left`.
- **Narrow ceiling COURSES** (a ripped last 4 ft row against a wall — 1F: DP-C001-004 10 in,
  DP-C003-005/006 3 in). Only a course under 3 in is fixed now (`course_bands` takes a 16 in
  bay); 3–16 in courses remain. Candidate next rule: shift the course start so both end courses
  are ≥ 16 in.
- **Fire-rated two-layer walls**: `door_head_courses` re-lays only the room-facing layer; the
  second layer keeps its 2 ft stagger, so both layers can share a 6 ft joint. No rated walls in
  1F.
- **Soffit-end sample in the fit check**: `diag_wall_ceiling_fit.py` flags one sample at x = 0 on
  soffit walls 006/007 — the junction with wall 005/006, covered by that wall's boards.
- **Ceiling rule is level-wide** when `FOLLOW_LOWER_AUTHORED_CEILING` is on (a 7 ft closet would
  pull every created ceiling on the level to 7 ft). Off by default now.
- The published copy of stage 1 in this repo is the one the pipeline uses; there is no separate
  "working copy" to keep in sync once this repo is the source.
