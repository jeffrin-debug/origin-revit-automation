# origin_bridge_check_stud_shape.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms ST-012-003's SOLID SHAPE actually changed from a C-channel (many faces, hollow-profile
# volume) to a simple flat rectangular slab (6 faces, solid box volume) - the material/style check
# alone can't tell shape apart; this checks face count and volume directly.
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


def inspect(mark):
    target = None
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = mk.AsString() if mk else None
        except Exception:
            m = None
        if m == mark:
            target = ds
            break
    if target is None:
        return {"mark": mark, "error": "not found"}
    opt = Options()
    geo = target.get_Geometry(opt)
    bb = target.get_BoundingBox(None)
    result = {"mark": mark}
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9:
            result["face_count"] = g.Faces.Size
            result["edge_count"] = g.Edges.Size
            result["volume_cf"] = round(g.Volume, 5)
            break
    if bb is not None:
        bbox_vol = (bb.Max.X - bb.Min.X) * (bb.Max.Y - bb.Min.Y) * (bb.Max.Z - bb.Min.Z)
        result["bbox_volume_cf"] = round(bbox_vol, 5)
        result["fill_ratio"] = round(result.get("volume_cf", 0) / bbox_vol, 4) if bbox_vol > 0 else None
    return result


OUT = {
    "ST_012_003": inspect("ST-012-003"),
    "ST_001_001_reference_normal_stud": inspect("ST-001-001"),
    "DP_012_001A_reference_drywall": inspect("DP-012-001A"),
}
