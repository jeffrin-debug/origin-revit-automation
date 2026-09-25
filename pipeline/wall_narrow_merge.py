# wall_narrow_merge.py - fold a narrow wall board into a neighbour, as long as it stays one sheet.
#
# Some wall boards are narrow with no joint beside them to move (wall_end_joint_fix.py reports
# them): a whole wall face shorter than 16 in (walls 003 / 010 in 1F), or the strip between an
# opening and a wall end. User direction 2026-09-25: "can we merge them whole with the neighbour
# panel which doesn't go more than 8 feet".
#
# A board narrower than NARROW_IN along its wall is merged with a neighbour when
#   1. the neighbour lies in the SAME PLANE (same facing, same offset - it may belong to another,
#      collinear wall) and touches it along the narrow board's WHOLE edge - beside it in the same
#      course, or above/below it (e.g. the board over a door, the way a sheet is hung over an
#      opening and cut);
#   2. the merged outline still fits ONE 4 x 8 ft sheet, either way up;
#   3. the union is one solid with the two volumes' sum (nothing overlaps, nothing is lost).
# Of the neighbours that qualify, the one giving the smallest merged board wins. The survivor is
# the larger board (its mark kept, "NARROW_MERGED=<other>" in its comments). Anything that
# qualifies with no neighbour is reported with the reason.

import traceback

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

APP_ID = "ORIGIN_ASSEMBLY_V4"
NARROW_IN = 16.0
SHEET_SHORT_IN, SHEET_LONG_IN = 48.0, 96.0
PLANE_TOL_IN, TOUCH_TOL_IN = 0.05, 0.05
VOL_REL_TOL = 0.01


def _par(e, b):
    try:
        p = e.get_Parameter(b)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def _solids(e):
    try:
        return [g for g in (e.get_Geometry(Options()) or []) if isinstance(g, Solid) and g.Volume > 1e-9]
    except Exception:
        return []


# ------------------------------------------------------------------ pure 2-D logic (offline)

def pick(narrow, cands):
    """narrow / cands: {"mark", "r": (a0, z0, a1, z1)} in the shared plane's own (along, up)
    coordinates, inches. Returns (best_cand, merged_rect) or (None, why)."""
    a0, z0, a1, z1 = narrow["r"]
    t = TOUCH_TOL_IN
    best = None
    for c in cands:
        b0, y0, b1, y1 = c["r"]
        full = False
        if abs(b1 - a0) <= t or abs(b0 - a1) <= t:            # beside it: must cover its full height
            full = y0 <= z0 + t and y1 >= z1 - t
        elif abs(y1 - z0) <= t or abs(y0 - z1) <= t:          # above/below: must cover its full width
            full = b0 <= a0 + t and b1 >= a1 - t
        if not full:
            continue
        m = (min(a0, b0), min(z0, y0), max(a1, b1), max(z1, y1))
        w, h = m[2] - m[0], m[3] - m[1]
        if min(w, h) > SHEET_SHORT_IN + 1e-6 or max(w, h) > SHEET_LONG_IN + 1e-6:
            continue
        area = w * h
        if best is None or area < best[2]:
            best = (c, m, area)
    if best is None:
        return None, "no same-plane neighbour touches its whole edge and still fits one 4 x 8 sheet"
    return best[0], best[1]


# ------------------------------------------------------------------ Revit side

