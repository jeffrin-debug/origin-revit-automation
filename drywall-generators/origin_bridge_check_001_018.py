# origin_bridge_check_001_018.py - run via the ORIGIN Bridge. READ-ONLY.
# Full dump + real overlap check for the DP-001-008B vs DP-018-003A conflict found on "Project8" -
# no matching "would erase" warning was logged for this pair, so it needs its own root-cause look.
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

TARGET_MARKS = ["DP-001-008A", "DP-001-008B", "DP-018-003A", "DP-018-003B"]


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

out = []
hosts = set()
ds_by_mark = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGET_MARKS:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    host = host_of(comments)
    if host:
        hosts.add(host)
    ds_by_mark[mark] = ds
    bb = ds.get_BoundingBox(None)
    out.append({
        "mark": mark, "comments": comments, "host": host,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })
out.sort(key=lambda r: r["mark"])

wall_info = []
for h in sorted(hosts):
    if not h.startswith("WALL=W"):
        continue
    try:
        eid = int(h.replace("WALL=W", ""))
    except Exception:
        continue
    w = doc.GetElement(ElementId(eid))
    if isinstance(w, Wall):
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        wall_info.append({
            "host": h, "eid": eid, "width_in": round(w.Width * 12.0, 3),
            "p0": [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)],
            "p1": [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)],
        })


def solids_of(ds):
    opt = Options()
    opt.ComputeReferences = False
    geo = ds.get_Geometry(opt)
    sub = []
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9:
            sub.append(g)
    return sub


def real_overlap(mark_a, mark_b):
    a = ds_by_mark.get(mark_a)
    b = ds_by_mark.get(mark_b)
    if a is None or b is None:
        return None
    sa = solids_of(a)
    sb = solids_of(b)
    total = 0.0
    a_vol = sum(s.Volume for s in sa)
    b_vol = sum(s.Volume for s in sb)
    for s1 in sa:
        for s2 in sb:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                    s1, s2, BooleanOperationsType.Intersect)
                if inter is not None:
                    total += inter.Volume
            except Exception:
                pass
    return {"overlap_cf": round(total, 6), "a_vol_cf": round(a_vol, 6), "b_vol_cf": round(b_vol, 6)}


overlap = real_overlap("DP-001-008B", "DP-018-003A")

OUT = {"elements": out, "wall_info": wall_info, "overlap": overlap}
