# ORIGIN — terminal commands

One bridge, one runner, four commands. Open an env in Revit, come to the terminal, type a line.

**Nothing below saves anything.** The model changes in the open Revit session; you look at it
and save it yourself. `pipeline.cmd` is still the batch, and it stays the only thing that
writes `.rvt` files.

---

## Before the first command (once per Revit session)

1. Open **Revit 2026** and open the env you want to work on.
2. **Manage → Dynamo** → open
   `C:\Users\Origoncad\origin_pipeline\dynamo\ORIGIN Pipeline Bridge.dyn`
3. Bottom-left of the Dynamo window: run mode **Periodic**, interval **1000 ms**.
4. Leave Dynamo open.

Then in the terminal:

```powershell
cd C:\Users\Origoncad\origin_pipeline
.\origin.ps1 status
```

`bridge : alive (doc 'YourEnv', view '{3D}', tick 412)` means you are ready.

> This is the **pipeline** bridge — the same one `pipeline.cmd` uses. The ceiling repo's own
> bridge is no longer needed for this flow; a command carries an absolute script path, so one
> bridge drives both repos.

---

## The commands

```powershell
.\origin.ps1 sep          # 1. ceiling / wall separation
.\origin.ps1 panels       # 2. drywall panels on walls + ceilings
.\origin.ps1 panels-all   # 3. drywall on walls, ceilings, soffits, columns, beams
.\origin.ps1 all          # 4. master - separation, then all five generators
```

| Command | What runs | Aliases |
|---|---|---|
| `sep` | Per-room ceiling rebuild: seals the perimeter, closes doorways, finds rooms, keeps the ceilings someone authored, deletes the blanket, cuts one ceiling per remaining room at that room's own wall top | `separation`, `ceiling` |
| `panels` | Wall generator, then ceiling generator | — |
| `panels-all` | walls → ceilings → soffits → columns → beams | `az` |
| `all` | `sep`, then all five generators | `master` |
| `status` | Is the bridge alive, and on which document | — |
| `doctor` | Check every path resolved correctly. **Run this first on a new machine** | — |

One generator at a time, when you are chasing something specific:

```powershell
.\origin.ps1 walls
.\origin.ps1 ceilings
.\origin.ps1 soffits
.\origin.ps1 columns
.\origin.ps1 beams
```

### Shorter typing

`origin.cmd` sits next to `origin.ps1`, so from that folder you can drop the `.\ .ps1`:

```powershell
origin sep
origin all
```

Add `C:\Users\Origoncad\origin_pipeline` to your PATH and it works from any folder.

---

## Your normal flow

```powershell
origin sep        # look at the ceilings in the ORIGIN Assembly 3D view
origin panels     # look at the boards
                  # happy? File > Save As in Revit
```

or, when you already trust it on this env:

```powershell
origin all
```

---

## Rules the runner enforces for you

- **Order is fixed, not what you typed.** Separation always runs before panels — the panel
  generators read the ceilings it builds. Walls always run before the other four; they own the
  corner and butt logic everything else measures against.
- **Separation failing stops the panels.** If the ceiling rebuild fails verification it is
  rolled back and no generator runs, so drywall can never be laid over a ceiling layout that
  did not verify.
- **Re-running is safe.** Panel output is tagged `ORIGIN_*_V1` DirectShapes, so a second run
  replaces rather than duplicates. Separation keeps ceilings that are already correct.
- **Ceiling panel direction is decided per env, from the site's main door.** You no longer set
  it by hand. See below.

---

## Ceiling panel direction

The rule, applied automatically on every env:

> **Furring runs ALONG the direction you walk in through the site's main door.**
> Boards run across it — boards always cross their framing.

How the main door is found:

1. Every `OST_Doors` element in the model.
2. A door is **exterior** when it sits within `nearest door's distance + 0.30 m` of the footprint
   boundary (capped at 2 m). The band is **adaptive on purpose** — a fixed 2 m band covers the
   whole of a small plate. On 1F (25 × 20 ft) it made all five doors look exterior and a door in
   the middle of the plan won on width.
3. Of those, the **widest** is the main entrance; distance breaks a tie between equal widths.
4. Its facing direction is the walk-in direction, snapped to the nearer world axis.

The run prints what it decided:

```
  panels     OK      41.7s
             targets: 72 walls, 12 ceilings
             ceiling direction: furring along Y, boards' long edge along X
             (FURRING_RUN_NS=False) - widest exterior door: 3000 mm wide,
             0.15 m from the edge, facing (0.0, 1.0) -> walk-in along Y
```

