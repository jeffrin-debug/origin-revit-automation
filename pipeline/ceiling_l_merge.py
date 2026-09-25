# ceiling_l_merge.py - rejoin ceiling boards that were split with no wall on the seam, L-shapes too.
#
# The ceiling generator cuts each 4x8 cell where walls need it. Where a wall ENDS inside a cell it
# first slices the WHOLE cell at the wall's end line ("so the part beyond the stub stays whole"),
# which is right for a stub in the middle of a room but leaves a needless seam where the wall ends
# at the corner of a notch in the ceiling. In 1F: soffit wall 006 ends at y = 307.44in inside
# C007's cell, so DP-C007-006 (54.5 x 33.25in) and DP-C007-007 (13.75 x 14.75in) came out as two
# boards that are really one sheet with a notch cut out of it.
#
# The generator's own merge_boards_split_without_real_wall() would rejoin them, but only when the
# two boards line up full-width on one side (a rectangle union). User direction 2026-09-25: "we
# can have even L shaped panel where needed". This pass merges two boards of the same ceiling when
#
#   1. they touch along the WHOLE edge of the smaller board        (one sheet, not a patchwork)
#   2. no wall that reaches the ceiling crosses that shared edge    (the generator's own test,
#                                                                    endpoint-touching allowed)
#   3. the merged outline still fits one standard sheet (<= 4 x 8 ft) - the generator's cap
#   4. the union is one solid whose volume is the two boards' sum  (no overlap, nothing lost)
#
# and repeats until nothing more merges. The larger board keeps its mark and gets
# "L_MERGED=<other>" in its comments; the ceiling manifest drops the absorbed board and widens the
# survivor's bbox. The generator's narrow-soffit boards (DP-S###-*, "exactly two boards" by design)
# are left alone. The generator file itself is not touched.

import json
import os
import traceback

APP_ID = "ORIGIN_CEILING_V1"
CFG = {
    "TOL_FT": 0.02,
    "SHEET_SHORT_FT": 4.0,
    "SHEET_LONG_FT": 8.0,
    "WALL_TOL_FT": 0.05,
    "VOL_REL_TOL": 0.02,
}


# ------------------------------------------------------------------ pure geometry (offline)

def shared_edge(a, b, tol):
    """a, b = (x0, y0, x1, y1, z0, z1). If they touch along an edge, return
    (vertical, c, lo, hi) - the shared segment - else None."""
    if abs(a[4] - b[4]) > tol or abs(a[5] - b[5]) > tol:
        return None
    for (p, q) in ((a, b), (b, a)):
        if abs(p[2] - q[0]) <= tol:                              # p's right edge = q's left edge
            lo, hi = max(p[1], q[1]), min(p[3], q[3])
            if hi - lo > tol:
                return (True, (p[2] + q[0]) / 2.0, lo, hi)
        if abs(p[3] - q[1]) <= tol:                              # p's top edge = q's bottom edge
            lo, hi = max(p[0], q[0]), min(p[2], q[2])
            if hi - lo > tol:
                return (False, (p[3] + q[1]) / 2.0, lo, hi)
    return None


def wall_crosses(walls, vertical, c, lo, hi, tol):
    """The ceiling generator's _wall_crosses_segment(): a wall touching only an END of the
    segment does not count. walls = [(x0, y0, x1, y1)] plan boxes of walls that reach the ceiling."""
    for (wx0, wy0, wx1, wy1) in walls:
        if vertical:
            if wx0 - tol <= c <= wx1 + tol and wy1 > lo + tol and wy0 < hi - tol:
                return True
        else:
            if wy0 - tol <= c <= wy1 + tol and wx1 > lo + tol and wx0 < hi - tol:
                return True
    return False


