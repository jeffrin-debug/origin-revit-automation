# soffit_detect.py - recognise soffits drawn as ordinary short walls, and board their underside.
#
# The drywall generators only know a soffit by NAME: a Ceiling whose category/type says "soffit",
# or a wall of type "Generic - 2'" (the soffit band). In 1F the soffit along the edge of the 8 ft
# ceiling is two plain partitions instead - walls 006/007, "Interior - 4 3/4" Partition (1-hr) 2",
# 7'-0" to 8'-4 1/4" - so they were boarded like any wall: two sides, and NOTHING underneath.
#
# This pass recognises the SHAPE instead (user direction 2026-09-25: "in upcoming envs also those
# kind of soffit should be recognisable without saying it"). A wall is a soffit when ALL hold:
#
#   * it starts at least SOFFIT_MIN_BASE_FT above its own level      (hangs high, off the floor)
#   * it is at most SOFFIT_MAX_HEIGHT_FT tall                         (a band, not a wall)
#   * it hosts no door or window
#   * no other wall stands under its footprint                        (open space below)
#   * a ceiling meets it: a ceiling's underside lies between the wall's base and top (plus
#     SOFFIT_TOP_TOL_FT), within SOFFIT_CEILING_REACH_FT of it in plan
#
# Walls of the generator's own soffit-band type are skipped - they already belong to its soffit
# flow. For each soffit the pass adds ONE underside board spanning its boards' outer faces, laid
# under the side boards so their bottom edges are covered. Where two soffits meet at a corner the
# higher ElementId (the generator's through-wall tiebreak) is boarded first and the other is cut
# against it, and every board is cut clear of other walls' framing and boards - so nothing
# overlaps. The side boards are tagged SOFFIT=1.
#
# The underside boards carry the wall generator's own APP_ID and WALL=W<eid> token, so the next
# walls run deletes and regenerates them with everything else on that wall.

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
SOFFIT_BAND_WALL_TYPE_NAME = "Generic - 2'"     # the generator's own soffit band - not ours

CFG = {
    "SOFFIT_MIN_BASE_FT": 6.0,
    "SOFFIT_MAX_HEIGHT_FT": 3.0,
    "SOFFIT_TOP_TOL_FT": 0.1,
    "SOFFIT_CEILING_REACH_FT": 1.0,
    "BELOW_TOL_FT": 0.05,
    "BELOW_SHARE": 0.20,             # a wall under more than this share of the footprint = not a soffit
    "BOARD_T_FT": 0.5 / 12.0,
    # Raising a soffit to the ceiling it falls short of (user direction 2026-09-25: "if any soffit
    # doesn't touch the ceiling and forms some gap we need to move the soffit up").
    "RAISE_TO_CEILING": True,
    "TOUCH_TOL_FT": 0.1 / 12.0,      # a top within this of a ceiling underside touches it
    "MAX_RAISE_FT": 2.0,             # never move a soffit further than this - report it instead
    "MIN_DROP_FT": 1.0 / 12.0,       # after the move its bottom must still hang this far below
                                     # every ceiling beside it, or it would vanish into one
    "SIDE_PROBE_FT": 0.75,           # how far past each face to look for that side's ceiling
}


# ------------------------------------------------------------------ pure classification (offline)

