# probe_seal_perimeter.py
# ============================================================
# Bridging wall ends did not help, so the interior is probably leaking to the OUTSIDE rather
# than between rooms. This seals the building perimeter with temporary Room Separation Lines
# traced around the floor slab's outer edge, then runs NewRooms2.
#
# Interpreting the result:
#   total area jumps to ~1000 sf, split into several rooms -> the perimeter was the leak, and
#       sealing it lets Revit find the real rooms. This becomes the fix.
#   one enormous room                                      -> the interior walls do not divide
#       the space either; the model is effectively open-plan at the boundary plane.
#   still ~160 sf                                          -> something else entirely.
#
# Everything is rolled back. Nothing is modified.
# ============================================================

import clr
import math
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def bottom_face_loops(e):
    opt = Options()
    opt.ComputeReferences = False
    best, bz = None, None
    try:
        for g in e.get_Geometry(opt):
            if not isinstance(g, Solid) or g.Volume <= 0:
                continue
            for f in g.Faces:
                if isinstance(f, PlanarFace) and f.FaceNormal.Z < -0.9:
                    if best is None or f.Origin.Z < bz:
                        best, bz = f, f.Origin.Z
    except Exception:
        return None
    if best is None:
        return None
    loops = []
    try:
        for cl in best.GetEdgesAsCurveLoops():
            pts = []
            for c in cl:
                try:
                    tess = c.Tessellate()
                except Exception:
                    tess = [c.GetEndPoint(0), c.GetEndPoint(1)]
                for p in tess:
                    if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                        pts.append((p.X, p.Y))
            if len(pts) >= 3:
                loops.append(pts)
    except Exception:
        return None
    loops.sort(key=poly_area, reverse=True)
    return loops


res = {"doc": doc.Title}

levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)
base_lv = levels[0]
plane_ft = base_lv.Elevation
try:
    p = base_lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
    plane_ft = base_lv.Elevation + (p.AsDouble() if p else 0.0)
except Exception:
    pass

plan_view = None
for v in FilteredElementCollector(doc).OfClass(ViewPlan):
    try:
        if v.IsTemplate:
            continue
        gl = v.GenLevel
        if gl is not None and eid_value(gl.Id) == eid_value(base_lv.Id):
            plan_view = v
            break
    except Exception:
        continue
res["plan_view"] = plan_view.Name if plan_view is not None else None

foot, best_a = None, 0.0
for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
    loops = bottom_face_loops(fl)
    if not loops:
        continue
    a = poly_area(loops[0])
    if a > best_a:
        best_a, foot = a, loops[0]
res["footprint_area_sf"] = round(best_a, 1)
res["footprint_vertices"] = 0 if foot is None else len(foot)

if foot is None or plan_view is None:
    res["error"] = "need both a floor slab and a plan view"
    OUT = res
else:
    t = None
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        t = Transaction(doc, "ORIGIN seal-perimeter probe (rolled back)")
        fho = t.GetFailureHandlingOptions()
        try:
            fho.SetForcedModalHandling(False)
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        t.Start()

        sp = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(
            XYZ.BasisZ, XYZ(0, 0, plane_ft)))
        made = 0
        n = len(foot)
        for i in range(n):
            a = foot[i]
            b = foot[(i + 1) % n]
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.01:
                continue
            try:
                arr = CurveArray()
                arr.Append(Line.CreateBound(XYZ(a[0], a[1], plane_ft),
                                            XYZ(b[0], b[1], plane_ft)))
                doc.Create.NewRoomBoundaryLines(sp, arr, plan_view)
                made += 1
            except Exception:
                continue
        res["perimeter_lines_created"] = made
        doc.Regenerate()

        ph = None
        try:
            phs = doc.Phases
            ph = phs.get_Item(phs.Size - 1)
        except Exception:
            pass
        try:
            doc.Create.NewRooms2(base_lv, ph) if ph is not None else doc.Create.NewRooms2(base_lv)
        except Exception:
            doc.Create.NewRooms2(base_lv)
        doc.Regenerate()

        areas = []
        for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                  .WhereElementIsNotElementType()):
            try:
                if r.Area and r.Area > 0:
                    areas.append(round(r.Area, 2))
            except Exception:
                continue
        areas.sort(reverse=True)
        res["rooms_after"] = len(areas)
        res["total_room_area_sf"] = round(sum(areas), 1)
        res["room_areas_sf"] = areas[:40]
        res["coverage_pct_of_footprint"] = round(100.0 * sum(areas) / max(best_a, 1e-9), 1)

        if sum(areas) < 0.4 * best_a:
            res["verdict"] = "perimeter was NOT the leak"
        elif len(areas) <= 2:
            res["verdict"] = "perimeter WAS the leak, but interior walls do not subdivide it"
        else:
            res["verdict"] = "PERIMETER WAS THE LEAK - sealing it recovers the real rooms"
    except Exception:
        res["error"] = traceback.format_exc()
    finally:
        try:
            if t is not None and t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

    OUT = res
