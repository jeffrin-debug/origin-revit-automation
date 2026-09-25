# origin_bridge_check_soffit_elem.py - run via the ORIGIN Bridge. READ-ONLY.
# User says there is NO real soffit in this environment, but the pipeline auto-detected and
# processed one Ceiling element (C394667) as a soffit via its Revit CATEGORY name containing
# "soffit". Ground-truth exactly what that element really is: its true BuiltInCategory, level,
# elevation, bbox, and whether it looks like an exterior roof-eave condition rather than an
# interior bulkhead/soffit.
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

out = {"ceilings": []}
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    rec = {"id": c.Id.IntegerValue if hasattr(c.Id, "IntegerValue") else int(str(c.Id))}
    try:
        cat = c.Category
        rec["category_name"] = cat.Name if cat else None
        rec["builtin_category"] = str(BuiltInCategory(cat.Id.IntegerValue)) if cat else None
    except Exception as ex:
        rec["category_error"] = str(ex)
    try:
        lvl = doc.GetElement(c.LevelId)
        rec["level_name"] = lvl.Name if lvl else None
    except Exception:
        rec["level_name"] = None
    try:
        hp = c.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
        rec["height_above_level_ft"] = hp.AsDouble() if hp else None
    except Exception:
        pass
    try:
        bb = c.get_BoundingBox(None)
        if bb:
            rec["bbox"] = {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}
    except Exception:
        pass
    try:
        mk = c.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        rec["mark"] = mk.AsString() if mk else None
    except Exception:
        pass
    try:
        cm = c.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        rec["comments"] = cm.AsString() if cm else None
    except Exception:
        pass
    out["ceilings"].append(rec)

# Also check whether any real roofs exist in the model (a true roof-eave soffit would usually
# have an associated Roof element nearby / above it).
try:
    roofs = list(FilteredElementCollector(doc).OfClass(RoofBase).WhereElementIsNotElementType())
    out["roof_count"] = len(roofs)
except Exception as ex:
    out["roof_count_error"] = str(ex)

OUT = out
