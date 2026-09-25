# diag_fins.py - find drywall boards that stick out past the corner they wrap.
#
# At an outside corner one wall's board deliberately runs past the wall end to cover the
# adjacent wall's drywall edge (corner_face_extents: "one panel runs past the wall end to the
# adjacent wall's outer drywall face and the other butts under it"). That is correct ONLY if it
# stops AT that outer face. If it overshoots, the surplus sticks out into open air as a thin
# fin - which is what reads as a stud-shaped shard welded to the panel, in every view, because
# it is a DP- element and no filter can tell it from real board.
#
# CORNER_OVERSHOOT_MAX_FT is 2.0 ft in the generator, so there is a lot of room to overshoot.
#
# This measures it: for every board, look along its own length axis at each end, find any
# PERPENDICULAR board near that end, and report how far this board's end passes beyond that
# board's far face. Read-only.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

REPORT_ABOVE_IN = 0.05      # ignore hairlines
NEAR_IN = 12.0              # a perpendicular board this close to the end counts as the corner

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title}


def par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def IN(v):
    return v * 12.0


boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    m = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if not m.startswith("DP-"):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    x0, x1 = IN(bb.Min.X), IN(bb.Max.X)
    y0, y1 = IN(bb.Min.Y), IN(bb.Max.Y)
    z0, z1 = IN(bb.Min.Z), IN(bb.Max.Z)
    dx, dy = x1 - x0, y1 - y0
    # A board is a thin sheet: one plan dimension is its thickness, the other its length.
    if dx < dy:
        axis, thick = "y", "x"          # runs along Y, thin in X
    else:
        axis, thick = "x", "y"
    boards.append({"mark": m, "x": (x0, x1), "y": (y0, y1), "z": (z0, z1),
                   "axis": axis, "thick": thick,
                   "infill": "CORNERINFILL=1" in par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)})

res["boards"] = len(boards)

fins = []
for b in boards:
    ax = b["axis"]
    lo, hi = b[ax]
    for other in boards:
        if other is b or other["axis"] == ax:
            continue                     # want the PERPENDICULAR one
        # the perpendicular board's thin direction is b's length axis: its faces are two
        # planes at constant value along ax
        of0, of1 = other[ax]
        # must overlap in Z to be the same corner
        if other["z"][1] <= b["z"][0] + 1e-6 or other["z"][0] >= b["z"][1] - 1e-6:
            continue
        # and must sit across b's own thin direction (i.e. actually at this corner)
        tk = b["thick"]
        if other[tk][1] < b[tk][0] - NEAR_IN or other[tk][0] > b[tk][1] + NEAR_IN:
            continue
        # how far does b pass beyond the far face of `other`, at each end?
        # end HI: b runs up to hi; other occupies of0..of1. Overshoot = hi - of1
        over_hi = hi - of1
        over_lo = of0 - lo
        for (end, over) in (("hi", over_hi), ("lo", over_lo)):
            if over <= REPORT_ABOVE_IN:
                continue
            # only a real fin if b actually reaches this corner - its end must be near `other`
            reach = (abs(hi - of1) if end == "hi" else abs(lo - of0))
            if reach > NEAR_IN:
                continue
            fins.append({"board": b["mark"], "end": end,
                         "past_perpendicular_face_in": round(over, 3),
                         "against": other["mark"],
                         "infill": b["infill"],
                         "b_axis": ax})

# one worst entry per board
best = {}
for f in fins:
    k = f["board"]
    if k not in best or f["past_perpendicular_face_in"] > best[k]["past_perpendicular_face_in"]:
        best[k] = f
rows = sorted(best.values(), key=lambda r: -r["past_perpendicular_face_in"])

res["boards_with_a_fin"] = len(rows)
res["total_checked"] = len(boards)
buckets = {"over_2in": 0, "0.5_to_2in": 0, "under_0.5in": 0}
for r in rows:
    v = r["past_perpendicular_face_in"]
    if v > 2.0:
        buckets["over_2in"] += 1
    elif v >= 0.5:
        buckets["0.5_to_2in"] += 1
    else:
        buckets["under_0.5in"] += 1
res["buckets"] = buckets
res["worst"] = rows[:15]
OUT = res
