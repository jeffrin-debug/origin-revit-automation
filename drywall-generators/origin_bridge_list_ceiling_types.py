# origin_bridge_list_ceiling_types.py - run via the ORIGIN Bridge. READ-ONLY.
# Lists every CeilingType in the model (family name + type name + id) and how many real Ceiling
# instances currently use each one, to pick a normal (non-Roof-Soffit) type to reassign 396998 to.
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

usage = {}
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    tid = c.GetTypeId()
    key = int(tid.Value) if hasattr(tid, "Value") else int(tid.IntegerValue)
    usage[key] = usage.get(key, 0) + 1

out = []
for ct in FilteredElementCollector(doc).OfClass(CeilingType):
    tid = ct.Id
    key = int(tid.Value) if hasattr(tid, "Value") else int(tid.IntegerValue)
    try:
        fam = ct.FamilyName
    except Exception:
        fam = None
    try:
        p = ct.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        tname = p.AsString() if p else None
    except Exception:
        tname = None
    out.append({
        "type_id": key, "family_name": fam, "type_name": tname,
        "instances_using_it": usage.get(key, 0),
    })
out.sort(key=lambda r: -r["instances_using_it"])

OUT = {"types": out}
