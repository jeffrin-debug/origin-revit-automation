# ORIGIN env pipeline

Turns a plain `.rvt` env into a drywall-panelled env ready for sim, in two stages, without
anyone needing to open Dynamo, edit a script, or ask Claude.

```
   your .rvt env
        |
        |  stage 1   per-room ceilings          (origin_ceiling_rebuild)
        v
   01_ceiling_done\<env>.rvt
        |
        |  stage 2   panels, framing, soffits,  (origin_revit_drywall_scripts_v2_two_faces)
        |            columns, beams
        v
   02_panels_done\<env>.rvt
        |
        |  you look at it in Revit and approve
        v
   03_sim_ready\<env>.rvt        -> USD export -> Isaac Sim
```

The source `.rvt` is never written to. Every stage verifies before it saves, and a file that
fails is rolled back and not saved at all — so a folder only ever contains files that passed.

---

# RUNBOOK

## Step 1 — start Revit and the bridge (once per Revit session)

1. Open **Revit 2026** and open any model. The bridge just needs a live session; the envs
   themselves are opened in the background.
2. **Manage → Dynamo** → open
   `C:\Users\Origoncad\origin_pipeline\dynamo\ORIGIN Pipeline Bridge.dyn`
3. Bottom-left of the Dynamo window: run mode **Periodic**, interval **1000 ms**.
4. Leave Dynamo open.

The launcher shows `Bridge : alive` at the top when this is done. If it says `STALE`, the run
mode dropped back to Manual — set it to Periodic again.

## Step 2 — run the pipeline

Double-click **`pipeline.cmd`**.

```
  ORIGIN ENV PIPELINE
  ===================

  Source : (none chosen)
           0 env(s) queued
  Bridge : alive (doc 'Project1')

   1) Choose source file or folder
   2) Run  ceilings + panels      (the full flow)
   3) Run  ceilings only
   4) Run  panels only            (on 01_ceiling_done)
   5) Review finished files       -> approve / reject
   6) Promote approved            -> 03_sim_ready
   7) Status
   8) Verify stage 2 on one file  (nothing saved)
   9) Open the output folders
   Q) Quit
```

Normal use is **1 → 2 → 5 → 6**.

`1` opens a file picker — pick one `.rvt`, several, or a whole folder. Revit auto-backups
(`name.0001.rvt`) and anything over 50 MB are ignored automatically; in `Downloads` those are
architecture reference models, not envs.

Revit is busy while a run is going. Ceilings take about 3 s per env; panels are much heavier.

## Step 3 — look at the results

Menu `5` walks the finished models one at a time, printing the warning counts for each, and
offers **[O] open in Revit / [A] approve / [R] reject**.

Judge the model in the **ORIGIN Assembly** 3D view. In any other view the boards sit flush
against the base wall and z-fight — random grey patches that look like missing drywall but
are only a display artifact.

> Opening a model in Revit makes it the active document, which **stops the bridge**. Finish
> reviewing, then reopen the graph before the next run.

Rejected files stay in `02_panels_done` so you can look again or re-run them.

## Step 4 — promote

Menu `6` moves everything approved into `03_sim_ready`. That folder is the pipeline's output —
it is what goes on to USD export and Isaac Sim.

---

## Before the first real batch: menu 8

Stage 2 had never run on a background document before this pipeline existed. Menu `8` opens
one env in the background, runs the panel generators against it, reports what they built, and
closes **without saving**.

The number to look at is `directshapes_in_background_doc_by_mark_prefix`. Boards and studs
counted there mean the generators really did write into the background document. If the
injection had failed they would have written into the model open in the UI and that count
would be zero.

Change `TARGET` at the top of `verify_stage2.py` to test a different env, or set
`ONLY = ["walls"]` to run a single generator while shaking something out.

---

## Things that will bite you

| Symptom | Cause / fix |
|---|---|
| `Bridge : STALE by Ns` | Dynamo run mode fell back to Manual, or a model was opened in the UI. Set it to Periodic again. |
| An env is `skipped (open in UI)` | A file open in Revit cannot be opened as a background document. Close it (Don't Save) and re-run. |
| `quarantined (saved in a newer Revit)` | The file is Revit 2027. Open Revit 2027, start the bridge there, run the same flow. |
| Run freezes, Revit at 0% CPU | A modal dialog is waiting. The pipeline auto-answers the ones it knows; if a different one appears, click it and note which. |
| `ceiling failed - rolled back` | Verification rejected the rebuild. `_reports\<env>_pipeline.json` has `fail_reasons`. Nothing was saved. |
| `panels failed` | A generator raised. `_reports\<env>_pipeline.json` → `panels.generators.<name>.FATAL` has the traceback. Nothing was saved. |
| Edited a `.py` — restart? | No. The bridge re-reads every script from disk on each command. |
| Edited the `.dyn` | Close the graph in Dynamo choosing **Don't Save**, then reopen. Dynamo caches node code and writes the stale version back over your edit. |

---

## What is where

| Path | Purpose |
|---|---|
| `pipeline.cmd` | **Double-click this.** |
| `pipeline.ps1` | The menu, the ledger, review and promote. Never touches Revit directly. |
| `pipeline_run.py` | Runs inside Revit: per env, one background open, stage 1 → stage 2 → save. |
| `stage2_panels.py` | Stage 2 — drives the five drywall generators against a given document. |
| `verify_stage2.py` | The menu-8 check. Opens one env, runs panels, saves nothing. |
| `send_command.ps1` | Drives the bridge from PowerShell. Writes `command.json` BOM-less. |
| `_run_config.json` | Written fresh by the launcher before each run — the file list and stages. |
| `ledger.json` | Per-env state: ceiling, panels, review, promoted. |
| `_reports\<env>_pipeline.json` | Full detail for one env, both stages. |
| `_reports\<env>_manifests\` | That env's generator manifests, copied aside so a batch does not leave only the last env's diagnostics. |
| `_logs\run_*.json` | Raw `result.json` of every run. |

## How stage 2 reaches a background document

The five generators were written to work on whatever model is open in the Revit UI:

```python
doc = DocumentManager.Instance.CurrentDBDocument
```

Each now takes an injected document when the pipeline provides one, and is otherwise
completely unchanged — so opening the graph in Dynamo by hand still behaves exactly as before:

```python
_origin_target_doc = globals().get("ORIGIN_TARGET_DOC")
doc = _origin_target_doc if _origin_target_doc is not None else DocumentManager.Instance.CurrentDBDocument
```

The elements are passed in as `IN[0]` rather than through the Revit selection. That part is not
a convenience: the selection belongs to the **active** document, and feeding those element ids
to a background document resolves them against whatever unrelated elements happen to share
those id numbers.

Originals of the five files, as they were before this edit, are in
`_backups\pre_doc_injection\`. The drywall repo had uncommitted work in three of them at the
time, so the change was deliberately **not** committed — `git diff` there shows this edit mixed
in with that work in progress.

## Notes

- Everything runs in **Revit 2026** — the version the ceiling stage is verified on, and the only
  one with the Omniverse connector installed, so the same session carries through to USD export.
- The Dynamo node must use engine **CPython3**. Revit 2026.4 ships Dynamo 3.6.2, whose only
  Python engine is `DSCPython.dll`; a node set to `PythonNet3` fails before executing a single
  line, with no log entry.
- `command.json` and `_run_config.json` must be written **without a UTF-8 BOM** or Python's
  `json.load` rejects them and the command is ignored silently. The launcher handles this.
- Stage 2 never runs on a document whose stage 1 failed verification, so a ceiling problem can
  never be papered over with drywall.
