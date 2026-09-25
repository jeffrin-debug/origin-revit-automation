# origin_bridge_check_visible_near_panels.py - run via the ORIGIN Bridge. READ-ONLY.
# For each target panel's bbox, scans ALL document elements (any category) nearby and reports
# which ones are actually VISIBLE in the "ORIGIN Assembly" view right now - to catch a real
# Wall/Floor/Ceiling/Door bleeding through via a per-element visibility override even though its
# whole category is hidden at the view level (confirmed root cause earlier this session).
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

TARGET_EIDS = [412520, 412788]
PAD = 1.0   # generous padding (ft) - catch anything crossing nearby, not just touching exactly

view = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
        view = v
        break

results = []
for eid in TARGET_EIDS:
    e = doc.GetElement(ElementId(eid))
    entry = {"eid": eid, "view_found": view is not None}
    if e is None or view is None:
        results.append(entry)
        continue
    bb = e.get_BoundingBox(None)
    if bb is None:
        results.append(entry)
        continue
    nearby = []
    for other in FilteredElementCollector(doc).WhereElementIsNotElementType():
        if other.Id == e.Id:
            continue
        try:
            obb = other.get_BoundingBox(view)
        except Exception:
            obb = None
        if obb is None:
            continue
        if (obb.Max.X < bb.Min.X - PAD or obb.Min.X > bb.Max.X + PAD or
                obb.Max.Y < bb.Min.Y - PAD or obb.Min.Y > bb.Max.Y + PAD or
                obb.Max.Z < bb.Min.Z - PAD or obb.Min.Z > bb.Max.Z + PAD):
            continue
        try:
            cat_name = other.Category.Name if other.Category else None
        except Exception:
            cat_name = None
        try:
            is_hidden = other.IsHidden(view)
        except Exception:
            is_hidden = None
        try:
            cat_hidden = other.Category.get_Visible(view) is False if other.Category else None
        except Exception:
            cat_hidden = None
        try:
            mk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            omark = mk.AsString() if mk else None
        except Exception:
            omark = None
        nearby.append({
            "eid": (other.Id.Value if hasattr(other.Id, "Value") else other.Id.IntegerValue),
            "class": type(other).__name__,
            "category": cat_name,
            "mark": omark,
            "is_hidden_in_view": is_hidden,
            "category_hidden_in_view": cat_hidden,
            "VISIBLE_AND_SUSPECT": (is_hidden is False and cat_hidden is True),
        })
    entry["nearby_count"] = len(nearby)
    entry["nearby"] = nearby
    results.append(entry)

OUT = {"panels": results}
