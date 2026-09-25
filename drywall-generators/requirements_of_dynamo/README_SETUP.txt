ORIGIN BRIDGE - SETUP ON A NEW MACHINE
========================================

WHAT'S IN THIS FOLDER
----------------------
dynamo\ORIGIN Bridge.dyn          - the live bridge listener graph (must be opened + run in Dynamo)
origin_revit_bridge.py            - reference copy of the bridge listener's code (for editing/history only -
                                     the .dyn file carries its OWN baked-in copy of this code; editing this
                                     .py file does NOT change what the .dyn runs)
origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py    - wall generator (studs/track + drywall)
origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py        - ceiling generator (furring/mains + drywall)
origin_soffit_assembly_v1.py                                 - soffit generator
origin_beam_assembly_v1.py                                   - beam drywall-wrap generator
origin_column_assembly_v1.py                                 - column drywall-wrap generator
origin_bridge_run_all.py          - runs walls -> ceilings -> soffits -> columns -> beams, in order
origin_bridge_run_walls.py        - runs the wall generator on every wall in the model
origin_bridge_run_ceiling_only.py - runs ONLY the ceiling generator (not soffits)
origin_bridge_run_soffit_ceiling.py - runs ceilings then soffits together
origin_bridge_run_soffit.py       - runs only the soffit generator
origin_bridge_run_columns.py      - runs only the column generator
families\TM_outlet_box.rfa, TM_outlet_box_ef.rfa - outlet families (optional - auto-created if missing)

NOT INCLUDED (needed separately)
----------------------------------
- The actual .rvt Revit project file.
- Revit itself (target version: 2027) with Dynamo for Revit available.

SETUP STEPS
-----------
1. Copy this whole folder to the new machine.

2. IMPORTANT - HARDCODED PATHS: every script above hardcodes the absolute path
   C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\...
   (both the folder location AND the Windows username "Origoncad").

   EASIEST: on the new machine, log in as a user also named "Origoncad" and place this folder
   at the exact path:
       C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\requirements_of_dynamo
   Then nothing needs editing.

   IF THE USERNAME OR PATH MUST DIFFER: you must edit the hardcoded path in:
     - origin_revit_bridge.py               -> BRIDGE_DIR constant near the top
     - every origin_bridge_run_*.py          -> REPO constant near the top
     - each generator script                 -> MANIFEST_PATH constant (and OUTLET_RFA_PATH in
                                                 the wall generator)
   AND you must re-paste the corrected code into the Python node inside
   dynamo\ORIGIN Bridge.dyn itself (the .dyn does not read origin_revit_bridge.py live - it only
   carries its own embedded copy of that code, created when the node was last edited/saved).

3. Open the target .rvt project in Revit.

4. Open Dynamo (Manage tab -> Dynamo), then open dynamo\ORIGIN Bridge.dyn.

5. Set the run-mode selector (bottom-left of the Dynamo window) to PERIODIC, interval ~1000 ms,
   and leave Dynamo running. Closing Dynamo or switching to a different graph stops the bridge.

6. The bridge folder (bridge\command.json / result.json / heartbeat.json) does NOT need to be
   copied - it creates itself automatically the moment the bridge starts ticking. An external
   process (Claude Code or otherwise) drives Revit by writing bridge\command.json with an
   incrementing "id" and the absolute path to one of the scripts above, then polling
   bridge\heartbeat.json / result.json for it to run.
