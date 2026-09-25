# origin_bridge_check_wall010.py - run via the ORIGIN Bridge. READ-ONLY.
# Ground-truths DP-010-001B/003B/006B (user reports the "same issue" as the wall 008 / ST-009-001
# fix) - their bboxes, wall 010's own Location line, and any nearby stud from a DIFFERENT wall
# whose bbox comes close to/overlaps their Y (or X) range, to identify the analogous neighbor.
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

TARGET_MARKS = ["DP-010-001B", "DP-010-003B", "DP-010-006B"]

out = {"boards": {}}

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
found = {}
all_studs = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    if mark in TARGET_MARKS:
        try:
            cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        bb = ds.get_BoundingBox(None)
        found[mark] = {
            "comments": comments,
            "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                     "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
        }
    if mark.startswith("ST-"):
        bb = ds.get_BoundingBox(None)
        if bb is not None:
            all_studs.append((mark, bb))

out["boards"] = found

# Wall 010's own Location line, for reference.
try:
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and mk.AsString() == "010":
            lc = w.Location.Curve
            out["wall_010_location"] = {
                "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                "width_ft": round(w.Width, 4),
            }
            break
except Exception as ex:
    out["wall_010_location_error"] = str(ex)

# For each target board, find every OTHER wall's stud whose bbox is within 0.5ft (bbox-expanded)
# of the board's own bbox - the analogous "ST-009-001" for wall 010.
RADIUS_FT = 0.5
nearby = {}
for mark, rec in found.items():
    b = rec["bbox"]
    bx0, by0, bz0 = b["min"]
    bx1, by1, bz1 = b["max"]
    hits = []
    for (smark, sbb) in all_studs:
        if (sbb.Max.X < bx0 - RADIUS_FT or sbb.Min.X > bx1 + RADIUS_FT or
                sbb.Max.Y < by0 - RADIUS_FT or sbb.Min.Y > by1 + RADIUS_FT or
                sbb.Max.Z < bz0 - RADIUS_FT or sbb.Min.Z > bz1 + RADIUS_FT):
            continue
        # skip studs that belong to the same wall (mark prefix ST-010-)
        if smark.startswith("ST-010-"):
            continue
        ox = min(bx1, sbb.Max.X) - max(bx0, sbb.Min.X)
        oy = min(by1, sbb.Max.Y) - max(by0, sbb.Min.Y)
        oz = min(bz1, sbb.Max.Z) - max(bz0, sbb.Min.Z)
        hits.append({
            "stud": smark,
            "axis_overlap_in": {"x": round(ox * 12.0, 4), "y": round(oy * 12.0, 4), "z": round(oz * 12.0, 4)},
            "stud_bbox": {"min": [round(sbb.Min.X, 4), round(sbb.Min.Y, 4), round(sbb.Min.Z, 4)],
                          "max": [round(sbb.Max.X, 4), round(sbb.Max.Y, 4), round(sbb.Max.Z, 4)]},
        })
    nearby[mark] = hits

out["nearby_other_wall_studs"] = nearby

OUT = out
