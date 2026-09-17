# ORIGIN — Revit drywall automation

Turns a plain Revit `.rvt` environment into a per-room-ceilinged, drywall-panelled model ready
for USD export and Isaac Sim — driven from a terminal, without opening Dynamo or editing a
script between runs.

```
   your .rvt env
        |
        |  stage 1   per-room ceilings          (ceiling-rebuild/)
        v
   ceilings separated from the blanket
        |
        |  stage 2   panels, framing, soffits,  (pipeline/stage2_panels.py)
        |            columns, beams
        v
   drywall-panelled model -> USD -> Isaac Sim
```

## What's here

| Folder | Contents |
|---|---|
| `pipeline/` | The command line (`origin.ps1`), the in-Revit runner, the batch pipeline, the ceiling-direction rule, diagnostics |
| `ceiling-rebuild/` | The per-room ceiling rebuild — all the geometry logic, its own batch and live drivers, and the probes kept from working the problems out |
| `docs/` | `ORIGIN_COMMANDS.md` — the runbook |

## Quick start

Everything runs against the model open in Revit, through a Dynamo bridge node polling a
`command.json` file.

1. Open **Revit 2026** and open an environment.
2. **Manage → Dynamo** → open `pipeline/dynamo/ORIGIN Pipeline Bridge.dyn`, set run mode
   **Periodic** at **1000 ms**, leave it open.
3. From a terminal:

```powershell
.\origin.ps1 status        # is the bridge alive
.\origin.ps1 sep           # ceiling / wall separation
.\origin.ps1 panels        # drywall on walls + ceilings
.\origin.ps1 panels-all    # walls, ceilings, soffits, columns, beams
.\origin.ps1 all           # separation, then everything
```

Nothing is saved — the model changes in the open session and you save it yourself. Full
runbook in [`docs/ORIGIN_COMMANDS.md`](docs/ORIGIN_COMMANDS.md).

## The two rules worth knowing

**Ceiling heights come from each room's own walls.** A ceiling somebody dropped below the wall
top is kept as authored; everything else is recut to the room outline at the top of that room's
own bounding walls. Measuring per room rather than per level is deliberate — a perimeter room's
exterior wall runs to the roof while an interior room's partitions stop lower, so one height for
a whole floor is wrong for one of them either way.

**Ceiling panel direction comes from the site's main door.** Furring runs along the direction
you walk in through the widest door in the perimeter; boards run across it. The perimeter band
is adaptive rather than a fixed distance, because on a small plate a fixed band covers the whole
building and an interior door wins on width.

Both are documented in full in `docs/ORIGIN_COMMANDS.md` and `ceiling-rebuild/README.md`.

## Tests

Both rules can be exercised without Revit — the decision logic is pure Python and the Revit
imports are stubbed:

```powershell
python pipeline/test_ceiling_direction_offline.py     # 37 checks
python ceiling-rebuild/test_classifier_offline.py     # 24 checks
```

## Before you run this anywhere else

**Paths are hard-coded.** 29 of the 52 scripts contain absolute paths under
`C:\Users\Origoncad\`, pointing at three roots:

```
C:\Users\Origoncad\origin_pipeline
C:\Users\Origoncad\origin_ceiling_rebuild
C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces
```

They are load-bearing — the Dynamo bridge node has its folder baked in, and every script
`exec`s its dependencies by absolute path rather than importing them (deliberate: Dynamo caches
`sys.modules` across ticks and a stale module is a silent, expensive class of bug). Nothing
here will run on another machine until those are repointed.

**The drywall generators are not in this repo.** Stage 2 drives five generators
(`origin_wall_assembly_*`, `origin_ceiling_assembly_*`, `origin_soffit_assembly_*`,
`origin_column_assembly_*`, `origin_beam_assembly_*`) that live in a separate repository, and
`pipeline/stage2_panels.py` reaches them through the `REPO` constant at the top of the file.
This code never modifies them — where behaviour has to change, the relevant assignment is
rewritten in the generator's source *string* just before it is compiled.

**Environments are not in this repo either.** `.rvt` files are project data and are gitignored.

## Requirements

- Revit 2026 with Dynamo 3.6.2 (Python engine **CPython3** — `PythonNet3` fails before
  executing a line, with no log entry)
- Windows PowerShell 5.1 for the launchers
- Python 3 to run the offline tests
