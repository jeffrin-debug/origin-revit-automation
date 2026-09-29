# Decision log

Newest first. Each entry: what the user asked (their words where it matters), what was built,
and anything that was reversed. Read this before "simplifying" a rule — several look arbitrary
until you see the case behind them.

## 2026-09-29 (env C9)

- **L-corner end studs inset** (`corner_end_studs.py`). C9 wall 004 × 002: the through wall's end
  stud, centred on the wall end, poked ⅝ in into the butting board's path; the stud-trim cut that
  board back 3 in and left the stud end exposed. User picked "pull wall 004 back" over moving
  wall 002's board (would float ⅝ in off its studs) or a return piece (panels still not meeting),
  and asked for the generator rule too. Fixed live in C9 (`corner_close_active.py` +
  `corner_close_butt_stud.py`, tagged `CORNER_CLOSED=2026-09-29`).
- **Sheets laid out between splits** (`wall_split_first.py`). C9 wall 037: a sliver DP-037-003A
  (1.37 in) left by the column trim beside a 64.5 in board that could have been one. User asked
  "why sep sep panels", then "do A and the generator change": merged live (`merge_pair_active.py`)
  and the generator's tile-then-split order changed. Not done yet (offered): re-running
  `wall_narrow_merge` after the columns step.

## 2026-09-26 … 09-28 (envs C9, 2C, 4D, B5)

- **Column stud wraps** — every exposed column face wrapped like a wall; wall boards stop where
  the column's panels meet them (replaces "board behind the column stays").
- **Ceiling holes from dropped thin pieces** fixed in the generator (thin strips absorbed, last
  course takes a bay) and **`ceiling_coverage_check.py`** added as a net for the next cause.
- **L-merge blocked only by real butt joints**, not by boards ending on the same line.
- **Collinear clamp = same line only**; **two collinear pieces at a crossing = one through wall**.
- **Narrow authored drops kept** in stage 1 when the room's probes miss them.
- `wall_narrow_merge` measures a board it already merged from the solid it built (Revit returned
  the stale shape and a 0–96 in board was deleted on 2C wall 029).

## 2026-09-25 (env 1F)

- **Drywall generators bundled into this repo** (`drywall-generators/`). They are the owner's
  own code; they had been kept out because every commit in their local folder carries the name
  "Keshubh" — that was only a repo-local git identity on this machine. `origin_paths` finds the
  bundled copy; stage 2 localises each generator's hard-coded `MANIFEST_PATH`.

- **Narrow wall boards merge into a neighbour** within one 4×8 sheet ("can we merge them whole
  with the neighbour panel which doesn't go more than 8 feet"). First version merged a board twice
  in one round using its stale shape and lost wall 010's bottom 4 ft of board — fixed (one merge
  per board per round, geometry re-checked). Wall 003 B boards were already split in two by a
  generator stud-trim slot; merges may carry an existing split but never add one.
- **16 in minimum between a joint and a wall**, ceilings first, then "also suit for walls".
  Layout-time rule plus a post-pass for ends the layout cannot see (T-junctions, trimmed ends).
- **Soffits raised to touch the ceiling** when they fall short ("move the soffit up and panelise
  it"). 1F: walls 006/007 raised 7¾ in (84 → 91¾ in base) to meet the 9 ft C007.
- **Height per room** chosen over "lower ceiling wins" (see below — reversed the same day). Needed
  two follow-ups: wall boards follow the ceiling per stretch (the generator's deferred per-cell
  cap), and a created-by-script tag on ceilings so the script's own ceilings are not kept as
  authored drops.
- **L-shaped ceiling boards allowed** where a seam is needless.
- **Stale ceiling assemblies purged** — found 58 elements left at 9 ft after a recut.
- **Soffit detection by shape** ("recognisable without saying it to claude").
- **Outside corners lap/butt** ("both has to be meetable panels") — reverses the generator's
  2026-08-07 "both end where they touch", which was chosen after an older wrap overlapped by t.
  Overlap scan confirmed zero overlap after the change.
- **"Lower ceiling wins"** (`FOLLOW_LOWER_AUTHORED_CEILING`) — the user first chose that created
  ceilings follow the level's lowest authored ceiling, to stop a wall face spanning two ceiling
  heights. **Reversed later that day** to height per room (above). Kept as an option.
- **Corner-infill strips folded into the neighbouring board**, redundant/doubled strips deleted.
- **Door head rows 4 + 2 + 4** for 8 ft doors; 7 ft doors keep 4 + 4 + 2 (confirmed correct).
- **Infill height bug** (base offset counted twice) fixed — surfaced when ceilings dropped to 8 ft.

## 2026-09-15 … 09-22 (earlier sessions)

- Per-face ceiling cap in the wall generator; per-cell cap deferred (now done, 2026-09-25).
- Wall joints must land on studs (`wall_joint_layout.py`, now in the generator as
  `course_cells_on_studs`).
- Ceiling direction from the main door; header fallback for door-less envs.
- All paths resolved at run time (`origin_paths.py`, `origin doctor`).
- The drywall generators were left out of this repo at first, on the mistaken belief (from the git
  author name) that they were a colleague's code — corrected 2026-09-25, see above.
