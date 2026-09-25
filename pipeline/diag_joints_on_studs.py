# diag_joints_on_studs.py - read-only proof that every drywall butt joint has a stud behind it.
#
# Measures against the studs ACTUALLY IN THE MODEL, not a reconstructed 16" grid. That matters:
# the stud list legitimately includes lines the rhythm does not predict - opening jambs, and
# since 2026-09-21 partition tees - so a reconstructed grid reports false failures.
#
# For every wall: project each ORIGIN stud and board onto the wall's own axis, group boards into
# courses, and check each internal butt joint (where one board ends and the next begins) against
# the stud lines. The face's two outer edges are not joints - at a wrapped corner a sheet
# deliberately hangs past the wall end - so they are excluded.

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

TOL_IN = 0.30          # a joint this close to a stud centre counts as on it

doc = DocumentManager.Instance.CurrentDBDocument


def eidv(e):
    try:
        return e.Value
    except Exception:
        return e.IntegerValue


def mark_of(ds):
    try:
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return p.AsString() if p else None
    except Exception:
        return None


def comment_of(ds):
    try:
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return p.AsString() or ""
    except Exception:
        return ""


# Collect ORIGIN output, bucketed by the host wall recorded in its own comment token.
studs = {}      # wall eid -> [centre points]
boards = {}     # wall eid -> [(bbox, mark)]
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    m = mark_of(ds)
    if not m or not (m.startswith("ST-") or m.startswith("DP-")):
        continue
    cs = comment_of(ds)
    wid = None
    for tok in cs.split():
        if tok.startswith("WALL=W"):
            try:
                wid = int(tok[6:])
            except Exception:
                wid = None
            break
    if wid is None:
        continue
    try:
        bb = ds.get_BoundingBox(None)
    except Exception:
        continue
    if bb is None:
        continue
    if m.startswith("ST-"):
        studs.setdefault(wid, []).append(bb)
    else:
        boards.setdefault(wid, []).append((bb, m))

rows = []
tot_joints = 0
tot_off = 0

for wid, bl in boards.items():
    w = doc.GetElement(ElementId(wid))
    if w is None:
        continue
    try:
        crv = w.Location.Curve
        a, b = crv.GetEndPoint(0), crv.GetEndPoint(1)
        L = a.DistanceTo(b)
        if L < 1e-6:
            continue
        dx, dy = (b.X - a.X) / L, (b.Y - a.Y) / L
    except Exception:
        continue

    def along(bb):
        cx = (bb.Min.X + bb.Max.X) / 2.0
        cy = (bb.Min.Y + bb.Max.Y) / 2.0
        return ((cx - a.X) * dx + (cy - a.Y) * dy) * 12.0

    def span(bb):
        pts = [(bb.Min.X, bb.Min.Y), (bb.Max.X, bb.Min.Y),
               (bb.Min.X, bb.Max.Y), (bb.Max.X, bb.Max.Y)]
        ss = [((px - a.X) * dx + (py - a.Y) * dy) * 12.0 for (px, py) in pts]
        return min(ss), max(ss)

    stud_s = sorted(set(round(along(s), 2) for s in studs.get(wid, [])))
    if not stud_s:
        continue

    # Group boards into courses by their vertical band and which face they sit on.
    courses = {}
    for (bb, m) in bl:
        z0 = round(bb.Min.Z * 12.0, 1)
        # face side: signed perpendicular offset of the board centre from the wall axis
        cx = (bb.Min.X + bb.Max.X) / 2.0
        cy = (bb.Min.Y + bb.Max.Y) / 2.0
        perp = -(cx - a.X) * dy + (cy - a.Y) * dx
        side = "A" if perp >= 0 else "B"
        courses.setdefault((z0, side), []).append(span(bb))

    w_joints = 0
    w_off = 0
    examples = []
    for key, spans in courses.items():
        spans.sort()
        for i in range(len(spans) - 1):
            end_i = spans[i][1]
            start_j = spans[i + 1][0]
            if abs(end_i - start_j) > 0.6:      # not a shared joint (opening or gap between)
                continue
            j = (end_i + start_j) / 2.0
            w_joints += 1
            d = min(abs(j - s) for s in stud_s)
            if d > TOL_IN:
                w_off += 1
                if len(examples) < 3:
                    nearest = min(stud_s, key=lambda s: abs(s - j))
                    examples.append({"joint_in": round(j, 2), "nearest_stud_in": nearest,
                                     "off_by_in": round(d, 2), "band_z_in": key[0],
                                     "face": key[1]})
    tot_joints += w_joints
    tot_off += w_off
    if w_joints:
        rows.append({"wall": wid, "studs": len(stud_s), "joints": w_joints,
                     "off_stud": w_off, "examples": examples})

rows.sort(key=lambda r: -r["off_stud"])
OUT = {
    "doc": doc.Title,
    "tolerance_in": TOL_IN,
    "walls_with_boards": len(rows),
    "total_butt_joints": tot_joints,
    "joints_off_stud": tot_off,
    "pct_on_stud": (round(100.0 * (tot_joints - tot_off) / tot_joints, 2) if tot_joints else None),
    "worst_walls": rows[:10],
}
