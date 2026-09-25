# origin_bridge_check_door_frame_visibility.py - run via the ORIGIN Bridge. READ-ONLY.
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

view = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
        view = v
        break

out = {"view_found": view is not None, "frames": []}
if view is not None:
    for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if not mark or not mark.startswith("DF-"):
            continue
        try:
            hidden = e.IsHidden(view)
        except Exception:
            hidden = None
        out["frames"].append({"mark": mark, "is_hidden_in_view": hidden})

OUT = out
