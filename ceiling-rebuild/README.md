# ORIGIN — per-room ceiling rebuild

Each env was authored with **one giant ceiling blanketing the whole floor plate** instead of one
ceiling per room. This fixes that: keeps any ceiling already correct for a room, builds one for
every room that lacks one, deletes the blanket. Originals are never modified — verified copies
are written to `out\`, and a file that fails verification is rolled back and not saved at all.

Standalone: its own bridge folder, its own Dynamo graph, its own copies of the geometry helpers.
Shares nothing with `origin_revit_drywall_scripts_v2_two_faces`.

---

# RUNBOOK — running this without Claude

## Step 1 — start Revit and the bridge (once per Revit session)

1. Open **Revit 2026** and open any model (the bridge just needs a live session).
2. **Manage → Dynamo** → open
   `C:\Users\Origoncad\origin_ceiling_rebuild\dynamo\ORIGIN Ceiling Bridge.dyn`
3. Bottom-left of the Dynamo window: set run mode to **Periodic**, interval **1000 ms**.
4. Leave Dynamo open. Check it is alive:

```powershell
Get-Content C:\Users\Origoncad\origin_ceiling_rebuild\bridge\heartbeat.json
```

The `tick` number must increase each second. If it does not, the run mode has dropped back to
Manual — set it to Periodic again.

## Step 2 — point it at your envs

Open `ceiling_rebuild_run.py` and set:

```python
INPUT_DIR = r"C:\Users\Origoncad\Downloads"      # folder holding the .rvt envs
SAVE      = True                                  # False = dry run, verify but write nothing
```

Discovery automatically skips Revit auto-backups (`name.0001.rvt`) and anything over 50 MB
(those are architecture reference models, not envs).

## Step 3 — run the batch

```powershell
cd C:\Users\Origoncad\origin_ceiling_rebuild
.\send_command.ps1 ceiling_rebuild_run.py -TimeoutSec 600
```

Roughly 3 seconds per env. Results:

* fixed models → `out\<env>.rvt`
* per-file detail → `out\_reports\<env>_rebuild.json`
* a summary table prints when it finishes

## Step 4 — check the summary

```
ok            21    saved and fully verified
failed         0    verification failed -> rolled back, NOT saved
errors         0    unexpected exception
quarantined    3    saved in Revit 2027, cannot open in the 2026 host
skipped        4    currently open in the Revit UI
```

Anything not `ok` was left alone. Nothing partially-applied ever reaches disk.

---

## Running one env live instead (to watch it happen)

1. Open the env in Revit.
2. Confirm `bridge\heartbeat.json` names that document.
3. Run:

```powershell
.\send_command.ps1 ceiling_rebuild_current_doc.py
```

The model changes on screen immediately. **Nothing is saved**, and **Ctrl+Z undoes the whole
rebuild in one step**. Set `DRY_RUN = True` in that file to report what it would do and touch
nothing.

---

## Things that will bite you

| Symptom | Cause / fix |
|---|---|
| `Bridge heartbeat is N s old` | Dynamo run mode fell back to Manual. Set it to Periodic again. |
| An env is `skipped (open in UI)` | A file open in Revit cannot be opened as a background document. Close it (Don't Save) and re-run. |
| `quarantined (saved in a newer Revit)` | The file is Revit 2027. Open Revit 2027, start the bridge there, and run the same scripts. |
| Batch freezes, Revit at 0% CPU | A modal dialog is waiting. The script auto-answers `Dialog_Revit_DocWarnDialog`; if a different one appears, click it and tell me which. |
| Edited a `.py` — do I restart? | No. The bridge re-reads the script file from disk on every command. |
| Edited the `.dyn` | Close the graph in Dynamo choosing **Don't Save**, then reopen. Dynamo caches node code and will write the stale version back over your edit. |

## Tunables — top of `origin_ceiling_rebuild_core.py`

| Setting | Meaning |
|---|---|
| `AUTHORED_DROP_MIN_MM` | 50 — a ceiling further than this below its room's wall top was dropped deliberately and is kept; nearer than this it is top-layer modelling noise |
| `ROOM_WALL_TOP_RULE` | `modal` (default) / `max` / `min` — how to reduce the tops of one room's bounding walls to a single height |
| `WALL_TOP_TOL_MM` | 1.0 — how close a cut ceiling must land to its room's wall top, and how far below it may sit at all |
| `DEFAULT_CEILING_HEIGHT_MM` | 2743.2 — last-resort fallback only, for a room with no wall and a level with no walls either |
| `PREFERRED_CEILING_TYPE_NAMES` | Type to use when the env has none of its own. Must have a compound structure — a "Generic" type builds a zero-thickness ceiling with no geometry |
| `AREA_MATCH_PCT` / `AREA_MATCH_ABS_SF` | How closely a ceiling must match a room to count as already correct (0.5%) |
| `MIN_REGION_SF` | Regions below this are flagged `tiny_region` but still get a ceiling |
| `INCLUDE_SOFFIT_CATEGORY` | Treat "Roof Soffits" elements as ceilings. Leave True — the blanket is often one |

---

# How it works

1. **Seal the perimeter.** These envs leak at the building edge, so Revit cannot enclose
   anything large — 13e (2) found 11 rooms totalling 159 sf of a 1002 sf plate. Temporary room
   separation lines are traced around the floor slab outline; rooms then close properly (13
   rooms, 945 sf). Where a real wall exists it still wins the boundary, so rooms keep stopping
   at wall finish faces. The lines are deleted afterwards.
2. **Close the doorways.** These envs model a doorway as a real gap in the wall with only a
   short header wall above it (813–1016 mm long, 2133.6 → 3048 mm). At the height Revit
   measures rooms there is nothing in the opening, so adjoining rooms merge into one region and
   share one ceiling. Those header walls are traced down to the measurement plane, which closes
   each opening exactly. Project1 went from 4 ceilings (one 529 sf blob) to 9.
3. **Find the rooms.** `NewRooms2` on each level classified as a real storey. A level is not a
   storey if it has no walls based on it, or only a small proportion of them — "Door Level"
   carries Revit's Building Story flag and has 11 real walls against the floor's 79. Get this
   wrong and it builds a duplicate set of ceilings stacked over the real ones.
4. **Measure each room's own wall top.** Taken from that room's boundary segments, so it is the
   walls the room actually stops against — not every wall on the level. Modal value in 5 mm
   buckets, so one odd wall cannot skew a room. This one number drives both rules below.
5. **Classify every existing ceiling** against the rooms, in two tiers:
   * more than `AUTHORED_DROP_MIN_MM` **below its own room's wall top** → a ceiling somebody
     dropped there on purpose → **keep, untouched**, whether it covers the whole room or only
     part of it;
   * **at** the wall top → part of the top layer. Kept only when it already is that room's
     ceiling *and* that room has no authored drop; otherwise **deleted** so the room is recut.

   A ceiling touching more than one room is the blanket and is **always deleted** — one element
   cannot be kept over the room that authored a drop and recut over the room next door.
6. **Cut one ceiling per uncovered room**, to that room's outline, at **that room's own wall
   top** — flush with where its walls end, never below them. Height is resolved per room, so two
   rooms on one level can legitimately finish at different elevations.

   A room that has an authored drop gets **nothing** created. Whatever area the drop leaves
   uncovered stays **bare by design**, reported as `bare_area_sf`.
7. **Verify, then save.** Nine checks — readable geometry, every room ending with the ceiling
   planned for it, no leftovers, full probe coverage of recut rooms, per-room area, the resolved
   per-room elevation, never below the room's wall top, not buried in a slab, and rooms covering
   at least 60% of the deleted blanket's area. Any failure rolls the whole file back.

## Files

| File | Purpose |
|---|---|
| `origin_ceiling_rebuild_core.py` | All the logic. Takes `doc` as an argument, so it behaves identically on a live or background document |
| `ceiling_rebuild_run.py` | **The batch.** Discovers envs, rebuilds, verifies, saves to `out\` |
| `ceiling_rebuild_current_doc.py` | Rebuild the model open in the Revit UI, nothing saved |
| `ceiling_audit_batch.py` | Read-only audit — reports what it *would* do |
| `send_command.ps1` | Drives the bridge from PowerShell |
| `ceiling_bridge.py` | Reference copy of the code embedded in the Dynamo node |
| `diagnose_*.py`, `probe_*.py` | Diagnostics kept from working the problems out |

## Notes for whoever maintains this

- `OfClass(Ceiling)` also returns **Roof Soffits** elements. The blanket is frequently one of
  those (12M_FR_11, 13e (2)). They are matched and deleted like ceilings but never used as a
  type source — a type cannot be assigned across categories, the set silently no-ops.
- The Dynamo node must use engine **CPython3**. Revit 2026.4 ships Dynamo 3.6.2, whose only
  Python engine is `DSCPython.dll`; a node set to `PythonNet3` fails before executing a single
  line, with no log entry.
- `command.json` must be written **without a UTF-8 BOM** or Python's `json.load` rejects it and
  the bridge ignores the command silently. `send_command.ps1` already handles this.
- Ceiling height **is** taken from the wall tops, as of 2026-09-17, but from **each room's own
  bounding walls** — never the level-wide modal wall top. That earlier rule is what put ceilings
  at 3048 mm inside the roof slab, invisible, while the real ceilings sat at 2743.2 mm: it let a
  perimeter room's exterior wall, which runs to the roof, set the height for the whole floor.
  Measuring per room keeps an interior room on its own partitions.
- Because of that, **V6 cannot fail a ceiling whose height came from real walls.** A perimeter
  room's ceiling legitimately lands at Roof Level now. V6 still guards the fallback paths, and
  V8 is what enforces "never below the wall top".
- A room can now legitimately be **partly bare** — that is the authored-drop rule, not a defect.
  V3 only requires full coverage of rooms that were recut. Watch `bare_area_sf` in the summary:
  that area gets no ceiling drywall in stage 2.
- The previous behaviour (one height per level, copied from the env's own correct ceilings) is
  in `_backups\origin_ceiling_rebuild_core.*.pre_authored_mode.py`.
