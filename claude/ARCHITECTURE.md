# Architecture

## How a command reaches Revit

```
terminal ── origin.ps1 / send_command.ps1
               │ writes bridge\command.json  {id, script, transaction}
               ▼
Revit + Dynamo ── ORIGIN Pipeline Bridge.dyn (Periodic, 1000 ms)
               │ sees a new id → exec(script) against the open document
               │ writes bridge\result.json  {id, ok, out | error}
               │ writes bridge\heartbeat.json every tick  {time, doc, view, selection_count}
               ▼
terminal reads result.json for that id
```

- `send_command.ps1 <script.py>` runs **any** script (absolute or pipeline-relative) and prints its
  `OUT`. It refuses if the heartbeat is older than 30 s. A **blank** heartbeat or a stale one
  means Dynamo/Revit stopped — check `Get-Process Revit` and the Revit journal
  (`%LOCALAPPDATA%\Autodesk\Revit\Autodesk Revit 2026\Journals`).
- `origin.ps1 <command>` writes `_origin_cli.json` (`{"command", "steps"}`) and sends
  `origin_run.py`, which runs the steps in canonical order and writes a report to
  `pipeline/_reports/live/<doc>_<timestamp>.json` (git-ignored). Its printed summary is a slim
  version; the full detail is in that report.
- Offline tests import modules directly with plain CPython (Revit namespaces stubbed) — they
  never need the bridge.

## Stage 1 — ceilings per room (`ceiling-rebuild/origin_ceiling_rebuild_core.py`)

Places temporary rooms, classifies every existing ceiling (`match_ceilings_to_regions`), deletes
blankets/strays, creates one ceiling per room that needs one, removes the temporary rooms, then
runs its own verify checks (V1–V8). See `claude/RULES.md` → *Ceiling height*.

## Stage 2 — panels (`pipeline/stage2_panels.py`, `run_on_document`)

The generators run in this order; for each, the pipeline patches the source string, execs it,
then runs its post-passes. **Order matters** — later steps measure against earlier output.

| # | Step | Module | Kind |
|---|---|---|---|
| **walls** — before the generator |
| 1 | Raise any soffit that falls short of the ceiling beside it | `soffit_detect.raise_to_ceiling` | edits Revit walls |
| 2 | Hand the soffit wall ids to the generator (`ORIGIN_SOFFIT_WALL_IDS`) | `soffit_detect.soffit_wall_ids` | namespace |
| **walls** — source patches, then exec |
| 3 | Corner-infill patch built at the wrong height on raised walls (base offset counted twice) | `infill_z_fix` | bug fix, always on |
| 4 | Wall boards follow the ceiling over each STRETCH of a face | `wall_ceiling_profile` | patch |
| 5 | Outside corners: one board laps, the other butts behind it | `corner_lap` | patch |
| 6 | Door head near a row joint → rows 4 + 2 + 4 ft | `door_head_courses` | patch |
| 7 | No joint within 16 in of a face end (joint moved to a stud) | `wall_end_joints` | patch |
| **walls** — post-passes on the finished boards |
| 8 | Delete redundant corner-infill strips; fold the rest into the board beside them | `infill_merge` | post-pass |
| 9 | Joints still < 16 in from a hard end (T-junctions, trimmed ends) → move to a stud | `wall_end_joint_fix` | post-pass |
| 10 | Narrow boards with no joint → merge into a same-plane neighbour if one 4×8 sheet | `wall_narrow_merge` | post-pass |
| 11 | Soffit walls → underside board + `SOFFIT=1` tags | `soffit_detect.run` | post-pass |
| **ceilings** — before / patches / exec |
| 12 | Delete ceiling-generator output whose ceiling no longer exists | `stage2_panels._purge_orphan_ceiling_assemblies` | cleanup |
| 13 | Furring/board direction from the main door | `ceiling_direction.apply_to_source` | patch |
| 14 | No joint within 16 in of a wall (joint moved by whole furring bays) | `ceiling_end_joints` | patch |
| **ceilings** — post-pass |
| 15 | Rejoin boards split with no wall on the seam, L-shapes allowed, one 4×8 sheet | `ceiling_l_merge` | post-pass |
| **soffits, columns, beams** | generators run as-is |

Patch modules expose `apply_to_source(src) -> (src, info)` and often `collect(ns, info)` to pull
what they recorded out of the generator's namespace (e.g. `_ORIGIN_END_JOINTS`). Post-pass
modules expose `run(doc, ...) -> report`, open their own transaction via `TransactionManager`,
and do each change inside a `SubTransaction` that is rolled back unless every check passes.
Every step's report lands in the run report under its own key (`soffit_raise`,
`wall_end_joints`, `wall_end_joint_fix`, `wall_narrow_merge`, `infill_merge`,
`ceiling_end_joints`, `ceiling_l_merge`, `orphan_ceiling_assemblies`, ...).

## Paths

`origin_paths.py` resolves everything from its own file location: `PIPELINE_ROOT`,
`CEILING_ROOT` (sibling folder named `ceiling-rebuild` / `ceiling_rebuild` /
`origin_ceiling_rebuild`), and `DRYWALL_REPO` from `ORIGIN_DRYWALL_REPO`, `origin.config.json`,
then the bundled `drywall-generators/` beside `pipeline/`. Run `.\pipeline\origin.ps1 doctor` on a new machine. Tests that patch a
generator (`test_wall_*`, `test_door_head_*`, `test_ceiling_end_joints_*`) need `DRYWALL_REPO` to
resolve; the others do not.

## Manifests

Each generator writes a JSON manifest into the drywall repo folder. Its `MANIFEST_PATH` is
hard-coded to the machine it was written on; stage 2 rewrites it to the folder this run resolved
(`_localise_manifest_path`, reported as `manifest_paths`), so it works on any machine
(`origin_assembly_manifest_notaper_noscrew_nojoint.json`, `origin_ceiling_manifest_...json`, ...).
Post-passes that remove or reshape boards update it (`infill_merge`, `ceiling_l_merge`,
`soffit_detect`). Note the wall generator's own post-passes (stud trimming) do NOT update board
x-ranges in the manifest — trust live geometry over manifest extents.
