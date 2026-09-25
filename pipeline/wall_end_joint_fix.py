# wall_end_joint_fix.py - move wall-board joints that still end up < 16 in from a hard end.
#
# wall_end_joints.py moves a joint while the generator lays each course, measured from the face
# ends it knows then. Two things only happen AFTER that and put a sliver back (1F, 2026-09-25):
#
#   * a wall that BUTTS INTO the face mid-span breaks the course there (partition split) - the
#     piece between that break and the next joint can be a few inches (walls 011, 012, 016);
#   * the end board is later trimmed clear of the neighbouring wall's framing, which takes inches
#     off the "end" the first rule measured (walls 009, 013: 17.8 in became 11.3 in).
#
# This pass works on the finished boards. In each course of each face it finds a board narrower
# than MIN_END_IN that touches another board on one side (a joint) and ends at something fixed on
# the other (face end, a wall butting in, an opening). The joint moves into the neighbour, to the
# nearest STUD LINE of that wall that leaves the short piece AND the neighbour both >= MIN_END_IN,
# keeps the grown board within one sheet, and is >= JAMB_CLEAR_IN from a door/window jamb. The
# strip between the old and new joint is cut out of the neighbour and unioned onto the short
# board (booleans, in a SubTransaction - rolled back unless both stay single solids and the
# volume is conserved). What cannot be fixed - no joint beside it, or no stud that satisfies all
# of that - is reported, with the reason.

import traceback

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

APP_ID = "ORIGIN_ASSEMBLY_V4"
MIN_END_IN = 16.0
SHEET_IN = 96.0
JAMB_CLEAR_IN = 4.0
TOUCH_IN = 0.05
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


def _tok(cm, key):
    for t in cm.split("|"):
        t = t.strip()
        if t.startswith(key):
            return t[len(key):]
    return None


def _along(bb, p0, u):
    a = [XYZ(x, y, 0).Subtract(XYZ(p0.X, p0.Y, 0)).DotProduct(u)
         for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
    return min(a), max(a)


def _box(p0, u, n, a0, a1, b0, b1, z0, z1):
    pts = [XYZ(p0.X, p0.Y, 0).Add(u.Multiply(a)).Add(n.Multiply(b)) for (a, b) in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]
    pts = [XYZ(p.X, p.Y, z0) for p in pts]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)


def _bool(a, b, op):
    for (x, y) in ((a, b), (b, a)) if op == BooleanOperationsType.Intersect else ((a, b),):
        try:
            return BooleanOperationsUtils.ExecuteBooleanOperation(x, y, op)
        except Exception:
            continue
    return None


def _collect(doc):
    walls, faces, studs = {}, {}, {}
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            c = w.Location.Curve
            if not isinstance(c, Line):
                continue
        except Exception:
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        u = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize()
        wid = "W{}".format(w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value)
        jambs = []
        for i in w.FindInserts(True, False, False, False):
            e = doc.GetElement(i)
            ob = e.get_BoundingBox(None) if e is not None else None
            if ob is not None:
                a0, a1 = _along(ob, p0, u)
                jambs += [a0, a1]
        walls[wid] = {"p0": p0, "u": u, "n": XYZ(-u.Y, u.X, 0), "jambs": jambs,
                      "mark": _par(w, BuiltInParameter.ALL_MODEL_MARK)}
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        cm = _par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith(APP_ID + " |"):
            continue
        wid = _tok(cm, "WALL=")
        if wid not in walls:
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        w = walls[wid]
        a0, a1 = _along(bb, w["p0"], w["u"])
        mk = _par(ds, BuiltInParameter.ALL_MODEL_MARK)
        if "| DRYWALL |" in cm:
            if "SOFFIT_UNDERSIDE" in cm or "CORNERINFILL=1" in cm or "| L0 |" not in cm:
                continue
            face = "A" if "FACE_A" in cm else "B"
            key = (wid, face, round(bb.Min.Z, 3), round(bb.Max.Z, 3))
            faces.setdefault(key, []).append({"ds": ds, "cm": cm, "mark": mk, "a0": a0, "a1": a1, "bb": bb})
        elif mk.startswith("ST-") and ("| STUD |" in cm or "| KINGSTUD |" in cm):
            studs.setdefault(wid, []).append(((a0 + a1) / 2.0, bb.Min.Z, bb.Max.Z))
    return walls, faces, studs


