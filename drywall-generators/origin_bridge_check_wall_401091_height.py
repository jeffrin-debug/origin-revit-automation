# origin_bridge_check_wall_401091_height.py - run via the ORIGIN Bridge. READ-ONLY.
# Studs on wall 401091 go to Z=10, drywall only to Z=4 - one of the two height computations is
# wrong. Dumps the wall's real height/level/offset parameters plus every DP-023-*/ST-023-*
# element's Z range, to see if there's a pattern (e.g. openings) explaining the 4ft cutoff, or
# whether it's simply a bug.
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

WALL_EID = 401091
w = doc.GetElement(ElementId(WALL_EID))
out = {"exists": w is not None}
if w is not None:
    try:
        lvl = doc.GetElement(w.LevelId)
        out["base_level"] = lvl.Name if lvl else None
        out["base_level_elev"] = lvl.Elevation if lvl else None
    except Exception as ex:
        out["base_level_error"] = str(ex)
    try:
        p = w.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        out["unconnected_height_ft"] = p.AsDouble() if p else None
    except Exception as ex:
        out["unconnected_height_error"] = str(ex)
    try:
        p = w.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
        top_id = p.AsElementId() if p else None
        out["top_constraint_is_unconnected"] = (top_id is not None and top_id == ElementId.InvalidElementId)
        if top_id is not None and top_id != ElementId.InvalidElementId:
            tl = doc.GetElement(top_id)
            out["top_constraint_level"] = tl.Name if tl else None
    except Exception as ex:
        out["top_constraint_error"] = str(ex)
    try:
        p = w.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)
        out["top_offset_ft"] = p.AsDouble() if p else None
    except Exception:
        pass
    try:
        p = w.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        out["base_offset_ft"] = p.AsDouble() if p else None
    except Exception:
        pass
    try:
        bb = w.get_BoundingBox(None)
        out["wall_real_bbox"] = None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}
    except Exception as ex:
        out["wall_bbox_error"] = str(ex)

# Every DP-023-*/ST-023-* element's Z range, and openings on this wall.
elements = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-023-") or mark.startswith("ST-023-")):
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    elements.append({
        "mark": mark, "kind": (comments.split("|")[3].strip() if comments and len(comments.split("|")) > 3 else None),
        "z_min": round(bb.Min.Z, 3) if bb else None, "z_max": round(bb.Max.Z, 3) if bb else None,
    })
elements.sort(key=lambda r: r["mark"])
out["elements_z_ranges"] = elements

openings = []
try:
    for e in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
        try:
            host = e.Host
        except Exception:
            host = None
        if host is None or host.Id.IntegerValue != WALL_EID:
            continue
        try:
            cat = e.Category.Name if e.Category else None
        except Exception:
            cat = None
        if cat in ("Doors", "Windows"):
            openings.append({"category": cat, "id": e.Id.IntegerValue})
except Exception as ex:
    out["openings_error"] = str(ex)
out["openings"] = openings

OUT = out
