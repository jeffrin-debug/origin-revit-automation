# origin_bridge_check_s001_003_004.py - run via the ORIGIN Bridge. READ-ONLY.
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

targets = ["DP-S001-003", "DP-S001-004"]
results = []
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in targets:
        continue
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = e.get_BoundingBox(None)
    opt = Options()
    geo = e.get_Geometry(opt)
    vol = 0.0
    face_count = 0
    if geo:
        for g in geo:
            if isinstance(g, Solid):
                vol += g.Volume
                face_count += g.Faces.Size
    results.append({
        "mark": mark, "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "comments": comments,
        "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)],
        "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)],
        "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)],
        "volume_cf": round(vol, 5), "face_count": face_count,
    })

results.sort(key=lambda r: r["mark"])
OUT = {"panels": results}
