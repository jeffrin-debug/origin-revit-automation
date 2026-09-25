# Decision log

Newest first. Each entry: what the user asked (their words where it matters), what was built,
and anything that was reversed. Read this before "simplifying" a rule — several look arbitrary
until you see the case behind them.

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
