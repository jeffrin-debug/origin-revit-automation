# origin_bridge_st012_003_vertices.py - run via the ORIGIN Bridge. READ-ONLY.
# ST-012-003's bbox looked ~23in wide in one axis vs its neighbor drywall's 0.5in - get the REAL
# solid vertices (not just an axis-aligned bbox) to confirm the actual shape before touching code.
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

TARGET_MARKS = ["ST-012-003", "DP-012-001A", "DP-006-001A"]


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
out = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGET_MARKS:
        continue
    solids = solids_of(ds)
    rec = {"volume_cf": round(sum(s.Volume for s in solids), 6), "solids": len(solids), "faces": []}
    for s in solids:
        for f in s.Faces:
            if not isinstance(f, PlanarFace):
                continue
            n = f.FaceNormal
            loops = list(f.GetEdgesAsCurveLoops())
            if not loops:
                continue
            pts = []
            for curve in loops[0]:
                p = curve.GetEndPoint(0)
                pts.append([round(p.X, 4), round(p.Y, 4), round(p.Z, 4)])
            rec["faces"].append({
                "normal": [round(n.X, 4), round(n.Y, 4), round(n.Z, 4)],
                "area_sf": round(f.Area, 4),
                "points": pts,
            })
    out[mark] = rec

OUT = out