def classify(walls, ceilings, cfg=None):
    """walls:    [{"id", "type", "straight", "inserts", "level_z", "x", "y", "z"}] - x/y/z are
                 (min, max) world extents in ft.
       ceilings: [{"id", "bottom_z", "x", "y"}].
       Returns (soffits, rejected): soffits = [{"id", "ceiling_id", ...}], rejected = [{"id", why}]
       for walls that looked high and short but failed a test (so a near miss is visible)."""
    cfg = dict(CFG, **(cfg or {}))
    soffits, rejected = [], []
    for w in walls:
        base_above = w["z"][0] - w["level_z"]
        height = w["z"][1] - w["z"][0]
        if base_above < cfg["SOFFIT_MIN_BASE_FT"] or height > cfg["SOFFIT_MAX_HEIGHT_FT"]:
            continue                                   # an ordinary wall - not even a candidate
        why = None
        if w.get("type") == SOFFIT_BAND_WALL_TYPE_NAME:
            why = "already the generator's soffit band type"
        elif not w.get("straight", True):
            why = "not straight"
        elif w.get("inserts"):
            why = "hosts {} door/window insert(s)".format(w["inserts"])
        else:
            # A wall that merely butts into the soffit's end (a few inches of footprint at a
            # junction) is not "under" it; one covering a real share of its footprint is.
            area = max(1e-9, (w["x"][1] - w["x"][0]) * (w["y"][1] - w["y"][0]))
            for o in walls:
                if o["id"] == w["id"] or o["z"][0] >= w["z"][0] - cfg["BELOW_TOL_FT"]:
                    continue
                ox = min(o["x"][1], w["x"][1]) - max(o["x"][0], w["x"][0])
                oy = min(o["y"][1], w["y"][1]) - max(o["y"][0], w["y"][0])
                if ox > 0 and oy > 0 and ox * oy / area > cfg["BELOW_SHARE"]:
                    why = "wall {} stands under {:.0%} of it".format(o["id"], ox * oy / area)
                    break
        ceiling_id = None
        if why is None:
            r = cfg["SOFFIT_CEILING_REACH_FT"]
            # meets it, or hangs above it within reach of a raise (a soffit with a GAP to its
            # ceiling is still a soffit - that gap is exactly what raise_to_ceiling() closes)
            reach_up = max(cfg["SOFFIT_TOP_TOL_FT"],
                           cfg["MAX_RAISE_FT"] if cfg.get("RAISE_TO_CEILING") else 0.0)
            for c in ceilings:
                if not (w["z"][0] - 1e-6 <= c["bottom_z"] <= w["z"][1] + reach_up):
                    continue
                if (c["x"][0] - r <= w["x"][1] and w["x"][0] <= c["x"][1] + r and
                        c["y"][0] - r <= w["y"][1] and w["y"][0] <= c["y"][1] + r):
                    ceiling_id = c["id"]
                    break
            if ceiling_id is None:
                why = "no ceiling meets it"
        row = {"id": w["id"], "base_above_level_ft": round(base_above, 3),
               "height_ft": round(height, 3), "type": w.get("type")}
        if why is None:
            row["ceiling_id"] = ceiling_id
            soffits.append(row)
        else:
            row["why"] = why
            rejected.append(row)
    return soffits, rejected


def decide_raise(bottom, top, undersides, cfg=None):
    """bottom/top: the soffit's world Z (ft). undersides: underside Z of every ceiling beside it,
    on either face. Returns (action, delta_ft, why):
       "touches" - no ceiling beside it sits above its top: nothing to move, just panelise
       "raise"   - move it up by delta_ft so its top meets the highest ceiling it falls short of
       "keep"    - there is a gap but moving would break a guard; why says which"""
    cfg = dict(CFG, **(cfg or {}))
    if not undersides:
        return "keep", 0.0, "no ceiling beside it"
    above = [u for u in undersides if u > top + cfg["TOUCH_TOL_FT"]]
    if not above:
        return "touches", 0.0, "top meets every ceiling beside it"
    target = max(above)
    delta = target - top
    if delta > cfg["MAX_RAISE_FT"] + 1e-9:
        return "keep", 0.0, "gap {:.2f} in is more than the {:.1f} ft raise limit".format(
            delta * 12.0, cfg["MAX_RAISE_FT"])
    lowest = min(undersides)
    if bottom + delta > lowest - cfg["MIN_DROP_FT"] + 1e-9:
        return "keep", 0.0, ("raising {:.2f} in would lift its bottom to {:.2f} in, into the "
                             "ceiling at {:.2f} in".format(delta * 12.0, (bottom + delta) * 12.0,
                                                           lowest * 12.0))
    return "raise", delta, "gap {:.2f} in to the ceiling at {:.2f} in".format(delta * 12.0, target * 12.0)


