# infill_merge.py - fold corner-infill strips into the board next to them.
#
# The wall generator's emit_corner_infill_for_exposed_studs() post-pass covers a stud that no
# board reaches with a separate stud-shaped strip (Comments "... CORNERINFILL=1"), e.g.
# DP-003-004B: 0.63in x 0.5in x 9 ft between wall 009's face-B boards and wall 004's face.
# Nobody hangs a 5/8in strip of drywall on site - the board beside the gap simply runs 5/8in
# further. This pass does exactly that, after the generator has finished:
#
#   1. every infill strip is matched to the boards on the SAME face plane that TOUCH one of its
#      two long edges;
#   2. a side qualifies only if its boards together cover the strip's whole height and each is a
#      single solid; the side whose boards belong to a DIFFERENT wall than the strip is preferred
#      (that board is the one continuing along the line - the strip's own host is the wall whose
#      boards were pulled back at the corner);
#   3. each of those boards gets the slice of the strip at its own height boolean-unioned onto it,
#      and the strip is deleted.
#
# All of one strip's edits run in a SubTransaction and are rolled back unless every step checks
# out (single merged solid, volumes add up, whole strip absorbed) - so a strip is either fully
# folded in or left exactly as the generator made it. No stud is ever left exposed.
#
# The generator repository is not touched; this works on the DirectShapes it produced. Runs from
# stage2_panels.py right after the walls generator; merge_infill_active.py runs it on the model
# open in Revit without regenerating anything.

import json
import os
import traceback

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

APP_ID = "ORIGIN_ASSEMBLY_V4"
INFILL_TOKEN = "CORNERINFILL=1"
MERGED_TOKEN = "INFILL_MERGED="

PLANE_TOL_FT = 0.02 / 12.0      # same face plane: thickness-axis extents agree to 0.02in
TOUCH_TOL_FT = 0.02 / 12.0      # boards touch the strip's edge within 0.02in
COVER_TOL_FT = 0.05 / 12.0      # neighbours must cover the strip's height to within 0.05in
VOL_REL_TOL = 0.01              # merged volume = board + slice, within 1 %


def _par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def _set_comments(e, s):
    p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(s)


def _solids(e):
    out = []
    try:
        geo = e.get_Geometry(Options())
        for g in geo or []:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


def _host(comments):
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok[5:]
    return None


def _wall_axes(doc, host):
    """Unit along-wall direction u and its plan normal n for host 'W<eid>'."""
    try:
        w = doc.GetElement(ElementId(int(host[1:])))
        c = w.Location.Curve
        if not isinstance(c, Line):
            return None
        d = c.GetEndPoint(1).Subtract(c.GetEndPoint(0))
        d = XYZ(d.X, d.Y, 0.0).Normalize()
        return d, XYZ(-d.Y, d.X, 0.0)
    except Exception:
        return None


def _ranges(bb, u, n):
    pts = [XYZ(x, y, 0.0) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
    a = [p.DotProduct(u) for p in pts]
    b = [p.DotProduct(n) for p in pts]
    return (min(a), max(a)), (min(b), max(b)), (bb.Min.Z, bb.Max.Z)


def _covers(intervals, lo, hi):
    cur = lo
    for (a, b) in sorted(intervals):
        if a > cur + COVER_TOL_FT:
            return False
        cur = max(cur, b)
    return cur >= hi - COVER_TOL_FT


def _slab(bb, z0, z1, mat_id, gs_id):
    """A box spanning well past the strip in plan, between z0 and z1 - intersected with the strip
    it yields the strip's slice at one board's height. Carries the board's material/style so the
    slice's cut faces match the board."""
    pad = 1.0
    x0, x1 = bb.Min.X - pad, bb.Max.X + pad
    y0, y1 = bb.Min.Y - pad, bb.Max.Y + pad
    pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    opts = SolidOptions(mat_id or ElementId.InvalidElementId, gs_id or ElementId.InvalidElementId)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0, opts)


def _face_style(solid):
    mat = ElementId.InvalidElementId
    try:
        for f in solid.Faces:
            if f.MaterialElementId != ElementId.InvalidElementId:
                mat = f.MaterialElementId
                break
    except Exception:
        pass
    gs = solid.GraphicsStyleId if solid.GraphicsStyleId is not None else ElementId.InvalidElementId
    return mat, gs


def _collect(doc):
    boards, strips = [], []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        cm = _par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith(APP_ID + " |") or "| DRYWALL |" not in cm:
            continue
        mk = _par(ds, BuiltInParameter.ALL_MODEL_MARK)
        bb = ds.get_BoundingBox(None)
        if not mk.startswith("DP-") or bb is None:
            continue
        row = {"ds": ds, "mark": mk, "comments": cm, "host": _host(cm), "bb": bb}
        (strips if INFILL_TOKEN in cm else boards).append(row)
    return boards, strips


