# diag_intrusion.py - is any framing STILL physically inside a drywall board?
#
# Bounding boxes lie here: a C-stud is formed sheet metal, so its bbox volume is many times its
# real solid volume. The only honest test is a boolean intersect of the actual solids, which is
# what this does - model-wide, read-only, no transaction.
#
# Reports, per board, the real intersecting volume left after trim_drywall_from_neighbor_studs
# has run. Anything above a hairline is a genuine unresolved clash.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

REPORT_ABOVE_CUIN = 0.05        # ignore hairline coincidences
doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "threshold_cuin": REPORT_ABOVE_CUIN}


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def solids_of(e):
    opt = Options()
    opt.ComputeReferences = False
    opt.DetailLevel = ViewDetailLevel.Fine
    out = []
    try:
        for g in e.get_Geometry(opt):
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


boards, framing = [], []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    m = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if not m:
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    rec = (ds, m, bb)
    if m.startswith("DP-"):
        boards.append(rec)
    elif m.startswith("ST-") or m.startswith("DF-"):
        framing.append(rec)

res["boards"] = len(boards)
res["framing"] = len(framing)


def bb_hit(a, b, pad=0.0):
    return not (a.Min.X > b.Max.X + pad or a.Max.X < b.Min.X - pad or
                a.Min.Y > b.Max.Y + pad or a.Max.Y < b.Min.Y - pad or
                a.Min.Z > b.Max.Z + pad or a.Max.Z < b.Min.Z - pad)


hits = []
checked = 0
errors = 0
for (bds, bm, bbb) in boards:
    bsolids = None
    for (fds, fm, fbb) in framing:
        if not bb_hit(bbb, fbb):
            continue
        if bsolids is None:
            bsolids = solids_of(bds)
            if not bsolids:
                break
        for fs in solids_of(fds):
            for bs in bsolids:
                checked += 1
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        bs, fs, BooleanOperationsType.Intersect)
                except Exception:
                    errors += 1
                    continue
                if inter is None:
                    continue
                v_cuin = inter.Volume * 1728.0
                if v_cuin > REPORT_ABOVE_CUIN:
                    hits.append({"board": bm, "framing": fm,
                                 "volume_cuin": round(v_cuin, 3),
                                 "same_host": (par(bds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                                               .split("WALL=")[-1].split("|")[0].strip()
                                               == par(fds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                                               .split("WALL=")[-1].split("|")[0].strip())})

hits.sort(key=lambda r: -r["volume_cuin"])
by_kind = {"stud_ST": 0, "doorframe_DF": 0}
for h in hits:
    if h["framing"].startswith("ST-"):
        by_kind["stud_ST"] += 1
    else:
        by_kind["doorframe_DF"] += 1

res["pairs_boolean_tested"] = checked
res["boolean_errors"] = errors
res["intrusions_found"] = len(hits)
res["by_kind"] = by_kind
res["total_intruding_cuin"] = round(sum(h["volume_cuin"] for h in hits), 3)
res["worst"] = hits[:15]
OUT = res
