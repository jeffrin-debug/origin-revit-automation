# ceiling_joints_on_furring.py - every ceiling butt joint lands on a furring channel.
#
# The rule "a board ends / starts on the framing behind it" was only ever ENFORCED on walls
# (wall_split_first / wall_end_joints lay sheets out on real stud lines). On ceilings it held by
# coincidence: the generator lays 8 ft cells from the same origin as the 16 in furring grid, so its
# own 8 ft joints fall on a channel (96 = 6 x 16) and ceiling_end_joints.py only ever moves them by
# whole bays. Every OTHER cut the generator makes is off that grid - above all "a wall ENDS inside
# a cell: split the whole cell at the wall's end line", whose line is wall geometry. C9 2026-09-29:
# wall 002 starts at wall 004's centreline, y = 423.83 in, inside C007's 333.83..429.83 cell, so
# DP-C007-005 / DP-C007-006 butted at 423.83 - 6 in from one channel, 10 in from the next - and
# nothing checked ceiling joints at all (diag_joints_on_studs.py read WALL= boards only).
#
# This pass works on the FINISHED boards, so it does not matter which generator path made the
# cut. Per ceiling, the furring channels actually in the model (ST-C###, "| FURRING |") give the
# joint axis (channels run along X -> butt joints are edges at constant y) and the channel lines.
# Two boards of one ceiling and layer that touch along such an edge form a butt joint; it is ON
# framing when a channel line is within TOL_IN of it and channel steel covers >= COVER_MIN of its
# length. An off-channel joint moves to the nearest channel line that
#
#   * leaves the shrinking board >= MIN_PIECE_IN along the axis,
#   * keeps the growing board within one sheet (<= 4 x 8 ft plan extent),
#   * is itself covered by channel steel,
#
# by cutting the strip between the old and new joint (across the shared edge only) out of one
# board and unioning it onto the other - in a SubTransaction, rolled back unless both stay single
# solids and the volume is conserved. What cannot move is reported with the reason, and check()
# (read-only) runs after every panels run so an off-channel joint can never go unnoticed again.

import json
import os
import traceback

APP_ID = "ORIGIN_CEILING_V1"
CFG = {
    "TOL_IN": 0.30,          # joint this close to a channel centreline counts as on it
    "COVER_MIN": 0.75,       # share of the joint's length that channel steel must back
    "MIN_PIECE_IN": 16.0,    # neither board may drop below one furring bay along the axis
    "SHEET_SHORT_IN": 48.0,
    "SHEET_LONG_IN": 96.0,
    "TOUCH_IN": 0.25,        # boards whose edges are this close are butting
    "LINE_MERGE_IN": 0.5,    # furring pieces this close on the cross axis are one line
    "VOL_REL_TOL": 0.01,
    "MAX_PASSES": 6,
}


# ------------------------------------------------------------------ pure geometry (offline)
# Everything below works in inches on plan boxes (x0, y0, x1, y1) - no Revit.

def furring_lines(furs, cfg=None):
    """furs = [(x0, y0, x1, y1)] channel plan boxes of one ceiling. Returns (joint_axis, lines):
    joint_axis 'y' when channels run along X (so butt joints are edges at constant y), and
    lines = [(value, [(lo, hi), ...])] - each channel line with the steel along it."""
    cfg = dict(CFG, **(cfg or {}))
    if not furs:
        return None, []
    along_x = sum(1 for f in furs if (f[2] - f[0]) >= (f[3] - f[1]))
    axis = "y" if along_x * 2 >= len(furs) else "x"
    lines = []
    for f in furs:
        if axis == "y":
            v, seg = (f[1] + f[3]) / 2.0, (f[0], f[2])
        else:
            v, seg = (f[0] + f[2]) / 2.0, (f[1], f[3])
        for ln in lines:
            if abs(ln[0] - v) <= cfg["LINE_MERGE_IN"]:
                ln[1].append(seg)
                break
        else:
            lines.append([v, [seg]])
    lines.sort(key=lambda t: t[0])
    return axis, [(v, sorted(s)) for (v, s) in lines]


def covered(segs, lo, hi):
    """Length of [lo, hi] covered by the union of segs."""
    tot, cur = 0.0, lo
    for (a, b) in sorted(segs):
        a, b = max(a, cur), min(b, hi)
        if b > a:
            tot += b - a
            cur = b
    return tot


def _ax(box, axis):
    """(lo, hi) of a box along the joint axis, then across it."""
    if axis == "y":
        return (box[1], box[3]), (box[0], box[2])
    return (box[0], box[2]), (box[1], box[3])


