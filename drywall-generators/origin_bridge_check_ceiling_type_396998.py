# origin_bridge_check_ceiling_type_396998.py - run via the ORIGIN Bridge. READ-ONLY.
# The pipeline classifies ceiling host tag C396998 as a "soffit" (S-prefix) because its type or
# family name contains "soffit". The user says there is no soffit in this environment - dumping
# the real type/family name to see whether that classification is a genuine match or a false
# positive (e.g. a naming collision unrelated to it actually being an architectural soffit).
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

TARGET_EID = 396998

e = doc.GetElement(ElementId(TARGET_EID))
out = {"exists": e is not None}
if e is not None:
    out["type"] = type(e).__name__
    try:
        out["category"] = e.Category.Name if e.Category else None
    except Exception:
        out["category"] = None
    try:
        ct = doc.GetElement(e.GetTypeId())
        out["type_name"] = ct.Name if ct is not None else None
        out["family_name"] = ct.FamilyName if (ct is not None and hasattr(ct, "FamilyName")) else None
    except Exception as ex:
        out["type_name_error"] = str(ex)
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        out["mark"] = mk.AsString() if mk else None
    except Exception:
        out["mark"] = None
    try:
        bb = e.get_BoundingBox(None)
        out["bbox"] = None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}
    except Exception:
        out["bbox"] = None
    try:
        lvl = doc.GetElement(e.LevelId)
        out["level"] = lvl.Name if lvl else None
    except Exception:
        out["level"] = None
    try:
        ho = e.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
        out["height_above_level_ft"] = ho.AsDouble() if ho else None
    except Exception:
        out["height_above_level_ft"] = None

OUT = out
