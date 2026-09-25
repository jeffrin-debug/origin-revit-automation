# origin_bridge_check_corner_gap.py - run via the ORIGIN Bridge. READ-ONLY.
# User selected ST-014-001 (a stud) at a corner in the ORIGIN Assembly view and reports a visible
# black gap - genuinely missing drywall coverage, not just a stud color. Ground-truths ST-014-001
# exactly, wall 014's own real geometry/neighbors at both ends, and every DP-* board within a
# generous radius, to find the real hole rather than guessing.
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

out = {}

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
by_mark = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark:
        by_mark[mark] = ds

target = by_mark.get("ST-014-001")
if target is None:
    out["error"] = "ST-014-001 not found"
    OUT = out
else:
    bb = target.get_BoundingBox(None)
    try:
        cm = target.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    out["ST-014-001"] = {
        "comments": comments,
        "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                 "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    }

    # Wall 014's own real geometry.
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and mk.AsString() == "014":
            lc = w.Location.Curve
            wbb = w.get_BoundingBox(None)
            out["wall_014"] = {
                "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                "width_ft": round(w.Width, 4),
                "bbox": {"min": [round(wbb.Min.X, 4), round(wbb.Min.Y, 4), round(wbb.Min.Z, 4)],
                         "max": [round(wbb.Max.X, 4), round(wbb.Max.Y, 4), round(wbb.Max.Z, 4)]},
            }
            break

    # Every DP-* board within 1.5ft of ST-014-001's own bbox.
    pad = 1.5
    nearby_boards = []
    for mark, ds in by_mark.items():
        if not mark.startswith("DP-"):
            continue
        obb = ds.get_BoundingBox(None)
        if (obb.Max.X < bb.Min.X - pad or obb.Min.X > bb.Max.X + pad or
                obb.Max.Y < bb.Min.Y - pad or obb.Min.Y > bb.Max.Y + pad or
                obb.Max.Z < bb.Min.Z - pad or obb.Min.Z > bb.Max.Z + pad):
            continue
        try:
            cm2 = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments2 = cm2.AsString() if cm2 else None
        except Exception:
            comments2 = None
        nearby_boards.append({
            "mark": mark, "comments": comments2,
            "bbox": {"min": [round(obb.Min.X, 4), round(obb.Min.Y, 4), round(obb.Min.Z, 4)],
                     "max": [round(obb.Max.X, 4), round(obb.Max.Y, 4), round(obb.Max.Z, 4)]},
        })
    out["nearby_boards_within_1.5ft"] = nearby_boards

    # Every ST-* framing member within 1.5ft too, for context.
    nearby_studs = []
    for mark, ds in by_mark.items():
        if not mark.startswith("ST-") or mark == "ST-014-001":
            continue
        obb = ds.get_BoundingBox(None)
        if (obb.Max.X < bb.Min.X - pad or obb.Min.X > bb.Max.X + pad or
                obb.Max.Y < bb.Min.Y - pad or obb.Min.Y > bb.Max.Y + pad or
                obb.Max.Z < bb.Min.Z - pad or obb.Min.Z > bb.Max.Z + pad):
            continue
        try:
            cm3 = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments3 = cm3.AsString() if cm3 else None
        except Exception:
            comments3 = None
        nearby_studs.append({"mark": mark, "comments": comments3,
                              "bbox": {"min": [round(obb.Min.X, 4), round(obb.Min.Y, 4), round(obb.Min.Z, 4)],
                                       "max": [round(obb.Max.X, 4), round(obb.Max.Y, 4), round(obb.Max.Z, 4)]}})
    out["nearby_studs_within_1.5ft"] = nearby_studs

    OUT = out
