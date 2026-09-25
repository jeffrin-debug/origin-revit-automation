# origin_bridge_check_022_023.py - run via the ORIGIN Bridge. READ-ONLY.
# Full dump of every ST-*/DP-* element for wall hosts 022 (W383245) and 023 (W383365), plus a real
# boolean overlap sweep between the two hosts, to investigate the user-reported "walls overlapping"
# and "ST-023-001 has no drywall panel" findings.
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

TAGS = ["WALL=W383245", "WALL=W383365"]


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


elems = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or not any(t in comments for t in TAGS):
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = ds.get_BoundingBox(None)
    elems.append({
        "ds": ds, "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
    })
elems.sort(key=lambda r: r["mark"] or "")

# Real boolean overlaps between any pair of these elements (022 vs 023 mostly, but check all pairs)
findings = []
n = len(elems)
for i in range(n):
    for j in range(i + 1, n):
        a, b = elems[i], elems[j]
        ba, bb_ = a["bbox"], b["bbox"]
        if ba is None or bb_ is None:
            continue
        if (ba["max"][0] < bb_["min"][0] or bb_["max"][0] < ba["min"][0] or
                ba["max"][1] < bb_["min"][1] or bb_["max"][1] < ba["min"][1] or
                ba["max"][2] < bb_["min"][2] or bb_["max"][2] < ba["min"][2]):
            continue
        max_ov = 0.0
        for s1 in solids_of(a["ds"]):
            for s2 in solids_of(b["ds"]):
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if max_ov > 1e-7:
            findings.append({"a": a["mark"], "b": b["mark"], "real_overlap_cf": round(max_ov, 6)})

OUT = {
    "elements": [{"mark": e["mark"], "comments": e["comments"], "bbox": e["bbox"]} for e in elems],
    "overlap_findings": findings,
}
