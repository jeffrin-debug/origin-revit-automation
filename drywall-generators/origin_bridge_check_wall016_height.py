# origin_bridge_check_wall016_height.py - run via the ORIGIN Bridge. READ-ONLY.
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

w = doc.GetElement(ElementId(388627))
out = {"exists": w is not None}
if w is not None:
    bb = w.get_BoundingBox(None)
    out["bbox_z"] = [round(bb.Min.Z, 4), round(bb.Max.Z, 4)] if bb else None
    try:
        out["is_curtain"] = w.WallType.Kind == WallKind.Curtain
    except Exception as ex:
        out["is_curtain_err"] = str(ex)
    try:
        wt = doc.GetElement(w.GetTypeId())
        out["wall_type_name"] = wt.Name if wt else None
    except Exception:
        pass
    try:
        hp = w.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        out["height_param_ft"] = hp.AsDouble() if hp else None
    except Exception:
        pass
    try:
        bo = w.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        out["base_offset_ft"] = bo.AsDouble() if bo else None
    except Exception:
        pass

# Ceiling C406965's own Z (bottom face).
c = doc.GetElement(ElementId(406965))
if c is not None:
    cbb = c.get_BoundingBox(None)
    out["ceiling_bbox_z"] = [round(cbb.Min.Z, 4), round(cbb.Max.Z, 4)] if cbb else None

OUT = out