def butt_joints(boards, axis, cfg=None):
    """boards = [{"mark", "box": (x0,y0,x1,y1), "layer"}]. Every pair that butts along an edge at
    constant `axis`: [(lower_idx, upper_idx, c, lo, hi)] - c the joint line, lo..hi its extent."""
    cfg = dict(CFG, **(cfg or {}))
    tol = cfg["TOUCH_IN"]
    out = []
    for i in range(len(boards)):
        for j in range(len(boards)):
            if i == j or boards[i].get("layer") != boards[j].get("layer"):
                continue
            (a0, a1), (ac0, ac1) = _ax(boards[i]["box"], axis)
            (b0, b1), (bc0, bc1) = _ax(boards[j]["box"], axis)
            if abs(a1 - b0) > tol or a0 >= b0:
                continue
            lo, hi = max(ac0, bc0), min(ac1, bc1)
            if hi - lo > tol:
                out.append((i, j, (a1 + b0) / 2.0, lo, hi))
    return out


def line_backing(lines, c, lo, hi, cfg=None):
    """Best channel line for a joint at c spanning lo..hi: (line_value, offset_in, cover_share)."""
    cfg = dict(CFG, **(cfg or {}))
    best = None
    for (v, segs) in lines:
        off = abs(v - c)
        share = covered(segs, lo, hi) / max(hi - lo, 1e-9)
        if best is None or off < best[1] - 1e-9:
            best = (v, off, share)
    return best


def is_on_channel(lines, c, lo, hi, cfg=None):
    cfg = dict(CFG, **(cfg or {}))
    for (v, segs) in lines:
        if abs(v - c) <= cfg["TOL_IN"] and covered(segs, lo, hi) >= cfg["COVER_MIN"] * (hi - lo) - 1e-6:
            return True
    return False


def plan_move(boards, joint, axis, lines, cfg=None):
    """Where an off-channel joint should go. Returns ({"to", "grow", "shrink"}, None) or
    (None, reason). grow/shrink are board indices; the strip between c and `to` across lo..hi
    moves from shrink to grow."""
    cfg = dict(CFG, **(cfg or {}))
    i, j, c, lo, hi = joint
    (a0, a1), (ac0, ac1) = _ax(boards[i]["box"], axis)          # lower board
    (b0, b1), (bc0, bc1) = _ax(boards[j]["box"], axis)          # upper board
    mn = cfg["MIN_PIECE_IN"]
    cands, why = [], []
    for (v, segs) in lines:
        if abs(v - c) <= cfg["TOL_IN"]:
            continue
        if covered(segs, lo, hi) < cfg["COVER_MIN"] * (hi - lo) - 1e-6:
            continue
        if v > c:                        # lower board grows up to v, upper shrinks
            grow, shrink = i, j
            rest = b1 - v
            g_along = v - a0
            g_cross = max(ac1, hi) - min(ac0, lo)
        else:                            # upper board grows down to v, lower shrinks
            grow, shrink = j, i
            rest = v - a0
            g_along = b1 - v
            g_cross = max(bc1, hi) - min(bc0, lo)
        if rest < mn - 1e-6:
            why.append("{:.2f}: leaves a {:.1f} in piece".format(v, rest))
            continue
        long_side, short_side = max(g_along, g_cross), min(g_along, g_cross)
        if long_side > cfg["SHEET_LONG_IN"] + 1e-6 or short_side > cfg["SHEET_SHORT_IN"] + 1e-6:
            why.append("{:.2f}: grown sheet {:.1f} x {:.1f} in".format(v, g_cross, g_along))
            continue
        cands.append((abs(v - c), -rest, v, grow, shrink))
    if not cands:
        return None, "no channel line within reach keeps both boards legal ({})".format(
            "; ".join(why[:4]) or "no channel steel under the joint's extent")
    cands.sort()
    _, _, v, grow, shrink = cands[0]
    return {"to": v, "grow": grow, "shrink": shrink}, None


