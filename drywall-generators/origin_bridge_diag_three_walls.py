# origin_bridge_diag_three_walls.py - READ-ONLY.
# Are walls 020 / 068 / 069 one continuous run split into three Revit elements, and how does each
# one's own FACE_B board layout decompose along it?
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

EIDS = [385084, 412970, 413352]
APP_ID = "ORIGIN_ASSEMBLY_V4"

walls = []
for eid in EIDS:
    w = doc.GetElement(ElementId(eid))
    if w is None:
        continue
    rec = {"eid": eid}
    try:
        rec["mark"] = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
    except Exception:
        rec["mark"] = None
    try:
        rec["name"] = w.Name
        rec["width_in"] = round(w.WallType.Width * 12.0, 3)
    except Exception:
        pass
    try:
        c = w.Location.Curve
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        rec["start"] = [round(p0.X, 3), round(p0.Y, 3), round(p0.Z, 3)]
        rec["end"] = [round(p1.X, 3), round(p1.Y, 3), round(p1.Z, 3)]
        rec["length_ft"] = round(c.Length, 3)
        d = (p1 - p0).Normalize()
        rec["dir"] = [round(d.X, 4), round(d.Y, 4)]
        rec["angle_deg"] = round(math.degrees(math.atan2(d.Y, d.X)), 2)
    except Exception as ex:
        rec["curve_err"] = str(ex)
    try:
        o = w.Orientation
        rec["orientation"] = [round(o.X, 3), round(o.Y, 3)]
    except Exception:
        pass
    # joined neighbours at each end
    for end in (0, 1):
        try:
            arr = w.Location.get_ElementsAtJoin(end)
            rec["joined_at_%d" % end] = [
                (e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value)
                for e in arr if e.Id != w.Id]
        except Exception:
            rec["joined_at_%d" % end] = "err"
    walls.append(rec)

# endpoint proximity between the three
gaps = []
for i in range(len(walls)):
    for j in range(len(walls)):
        if i >= j:
            continue
        a, b = walls[i], walls[j]
        if "start" not in a or "start" not in b:
            continue
        for an, ap in (("start", a["start"]), ("end", a["end"])):
            for bn, bp in (("start", b["start"]), ("end", b["end"])):
                d = math.sqrt((ap[0] - bp[0]) ** 2 + (ap[1] - bp[1]) ** 2)
                if d < 1.0:
                    gaps.append({"pair": "%s.%s <-> %s.%s" % (a["mark"], an, b["mark"], bn),
                                 "distance_in": round(d * 12.0, 3)})

# every FACE_B board on these walls, positioned along its OWN wall
boards = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
    except Exception:
        continue
    if not c.startswith(APP_ID + " |") or "| DRYWALL" not in c:
        continue
    host = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL=W"):
            host = int(tok[len("WALL=W"):])
    if host not in EIDS:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
    except Exception:
        mk = None
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    face = "B" if "FACE_B" in c else "A"
    wrec = [w for w in walls if w["eid"] == host]
    along0 = along1 = None
    if wrec and "start" in wrec[0] and "dir" in wrec[0]:
        s = wrec[0]["start"]
        d = wrec[0]["dir"]
        for (px, py) in ((bb.Min.X, bb.Min.Y), (bb.Max.X, bb.Max.Y)):
            t = (px - s[0]) * d[0] + (py - s[1]) * d[1]
            along0 = t if along0 is None else min(along0, t)
            along1 = t if along1 is None else max(along1, t)
    boards.setdefault(host, []).append({
        "mark": mk, "face": face,
        "z": [round(bb.Min.Z, 2), round(bb.Max.Z, 2)],
        "along_ft": ([round(along0, 3), round(along1, 3)]
                     if along0 is not None else "no wall axis"),
        "len_ft": (round(along1 - along0, 3) if along0 is not None else None),
    })

for h in boards:
    boards[h] = sorted(boards[h], key=lambda b: (
        b["face"], b["z"][0],
        b["along_ft"][0] if isinstance(b["along_ft"], list) else 0.0))

OUT = {"walls": walls, "endpoint_gaps_under_1ft": gaps,
       "face_B_course1_boards": dict(
           (str(h), [b for b in v if b["face"] == "B" and b["z"][0] < 0.1])
           for h, v in boards.items()),
       "all_board_counts": dict((str(h), len(v)) for h, v in boards.items())}
