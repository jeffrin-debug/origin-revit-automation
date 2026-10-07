# open_view.py - make a named view active in the Revit UI (no model change).
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
NAME = "ORIGIN Assembly"
v = next((x for x in FilteredElementCollector(doc).OfClass(View) if not x.IsTemplate and x.Name == NAME), None)
if v is None:
    OUT = {"error": "no view named " + NAME, "3d_views": [x.Name for x in FilteredElementCollector(doc).OfClass(View3D)]}
else:
    uidoc.RequestViewChange(v)
    OUT = {"requested": NAME, "view_id": v.Id.Value}
