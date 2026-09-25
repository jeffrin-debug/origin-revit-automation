# origin_bridge_check_c406965_identity.py - run via the ORIGIN Bridge. READ-ONLY.
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

e = doc.GetElement(ElementId(406965))
out = {"exists": e is not None}
if e is not None:
    try:
        out["category"] = e.Category.Name if e.Category else None
    except Exception as ex:
        out["category_error"] = str(ex)
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        out["mark"] = mk.AsString() if mk else None
    except Exception:
        pass
    try:
        ct = doc.GetElement(e.GetTypeId())
        out["type_name"] = ct.Name if ct else None
        out["family_name"] = ct.FamilyName if (ct and hasattr(ct, "FamilyName")) else None
    except Exception as ex:
        out["type_error"] = str(ex)

# Also list ALL Ceiling-class elements in the doc with their category+type, for full context.
all_ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    try:
        cat = c.Category.Name if c.Category else None
    except Exception:
        cat = None
    try:
        ct = doc.GetElement(c.GetTypeId())
        tname = ct.Name if ct else None
    except Exception:
        tname = None
    try:
        mk = c.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    all_ceilings.append({
        "eid": c.Id.Value if hasattr(c.Id, "Value") else c.Id.IntegerValue,
        "category": cat, "type_name": tname, "mark": mark,
    })

OUT = {"target": out, "all_ceilings": all_ceilings}
