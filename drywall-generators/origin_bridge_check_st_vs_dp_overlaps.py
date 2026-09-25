# origin_bridge_check_st_vs_dp_overlaps.py - run via the ORIGIN Bridge. READ-ONLY.
# Full model sweep, but reports ONLY ST-vs-DP real overlaps (any magnitude > 1e-6 cf),
# with no truncation - the general sweep only samples the first 20 pairs found, which
# isn't enough to confirm the same-host-stud fix cleared every clamped-depth wall.
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


elems = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-") or mark.startswith("ST-")):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    elems.append((mark, ds, bb))

st_dp_findings = []
n = len(elems)
for i in range(n):
    m1, ds1, b1 = elems[i]
    for j in range(i + 1, n):
        m2, ds2, b2 = elems[j]
        is_st_dp = (m1.startswith("ST-") and m2.startswith("DP-")) or (m1.startswith("DP-") and m2.startswith("ST-"))
        if not is_st_dp:
            continue
        if (b1.Max.X <= b2.Min.X or b2.Max.X <= b1.Min.X or
                b1.Max.Y <= b2.Min.Y or b2.Max.Y <= b1.Min.Y or
                b1.Max.Z <= b2.Min.Z or b2.Max.Z <= b1.Min.Z):
            continue
        max_ov = 0.0
        for s1 in solids_of(ds1):
            for s2 in solids_of(ds2):
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if max_ov > 1e-6:
            st_dp_findings.append({"a": m1, "b": m2, "overlap_cf": round(max_ov, 6)})

OUT = {
    "elements_scanned": n,
    "st_vs_dp_overlap_count": len(st_dp_findings),
    "st_vs_dp_findings": st_dp_findings,
}
