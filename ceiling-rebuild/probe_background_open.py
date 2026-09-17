# probe_background_open.py
# ============================================================
# STAGE 0 PROBE 1 - can we open an env as a BACKGROUND document and read it?
#
# Run through the ceiling bridge with "transaction": false. Opens the first candidate .rvt
# that is not already open in the UI, reports what the document looks like from the API with
# no active view, then closes it without saving. Nothing is modified.
#
# GO  = the file opens, ActiveView is None, level/wall/ceiling/room counts come back, closes clean.
# NO-GO = fall back to UI-document mode (OpenAndActivateDocument, one file per bridge tick).
# ============================================================

import clr
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

CANDIDATES = [
    r"C:\Users\Origoncad\Downloads\B1-a.rvt",
    r"C:\Users\Origoncad\Downloads\409_Testing.rvt",
    r"C:\Users\Origoncad\Downloads\Project8.rvt",
    r"C:\Users\Origoncad\Downloads\12M_FR_11.rvt",
]

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

res = {
    "host_revit": None,
    "open_documents": [],
    "picked": None,
    "basic_file_info": {},
    "steps": [],
    "doc": {},
    "verdict": None,
}


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        try:
            return eid.IntegerValue
        except Exception:
            return -1


def step(name, fn):
    """Run one probe step, recording ok/error/duration instead of letting it kill the run."""
    t0 = time.time()
    try:
        v = fn()
        res["steps"].append({"step": name, "ok": True, "sec": round(time.time() - t0, 2)})
        return v
    except Exception:
        res["steps"].append({"step": name, "ok": False, "sec": round(time.time() - t0, 2),
                             "error": traceback.format_exc()})
        return None


try:
    res["host_revit"] = "{}.{}".format(app.VersionNumber, app.SubVersionNumber)
except Exception:
    try:
        res["host_revit"] = str(app.VersionNumber)
    except Exception:
        pass

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass
res["open_documents"] = open_titles

# A file already open in the UI cannot be opened again as a background document, so skip those.
pick = None
for p in CANDIDATES:
    if not os.path.exists(p):
        continue
    stem = os.path.splitext(os.path.basename(p))[0]
    if stem in open_titles:
        continue
    pick = p
    break

if pick is None:
    res["verdict"] = "NO CANDIDATE - every candidate is missing or already open in the UI"
    OUT = res
