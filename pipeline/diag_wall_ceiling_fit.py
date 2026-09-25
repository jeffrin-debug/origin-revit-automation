# diag_wall_ceiling_fit.py - read-only: do wall boards meet the ceiling over each stretch?
#
# For every wall face, every 0.5 ft along it: find the ceiling in front of the face (0.75 ft out,
# the generator's own probe offset, by ceiling bbox) and check
#   GAP       - no board of that face covers the point 1 in below that ceiling (bare studs)
#   OVERSHOOT - a board of that face reaches more than 0.1 in past that ceiling
# Samples over a door/window opening, and walls the ceiling is below the base of (soffit bands),
# are skipped. Reported per wall face with the along-wall ranges affected.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
STEP, OFF, BELOW, OVER = 0.5, 0.75, 1.0 / 12.0, 0.1 / 12.0


def par(e, b):
    p = e.get_Parameter(b)
    return (p.AsString() or "") if p else ""


ceilings = []
for c in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType():
    bb = c.get_BoundingBox(None)
    if bb is not None:
        ceilings.append((par(c, BuiltInParameter.ALL_MODEL_MARK), bb))

boards = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    cm = par(ds, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if not cm.startswith("ORIGIN_ASSEMBLY_V4") or "| DRYWALL |" not in cm or "SOFFIT_UNDERSIDE" in cm:
        continue
    w = [t.strip()[5:] for t in cm.split("|") if t.strip().startswith("WALL=")]
    face = "A" if "FACE_A" in cm else "B"
    bb = ds.get_BoundingBox(None)
    if w and bb is not None:
        boards.setdefault((w[0], face), []).append((par(ds, BuiltInParameter.ALL_MODEL_MARK), bb))

out = []
for wall in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        crv = wall.Location.Curve
        if not isinstance(crv, Line):
            continue
    except Exception:
        continue
    wid = "W{}".format(wall.Id.IntegerValue if hasattr(wall.Id, "IntegerValue") else wall.Id.Value)
    wb = wall.get_BoundingBox(None)
    p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
    L = p0.DistanceTo(XYZ(p1.X, p1.Y, p0.Z))
    u = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0).Normalize()
    n = XYZ(-u.Y, u.X, 0)
    openings = []
    for i in wall.FindInserts(True, False, False, False):
        e = doc.GetElement(i)
        ob = e.get_BoundingBox(None) if e is not None else None
        if ob is not None:
            a = [XYZ(x, y, 0).Subtract(XYZ(p0.X, p0.Y, 0)).DotProduct(u)
                 for x in (ob.Min.X, ob.Max.X) for y in (ob.Min.Y, ob.Max.Y)]
            openings.append((min(a) - 0.1, max(a) + 0.1, ob.Min.Z, ob.Max.Z + 0.1))
    for face in ("A", "B"):
        bl = boards.get((wid, face), [])
        if not bl:
            continue
        # which side of the wall line this face's boards are on
        cx = sum((b.Min.X + b.Max.X) / 2.0 for _, b in bl) / len(bl)
        cy = sum((b.Min.Y + b.Max.Y) / 2.0 for _, b in bl) / len(bl)
        # which way this face points: away from the wall's own middle (its bbox centre), and the
        # probe is taken OFF past this face - the location line can sit on either face
        wcx, wcy = (wb.Min.X + wb.Max.X) / 2.0, (wb.Min.Y + wb.Max.Y) / 2.0
        face_off = (cx - p0.X) * n.X + (cy - p0.Y) * n.Y
        mid_off = (wcx - p0.X) * n.X + (wcy - p0.Y) * n.Y
        s = 1.0 if face_off >= mid_off else -1.0
        bl_along = []
        for (m, b) in bl:
            al = [XYZ(x, y, 0).Subtract(XYZ(p0.X, p0.Y, 0)).DotProduct(u)
                  for x in (b.Min.X, b.Max.X) for y in (b.Min.Y, b.Max.Y)]
            bl_along.append((m, b, min(al), max(al)))
        gaps, overs = [], set()
        k = 0
        while k * STEP <= L:
            a = min(k * STEP + 0.01, L - 0.01)
            k += 1
            px = p0.X + u.X * a + n.X * (face_off + s * OFF)
            py = p0.Y + u.Y * a + n.Y * (face_off + s * OFF)
            cz = None
            for (_, cb) in ceilings:
                if cb.Min.X <= px <= cb.Max.X and cb.Min.Y <= py <= cb.Max.Y:
                    cz = cb.Min.Z if cz is None else min(cz, cb.Min.Z)
            if cz is None or cz <= wb.Min.Z + 1.0 or cz > wb.Max.Z + 0.01:
                continue
            z = cz - BELOW
            if any(o[0] <= a <= o[1] and o[2] <= z <= o[3] for o in openings):
                continue
            # match by position ALONG the wall - the location line may be a face, not the centre
            here = [(m, b) for (m, b, a0, a1) in bl_along if a0 - 0.02 <= a <= a1 + 0.02]
            if not any(b.Min.Z <= z <= b.Max.Z for (_, b) in here):
                gaps.append(round(a, 1))
            for (m, b) in here:
                if b.Max.Z > cz + OVER:
                    overs.add("{} ({:.2f} ft over)".format(m, b.Max.Z - cz))
        if gaps or overs:
            out.append({"wall": wid, "mark": par(wall, BuiltInParameter.ALL_MODEL_MARK), "face": face,
                        "gap_at_ft": gaps[:12], "gap_samples": len(gaps), "overshoot": sorted(overs)[:8]})
OUT = {"faces_with_issues": len(out), "issues": out}
