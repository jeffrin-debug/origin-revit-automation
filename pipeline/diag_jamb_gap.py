# diag_jamb_gap.py - READ-ONLY.
# Measure, along one wall's own axis, exactly where the jamb framing sits and where the drywall
# boards actually stop, at the Z band of the bare members. Replaces arithmetic-from-constants
# with numbers off the real model.
import clr
import json
import math
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

doc = DocumentManager.Instance.CurrentDBDocument

cfg = json.load(open(os.path.join(_paths["PIPELINE_ROOT"], "_jamb_config.json")))
WALL_EID = int(cfg["wall"])
Z_LO = float(cfg.get("z_lo", 0.0))
Z_HI = float(cfg.get("z_hi", 10.0))

APP_ID = "ORIGIN_ASSEMBLY_V4"
IN = 12.0

w = doc.GetElement(ElementId(WALL_EID))
crv = w.Location.Curve
p0 = crv.GetEndPoint(0)
p1 = crv.GetEndPoint(1)
L = crv.Length
ux = (p1.X - p0.X) / L
uy = (p1.Y - p0.Y) / L
o = w.Orientation


def along(px, py):
    return (px - p0.X) * ux + (py - p0.Y) * uy


def across(px, py):
    return (px - p0.X) * o.X + (py - p0.Y) * o.Y


def span_of(e):
    bb = e.get_BoundingBox(None)
    if bb is None:
        return None
    ts, ns = [], []
    for (x, y) in ((bb.Min.X, bb.Min.Y), (bb.Max.X, bb.Min.Y),
                   (bb.Max.X, bb.Max.Y), (bb.Min.X, bb.Max.Y)):
        ts.append(along(x, y))
        ns.append(across(x, y))
    return (min(ts), max(ts), min(ns), max(ns), bb.Min.Z, bb.Max.Z)


framing = []
boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
    except Exception:
        continue
    if not c.startswith(APP_ID + " |"):
        continue
    if ("WALL=W%d " % WALL_EID) not in c and ("WALL=W%d|" % WALL_EID) not in c:
        if ("WALL=W%d" % WALL_EID) not in c:
            continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString()
    except Exception:
        mk = None
    s = span_of(ds)
    if s is None:
        continue
    if s[5] < Z_LO + 0.05 or s[4] > Z_HI - 0.05:
        continue
    kind = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok in ("STUD", "TRACK", "HEADER", "SILL", "KINGSTUD", "JACK", "CRIPPLE", "DRYWALL"):
            kind = tok
    face = "B" if "FACE_B" in c else ("A" if "FACE_A" in c else "-")
    rec = {"mark": mk, "kind": kind, "face": face,
           "along_in": [round(s[0] * IN, 2), round(s[1] * IN, 2)],
           "across_in": [round(s[2] * IN, 2), round(s[3] * IN, 2)],
           "z_ft": [round(s[4], 2), round(s[5], 2)]}
    if kind == "DRYWALL":
        boards.append(rec)
    else:
        framing.append(rec)

framing.sort(key=lambda r: r["along_in"][0])
boards.sort(key=lambda r: (r["face"], r["along_in"][0]))

# the wall's real hosted inserts, for the true opening position
inserts = []
try:
    for eid in w.FindInserts(True, False, True, True):
        e = doc.GetElement(eid)
        if e is None:
            continue
        bb = e.get_BoundingBox(None)
        if bb is None:
            continue
        s = span_of(e)
        try:
            cat = e.Category.Name
        except Exception:
            cat = "?"
        inserts.append({"cat": cat,
                        "along_in": [round(s[0] * IN, 2), round(s[1] * IN, 2)],
                        "z_ft": [round(s[4], 2), round(s[5], 2)]})
except Exception:
    pass

OUT = {
    "wall": WALL_EID, "type": w.Name,
    "width_in": round(w.WallType.Width * IN, 2),
    "length_ft": round(L, 3),
    "orientation": [round(o.X, 3), round(o.Y, 3)],
    "z_window": [Z_LO, Z_HI],
    "inserts": inserts,
    "framing": framing,
    "boards": boards,
}
