# origin_bridge_diag_one_board.py - READ-ONLY.
# Settle whether DP-057-007B genuinely runs past a ceiling, or whether the audit is over-reporting
# it. A face-B board sits on the OUTWARD side of its wall, but its plan centroid lies within the
# wall thickness - and ceilings are commonly sketched to the wall face or centreline, so a centroid
# test can report "under a ceiling" for a board whose own side has open plenum above it.
# Tests containment at the centroid AND at points stepped out to either side.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

TARGET = "DP-057-007B"


def solids_of(e):
    out = []
    try:
        geo = e.get_Geometry(Options())
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


def make_box(x0, y0, z0, x1, y1, z1):
    try:
        pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[CurveLoop]()
        loops.Add(loop)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)
    except Exception:
        return None


ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    bb = c.get_BoundingBox(None)
    if bb is None:
        continue
    ceilings.append({"id": c.Id.IntegerValue if hasattr(c.Id, "IntegerValue") else c.Id.Value,
                     "z": bb.Min.Z,
                     "box": (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z),
                     "solids": solids_of(c)})


def hit_at(px, py):
    """Which ceilings really cover (px, py)."""
    out = []
    for cp in ceilings:
        b = cp["box"]
        if px < b[0] or px > b[3] or py < b[1] or py > b[4]:
            continue
        probe = make_box(px - 0.05, py - 0.05, cp["z"] + 0.01, px + 0.05, py + 0.05, cp["z"] + 0.05)
        if probe is None:
            continue
        for s in cp["solids"]:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                    probe, s, BooleanOperationsType.Intersect)
            except Exception:
                continue
            if inter is not None and inter.Volume > 1e-9:
                out.append({"ceiling": cp["id"], "z": round(cp["z"], 3)})
                break
    return out


info = {"target": TARGET, "found": False}

for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark != TARGET:
        continue
    info["found"] = True
    bb = ds.get_BoundingBox(None)
    info["board_bbox"] = [round(v, 3) for v in
                          (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)]
    info["board_top_ft"] = round(bb.Max.Z, 3)
    try:
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        info["comment"] = p.AsString() if p else None
    except Exception:
        pass

    cx = (bb.Min.X + bb.Max.X) / 2.0
    cy = (bb.Min.Y + bb.Max.Y) / 2.0

    # host wall + its orientation, so "outward" is meaningful
    host_eid = None
    for tok in (info.get("comment") or "").split("|"):
        tok = tok.strip()
        if tok.startswith("WALL=W"):
            try:
                host_eid = int(tok[len("WALL=W"):])
            except Exception:
                pass
    nx, ny = 1.0, 0.0
    if host_eid is not None:
        w = doc.GetElement(ElementId(host_eid))
        info["host_wall"] = host_eid
        try:
            o = w.Orientation
            nx, ny = o.X, o.Y
            info["wall_orientation"] = [round(o.X, 3), round(o.Y, 3)]
            info["wall_width_in"] = round(w.WallType.Width * 12.0, 2)
        except Exception:
            pass

    info["at_centroid"] = hit_at(cx, cy)
    info["stepped_along_+orientation"] = [
        {"offset_ft": d, "hits": hit_at(cx + nx * d, cy + ny * d)} for d in (0.25, 0.75, 1.5, 3.0)]
    info["stepped_along_-orientation"] = [
        {"offset_ft": d, "hits": hit_at(cx - nx * d, cy - ny * d)} for d in (0.25, 0.75, 1.5, 3.0)]
    break

OUT = info
