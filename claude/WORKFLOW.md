# Working with the live model

## Before anything

```powershell
.\pipeline\origin.ps1 status        # heartbeat age, document, view, selection count
.\pipeline\origin.ps1 doctor        # every path resolved (first run on a new machine)
```

The bridge must be open in Dynamo (`pipeline/dynamo/ORIGIN Pipeline Bridge.dyn`, Periodic).
If `send_command.ps1` fails reading the heartbeat, or the heartbeat is blank/stale, Revit or
Dynamo stopped — ask the user to reopen the model and restart the bridge. Unsaved changes are
lost when Revit goes down; the pipeline rebuilds everything in one run.

## "I have selected …" — always read the selection first

```powershell
.\pipeline\send_command.ps1 diag_selected.py
```
Returns each selected element's mark, category, Comments (host, face, tags), exact solids, bbox
in inches, and every DirectShape within 1 in (`touching`). Answer from this, not from a guess.

## Running

```powershell
.\pipeline\origin.ps1 all          # stage 1 + all five generators + every pass
.\pipeline\origin.ps1 panels       # walls + ceilings only
```
Run it **twice** after any rule change: the second run must report the same moves/merges and
create/delete no ceilings (`ceiling kept N, created 0`) — anything else means a rule is not stable.

## Checks (all read-only)

| Script | What it proves |
|---|---|
| `diag_board_overlaps.py` | No two drywall boards interpenetrate (boolean intersect, not bbox). Must be **0** |
| `diag_wall_ceiling_fit.py` | Every wall face has board up to the ceiling over each stretch, none past it. Junction-end single samples at soffit ends are a known artefact |
| `diag_narrow_boards.py` | Wall boards < 16 in along the wall; ceiling boards < 16 in along the run; narrow ceiling courses |
| `diag_door_sizes.py` / `diag_door_layout.py` | Door sizes; studs & boards around one door (`DOOR_ID` at top) |
| `diag_doors.py` | Every door and which one drives the ceiling direction |
| `diag_beams.py` | Beams and their boards' gaps/overlaps |
| `merge_infill_active.py` | `DRY_RUN = True`: list every corner-infill strip and what the merge would do |

Write a throw-away probe in the session scratchpad (not the repo) for one-off questions, and
send it with `send_command.ps1 <absolute path>`.

## Changing a rule

1. Find the module in `claude/ARCHITECTURE.md`. If it is a generator behaviour, add/modify an
   `apply_to_source` patch — anchor on exact text, require exactly one match, skip with a reason
   otherwise. Never edit the generator repo.
2. Keep the rule's numbers as named constants and add a stage-2 flag.
3. Add or update its `test_*_offline.py` — real numbers from the case that motivated it, plus the
   cases that must NOT change.
4. Run it live twice, then the checks above. Report measured results, and anything left unfixed
   with the reason the module recorded.
5. Record the decision in `claude/DECISIONS.md` and the rule in `claude/RULES.md`.

## Offline tests

```powershell
Get-ChildItem pipeline\test_*_offline.py | ForEach-Object { python $_.FullName | Select-Object -Last 1 }
python ceiling-rebuild\test_classifier_offline.py
```
All pass as of 2026-09-25 (208 checks). The generator-patching tests need `DRYWALL_REPO`.
