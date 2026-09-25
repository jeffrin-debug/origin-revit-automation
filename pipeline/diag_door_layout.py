# diag_door_layout.py - read-only: the studs and boards the wall generator built around ONE door.
#
# Set DOOR_ID below (or leave None to use the current Revit selection's first door). Everything is
# reported in FEET, measured along the host wall from the door's left edge (negative = left of the
# door) and up from the floor, so the course heights and stud positions read directly.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

DOOR_ID = 381894        # DR-008A, 3'-0" x 7'-0"
WINDOW_FT = 3.0         # report members this far either side of the door

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def eid(e):
    return e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


door = None
if DOOR_ID:
    door = doc.GetElement(ElementId(DOOR_ID))
else:
    for i in uidoc.Selection.GetElementIds():
        e = doc.GetElement(i)
        if e is not None and e.Category is not None and e.Category.Id == ElementId(BuiltInCategory.OST_Doors):
            door = e
            break

res = {"doc": doc.Title}
if door is None:
    res["error"] = "no door"
    OUT = res
else:
    wall = door.Host
    c = wall.Location.Curve
    p0 = c.GetEndPoint(0)
    u = c.GetEndPoint(1).Subtract(p0).Normalize()
    base_z = doc.GetElement(wall.LevelId).Elevation if wall.LevelId != ElementId.InvalidElementId else 0.0
    try:
        base_z += wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
    except Exception:
        pass

    def span(bb):
        pts = [XYZ(x, y, 0) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        a = [p.Subtract(XYZ(p0.X, p0.Y, 0)).DotProduct(u) for p in pts]
        return min(a), max(a)

    dbb = door.get_BoundingBox(None)
    d0, d1 = span(dbb)
    wall_h = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
    res["door"] = {"id": eid(door), "mark": par(door, BuiltInParameter.ALL_MODEL_MARK),
                   "type": door.Name, "host_wall": eid(wall),
                   "wall_mark": par(wall, BuiltInParameter.ALL_MODEL_MARK),
                   "wall_height_ft": round(wall_h, 3),
                   "door_width_with_trim_ft": round(d1 - d0, 3),
                   "door_top_ft": round(dbb.Max.Z - base_z, 3)}

    tag = "WALL=W{}".format(eid(wall))
    studs, boards = [], []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        cm = par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if tag not in cm:
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        a0, a1 = span(bb)
        if a1 < d0 - WINDOW_FT or a0 > d1 + WINDOW_FT:
            continue
        row = {"mark": par(ds, BuiltInParameter.ALL_MODEL_MARK),
               "from_ft": round(a0 - d0, 3), "to_ft": round(a1 - d0, 3),
               "z_ft": [round(bb.Min.Z - base_z, 3), round(bb.Max.Z - base_z, 3)]}
        kind = ""
        for k in ("KINGSTUD", "JACK", "CRIPPLE", "HEADER", "SILL", "TRACK", "STUD"):
            if k in cm:
                kind = k
                break
        if "DRYWALL" in cm:
            face = "A" if "FACE_A" in cm else "B"
            row["face"] = face
            boards.append(row)
        elif row["mark"].startswith("ST-"):
            row["kind"] = kind
            studs.append(row)
    studs.sort(key=lambda r: (r["from_ft"], r["z_ft"][0]))
    boards.sort(key=lambda r: (r["face"], r["z_ft"][0], r["from_ft"]))
    res["framing"] = studs
    res["boards"] = boards
    OUT = res
