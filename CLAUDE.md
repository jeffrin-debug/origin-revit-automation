# CLAUDE.md — start here

You are working on **ORIGIN Revit drywall automation**: it turns a plain Revit `.rvt`
environment into a model with per-room ceilings and fully panelised drywall (walls, ceilings,
soffits, columns, beams) for USD export and Isaac Sim. It is driven from a terminal while the
model is open in Revit.

Read this file, then the one in `claude/` that matches the task:

| File | Read it when |
|---|---|
| [`claude/ARCHITECTURE.md`](claude/ARCHITECTURE.md) | You need to know what runs, in what order, and where a behaviour lives |
| [`claude/RULES.md`](claude/RULES.md) | You are changing how boards, ceilings, soffits or joints are laid out — every rule, its numbers, and **why** the user chose it |
| [`claude/WORKFLOW.md`](claude/WORKFLOW.md) | You need to run something, look at what the user selected in Revit, or verify a change live |
| [`claude/DECISIONS.md`](claude/DECISIONS.md) | Before reversing or "simplifying" a rule — the history, including rules that were tried and reverted |
| [`claude/OPEN_ISSUES.md`](claude/OPEN_ISSUES.md) | Picking up work — known defects and limits, with where they are |

## Hard rules (do not break these)

1. **The five drywall generators are NOT in this repo and must never be committed, vendored or
   published.** `origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py`,
   `origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py`, `origin_soffit_assembly_v1.py`,
   `origin_column_assembly_v1.py`, `origin_beam_assembly_v1.py` live in a colleague's separate
   repository (`origin_revit_drywall_scripts_v2_two_faces`). It is found at run time through the
   `drywall_repo` setting (`origin.config.json` / `ORIGIN_DRYWALL_REPO`), never a hard-coded path.
2. **Never edit a generator file.** To change generator behaviour, rewrite the relevant line in
   the generator's *source string* just before it is compiled — every `pipeline/*.py` module with
   an `apply_to_source(src)` does exactly this, and each checks its anchor text occurs exactly
   once (and skips, reporting why, if it does not). Or post-process the DirectShapes the generator
   made, after it runs (the `run(doc)` modules).
3. **Nothing saves the model.** Every command changes the open Revit session only; the user saves.
   Revit can crash — say so plainly if it does, because unsaved work is gone.
4. **Every rule is switchable** by a flag at the top of `pipeline/stage2_panels.py` (or in the
   ceiling core's `CFG`). Add a flag for any new rule.
5. **Verify, don't assume.** Offline tests first (`python pipeline/test_*_offline.py`), then a
   live run, then the diagnostics in `claude/WORKFLOW.md` — and run the pipeline twice to prove a
   rule is stable. Report what the checks actually showed.

## Layout

```
pipeline/            stage 2 (panels) + the CLI + every rule module + diagnostics + tests
  origin.ps1         the command line  (.\origin.ps1 all | panels | status | doctor ...)
  send_command.ps1   send ANY script to the live Revit session through the bridge
  origin_run.py      the one in-Revit runner behind every origin command
  stage2_panels.py   runs the five generators in order, applies every patch/post-pass
  origin_paths.py    resolves every path at run time (pipeline root, ceiling root, drywall repo)
  dynamo/            ORIGIN Pipeline Bridge.dyn - the polling bridge node
ceiling-rebuild/     stage 1: split the blanket ceiling into one ceiling per room
docs/                ORIGIN_COMMANDS.md - the user-facing runbook
claude/              this knowledge base
```

## Conventions

- Revit internal units are **feet**; reports and conversations use **inches / feet-inches**.
  Convert at the edges (`* 12`), never inside geometry code.
- Marks: walls `001..`, boards `DP-<wall>-<n><face A|B>`, framing `ST-<wall>-<n>`, ceilings
  `C001..`, ceiling boards `DP-C<nnn>-<n>`, soffit undersides `DP-<wall>-001U`, doors `DR-...`.
- Every generated element's Comments start with its generator's APP_ID
  (`ORIGIN_ASSEMBLY_V4 | WALL=W<eid> | ...`, `ORIGIN_CEILING_V1 | CEILING=C<eid> | ...`). The
  `WALL=W<eid> ` / `CEILING=C<eid>` token is the cleanup key — keep it on anything you create.
  Pipeline tags appended to Comments: `CORNERINFILL=1`, `INFILL_MERGED=`, `L_MERGED=`,
  `NARROW_MERGED=`, `END_JOINT_MOVED=`, `SOFFIT=1`, `SOFFIT_UNDERSIDE`.
  Ceilings created by stage 1 carry `ORIGIN_CEILING_REBUILD created`.
- Comment style: explain *why* and cite the case that motivated it (env, element marks, date).
  Match the density of the surrounding code.
- Scripts run inside Revit via PythonNet: `XYZ - XYZ` does **not** work — use `.Subtract()`,
  `.Add()`, `.Multiply()`. `from System.Collections.Generic import List` for `SetShape`.
- A module run from the bridge sets `OUT = {...}` (JSON-serialisable) as its result.

## Quick commands

```powershell
.\pipeline\origin.ps1 status             # is the Revit bridge alive, which doc
.\pipeline\origin.ps1 all                # ceiling split, then walls/ceilings/soffits/columns/beams
.\pipeline\send_command.ps1 diag_selected.py      # what the user has selected in Revit, in detail
python pipeline\test_wall_end_joints_offline.py   # any test_*_offline.py - no Revit needed
```
