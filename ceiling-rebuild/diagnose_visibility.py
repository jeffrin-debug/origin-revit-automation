# diagnose_visibility.py
# ============================================================
# Answers one question about the CURRENT UI document: are the ceilings missing, or just not
# drawn in this view? Read-only, no transaction.
#
# Compares the model-wide ceiling list against what a collector scoped to the active view
# returns. An element present in the model but absent from the view-scoped collector is being
# filtered out by the view (view range / cut plane / category visibility / hidden), not missing.
# ============================================================

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


view = doc.ActiveView
res = {"doc": doc.Title, "active_view": view.Name, "view_type": str(view.ViewType)}

# --- what the view does to ceilings -------------------------------------------------
try:
    res["ceilings_category_hidden_in_view"] = view.GetCategoryHidden(
        ElementId(int(BuiltInCategory.OST_Ceilings)))
except Exception as ex:
    res["ceilings_category_hidden_in_view"] = "unknown ({})".format(ex)

try:
    vr = view.GetViewRange()
    def _pl(name, plane):
        lid = vr.GetLevelId(plane)
        lv = doc.GetElement(lid)
        base = lv.Elevation if lv is not None else 0.0
        off = vr.GetOffset(plane)
        return {"level": lv.Name if lv is not None else str(eid_value(lid)),
                "offset_mm": round(off * 304.8, 1),
                "abs_mm": round((base + off) * 304.8, 1)}
    res["view_range"] = {
        "top": _pl("top", PlanViewPlane.TopClipPlane),
        "cut": _pl("cut", PlanViewPlane.CutPlane),
        "bottom": _pl("bottom", PlanViewPlane.BottomClipPlane),
        "view_depth": _pl("depth", PlanViewPlane.ViewDepthPlane),
    }
except Exception as ex:
    res["view_range"] = "not a plan view or unavailable ({})".format(ex)

# --- model-wide vs view-scoped ------------------------------------------------------
model_ceilings = {}
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    row = {"id": eid_value(c.Id)}
    try:
        row["category"] = c.Category.Name
    except Exception:
        row["category"] = "?"
    try:
        p = c.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)
        row["area_sf"] = round(p.AsDouble(), 2) if p else None
    except Exception:
        row["area_sf"] = None
    try:
        bb = c.get_BoundingBox(None)
        row["bottom_mm"] = round(bb.Min.Z * 304.8, 1) if bb else None
        row["top_mm"] = round(bb.Max.Z * 304.8, 1) if bb else None
    except Exception:
        row["bottom_mm"] = None
    try:
        row["level"] = doc.GetElement(c.LevelId).Name
    except Exception:
        row["level"] = "?"
    try:
        row["hidden_by_user"] = c.IsHidden(view)
    except Exception:
        row["hidden_by_user"] = None
    model_ceilings[row["id"]] = row

in_view = set()
try:
    for c in (FilteredElementCollector(doc, view.Id).OfClass(Ceiling)
              .WhereElementIsNotElementType()):
        in_view.add(eid_value(c.Id))
except Exception as ex:
    res["view_collector_error"] = str(ex)

for cid, row in model_ceilings.items():
    row["visible_in_active_view"] = cid in in_view

res["ceiling_count_in_model"] = len(model_ceilings)
res["ceiling_count_in_active_view"] = len(in_view)
res["ceilings"] = sorted(model_ceilings.values(), key=lambda r: -(r.get("area_sf") or 0))

# --- levels, and anything else sitting at the new ceiling elevation ------------------
levels = []
for lv in FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType():
    levels.append({"name": lv.Name, "elev_mm": round(lv.Elevation * 304.8, 1)})
levels.sort(key=lambda r: r["elev_mm"])
res["levels"] = levels

floors = []
for fl in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
    try:
        bb = fl.get_BoundingBox(None)
        floors.append({"id": eid_value(fl.Id),
                       "bottom_mm": round(bb.Min.Z * 304.8, 1) if bb else None,
                       "top_mm": round(bb.Max.Z * 304.8, 1) if bb else None})
    except Exception:
        continue
res["floors"] = floors

res["reflected_ceiling_plans"] = [v.Name for v in FilteredElementCollector(doc).OfClass(ViewPlan)
                                  if (not v.IsTemplate) and str(v.ViewType) == "CeilingPlan"]

OUT = res
