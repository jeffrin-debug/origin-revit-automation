# origin_bridge_find_column_ceiling.py - run via the ORIGIN Bridge. READ-ONLY.
# Locates every real Column/StructuralColumn's plan footprint, and every ceiling drywall board
# (DP-C*) whose bbox is within a few feet of one - to find a live, real case of "a column near a
# ceiling panel run" to measure before designing a fix, instead of guessing.
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

cols = []
for bic in (BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns):
    try:
        for e in FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements():
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            try:
                mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                mark = mk.AsString() if mk else None
            except Exception:
                mark = None
            cols.append({
                "category": str(bic), "mark": mark,
                "bbox": {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                         "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
            })
    except Exception:
        pass

boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-C") or mark.startswith("DP-S")):
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    boards.append((mark, bb))

pad = 6.0  # ft
near = []
for c in cols:
    cmn = c["bbox"]["min"]
    cmx = c["bbox"]["max"]
    for (mark, bb) in boards:
        if (bb.Max.X < cmn[0] - pad or bb.Min.X > cmx[0] + pad or
                bb.Max.Y < cmn[1] - pad or bb.Min.Y > cmx[1] + pad):
            continue
        near.append({
            "column_mark": c["mark"], "column_bbox": c["bbox"], "board_mark": mark,
            "board_bbox": {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                           "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
        })

OUT = {"columns_found": len(cols), "columns": cols, "dp_c_boards_total": len(boards),
       "near_pairs": near[:60]}
