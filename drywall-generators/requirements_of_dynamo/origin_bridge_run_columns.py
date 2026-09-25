# origin_bridge_run_columns.py - run via the ORIGIN Bridge.
# Runs the column generator fresh from disk (self-collecting, no selection needed) so its
# collect_other_pipeline_solids() snapshot reflects the CURRENT state of every other generator's
# output, not a stale one from an earlier run this session.
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
SCRIPT = REPO + r"\origin_column_assembly_v1.py"

result = {}
try:
    ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": SCRIPT}
    exec(compile(open(SCRIPT).read(), SCRIPT, "exec"), ns)
    out = ns.get("OUT")
    if isinstance(out, dict):
        result = {k: v for k, v in out.items() if isinstance(v, (int, float, str, bool)) or k in ("warnings", "skipped")}
    else:
        result = {"OUT": str(out)}
except Exception:
    import traceback
    result = {"FATAL": traceback.format_exc()}

OUT = result
