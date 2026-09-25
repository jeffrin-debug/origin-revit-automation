# origin_bridge_run_ceiling_only.py - run via the ORIGIN Bridge.
# Runs ONLY the ceiling generator (not the separate soffit script) - needed now that
# PROCESS_MODE="all" makes the ceiling script also process "Roof Soffits"-categorized ceilings
# (per user direction, 2026-08-06). Running the combined soffit+ceiling runner would let the
# separate, untouched soffit script ALSO process the same element, creating duplicate/conflicting
# DirectShapes.
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
CEILING_SCRIPT = REPO + r"\origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py"

ids = List[ElementId]()
for e in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    ids.Add(e.Id)
uidoc.Selection.SetElementIds(ids)

result = {}
try:
    ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": CEILING_SCRIPT}
    exec(compile(open(CEILING_SCRIPT).read(), CEILING_SCRIPT, "exec"), ns)
    out = ns.get("OUT")
    if isinstance(out, dict):
        result = {k: v for k, v in out.items()
                  if isinstance(v, (int, float, str, bool)) or k in ("warnings", "ceilings_skipped", "notes")}
    else:
        result = {"OUT": str(out)}
except Exception:
    import traceback
    result = {"FATAL": traceback.format_exc()}

try:
    uidoc.Selection.SetElementIds(List[ElementId]())
except Exception:
    pass

OUT = result
