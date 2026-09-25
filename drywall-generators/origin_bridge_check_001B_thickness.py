# origin_bridge_check_001B_thickness.py - run via the ORIGIN Bridge. READ-ONLY.
# Dumps real face-based thickness for every current DP-001-*B DirectShape to see if the
# abnormal-thickness bug (found earlier as ~2.375in instead of 0.5in) still reproduces after
# the fresh run, and under which board number(s).
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

results = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-001-") or not mark.endswith("B"):
        continue

    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    solids = []
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            solids.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    solids.append(g2)

    entry = {"mark": mark, "eid": int(e.Id.Value) if hasattr(e.Id, "Value") else int(e.Id.IntegerValue),
             "solid_count": len(solids), "solids": []}
    for s in solids:
        vol = s.Volume
        face_count = s.Faces.Size
        bb = s.GetBoundingBox()
        mn = bb.Transform.OfPoint(bb.Min)
        mx = bb.Transform.OfPoint(bb.Max)
        y_span_in = round((mx.Y - mn.Y) * 12.0, 4)
        # find the Y-facing (normal ~ +-Y) face(s) to get true area for thickness = vol/area
        y_face_area = None
        for f in s.Faces:
            try:
                n = f.ComputeNormal(UV(0.5, 0.5))
            except Exception:
                continue
            if abs(n.Y) > 0.9:
                a = f.Area
                if y_face_area is None or a > y_face_area:
                    y_face_area = a
        thickness_in = round((vol / y_face_area) * 12.0, 4) if y_face_area else None
        entry["solids"].append({
            "face_count": face_count, "volume_cf": round(vol, 5),
            "bbox_min": [round(mn.X, 4), round(mn.Y, 4), round(mn.Z, 4)],
            "bbox_max": [round(mx.X, 4), round(mx.Y, 4), round(mx.Z, 4)],
            "y_span_in": y_span_in, "y_face_area_sf": round(y_face_area, 4) if y_face_area else None,
            "thickness_from_area_in": thickness_in,
        })
    results.append(entry)

results.sort(key=lambda r: r["mark"])
OUT = {"count": len(results), "boards": results}