Things it will tell you rather than guess silently:

| Message | Meaning |
|---|---|
| `direction NOT applied: no OST_Doors elements…` | This env models doorways as bare gaps with a header wall above — there is no door to read. The generator keeps its own default; nothing breaks. |
| `! closest door is N m from the footprint edge` | No door is really in an exterior wall, so the pick is a guess. Worth a look. |
| `! main door faces N deg off the X axis` | The site is rotated. The grid is snapped to the nearer axis, which fits poorly past ~20°. |

Tuning lives at the top of `origin_pipeline\ceiling_direction.py` — `EDGE_CLUSTER_M` (0.30),
`EXTERIOR_BAND_M` (2.0 cap), `NO_PERIMETER_DOOR_M` (1.0) and `MIN_DOOR_WIDTH_FT` (2.0). Set
`CEILING_DIRECTION_FROM_DOOR = False` in `stage2_panels.py` to hand the generator back its own
hard-coded direction.

To see what it decided on any open model without changing anything:

```powershell
.\send_command.ps1 diag_doors.py
```

That lists every door with its width, position, facing and distance to the boundary, plus which
one won and why.

The drywall repo is **never modified** — the `FURRING_RUN_NS` assignment is rewritten in the
source string in memory, just before it is compiled.

---

## Reading the output

```
  ORIGIN  sep           doc: Project7.0018
  ------------------------------------------------------------
  ceiling    OK      3.1s
             12 rooms | 4 authored | 4 kept | 8 cut | 90 deleted (87 collateral) | 0.0 sf bare
  ------------------------------------------------------------
  nothing saved - File > Save As in Revit to keep this  (3.4s total)
  detail: C:\Users\Origoncad\origin_pipeline\_reports\live\Project7 0018_20260917_143210.json
```

| Number | Means |
|---|---|
| `rooms` | Enclosed regions found after sealing and closing doorways |
| `authored` | Rooms where somebody's dropped ceiling was kept — nothing new was built there |
| `kept` | Existing ceilings left untouched |
| `cut` | New ceilings cut out of the blanket to the room outline |
| `deleted` | Elements actually removed. **`collateral`** is everything beyond the ceilings asked for — mostly their own sketch lines, but check it if the env has recessed lights or diffusers |
| `bare` | Area left with no ceiling, under a partial authored drop. This area gets **no** ceiling drywall |

Full detail for every run lands in `origin_pipeline\_reports\live\`.

Add `-Raw` to any command to get the complete JSON instead of the summary:

```powershell
.\origin.ps1 sep -Raw
```

Long runs: the default wait is 30 minutes. Override with `-TimeoutSec`.

---

## When something goes wrong

| What you see | Cause / fix |
|---|---|
| `bridge is STALE by Ns` | Dynamo run mode fell back to Manual, or a model was opened in the UI. Set it back to Periodic. |
| `bridge is not running` | The graph was never started, or the node failed. Check `origin_pipeline\bridge\node_error.txt`. |
| `no result came back` | The node threw mid-command — `bridge\node_error.txt` has the traceback. |
| `panels SKIPPED` | Separation failed verification. The reason is printed above it, starting with `!`. |
| Grey patches that look like missing drywall | Judge the model in the **ORIGIN Assembly** 3D view only. In other views boards sit flush against the base wall and z-fight. |
| Edited a `.py` — restart? | No. The bridge re-reads every script from disk on each command. |
| Edited the `.dyn` | Close the graph in Dynamo choosing **Don't Save**, then reopen. Dynamo caches node code and writes the stale version back over your edit. |

---

## What sits behind this

| File | Role |
|---|---|
| `origin_pipeline\origin.ps1` | The command line — maps a verb to a step list, checks the bridge, prints the summary |
| `origin_pipeline\origin.cmd` | So you can type `origin sep` |
| `origin_pipeline\origin_run.py` | Runs inside Revit. Reads `_origin_cli.json`, runs the steps in canonical order on the open document |
| `origin_pipeline\stage2_panels.py` | Drives the five drywall generators |
| `origin_ceiling_rebuild\origin_ceiling_rebuild_core.py` | All the ceiling separation logic |
| `origin_pipeline\bridge\` | `command.json` out, `result.json` back, `heartbeat.json` proof of life |

---

*Written 2026-09-17.*
