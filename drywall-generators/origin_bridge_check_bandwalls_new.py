# origin_bridge_check_bandwalls_new.py - run via the ORIGIN Bridge. READ-ONLY.
# Checks whether this new environment has any soffit "band walls" (the elevated 2'-tall walls
# that wrap a real soffit in Lab_01) - if none exist here either, that further confirms this
# building's one "Roof Soffits"-category ceiling has no real soffit/bulkhead relationship to
# anything, it's just a large ordinary ceiling filed under an unusual category.
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

out = {"wall_type_names": [], "band_wall_candidates": []}
walls = list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType())
names = set()
for w in walls:
    try:
        n = w.Name
    except Exception:
        n = None
    if n:
        names.add(n)
        if "2'" in n or "2 ft" in n.lower() or n == "Generic - 2'":
            out["band_wall_candidates"].append(n)

out["wall_type_names"] = sorted(names)
out["wall_count"] = len(walls)

OUT = out
