# origin_bridge_probe_wall_vs_ceiling.py - READ-ONLY.
# Quantify how far the generated WALL drywall runs past the ceiling plane it meets.
#
# The wall generator tiles courses over [0, wall_height] and never consults a ceiling (only
# soffit-category elements clip it), so a wall taller than the ceiling it sits under keeps
# producing board above the ceiling line. This measures that directly on the live model:
# for every generated wall drywall board, find the ceilings whose plan footprint it touches and
# report board_top_z - ceiling_bottom_z.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

WALL_APP_ID = "ORIGIN_ASSEMBLY_V4"
TOL_FT = 0.02          # ignore sub-1/4in noise


def bbox_of(e):
    try:
        bb = e.get_BoundingBox(None)
        if bb is None:
            return None
        return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    except Exception:
        return None


def solids_of(e):
    out = []
    try:
        geo = e.get_Geometry(Options())
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


def make_box(x0, y0, z0, x1, y1, z1):
    try:
        pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[CurveLoop]()
        loops.Add(loop)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)
    except Exception:
        return None


def plan_overlap(a, b):
    """True when two bboxes overlap in plan with a real (non-touching) area."""
    return not (a[3] <= b[0] + TOL_FT or b[3] <= a[0] + TOL_FT or
                a[4] <= b[1] + TOL_FT or b[4] <= a[1] + TOL_FT)


# ---- ceilings: plan extent + bottom-face elevation -------------------------------------------
ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    bb = bbox_of(c)
    if bb is None:
        continue
    mk = None
    try:
        p = c.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mk = p.AsString() if p else None
    except Exception:
        pass
    ceilings.append({"id": c.Id.IntegerValue if hasattr(c.Id, "IntegerValue") else c.Id.Value,
                     "mark": mk, "bb": bb, "z_bottom": bb[2], "z_top": bb[5],
                     "solids": solids_of(c)})

# ---- generated wall drywall boards ------------------------------------------------------------
boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comment = (p.AsString() or "") if p else ""
    except Exception:
        comment = ""
    if not comment.startswith(WALL_APP_ID + " |") or "| DRYWALL" not in comment:
        continue
    mk = None
    try:
        pm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mk = pm.AsString() if pm else None
    except Exception:
        pass
    if not mk or not mk.startswith("DP-"):
        continue
    bb = bbox_of(ds)
    if bb is None:
        continue
    boards.append({"mark": mk, "bb": bb})

# ---- compare -----------------------------------------------------------------------------------
def really_under(cx, cy, cp):
    """Is (cx, cy) genuinely inside this ceiling's real footprint? A plan BOUNDING BOX says yes for
    any point in the rectangle spanning an L-shaped or concave room, which over-reports badly on
    this model. Probe the ceiling's actual solid instead - the same test the generator's
    face_ceiling_cap() uses, so probe and generator agree on what 'under a ceiling' means."""
    zc = cp["z_bottom"]
    probe = None
    try:
        probe = make_box(cx - 0.05, cy - 0.05, zc + 0.01, cx + 0.05, cy + 0.05, zc + 0.05)
    except Exception:
        return False
    if probe is None:
        return False
    for s in cp.get("solids", []):
        try:
            inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                probe, s, BooleanOperationsType.Intersect)
        except Exception:
            continue
        if inter is not None and inter.Volume > 1e-9:
            return True
    return False


offenders = []
clean = 0
no_ceiling = 0
bbox_only = 0
per_wall = {}

for b in boards:
    bb = b["bb"]
    cx = (bb[0] + bb[3]) / 2.0
    cy = (bb[1] + bb[4]) / 2.0
    met = [c for c in ceilings
           if plan_overlap(bb, c["bb"]) and really_under(cx, cy, c)]
    if not met:
        no_ceiling += 1
        if any(plan_overlap(bb, c["bb"]) for c in ceilings):
            bbox_only += 1
        continue
    # the lowest ceiling this board runs into is the one it should stop at
    lowest = min(met, key=lambda c: c["z_bottom"])
    over = bb[5] - lowest["z_bottom"]
    if over > TOL_FT:
        wall_tag = b["mark"].split("-")[1] if len(b["mark"].split("-")) > 2 else "?"
        rec = {"board": b["mark"], "wall": wall_tag,
               "board_top_ft": round(bb[5], 3),
               "ceiling_bottom_ft": round(lowest["z_bottom"], 3),
               "overshoot_in": round(over * 12.0, 2),
               "ceiling_mark": lowest["mark"]}
        offenders.append(rec)
        w = per_wall.setdefault(wall_tag, {"wall": wall_tag, "boards": 0, "max_overshoot_in": 0.0})
        w["boards"] += 1
        w["max_overshoot_in"] = max(w["max_overshoot_in"], round(over * 12.0, 2))
    else:
        clean += 1

offenders.sort(key=lambda r: -r["overshoot_in"])
walls_sorted = sorted(per_wall.values(), key=lambda w: -w["max_overshoot_in"])

OUT = {
    "ceilings_found": len(ceilings),
    "ceiling_bottom_elevations_ft": sorted(set(round(c["z_bottom"], 3) for c in ceilings)),
    "wall_drywall_boards": len(boards),
    "boards_over_a_ceiling": len(offenders),
    "boards_stopping_at_or_below": clean,
    "boards_under_no_ceiling": no_ceiling,
    "of_those_bbox_overlapped_but_not_really_under": bbox_only,
    "max_overshoot_in": offenders[0]["overshoot_in"] if offenders else 0.0,
    "walls_affected": len(per_wall),
    "per_wall_worst": walls_sorted[:25],
    "worst_boards": offenders[:25],
}