def _plan_strip(doc, s, boards):
    """Pick the side to extend. Returns (side_label, [board rows]) or (None, reason)."""
    axes = _wall_axes(doc, s["host"]) if s["host"] else None
    if axes is None:
        return None, "strip host wall is not straight"
    u, n = axes
    (su0, su1), (sn0, sn1), (sz0, sz1) = _ranges(s["bb"], u, n)
    sides = {"lo": [], "hi": []}
    for b in boards:
        (bu0, bu1), (bn0, bn1), (bz0, bz1) = _ranges(b["bb"], u, n)
        if abs(bn0 - sn0) > PLANE_TOL_FT or abs(bn1 - sn1) > PLANE_TOL_FT:
            continue                                  # not the same face plane
        if bz1 <= sz0 + COVER_TOL_FT or bz0 >= sz1 - COVER_TOL_FT:
            continue                                  # no height overlap
        if abs(bu1 - su0) <= TOUCH_TOL_FT:
            sides["lo"].append(b)
        elif abs(bu0 - su1) <= TOUCH_TOL_FT:
            sides["hi"].append(b)
    ok = []
    for label, rows in sides.items():
        if not rows or not _covers([(r["bb"].Min.Z, r["bb"].Max.Z) for r in rows], sz0, sz1):
            continue
        if any(len(_solids(r["ds"])) != 1 for r in rows):
            continue
        other_wall = all(r["host"] != s["host"] for r in rows)
        ok.append((0 if other_wall else 1, label, rows))
    if not ok:
        found = dict((k, [r["mark"] for r in v]) for k, v in sides.items())
        return None, "no side with coplanar boards covering the full height (touching: {})".format(found)
    ok.sort(key=lambda t: t[0])
    return ok[0][1], ok[0][2]


def _merge_one(doc, s, rows):
    """Union the strip's slice at each board's height onto that board, then delete the strip.
    Raises on anything that does not check out; the caller rolls the SubTransaction back."""
    ssol = _solids(s["ds"])
    if len(ssol) != 1:
        raise Exception("strip has {} solids".format(len(ssol)))
    ssol = ssol[0]
    absorbed = 0.0
    done = []
    for r in sorted(rows, key=lambda r: r["bb"].Min.Z):
        bsol = _solids(r["ds"])[0]
        mat, gs = _face_style(bsol)
        z0 = max(r["bb"].Min.Z, s["bb"].Min.Z)
        z1 = min(r["bb"].Max.Z, s["bb"].Max.Z)
        if z1 - z0 <= 1e-6:
            continue
        piece = BooleanOperationsUtils.ExecuteBooleanOperation(
            ssol, _slab(s["bb"], z0, z1, mat, gs), BooleanOperationsType.Intersect)
        if piece is None or piece.Volume <= 1e-9:
            continue
        merged = BooleanOperationsUtils.ExecuteBooleanOperation(bsol, piece, BooleanOperationsType.Union)
        if merged is None:
            raise Exception("union failed for " + r["mark"])
        if len(SolidUtils.SplitVolumes(merged)) != 1:
            raise Exception("union with {} is not one piece".format(r["mark"]))
        want = bsol.Volume + piece.Volume
        if abs(merged.Volume - want) > VOL_REL_TOL * want:
            raise Exception("volume check failed for {} ({:.4f} vs {:.4f} cu ft)".format(
                r["mark"], merged.Volume, want))
        shape = List[GeometryObject]()
        shape.Add(merged)
        r["ds"].SetShape(shape)
        grow_in = round(piece.Volume / max(1e-9, (z1 - z0)) / (0.5 / 12.0) * 12.0, 2)
        cm = r["comments"] + " {}{}+{}in".format(MERGED_TOKEN, s["mark"], grow_in)
        _set_comments(r["ds"], cm)
        r["comments"] = cm
        absorbed += piece.Volume
        done.append({"board": r["mark"], "z_ft": [round(z0, 3), round(z1, 3)], "grew_in": grow_in})
    if abs(absorbed - ssol.Volume) > VOL_REL_TOL * ssol.Volume:
        raise Exception("only {:.0%} of the strip was absorbed".format(absorbed / ssol.Volume))
    doc.Delete(s["ds"].Id)
    return done


def _update_manifest(path, merged, redundant=()):
    """Drop the absorbed and the redundant strips from the wall manifest and note the extension
    on each board that absorbed one."""
    if not path or not os.path.exists(path) or not (merged or redundant):
        return False
    with open(path) as fh:
        m = json.load(fh)
    gone = set(x["strip"] for x in merged) | set(x["strip"] for x in redundant)
    grew = {}
    for x in merged:
        for d in x["into"]:
            grew.setdefault(d["board"], []).append({"strip": x["strip"], "grew_in": d["grew_in"]})
    m["boards"] = [b for b in m.get("boards", []) if b.get("board_id") not in gone]
    for b in m["boards"]:
        if b.get("board_id") in grew:
            b["infill_merged"] = grew[b["board_id"]]
    m.setdefault("summary", {})["corner_infill_merged"] = len(merged)
    with open(path, "w") as fh:
        json.dump(m, fh, indent=2)
    return True


