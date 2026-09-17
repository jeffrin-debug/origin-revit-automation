# probe_newrooms2.py
# ============================================================
# STAGE 0 PROBE 2 - the architecture gate.
#
# Can we discover every enclosed region on a BACKGROUND document (no active view)?
# Everything here is rolled back - no model is changed, nothing is saved.
#
# Three rungs, tried in order per level, each inside its own rolled-back SubTransaction:
#   a) nd.Create.NewRooms2(level, phase)              - as-is
#   b) temp ViewPlan.Create(...) for the level, then NewRooms2 again
#   c) reported only here: seeded NewRoom(level, UV) via flood-fill (built later if needed)
#
# NewRooms2 places a room in every enclosed region that does NOT already contain one, so the
# count it returns IS missing_region_count - the number of rooms the env is short. On a model
# with zero rooms that count is the total number of enclosed regions.
#
# GO  = some rung returns a plausible region count on a background doc.
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


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

CANDIDATES = [
    os.path.join(_paths["INPUT_DIR"], "B1-a.rvt"),
    os.path.join(_paths["INPUT_DIR"], "409_Testing.rvt"),
    os.path.join(_paths["INPUT_DIR"], "Project8.rvt"),
    os.path.join(_paths["INPUT_DIR"], "12M_FR_11.rvt"),
]

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

res = {"picked": None, "phases": [], "levels": [], "errors": [], "verdict": None}


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        try:
            return eid.IntegerValue
        except Exception:
            return -1


def room_ids(d):
    out = set()
    try:
        for r in (FilteredElementCollector(d).OfCategory(BuiltInCategory.OST_Rooms)
                  .WhereElementIsNotElementType()):
            out.add(eid_value(r.Id))
    except Exception:
        pass
    return out


def pick_phase(d, level):
    """Rooms must live in a phase where the bounding walls exist. Take the most common
    CreatedPhaseId over that level's room-bounding walls; fall back to the last phase.
    The ActiveView-based lookup is unavailable on a background document."""
    counts = {}
    try:
        for w in FilteredElementCollector(d).OfClass(Wall).WhereElementIsNotElementType():
            try:
                if eid_value(w.LevelId) != eid_value(level.Id):
                    continue
                rb = w.get_Parameter(BuiltInParameter.WALL_ATTR_ROOM_BOUNDING)
                if rb is not None and rb.AsInteger() != 1:
                    continue
                pid = eid_value(w.CreatedPhaseId)
                counts[pid] = counts.get(pid, 0) + 1
            except Exception:
                continue
    except Exception:
        pass
    if counts:
        best = sorted(counts.items(), key=lambda kv: -kv[1])[0][0]
        try:
            ph = d.GetElement(ElementId(best))
            if ph is not None:
                return ph, "wall CreatedPhaseId (n={})".format(counts[best])
        except Exception:
            pass
    try:
        phs = d.Phases
        return phs.get_Item(phs.Size - 1), "last phase"
    except Exception:
        return None, "none"


def floor_plan_vft_id(d):
    for vft in FilteredElementCollector(d).OfClass(ViewFamilyType):
        try:
            if vft.ViewFamily == ViewFamily.FloorPlan:
                return vft.Id
        except Exception:
            continue
    return None


open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

pick = None
for p in CANDIDATES:
    if os.path.exists(p) and os.path.splitext(os.path.basename(p))[0] not in open_titles:
        pick = p
        break

if pick is None:
    res["verdict"] = "NO CANDIDATE - missing or already open in the UI"
    OUT = res
