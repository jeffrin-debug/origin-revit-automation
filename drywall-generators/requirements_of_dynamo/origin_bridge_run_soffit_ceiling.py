# origin_bridge_run_soffit_ceiling.py - run via the ORIGIN Bridge.
# Re-runs Ceilings then Soffits fresh from disk (mirrors origin_bridge_run_all.py's pattern:
# select every ceiling so the ceiling generator, which reads selection when no Dynamo input is
# wired, processes the whole model; soffit plugin self-collects). Used to verify the
# COLUMN_BEAM_CLEARANCE_FT tightening (0.6in -> 0.5in, matching DRYWALL_T_FT) lands cleanly.
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
GENERATORS = [
    ("ceiling", REPO + r"\origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py"),
    ("soffit", REPO + r"\origin_soffit_assembly_v1.py"),
]

ids = List[ElementId]()
for e in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    ids.Add(e.Id)
uidoc.Selection.SetElementIds(ids)

results = {}
for (label, path) in GENERATORS:
    ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": path}
    try:
        exec(compile(open(path).read(), path, "exec"), ns)
        out = ns.get("OUT")
        if isinstance(out, dict):
            slim = {}
            for k, v in out.items():
                if isinstance(v, (int, float, str, bool)) or v is None:
                    slim[k] = v
                elif k in ("warnings", "ceilings_skipped", "skipped"):
                    slim[k] = v
            results[label] = slim
        else:
            results[label] = str(out)
    except Exception as ex:
        import traceback
        results[label] = {"FATAL": traceback.format_exc()}

try:
    uidoc.Selection.SetElementIds(List[ElementId]())
except Exception:
    pass

OUT = results
