# origin_bridge_dump_solid_faces.py - run via the ORIGIN Bridge. READ-ONLY.
# DP-001-003B's bbox shows an abnormal 2.375in thickness instead of the intended 0.5in. Dumps the
# real solid's face count/normals/areas to see whether it's a simple 6-face box (uniformly thick,
# meaning a real Y-inset computation bug) or something more complex (a boolean leftover/artifact
# shape), which points to a very different root cause.
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

TARGETS = ["DP-001-003B", "DP-001-007B", "DP-001-003A"]

out = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGETS:
        continue
    opt = Options()
    geo = ds.get_Geometry(opt)
    solids = [g for g in geo if isinstance(g, Solid) and g.Volume > 1e-9] if geo else []
    entry = {"solid_count": len(solids), "solids": []}
    for si, sol in enumerate(solids):
        faces = []
        for f in sol.Faces:
            try:
                normal = f.ComputeNormal(UV(0.5, 0.5))
                area = f.Area
                bb = f.GetBoundingBox()
                faces.append({
                    "normal": [round(normal.X, 3), round(normal.Y, 3), round(normal.Z, 3)],
                    "area_sf": round(area, 4),
                })
            except Exception as ex:
                faces.append({"error": str(ex)})
        entry["solids"].append({"volume_cf": round(sol.Volume, 5), "face_count": len(faces), "faces": faces})
    out[mark] = entry

OUT = out
