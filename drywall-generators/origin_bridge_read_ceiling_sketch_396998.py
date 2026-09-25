# origin_bridge_read_ceiling_sketch_396998.py - run via the ORIGIN Bridge. READ-ONLY.
# Reads the exact boundary profile, level, and height offset of ceiling 396998 (the "Roof Soffit"
# element) so it can be recreated as a real Ceiling with identical geometry.
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

TARGET_EID = 396998
e = doc.GetElement(ElementId(TARGET_EID))
out = {}

try:
    out["level_id"] = int(e.LevelId.Value) if hasattr(e.LevelId, "Value") else int(e.LevelId.IntegerValue)
    lvl = doc.GetElement(e.LevelId)
    out["level_name"] = lvl.Name if lvl else None
except Exception as ex:
    out["level_error"] = str(ex)

try:
    ho = e.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
    out["height_offset_ft"] = ho.AsDouble() if ho else None
except Exception as ex:
    out["height_offset_error"] = str(ex)

try:
    sketch_id = e.SketchId
    out["sketch_id"] = int(sketch_id.Value) if hasattr(sketch_id, "Value") else int(sketch_id.IntegerValue)
    sketch = doc.GetElement(sketch_id)
    out["sketch_found"] = sketch is not None
    if sketch is not None:
        profile = sketch.Profile
        loops = []
        for arr in profile:
            loop = []
            for c in arr:
                p0 = c.GetEndPoint(0)
                p1 = c.GetEndPoint(1)
                loop.append({
                    "type": type(c).__name__,
                    "p0": [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)],
                    "p1": [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)],
                })
            loops.append(loop)
        out["loops"] = loops
        out["loop_count"] = len(loops)
except Exception as ex:
    import traceback
    out["sketch_error"] = traceback.format_exc()

OUT = out
