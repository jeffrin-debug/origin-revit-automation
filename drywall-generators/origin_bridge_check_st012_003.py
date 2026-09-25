# origin_bridge_check_st012_003.py - run via the ORIGIN Bridge. READ-ONLY.
# User report: ST-012-003 (soffit band-wall framing, rendered as a flat slab matching drywall) now
# sits with a slight "bump" - not level/flush with its neighbor drywall panel DP-006-001A. Ground-
# truths both elements' real bboxes, materials, and face-normal-direction extent to find the exact
# offset before touching anything.
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

TARGET_MARKS = ["ST-012-003", "DP-006-001A", "DP-012-001A", "DP-012-002A", "ST-012-001", "ST-012-002"]


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
found = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in TARGET_MARKS:
        try:
            cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        try:
            matp = ds.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
            mat_name = None
            if matp:
                mid = matp.AsElementId()
                if mid and mid.IntegerValue > 0:
                    me = doc.GetElement(mid)
                    mat_name = me.Name if me else None
        except Exception:
            mat_name = None
        bb = ds.get_BoundingBox(None)
        found[mark] = {
            "comments": comments,
            "material": mat_name,
            "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                     "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
            "_ds": ds,
        }

out = {"found_marks": list(found.keys())}
for mk, rec in found.items():
    out[mk] = {"comments": rec["comments"], "material": rec["material"], "bbox": rec["bbox"]}

if "ST-012-003" in found and "DP-006-001A" in found:
    a = found["ST-012-003"]["bbox"]
    b = found["DP-006-001A"]["bbox"]
    out["axis_overlap_in"] = {
        "x": round((min(a["max"][0], b["max"][0]) - max(a["min"][0], b["min"][0])) * 12.0, 4),
        "y": round((min(a["max"][1], b["max"][1]) - max(a["min"][1], b["min"][1])) * 12.0, 4),
        "z": round((min(a["max"][2], b["max"][2]) - max(a["min"][2], b["min"][2])) * 12.0, 4),
    }
    max_ov = 0.0
    for s1 in solids_of(found["ST-012-003"]["_ds"]):
        for s2 in solids_of(found["DP-006-001A"]["_ds"]):
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                    s1, s2, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > max_ov:
                    max_ov = inter.Volume
            except Exception:
                continue
    out["real_overlap_cf"] = round(max_ov, 8)

OUT = out
