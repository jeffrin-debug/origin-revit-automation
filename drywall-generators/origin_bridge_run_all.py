# origin_bridge_run_all.py - run the WHOLE pipeline through the ORIGIN Bridge.
# Selects every wall + ceiling in the model, then executes each generator .py fresh from disk
# (walls -> ceilings -> soffits -> columns -> beams) and returns all summaries.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

REPO = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces"
GENERATORS = [
    ("walls", REPO + r"\origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py"),
    ("ceilings", REPO + r"\origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py"),
    ("soffits", REPO + r"\origin_soffit_assembly_v1.py"),
    ("columns", REPO + r"\origin_column_assembly_v1.py"),
    ("beams", REPO + r"\origin_beam_assembly_v1.py"),
]

# Select every wall + ceiling so the wall/ceiling generators (which read the selection when no
# Dynamo input is wired) process the whole model. Soffit/column/beam plugins self-collect.
ids = List[ElementId]()
for cls in (Wall, Ceiling):
    for e in FilteredElementCollector(doc).OfClass(cls).WhereElementIsNotElementType():
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
                elif k in ("warnings", "walls_skipped", "ceilings_skipped", "skipped"):
                    slim[k] = v
            results[label] = slim
        else:
            results[label] = str(out)
    except Exception as ex:
        import traceback
        results[label] = {"FATAL": traceback.format_exc()}

# Clear the selection again so the user's view is clean.
try:
    uidoc.Selection.SetElementIds(List[ElementId]())
except Exception:
    pass

OUT = results
