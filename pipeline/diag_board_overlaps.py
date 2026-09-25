# diag_board_overlaps.py - read-only: every pair of wall/ceiling drywall boards that interpenetrate.
#
# Bounding boxes pre-filter; the real test is a boolean Intersect of the two solids, so boards that
# merely touch (a butt joint, a lapped corner) are NOT reported. Used as a before/after guard when
# a corner or layout rule changes.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
MIN_CUIN = 0.01          # ignore numerical dust


def par(e, b):
    p = e.get_Parameter(b)
    return (p.AsString() or "") if p else ""


boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    cm = par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    mk = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if not cm.startswith("ORIGIN") or not mk.startswith("DP-"):
        continue
    bb = ds.get_BoundingBox(None)
    sol = [g for g in (ds.get_Geometry(Options()) or []) if isinstance(g, Solid) and g.Volume > 1e-9]
    if bb is not None and sol:
        boards.append((mk, bb, sol))

hits = []
for i in range(len(boards)):
    ma, a, sa = boards[i]
    for j in range(i + 1, len(boards)):
        mb, b, sb = boards[j]
        if (a.Max.X <= b.Min.X or b.Max.X <= a.Min.X or a.Max.Y <= b.Min.Y or b.Max.Y <= a.Min.Y or
                a.Max.Z <= b.Min.Z or b.Max.Z <= a.Min.Z):
            continue
        vol = 0.0
        for x in sa:
            for y in sb:
                try:
                    r = BooleanOperationsUtils.ExecuteBooleanOperation(x, y, BooleanOperationsType.Intersect)
                    if r is not None:
                        vol += r.Volume
                except Exception:
                    pass
        cuin = vol * 1728.0
        if cuin > MIN_CUIN:
            hits.append({"a": ma, "b": mb, "cu_in": round(cuin, 3)})
hits.sort(key=lambda h: -h["cu_in"])
OUT = {"boards": len(boards), "overlapping_pairs": len(hits), "pairs": hits}
