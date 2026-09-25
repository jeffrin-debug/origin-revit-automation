# origin_bridge_run_walls_by_ids.py - run via the ORIGIN Bridge.
# Force-selects a hardcoded list of wall element ids (edit TARGET_EIDS below), then runs the wall
# generator scoped to exactly that selection - for testing a specific multi-wall combination (e.g.
# a doorway modeled as several separate wall segments) as one group, without relying on the user
# to Ctrl+select every piece by hand in Revit. Leaves the selection set afterward so follow-up
# read-only probes (origin_bridge_describe_wall.py / origin_bridge_wall_generated.py) can inspect
# the same group.
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

TARGET_EIDS = []

REPO = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces"
WALL_SCRIPT = REPO + r"\origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py"

ids = List[ElementId]()
found = []
for eid in TARGET_EIDS:
    e = doc.GetElement(ElementId(eid))
    if isinstance(e, Wall):
        ids.Add(e.Id)
        found.append(eid)
uidoc.Selection.SetElementIds(ids)

result = {}
if len(found) == 0:
    result = {"FATAL": "None of TARGET_EIDS resolved to a Wall in this document."}
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

result["_target_eids"] = TARGET_EIDS
result["_resolved_wall_eids"] = found
OUT = result
