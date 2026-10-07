# list_views.py - read-only: 3D views in the open model and how many ORIGIN_ASSEMBLY elements exist.
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
views = [v.Name for v in FilteredElementCollector(doc).OfClass(View3D) if not v.IsTemplate]
n = 0
for e in FilteredElementCollector(doc).OfClass(DirectShape):
    p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p and (p.AsString() or "").startswith("ORIGIN_ASSEMBLY"):
        n += 1
OUT = {"doc": doc.Title, "views_3d": views, "origin_assembly_elements": n}
