# origin_bridge_check_corner_geometry.py - run via the ORIGIN Bridge. READ-ONLY.
# Deep-dive on a specific reported corner: wall centerlines/widths for W380854 and W404773,
# plus the real 2D footprint (XY vertex outline, deduped) of DP-010-001A and DP-033-001B near
# the corner, so we can see the ACTUAL cut shape (plain rectangle vs notch/miter) rather than
# just bounding boxes.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break


def solids_of(e):
    out = []
    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    out.append(g2)
    return out


def mark_of(e):
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return mk.AsString() if mk else None
    except Exception:
        return None


def xy_outline(e, z_sample=2.0, tol=0.01):
    solids = solids_of(e)
    pts = set()
    for s in solids:
        for edge in s.Edges:
            crv = edge.AsCurve()
            for t in (0.0, 1.0):
                try:
                    p = crv.Evaluate(t, True) if hasattr(crv, "Evaluate") else None
                except Exception:
                    p = None
            try:
                p0 = crv.GetEndPoint(0)
                p1 = crv.GetEndPoint(1)
                for p in (p0, p1):
                    if abs(p.Z - z_sample) < 1.0:
                        pts.add((round(p.X, 4), round(p.Y, 4), round(p.Z, 4)))
            except Exception:
                continue
    return sorted(pts)


out = {}

wall_ids = {"W380854": 380854, "W404773": 404773}
for tag, wid in wall_ids.items():
    w = doc.GetElement(ElementId(wid))
    if w is None:
        out[tag] = None
        continue
    loc = w.Location
    crv = loc.Curve if hasattr(loc, "Curve") else None
    info = {"width_ft": round(w.Width, 4), "width_in": round(w.Width * 12.0, 4)}
    if crv is not None:
        p0 = crv.GetEndPoint(0)
        p1 = crv.GetEndPoint(1)
        info["p0"] = [round(p0.X, 4), round(p0.Y, 4)]
        info["p1"] = [round(p1.X, 4), round(p1.Y, 4)]
    try:
        wt = doc.GetElement(w.GetTypeId())
        info["type_name"] = wt.Name if wt else None
    except Exception:
        pass
    out[tag] = info

targets = ["DP-010-001A", "DP-033-001B"]
boards = {}
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    mk = mark_of(e)
    if mk in targets:
        boards[mk] = e

for mk, e in boards.items():
    bb = e.get_BoundingBox(None)
    out[mk + "_outline_xy"] = xy_outline(e)
    out[mk + "_bbox"] = None if bb is None else {
        "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
        "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)],
    }

OUT = out