def _describe(s):
    bb = s["bb"]
    return {"strip": s["mark"], "id": s["ds"].Id.IntegerValue if hasattr(s["ds"].Id, "IntegerValue")
            else s["ds"].Id.Value, "host": s["host"],
            "size_in": [round((bb.Max.X - bb.Min.X) * 12, 2), round((bb.Max.Y - bb.Min.Y) * 12, 2),
                        round((bb.Max.Z - bb.Min.Z) * 12, 2)],
            "x_in": [round(bb.Min.X * 12, 2), round(bb.Max.X * 12, 2)],
            "y_in": [round(bb.Min.Y * 12, 2), round(bb.Max.Y * 12, 2)],
            "z_ft": [round(bb.Min.Z, 3), round(bb.Max.Z, 3)]}


def plan(doc):
    """Read-only: every infill strip in the model and what run() would do with it."""
    boards, strips = _collect(doc)
    out = []
    for s in strips:
        row = _describe(s)
        side, rows = _plan_strip(doc, s, boards)
        if side is None:
            row["would"] = "keep"
            row["why"] = rows
        else:
            row["would"] = "extend"
            row["side"] = side
            row["into"] = [{"board": r["mark"], "host": r["host"],
                            "z_ft": [round(r["bb"].Min.Z, 3), round(r["bb"].Max.Z, 3)]} for r in rows]
        out.append(row)
    return {"strips": len(out), "would_extend": sum(1 for r in out if r["would"] == "extend"),
            "would_keep": sum(1 for r in out if r["would"] == "keep"), "cases": out}


REDUNDANT_SHARE = 0.5          # a strip this much inside other drywall adds nothing but overlap


def _overlap_volume(a_solids, b_solids):
    v = 0.0
    for x in a_solids:
        for y in b_solids:
            for (p, q) in ((x, y), (y, x)):
                try:
                    r = BooleanOperationsUtils.ExecuteBooleanOperation(p, q, BooleanOperationsType.Intersect)
                    v += r.Volume if r is not None else 0.0
                    break
                except Exception:
                    continue
    return v


def _drop_redundant(doc, boards, strips, rep):
    """A strip is only meant where NO board covers a stud. When the generator's own subtraction
    fails on a thin sliver it emits one anyway, inside a board (1F 2026-09-25: DP-007-002A inside
    DP-007-001A), and two studs side by side can each emit one on top of the other (DP-012-014A/
    015A, DP-014-009B/010B). A strip mostly inside other drywall is deleted; of two overlapping
    strips the later one goes. Returns the strips that remain."""
    keep = []
    for s in strips:
        ss = _solids(s["ds"])
        vol = sum(x.Volume for x in ss)
        bb = s["bb"]
        others = [o for o in boards + keep
                  if not (o["bb"].Max.X < bb.Min.X or o["bb"].Min.X > bb.Max.X or
                          o["bb"].Max.Y < bb.Min.Y or o["bb"].Min.Y > bb.Max.Y or
                          o["bb"].Max.Z < bb.Min.Z or o["bb"].Min.Z > bb.Max.Z)]
        inside = _overlap_volume(ss, [y for o in others for y in _solids(o["ds"])]) if vol > 0 else 0.0
        if vol > 0 and inside >= REDUNDANT_SHARE * vol:
            doc.Delete(s["ds"].Id)
            rep["redundant_deleted"].append({"strip": s["mark"], "inside_pct": round(100.0 * inside / vol, 1)})
        else:
            keep.append(s)
    return keep


def run(doc, manifest_path=None):
    """Fold every corner-infill strip into its neighbour. Opens and commits its own transaction,
    so it must not be called from inside one. Returns a report dict."""
    rep = {"strips": 0, "merged": [], "kept": [], "redundant_deleted": []}
    boards, strips = _collect(doc)
    rep["strips"] = len(strips)
    if not strips:
        return rep
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        strips = _drop_redundant(doc, boards, strips, rep)
        doc.Regenerate()
        for s in strips:
            side, rows = _plan_strip(doc, s, boards)
            if side is None:
                rep["kept"].append({"strip": s["mark"], "why": rows})
                continue
            st = SubTransaction(doc)
            st.Start()
            try:
                done = _merge_one(doc, s, rows)
                st.Commit()
                rep["merged"].append({"strip": s["mark"], "side": side,
                                      "into": done})
                # the grown boards may border the next strip - measure them as they are now
                doc.Regenerate()
                for r in rows:
                    r["bb"] = r["ds"].get_BoundingBox(None) or r["bb"]
            except Exception as ex:
                st.RollBack()
                rep["kept"].append({"strip": s["mark"], "why": str(ex)[:300]})
    finally:
        TransactionManager.Instance.TransactionTaskDone()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-400:]
    try:
        rep["manifest_updated"] = _update_manifest(manifest_path, rep["merged"], rep["redundant_deleted"])
    except Exception:
        rep["manifest_error"] = traceback.format_exc()[-400:]
    rep["merged_count"] = len(rep["merged"])
    rep["kept_count"] = len(rep["kept"])
    return rep
