# origin_bridge_run_walls.py - run via the ORIGIN Bridge.
# Selects every wall in the model, then runs the wall generator fresh from disk (picks up the
# soffit/column stop-short fix), and clears the selection again afterward.
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
    exec(compile(open(WALL_SCRIPT).read(), WALL_SCRIPT, "exec"), ns)
    out = ns.get("OUT")
    if isinstance(out, dict):
        result = {k: v for k, v in out.items()
                  if isinstance(v, (int, float, str, bool)) or k in ("warnings", "walls_skipped", "notes")}
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
