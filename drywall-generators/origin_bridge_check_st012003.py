# origin_bridge_check_st012003.py - run via the ORIGIN Bridge. READ-ONLY.
# Ground truth for ST-012-003 (flagged as "unusual"): full details + every other element on wall
# 012 (both ST- framing and DP- drywall) for direct comparison, real solid volume/bbox for each,
# plus a real boolean-overlap check of ST-012-003 against everything nearby.
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


def bbox_center(bb):
    return XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

wall012_elements = []
target = None
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or "-012-" not in mark:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    solids = solids_of(ds)
    entry = {
        "mark": mark,
        "element_id": ds.Id.Value if hasattr(ds.Id, "Value") else ds.Id.IntegerValue,
        "comments": comments,
        "solid_count": len(solids),
        "total_volume_cf": round(sum(s.Volume for s in solids), 5),
        "bbox_ft": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                    "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]} if bb else None,
    }
    wall012_elements.append(entry)
    if mark == "ST-012-003":
        target = (ds, entry)

wall012_elements.sort(key=lambda r: r["mark"])

out = {"wall_012_elements": wall012_elements}

if target is not None:
    tds, tentry = target
    tbb = tds.get_BoundingBox(None)
    tc = bbox_center(tbb)
    tsolids = solids_of(tds)
    overlaps = []
    for ds in all_ds:
        if ds.Id == tds.Id:
            continue
        obb = ds.get_BoundingBox(None)
        if obb is None:
            continue
        if tc.DistanceTo(bbox_center(obb)) > 4.0:
            continue
        osolids = solids_of(ds)
        if not osolids:
            continue
        max_ov = 0.0
        for s1 in tsolids:
            for s2 in osolids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if max_ov > 1e-7:
            try:
                omk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                omark = omk.AsString() if omk else None
            except Exception:
                omark = None
            overlaps.append({"other_mark": omark, "overlap_cf": round(max_ov, 5)})
    out["ST_012_003_real_overlaps_nearby"] = overlaps
else:
    out["ST_012_003_not_found"] = True

OUT = out
