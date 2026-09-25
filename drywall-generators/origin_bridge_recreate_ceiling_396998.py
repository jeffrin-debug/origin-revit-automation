# origin_bridge_recreate_ceiling_396998.py - run via the ORIGIN Bridge. TRANSACTION.
# Ceiling 396998 uses Revit's "Roof Soffit" category, a different category from ordinary
# "Ceilings" - Revit does not allow swapping a type across categories (confirmed: a direct
# ELEM_TYPE_PARAM.Set() silently no-ops). Recreates it as a real Ceiling with the identical
# boundary (captured via origin_bridge_read_ceiling_sketch_396998.py), same level/height offset,
# using the type already shared by all 4 other real ceilings in this model
# (Compound Ceiling: GWB on Mtl. Stud). Deletes the old Roof-Soffit element afterward.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List as NetList

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

OLD_EID = 396998
NEW_TYPE_ID = 44748     # Compound Ceiling: GWB on Mtl. Stud
LEVEL_ID = 9946          # Level 2
HEIGHT_OFFSET_FT = 0.0

PTS = [
    (-14.5237, 1.4126, 10.0), (-29.0237, 1.4126, 10.0), (-29.0237, 5.1626, 10.0),
    (-50.5237, 5.1626, 10.0), (-50.5237, 15.5792, 10.0), (-50.6904, 15.5792, 10.0),
    (-50.6904, 16.5792, 10.0), (-42.857, 16.5792, 10.0), (-42.857, 16.0792, 10.0),
    (-41.107, 16.0792, 10.0), (-41.107, 16.5792, 10.0), (-39.107, 16.5792, 10.0),
    (-39.107, 16.0792, 10.0), (-23.2737, 16.0792, 10.0), (-23.2737, 16.3292, 10.0),
    (-14.5237, 16.3292, 10.0), (-14.5237, 15.9126, 10.0),
]

TransactionManager.Instance.EnsureInTransaction(doc)
result = {}
try:
    loop = CurveLoop()
    n = len(PTS)
    for i in range(n):
        p0 = XYZ(*PTS[i])
        p1 = XYZ(*PTS[(i + 1) % n])
        loop.Append(Line.CreateBound(p0, p1))

    loops = NetList[CurveLoop]()
    loops.Add(loop)

    old = doc.GetElement(ElementId(OLD_EID))
    old_bbox = old.get_BoundingBox(None) if old is not None else None
    if old is not None:
        doc.Delete(old.Id)

    new_ceiling = Ceiling.Create(doc, loops, ElementId(NEW_TYPE_ID), ElementId(LEVEL_ID))
    result["new_element_id"] = int(new_ceiling.Id.Value) if hasattr(new_ceiling.Id, "Value") else int(new_ceiling.Id.IntegerValue)

    ho = new_ceiling.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
    if ho and not ho.IsReadOnly:
        ho.Set(HEIGHT_OFFSET_FT)

    result["created"] = True
except Exception as ex:
    import traceback
    result["error"] = traceback.format_exc()
finally:
    TransactionManager.Instance.TransactionTaskDone()

try:
    doc.Regenerate()
except Exception:
    pass

if result.get("created"):
    try:
        ne = doc.GetElement(ElementId(result["new_element_id"]))
        result["new_category"] = ne.Category.Name if ne.Category else None
        ct = doc.GetElement(ne.GetTypeId())
        result["new_family_name"] = ct.FamilyName if ct is not None else None
        nb = ne.get_BoundingBox(None)
        result["new_bbox"] = None if nb is None else {
            "min": [round(nb.Min.X, 3), round(nb.Min.Y, 3), round(nb.Min.Z, 3)],
            "max": [round(nb.Max.X, 3), round(nb.Max.Y, 3), round(nb.Max.Z, 3)]}
    except Exception as ex:
        result["verify_error"] = str(ex)

OUT = result
