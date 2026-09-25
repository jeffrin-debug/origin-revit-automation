# origin_bridge_fix_ceiling_type_396998.py - run via the ORIGIN Bridge. TRANSACTION.
# Ceiling 396998 is the ONLY element in this model using the "Roof Soffit: Generic - 4"" type
# (confirmed via origin_bridge_list_ceiling_types.py) while all 4 other real ceilings use
# "Compound Ceiling: GWB on Mtl. Stud" - a stray modeling mistake, not an intentional soffit
# (confirmed with the user). Switches it to match the other ceilings.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

TARGET_EID = 396998
NEW_TYPE_ID = 44748   # Compound Ceiling: GWB on Mtl. Stud - used by all 4 other real ceilings

TransactionManager.Instance.EnsureInTransaction(doc)
result = {}
try:
    e = doc.GetElement(ElementId(TARGET_EID))
    if e is None:
        result["error"] = "element not found"
    else:
        old_type_id = e.GetTypeId()
        old_type = doc.GetElement(old_type_id)
        try:
            result["old_family_name"] = old_type.FamilyName
        except Exception:
            result["old_family_name"] = None
        tp = e.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
        if tp is None or tp.IsReadOnly:
            result["error"] = "ELEM_TYPE_PARAM missing or read-only"
        else:
            tp.Set(ElementId(NEW_TYPE_ID))
            result["changed"] = True
        new_type = doc.GetElement(e.GetTypeId())
        try:
            result["new_family_name"] = new_type.FamilyName
        except Exception:
            result["new_family_name"] = None
except Exception as ex:
    result["error"] = str(ex)
finally:
    TransactionManager.Instance.TransactionTaskDone()

try:
    doc.Regenerate()
except Exception:
    pass

OUT = result
