# Origin Revit Drywall Scripts v3 â€” Unified

v3 merges the two earlier, divergent approaches into **one script** and fixes the correctness
bugs that were silently producing wrong geometry.

## Why v3 exists

Earlier the package shipped two unrelated strategies that shared no code and disagreed on the
spec:

- **Lineage A â€” DirectShape** (`origin_drywall_dynamo_v2_two_faces.py`): raw solids, both faces
  in one run, no studs, screws at 12".
- **Lineage B â€” Family instances** (`ORG_Generate_Drywall_System_V1_2.py` + the Word plan):
  studs + schedulable parameters, but one side per run and a cleanup that could wipe the first
  side, screws at 9".

Both also assumed the wall **Location Line was the centerline**, so panels landed off the real
surface whenever it was set to a finish/core face.

`origin_drywall_unified_v3.py` is the single trunk going forward. The old files are kept for
history but are **deprecated** â€” see the bottom of this file.

## What changed (correctness first)

1. **True wall-face placement.** v3 reads the wall's Location Line
   (`WALL_KEY_REF_PARAM`) and compound structure and places each face on its real surface.
   This is the big fix over v1/v2.
2. **Safe, wall-scoped cleanup.** Delete-previous only removes v3 output on the walls you are
   processing this run, then rebuilds both enabled faces. It can no longer wipe drywall on other
   walls, and both faces regenerate together so neither side is orphaned. (Caveat: if you disable
   a face in `FACE_LAYOUTS` and rerun with delete on, that face's panels on the processed walls
   are removed and not rebuilt â€” that's intended.)
3. **Level-Z guard** for family mode (level-based placement can otherwise snap panels to the
   level plane).
4. **Diagnostics** â€” skipped walls and failed geometry now appear in `OUT["warnings"]` and
   `OUT["walls_skipped"]` instead of being swallowed; each wall is isolated so one failure does
   not abort the rest.
5. **Unified screw spacing** â€” 9" vertical OC + 1" top/bottom offset (the plan's spec).
6. **Studs in both modes**, placed once per wall and centered on the structural **core** (correct
   for asymmetric compound walls, not just the total-wall midplane).

## Files

- `origin_drywall_unified_v3.py` â€” the generator. **Start here.**
- `origin_wall_data_exporter_v3.py` â€” debug export; now also reports Location Line, compound
  layers, and the exact face offsets the generator will use.
- `claude_prompt_revit_drywall_v3.md` â€” prompt for asking Claude to debug/modify v3.

## Two output modes

Set `OUTPUT_MODE` at the top of `origin_drywall_unified_v3.py`:

- `"directshape"` (default) â€” builds raw DirectShape solids. **No families required. Runs
  anywhere.** Best for fast visualization. Tagged with `ApplicationId = ORIGIN_DRYWALL_V3`.
- `"family"` â€” places instances of `ORG_MetalStud` / `ORG_GWB_Panel` / `ORG_GWB_ScrewMarker`
  (wired to `IN[1..3]`). Gives schedulable instance parameters. Requires those families loaded.
  Tagged with the `Generated_By` parameter = `ORIGIN_DRYWALL_V3`.

Seam strips are generated in DirectShape mode only (there is no seam family yet).

## First test (DirectShape, zero setup)

1. Open a **copy** of your Revit model.
2. Open Dynamo, new graph, add one Python Script node (engine: **CPython3**).
3. Paste the full contents of `origin_drywall_unified_v3.py`.
4. Select one straight wall in Revit.
5. Run. Inspect in 3D â€” panels on both faces, studs at 16" OC, screws at 9" OC.
6. `OUT` is a result dict: `panels_created`, `seams_created`, `screws_created`,
   `studs_created`, `walls_skipped`, `warnings`.

## Dynamo input wiring

| Input | Meaning | Needed in |
|-------|---------|-----------|
| `IN[0]` | Selected wall(s) (falls back to Revit selection) | both modes |
| `IN[1]` | `ORG_MetalStud` family type | family mode |
| `IN[2]` | `ORG_GWB_Panel` family type | family mode |
| `IN[3]` | `ORG_GWB_ScrewMarker` family type | family mode |
| `IN[4]` | Normal flip: `1` (default) or `-1` if Orientation is reversed | optional |
| `IN[5]` | Delete previous Origin drywall: `True`/`False` | optional |
| `IN[6]` | Generate screws: `True`/`False` | optional |

In DirectShape mode you only need `IN[0]`.

## Key settings (top of the script)

- `FACE_LAYOUTS` â€” the two faces, each with `base_edge_shift_ft` / `odd_row_additional_shift_ft`.
  Set `"enabled": False` to skip a face. Face B is shifted one 16" stud bay so the two sides
  do not mirror.
- `PANEL_LENGTH_FT = 8.0`, `PANEL_HEIGHT_FT = 4.0`, `PANEL_THICKNESS_FT = 0.5/12`
- `STUD_SPACING_FT = 16/12`, `SCREW_SPACING_VERTICAL_FT = 9/12`, `SCREW_TOP_BOTTOM_OFFSET_FT = 1/12`
- `GENERATE_STUDS`, `GENERATE_SEAMS`, `GENERATE_SCREWS`
- `COLOR_BY_TYPE = True` â€” in DirectShape mode, place panels/seams/screws/studs on separate
  colored Generic Model subcategories (`ORIGIN Drywall Panel/Seam/Screw`, `ORIGIN Metal Stud`).
  They then shade in distinct colors and can be toggled individually in Visibility/Graphics
  (e.g. hide screws to speed up large views). No effect in family mode.
- `MAX_SCREWS_PER_RUN = 7000` (safety guard across both faces)

## Family-mode contract (IMPORTANT)

Family mode fails **silently** if the families are not modeled to match. Build them per the
Word plan (`Revit_Drywall_System_Automation_Plan.docx`, Â§3):

- Origins at the **geometric center** of the family.
- `ORG_GWB_Panel` geometry driven by instance params `Panel_Length` / `Panel_Height` /
  `Panel_Thickness`.
- `ORG_MetalStud` geometry driven by `Stud_Height` (and `Stud_Width` / `Stud_Depth`).
- Each family needs a text instance param `Generated_By` (v3 writes `ORIGIN_DRYWALL_V3` for
  cleanup) plus the schedulable params listed in the plan (`Panel_ID`, `Side`, `Is_Cut_Panel`, â€¦).

If a panel family is not parametric, every panel renders at the family's default size and no
error is raised â€” check `OUT["warnings"]` and a 3D view.

## Verify the correctness fix

The signature test: on one wall, set **Location Line = "Finish Face: Exterior"** and rerun.
Panels must sit on the true faces. Under v1/v2 they would have been off by about half the wall
width. Run `origin_wall_data_exporter_v3.py` on the wall to see `computed_face_offsets` and
confirm they match what you see in Revit.

## Still approximate (unchanged)

- Straight vertical walls only; curved/slanted walls are skipped and reported.
- Openings are approximated from hosted-insert bounding boxes (may overcut near door swings).
- This is visualization/layout geometry, not shop-drawing certification.

## Recommended next work

- Seam family for family mode.
- Panel/seam/screw/stud coordinate export (schedules or Isaac Sim / robot planning).
- True opening geometry (rough-opening params) instead of bounding boxes.

Done in v3: unified DirectShape + family modes, true face placement, core-centered studs,
scoped cleanup, per-type coloring/subcategories.

## Deprecated (kept for history â€” do not use for new work)

- `origin_drywall_dynamo_v1.py`, `origin_drywall_dynamo_v2_two_faces.py`
- `ORG_Generate_Drywall_System_V1_2.py`
- `origin_wall_data_exporter_v1.py`, `origin_wall_data_exporter_v2_two_faces.py`
- `README.md`, `README_v2_two_faces.md`, `claude_prompt_revit_drywall.md`,
  `claude_prompt_revit_drywall_v2.md`

`Revit_Drywall_System_Automation_Plan.docx` remains the reference spec for the family kit.
