# origin_bridge_set_plain_shading.py - run via the ORIGIN Bridge. Small, reversible VIEW SETTING
# change only (not model geometry): switches the "ORIGIN Assembly" view from RealisticWithEdges
# (directional-lighting-based shading, can render an away-facing face near-black even with correct
# material) to plain Shading (flat material color, no directional lighting) - a direct test of
# whether a "dark/intrusion-looking" area is a lighting artifact rather than a real defect.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

v = None
for view in FilteredElementCollector(doc).OfClass(View3D):
    if view.Name == "ORIGIN Assembly" and not view.IsTemplate:
        v = view
        break

if v is None:
    OUT = {"error": "view 'ORIGIN Assembly' not found"}
else:
    before = str(v.DisplayStyle)
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        v.DisplayStyle = DisplayStyle.Shading
    finally:
        TransactionManager.Instance.TransactionTaskDone()
    OUT = {"doc_title": target_title, "view_name": v.Name,
           "display_style_before": before, "display_style_after": str(v.DisplayStyle)}
