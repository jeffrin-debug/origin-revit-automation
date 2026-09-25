# diag_door_sizes.py - read-only: every door's size in feet.
#
# Reports the family's own Width / Height / Thickness / Trim Width (instance value first, then
# type), plus the door's actual bounding box measured along and across its host wall, so a family
# whose parameters don't match its geometry shows up as a difference between the two.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title}


def eid(e):
    return e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value


def ft(v):
    return round(v, 3) if v is not None else None


def ft_in(v):
    if v is None:
        return None
    total = round(v * 12.0 * 8.0) / 8.0          # nearest 1/8"
    f = int(total // 12)
    i = total - f * 12
    whole = int(i)
    frac = {0: "", 1: " 1/8", 2: " 1/4", 3: " 3/8", 4: " 1/2", 5: " 5/8", 6: " 3/4", 7: " 7/8"}[int(round((i - whole) * 8))]
    return "{}'-{}{}\"".format(f, whole, frac)


def length_param(e, names, bips):
    """First length value found on the instance, then on its type. Returns (feet, where)."""
    t = doc.GetElement(e.GetTypeId())
    for src, owner in (("instance", e), ("type", t)):
        if owner is None:
            continue
        for b in bips:
            try:
                p = owner.get_Parameter(b)
                if p is not None and p.HasValue and p.StorageType == StorageType.Double:
                    return p.AsDouble(), src
            except Exception:
                pass
        for n in names:
            try:
                p = owner.LookupParameter(n)
                if p is not None and p.HasValue and p.StorageType == StorageType.Double:
                    return p.AsDouble(), src
            except Exception:
                pass
    return None, None


doors = []
for d in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors) \
        .WhereElementIsNotElementType():
    w, w_src = length_param(d, ["Width"], [BuiltInParameter.DOOR_WIDTH, BuiltInParameter.FAMILY_WIDTH_PARAM])
    h, h_src = length_param(d, ["Height"], [BuiltInParameter.DOOR_HEIGHT, BuiltInParameter.FAMILY_HEIGHT_PARAM])
    th, _ = length_param(d, ["Thickness"], [BuiltInParameter.FAMILY_THICKNESS_PARAM])
    tw, _ = length_param(d, ["Trim Width"], [])
    rw, _ = length_param(d, ["Rough Width"], [BuiltInParameter.FAMILY_ROUGH_WIDTH_PARAM])
    rh, _ = length_param(d, ["Rough Height"], [BuiltInParameter.FAMILY_ROUGH_HEIGHT_PARAM])

    row = {"id": eid(d), "family": d.Symbol.Family.Name if d.Symbol else "", "type": d.Name,
           "mark": (d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString() or ""),
           "host_wall": eid(d.Host) if d.Host else None,
           "level": doc.GetElement(d.LevelId).Name if d.LevelId != ElementId.InvalidElementId else "",
           "width_ft": ft(w), "width": ft_in(w), "width_from": w_src,
           "height_ft": ft(h), "height": ft_in(h), "height_from": h_src,
           "thickness_ft": ft(th), "thickness": ft_in(th),
           "trim_width_ft": ft(tw), "rough_width_ft": ft(rw), "rough_height_ft": ft(rh)}

    # measured size: along the host wall, across it, and vertical
    bb = d.get_BoundingBox(None)
    if bb is not None:
        u = None
        try:
            c = d.Host.Location.Curve
            u = (c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()
        except Exception:
            pass
        pts = [XYZ(x, y, z) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y) for z in (bb.Min.Z, bb.Max.Z)]
        if u is not None:
            n = XYZ(-u.Y, u.X, 0)
            along = [p.DotProduct(u) for p in pts]
            across = [p.DotProduct(n) for p in pts]
            row["bbox_along_wall_ft"] = ft(max(along) - min(along))
            row["bbox_across_wall_ft"] = ft(max(across) - min(across))
        row["bbox_height_ft"] = ft(bb.Max.Z - bb.Min.Z)
        row["bottom_z_ft"] = ft(bb.Min.Z)
    doors.append(row)

doors.sort(key=lambda r: r["id"])
res["door_count"] = len(doors)
res["doors"] = doors
OUT = res