def _plan(walls, faces, studs):
    """Pure-ish: every short end piece and the joint move that fixes it (or why not)."""
    mn, tol = MIN_END_IN / 12.0, TOUCH_IN / 12.0
    out = []
    for key, bl in faces.items():
        wid, face, z0, z1 = key
        bl = sorted(bl, key=lambda b: b["a0"])
        lines = sorted(set(round(a, 4) for (a, s0, s1) in studs.get(wid, []) if s0 <= z0 + 0.05 and s1 >= z1 - 0.05))
        jambs = walls[wid]["jambs"]
        for i, b in enumerate(bl):
            width = b["a1"] - b["a0"]
            if width >= mn - 1e-6:
                continue
            left = bl[i - 1] if i > 0 and abs(bl[i - 1]["a1"] - b["a0"]) <= tol else None
            right = bl[i + 1] if i + 1 < len(bl) and abs(bl[i + 1]["a0"] - b["a1"]) <= tol else None
            row = {"wall": walls[wid]["mark"], "face": face, "course_in": [round(z0 * 12), round(z1 * 12)],
                   "board": b["mark"], "width_in": round(width * 12, 2)}
            if left is None and right is None:
                row.update({"fix": None, "why": "no joint beside it - bounded by the face end / a wall / "
                                                "an opening on both sides"})
                out.append(row)
                continue
            best = None
            for nb, side in ((right, "right"), (left, "left")):
                if nb is None:
                    continue
                if side == "right":          # joint at b.a1 moves right into nb
                    cands = [s for s in lines if b["a0"] + mn - 1e-6 <= s <= nb["a1"] - mn + 1e-6 and s > b["a1"]
                             and s - b["a0"] <= SHEET_IN / 12.0 + 1e-6]
                    cands = [s for s in cands if all(abs(s - j) >= JAMB_CLEAR_IN / 12.0 for j in jambs)]
                    if cands:
                        s = min(cands)
                        cand = (s - b["a1"], nb, side, b["a1"], s)
                else:                        # joint at b.a0 moves left into nb
                    cands = [s for s in lines if nb["a0"] + mn - 1e-6 <= s <= b["a1"] - mn + 1e-6 and s < b["a0"]
                             and b["a1"] - s <= SHEET_IN / 12.0 + 1e-6]
                    cands = [s for s in cands if all(abs(s - j) >= JAMB_CLEAR_IN / 12.0 for j in jambs)]
                    if cands:
                        s = max(cands)
                        cand = (b["a0"] - s, nb, side, b["a0"], s)
                if cands and (best is None or cand[0] < best[0]):
                    best = cand
            if best is None:
                row.update({"fix": None, "why": "no stud line leaves both pieces >= {:.0f} in within one "
                                                "sheet, clear of jambs".format(MIN_END_IN)})
            else:
                _, nb, side, j, s = best
                row.update({"fix": {"into": nb["mark"], "joint_from_ft": round(j, 3), "joint_to_ft": round(s, 3),
                                    "moved_in": round(abs(s - j) * 12, 2)},
                            "_b": b, "_nb": nb, "_key": key})
            out.append(row)
    return out


def _apply(doc, walls, row):
    b, nb, key = row["_b"], row["_nb"], row["_key"]
    wid, face, z0, z1 = key
    w = walls[wid]
    j, s = row["fix"]["joint_from_ft"], row["fix"]["joint_to_ft"]
    across = []
    for bb in (b["bb"], nb["bb"]):
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                across.append(XYZ(x, y, 0).Subtract(XYZ(w["p0"].X, w["p0"].Y, 0)).DotProduct(w["n"]))
    slab = _box(w["p0"], w["u"], w["n"], min(j, s), max(j, s), min(across) - 0.1, max(across) + 0.1,
                z0 - 0.01, z1 + 0.01)
    sb, sn = _solids(b["ds"]), _solids(nb["ds"])
    if len(sb) != 1 or len(sn) != 1:
        raise Exception("boards are not single solids")
    piece = _bool(sn[0], slab, BooleanOperationsType.Intersect)
    rest = _bool(sn[0], slab, BooleanOperationsType.Difference)
    grown = _bool(sb[0], piece, BooleanOperationsType.Union) if piece is not None else None
    if piece is None or rest is None or grown is None or piece.Volume <= 1e-9:
        raise Exception("boolean failed")
    if abs(grown.Volume + rest.Volume - sb[0].Volume - sn[0].Volume) > VOL_REL_TOL * (sb[0].Volume + sn[0].Volume):
        raise Exception("volume not conserved")
    if len(SolidUtils.SplitVolumes(grown)) != 1 or len(SolidUtils.SplitVolumes(rest)) != 1:
        raise Exception("a board would split in two")
    for (ds, sol, cm) in ((b["ds"], grown, b["cm"]), (nb["ds"], rest, nb["cm"])):
        shp = List[GeometryObject]()
        shp.Add(sol)
        ds.SetShape(shp)
    tag = " END_JOINT_MOVED={:.2f}->{:.2f}in".format(j * 12, s * 12)
    for (ds, cm) in ((b["ds"], b["cm"]), (nb["ds"], nb["cm"])):
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None and not p.IsReadOnly:
            p.Set(cm + tag)


def run(doc, dry_run=False):
    walls, faces, studs = _collect(doc)
    plan = _plan(walls, faces, studs)
    rep = {"short_pieces": len(plan), "moved": [], "left": []}
    todo = [r for r in plan if r.get("fix")]
    for r in plan:
        if not r.get("fix"):
            rep["left"].append(r)
    if dry_run or not todo:
        rep["moved"] = [dict((k, v) for k, v in r.items() if not k.startswith("_")) for r in todo]
        return rep
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        used = set()
        for r in todo:
            ids = (r["_b"]["mark"], r["_nb"]["mark"])
            clean = dict((k, v) for k, v in r.items() if not k.startswith("_"))
            if used.intersection(ids):
                clean.update({"fix": None, "why": "neighbour already changed this run - next run picks it up"})
                rep["left"].append(clean)
                continue
            st = SubTransaction(doc)
            st.Start()
            try:
                _apply(doc, walls, r)
                st.Commit()
                used.update(ids)
                rep["moved"].append(clean)
            except Exception as ex:
                st.RollBack()
                clean.update({"fix": None, "why": "move failed: " + str(ex)[:160]})
                rep["left"].append(clean)
        doc.Regenerate()
    finally:
        TransactionManager.Instance.TransactionTaskDone()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-300:]
    return rep
