# origin_bridge_check_dp001_006b.py - run via the ORIGIN Bridge. READ-ONLY.
# User: DP-001-006B is a wall panel that spans across where a soffit begins/ends along the wall's
# run - wants it forced to split into two separate panels there (before/after the soffit), same
# idea as the existing partition-split mechanism. Ground-truths the board's real extent plus the
# soffit band walls (005/006/012) and the real soffit Ceiling element, to find the exact boundary.
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

TARGET_MARKS = ["DP-001-006B", "DP-001-005B", "DP-001-007B"]

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
out = {"boards": {}}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in TARGET_MARKS:
        try:
            cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        bb = ds.get_BoundingBox(None)
        out["boards"][mark] = {
            "comments": comments,
            "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                     "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
        }

# Wall 001's own Location line, for reference.
try:
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and mk.AsString() == "001":
            lc = w.Location.Curve
            out["wall_001_location"] = {
                "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                "width_ft": round(w.Width, 4),
            }
            break
except Exception as ex:
    out["wall_001_location_error"] = str(ex)

# Soffit band walls (005/006/012) real Location lines - the soffit's own footprint against wall 001.
out["band_walls"] = {}
for tag in ("005", "006", "012"):
    try:
        for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            if mk and mk.AsString() == tag:
                lc = w.Location.Curve
                out["band_walls"][tag] = {
                    "start": [round(lc.GetEndPoint(0).X, 4), round(lc.GetEndPoint(0).Y, 4)],
                    "end": [round(lc.GetEndPoint(1).X, 4), round(lc.GetEndPoint(1).Y, 4)],
                }
                break
    except Exception as ex:
        out["band_walls"][tag] = {"error": str(ex)}

# The real soffit Ceiling element's own bbox.
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    bb = c.get_BoundingBox(None)
    if bb is None:
        continue
    out["soffit_ceiling_bbox"] = {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                                   "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}
    break

OUT = out