def survey(boards, furs, cfg=None):
    """One ceiling: every butt joint and whether it is on a channel. Returns (axis, lines, rows)."""
    cfg = dict(CFG, **(cfg or {}))
    axis, lines = furring_lines(furs, cfg)
    rows = []
    if axis is None:
        return axis, lines, rows
    for jt in butt_joints(boards, axis, cfg):
        i, j, c, lo, hi = jt
        on = is_on_channel(lines, c, lo, hi, cfg)
        bk = line_backing(lines, c, lo, hi, cfg)
        rows.append({"joint": jt, "on": on, "a": boards[i]["mark"], "b": boards[j]["mark"],
                     "axis": axis, "at_in": round(c, 2), "from_in": round(lo, 2), "to_in": round(hi, 2),
                     "nearest_channel_in": round(bk[0], 2) if bk else None,
                     "off_by_in": round(bk[1], 2) if bk else None})
    return axis, lines, rows


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
    """{host: {"boards": [...], "furs": [(x0,y0,x1,y1) in]}} for every ORIGIN ceiling."""
    out = {}
    for ds in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape).WhereElementIsNotElementType():
        cm = _par(DB, ds, DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not cm.startswith(APP_ID + " |"):
            continue
        toks = [t.strip() for t in cm.split("|")]
        host = [t for t in toks if t.startswith("CEILING=")]
        bb = ds.get_BoundingBox(None)
        if not host or bb is None:
            continue
        box = (bb.Min.X * 12.0, bb.Min.Y * 12.0, bb.Max.X * 12.0, bb.Max.Y * 12.0)
        rec = out.setdefault(host[0][8:], {"boards": [], "furs": []})
        mk = _par(DB, ds, DB.BuiltInParameter.ALL_MODEL_MARK)
        if "FURRING" in toks:
            rec["furs"].append(box)
        elif "DRYWALL" in toks and mk.startswith("DP-") and not mk.startswith("DP-S"):
            layer = [t for t in toks if t[:1] == "L" and t[1:].isdigit()]
            rec["boards"].append({"ds": ds, "mark": mk, "cm": cm, "box": box,
                                  "layer": layer[0] if layer else None,
                                  "z": (bb.Min.Z, bb.Max.Z)})
    return out


def check(doc, cfg=None):
    """Read-only: every ceiling butt joint, and the ones not on a furring channel."""
    DB, _, _ = _revit()
    cfg = dict(CFG, **(cfg or {}))
    rep = {"ok": True, "ceilings": 0, "joints": 0, "on_channel": 0, "off_channel": [],
           "no_furring": []}
    for host, rec in sorted(_collect(doc, DB).items()):
        if not rec["boards"]:
            continue
        rep["ceilings"] += 1
        axis, lines, rows = survey(rec["boards"], rec["furs"], cfg)
        if axis is None:
            rep["no_furring"].append(host)
            continue
        for r in rows:
            rep["joints"] += 1
            if r["on"]:
                rep["on_channel"] += 1
            else:
                rep["off_channel"].append(dict([("ceiling", host)] + [(k, v) for k, v in r.items()
                                                                      if k not in ("joint", "on")]))
    rep["ok"] = not rep["off_channel"]
    return rep


def _apply(doc, DB, List, boards, mv, joint, axis, cfg):
    i, j, c, lo, hi = joint
    g, s = boards[mv["grow"]], boards[mv["shrink"]]
    # reach just past the OLD joint line (so no hairline of the shrinking board is left on the
    # grown side) but stop exactly on the channel line
    pad = 0.02
    a0, a1 = (c - pad, mv["to"]) if mv["to"] > c else (mv["to"], c + pad)
    z0 = min(g["z"][0], s["z"][0]) - 0.01
    z1 = max(g["z"][1], s["z"][1]) + 0.01
    if axis == "y":
        x0, y0, x1, y1 = lo, a0, hi, a1
    else:
        x0, y0, x1, y1 = a0, lo, a1, hi
    pts = [DB.XYZ(x / 12.0, y / 12.0, z0) for (x, y) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    loop = DB.CurveLoop()
    for k in range(4):
        loop.Append(DB.Line.CreateBound(pts[k], pts[(k + 1) % 4]))
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    slab = DB.GeometryCreationUtilities.CreateExtrusionGeometry(loops, DB.XYZ.BasisZ, z1 - z0)
    sg, ss = _solids(DB, g["ds"]), _solids(DB, s["ds"])
    if len(sg) != 1 or len(ss) != 1:
        raise Exception("boards are not single solids")
    B = DB.BooleanOperationsUtils.ExecuteBooleanOperation
    T = DB.BooleanOperationsType
    strip = B(ss[0], slab, T.Intersect)
    rest = B(ss[0], slab, T.Difference)
    if strip is None or rest is None or strip.Volume <= 1e-9:
        raise Exception("boolean failed")
    grown = B(sg[0], strip, T.Union)
    want = sg[0].Volume + ss[0].Volume
    if grown is None or abs(grown.Volume + rest.Volume - want) > cfg["VOL_REL_TOL"] * want:
        raise Exception("volume not conserved")
    if len(DB.SolidUtils.SplitVolumes(grown)) != 1 or len(DB.SolidUtils.SplitVolumes(rest)) != 1:
        raise Exception("a board would split in two")
    for (b, sol) in ((g, grown), (s, rest)):
        shp = List[DB.GeometryObject]()
        shp.Add(sol)
        b["ds"].SetShape(shp)
    tag = " JOINT_TO_FURRING={:.2f}->{:.2f}in".format(c, mv["to"])
    for b in (g, s):
        p = b["ds"].get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p is not None and not p.IsReadOnly:
            p.Set(b["cm"] + tag)


def _update_manifest(doc, DB, path, hosts_marks):
    """Refresh bbox_ft of every board this pass reshaped."""
    if not path or not os.path.exists(path) or not hosts_marks:
        return False
    live = {}
    for host, rec in _collect(doc, DB).items():
        for b in rec["boards"]:
            if (host, b["mark"]) in hosts_marks:
                x0, y0, x1, y1 = b["box"]
                live[(host, b["mark"])] = [round(x0 / 12.0, 3), round(y0 / 12.0, 3),
                                           round(x1 / 12.0, 3), round(y1 / 12.0, 3)]
    with open(path) as fh:
        m = json.load(fh)
    for r in m.get("boards", []):
        host = str(r.get("host_ceiling"))
        key = (host if host.startswith("C") else "C" + host, r.get("board_id"))
        if key in live:
            r["bbox_ft"] = live[key]
            r["joint_moved_to_furring"] = True
    m.setdefault("summary", {})["ceiling_joints_moved_to_furring"] = len(hosts_marks) // 2
    with open(path, "w") as fh:
        json.dump(m, fh, indent=2)
    return True


def run(doc, manifest_path=None, cfg=None):
    """Move every off-channel ceiling joint onto a channel, then check. Own transaction."""
    DB, TM, List = _revit()
    cfg = dict(CFG, **(cfg or {}))
    rep = {"moved": [], "left": [], "failed": []}
    touched = set()
    try:
        TM.Instance.ForceCloseTransaction()
    except Exception:
        pass
    TM.Instance.EnsureInTransaction(doc)
    try:
        tried = set()
        for _ in range(cfg["MAX_PASSES"]):
            did = False
            left = []
            for host, rec in sorted(_collect(doc, DB).items()):
                boards = rec["boards"]
                axis, lines, rows = survey(boards, rec["furs"], cfg)
                used = set()
                for r in rows:
                    if r["on"]:
                        continue
                    jt = r["joint"]
                    row = {"ceiling": host, "a": r["a"], "b": r["b"], "at_in": r["at_in"],
                           "from_in": r["from_in"], "to_in": r["to_in"]}
                    key = (host, r["a"], r["b"], r["at_in"])
                    if key in tried:
                        continue
                    if used.intersection((jt[0], jt[1])):
                        continue                  # a board changed this pass - next pass sees it
                    mv, why = plan_move(boards, jt, axis, lines, cfg)
                    if mv is None:
                        row["why"] = why
                        left.append(row)
                        tried.add(key)
                        continue
                    tried.add(key)
                    st = DB.SubTransaction(doc)
                    st.Start()
                    try:
                        _apply(doc, DB, List, boards, mv, jt, axis, cfg)
                        st.Commit()
                        doc.Regenerate()
                        used.update((jt[0], jt[1]))
                        touched.update(((host, r["a"]), (host, r["b"])))
                        row.update({"moved_to_in": round(mv["to"], 2),
                                    "grew": boards[mv["grow"]]["mark"],
                                    "shrank": boards[mv["shrink"]]["mark"]})
                        rep["moved"].append(row)
                        did = True
                    except Exception as ex:
                        st.RollBack()
                        row["why"] = "move failed: " + str(ex)[:160]
                        rep["failed"].append(row)
            rep["left"] = left
            if not did:
                break
        doc.Regenerate()
    finally:
        TM.Instance.TransactionTaskDone()
        try:
            TM.Instance.ForceCloseTransaction()
        except Exception:
            rep["force_close_error"] = traceback.format_exc()[-300:]
    try:
        rep["manifest_updated"] = _update_manifest(doc, DB, manifest_path, touched)
    except Exception:
        rep["manifest_error"] = traceback.format_exc()[-300:]
    rep["check"] = check(doc, cfg)
    return rep
