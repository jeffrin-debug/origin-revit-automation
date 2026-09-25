# origin_bridge_diag_wall_ceiling_span.py - READ-ONLY.
# Walk wall W431171's EXTERIOR face at fine steps and report exactly where a ceiling covers it.
# Tells us whether face_ceiling_cap()'s 9-sample sweep missed a short stretch (a density problem)
# or whether something else is going on.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

EID = 431171
PROBE_OFFSET_FT = 0.75
STEP_FT = 0.25


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
    ceilings.append({"z": bb.Min.Z,
                     "box": (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z),
                     "solids": solids_of(c)})


def z_at(px, py):
    best = None
    for cp in ceilings:
        b = cp["box"]
        if px < b[0] or px > b[3] or py < b[1] or py > b[4]:
            continue
        if best is not None and cp["z"] >= best:
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
                best = cp["z"]
                break
    return best


w = doc.GetElement(ElementId(EID))
crv = w.Location.Curve
p0 = crv.GetEndPoint(0)
p1 = crv.GetEndPoint(1)
length = crv.Length
ux = (p1.X - p0.X) / length
uy = (p1.Y - p0.Y) / length
o = w.Orientation

walk = []
n = int(length / STEP_FT) + 1
for i in range(n + 1):
    along = min(length, i * STEP_FT)
    px = p0.X + ux * along + o.X * PROBE_OFFSET_FT
    py = p0.Y + uy * along + o.Y * PROBE_OFFSET_FT
    walk.append({"along_ft": round(along, 2), "ceiling_z": z_at(px, py)})

# where the current 9-sample sweep actually lands
samples = []
for i in range(9):
    f = (i + 0.5) / 9.0
    along = length * f
    px = p0.X + ux * along + o.X * PROBE_OFFSET_FT
    py = p0.Y + uy * along + o.Y * PROBE_OFFSET_FT
    samples.append({"along_ft": round(along, 2), "ceiling_z": z_at(px, py)})

covered = [wk["along_ft"] for wk in walk if wk["ceiling_z"] is not None]

OUT = {
    "wall": EID,
    "length_ft": round(length, 3),
    "exterior_offset_probe_ft": PROBE_OFFSET_FT,
    "covered_from_ft": min(covered) if covered else None,
    "covered_to_ft": max(covered) if covered else None,
    "covered_steps": len(covered),
    "total_steps": len(walk),
    "nine_sample_sweep": samples,
    "walk": walk,
}
