# origin_bridge_check_soffit_rotation.py - run via the ORIGIN Bridge. READ-ONLY.
# Checks whether the soffit ceiling C406965's own boundary edges are axis-aligned in world X/Y,
# or genuinely rotated - to tell apart "the building is rotated" from "the 3D view camera is
# rotated" as the explanation for DP-S001-018 looking vertical on screen despite a wider world-X
# bounding box.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
import math

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

ceiling = doc.GetElement(ElementId(406965))
out = {"ceiling_found": ceiling is not None, "edges": [], "view_rotation": None}

if ceiling is not None:
    try:
        sketch_id = ceiling.SketchId
        sketch = doc.GetElement(sketch_id)
        profile = sketch.Profile
        for loop in profile:
            for curve in loop:
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                dx = p1.X - p0.X
                dy = p1.Y - p0.Y
                length = math.sqrt(dx * dx + dy * dy)
                angle_deg = math.degrees(math.atan2(dy, dx)) if length > 1e-6 else None
                out["edges"].append({
                    "p0": [round(p0.X, 3), round(p0.Y, 3)], "p1": [round(p1.X, 3), round(p1.Y, 3)],
                    "length_ft": round(length, 3),
                    "angle_deg_from_world_x": round(angle_deg, 2) if angle_deg is not None else None,
                })
    except Exception as ex:
        out["sketch_error"] = str(ex)

# Also check any wall near the soffit for its own angle (walls define the "true" building grid).
walls_near = []
try:
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            curve = w.Location.Curve
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
        except Exception:
            continue
        dx = p1.X - p0.X
        dy = p1.Y - p0.Y
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1.0:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        # normalize to [0,90) since a wall's "forward" direction is arbitrary
        norm_angle = angle % 90
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        walls_near.append({"mark": mark, "angle_deg_mod90": round(norm_angle, 2)})
except Exception as ex:
    out["walls_error"] = str(ex)
out["wall_angles_sample"] = walls_near[:8]

# View rotation: for the active 3D view, dump its right/up vectors relative to world X/Y/Z.
try:
    v = uidoc.ActiveView
    orient = v.GetOrientation()
    fwd = orient.ForwardDirection
    up = orient.UpDirection
    out["view_rotation"] = {
        "view_name": v.Name,
        "forward": [round(fwd.X, 3), round(fwd.Y, 3), round(fwd.Z, 3)],
        "up": [round(up.X, 3), round(up.Y, 3), round(up.Z, 3)],
    }
except Exception as ex:
    out["view_rotation_error"] = str(ex)

OUT = out
