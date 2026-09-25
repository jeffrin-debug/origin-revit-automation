# diag_hide_check.py - did the panels-only view actually hide the framing?
#
# FilteredElementCollector(doc, viewId) does not reliably exclude per-element hidden items, so
# ask each element directly with Element.IsHidden(view). That is the authoritative answer.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

VIEW_NAME = "ORIGIN Panels Only"
doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "view": VIEW_NAME}


def mark(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


view = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    try:
        if (not v.IsTemplate) and v.Name == VIEW_NAME:
            view = v
            break
    except Exception:
        continue

if view is None:
    res["error"] = "view not found"
else:
    res["view_id"] = view.Id.IntegerValue if hasattr(view.Id, "IntegerValue") else view.Id.Value
    tot = {"ST": [0, 0], "DP": [0, 0], "SC": [0, 0], "other": [0, 0]}   # [hidden, visible]
    samples = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        m = mark(ds)
        k = "ST" if m.startswith("ST-") else "DP" if m.startswith("DP-") else "SC" if m.startswith("SC-") else "other"
        try:
            h = ds.IsHidden(view)
        except Exception:
            h = None
        if h is True:
            tot[k][0] += 1
        else:
            tot[k][1] += 1
            if k == "ST" and len(samples) < 6:
                samples.append({"mark": m, "id": ds.Id.IntegerValue if hasattr(ds.Id, "IntegerValue") else ds.Id.Value,
                                "IsHidden": h})
    res["by_prefix_hidden_visible"] = tot
    res["framing_still_visible_samples"] = samples

    # Is the whole Generic Models category on or off in this view?
    try:
        cat = Category.GetCategory(doc, BuiltInCategory.OST_GenericModel)
        res["generic_models_category_hidden"] = view.GetCategoryHidden(cat.Id)
    except Exception as ex:
        res["generic_models_category_hidden"] = "err: %s" % ex
    try:
        res["view_discipline"] = str(view.Discipline)
        res["detail_level"] = str(view.DetailLevel)
        res["has_section_box"] = view.IsSectionBoxActive
    except Exception:
        pass

OUT = res
