# origin_bridge_check_ceiling_void.py - run via the ORIGIN Bridge. READ-ONLY.
# User screenshot shows a large white/empty L-shaped void in a ceiling plan view where drywall
# panels should be. Ground-truths every currently-existing ceiling/soffit board's real bbox, so
# the void's exact extent (and whether it's new or the previously-documented, intentionally
# reverted coverage gap) can be identified precisely.
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
boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-"):
        continue
    if not (mark.startswith("DP-S") or mark.startswith("DP-C")):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    boards.append({
        "mark": mark,
        "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                 "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })

# Also the real Ceiling/Soffit source elements, for the true expected outline.
ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    bb = c.get_BoundingBox(None)
    if bb is None:
        continue
    try:
        name = c.Name
    except Exception:
        name = None
    ceilings.append({
        "id": c.Id.IntegerValue if hasattr(c.Id, "IntegerValue") else int(str(c.Id)),
        "name": name,
        "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                 "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })

OUT = {"board_count": len(boards), "boards": boards, "ceiling_elements": ceilings}
