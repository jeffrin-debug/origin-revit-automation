# origin_bridge_check_395748_intrusion.py - run via the ORIGIN Bridge. READ-ONLY.
# Direct, by-mark real-boolean check: does DP-003-002A/004A/006A (wall 395748) currently intersect
# ST-004-001 (wall 380854's corner stud)? Confirms whether the intrusion is still present after
# the most recent isolated re-run of wall 395748 alone.
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

TARGETS = ["DP-003-002A", "DP-003-004A", "DP-003-006A", "ST-004-001"]


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


by_mark = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in TARGETS:
        by_mark[mark] = ds

pairs = []
stud = by_mark.get("ST-004-001")
for m in ("DP-003-002A", "DP-003-004A", "DP-003-006A"):
    ds = by_mark.get(m)
    if ds is None or stud is None:
        pairs.append({"a": m, "b": "ST-004-001", "found_a": ds is not None, "found_b": stud is not None})
        continue
    bb1 = ds.get_BoundingBox(None)
    bb2 = stud.get_BoundingBox(None)
    max_ov = 0.0
    for s1 in solids_of(ds):
        for s2 in solids_of(stud):
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(s1, s2, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > max_ov:
                    max_ov = inter.Volume
            except Exception:
                continue
    pairs.append({
        "a": m, "b": "ST-004-001", "real_overlap_cf": round(max_ov, 6),
        "a_bbox": {"min": [round(bb1.Min.X, 3), round(bb1.Min.Y, 3), round(bb1.Min.Z, 3)],
                   "max": [round(bb1.Max.X, 3), round(bb1.Max.Y, 3), round(bb1.Max.Z, 3)]},
        "b_bbox": {"min": [round(bb2.Min.X, 3), round(bb2.Min.Y, 3), round(bb2.Min.Z, 3)],
                   "max": [round(bb2.Max.X, 3), round(bb2.Max.Y, 3), round(bb2.Max.Z, 3)]},
    })

OUT = {"pairs": pairs}
