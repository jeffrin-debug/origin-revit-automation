# conformance_fix_w1.py
# ============================================================
# STAGE 0, PHASE B - W1 / H1 : one physical wall becomes one wall element.
#
# For each collinear chain (same type + width, one axis, touching end-to-end):
#     1. choose a SURVIVOR   - a fragment carrying hosted elements first, then the longest
#     2. delete the other fragments
#     3. stretch the survivor's LocationCurve to the chain's full span
#     4. re-detect and re-count; commit only if both agree, otherwise ROLL BACK THAT CHAIN
#
# Each chain is its own Transaction, so a failure on chain 14 keeps the thirteen before it.
# Delete-then-stretch, never the reverse: two walls briefly sharing a footprint is what makes
# Revit refuse or silently relocate the survivor.
#
# The source .rvt is NEVER written to - the merged document is SaveAs'd to 00_normalized, and
# the source mtime is asserted unchanged afterwards. With "save": false nothing is written at
# all and this is a pure dry run that still reports exactly what it would have done.
#
# Chains are SKIPPED, never forced, when:
#   W4  fragments disagree on type / width / base level / base offset / height /
#       location-line reference / room-bounding flag
#   H1  two or more fragments carry hosted elements (Revit has no practical re-host API,
#       and a lost door is not recoverable)
#
# NOTE: the bridge's exec() context does not support the XYZ '-' operator, so all vector maths
# here is on components.
# ============================================================

import clr
import json
import math
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

ROOT = r"C:\Users\Origoncad\origin_pipeline"
CONFIG_PATH = os.path.join(ROOT, "_fix_config.json")
OUT_DIR = os.path.join(ROOT, "_reports", "conformance")

ANGLE_TOL_DEG = 1.0
OFFSET_TOL_FT = 0.02
GAP_TOL_FT = 0.05
# Blast-radius guard: if a single env's chains would remove more than this share of its walls,
# the numbers are more likely to mean a wrong tolerance than a wholly broken model. Report,
# do not rewrite. Calibrated against the corpus, where the worst real env sits near 0.52.
MAX_REMOVED_SHARE = 0.75
# Merging can create new adjacency, so sweeps repeat until one changes nothing. Bounded so a
# pathological model cannot spin: in practice a clean env settles in 2-3.
MAX_PASSES = 6

cfg = json.load(open(CONFIG_PATH))
FILES = cfg.get("files") or []
SAVE = bool(cfg.get("save", False))
OUT_NORM = cfg.get("out_normalized") or os.path.join(ROOT, "00_normalized")

for d in (OUT_DIR, OUT_NORM):
    if not os.path.exists(d):
        os.makedirs(d)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

dialogs_seen = []


def _on_dialog(sender, args):
    try:
        dialogs_seen.append(str(args.DialogId))
    except Exception:
        dialogs_seen.append("<unknown>")
    try:
        args.OverrideResult(1)
    except Exception:
        pass


dialog_hooked = False
try:
    uiapp.DialogBoxShowing += _on_dialog
    dialog_hooked = True
except Exception:
    pass


# ============================================================
# detection (kept identical to conformance_audit.py)
# ============================================================

def read_walls(doc):
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
            "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y), "z0": p0.Z, "z1": p1.Z,
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
            and s("key_ref") and s("rb") and s("name") )


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
    """The two extreme points of the chain along its shared axis, as (x, y) pairs."""
    d = mem[0]["d"]
    o = mem[0]["p0"]
    best_lo = None
    best_hi = None
    lo_t = hi_t = None
    for m in mem:
        for p in (m["p0"], m["p1"]):
            t = (p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1]
            if lo_t is None or t < lo_t:
                lo_t, best_lo = t, p
            if hi_t is None or t > hi_t:
                hi_t, best_hi = t, p
    return best_lo, best_hi, (hi_t - lo_t)


# ============================================================
# the fix
# ============================================================

def label(mem):
    """Source envs have no Marks yet - those are assigned later by the drywall generator - so
    identify a chain by element id, which always exists."""
    out = []
    for m in mem:
        out.append(m["mark"] if m["mark"] else "id" + str(m["eid"]))
    return out


def try_merge_one(doc, mem, survivor, doomed, lo, hi, span, break_joins):
    """One attempt at one chain, in its own Transaction. Returns (ok, why).

    break_joins re-runs the attempt after explicitly disallowing the survivor's end joins: a wall
    joined to a neighbour will not always accept a longer LocationCurve, and silently keeps a
    clamped length instead of raising (seen live: a survivor stretched to 3.750 ft when the chain
    span was 11.500 ft). The join is restored after the stretch."""
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


