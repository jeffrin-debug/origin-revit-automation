# origin_bridge_check_doors.py - run via the ORIGIN Bridge. READ-ONLY.
# Investigates real Door family instances: family/type name, host wall, and a breakdown of their
# geometry by sub-category (looking for a "Frame/Mullion"-style split between frame and panel),
# to design a general door-frame passthrough into the ORIGIN Assembly.
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


def cat_name_of(geom_obj):
    try:
        gsid = geom_obj.GraphicsStyleId
        if gsid and gsid != ElementId.InvalidElementId:
            gs = doc.GetElement(gsid)
            if gs and gs.GraphicsStyleCategory:
                return gs.GraphicsStyleCategory.Name
    except Exception:
        pass
    return None


def solids_by_subcat(e, depth=0):
    out = {}
    opt = Options()
    opt.ComputeReferences = False
    try:
        opt.DetailLevel = ViewDetailLevel.Fine
    except Exception:
        pass
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            cn = cat_name_of(g) or "(none)"
            rec = out.setdefault(cn, {"count": 0, "volume": 0.0})
            rec["count"] += 1
            rec["volume"] += g.Volume
        elif isinstance(g, GeometryInstance) and depth < 3:
            inst_geo = g.GetInstanceGeometry()
            for g2 in inst_geo:
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    cn = cat_name_of(g2) or "(none)"
                    rec = out.setdefault(cn, {"count": 0, "volume": 0.0})
                    rec["count"] += 1
                    rec["volume"] += g2.Volume
    return out


doors = []
for e in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType():
    try:
        fam = e.Symbol.Family.Name
        typ = e.Symbol.Name
    except Exception:
        fam, typ = None, None
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    host = None
    try:
        h = e.Host
        if h:
            host = eid_str = (h.Id.Value if hasattr(h.Id, "Value") else h.Id.IntegerValue)
    except Exception:
        pass
    bb = e.get_BoundingBox(None)
    subcats = solids_by_subcat(e)
    doors.append({
        "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "family": fam, "type": typ, "mark": mark, "host_wall_eid": host,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)],
        },
        "subcategory_solids": {k: {"count": v["count"], "volume_cf": round(v["volume"], 5)}
                               for k, v in subcats.items()},
    })

OUT = {"door_count": len(doors), "doors": doors}