# ------------------------------------------------------------------ Revit side

def _eid(e):
    return e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value


def _par(e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def _set(e, bip, s):
    p = e.get_Parameter(bip)
    if p is not None and not p.IsReadOnly:
        p.Set(s)


def _solids(e):
    try:
        return [g for g in (e.get_Geometry(Options()) or []) if isinstance(g, Solid) and g.Volume > 1e-9]
    except Exception:
        return []


def _wall_rows(doc):
    rows, by_id = [], {}
    door = ElementId(BuiltInCategory.OST_Doors)
    win = ElementId(BuiltInCategory.OST_Windows)
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        bb = w.get_BoundingBox(None)
        if bb is None:
            continue
        lvl = doc.GetElement(w.LevelId)
        n_ins = 0
        try:
            for i in w.FindInserts(True, False, False, False):
                e = doc.GetElement(i)
                if e is not None and e.Category is not None and e.Category.Id in (door, win):
                    n_ins += 1
        except Exception:
            pass
        try:
            straight = isinstance(w.Location.Curve, Line)
        except Exception:
            straight = False
        try:
            tname = w.Name
        except Exception:
            tname = ""
        row = {"id": _eid(w), "type": tname, "straight": straight, "inserts": n_ins,
               "level_z": lvl.Elevation if lvl is not None else 0.0,
               "x": (bb.Min.X, bb.Max.X), "y": (bb.Min.Y, bb.Max.Y), "z": (bb.Min.Z, bb.Max.Z)}
        rows.append(row)
        by_id[row["id"]] = w
    return rows, by_id


def _ceiling_rows(doc):
    rows = []
    for c in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings) \
            .WhereElementIsNotElementType():
        bb = c.get_BoundingBox(None)
        if bb is not None:
            rows.append({"id": _eid(c), "bottom_z": bb.Min.Z,
                         "x": (bb.Min.X, bb.Max.X), "y": (bb.Min.Y, bb.Max.Y)})
    return rows


def _origin_shapes(doc):
    out = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        cm = _par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith("ORIGIN"):
            continue
        bb = ds.get_BoundingBox(None)
        if bb is not None:
            out.append({"ds": ds, "cm": cm, "mark": _par(ds, BuiltInParameter.ALL_MODEL_MARK), "bb": bb})
    return out


def _box_from_plan(u, n, a0, a1, b0, b1, z0, h, mat, gs):
    pts = [u.Multiply(a).Add(n.Multiply(b)) for (a, b) in ((a0, b0), (a1, b0), (a1, b1), (a0, b1))]
    pts = [XYZ(p.X, p.Y, z0) for p in pts]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(
        loops, XYZ.BasisZ, h, SolidOptions(mat or ElementId.InvalidElementId, gs or ElementId.InvalidElementId))


def _subtract(cut, other):
    for (a, b) in ((cut, other), (other, cut)):
        try:
            inter = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
            if inter is None or inter.Volume <= 1e-9:
                return cut
            return BooleanOperationsUtils.ExecuteBooleanOperation(cut, inter, BooleanOperationsType.Difference)
        except Exception:
            continue
    return cut


