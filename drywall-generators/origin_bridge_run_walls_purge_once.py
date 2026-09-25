# origin_bridge_run_walls_purge_once.py - run via the ORIGIN Bridge. ONE-TIME CLEANUP.
# Curtain walls (glass storefronts) are now excluded from wall processing (get_input_walls), so
# delete_previous()'s normal per-run scope (only the walls being processed) can no longer see
# their OLD generated content - it's orphaned forever otherwise. Runs the wall generator once
# with purge_all=True (Dynamo IN[9]) to remove EVERY Origin element model-wide before the normal
# regeneration pass, exactly the scenario purge_all was built for ("orphans left when walls were
# recreated ... or an older build ran"). Same as origin_bridge_run_walls.py otherwise.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

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

ids = List[ElementId]()
for e in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    ids.Add(e.Id)
uidoc.Selection.SetElementIds(ids)

result = {}
try:
    ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": WALL_SCRIPT}
    ns["IN"][9] = True   # purge_all override
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
finally:
    try:
        uidoc.Selection.SetElementIds(List[ElementId]())
    except Exception:
        pass

OUT = result
