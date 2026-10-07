# layout-bridge — build rooms live in Revit from a drawing

A second, separate Dynamo bridge (so it never collides with the pipeline's) for **authoring
layouts**: rooms traced from architectural PDFs are built directly into the open Revit model —
walls, doors, window openings, ceiling with air-device cutouts, floor, room — then checked by
geometry and saved. The output is meant to go through the panel pipeline and on to Isaac Sim.

```
layout-bridge/
  dynamo/ORIGIN_Layout_Bridge.dyn   polling node (CPython3, Periodic 1000 ms) -> bridge\ next to it
  send.ps1 <script.py>              write bridge\command.json (BOM-less), wait for result.json
  scripts/                          generic tools (below)
```

Room builds themselves (`scripts/layout_<room>_data.py` holding every dimension, and
`scripts/room_<room>_artifact.py` doing a one-pass, re-runnable build) are **not committed**:
their numbers are measured from client drawings. They stay on the build machine
(see `.gitignore`).

## Tools

| Script | Does |
|---|---|
| `probe.py` | Read-only: levels, wall / door / ceiling / floor types in the open model |
| `inventory.py` | Read-only: which layouts (by `ORIGIN_LAYOUT_<room>` Comments tag) the open model holds |
| `selected.py` | Read-only: what the user has selected (walls: length, height, thickness, type) |
| `list_walls.py` | Read-only: every wall with mark, comment, length, thickness and the z-levels of its solid |
| `list_views.py` / `open_view.py` | List 3D views / switch the UI to a named view (e.g. `ORIGIN Assembly`) |
| `diag_overlaps.py` | Read-only: pairwise solid intersection of every layout wall and DirectShape (must be empty) |
| `diag_wall_solids.py` | Read-only: one wall's solid edges - the real opening sizes Revit cut (`diag_wall_solids.json {"mark": ...}`) |
| `export_plan.py` | PNG of the L1 plan to `renders\` to check door swings without the user |
| `save_model.py` | Save; a never-saved model goes to `models\<name>.rvt` (`save_model.json {"name"}` or the doc title), never overwriting |

## Sim-ready wall rules (how a room is built)

Walls feed Isaac Sim, where any wall face hidden against another gets textured and the spray
robot cannot reach it. So:

1. **Square-cut corners.** Each wall spans exactly its own interior face, extruded outward, with
   joins disallowed at both ends (`WallUtils.DisallowWallJoinAtEnd`). Neighbours touch only along
   the inside corner line. (Revit's auto-join leaves 0 overlap volume but flush hidden faces.)
2. **Outside notches** are filled by separate **Generic Model DirectShape** corner blocks
   (L-shaped around a chase/column/pier) that touch only walls' outer end faces.
3. **In-room chases / columns / piers** are one solid no-join wall exactly filling the notch.
4. **Door cut = drawn opening.** `Door-Passage-Single-Flush` cuts its frame into the wall
   (+2" each side, +4" head), so the door type is sized (w-4) x (h-4).
5. **Prove it by geometry:** `diag_overlaps` empty, each wall's volume = length x thickness x
   height - openings, opening edges read back with `diag_wall_solids`, room area = source area.
6. **Save after every build** (`save_model.py`), one room per model.

## Known clash with the panel pipeline (2026-10-07)

- The wall generator deletes plain wall Openings (`REMOVE_MANUAL_CUTOUTS = True`), so window
  bands built as Openings are boarded over. Use a window family, or change that policy.
- Stage 1 (`origin sep` / `all`) deletes an authored ceiling that sits at the wall tops or has
  holes, and recuts it without the holes. Run only `origin panels` on these models.
See `claude/OPEN_ISSUES.md`.