def _underside(doc, wall, tag, shapes, cfg, report):
    """Build and place the underside board for one soffit wall. Returns the board row or None."""
    wid = "W{}".format(_eid(wall))
    own = [s for s in shapes if ("WALL=" + wid + " ") in s["cm"]]
    sides = [s for s in own if "| DRYWALL |" in s["cm"] and "SOFFIT_UNDERSIDE" not in s["cm"]]
    if not sides:
        report["skipped"].append({"wall": wid, "why": "no side boards to measure"})
        return None
    c = wall.Location.Curve
    d = c.GetEndPoint(1).Subtract(c.GetEndPoint(0))
    u = XYZ(d.X, d.Y, 0).Normalize()
    n = XYZ(-u.Y, u.X, 0)
    a, b = [], []
    for s in sides:
        bb = s["bb"]
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                p = XYZ(x, y, 0)
                a.append(p.DotProduct(u))
                b.append(p.DotProduct(n))
    base = min(s["bb"].Min.Z for s in sides)
    t = cfg["BOARD_T_FT"]
    ref = _solids(sides[0]["ds"])
    mat = ElementId.InvalidElementId
    gs = ElementId.InvalidElementId
    if ref:
        gs = ref[0].GraphicsStyleId
        for f in ref[0].Faces:
            if f.MaterialElementId != ElementId.InvalidElementId:
                mat = f.MaterialElementId
                break
    solid = _box_from_plan(u, n, min(a), max(a), min(b), max(b), base - t, t, mat, gs)
    full = solid.Volume
    sb = solid.GetBoundingBox()
    mn, mx = sb.Transform.OfPoint(sb.Min), sb.Transform.OfPoint(sb.Max)
    lo = XYZ(min(mn.X, mx.X), min(mn.Y, mx.Y), min(mn.Z, mx.Z))
    hi = XYZ(max(mn.X, mx.X), max(mn.Y, mx.Y), max(mn.Z, mx.Z))
    cut_by = []
    for s in shapes:
        if ("WALL=" + wid + " ") in s["cm"]:
            continue
        ob = s["bb"]
        if (ob.Max.X <= lo.X or ob.Min.X >= hi.X or ob.Max.Y <= lo.Y or ob.Min.Y >= hi.Y or
                ob.Max.Z <= lo.Z or ob.Min.Z >= hi.Z):
            continue
        for o in _solids(s["ds"]):
            before = solid.Volume
            solid = _subtract(solid, o)
            if solid is None or solid.Volume <= 1e-9:
                report["skipped"].append({"wall": wid, "why": "fully occupied by " + s["mark"]})
                return None
            if solid.Volume < before - 1e-9:
                cut_by.append(s["mark"])
    # Cutting clear of a neighbour at a junction can leave a crumb detached from the board; a
    # board is one piece, so keep the main body and report what was dropped.
    dropped_cuin = 0.0
    try:
        parts = sorted(SolidUtils.SplitVolumes(solid), key=lambda p: -p.Volume)
        if len(parts) > 1:
            dropped_cuin = sum(p.Volume for p in parts[1:]) * 1728.0
            solid = parts[0]
    except Exception:
        pass
    mark = "DP-{}-001U".format(tag)
    cm = ("{} | WALL={} | SOFFIT_UNDERSIDE | DRYWALL | {} | L0 | t={}in | typeX=0 | cut=1 | "
          "taper=0 | waste=0.0sf SOFFIT=1").format(APP_ID, wid, mark, round(t * 12.0, 3))
    ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
    ds.ApplicationId = APP_ID
    ds.ApplicationDataId = mark
    shape = List[GeometryObject]()
    shape.Add(solid)
    ds.SetShape(shape)
    try:
        ds.Name = mark
    except Exception:
        pass
    _set(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, cm)
    _set(ds, BuiltInParameter.ALL_MODEL_MARK, mark)
    for s in sides:
        if "SOFFIT=1" not in s["cm"]:
            _set(s["ds"], BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS, s["cm"] + " SOFFIT=1")
    bb = ds.get_BoundingBox(None)
    row = {"board": mark, "wall": wid, "cut_by": sorted(set(cut_by)),
           "kept_pct": round(100.0 * solid.Volume / full, 1) if full else None,
           "dropped_crumb_cuin": round(dropped_cuin, 3),
           "width_in": round((max(b) - min(b)) * 12.0, 2),
           "length_in": round((max(a) - min(a)) * 12.0, 2),
           "z_in": [round((base - t) * 12.0, 2), round(base * 12.0, 2)]}
    shapes.append({"ds": ds, "cm": cm, "mark": mark,
                   "bb": bb if bb is not None else BoundingBoxXYZ()})
    if bb is None:
        shapes[-1]["bb"].Min, shapes[-1]["bb"].Max = lo, hi
    return row


