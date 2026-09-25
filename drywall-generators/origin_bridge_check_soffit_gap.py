# origin_bridge_check_soffit_gap.py - run via the ORIGIN Bridge. READ-ONLY.
# User reports a visible WHITE (not black) gap near DP-S001-004 - in flat Shading mode a blank
# white area usually means genuinely NO geometry there (background showing through), not a
# lighting artifact. Ground-truths DP-S001-004's real bbox/material, every other DP-S001-* board's
# bbox (to look for a real coverage hole - a rectangular region with no board covering it), and
# every wall/column bbox nearby that the soffit is supposed to reach.
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


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

target = None
soffit_boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    if mark == "DP-S001-004":
        target = ds
    if mark.startswith("DP-S") or mark.startswith("ST-S"):
        bb = ds.get_BoundingBox(None)
        if bb is not None:
            soffit_boards.append({
                "mark": mark,
                "bbox_ft": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
            })

out = {"target_found": target is not None, "all_soffit_elements": sorted(soffit_boards, key=lambda r: r["mark"])}

if target is not None:
    tbb = target.get_BoundingBox(None)
    try:
        cm = target.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    try:
        mat_ids = target.GetMaterialIds(False)
        mat_names = [doc.GetElement(m).Name for m in mat_ids]
    except Exception as ex:
        mat_names = ["ERR: {}".format(ex)]
    tsolids = solids_of(target)
    out["target"] = {
        "comments": comments, "materials": mat_names,
        "solid_count": len(tsolids), "volume_cf": round(sum(s.Volume for s in tsolids), 5),
        "bbox_ft": {"min": [round(tbb.Min.X, 4), round(tbb.Min.Y, 4), round(tbb.Min.Z, 4)],
                    "max": [round(tbb.Max.X, 4), round(tbb.Max.Y, 4), round(tbb.Max.Z, 4)]},
    }

    # Find the soffit Ceiling element itself (its outline is the "should be covered" reference).
    ceiling_bbox = None
    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        try:
            cat = c.Category
            if cat is not None and cat.Name and "soffit" in cat.Name.lower():
                cbb = c.get_BoundingBox(None)
                if cbb is not None:
                    ceiling_bbox = {"min": [round(cbb.Min.X, 4), round(cbb.Min.Y, 4), round(cbb.Min.Z, 4)],
                                     "max": [round(cbb.Max.X, 4), round(cbb.Max.Y, 4), round(cbb.Max.Z, 4)]}
        except Exception:
            pass
    out["soffit_ceiling_bbox"] = ceiling_bbox

    # Nearby walls/columns within 3 ft that the gap might be at the edge of.
    nearby = []
    tc = XYZ((tbb.Min.X + tbb.Max.X) / 2.0, (tbb.Min.Y + tbb.Max.Y) / 2.0, (tbb.Min.Z + tbb.Max.Z) / 2.0)
    for ds in all_ds:
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            omark = mk.AsString() if mk else None
        except Exception:
            omark = None
        if not omark or omark.startswith("DP-S") or omark.startswith("ST-S") or omark.startswith("DP-K") or omark.startswith("ST-K"):
            continue
        obb = ds.get_BoundingBox(None)
        if obb is None:
            continue
        oc = XYZ((obb.Min.X + obb.Max.X) / 2.0, (obb.Min.Y + obb.Max.Y) / 2.0, (obb.Min.Z + obb.Max.Z) / 2.0)
        if tc.DistanceTo(oc) > 4.0:
            continue
        nearby.append({
            "mark": omark,
            "bbox_ft": {"min": [round(obb.Min.X, 4), round(obb.Min.Y, 4), round(obb.Min.Z, 4)],
                        "max": [round(obb.Max.X, 4), round(obb.Max.Y, 4), round(obb.Max.Z, 4)]},
        })
    out["nearby_non_soffit_elements"] = nearby

OUT = out
