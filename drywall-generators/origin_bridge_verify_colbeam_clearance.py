# origin_bridge_verify_colbeam_clearance.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms COLUMN_BEAM_CLEARANCE_FT (0.05 ft = 0.6in) is the exact mechanism behind the "mini tiny
# vacuum gap" the user described between DP-S001-004 (ceiling board, column cutout) and the real
# column element K512059 - by comparing the REAL column element's own raw bbox against the
# distance to DP-S001-004's cutout, using the real column drywall boards as the physical reference
# a robot would actually touch.
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

COLUMN_EID = 512059

col = doc.GetElement(ElementId(COLUMN_EID))
out = {"column_found": col is not None}
if col is not None:
    cbb = col.get_BoundingBox(None)
    out["real_column_element_bbox"] = {
        "min": [round(cbb.Min.X, 4), round(cbb.Min.Y, 4), round(cbb.Min.Z, 4)],
        "max": [round(cbb.Max.X, 4), round(cbb.Max.Y, 4), round(cbb.Max.Z, 4)],
    }
    C = 0.05
    out["expected_cutout_bbox_with_clearance"] = {
        "min": [round(cbb.Min.X - C, 4), round(cbb.Min.Y - C, 4)],
        "max": [round(cbb.Max.X + C, 4), round(cbb.Max.Y + C, 4)],
    }

OUT = out
