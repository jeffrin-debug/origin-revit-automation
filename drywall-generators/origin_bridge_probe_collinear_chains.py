# origin_bridge_probe_collinear_chains.py - READ-ONLY.
# How much of this model is ONE physical wall modelled as SEVERAL collinear Revit wall elements?
# Each such chain currently gets one independent board layout per element, so a continuous run is
# panelised as fragments (and a short stub element can only ever produce a stub panel).
#
# NOTE: the bridge's exec() context does not support the XYZ '-' operator ("unsupported operand
# type(s) for -: 'XYZ' and 'XYZ'"), so all vector maths here is done on components.
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

ANGLE_TOL_DEG = 1.0      # direction match
OFFSET_TOL_FT = 0.02     # lateral offset between the two axes (must be the same line)
GAP_TOL_FT = 0.05        # end-to-end touching

walls = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        wt = w.WallType
        if wt is not None and wt.Kind == WallKind.Curtain:
            continue
    except Exception:
        pass
    try:
        c = w.Location.Curve
    except Exception:
        continue
    if not isinstance(c, Line):
        continue
    p0 = c.GetEndPoint(0)
    p1 = c.GetEndPoint(1)
    dx, dy = p1.X - p0.X, p1.Y - p0.Y
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-6:
        continue
    try:
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
    except Exception:
        mk = None
    try:
        nm = w.Name
    except Exception:
        nm = None
    try:
        width = w.WallType.Width
    except Exception:
        width = None
    walls.append({
        "eid": w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value,
        "mark": mk, "name": nm, "width": width,
        "p0": (p0.X, p0.Y), "p1": (p1.X, p1.Y),
        "d": (dx / L, dy / L), "len": L, "z": p0.Z,
    })


def same_line(a, b):
    ax, ay = a["d"]
    bx, by = b["d"]
    dot = abs(ax * bx + ay * by)
    if dot < math.cos(math.radians(ANGLE_TOL_DEG)):
        return False
    if abs(a["z"] - b["z"]) > OFFSET_TOL_FT:
        return False
    # lateral distance of b.p0 from a's infinite axis
    vx, vy = b["p0"][0] - a["p0"][0], b["p0"][1] - a["p0"][1]
    perp = abs(vx * (-ay) + vy * ax)
    return perp <= OFFSET_TOL_FT


def touching(a, b):
    for pa in (a["p0"], a["p1"]):
        for pb in (b["p0"], b["p1"]):
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= GAP_TOL_FT:
                return True
    return False


def same_build(a, b):
    if a["name"] != b["name"]:
        return False
    if a["width"] is None or b["width"] is None:
        return False
    return abs(a["width"] - b["width"]) < 1e-4


# union-find over "collinear + touching + same type"
parent = dict((w["eid"], w["eid"]) for w in walls)


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra


for i in range(len(walls)):
    for j in range(i + 1, len(walls)):
        a, b = walls[i], walls[j]
        if not same_build(a, b):
            continue
        if not same_line(a, b):
            continue
        if not touching(a, b):
            continue
        union(a["eid"], b["eid"])

groups = {}
by_eid = dict((w["eid"], w) for w in walls)
for w in walls:
    groups.setdefault(find(w["eid"]), []).append(w)

chains = []
for root, members in groups.items():
    if len(members) < 2:
        continue
    total = sum(m["len"] for m in members)
    members_sorted = sorted(members, key=lambda m: (m["p0"][0], m["p0"][1]))
    chains.append({
        "walls": len(members),
        "total_len_ft": round(total, 2),
        "type": members_sorted[0]["name"],
        "marks": [m["mark"] for m in members_sorted],
        "lengths_ft": [round(m["len"], 3) for m in members_sorted],
        "shortest_ft": round(min(m["len"] for m in members), 3),
        "whole_sheets_if_merged": int(total // 8.0),
    })

chains.sort(key=lambda c: -c["walls"])
stubs = [c for c in chains if c["shortest_ft"] < 2.0]

OUT = {
    "doc": doc.Title,
    "straight_non_curtain_walls": len(walls),
    "collinear_chains": len(chains),
    "walls_inside_a_chain": sum(c["walls"] for c in chains),
    "chains_containing_a_stub_under_2ft": len(stubs),
    "chains": chains[:30],
}