def _update_manifest(path, report):
    if not path or not os.path.exists(path):
        return False
    with open(path) as fh:
        m = json.load(fh)
    m["soffits_detected"] = report["soffits"]
    for b in report["boards"]:
        m.setdefault("boards", []).append({
            "board_id": b["board"], "host_wall": b["wall"], "face": "SOFFIT_UNDERSIDE",
            "layer": 0, "type_x": False, "thickness_in": 0.5, "is_cut": True, "tapered": False,
            "shape": "rect" if not b["cut_by"] else "cut", "width_in": b["width_in"],
            "length_in": b["length_in"], "z_in": b["z_in"]})
    with open(path, "w") as fh:
        json.dump(m, fh, indent=2)
    return True


def _ceiling_solids(doc):
    out = []
    for c in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings) \
            .WhereElementIsNotElementType():
        bb = c.get_BoundingBox(None)
        if bb is not None:
            out.append((_par(c, BuiltInParameter.ALL_MODEL_MARK) or str(_eid(c)), bb, _solids(c)))
    return out


def _ceilings_at(ceils, x, y):
    """Every ceiling whose real solid covers plan point (x, y): [(mark, underside_z)]."""
    hits = []
    for (m, bb, sol) in ceils:
        if not (bb.Min.X <= x <= bb.Max.X and bb.Min.Y <= y <= bb.Max.Y):
            continue
        z = bb.Min.Z + 0.01
        pts = [XYZ(x - .05, y - .05, z), XYZ(x + .05, y - .05, z),
               XYZ(x + .05, y + .05, z), XYZ(x - .05, y + .05, z)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[CurveLoop]()
        loops.Add(loop)
        probe = GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, 0.04)
        for s in sol:
            try:
                r = BooleanOperationsUtils.ExecuteBooleanOperation(probe, s, BooleanOperationsType.Intersect)
                if r is not None and r.Volume > 1e-9:
                    hits.append((m, bb.Min.Z))
                    break
            except Exception:
                pass
    return hits


def _side_ceilings(wall, ceils, cfg):
    """{mark: underside_z} of the ceilings beside either face of a straight wall."""
    crv = wall.Location.Curve
    p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
    u = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize()
    n = XYZ(-u.Y, u.X, 0)
    bb = wall.get_BoundingBox(None)
    # measure off the wall's real middle - its location line may sit on a face
    mid = XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, 0)
    off0 = XYZ(mid.X - p0.X, mid.Y - p0.Y, 0).DotProduct(n)
    reach = wall.Width / 2.0 + cfg["SIDE_PROBE_FT"]
    L = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).GetLength()
    found = {}
    samples = [L / 2.0] if L < 1.0 else [0.5 + 0.5 * k for k in range(int((L - 0.75) / 0.5) + 1)]
    for a in samples:
        for sgn in (1.0, -1.0):
            d = off0 + sgn * reach
            for (m, z) in _ceilings_at(ceils, p0.X + u.X * a + n.X * d, p0.Y + u.Y * a + n.Y * d):
                found[m] = z
    return found


