# origin_bridge_check_soffit_classification.py - run via the ORIGIN Bridge. READ-ONLY.
# Reproduces ceiling_prefix()'s EXACT logic (type Name + FamilyName substring match on "soffit")
# for element 396998, with full exception detail on each individual property access, to settle
# whether this element is genuinely name-matched as a soffit or something else is going on
# (e.g. matched by Category instead, or a false read).
import clr
import traceback

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

TARGET_EID = 396998
e = doc.GetElement(ElementId(TARGET_EID))
out = {}

ct = None
try:
    ct = doc.GetElement(e.GetTypeId())
    out["type_element_found"] = ct is not None
    out["type_element_class"] = type(ct).__name__ if ct is not None else None
except Exception:
    out["type_element_error"] = traceback.format_exc()

if ct is not None:
    try:
        out["ct_Name"] = ct.Name
    except Exception:
        out["ct_Name_error"] = traceback.format_exc()
    try:
        out["ct_FamilyName"] = ct.FamilyName
    except Exception:
        out["ct_FamilyName_error"] = traceback.format_exc()
    try:
        p = ct.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        out["ct_param_type_name"] = p.AsString() if p else None
    except Exception:
        out["ct_param_type_name_error"] = traceback.format_exc()
    try:
        p = ct.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        out["ct_param_family_name"] = p.AsString() if p else None
    except Exception:
        out["ct_param_family_name_error"] = traceback.format_exc()

try:
    out["element_category"] = e.Category.Name if e.Category else None
    out["element_category_bic"] = int(e.Category.Id.Value)
except Exception:
    out["element_category_error"] = traceback.format_exc()

OUT = out
