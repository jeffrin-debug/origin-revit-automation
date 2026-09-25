# diag_beams.py - read-only: every beam, its drywall boards, and the gaps where boards meet.
#
# For each structural-framing member: its bbox, the ORIGIN_BEAM_V1 boards hosted on it, how far
# those boards fall short of the beam's own faces, and every near-miss between two boards (the
# beam's own, or a beam board against a wall/ceiling panel) - pairs closer than NEAR_IN that do
# not actually touch. Gaps are per-axis separations in inches; a negative value is an overlap.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

NEAR_IN = 6.0           # report board pairs whose boxes come within this
TOUCH_IN = 0.02         # closer than this on every axis = touching

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title}


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def IN(v):
    return round(v * 12.0, 2)


def eid(e):
    return e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value


def box(e):
    bb = e.get_BoundingBox(None)
    if bb is None:
        return None
    return [(bb.Min.X * 12, bb.Max.X * 12), (bb.Min.Y * 12, bb.Max.Y * 12), (bb.Min.Z * 12, bb.Max.Z * 12)]


def seps(a, b):
    """Per-axis separation (in): >0 gap, <0 overlap depth."""
    return [round(max(a[i][0] - b[i][1], b[i][0] - a[i][1]), 2) for i in range(3)]


def fmt(b):
    return {"x": [round(b[0][0], 2), round(b[0][1], 2)],
            "y": [round(b[1][0], 2), round(b[1][1], 2)],
            "z": [round(b[2][0], 2), round(b[2][1], 2)]}


# every generated board, tagged by source
boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    cm = par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if not cm.startswith("ORIGIN"):
        continue
    mk = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if not mk.startswith("DP-"):
        continue
    b = box(ds)
    if b is None:
        continue
    host = ""
    for tok in cm.split("|"):
        tok = tok.strip()
        if tok.startswith("HOST="):
            host = tok[5:]
    boards.append({"mark": mk, "app": cm.split("|")[0].strip(), "host": host,
                   "comments": cm[:160], "box": b})

beam_boards = [b for b in boards if b["app"] == "ORIGIN_BEAM_V1"]
other_boards = [b for b in boards if b["app"] != "ORIGIN_BEAM_V1"]
res["board_totals"] = {"beam": len(beam_boards), "other": len(other_boards)}

beams = []
for fm in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming) \
        .WhereElementIsNotElementType():
    bb = box(fm)
    if bb is None:
        continue
    bid = str(eid(fm))
    mine = [b for b in beam_boards if b["host"] == bid]
    row = {"id": eid(fm), "mark": par(fm, BuiltInParameter.ALL_MODEL_MARK),
           "type": fm.Name, "bbox": fmt(bb),
           "size_in": [round(bb[i][1] - bb[i][0], 2) for i in range(3)],
           "board_count": len(mine),
           "boards": [dict(mark=b["mark"], **fmt(b["box"])) for b in sorted(mine, key=lambda r: r["mark"])]}

    # coverage: how far the union of this beam's boards falls short of the beam's bbox
    if mine:
        u = [(min(b["box"][i][0] for b in mine), max(b["box"][i][1] for b in mine)) for i in range(3)]
        row["coverage_short_in"] = {
            ax: {"min_side": round(u[i][0] - bb[i][0], 2), "max_side": round(bb[i][1] - u[i][1], 2)}
            for i, ax in enumerate("xyz")}

    # near-misses: this beam's boards against each other and against any other board nearby
    near = []
    for i, a in enumerate(mine):
        for b in mine[i + 1:] + other_boards:
            s = seps(a["box"], b["box"])
            if max(s) > NEAR_IN:
                continue
            gap = max(s)
            if gap > TOUCH_IN:
                state = "GAP"
            elif gap < -TOUCH_IN:
                state = "OVERLAP"                   # interpenetrating on all three axes
            else:
                continue                            # touching cleanly
            near.append({"a": a["mark"], "b": b["mark"], "b_app": b["app"], "state": state,
                         "sep_x": s[0], "sep_y": s[1], "sep_z": s[2], "gap_in": round(gap, 2)})
    near.sort(key=lambda r: (r["state"] != "GAP", r["gap_in"]))
    row["issues"] = near
    row["gap_count"] = sum(1 for r in near if r["state"] == "GAP")
    row["overlap_count"] = sum(1 for r in near if r["state"] == "OVERLAP")
    beams.append(row)

res["beam_count"] = len(beams)
res["beams_without_boards"] = [b["id"] for b in beams if b["board_count"] == 0]
res["beams"] = beams
OUT = res