def _collect(doc):
    walls = {}
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            c = w.Location.Curve
            if not isinstance(c, Line):
                continue
        except Exception:
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        u = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize()
        walls["W{}".format(w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value)] = (
            u, _par(w, BuiltInParameter.ALL_MODEL_MARK))
    boards = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        cm = _par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith(APP_ID + " |") or "| DRYWALL |" not in cm:
            continue
        if "SOFFIT_UNDERSIDE" in cm or "CORNERINFILL=1" in cm or "| L0 |" not in cm:
            continue
        wid = [t.strip()[5:] for t in cm.split("|") if t.strip().startswith("WALL=")]
        if not wid or wid[0] not in walls:
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        u, wm = walls[wid[0]]
        # canonical plane frame: along = the wall's axis made positive, normal perpendicular
        if abs(u.X) >= abs(u.Y):
            ax, nx = XYZ(1, 0, 0), XYZ(0, 1, 0)
        else:
            ax, nx = XYZ(0, 1, 0), XYZ(1, 0, 0)
        pts = [XYZ(x, y, 0) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        al = [p.DotProduct(ax) * 12 for p in pts]
        nr = [p.DotProduct(nx) * 12 for p in pts]
        boards.append({"ds": ds, "cm": cm, "mark": _par(ds, BuiltInParameter.ALL_MODEL_MARK),
                       "wall": wm, "axis": "x" if ax.X else "y",
                       "plane": (round(min(nr), 2), round(max(nr), 2)),
                       "r": (min(al), bb.Min.Z * 12, max(al), bb.Max.Z * 12)})
    return boards


def _bridge(n, c, half_in=0.01):
    """A 2*half_in slab across the seam between narrow board n and neighbour c, over their
    contact area and through the board thickness - world coordinates from the plane frame."""
    a0, z0, a1, z1 = n["r"]
    b0, y0, b1, y1 = c["r"]
    t = TOUCH_TOL_IN
    if abs(b1 - a0) <= t or abs(b0 - a1) <= t:            # side by side: vertical seam
        s = a0 if abs(b1 - a0) <= t else a1
        al, ah, zl, zh = s - half_in, s + half_in, max(z0, y0), min(z1, y1)
    elif abs(y1 - z0) <= t or abs(y0 - z1) <= t:          # stacked: horizontal seam
        s = z0 if abs(y1 - z0) <= t else z1
        al, ah, zl, zh = max(a0, b0), min(a1, b1), s - half_in, s + half_in
    else:
        return None
    p_lo, p_hi = n["plane"]
    if n["axis"] == "x":
        pts = [(al, p_lo), (ah, p_lo), (ah, p_hi), (al, p_hi)]
        pts = [XYZ(x / 12.0, y / 12.0, zl / 12.0) for (x, y) in pts]
    else:
        pts = [(p_lo, al), (p_lo, ah), (p_hi, ah), (p_hi, al)]
        pts = [XYZ(x / 12.0, y / 12.0, zl / 12.0) for (x, y) in pts]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    try:
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, (zh - zl) / 12.0)
    except Exception:
        return None


def plan(doc):
    boards = _collect(doc)
    out = []
    for b in boards:
        if b["r"][2] - b["r"][0] >= NARROW_IN - 1e-6:
            continue
        same = [o for o in boards if o is not b and o["axis"] == b["axis"]
                and abs(o["plane"][0] - b["plane"][0]) <= PLANE_TOL_IN
                and abs(o["plane"][1] - b["plane"][1]) <= PLANE_TOL_IN]
        c, m = pick(b, same)
        row = {"board": b["mark"], "wall": b["wall"], "width_in": round(b["r"][2] - b["r"][0], 2),
               "z_in": [round(b["r"][1]), round(b["r"][3])]}
        if c is None:
            row["why"] = m
        else:
            row.update({"into": c["mark"], "into_wall": c["wall"],
                        "merged_in": [round(m[2] - m[0], 2), round(m[3] - m[1], 2)], "_b": b, "_c": c})
        out.append(row)
    return out


def run(doc, dry_run=False, max_rounds=5):
    """Merge, re-plan, merge again - a merge can make the next one possible (or impossible) -
    until a round changes nothing."""
    total = {"narrow": None, "merged": [], "left": [], "rounds": 0}
    for _ in range(1 if dry_run else max_rounds):
        rep = _run_once(doc, dry_run)
        total["rounds"] += 1
        if total["narrow"] is None:
            total["narrow"] = rep["narrow"]
        total["merged"] += rep["merged"]
        total["left"] = [r for r in rep["left"] if "already merged this run" not in r.get("why", "")]
        if rep.get("force_close_error"):
            total["force_close_error"] = rep["force_close_error"]
        if not rep["merged"]:
            break
    return total


