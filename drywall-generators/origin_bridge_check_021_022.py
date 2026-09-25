# origin_bridge_check_021_022.py - run via the ORIGIN Bridge. READ-ONLY.
# Full dump + real overlap check for the DP-021-001B vs DP-022-001B conflict found by the
# overlap sweep on "Project -1111", plus their host walls' own geometry, to find the root
# cause before fixing.
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

TARGET_MARKS = ["DP-021-001A", "DP-021-001B", "DP-022-001A", "DP-022-001B"]


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

# Real boolean-intersection check between the two conflicting boards.
by_mark = {r["mark"]: ds for ds, r in zip(
    [d for d in all_ds if (lambda m: m in TARGET_MARKS)(
        (lambda p: p.AsString() if p else None)(d.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)))],
    out)}

real_overlap = None
try:
    a = by_mark.get("DP-021-001B")
    b = by_mark.get("DP-022-001B")
    if a is not None and b is not None:
        def solids_of(ds):
            opt = Options()
            opt.ComputeReferences = False
            geo = ds.get_Geometry(opt)
            sub = []
            for g in geo:
                if isinstance(g, Solid) and g.Volume > 1e-9:
                    sub.append(g)
            return sub

        sa = solids_of(a)
        sb = solids_of(b)
        total = 0.0
        for s1 in sa:
            for s2 in sb:
                try:
                    diff = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if diff is not None:
                        total += diff.Volume
                except Exception:
                    pass
        real_overlap = round(total, 6)
except Exception as ex:
    real_overlap = "error: %s" % ex

OUT = {"elements": out, "wall_info": wall_info, "real_overlap_cf": real_overlap}
