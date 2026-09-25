# origin_bridge_probe_merge_feasibility.py - READ-ONLY.
# Feasibility study for a PRE-SCRIPT that normalises the Revit geometry (merging collinear wall
# fragments into single walls) BEFORE the drywall generators run.
#
# Answers three things per collinear chain:
#   1. PRIZE   - how much generated framing/drywall the fragmentation is currently costing.
#   2. BLOCKER - is anything hosted on a fragment that would be destroyed by deleting it
#                (doors/windows), and do the fragments actually share type/height/base so they
#                CAN legally become one wall?
#   3. PLAN    - which fragment should survive and what its merged curve would be.
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

ANGLE_TOL_DEG = 1.0
OFFSET_TOL_FT = 0.02
GAP_TOL_FT = 0.05
APP_ID = "ORIGIN_ASSEMBLY_V4"


def pval(el, bip):
    try:
        p = el.get_Parameter(bip)
        return p.AsDouble() if p else None
    except Exception:
        return None


def pint(el, bip):
    try:
        p = el.get_Parameter(bip)
        return p.AsInteger() if p else None
    except Exception:
        return None


walls = []
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
    if L < 1e-6:
        continue
    eid = w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value
    try:
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
    except Exception:
        mk = None
    walls.append({
        "eid": eid, "mark": mk, "name": w.Name,
        "width": (w.WallType.Width if w.WallType else None),
        "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y), "d": (dx / L, dy / L), "len": L, "z": p0.Z,
        "height": pval(w, BuiltInParameter.WALL_USER_HEIGHT_PARAM),
        "base_off": pval(w, BuiltInParameter.WALL_BASE_OFFSET),
        "base_lvl": (w.LevelId.IntegerValue if hasattr(w.LevelId, "IntegerValue") else w.LevelId.Value),
        "key_ref": pint(w, BuiltInParameter.WALL_KEY_REF_PARAM),
        "room_bounding": pint(w, BuiltInParameter.WALL_ATTR_ROOM_BOUNDING),
        "hosted": [],
    })

by_eid = dict((w["eid"], w) for w in walls)

# what is hosted on each wall (deleting a host destroys these)
for fi in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
    try:
        h = fi.Host
        if h is None:
            continue
        hid = h.Id.IntegerValue if hasattr(h.Id, "IntegerValue") else h.Id.Value
    except Exception:
        continue
    if hid not in by_eid:
        continue
    try:
        cat = fi.Category.Name if fi.Category else "?"
    except Exception:
        cat = "?"
    by_eid[hid]["hosted"].append(cat)

# generated ORIGIN elements per host wall
gen = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
    except Exception:
        continue
    if not c.startswith(APP_ID + " |"):
        continue
    host = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL=W"):
            try:
                host = int(tok[len("WALL=W"):])
            except Exception:
                pass
    if host is None:
        continue
    g = gen.setdefault(host, {"boards": 0, "framing": 0})
    if "| DRYWALL" in c:
        g["boards"] += 1
    else:
        g["framing"] += 1


def same_line(a, b):
    ax, ay = a["d"]; bx, by = b["d"]
    if abs(ax * bx + ay * by) < math.cos(math.radians(ANGLE_TOL_DEG)):
        return False
    if abs(a["z"] - b["z"]) > OFFSET_TOL_FT:
        return False
    vx, vy = b["p0"][0] - a["p0"][0], b["p0"][1] - a["p0"][1]
    return abs(vx * (-ay) + vy * ax) <= OFFSET_TOL_FT


def touching(a, b):
    for pa in (a["p0"], a["p1"]):
        for pb in (b["p0"], b["p1"]):
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= GAP_TOL_FT:
                return True
    return False


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

chains = []
tot_saved_framing = 0
tot_saved_boards = 0
blocked = 0
for root, mem in groups.items():
    if len(mem) < 2:
        continue
    d = mem[0]["d"]
    mem_sorted = sorted(mem, key=lambda m: m["p0"][0] * d[0] + m["p0"][1] * d[1])
    # extent along the shared axis
    ts = []
    o = mem_sorted[0]["p0"]
    for m in mem_sorted:
        for p in (m["p0"], m["p1"]):
            ts.append((p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1])
    span = max(ts) - min(ts)

    heights = set(round(m["height"], 4) if m["height"] else None for m in mem)
    bases = set(round(m["base_off"], 4) if m["base_off"] is not None else None for m in mem)
    levels = set(m["base_lvl"] for m in mem)
    keyrefs = set(m["key_ref"] for m in mem)
    rb = set(m["room_bounding"] for m in mem)

    survivor = max(mem, key=lambda m: m["len"])
    hosted_on_doomed = []
    for m in mem:
        if m["eid"] == survivor["eid"] and m["hosted"]:
            continue
        if m["hosted"]:
            hosted_on_doomed.append({"mark": m["mark"], "len_ft": round(m["len"], 3),
                                     "hosted": m["hosted"]})

    fr = sum(gen.get(m["eid"], {}).get("framing", 0) for m in mem)
    bd = sum(gen.get(m["eid"], {}).get("boards", 0) for m in mem)
    # a merged wall would need roughly what a single wall of this span needs
    est_fr_after = 2 + int(span / (16.0 / 12.0)) + 1      # 2 tracks + studs @16in OC
    saved_fr = max(0, fr - est_fr_after)
    tot_saved_framing += saved_fr

    issues = []
    if len(heights) > 1:
        issues.append("mixed heights %s" % sorted(str(h) for h in heights))
    if len(bases) > 1:
        issues.append("mixed base offsets %s" % sorted(str(b) for b in bases))
    if len(levels) > 1:
        issues.append("mixed base levels")
    if len(keyrefs) > 1:
        issues.append("mixed location-line refs %s" % sorted(str(k) for k in keyrefs))
    if len(rb) > 1:
        issues.append("mixed room-bounding")
    if hosted_on_doomed:
        issues.append("hosted elements on fragments that would be deleted")
    if issues:
        blocked += 1

    chains.append({
        "marks": [m["mark"] for m in mem_sorted],
        "pieces": len(mem),
        "span_ft": round(span, 3),
        "lengths_ft": [round(m["len"], 3) for m in mem_sorted],
        "survivor_mark": survivor["mark"],
        "survivor_len_ft": round(survivor["len"], 3),
        "framing_now": fr, "framing_est_after": est_fr_after, "framing_saved": saved_fr,
        "boards_now": bd,
        "hosted_on_doomed": hosted_on_doomed,
        "issues": issues,
    })

chains.sort(key=lambda c: -c["framing_saved"])

OUT = {
    "doc": doc.Title,
    "chains": len(chains),
    "walls_in_chains": sum(c["pieces"] for c in chains),
    "chains_with_issues": blocked,
    "chains_clean_to_merge": len(chains) - blocked,
    "total_framing_now_in_chains": sum(c["framing_now"] for c in chains),
    "est_framing_saved": tot_saved_framing,
    "total_boards_now_in_chains": sum(c["boards_now"] for c in chains),
    "detail": chains,
}
