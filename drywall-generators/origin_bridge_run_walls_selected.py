# origin_bridge_run_walls_selected.py - run via the ORIGIN Bridge.
# Runs the wall generator fresh from disk against WHATEVER is currently selected in Revit - does
# NOT force-select every wall (unlike origin_bridge_run_walls.py, which is for full-model runs)
# and does NOT clear the selection afterward, so the same wall stays selected for follow-up
# read-only probes (origin_bridge_describe_wall.py etc.) without having to re-pick it. Built for
# the wall-by-wall review workflow: select exactly one wall in Revit, run this, inspect just that
# wall's output, move on.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

REPO = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces"
WALL_SCRIPT = REPO + r"\origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py"

sel_ids = uidoc.Selection.GetElementIds()
wall_count = 0
for eid in sel_ids:
    e = doc.GetElement(eid)
    if isinstance(e, Wall):
        wall_count += 1

result = {}
if wall_count == 0:
    result = {"FATAL": "Nothing selected (or no Wall in the selection) - select one or more "
                       "walls in Revit before running this."}
else:
    try:
        ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": WALL_SCRIPT}
        exec(compile(open(WALL_SCRIPT).read(), WALL_SCRIPT, "exec"), ns)
        out = ns.get("OUT")
        if isinstance(out, dict):
            result = {k: v for k, v in out.items()
                      if isinstance(v, (int, float, str, bool)) or k in ("warnings", "walls_skipped")}
        else:
            result = {"OUT": str(out)}
    except Exception:
        import traceback
        result = {"FATAL": traceback.format_exc()}

result["_selected_wall_count"] = wall_count
OUT = result