def candidates(boards, walls, cfg=None):
    """boards = [{"mark", "box": (x0,y0,x1,y1,z0,z1), "layer"}], one ceiling. Returns every pair
    that passes tests 1-3, longest shared edge first: [(i, j, (vertical, c, lo, hi))]."""
    cfg = dict(CFG, **(cfg or {}))
    tol = cfg["TOL_FT"]
    out = []
    for i in range(len(boards)):
        a = boards[i]["box"]
        for j in range(i + 1, len(boards)):
            if boards[i].get("layer") != boards[j].get("layer"):
                continue
            b = boards[j]["box"]
            e = shared_edge(a, b, tol)
            if e is None:
                continue
            vertical, c, lo, hi = e
            # 1. the smaller board's whole edge is on the seam
            ea = (a[3] - a[1]) if vertical else (a[2] - a[0])
            eb = (b[3] - b[1]) if vertical else (b[2] - b[0])
            if (hi - lo) < min(ea, eb) - tol:
                continue
            # 3. one sheet
            ux = max(a[2], b[2]) - min(a[0], b[0])
            uy = max(a[3], b[3]) - min(a[1], b[1])
            if min(ux, uy) > cfg["SHEET_SHORT_FT"] + 1e-6 or max(ux, uy) > cfg["SHEET_LONG_FT"] + 1e-6:
                continue
            # 2. no wall on the seam
            if wall_crosses(walls, vertical, c, lo, hi, cfg["WALL_TOL_FT"]):
                continue
            # An L-merge only removes a NEEDLESS seam. A line other boards also end on is a real
            # butt joint / grid line; folding a board across it would leave a stepped joint.
            if abs(ea - eb) > tol:
                on_joint = False
                for k in range(len(boards)):
                    if k in (i, j):
                        continue
                    kb = boards[k]["box"]
                    edges = (kb[0], kb[2]) if vertical else (kb[1], kb[3])
                    if any(abs(v - c) <= tol for v in edges):
                        on_joint = True
                        break
                if on_joint:
                    continue
            out.append((i, j, e))
    out.sort(key=lambda t: -(t[2][3] - t[2][2]))
    return out


# ------------------------------------------------------------------ Revit side

def _revit():
    import clr
    clr.AddReference('RevitAPI')
    clr.AddReference('RevitServices')
    from Autodesk.Revit import DB
    from RevitServices.Transactions import TransactionManager
    from System.Collections.Generic import List
    return DB, TransactionManager, List