def _run_once(doc, dry_run=False):
    rows = plan(doc)
    rep = {"narrow": len(rows), "merged": [], "left": []}
    todo = [r for r in rows if r.get("into")]
    rep["left"] = [r for r in rows if not r.get("into")]
    clean = lambda r: dict((k, v) for k, v in r.items() if not k.startswith("_"))
    if dry_run or not todo:
        rep["merged"] = [clean(r) for r in todo]
        return rep
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        gone = set()
        for r in todo:
            b, c = r["_b"], r["_c"]
            # A board takes part in ONE merge per round, as keeper or as absorbed. Its geometry
            # changes with the merge and the plan was made before it - reusing it in the same
            # round once merged a board's STALE shape and lost the part it had just absorbed
            # (wall 010, 2026-09-25: the 0-48 in board vanished). The next round re-plans.
            if b["mark"] in gone or c["mark"] in gone:
                x = clean(r)
                x["why"] = "neighbour already merged this run - next run picks it up"
                rep["left"].append(x)
                continue
            keep, lose = (c, b)
            st = SubTransaction(doc)
            st.Start()
            try:
                doc.Regenerate()
                for (d, rr) in ((keep, keep["r"]), (lose, lose["r"])):
                    bb = d["ds"].get_BoundingBox(None)
                    if bb is None or abs(bb.Min.Z * 12 - rr[1]) > 0.05 or abs(bb.Max.Z * 12 - rr[3]) > 0.05:
                        raise Exception("{} changed since it was planned".format(d["mark"]))
                sk, sl = _solids(keep["ds"]), _solids(lose["ds"])
                if len(sk) != 1 or len(sl) != 1:
                    raise Exception("not single solids")
                u = BooleanOperationsUtils.ExecuteBooleanOperation(sk[0], sl[0], BooleanOperationsType.Union)
                want = sk[0].Volume + sl[0].Volume
                if u is None or abs(u.Volume - want) > VOL_REL_TOL * want:
                    raise Exception("union volume does not add up (overlap or gap)")
                # the union may not have MORE pieces than the more fragmented of the two boards:
                # merging must not create a split, but a board the generator already cut in two
                # (wall 003 B, 1F: a 0.04 in slot from a stud trim) carries that split along
                allowed = max(len(SolidUtils.SplitVolumes(sk[0])), len(SolidUtils.SplitVolumes(sl[0])))
                if len(SolidUtils.SplitVolumes(u)) > allowed:
                    # Two boards meeting exactly face to face, each with its seam face split into
                    # several (trim notches), can come back as two lumps (wall 003 B, 1F). Fuse
                    # them through a 0.02 in bridge across the seam - accepted only if the bridge
                    # adds no volume, i.e. it lies wholly inside the two boards.
                    br = _bridge(lose, keep)
                    u2 = None
                    if br is not None:
                        try:
                            u2 = BooleanOperationsUtils.ExecuteBooleanOperation(
                                BooleanOperationsUtils.ExecuteBooleanOperation(sl[0], br, BooleanOperationsType.Union),
                                sk[0], BooleanOperationsType.Union)
                        except Exception:
                            u2 = None
                    if (u2 is None or len(SolidUtils.SplitVolumes(u2)) > allowed or
                            abs(u2.Volume - want) > VOL_REL_TOL * want):
                        raise Exception("union is not one piece")
                    u = u2
                shp = List[GeometryObject]()
                shp.Add(u)
                keep["ds"].SetShape(shp)
                p = keep["ds"].get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                if p is not None and not p.IsReadOnly:
                    p.Set(keep["cm"] + " NARROW_MERGED={}".format(lose["mark"]))
                doc.Delete(lose["ds"].Id)
                st.Commit()
                gone.add(lose["mark"])
                gone.add(keep["mark"])
                rep["merged"].append(clean(r))
            except Exception as ex:
                st.RollBack()
                x = clean(r)
                x["why"] = "merge failed: " + str(ex)[:160]
                rep["left"].append(x)
        doc.Regenerate()
    finally:
        TransactionManager.Instance.TransactionTaskDone()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-300:]
    return rep
