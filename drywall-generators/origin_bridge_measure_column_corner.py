# origin_bridge_measure_column_corner.py - run via the ORIGIN Bridge. READ-ONLY.
# Precisely measures real gaps AND real overlaps between the 7 currently-relevant elements at the
# K001 column corner: the column's 4 drywall boards (DP-K001-001/003/005/007) and wall 010's 3
# boards touching the same corner (DP-010-001B/003B/006B) - every pairwise combination, real
# boolean intersection for overlap, closest-approach distance for gap.
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

MARKS = ["DP-K001-001", "DP-K001-003", "DP-K001-005", "DP-K001-007",
         "DP-010-001B", "DP-010-003B", "DP-010-006B"]


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


elems = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in MARKS:
        bb = ds.get_BoundingBox(None)
        try:
            mat_ids = ds.GetMaterialIds(False)
            mat_names = [doc.GetElement(m).Name for m in mat_ids]
        except Exception:
            mat_names = []
        elems[mark] = {
            "ds": ds, "solids": solids_of(ds), "materials": mat_names,
            "bbox_ft": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                        "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]} if bb else None,
        }

found = list(elems.keys())
pairs = []
keys = list(elems.keys())
for i in range(len(keys)):
    for j in range(i + 1, len(keys)):
        m1, m2 = keys[i], keys[j]
        e1, e2 = elems[m1], elems[m2]
        # bbox-based closest distance (rough gap indicator, both directions)
        b1, b2 = e1["bbox_ft"], e2["bbox_ft"]
        gaps = []
        for ax in range(3):
            gap = max(b1["min"][ax] - b2["max"][ax], b2["min"][ax] - b1["max"][ax], 0.0)
            gaps.append(gap)
        bbox_gap_ft = max(gaps)  # 0 if bboxes touch/overlap on all axes

        max_ov = 0.0
        for s1 in e1["solids"]:
            for s2 in e2["solids"]:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if bbox_gap_ft < 0.5 or max_ov > 1e-9:
            pairs.append({
                "pair": [m1, m2],
                "bbox_gap_in": round(bbox_gap_ft * 12.0, 4),
                "real_overlap_cf": round(max_ov, 6),
            })

OUT = {
    "found_marks": found,
    "not_found_marks": [m for m in MARKS if m not in found],
    "element_details": {m: {"bbox_ft": elems[m]["bbox_ft"], "materials": elems[m]["materials"]} for m in found},
    "pairwise_gap_and_overlap": pairs,
}
