# conformance_audit.py
# ============================================================
# STAGE 0, PHASE A - "Look, change nothing."
#
# Opens each env as a BACKGROUND document, runs every panel-readiness detector, closes WITHOUT
# saving, and asserts the source .rvt mtime is unchanged. No Transaction is ever opened, so there
# is nothing that could be committed even by accident.
#
# Reads  _audit_config.json  {"files": [...]}
# Writes _reports\conformance\<env>.json   per env
#        _reports\conformance\_summary.json  the corpus frequency table
#
# Detector ids follow the conformance model:
#   W1 collinear fragments   W2 stub walls      W3 curved walls
#   W4 chain attr mismatch   W5 thin walls      R1 rooms placed
#   C1 ceilings vs walls     H1 hosted on chain G1 degenerate / duplicate
#
# NOTE: the bridge's exec() context does not support the XYZ '-' operator ("unsupported operand
# type(s) for -: 'XYZ' and 'XYZ'"), so every vector calculation here is done on components.
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


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

ROOT = _paths["PIPELINE_ROOT"]
CONFIG_PATH = os.path.join(ROOT, "_audit_config.json")
OUT_DIR = os.path.join(ROOT, "_reports", "conformance")

# --- thresholds (this pass exists to calibrate these; they are first guesses) ---------------
COLLINEAR_ANGLE_TOL_DEG = 1.0
COLLINEAR_OFFSET_TOL_FT = 0.02
COLLINEAR_GAP_TOL_FT = 0.05
STUB_MAX_FT = 0.5
DRYWALL_PER_FACE_FT = 0.5 / 12.0
MIN_STUD_DEPTH_FT = 1.25 / 12.0
MIN_ROOM_AREA_SF = 1.0
DUP_WALL_TOL_FT = 0.05

cfg = json.load(open(CONFIG_PATH))
FILES = cfg.get("files") or []

if not os.path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

# --- dialog suppression (same reason as pipeline_run.py: an unanswered task dialog freezes the
# batch at zero CPU with nobody at the keyboard) ---------------------------------------------
dialogs_seen = []


def _on_dialog(sender, args):
    try:
        dialogs_seen.append(str(args.DialogId))
    except Exception:
        dialogs_seen.append("<unknown dialog>")
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
# detectors
# ============================================================

def read_walls(doc):
    """Straight, non-curtain walls with the geometry the detectors need. Curved and curtain
    walls are returned separately - they are findings in their own right, not noise."""
    straight, curved, curtain = [], [], []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        eid = w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
        except Exception:
            mk = None
        try:
            is_curtain = (w.WallType is not None and w.WallType.Kind == WallKind.Curtain)
        except Exception:
            is_curtain = False
        if is_curtain:
            curtain.append({"eid": eid, "mark": mk})
            continue
        try:
            c = w.Location.Curve
        except Exception:
            continue
        if not isinstance(c, Line):
            try:
                ln = c.Length
            except Exception:
                ln = None
            curved.append({"eid": eid, "mark": mk, "len_ft": (round(ln, 3) if ln else None)})
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        dx, dy = p1.X - p0.X, p1.Y - p0.Y
        L = math.sqrt(dx * dx + dy * dy)
        if L < 1e-9:
            straight.append({"eid": eid, "mark": mk, "len": 0.0, "degenerate": True,
                             "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y), "d": (1.0, 0.0),
                             "z": p0.Z, "name": None, "width": None, "height": None,
                             "base_off": None, "base_lvl": None, "key_ref": None, "rb": None})
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
            nm = w.Name
        except Exception:
            nm = None
        try:
            width = w.WallType.Width
        except Exception:
            width = None
        try:
            lvl = w.LevelId.IntegerValue if hasattr(w.LevelId, "IntegerValue") else w.LevelId.Value
        except Exception:
            lvl = None
        straight.append({
            "eid": eid, "mark": mk, "name": nm, "width": width,
            "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y), "d": (dx / L, dy / L),
            "len": L, "z": p0.Z, "degenerate": False,
            "height": pd(BuiltInParameter.WALL_USER_HEIGHT_PARAM),
            "base_off": pd(BuiltInParameter.WALL_BASE_OFFSET),
            "base_lvl": lvl,
            "key_ref": pi(BuiltInParameter.WALL_KEY_REF_PARAM),
            "rb": pi(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING),
        })
    return straight, curved, curtain


