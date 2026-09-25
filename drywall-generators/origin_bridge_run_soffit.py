# origin_bridge_run_soffit.py - run via the ORIGIN Bridge.
# Runs the soffit generator fresh from disk (self-collecting, no selection needed).
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
SCRIPT = REPO + r"\origin_soffit_assembly_v1.py"

result = {}
try:
    ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": SCRIPT}
    exec(compile(open(SCRIPT).read(), SCRIPT, "exec"), ns)
    out = ns.get("OUT")
    if isinstance(out, dict):
        result = {k: v for k, v in out.items() if isinstance(v, (int, float, str, bool)) or k in ("warnings", "ceilings_skipped")}
    else:
        result = {"OUT": str(out)}
except Exception:
    import traceback
    result = {"FATAL": traceback.format_exc()}

OUT = result
