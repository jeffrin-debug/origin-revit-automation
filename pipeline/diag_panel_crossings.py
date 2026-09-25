# diag_panel_crossings.py - panels from one wall passing THROUGH another wall's panel.
#
# At a T-junction the butting wall's drywall should stop at the through-wall's finish face.
# When it does not, the two sheets cross in plan: the trim's Phase 2 then subtracts the shared
# column from the lexicographically-later board, leaving it with a full-height square groove
# where the other sheet passes through. That groove reads as a thin stud-shaped strip on the
# panel face - visible in every view, and impossible to filter out because both pieces are
# legitimate DP- boards.
#
# Counts how many board pairs actually cross. Wall boards only: a board is a wall board when
# its THIN axis is X or Y. A ceiling board is thin in Z and is excluded - getting that wrong is
# what made an earlier version of this report nonsense.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

MIN_OVERLAP_IN = 0.05
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


walls_boards = []
skipped_ceiling = 0
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    m = par(ds, BuiltInParameter.ALL_MODEL_MARK)
    if not m.startswith("DP-"):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    dx, dy, dz = IN(bb.Max.X - bb.Min.X), IN(bb.Max.Y - bb.Min.Y), IN(bb.Max.Z - bb.Min.Z)
    # thin axis decides orientation; a wall board is thin in X or Y, a ceiling board in Z
    thin = min(dx, dy, dz)
    if thin == dz:
        skipped_ceiling += 1
        continue
    facing = "x" if thin == dx else "y"
    walls_boards.append({
        "ds": ds,
        "mark": m, "facing": facing,
        "x": (IN(bb.Min.X), IN(bb.Max.X)),
        "y": (IN(bb.Min.Y), IN(bb.Max.Y)),
        "z": (IN(bb.Min.Z), IN(bb.Max.Z)),
        "host": par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).split("WALL=")[-1].split("|")[0].strip(),
    })

res["wall_boards"] = len(walls_boards)
res["ceiling_boards_skipped"] = skipped_ceiling


def _solids(e):
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


def ov(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


crossings = []
for i in range(len(walls_boards)):
    A = walls_boards[i]
    for j in range(i + 1, len(walls_boards)):
        B = walls_boards[j]
        if A["facing"] == B["facing"]:
            continue                       # parallel sheets cannot cross
        if A["host"] == B["host"]:
            continue                       # same wall
        ox, oy, oz = ov(A["x"], B["x"]), ov(A["y"], B["y"]), ov(A["z"], B["z"])
        if not (ox > MIN_OVERLAP_IN and oy > MIN_OVERLAP_IN and oz > MIN_OVERLAP_IN):
            continue
        # bboxes overlapping is only the broad phase - a trimmed board keeps its bbox. The
        # question is whether any MATERIAL still occupies the same space.
        real = 0.0
        for sa in _solids(A["ds"]):
            for sb in _solids(B["ds"]):
                try:
                    it = BooleanOperationsUtils.ExecuteBooleanOperation(
                        sa, sb, BooleanOperationsType.Intersect)
                except Exception:
                    continue
                if it is not None:
                    real += it.Volume * 1728.0
        if real <= 0.05:
            continue
        crossings.append({
            "a": A["mark"], "b": B["mark"],
            "bbox_overlap_in": {"x": round(ox, 3), "y": round(oy, 3), "z": round(oz, 3)},
            "real_solid_cuin": round(real, 3),
        })

crossings.sort(key=lambda r: -r["real_solid_cuin"])
affected = set()
for c in crossings:
    affected.add(c["a"])
    affected.add(c["b"])

res["crossing_pairs"] = len(crossings)
res["boards_involved"] = len(affected)
res["pct_of_wall_boards"] = (round(100.0 * len(affected) / len(walls_boards), 1)
                             if walls_boards else 0)
res["total_real_cuin"] = round(sum(c["real_solid_cuin"] for c in crossings), 2)
res["worst"] = crossings[:12]
OUT = res
