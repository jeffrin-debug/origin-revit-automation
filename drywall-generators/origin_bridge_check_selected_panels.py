# origin_bridge_check_selected_panels.py - run via the ORIGIN Bridge. READ-ONLY.
# Face-dump + overlap check for the currently-selected DirectShape(s), by element id, to diagnose
# a reported "extruding"/abnormal-thickness issue on a specific selected panel.
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

TARGET_EIDS = [412520, 412788]


def solids_of(e):
    out = []
    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    out.append(g2)
    return out


def dump_solid(s):
    bb = s.GetBoundingBox()
    mn = bb.Transform.OfPoint(bb.Min)
    mx = bb.Transform.OfPoint(bb.Max)
    xs, ys, zs = (mx.X - mn.X), (mx.Y - mn.Y), (mx.Z - mn.Z)
    thin_axis = None
    if xs < 0.15 and ys >= 0.15:
        thin_axis = "X"
    elif ys < 0.15 and xs >= 0.15:
        thin_axis = "Y"
    thin_span_in = round((xs if thin_axis == "X" else ys) * 12.0, 4) if thin_axis else None
    return {
        "face_count": s.Faces.Size, "volume_cf": round(s.Volume, 5),
        "bbox_min": [round(mn.X, 4), round(mn.Y, 4), round(mn.Z, 4)],
        "bbox_max": [round(mx.X, 4), round(mx.Y, 4), round(mx.Z, 4)],
        "x_span_in": round(xs * 12.0, 4), "y_span_in": round(ys * 12.0, 4),
        "z_span_ft": round(zs, 4), "thin_axis": thin_axis, "thin_span_in": thin_span_in,
    }


results = []
all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType())
for eid in TARGET_EIDS:
    e = doc.GetElement(ElementId(eid))
    entry = {"eid": eid, "exists": e is not None}
    if e is None:
        results.append(entry)
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    entry["mark"] = mark
    entry["comments"] = comments
    mysolids = solids_of(e)
    entry["solid_count"] = len(mysolids)
    entry["solids"] = [dump_solid(s) for s in mysolids]

    # Broad-phase overlap scan against every other real ST-/DP- element in the model.
    bb = e.get_BoundingBox(None)
    overlaps = []
    if bb is not None and mysolids:
        pad = 0.02
        for other in all_ds:
            if other.Id.IntegerValue == eid if hasattr(other.Id, "IntegerValue") else other.Id.Value == eid:
                continue
            try:
                omk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                omark = omk.AsString() if omk else None
            except Exception:
                omark = None
            if not omark or not (omark.startswith("DP-") or omark.startswith("ST-")):
                continue
            obb = other.get_BoundingBox(None)
            if obb is None:
                continue
            if (obb.Max.X < bb.Min.X - pad or obb.Min.X > bb.Max.X + pad or
                    obb.Max.Y < bb.Min.Y - pad or obb.Min.Y > bb.Max.Y + pad or
                    obb.Max.Z < bb.Min.Z - pad or obb.Min.Z > bb.Max.Z + pad):
                continue
            osolids = solids_of(other)
            if not osolids:
                continue
            for s1 in mysolids:
                for s2 in osolids:
                    try:
                        inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                            s1, s2, BooleanOperationsType.Intersect)
                        if inter is not None and inter.Volume > 1e-7:
                            overlaps.append({"other_mark": omark, "overlap_cf": round(inter.Volume, 6)})
                    except Exception as ex:
                        overlaps.append({"other_mark": omark, "error": str(ex)})
    entry["overlaps"] = overlaps
    results.append(entry)

OUT = {"panels": results}