def raise_to_ceiling(doc, cfg=None):
    """Move every detected soffit that falls short of a ceiling beside it up until it touches.
    Must run BEFORE the walls generator. Opens and commits its own transaction. Returns a report
    with each soffit's action and its previous base/top offsets (to undo by hand if wanted)."""
    cfg = dict(CFG, **(cfg or {}))
    rep = {"checked": [], "raised": 0}
    if not cfg.get("RAISE_TO_CEILING"):
        return rep
    walls, by_id = _wall_rows(doc)
    soffits, _rej = classify(walls, _ceiling_rows(doc), cfg)
    if not soffits:
        return rep
    ceils = _ceiling_solids(doc)
    todo = []
    for s in soffits:
        w = by_id[s["id"]]
        bb = w.get_BoundingBox(None)
        sides = _side_ceilings(w, ceils, cfg)
        action, delta, why = decide_raise(bb.Min.Z, bb.Max.Z, list(sides.values()), cfg)
        row = {"wall": _par(w, BuiltInParameter.ALL_MODEL_MARK) or s["id"], "id": s["id"],
               "bottom_in": round(bb.Min.Z * 12, 2), "top_in": round(bb.Max.Z * 12, 2),
               "ceilings_beside": dict((k, round(v * 12, 2)) for k, v in sides.items()),
               "action": action, "why": why}
        rep["checked"].append(row)
        if action == "raise":
            todo.append((w, delta, row))
    if not todo:
        return rep
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        for (w, delta, row) in todo:
            st = SubTransaction(doc)
            st.Start()
            try:
                pb = w.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
                row["base_offset_was_in"] = round(pb.AsDouble() * 12, 3)
                pb.Set(pb.AsDouble() + delta)
                ht = w.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE)
                if ht is not None and ht.AsElementId() != ElementId.InvalidElementId:
                    pt = w.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET)   # top tied to a level
                    row["top_offset_was_in"] = round(pt.AsDouble() * 12, 3)
                    pt.Set(pt.AsDouble() + delta)
                st.Commit()
                doc.Regenerate()
                nb = w.get_BoundingBox(None)
                row["now_bottom_in"] = round(nb.Min.Z * 12, 2)
                row["now_top_in"] = round(nb.Max.Z * 12, 2)
                row["raised_in"] = round(delta * 12, 2)
                rep["raised"] += 1
            except Exception:
                st.RollBack()
                row["action"] = "keep"
                row["why"] = "move failed: " + traceback.format_exc()[-200:]
    finally:
        TransactionManager.Instance.TransactionTaskDone()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-300:]
    return rep


def soffit_wall_ids(doc, cfg=None):
    """'W<eid>' of every wall classify() calls a soffit - handed to the walls generator so each
    face of a soffit stops at its own ceiling, however close that ceiling is to the soffit base."""
    walls, _ = _wall_rows(doc)
    soffits, _ = classify(walls, _ceiling_rows(doc), cfg)
    return ["W{}".format(s["id"]) for s in soffits]


def run(doc, manifest_path=None, cfg=None):
    """Detect soffit walls and board their undersides. Opens and commits its own transaction."""
    cfg = dict(CFG, **(cfg or {}))
    report = {"soffits": [], "rejected": [], "boards": [], "skipped": []}
    walls, by_id = _wall_rows(doc)
    soffits, rejected = classify(walls, _ceiling_rows(doc), cfg)
    report["soffits"], report["rejected"] = soffits, rejected
    if not soffits:
        return report
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        shapes = _origin_shapes(doc)
        # higher ElementId first - the generator's through-wall tiebreak at a corner
        for s in sorted(soffits, key=lambda r: -r["id"]):
            w = by_id[s["id"]]
            tag = _par(w, BuiltInParameter.ALL_MODEL_MARK) or str(s["id"])
            s["wall_mark"] = tag
            st = SubTransaction(doc)
            st.Start()
            try:
                row = _underside(doc, w, tag, shapes, cfg, report)
                st.Commit()
                if row:
                    report["boards"].append(row)
            except Exception:
                st.RollBack()
                report["skipped"].append({"wall": s["id"], "why": traceback.format_exc()[-300:]})
            doc.Regenerate()
    finally:
        TransactionManager.Instance.TransactionTaskDone()
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            report["force_close_error"] = traceback.format_exc()[-300:]
    try:
        report["manifest_updated"] = _update_manifest(manifest_path, report)
    except Exception:
        report["manifest_error"] = traceback.format_exc()[-300:]
    return report