else:
    res["picked"] = pick

    # Zero-cost pre-open facts: catches a workshared file or one saved by a newer Revit.
    def _bfi():
        bfi = BasicFileInfo.Extract(pick)
        res["basic_file_info"] = {
            "saved_in_version": bfi.SavedInVersion,
            "is_workshared": bfi.IsWorkshared,
            "is_central": bfi.IsCentral,
            "is_local": bfi.IsLocal,
        }
    step("BasicFileInfo.Extract", _bfi)

    # Dynamo holds a transaction open across a graph run; OpenDocumentFile throws if any
    # transaction is open anywhere in the session.
    step("ForceCloseTransaction", lambda: TransactionManager.Instance.ForceCloseTransaction())

    def _open():
        mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(pick)
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        try:
            oo.AllowOpeningLocalByWrongUser = True
        except Exception:
            pass
        return app.OpenDocumentFile(mp, oo)

    nd = step("OpenDocumentFile", _open)

    if nd is None:
        res["verdict"] = "NO-GO - background open failed, see steps[].error"
        OUT = res
    else:
        def _read():
            d = res["doc"]
            d["title"] = nd.Title
            d["path"] = nd.PathName
            d["is_family"] = nd.IsFamilyDocument
            d["is_workshared"] = nd.IsWorkshared
            try:
                d["active_view"] = nd.ActiveView.Name
            except Exception:
                d["active_view"] = None
            d["active_view_is_none"] = d.get("active_view") is None

            levels = []
            for lv in FilteredElementCollector(nd).OfClass(Level).WhereElementIsNotElementType():
                levels.append({
                    "id": eid_value(lv.Id),
                    "name": lv.Name,
                    "elev_ft": round(lv.Elevation, 4),
                    "elev_mm": round(lv.Elevation * 304.8, 1),
                })
            levels.sort(key=lambda x: x["elev_ft"])
            d["levels"] = levels

            # OfClass(Ceiling) also returns Roof Soffits-category elements - split them here,
            # because that distinction drives every delete/keep decision later.
            ceilings = []
            for c in FilteredElementCollector(nd).OfClass(Ceiling).WhereElementIsNotElementType():
                row = {"id": eid_value(c.Id)}
                try:
                    row["category"] = c.Category.Name
                except Exception:
                    row["category"] = "?"
                try:
                    row["type"] = nd.GetElement(c.GetTypeId()).Name
                except Exception:
                    row["type"] = "?"
                try:
                    row["level_id"] = eid_value(c.LevelId)
                except Exception:
                    row["level_id"] = -1
                try:
                    a = c.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)
                    row["area_sf"] = round(a.AsDouble(), 2) if a else None
                except Exception:
                    row["area_sf"] = None
                try:
                    h = c.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM)
                    row["height_offset_ft"] = round(h.AsDouble(), 4) if h else None
                    row["height_offset_mm"] = round(h.AsDouble() * 304.8, 1) if h else None
                except Exception:
                    row["height_offset_ft"] = None
                ceilings.append(row)
            d["ceilings"] = ceilings

            rooms = []
            for r in (FilteredElementCollector(nd).OfCategory(BuiltInCategory.OST_Rooms)
                      .WhereElementIsNotElementType()):
                row = {"id": eid_value(r.Id)}
                try:
                    row["name"] = r.Name
                except Exception:
                    row["name"] = "?"
                try:
                    row["area_sf"] = round(r.Area, 2)
                except Exception:
                    row["area_sf"] = 0.0
                try:
                    row["placed"] = r.Location is not None
                except Exception:
                    row["placed"] = False
                try:
                    row["level_id"] = eid_value(r.LevelId)
                except Exception:
                    row["level_id"] = -1
                rooms.append(row)
            d["rooms"] = rooms
            d["room_count"] = len(rooms)
            d["enclosed_room_count"] = len([r for r in rooms if r.get("area_sf", 0) > 0.0])

            def _count_cls(cls):
                try:
                    return (FilteredElementCollector(nd).OfClass(cls)
                            .WhereElementIsNotElementType().GetElementCount())
                except Exception:
                    return -1

            def _count_cat(bic):
                try:
                    return (FilteredElementCollector(nd).OfCategory(bic)
                            .WhereElementIsNotElementType().GetElementCount())
                except Exception:
                    return -1

            d["counts"] = {
                "walls": _count_cls(Wall),
                "floors": _count_cls(Floor),
                "room_separation_lines": _count_cat(BuiltInCategory.OST_RoomSeparationLines),
                "revit_links": _count_cls(RevitLinkInstance),
                "generic_models": _count_cat(BuiltInCategory.OST_GenericModel),
                "direct_shapes": _count_cls(DirectShape),
                "lighting_fixtures": _count_cat(BuiltInCategory.OST_LightingFixtures),
                "air_terminals": _count_cat(BuiltInCategory.OST_DuctTerminal),
            }

            # NewRooms2 may need a plan view for the level - record which levels already have one.
            plans = {}
            for vp in FilteredElementCollector(nd).OfClass(ViewPlan):
                try:
                    if vp.IsTemplate:
                        continue
                    gl = vp.GenLevel
                    if gl is not None:
                        plans[eid_value(gl.Id)] = vp.Name
                except Exception:
                    continue
            d["levels_with_plan_view"] = plans
            d["levels_missing_plan_view"] = [lv["name"] for lv in levels
                                             if lv["id"] not in plans]

            # Room boundaries are computed at this height, not at the level - a non-zero value
            # silently changes the room topology relative to what the plan looks like.
            ch = {}
            for lv in FilteredElementCollector(nd).OfClass(Level).WhereElementIsNotElementType():
                try:
                    p = lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
                    ch[lv.Name] = round(p.AsDouble() * 304.8, 1) if p else None
                except Exception:
                    ch[lv.Name] = None
            d["room_computation_height_mm"] = ch

        step("read background document", _read)
        step("Close(False)", lambda: nd.Close(False))
        step("ForceCloseTransaction (after)",
             lambda: TransactionManager.Instance.ForceCloseTransaction())

        ok = all(s["ok"] for s in res["steps"])
        res["verdict"] = ("GO - background documents work" if ok
                          else "PARTIAL - see steps[].error")
        OUT = res
