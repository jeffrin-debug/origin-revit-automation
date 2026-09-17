# w1_core.py
# ============================================================
# W1 / H1 - "one physical wall is one wall element" - detection and merge, with NO driver.
#
# Exec'd by both drivers so the algorithm exists exactly once:
#   conformance_fix_w1.py   batch, background documents, SaveAs -> 00_normalized
#   w1_apply_active.py      the document open in the Revit UI, in place, nothing saved
#
# (The ceiling and soffit generators in the drywall repo are the same 2,400-line file twice,
# differing only in two constants - every fix there has to be made in both or they silently
# diverge. Not repeating that here.)
#
# NOTE: the bridge's exec() context does not support the XYZ '-' operator ("unsupported operand
# type(s) for -: 'XYZ' and 'XYZ'"), so all vector maths is on components.
# ============================================================

import math
import traceback

from Autodesk.Revit.DB import (
    FilteredElementCollector, Wall, WallKind, WallUtils, Line, XYZ, Transaction,
    BuiltInParameter, FamilyInstance)

ANGLE_TOL_DEG = 1.0
OFFSET_TOL_FT = 0.02
GAP_TOL_FT = 0.05
# If a single env's chains would remove more than this share of its walls, that is more likely a
# wrong tolerance than a wholly broken model: report, do not rewrite. The worst real env in the
# 30-model corpus sits near 0.52.
MAX_REMOVED_SHARE = 0.75
# Merging creates new adjacency, so sweeps repeat until one changes nothing. A clean env settles
# in 2-3; the bound stops a pathological model spinning.
MAX_PASSES = 6


def read_walls(doc):
    """Straight, non-curtain walls with everything the detectors and the W4 guard need."""
    out = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            if w.WallType is not None and w.WallType.Kind == WallKind.Curtain:
                continue
        except Exception:
            pass
        try:
            c = w.Location.Curve
        except Exception:
            continue
        if not isinstance(c, Line):
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        dx, dy = p1.X - p0.X, p1.Y - p0.Y
        L = math.sqrt(dx * dx + dy * dy)
        if L < 1e-9:
            continue

        def pd(bip):
            try:
                p = w.get_Parameter(bip)
                return p.AsDouble() if p else None
            except Exception:
                return None

        def pi(bip):
            try:
                p = w.get_Parameter(bip)
                return p.AsInteger() if p else None
            except Exception:
                return None

        try:
            lvl = w.LevelId.IntegerValue if hasattr(w.LevelId, "IntegerValue") else w.LevelId.Value
        except Exception:
            lvl = None
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
        except Exception:
            mk = None
        out.append({
            "el": w,
            "eid": w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value,
            "mark": mk, "name": w.Name,
            "width": (w.WallType.Width if w.WallType else None),
            "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y), "z0": p0.Z,
            "d": (dx / L, dy / L), "len": L,
            "height": pd(BuiltInParameter.WALL_USER_HEIGHT_PARAM),
            "base_off": pd(BuiltInParameter.WALL_BASE_OFFSET),
            "base_lvl": lvl,
            "key_ref": pi(BuiltInParameter.WALL_KEY_REF_PARAM),
            "rb": pi(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING),
        })
    return out


def same_line(a, b):
    ax, ay = a["d"]
    bx, by = b["d"]
    if abs(ax * bx + ay * by) < math.cos(math.radians(ANGLE_TOL_DEG)):
        return False
    if abs(a["z0"] - b["z0"]) > OFFSET_TOL_FT:
        return False
    vx, vy = b["p0"][0] - a["p0"][0], b["p0"][1] - a["p0"][1]
    return abs(vx * (-ay) + vy * ax) <= OFFSET_TOL_FT


def touching(a, b):
    for pa in (a["p0"], a["p1"]):
        for pb in (b["p0"], b["p1"]):
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= GAP_TOL_FT:
                return True
    return False


def find_chains(walls):
    parent = dict((w["eid"], w["eid"]) for w in walls)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            if a["name"] != b["name"]:
                continue
            if a["width"] is None or b["width"] is None or abs(a["width"] - b["width"]) > 1e-4:
                continue
            if not same_line(a, b) or not touching(a, b):
                continue
            ra, rb = find(a["eid"]), find(b["eid"])
            if ra != rb:
                parent[rb] = ra

    groups = {}
    for w in walls:
        groups.setdefault(find(w["eid"]), []).append(w)
    return [m for m in groups.values() if len(m) > 1]


def attrs_uniform(mem):
    def s(key, rnd=False):
        vals = []
        for m in mem:
            v = m[key]
            if rnd and v is not None:
                v = round(v, 4)
            vals.append(v)
        return len(set(vals)) == 1
    return (s("height", True) and s("base_off", True) and s("base_lvl")
            and s("key_ref") and s("rb") and s("name"))


def hosted_map(doc, eids):
    out = {}
    for fi in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
        try:
            h = fi.Host
            if h is None:
                continue
            hid = h.Id.IntegerValue if hasattr(h.Id, "IntegerValue") else h.Id.Value
        except Exception:
            continue
        if hid in eids:
            try:
                cat = fi.Category.Name if fi.Category else "?"
            except Exception:
                cat = "?"
            out.setdefault(hid, []).append(cat)
    return out


def chain_endpoints(mem):
    d = mem[0]["d"]
    o = mem[0]["p0"]
    best_lo = best_hi = None
    lo_t = hi_t = None
    for m in mem:
        for p in (m["p0"], m["p1"]):
            t = (p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1]
            if lo_t is None or t < lo_t:
                lo_t, best_lo = t, p
            if hi_t is None or t > hi_t:
                hi_t, best_hi = t, p
    return best_lo, best_hi, (hi_t - lo_t)


