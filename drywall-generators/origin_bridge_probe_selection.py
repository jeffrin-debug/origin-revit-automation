# origin_bridge_probe_selection.py - run via the ORIGIN Bridge. READ-ONLY - makes no changes.
# Reports everything about whatever is CURRENTLY SELECTED in Revit: category, family/type,
# Mark/Comments (so we can tell if it's one of our generated DP-* boards vs a raw Wall/other
# element), real solid volume, and bbox - so we can diagnose a "no drywall" report without
# guessing or touching the model.
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


def get_solids(e):
    solids = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return solids
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                solids.append(g)
    except Exception:
        pass
    return solids


ids = list(uidoc.Selection.GetElementIds())
out = {"selection_count": len(ids), "elements": []}

for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    info = {"element_id": eid.Value if hasattr(eid, "Value") else eid.IntegerValue}
    try:
        info["category"] = e.Category.Name if e.Category else None
    except Exception:
        info["category"] = None
    try:
        info["class"] = e.GetType().Name
    except Exception:
        info["class"] = None
    try:
        info["name"] = e.Name
    except Exception:
        info["name"] = None
    try:
        c = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        info["comments"] = c.AsString() if c else None
    except Exception:
        info["comments"] = None
    try:
        m = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        info["mark"] = m.AsString() if m else None
    except Exception:
        info["mark"] = None
    try:
        mat_ids = e.GetMaterialIds(False)
        mat_names = []
        for mid in mat_ids:
            mat = doc.GetElement(mid)
            mat_names.append(mat.Name if mat else str(mid))
        info["materials"] = mat_names
    except Exception as ex:
        info["materials"] = "ERR: {}".format(ex)
    solids = get_solids(e)
    info["solid_count"] = len(solids)
    info["total_volume_cf"] = round(sum(s.Volume for s in solids), 4)
    try:
        bb = e.get_BoundingBox(None)
        if bb:
            info["bbox_ft"] = {
                "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)],
            }
    except Exception:
        pass
    out["elements"].append(info)

OUT = out