def same_line(a, b):
    ax, ay = a["d"]
    bx, by = b["d"]
    if abs(ax * bx + ay * by) < math.cos(math.radians(COLLINEAR_ANGLE_TOL_DEG)):
        return False
    if abs(a["z"] - b["z"]) > COLLINEAR_OFFSET_TOL_FT:
        return False
    vx, vy = b["p0"][0] - a["p0"][0], b["p0"][1] - a["p0"][1]
    return abs(vx * (-ay) + vy * ax) <= COLLINEAR_OFFSET_TOL_FT


def touching(a, b):
    for pa in (a["p0"], a["p1"]):
        for pb in (b["p0"], b["p1"]):
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= COLLINEAR_GAP_TOL_FT:
                return True
    return False


def find_chains(straight):
    live = [w for w in straight if not w["degenerate"]]
    parent = dict((w["eid"], w["eid"]) for w in live)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            a, b = live[i], live[j]
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
    for w in live:
        groups.setdefault(find(w["eid"]), []).append(w)
    return [m for m in groups.values() if len(m) > 1]


def audit_document(doc, path):
    rep = {"file": os.path.basename(path), "source": path}
    try:
        rep["title"] = doc.Title
    except Exception:
        pass

    straight, curved, curtain = read_walls(doc)
    rep["inventory"] = {
        "walls_straight": len(straight),
        "walls_curved": len(curved),
        "walls_curtain": len(curtain),
    }
    for nm, bic in (("ceilings", BuiltInCategory.OST_Ceilings),
                    ("floors", BuiltInCategory.OST_Floors),
                    ("doors", BuiltInCategory.OST_Doors),
                    ("windows", BuiltInCategory.OST_Windows),
                    ("columns", BuiltInCategory.OST_Columns),
                    ("struct_columns", BuiltInCategory.OST_StructuralColumns),
                    ("beams", BuiltInCategory.OST_StructuralFraming),
                    ("levels", BuiltInCategory.OST_Levels)):
        try:
            rep["inventory"][nm] = len(list(
                FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()))
        except Exception:
            rep["inventory"][nm] = None

    findings = {}

    # ---- W1 / W4 / H1 : collinear fragment chains -----------------------------------------
    chains = find_chains(straight)
    hosted_by_wall = {}
    for fi in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
        try:
            h = fi.Host
            if h is None:
                continue
            hid = h.Id.IntegerValue if hasattr(h.Id, "IntegerValue") else h.Id.Value
        except Exception:
            continue
        try:
            cat = fi.Category.Name if fi.Category else "?"
        except Exception:
            cat = "?"
        hosted_by_wall.setdefault(hid, []).append(cat)

    chain_rows = []
    w4_bad = 0
    h1_bad = 0
    for mem in chains:
        d = mem[0]["d"]
        o = mem[0]["p0"]
        ts = []
        for m in mem:
            for p in (m["p0"], m["p1"]):
                ts.append((p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1])
        span = max(ts) - min(ts)
        attrs_ok = (
            len(set(round(m["height"], 4) if m["height"] is not None else None for m in mem)) == 1
            and len(set(round(m["base_off"], 4) if m["base_off"] is not None else None for m in mem)) == 1
            and len(set(m["base_lvl"] for m in mem)) == 1
            and len(set(m["key_ref"] for m in mem)) == 1
            and len(set(m["rb"] for m in mem)) == 1)
        if not attrs_ok:
            w4_bad += 1
        hosts = [m for m in mem if hosted_by_wall.get(m["eid"])]
        if len(hosts) > 1:
            h1_bad += 1
        chain_rows.append({
            "marks": [m["mark"] for m in mem],
            "pieces": len(mem),
            "span_ft": round(span, 3),
            "lengths_ft": sorted(round(m["len"], 3) for m in mem),
            "shortest_ft": round(min(m["len"] for m in mem), 3),
            "attrs_uniform": attrs_ok,
            "host_bearing_pieces": len(hosts),
        })
    chain_rows.sort(key=lambda r: -r["pieces"])
    findings["W1_collinear_chains"] = {
        "chains": len(chain_rows),
        "walls_involved": sum(r["pieces"] for r in chain_rows),
        "redundant_elements": sum(r["pieces"] - 1 for r in chain_rows),
        "worst": chain_rows[:10],
    }
    findings["W4_chain_attr_mismatch"] = {"chains": w4_bad}
    findings["H1_multi_host_chain"] = {"chains": h1_bad}

    # ---- W2 : stub walls -------------------------------------------------------------------
    in_chain = set()
    for mem in chains:
        for m in mem:
            in_chain.add(m["eid"])
    stubs = [w for w in straight if not w["degenerate"] and w["len"] < STUB_MAX_FT]
    findings["W2_stub_walls"] = {
        "count": len(stubs),
        "inside_a_chain": len([w for w in stubs if w["eid"] in in_chain]),
        "isolated": len([w for w in stubs if w["eid"] not in in_chain]),
        "shortest_ft": (round(min(w["len"] for w in stubs), 4) if stubs else None),
    }

    # ---- W3 : curved walls -----------------------------------------------------------------
    findings["W3_curved_walls"] = {"count": len(curved), "marks": [c["mark"] for c in curved][:10]}

    # ---- W5 : thin walls -------------------------------------------------------------------
    thin = []
    for w in straight:
        if w["width"] is None or w["degenerate"]:
            continue
        stud = w["width"] - 2.0 * DRYWALL_PER_FACE_FT
        if stud < MIN_STUD_DEPTH_FT:
            thin.append({"mark": w["mark"], "width_in": round(w["width"] * 12.0, 3),
                         "stud_in": round(stud * 12.0, 3)})
    findings["W5_thin_walls"] = {"count": len(thin), "worst": thin[:8]}

    # ---- G1 : degenerate + duplicate --------------------------------------------------------
    degen = [w for w in straight if w["degenerate"]]
    dups = 0
    live = [w for w in straight if not w["degenerate"]]
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            a, b = live[i], live[j]
            if abs(a["len"] - b["len"]) > DUP_WALL_TOL_FT:
                continue
            if (math.hypot(a["p0"][0] - b["p0"][0], a["p0"][1] - b["p0"][1]) < DUP_WALL_TOL_FT
                    and math.hypot(a["p1"][0] - b["p1"][0], a["p1"][1] - b["p1"][1]) < DUP_WALL_TOL_FT):
                dups += 1
    findings["G1_degenerate_duplicate"] = {"degenerate": len(degen), "duplicate_pairs": dups}

    # ---- R1 : rooms ------------------------------------------------------------------------
    placed = 0
    unplaced = 0
    try:
        for r in FilteredElementCollector(doc).OfCategory(
                BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
            try:
                a = r.Area
            except Exception:
                a = 0
            if a and a >= MIN_ROOM_AREA_SF:
                placed += 1
            else:
                unplaced += 1
    except Exception:
        placed = unplaced = None
    findings["R1_rooms"] = {"placed": placed, "unplaced_or_zero_area": unplaced}

    # ---- C1 : ceilings vs walls -------------------------------------------------------------
    c_elevs = []
    try:
        for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
            bb = c.get_BoundingBox(None)
            if bb is not None:
                c_elevs.append(round(bb.Min.Z, 3))
    except Exception:
        pass
    wall_tops = [round(w["z"] + w["height"], 3) for w in straight
                 if w["height"] and not w["degenerate"]]
    findings["C1_ceilings"] = {
        "count": len(c_elevs),
        "distinct_elevations_ft": sorted(set(c_elevs))[:8],
        "distinct_wall_tops_ft": sorted(set(wall_tops))[:8],
        "walls_taller_than_lowest_ceiling": (
            len([t for t in wall_tops if c_elevs and t > min(c_elevs) + 0.02])
            if c_elevs else 0),
    }

    rep["findings"] = findings

    blockers = []
    if findings["W3_curved_walls"]["count"] > 0:
        blockers.append("W3 curved walls are silently skipped by the wall generator")
    if placed == 0:
        blockers.append("R1 no placed Rooms - ceiling stage falls back to zone splitting")
    if findings["H1_multi_host_chain"]["chains"] > 0:
        blockers.append("H1 a chain has two host-bearing fragments - not safely mergeable")
    rep["blockers"] = blockers
    rep["mergeable_chains"] = len([r for r in chain_rows
                                   if r["attrs_uniform"] and r["host_bearing_pieces"] <= 1])
    return rep


# ============================================================
# batch
# ============================================================

rows = []
for path in FILES:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    t0 = time.time()
    row = {"file": name, "status": "pending"}

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
        mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(mp, oo)
        rep = audit_document(nd, path)
        rep["seconds"] = round(time.time() - t0, 1)
        with open(os.path.join(OUT_DIR, stem + ".json"), "w") as f:
            json.dump(rep, f, indent=2)
        row["status"] = "audited"
        row["walls"] = rep["inventory"]["walls_straight"]
        row["chains"] = rep["findings"]["W1_collinear_chains"]["chains"]
        row["redundant"] = rep["findings"]["W1_collinear_chains"]["redundant_elements"]
        row["stubs"] = rep["findings"]["W2_stub_walls"]["count"]
        row["curved"] = rep["findings"]["W3_curved_walls"]["count"]
        row["thin"] = rep["findings"]["W5_thin_walls"]["count"]
        row["rooms"] = rep["findings"]["R1_rooms"]["placed"]
        row["ceilings"] = rep["findings"]["C1_ceilings"]["count"]
        row["blockers"] = rep["blockers"]
        row["mergeable_chains"] = rep["mergeable_chains"]
    except Exception:
        row["status"] = "error"
        row["error"] = traceback.format_exc()[-900:]
    finally:
        try:
            if nd is not None:
                nd.Close(False)
        except Exception:
            row["close_error"] = traceback.format_exc()[-300:]
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

    # the source must be byte-identical: this pass opens no Transaction at all
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

ok = [r for r in rows if r["status"] == "audited"]
summary = {
    "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    "envs_requested": len(FILES),
    "envs_audited": len(ok),
    "envs_failed": len([r for r in rows if r["status"] == "error"]),
    "envs_skipped": len([r for r in rows if r["status"].startswith("skipped")]),
    "any_source_touched": [r["file"] for r in rows if r.get("source_untouched") is False],
    "dialogs_answered": len(dialogs_seen),
    "corpus": {
        "envs_with_collinear_chains": len([r for r in ok if r["chains"] > 0]),
        "envs_with_zero_rooms": len([r for r in ok if r["rooms"] == 0]),
        "envs_with_curved_walls": len([r for r in ok if r["curved"] > 0]),
        "envs_with_thin_walls": len([r for r in ok if r["thin"] > 0]),
        "envs_with_no_ceilings": len([r for r in ok if r["ceilings"] == 0]),
        "total_walls": sum(r["walls"] for r in ok),
        "total_redundant_wall_elements": sum(r["redundant"] for r in ok),
        "total_chains": sum(r["chains"] for r in ok),
        "total_mergeable_chains": sum(r["mergeable_chains"] for r in ok),
    },
    "rows": rows,
}
with open(os.path.join(OUT_DIR, "_summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

OUT = summary
