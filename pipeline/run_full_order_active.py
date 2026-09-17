# run_full_order_active.py
# ============================================================
# Run the COMPLETE pipeline order on the document open in the Revit UI:
#
#     purge   remove ORIGIN output from any earlier pass in this session
#     stage 1 origin_ceiling_rebuild_core  - the per-room / split ceiling rebuild
#     stage 2 stage2_panels                - the five drywall generators
#
# Stage 1 is the step that had never been run on these live envs - only stage 2 had. It is
# wrapped in its own Transaction and COMMITTED ONLY IF it reports ok, exactly as pipeline_run.py
# does, so a failed verification rolls the ceilings back instead of letting stage 2 panel over
# a bad rebuild.
#
# Nothing is saved. Close with Don't Save to discard.
# ============================================================

import clr
import json
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

ROOT = _paths["PIPELINE_ROOT"]
CEILING_ROOT = _paths["CEILING_ROOT"]

ORIGIN_APP_IDS = ("ORIGIN_ASSEMBLY_V4", "ORIGIN_CEILING_V1", "ORIGIN_BEAM_V1",
                  "ORIGIN_COLUMN_V1", "ORIGIN_BEAMCOL_V1")

doc = DocumentManager.Instance.CurrentDBDocument
out = {"doc": doc.Title, "saved": False,
       "note": "nothing saved - close with Don't Save to discard"}


def count_rooms(doc):
    placed = 0
    try:
        for r in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                  .WhereElementIsNotElementType()):
            try:
                if r.Area and r.Area > 1.0:
                    placed += 1
            except Exception:
                pass
    except Exception:
        return None
    return placed


def count_ceilings(doc):
    try:
        return len(list(FilteredElementCollector(doc).OfClass(Ceiling)
                        .WhereElementIsNotElementType()))
    except Exception:
        return None


def purge_origin(doc):
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    ids = List[ElementId]()
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
        except Exception:
            continue
        if any(c.startswith(a + " |") for a in ORIGIN_APP_IDS):
            ids.Add(ds.Id)
    for e in (FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_GenericModel)
              .WhereElementIsNotElementType()):
        try:
            p = e.LookupParameter("Generated_By")
            if p and p.AsString() in ORIGIN_APP_IDS:
                ids.Add(e.Id)
        except Exception:
            pass
    n = ids.Count
    if n:
        t = Transaction(doc, "ORIGIN purge before full-order run")
        t.Start()
        try:
            doc.Delete(ids)
            t.Commit()
        except Exception:
            t.RollBack()
            return -1
    return n


out["before"] = {"rooms_placed": count_rooms(doc), "ceilings": count_ceilings(doc),
                 "walls": len(list(FilteredElementCollector(doc).OfClass(Wall)
                                   .WhereElementIsNotElementType()))}

# ---- purge ------------------------------------------------------------------------------------
try:
    out["purged"] = purge_origin(doc)
except Exception:
    out["purge_error"] = traceback.format_exc()[-600:]

# ---- stage 1 : the split / per-room ceiling rebuild ---------------------------------------------
t0 = time.time()
core = {"__name__": "origin_ceiling_rebuild_core"}
core_path = os.path.join(CEILING_ROOT, "origin_ceiling_rebuild_core.py")
try:
    core["__file__"] = core_path
    exec(compile(open(core_path).read(), core_path, "exec"), core)
except Exception:
    out["stage1_load_error"] = traceback.format_exc()[-900:]

if "run_on_document" in core:
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    t = Transaction(doc, "ORIGIN rebuild per-room ceilings")
    try:
        fho = t.GetFailureHandlingOptions()
        fho.SetForcedModalHandling(False)
        fho.SetClearAfterRollback(True)
        t.SetFailureHandlingOptions(fho)
    except Exception:
        pass
    t.Start()
    try:
        rep = core["run_on_document"](doc, delete_unmatched=True)
        slim = {}
        for k, v in rep.items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                slim[k] = v
            elif k in ("fail_reasons", "warnings", "notes"):
                slim[k] = (v[:8] if isinstance(v, list) else v)
        out["stage1"] = slim
        if rep.get("ok"):
            t.Commit()
            out["stage1_result"] = "committed"
        else:
            t.RollBack()
            out["stage1_result"] = "ROLLED BACK - failed verification"
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        out["stage1_result"] = "exception - rolled back"
        out["stage1_error"] = traceback.format_exc()[-900:]
out["stage1_seconds"] = round(time.time() - t0, 1)
out["after_stage1"] = {"rooms_placed": count_rooms(doc), "ceilings": count_ceilings(doc)}

# ---- stage 2 : panels ----------------------------------------------------------------------------
t1 = time.time()
try:
    TransactionManager.Instance.ForceCloseTransaction()
except Exception:
    pass
s2_path = os.path.join(ROOT, "stage2_panels.py")
stage2 = {"__name__": "stage2_panels"}
try:
    stage2["__file__"] = s2_path
    exec(compile(open(s2_path).read(), s2_path, "exec"), stage2)
    rep2 = stage2["run_on_document"](doc)
    gens = rep2.get("generators") or {}
    w = gens.get("walls") or {}
    c = gens.get("ceilings") or {}
    slim = {}
    if isinstance(w, dict):
        for k in ("walls_processed", "boards_created", "studs_created", "tracks_created",
                  "corner_infill_boards", "walls_missing_coverage", "warnings"):
            slim["wall_" + k] = (len(w.get(k)) if k == "warnings" else w.get(k))
    if isinstance(c, dict):
        for k in ("ceilings_processed", "boards_created", "furring_created", "mains_created",
                  "rooms_found", "rooms_used", "small_boards_merged"):
            slim["ceil_" + k] = c.get(k)
    out["stage2"] = slim
except Exception:
    out["stage2_error"] = traceback.format_exc()[-900:]
out["stage2_seconds"] = round(time.time() - t1, 1)

# ---- panel quality ------------------------------------------------------------------------------
lens = []
framing = 0
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
    except Exception:
        continue
    if not c.startswith("ORIGIN_ASSEMBLY_V4 |"):
        continue
    if "| DRYWALL" not in c:
        framing += 1
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    lens.append(max(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y))
lens.sort()
n = len(lens)
out["panel_quality"] = {
    "boards": n, "framing": framing,
    "full_8ft_sheets": len([v for v in lens if v >= 7.9]),
    "slivers_under_1ft": len([v for v in lens if v < 1.0]),
    "median_len_ft": (round(lens[n // 2], 3) if n else None),
}

OUT = out