else:
    res["picked"] = pick
    nd = None
    t = None
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(pick)
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(mp, oo)

        try:
            phs = nd.Phases
            for i in range(phs.Size):
                res["phases"].append(phs.get_Item(i).Name)
        except Exception:
            res["errors"].append("phase enumeration: " + traceback.format_exc())

        vft_id = floor_plan_vft_id(nd)
        res["floor_plan_vft_found"] = vft_id is not None

        existing_plans = {}
        for vp in FilteredElementCollector(nd).OfClass(ViewPlan):
            try:
                if vp.IsTemplate:
                    continue
                gl = vp.GenLevel
                if gl is not None:
                    existing_plans[eid_value(gl.Id)] = vp.Name
            except Exception:
                continue

        before_all = room_ids(nd)
        res["rooms_before_total"] = len(before_all)

        t = Transaction(nd, "ORIGIN probe NewRooms2")
        fho = t.GetFailureHandlingOptions()
        try:
            fho.SetForcedModalHandling(False)
            fho.SetClearAfterRollback(True)
            t.SetFailureHandlingOptions(fho)
        except Exception:
            pass
        t.Start()

        levels = list(FilteredElementCollector(nd).OfClass(Level)
                      .WhereElementIsNotElementType())
        levels.sort(key=lambda lv: lv.Elevation)

        for lv in levels:
            lid = eid_value(lv.Id)
            row = {
                "level": lv.Name,
                "level_id": lid,
                "elev_mm": round(lv.Elevation * 304.8, 1),
                "has_plan_view": lid in existing_plans,
                "rooms_existing_on_level": 0,
                "rung_a_newrooms2": None,
                "rung_b_newrooms2_with_temp_plan": None,
            }
            try:
                row["rooms_existing_on_level"] = len(
                    [r for r in (FilteredElementCollector(nd)
                                 .OfCategory(BuiltInCategory.OST_Rooms)
                                 .WhereElementIsNotElementType())
                     if eid_value(r.LevelId) == lid])
            except Exception:
                pass

            ph, ph_why = pick_phase(nd, lv)
            row["phase"] = ph.Name if ph is not None else None
            row["phase_source"] = ph_why

            # ---- rung a: NewRooms2 as-is, rolled back -------------------------------
            st = SubTransaction(nd)
            try:
                st.Start()
                t0 = time.time()
                ids = None
                try:
                    ids = nd.Create.NewRooms2(lv, ph) if ph is not None else nd.Create.NewRooms2(lv)
                except Exception:
                    # Some builds expose only the single-argument overload.
                    ids = nd.Create.NewRooms2(lv)
                n = len(list(ids)) if ids is not None else 0
                row["rung_a_newrooms2"] = {"ok": True, "created": n,
                                           "sec": round(time.time() - t0, 2)}
            except Exception:
                row["rung_a_newrooms2"] = {"ok": False, "error": traceback.format_exc()}
            finally:
                try:
                    st.RollBack()
                except Exception:
                    pass

            # ---- rung b: only if rung a produced nothing ----------------------------
            a = row["rung_a_newrooms2"] or {}
            if (not a.get("ok")) or a.get("created", 0) == 0:
                st2 = SubTransaction(nd)
                try:
                    st2.Start()
                    made_view = None
                    if not row["has_plan_view"] and vft_id is not None:
                        made_view = ViewPlan.Create(nd, vft_id, lv.Id)
                    t0 = time.time()
                    ids = None
                    try:
                        ids = nd.Create.NewRooms2(lv, ph) if ph is not None else nd.Create.NewRooms2(lv)
                    except Exception:
                        ids = nd.Create.NewRooms2(lv)
                    n = len(list(ids)) if ids is not None else 0
                    row["rung_b_newrooms2_with_temp_plan"] = {
                        "ok": True, "created": n, "made_temp_view": made_view is not None,
                        "sec": round(time.time() - t0, 2)}
                except Exception:
                    row["rung_b_newrooms2_with_temp_plan"] = {
                        "ok": False, "error": traceback.format_exc()}
                finally:
                    try:
                        st2.RollBack()
                    except Exception:
                        pass

            res["levels"].append(row)

    except Exception:
        res["errors"].append(traceback.format_exc())
    finally:
        # Nothing may survive this probe.
        try:
            if t is not None and t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            res["errors"].append("rollback: " + traceback.format_exc())
        try:
            if nd is not None:
                res["rooms_after_rollback"] = len(room_ids(nd))
                nd.Close(False)
        except Exception:
            res["errors"].append("close: " + traceback.format_exc())
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

    best = 0
    for r in res["levels"]:
        for k in ("rung_a_newrooms2", "rung_b_newrooms2_with_temp_plan"):
            v = r.get(k) or {}
            if v.get("ok"):
                best = max(best, v.get("created", 0))
    res["max_regions_found"] = best
    res["verdict"] = ("GO - region discovery works on a background document"
                      if best > 0 else
                      "NO-GO - no rung found regions; fall back to UI-document mode")
    OUT = res
