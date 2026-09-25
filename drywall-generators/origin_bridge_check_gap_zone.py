# origin_bridge_check_gap_zone.py - run via the ORIGIN Bridge. READ-ONLY.
# A 2ft-wide strip (X -27.688 to -25.688, Y 9.373-17.373) is uncovered by any DP-S001-* board in
# the soffit's row 1/2, while row 3 (same X-range) is fully covered by one continuous board. Finds
# every real Revit element (any category) whose bbox overlaps this exact strip, to find out what's
# physically there - a beam, a wall, a duct, or genuinely nothing (a real coverage bug).
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

ZX0, ZY0, ZX1, ZY1 = -27.688, 9.373, -25.688, 17.373
ZZ0, ZZ1 = 8.0, 12.0

found = []
for e in FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements():
    try:
        bb = e.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        continue
    if (bb.Max.X < ZX0 or bb.Min.X > ZX1 or bb.Max.Y < ZY0 or bb.Min.Y > ZY1 or
            bb.Max.Z < ZZ0 or bb.Min.Z > ZZ1):
        continue
    try:
        cat = e.Category.Name if e.Category else None
    except Exception:
        cat = None
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    try:
        eidv = e.Id.IntegerValue
    except Exception:
        try:
            eidv = e.Id.Value
        except Exception:
            eidv = None
    found.append({
        "category": cat, "mark": mark, "element_id": eidv, "class": type(e).__name__,
        "bbox": {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                 "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
    })

OUT = {"zone": [ZX0, ZY0, ZX1, ZY1], "elements_found": len(found), "elements": found}