def merge_pass(doc, hosts_cache):
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

        ok, why = try_merge_one(doc, mem, survivor, doomed, lo, hi, span, False)
        if not ok:
            # the rollback invalidated those Element handles - re-read before retrying
            fresh = dict((w["eid"], w) for w in read_walls(doc))
            if survivor["eid"] in fresh and all(m["eid"] in fresh for m in doomed):
                ok, why2 = try_merge_one(
                    doc, mem, fresh[survivor["eid"]],
                    [fresh[m["eid"]] for m in doomed], lo, hi, span, True)
                if not ok:
                    why = "{} (retry with joins broken: {})".format(why, why2)
        if ok:
            merged += 1
            removed += len(doomed)
        else:
            failed.append({"chain": ids, "why": why})

    return merged, removed, skipped, failed, len(chains)


def merge_chains(doc, report):
    """Iterate to a fixed point. Joining two fragments can make the result collinear AND touching
    with a neighbour it did not touch before, so one sweep is not enough - measured live, an env
    still reported 7 chains after a single pass."""
    walls0 = read_walls(doc)
    report["walls_before"] = len(walls0)          # straight, non-curtain - same basis as _after
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
        m, r, sk, fl, found = merge_pass(doc, None)
        passes.append({"pass": p + 1, "chains_seen": found, "merged": m, "removed": r,
                       "skipped": len(sk), "failed": len(fl)})
        merged += m
        removed += r
        skipped, failed = sk, fl          # last pass wins: earlier ones were retried
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


def _save_as(nd, dst):
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    sao = SaveAsOptions()
    try:
        sao.OverwriteExistingFile = True
        sao.Compact = True
        sao.MaximumBackups = 1
    except Exception:
        pass
    nd.SaveAs(ModelPathUtils.ConvertUserVisiblePathToModelPath(dst), sao)
    return dst


rows = []
for path in FILES:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    row = {"file": name, "status": "pending", "saved": None}
    t0 = time.time()

    if not os.path.exists(path):
        row["status"] = "missing"
        rows.append(row)
        continue
    if stem in open_titles:
        row["status"] = "skipped (open in UI)"
        rows.append(row)
        continue

    nd = None
    mtime_before = os.path.getmtime(path)
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(
            ModelPathUtils.ConvertUserVisiblePathToModelPath(path), oo)
        rep = {"file": name, "source": path, "dry_run": (not SAVE)}
        merge_chains(nd, rep)
        if SAVE and rep.get("merged", 0) > 0 and not rep.get("guard_tripped"):
            row["saved"] = _save_as(nd, os.path.join(OUT_NORM, name))
        rep["saved_to"] = row["saved"]
        with open(os.path.join(OUT_DIR, stem + "_w1fix.json"), "w") as f:
            json.dump(rep, f, indent=2)
        row["status"] = "done"
        for k in ("walls_before", "walls_after", "chains_found", "merged", "fragments_removed",
                  "chains_remaining", "guard_tripped"):
            row[k] = rep.get(k)
        row["skipped_chains"] = len(rep.get("skipped", []))
        row["failed_chains"] = len(rep.get("failed", []))
        row["failed_detail"] = rep.get("failed", [])[:4]
        row["skipped_detail"] = rep.get("skipped", [])[:4]
    except Exception:
        row["status"] = "error"
        row["error"] = traceback.format_exc()[-800:]
    finally:
        try:
            if nd is not None:
                nd.Close(False)
        except Exception:
            pass
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

    try:
        row["source_untouched"] = (os.path.getmtime(path) == mtime_before)
    except Exception:
        row["source_untouched"] = None
    row["seconds"] = round(time.time() - t0, 1)
    rows.append(row)

if dialog_hooked:
    try:
        uiapp.DialogBoxShowing -= _on_dialog
    except Exception:
        pass

done = [r for r in rows if r["status"] == "done"]
OUT = {
    "mode": ("APPLY + SAVE" if SAVE else "DRY RUN - nothing written"),
    "envs": len(FILES),
    "done": len(done),
    "errors": len([r for r in rows if r["status"] == "error"]),
    "any_source_touched": [r["file"] for r in rows if r.get("source_untouched") is False],
    "totals": {
        "walls_before": sum(r.get("walls_before") or 0 for r in done),
        "walls_after": sum(r.get("walls_after") or 0 for r in done),
        "chains_found": sum(r.get("chains_found") or 0 for r in done),
        "chains_merged": sum(r.get("merged") or 0 for r in done),
        "chains_remaining": sum(r.get("chains_remaining") or 0 for r in done),
        "chains_skipped": sum(r.get("skipped_chains") or 0 for r in done),
        "chains_failed": sum(r.get("failed_chains") or 0 for r in done),
    },
    "rows": rows,
}
