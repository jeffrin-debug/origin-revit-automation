# panels_only_view.py
# ============================================================
# A 3D view containing NOTHING BUT THE DRYWALL PANELS, for OBJ/USD export.
#
# WHY THIS USES VIEW FILTERS AND NOT HideElements
#
# The first version of this hid the framing by element id. That works for exactly as long as
# nobody re-runs a generator: every ORIGIN run deletes its previous output and creates fresh
# DirectShapes with NEW ids, so the pinned hide list goes stale instantly and the view silently
# shows everything again. Observed live 2026-09-22 - the view was built against 502 panels /
# 469 framing, and twenty minutes later the model held 635 / 626 with not one element hidden.
#
# A ParameterFilterElement is a RULE, not a list. "Mark does not begin with DP-" keeps applying
# to whatever exists at the moment the view is drawn, so the view survives any number of
# re-runs. That is the only version of this worth having.
#
#   shown    Mark begins with DP-   drywall panels, walls and ceilings alike
#   hidden   everything else        ST-* framing, SC-* screws, untagged geometry
#   hidden   CORNERINFILL=1         stud-shaped corner patches, unless INCLUDE_CORNER_INFILL
#
# Nothing is created, moved or deleted in the model - this only configures a view.
# ============================================================

import clr
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List as NetList

VIEW_NAME = "ORIGIN Panels Only"
FILTER_NONPANEL = "ORIGIN - not a drywall panel"
FILTER_INFILL = "ORIGIN - corner infill patch"
INCLUDE_CORNER_INFILL = False

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "view": VIEW_NAME, "include_corner_infill": INCLUDE_CORNER_INFILL}
t0 = time.time()


def _rule(factory_name, param_bip, value):
    """ParameterFilterRuleFactory changed signature across versions - some take a trailing
    caseSensitive bool, some do not. Try both rather than pin a version."""
    f = getattr(ParameterFilterRuleFactory, factory_name)
    pid = ElementId(param_bip)
    try:
        return f(pid, value)
    except Exception:
        return f(pid, value, False)


def _ensure_filter(name, rules, cat_ids):
    for fe in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if fe.Name == name:
            try:
                fe.SetElementFilter(LogicalAndFilter([ElementParameterFilter(r) for r in rules])
                                    if len(rules) > 1 else ElementParameterFilter(rules[0]))
            except Exception:
                pass
            return fe, False
    ef = (LogicalAndFilter([ElementParameterFilter(r) for r in rules])
          if len(rules) > 1 else ElementParameterFilter(rules[0]))
    return ParameterFilterElement.Create(doc, name, cat_ids, ef), True


