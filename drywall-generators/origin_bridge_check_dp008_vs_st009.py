# origin_bridge_check_dp008_vs_st009.py - run via the ORIGIN Bridge. READ-ONLY.
# User's precise requirement: DP-008-002B should stop exactly where ST-009-001 (wall 009's own
# framing) starts. Ground-truths both elements' real bboxes/comments plus nearby context (the
# K001 column boards, and wall 009's own first drywall board) so the exact geometric relationship
# can be measured before any fix is designed.
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

TARGET_MARKS = ["DP-008-002B", "ST-009-001", "DP-009-001B", "DP-K001-001", "DP-K001-003"]


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
        bb = ds.get_BoundingBox(None)
        found[mark] = {
            "comments": comments,
            "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                     "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
            "_ds": ds,
        }

out = {"found_marks": list(found.keys())}
for mk, rec in found.items():
    out[mk] = {"comments": rec["comments"], "bbox": rec["bbox"]}

if "DP-008-002B" in found and "ST-009-001" in found:
    wb = found["DP-008-002B"]["bbox"]
    sb = found["ST-009-001"]["bbox"]
    ov_x = min(wb["max"][0], sb["max"][0]) - max(wb["min"][0], sb["min"][0])
    ov_y = min(wb["max"][1], sb["max"][1]) - max(wb["min"][1], sb["min"][1])
    ov_z = min(wb["max"][2], sb["max"][2]) - max(wb["min"][2], sb["min"][2])
    out["DP-008-002B_vs_ST-009-001_axis_overlap_in"] = {
        "x": round(ov_x * 12.0, 4), "y": round(ov_y * 12.0, 4), "z": round(ov_z * 12.0, 4)}
    max_ov = 0.0
    for s1 in solids_of(found["DP-008-002B"]["_ds"]):
        for s2 in solids_of(found["ST-009-001"]["_ds"]):
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                    s1, s2, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > max_ov:
                    max_ov = inter.Volume
            except Exception:
                continue
    out["DP-008-002B_vs_ST-009-001_real_overlap_cf"] = round(max_ov, 8)

# Also fetch the real Wall 009 element's own geometry for reference (location line, width).
try:
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and mk.AsString() == "009":
            lc = w.Location.Curve
            out["wall_009_location"] = {
                "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                "width_ft": round(w.Width, 4),
            }
            break
except Exception as ex:
    out["wall_009_location_error"] = str(ex)

OUT = out
