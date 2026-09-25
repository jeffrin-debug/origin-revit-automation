# origin_bridge_diag_one_wall.py - READ-ONLY. Why did wall W431171's exterior face escape the cap?
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

EID = 431171
SOFFIT_BAND_WALL_TYPE_NAME = "Generic - 2'"

w = doc.GetElement(ElementId(EID))
info = {"eid": EID, "is_wall": isinstance(w, Wall)}

try:
    info["wall_Name"] = w.Name
except Exception as ex:
    info["wall_Name"] = "ERR " + str(ex)
try:
    info["type_name"] = doc.GetElement(w.GetTypeId()).Name
except Exception as ex:
    info["type_name"] = "ERR " + str(ex)

info["is_soffit_band_by_name"] = (info.get("wall_Name") == SOFFIT_BAND_WALL_TYPE_NAME)

for nm, bip in (("base_offset", BuiltInParameter.WALL_BASE_OFFSET),
                ("unconnected_height", BuiltInParameter.WALL_USER_HEIGHT_PARAM),
                ("key_ref", BuiltInParameter.WALL_KEY_REF_PARAM)):
    try:
        p = w.get_Parameter(bip)
        if p is None:
            info[nm] = None
        elif nm == "key_ref":
            info[nm] = p.AsInteger()
        else:
            info[nm] = round(p.AsDouble(), 4)
    except Exception as ex:
        info[nm] = "ERR " + str(ex)

try:
    bb = w.get_BoundingBox(None)
    info["wall_bbox_z"] = [round(bb.Min.Z, 3), round(bb.Max.Z, 3)]
    info["wall_bbox_xy"] = [round(bb.Min.X, 2), round(bb.Min.Y, 2),
                            round(bb.Max.X, 2), round(bb.Max.Y, 2)]
except Exception:
    pass

try:
    loc = w.Location
    c = loc.Curve
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    info["curve_start"] = [round(p0.X, 3), round(p0.Y, 3), round(p0.Z, 3)]
    info["curve_end"] = [round(p1.X, 3), round(p1.Y, 3), round(p1.Z, 3)]
    info["length_ft"] = round(c.Length, 3)
except Exception as ex:
    info["curve"] = "ERR " + str(ex)

try:
    info["width_in"] = round(w.WallType.Width * 12.0, 3)
    info["orientation"] = [round(w.Orientation.X, 3), round(w.Orientation.Y, 3)]
except Exception:
    pass

OUT = info