try:
    TransactionManager.Instance.ForceCloseTransaction()
    t = Transaction(doc, "ORIGIN panels-only export view")
    t.Start()
    try:
        # --- the view -----------------------------------------------------------------
        view = None
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if (not v.IsTemplate) and v.Name == VIEW_NAME:
                    view = v
                    break
            except Exception:
                continue
        created = False
        if view is None:
            vft = None
            for ft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                try:
                    if ft.ViewFamily == ViewFamily.ThreeDimensional:
                        vft = ft
                        break
                except Exception:
                    continue
            if vft is None:
                raise Exception("no 3D ViewFamilyType in this document")
            view = View3D.CreateIsometric(doc, vft.Id)
            view.Name = VIEW_NAME
            created = True
        res["view_created"] = created

        # --- hide the host model categories ------------------------------------------
        for bic in (BuiltInCategory.OST_Walls, BuiltInCategory.OST_Doors,
                    BuiltInCategory.OST_Windows, BuiltInCategory.OST_Floors,
                    BuiltInCategory.OST_Ceilings, BuiltInCategory.OST_Roofs,
                    BuiltInCategory.OST_StructuralColumns,
                    BuiltInCategory.OST_StructuralFraming,
                    BuiltInCategory.OST_Rooms, BuiltInCategory.OST_Levels,
                    BuiltInCategory.OST_Grids, BuiltInCategory.OST_Lines,
                    BuiltInCategory.OST_RoomSeparationLines):
            try:
                cat = Category.GetCategory(doc, bic)
                if cat is not None and view.CanCategoryBeHidden(cat.Id):
                    view.SetCategoryHidden(cat.Id, True)
            except Exception:
                continue

        # --- rule-based filters over Generic Models (where DirectShapes live) ---------
        cat_ids = NetList[ElementId]()
        cat_ids.Add(ElementId(BuiltInCategory.OST_GenericModel))

        made = []
        # 1. anything whose Mark does not start with DP- is not a panel
        f1, new1 = _ensure_filter(
            FILTER_NONPANEL,
            [_rule("CreateNotBeginsWithRule", BuiltInParameter.ALL_MODEL_MARK, "DP-")],
            cat_ids)
        made.append((f1, FILTER_NONPANEL, new1))

        # 2. corner infill patches, tagged in their Comments by the wall generator
        f2 = None
        if not INCLUDE_CORNER_INFILL:
            f2, new2 = _ensure_filter(
                FILTER_INFILL,
                [_rule("CreateContainsRule", BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS,
                       "CORNERINFILL=1")],
                cat_ids)
            made.append((f2, FILTER_INFILL, new2))

        applied = []
        for (fe, nm, isnew) in made:
            try:
                if fe.Id not in list(view.GetFilters()):
                    view.AddFilter(fe.Id)
                view.SetFilterVisibility(fe.Id, False)
                applied.append({"filter": nm, "created": isnew, "visible": False})
            except Exception as ex:
                applied.append({"filter": nm, "error": str(ex)})
        res["filters"] = applied

        # If an older run left per-element hides behind, clear them - the filters do the work
        # now and a stale hide list would only confuse the next person.
        try:
            stale = NetList[ElementId]()
            n = 0
            for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
                try:
                    if ds.IsHidden(view):
                        stale.Add(ds.Id)
                        n += 1
                except Exception:
                    continue
            if n:
                view.UnhideElements(stale)
            res["stale_element_hides_cleared"] = n
        except Exception as ex:
            res["unhide_error"] = str(ex)

        t.Commit()
    except Exception:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        raise

    # --- verify by asking the VIEW what it will draw ----------------------------------
    # A view filter does not set Element.IsHidden, so that cannot be used here. A collector
    # scoped to the view does honour filters, which is the thing actually being checked.
    shown = {"panels": 0, "framing": 0, "infill": 0, "screws": 0, "other": 0}
    leaks = []
    for ds in FilteredElementCollector(doc, view.Id).OfClass(DirectShape):
        try:
            pm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = (pm.AsString() or "") if pm else ""
            pc = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            cs = (pc.AsString() or "") if pc else ""
        except Exception:
            m, cs = "", ""
        if "CORNERINFILL=1" in cs:
            shown["infill"] += 1
            leaks.append(m or "?")
        elif m.startswith("DP-"):
            shown["panels"] += 1
        elif m.startswith("ST-"):
            shown["framing"] += 1
            leaks.append(m)
        elif m.startswith("SC-"):
            shown["screws"] += 1
            leaks.append(m)
        else:
            shown["other"] += 1
            leaks.append(m or "<no mark>")
    total = {"panels": 0, "framing": 0, "infill": 0}
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            pm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = (pm.AsString() or "") if pm else ""
            pc = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            cs = (pc.AsString() or "") if pc else ""
        except Exception:
            m, cs = "", ""
        if "CORNERINFILL=1" in cs:
            total["infill"] += 1
        elif m.startswith("DP-"):
            total["panels"] += 1
        elif m.startswith("ST-"):
            total["framing"] += 1
    res["in_model"] = total
    res["visible_in_view"] = shown
    res["leaked"] = sorted(set(leaks))[:12]
    res["clean"] = (shown["framing"] == 0 and shown["screws"] == 0
                    and shown["other"] == 0
                    and (shown["infill"] == 0 or INCLUDE_CORNER_INFILL))
    res["status"] = "ok"
    res["note"] = ("view '{}' uses RULE-based filters, so it stays correct after any "
                   "generator re-run. Export that view to OBJ.".format(VIEW_NAME))
    OUT = res
except Exception:
    res["status"] = "error"
    res["error"] = traceback.format_exc()[-1500:]
    OUT = res
finally:
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

res["sec"] = round(time.time() - t0, 2)