def label(mem):
    """Source envs carry no Marks - those are assigned later by the drywall generator - so a
    chain is identified by element id, which always exists."""
    return [(m["mark"] if m["mark"] else "id" + str(m["eid"])) for m in mem]


def try_merge_one(doc, survivor, doomed, lo, hi, span, break_joins):
    """One attempt at one chain, in its own Transaction. Returns (ok, why).

    break_joins retries with the survivor's end joins disallowed: a joined wall does not always
    accept a longer LocationCurve and silently keeps a clamped length rather than raising (seen
    live - a survivor stretched to 3.750 ft when the chain span was 11.500 ft). Restored after."""
    z = survivor["z0"]
    before = len(list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType()))
    t = Transaction(doc, "ORIGIN W1 merge")
    t.Start()
    ok = False
    why = None
    try:
        for m in doomed:
            doc.Delete(m["el"].Id)
        doc.Regenerate()

        sw = survivor["el"]
        if break_joins:
            for end in (0, 1):
                try:
                    WallUtils.DisallowWallJoinAtEnd(sw, end)
                except Exception:
                    pass
            doc.Regenerate()

        sw.Location.Curve = Line.CreateBound(XYZ(lo[0], lo[1], z), XYZ(hi[0], hi[1], z))
        doc.Regenerate()

        if break_joins:
            for end in (0, 1):
                try:
                    WallUtils.AllowWallJoinAtEnd(sw, end)
                except Exception:
                    pass
            doc.Regenerate()

        after = len(list(FilteredElementCollector(doc).OfClass(Wall)
                         .WhereElementIsNotElementType()))
        got = sw.Location.Curve.Length
        if after != before - len(doomed):
            why = "wall count {}->{}, expected {}".format(before, after, before - len(doomed))
        elif abs(got - span) > 0.02:
            why = "survivor length {:.3f} ft, expected span {:.3f} ft".format(got, span)
        else:
            ok = True
    except Exception:
        why = traceback.format_exc().strip().split("\n")[-1][:200]

    if ok:
        t.Commit()
    else:
        try:
            t.RollBack()
        except Exception:
            pass
    return ok, why


def merge_pass(doc):
    """One detect-and-merge sweep. Returns (merged, removed, skipped, failed, chains_found)."""
    walls = read_walls(doc)
    chains = find_chains(walls)
    hosts = hosted_map(doc, set(w["eid"] for w in walls))

    merged = removed = 0
    skipped, failed = [], []

    for mem in chains:
        ids = label(mem)
        if not attrs_uniform(mem):
            skipped.append({"chain": ids, "why": "W4 fragments disagree on wall attributes"})
            continue
        host_pieces = [m for m in mem if hosts.get(m["eid"])]
        if len(host_pieces) > 1:
            skipped.append({"chain": ids,
                            "why": "H1 {} fragments carry hosted elements".format(len(host_pieces))})
            continue

        survivor = (max(host_pieces, key=lambda m: m["len"]) if host_pieces
                    else max(mem, key=lambda m: m["len"]))
        doomed = [m for m in mem if m["eid"] != survivor["eid"]]
        lo, hi, span = chain_endpoints(mem)

        ok, why = try_merge_one(doc, survivor, doomed, lo, hi, span, False)
        if not ok:
            # the rollback invalidated those Element handles - re-read before retrying
            fresh = dict((w["eid"], w) for w in read_walls(doc))
            if survivor["eid"] in fresh and all(m["eid"] in fresh for m in doomed):
                ok, why2 = try_merge_one(
                    doc, fresh[survivor["eid"]], [fresh[m["eid"]] for m in doomed],
                    lo, hi, span, True)
                if not ok:
                    why = "{} (retry with joins broken: {})".format(why, why2)
        if ok:
            merged += 1
            removed += len(doomed)
        else:
            failed.append({"chain": ids, "why": why})

    return merged, removed, skipped, failed, len(chains)


def merge_chains(doc, report):
    """Iterate to a fixed point, with the blast-radius guard applied first."""
    walls0 = read_walls(doc)
    report["walls_before"] = len(walls0)
    report["walls_total_before"] = len(list(
        FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType()))
    chains0 = find_chains(walls0)
    would_remove = sum(len(m) - 1 for m in chains0)
    report["chains_found"] = len(chains0)
    report["fragments_to_remove"] = would_remove

    if report["walls_before"] and (float(would_remove) / report["walls_before"]) > MAX_REMOVED_SHARE:
        report["guard_tripped"] = True
        report["note"] = ("W1 would remove {:.0%} of the walls, above the {:.0%} guard - "
                          "reported, not applied. Suspect a tolerance, not the model.".format(
                              float(would_remove) / report["walls_before"], MAX_REMOVED_SHARE))
        report["merged"] = 0
        return report

    merged = removed = 0
    passes = []
    skipped, failed = [], []
    for p in range(MAX_PASSES):
        m, r, sk, fl, found = merge_pass(doc)
        passes.append({"pass": p + 1, "chains_seen": found, "merged": m, "removed": r,
                       "skipped": len(sk), "failed": len(fl)})
        merged += m
        removed += r
        skipped, failed = sk, fl
        if m == 0:
            break

    report["passes"] = passes
    report["merged"] = merged
    report["fragments_removed"] = removed
    report["skipped"] = skipped
    report["failed"] = failed
    walls1 = read_walls(doc)
    report["walls_after"] = len(walls1)
    report["walls_total_after"] = len(list(
        FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType()))
    report["chains_remaining"] = len(find_chains(walls1))
    return report
