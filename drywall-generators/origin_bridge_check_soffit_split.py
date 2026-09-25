# origin_bridge_check_soffit_split.py - run via the ORIGIN Bridge. READ-ONLY.
# Verifies the new soffit-level partition-split fix: wall 001's top course (Z 8-10, at soffit
# level) around band wall 006's junction (Y=16.7901) should now be TWO boards, not one spanning
# across; wall 001's lower courses and wall 003 (a different band-wall junction) should be
# UNCHANGED from before (no floor-to-ceiling forced split reintroduced).
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

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
wall001_b = []
wall003 = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-"):
        continue
    bb = ds.get_BoundingBox(None)
    rec = {"mark": mark,
           "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                    "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}}
    if mark.startswith("DP-001-") and mark.endswith("B"):
        wall001_b.append(rec)
    if mark.startswith("DP-003-"):
        wall003.append(rec)

wall001_b.sort(key=lambda r: (r["bbox"]["min"][2], r["bbox"]["min"][1]))
wall003.sort(key=lambda r: (r["bbox"]["min"][2], r["bbox"]["min"][0], r["bbox"]["min"][1]))

OUT = {"wall_001_face_B": wall001_b, "wall_003_all": wall003}
