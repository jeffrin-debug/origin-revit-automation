# origin_bridge_check_door_frame_ds.py - run via the ORIGIN Bridge. READ-ONLY.
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
    if not mark or not mark.startswith("DF-"):
        continue
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = e.get_BoundingBox(None)
    vol = 0.0
    opt = Options()
    geo = e.get_Geometry(opt)
    face_total = 0
    if geo:
        for g in geo:
            if isinstance(g, Solid):
                vol += g.Volume
                face_total += g.Faces.Size
    results.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)],
        },
        "volume_cf": round(vol, 5), "face_total": face_total,
    })

OUT = {"count": len(results), "door_frames": results}
