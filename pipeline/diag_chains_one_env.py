# diag_chains_one_env.py - READ-ONLY.
# Dump every collinear chain in one env with the raw geometry behind it, so a human can judge
# whether the detector is right rather than trusting its count. Background open, closed unsaved.
import clr
import json
import math
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

ROOT = r"C:\Users\Origoncad\origin_pipeline"
cfg = json.load(open(os.path.join(ROOT, "_diag_config.json")))
PATH = cfg["file"]

ANGLE_TOL_DEG = 1.0
OFFSET_TOL_FT = 0.02
GAP_TOL_FT = 0.05

app = DocumentManager.Instance.CurrentUIApplication.Application


def read_walls(doc):
    out = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            curtain = (w.WallType is not None and w.WallType.Kind == WallKind.Curtain)
        except Exception:
            curtain = False
        try:
            c = w.Location.Curve
        except Exception:
            continue
        if curtain or not isinstance(c, Line):
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        dx, dy = p1.X - p0.X, p1.Y - p0.Y
        L = math.sqrt(dx * dx + dy * dy)
        if L < 1e-9:
            continue
        out.append({
            "eid": w.Id.IntegerValue if hasattr(w.Id, "IntegerValue") else w.Id.Value,
            "name": w.Name,
            "width_in": round(w.WallType.Width * 12.0, 3) if w.WallType else None,
            "p0": (round(p0.X, 3), round(p0.Y, 3)), "p1": (round(p1.X, 3), round(p1.Y, 3)),
            "len": L, "z": p0.Z,
            "d": (dx / L, dy / L),
        })
    return out


def same_line(a, b):
    ax, ay = a["d"]
    bx, by = b["d"]
    if abs(ax * bx + ay * by) < math.cos(math.radians(ANGLE_TOL_DEG)):
        return False
    if abs(a["z"] - b["z"]) > OFFSET_TOL_FT:
        return False
    vx, vy = b["p0"][0] - a["p0"][0], b["p0"][1] - a["p0"][1]
    return abs(vx * (-ay) + vy * ax) <= OFFSET_TOL_FT


def gap(a, b):
    best = None
    for pa in (a["p0"], a["p1"]):
        for pb in (b["p0"], b["p1"]):
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if best is None or d < best:
                best = d
    return best


nd = None
try:
    TransactionManager.Instance.ForceCloseTransaction()
    oo = OpenOptions()
    try:
        oo.Audit = False
    except Exception:
        pass
    nd = app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(PATH), oo)
    walls = read_walls(nd)

    parent = dict((w["eid"], w["eid"]) for w in walls)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = []
    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            if a["name"] != b["name"]:
                continue
            if a["width_in"] is None or b["width_in"] is None:
                continue
            if abs(a["width_in"] - b["width_in"]) > 1e-3:
                continue
            if not same_line(a, b):
                continue
            g = gap(a, b)
            if g > GAP_TOL_FT:
                continue
            pairs.append({"a": a["eid"], "b": b["eid"], "gap_in": round(g * 12.0, 4),
                          "type": a["name"]})
            ra, rb = find(a["eid"]), find(b["eid"])
            if ra != rb:
                parent[rb] = ra

    groups = {}
    for w in walls:
        groups.setdefault(find(w["eid"]), []).append(w)

    chains = []
    for mem in groups.values():
        if len(mem) < 2:
            continue
        d = mem[0]["d"]
        o = mem[0]["p0"]
        mem = sorted(mem, key=lambda m: (m["p0"][0] - o[0]) * d[0] + (m["p0"][1] - o[1]) * d[1])
        ts = []
        for m in mem:
            for p in (m["p0"], m["p1"]):
                ts.append((p[0] - o[0]) * d[0] + (p[1] - o[1]) * d[1])
        chains.append({
            "type": mem[0]["name"],
            "width_in": mem[0]["width_in"],
            "direction": [round(v, 4) for v in mem[0]["d"]],
            "span_ft": round(max(ts) - min(ts), 3),
            "sum_of_pieces_ft": round(sum(m["len"] for m in mem), 3),
            "pieces": [{"eid": m["eid"], "len_ft": round(m["len"], 3),
                        "from": list(m["p0"]), "to": list(m["p1"])} for m in mem],
        })

    OUT = {
        "file": os.path.basename(PATH),
        "straight_walls": len(walls),
        "chains": len(chains),
        "touching_pairs": pairs,
        "detail": chains,
        "all_walls": [{"eid": w["eid"], "type": w["name"], "len_ft": round(w["len"], 3),
                       "from": list(w["p0"]), "to": list(w["p1"])} for w in walls],
    }
except Exception:
    import traceback
    OUT = {"error": traceback.format_exc()[-1200:]}
finally:
    try:
        if nd is not None:
            nd.Close(False)
    except Exception:
        pass
