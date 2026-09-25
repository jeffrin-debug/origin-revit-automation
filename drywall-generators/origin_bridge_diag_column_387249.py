# origin_bridge_diag_column_387249.py - run via the ORIGIN Bridge. READ-ONLY.
# Column 387249 got zero DP-* boards even though the column generator ran and processed 3 OTHER
# columns cleanly with zero warnings/skips. Checks: is 387249 actually returned by the same
# category collector the generator uses, is it inside a Group (collectors don't recurse into
# groups by default - a classic silent-miss cause), and what its real bbox/dimensions are.
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

TARGET = 387249

cols = []
for bic in (BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns):
    try:
        cols.extend(list(FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()))
    except Exception as ex:
        cols.append(("ERROR", str(ex)))


def eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        pass
    try:
        return int(eid.IntegerValue)
    except Exception:
        return None


ids_found = []
target_in_collector = False
for c in cols:
    if isinstance(c, tuple):
        continue
    v = eid_value(c.Id)
    ids_found.append(v)
    if v == TARGET:
        target_in_collector = True

e = doc.GetElement(ElementId(TARGET))
info = {"exists": e is not None}
if e is not None:
    info["type"] = type(e).__name__
    try:
        info["category"] = e.Category.Name if e.Category else None
        info["category_id"] = int(e.Category.Id.Value) if e.Category else None
    except Exception:
        info["category"] = None
    try:
        info["group_id"] = eid_value(e.GroupId) if e.GroupId else None
        info["in_group"] = (e.GroupId is not None and eid_value(e.GroupId) != -1)
    except Exception:
        info["group_id"] = None
        info["in_group"] = None
    try:
        bb = e.get_BoundingBox(None)
        info["bbox"] = None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}
    except Exception as ex:
        info["bbox"] = "error: {}".format(ex)
    try:
        info["design_option"] = e.DesignOption.Name if e.DesignOption else None
    except Exception:
        info["design_option"] = None
    try:
        info["workset"] = e.WorksetId.IntegerValue if doc.IsWorkshared else None
    except Exception:
        info["workset"] = None
    try:
        p = e.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)
        t = doc.GetElement(p.AsElementId()) if p else None
        info["type_name"] = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() if t else None
    except Exception:
        info["type_name"] = None

OUT = {
    "target_eid": TARGET,
    "target_in_collector": target_in_collector,
    "collector_total_count": len(ids_found),
    "collector_ids_sample": sorted(ids_found)[:20],
    "element_info": info,
}
