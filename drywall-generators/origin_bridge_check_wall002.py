# origin_bridge_check_wall002.py - run via the ORIGIN Bridge. READ-ONLY.
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

out = {}
try:
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        tag = mk.AsString() if mk else None
        if tag in ("002", "010"):
            lc = w.Location.Curve
            out["wall_" + tag] = {
                "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                "width_ft": round(w.Width, 4),
                "eid": w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else int(str(w.Id)),
            }
except Exception as ex:
    out["error"] = str(ex)

OUT = out