def _par(DB, e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def _solids(DB, e):
    try:
        return [g for g in (e.get_Geometry(DB.Options()) or [])
                if isinstance(g, DB.Solid) and g.Volume > 1e-9]
    except Exception:
        return []


def _collect(doc, DB):
    by_ceiling = {}
    for ds in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape).WhereElementIsNotElementType():
        cm = _par(DB, ds, DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith(APP_ID + " |") or "| DRYWALL |" not in cm:
            continue
        mk = _par(DB, ds, DB.BuiltInParameter.ALL_MODEL_MARK)
        if not mk.startswith("DP-") or mk.startswith("DP-S"):
            continue
        host = [t.strip() for t in cm.split("|") if t.strip().startswith("CEILING=")]
        layer = [t.strip() for t in cm.split("|") if t.strip()[:1] == "L" and t.strip()[1:].isdigit()]
        bb = ds.get_BoundingBox(None)
        if not host or bb is None:
            continue
        by_ceiling.setdefault(host[0], []).append({
            "ds": ds, "mark": mk, "cm": cm, "layer": layer[0] if layer else None,
            "box": (bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y, bb.Min.Z, bb.Max.Z)})
    return by_ceiling


def _walls_reaching(doc, DB, z, tol):
    out = []
    for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType():
        try:
            if w.WallType.Kind == DB.WallKind.Curtain:
                continue
        except Exception:
            pass
        bb = w.get_BoundingBox(None)
        if bb is not None and bb.Min.Z <= z + tol and bb.Max.Z >= z - tol:
            out.append((bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y))
    return out


def plan(doc, cfg=None):
    """Read-only: which pairs would merge on the first pass, per ceiling."""
    DB, _, _ = _revit()
    cfg = dict(CFG, **(cfg or {}))
    out = []
    for host, boards in sorted(_collect(doc, DB).items()):
        walls = _walls_reaching(doc, DB, min(b["box"][4] for b in boards), 0.25)
        for (i, j, e) in candidates(boards, walls, cfg):
            out.append({"ceiling": host, "a": boards[i]["mark"], "b": boards[j]["mark"],
                        "seam": {"axis": "x" if e[0] else "y", "at_in": round(e[1] * 12, 2),
                                 "from_in": round(e[2] * 12, 2), "to_in": round(e[3] * 12, 2)}})
    return {"pairs": out}


def _merge_pair(doc, DB, List, keep, gone, cfg):
    sa, sb = _solids(DB, keep["ds"]), _solids(DB, gone["ds"])
    if len(sa) != 1 or len(sb) != 1:
        raise Exception("not single solids")
    u = DB.BooleanOperationsUtils.ExecuteBooleanOperation(sa[0], sb[0], DB.BooleanOperationsType.Union)
    want = sa[0].Volume + sb[0].Volume
    if u is None or abs(u.Volume - want) > cfg["VOL_REL_TOL"] * want:
        raise Exception("union volume does not add up")
    if len(DB.SolidUtils.SplitVolumes(u)) != 1:
        raise Exception("union is not one piece")
    shape = List[DB.GeometryObject]()
    shape.Add(u)
    keep["ds"].SetShape(shape)
    cm = keep["cm"] + " L_MERGED={}".format(gone["mark"])
    p = keep["ds"].get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(cm)
    doc.Delete(gone["ds"].Id)


def _update_manifest(path, merges):
    if not path or not os.path.exists(path) or not merges:
        return False
    with open(path) as fh:
        m = json.load(fh)
    rec = dict((b.get("board_id"), b) for b in m.get("boards", []))
    gone = set()
    for x in merges:
        k, g = rec.get(x["kept"]), rec.get(x["absorbed"])
        if k is not None and g is not None and k.get("bbox_ft") and g.get("bbox_ft"):
            kb, gb = k["bbox_ft"], g["bbox_ft"]
            k["bbox_ft"] = [min(kb[0], gb[0]), min(kb[1], gb[1]), max(kb[2], gb[2]), max(kb[3], gb[3])]
        if k is not None:
            k.setdefault("merged_from", []).append(x["absorbed"])
            k["shape"] = "L" if x["l_shaped"] else k.get("shape", "rect")
        gone.add(x["absorbed"])
    m["boards"] = [b for b in m.get("boards", []) if b.get("board_id") not in gone]
    m.setdefault("summary", {})["ceiling_l_merges"] = len(merges)
    with open(path, "w") as fh:
        json.dump(m, fh, indent=2)
    return True


def run(doc, manifest_path=None, cfg=None):
    """Merge every qualifying pair, repeatedly. Opens and commits its own transaction."""
    DB, TM, List = _revit()
    cfg = dict(CFG, **(cfg or {}))
    rep = {"merged": [], "failed": []}
    try:
        TM.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TM.Instance.EnsureInTransaction(doc)
    try:
        tried = set()
        while True:
            did = False
            for host, boards in sorted(_collect(doc, DB).items()):
                walls = _walls_reaching(doc, DB, min(b["box"][4] for b in boards), 0.25)
                for (i, j, e) in candidates(boards, walls, cfg):
                    a, b = boards[i], boards[j]
                    # marks repeat across ceilings (DP-C007-006 exists once per C007 build), so
                    # the ceiling is part of the key
                    key = (host,) + tuple(sorted((a["mark"], b["mark"])))
                    if key in tried:
                        continue
                    tried.add(key)
                    area = lambda r: (r["box"][2] - r["box"][0]) * (r["box"][3] - r["box"][1])
                    keep, gone = (a, b) if area(a) >= area(b) else (b, a)
                    ea = (a["box"][3] - a["box"][1]) if e[0] else (a["box"][2] - a["box"][0])
                    eb = (b["box"][3] - b["box"][1]) if e[0] else (b["box"][2] - b["box"][0])
                    st = DB.SubTransaction(doc)
                    st.Start()
                    try:
                        _merge_pair(doc, DB, List, keep, gone, cfg)
                        st.Commit()
                        rep["merged"].append({
                            "ceiling": host, "kept": keep["mark"], "absorbed": gone["mark"],
                            "l_shaped": abs(ea - eb) > cfg["TOL_FT"],
                            "seam": {"axis": "x" if e[0] else "y", "at_in": round(e[1] * 12, 2),
                                     "from_in": round(e[2] * 12, 2), "to_in": round(e[3] * 12, 2)}})
                        did = True
                    except Exception as ex:
                        st.RollBack()
                        rep["failed"].append({"a": a["mark"], "b": b["mark"], "why": str(ex)[:200]})
                        continue
                    break                       # boards changed - rescan this ceiling
                if did:
                    doc.Regenerate()
                    break
            if not did:
                break
    finally:
        TM.Instance.TransactionTaskDone()
        try:
            TM.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-300:]
    try:
        rep["manifest_updated"] = _update_manifest(manifest_path, rep["merged"])
    except Exception:
        rep["manifest_error"] = traceback.format_exc()[-300:]
    return rep
