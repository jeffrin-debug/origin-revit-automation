# origin_bridge_probe_view_categories.py - READ-ONLY.
# List every model category with instances in this document, its element count, and whether it is
# currently hidden in the ORIGIN Assembly view. Tells us exactly what the isolation rule is
# suppressing so the keep/hide split can be decided from the real model, not from guesswork.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

VIEW_NAME = "ORIGIN Assembly"

view = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    try:
        if (not v.IsTemplate) and v.Name == VIEW_NAME:
            view = v
            break
    except Exception:
        pass

cats = {}
for e in FilteredElementCollector(doc).WhereElementIsNotElementType():
    try:
        cat = e.Category
        if cat is None or cat.CategoryType != CategoryType.Model:
            continue
        cid = cat.Id.IntegerValue if hasattr(cat.Id, "IntegerValue") else cat.Id.Value
    except Exception:
        continue
    rec = cats.get(cid)
    if rec is None:
        rec = {"name": cat.Name, "id": cid, "count": 0, "cat_hidden": None,
               "elems_hidden": 0, "elems_visible": 0, "sample_types": {}}
        cats[cid] = rec
    rec["count"] += 1
    # what type/family is it - helps identify "LW Concrete on Metal Deck" style floors
    try:
        tid = e.GetTypeId()
        t = doc.GetElement(tid) if tid is not None else None
        tn = None
        if t is not None:
            p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            tn = p.AsString() if p else None
            if not tn:
                tn = getattr(t, "Name", None)
        if tn:
            rec["sample_types"][tn] = rec["sample_types"].get(tn, 0) + 1
    except Exception:
        pass
    if view is not None:
        try:
            if e.IsHidden(view):
                rec["elems_hidden"] += 1
            else:
                rec["elems_visible"] += 1
        except Exception:
            pass

if view is not None:
    for cid, rec in cats.items():
        try:
            rec["cat_hidden"] = view.GetCategoryHidden(ElementId(cid))
        except Exception:
            rec["cat_hidden"] = "err"

rows = sorted(cats.values(), key=lambda r: -r["count"])
for r in rows:
    # trim the type map so the result json stays readable
    st = sorted(r["sample_types"].items(), key=lambda kv: -kv[1])[:4]
    r["sample_types"] = ["{} x{}".format(k, n) for (k, n) in st]

OUT = {
    "view_found": view is not None,
    "view_name": VIEW_NAME,
    "model_categories_present": len(rows),
    "categories": rows,
}
