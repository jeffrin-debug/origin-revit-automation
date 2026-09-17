# demo_before_after_active.py
# ============================================================
# Before/after on the SAME live model, so the comparison has no second variable in it.
#
#   PASS A   run the five generators on the env exactly as the modeller built it
#   PURGE    remove every ORIGIN element pass A created
#   MERGE    W1 - collinear wall fragments become single walls
#   PASS B   run the same five generators again
#
# Nothing is saved at any point. Close the model with Don't Save and the env is untouched.
#
# The purge between passes is not optional housekeeping: the merge destroys wall element ids,
# and the generators' own cleanup is scoped by WALL=W<eid>. Pass A's panels would otherwise
# survive as orphans and be counted as pass B's work.
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
CORE = os.path.join(ROOT, "w1_core.py")
S2 = os.path.join(ROOT, "stage2_panels.py")

ORIGIN_APP_IDS = ("ORIGIN_ASSEMBLY_V4", "ORIGIN_CEILING_V1", "ORIGIN_BEAM_V1",
                  "ORIGIN_COLUMN_V1", "ORIGIN_BEAMCOL_V1")

core = {"__name__": "w1_core"}
core["__file__"] = CORE
exec(compile(open(CORE).read(), CORE, "exec"), core)

doc = DocumentManager.Instance.CurrentDBDocument
out = {"doc": doc.Title, "saved": False,
       "note": "nothing saved - close with Don't Save to discard everything"}


def measure(doc):
    """Panel-layout quality. Board COUNT is not the metric - a chopped-up wall produces more
    boards, not fewer, and the extra ones are offcuts nobody would cut. Full sheets and slivers
    are what say whether the layout is buildable."""
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
    return {
        "boards": n,
        "framing": framing,
        "full_8ft_sheets": len([v for v in lens if v >= 7.9]),
        "over_4ft": len([v for v in lens if v >= 4.0]),
        "slivers_under_1ft": len([v for v in lens if v < 1.0]),
        "median_len_ft": (round(lens[n // 2], 3) if n else None),
        "mean_len_ft": (round(sum(lens) / n, 3) if n else None),
        "max_len_ft": (round(lens[-1], 3) if n else None),
    }


def run_panels(doc):
    stage2 = {"__name__": "stage2_panels"}
    stage2["__file__"] = S2
    exec(compile(open(S2).read(), S2, "exec"), stage2)
    rep = stage2["run_on_document"](doc)
    gens = rep.get("generators") or {}
    w = gens.get("walls") or {}
    slim = {}
    if isinstance(w, dict):
        for k in ("walls_processed", "boards_created", "studs_created", "tracks_created",
                  "corner_infill_boards", "drywall_faces_capped_at_ceiling",
                  "walls_missing_coverage", "corners_trimmed", "small_gaps_closed"):
            slim[k] = w.get(k)
        slim["warnings"] = len(w.get("warnings") or [])
    c = gens.get("ceilings") or {}
    if isinstance(c, dict):
        slim["ceilings_processed"] = c.get("ceilings_processed")
        slim["ceiling_boards"] = c.get("boards_created")
        slim["rooms_found"] = c.get("rooms_found")
    return slim


def purge_origin(doc):
    """Delete every ORIGIN-generated element, regardless of which wall it claims as host."""
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
        t = Transaction(doc, "ORIGIN purge between demo passes")
        t.Start()
        try:
            doc.Delete(ids)
            t.Commit()
        except Exception:
            t.RollBack()
            return -1
    return n


# ---- baseline geometry -------------------------------------------------------------------
w0 = core["read_walls"](doc)
ch0 = core["find_chains"](w0)
out["geometry_before"] = {
    "straight_walls": len(w0),
    "chains": len(ch0),
    "redundant_fragments": sum(len(m) - 1 for m in ch0),
    "stubs_under_half_ft": len([w for w in w0 if w["len"] < 0.5]),
}

# ---- PASS A : panels on the env as built --------------------------------------------------
t0 = time.time()
try:
    out["pass_A_generators"] = run_panels(doc)
    out["pass_A_panels"] = measure(doc)
    out["pass_A_seconds"] = round(time.time() - t0, 1)
except Exception:
    out["pass_A_error"] = traceback.format_exc()[-900:]

# ---- PURGE ---------------------------------------------------------------------------------
try:
    out["purged"] = purge_origin(doc)
except Exception:
    out["purge_error"] = traceback.format_exc()[-600:]

# ---- MERGE ---------------------------------------------------------------------------------
rep = {}
try:
    TransactionManager.Instance.ForceCloseTransaction()
except Exception:
    pass
try:
    core["merge_chains"](doc, rep)
    out["merge"] = {k: rep.get(k) for k in
                    ("walls_before", "walls_after", "chains_found", "merged",
                     "fragments_removed", "chains_remaining", "guard_tripped")}
    out["merge"]["skipped"] = len(rep.get("skipped") or [])
    out["merge"]["failed"] = len(rep.get("failed") or [])
    out["merge_skipped_detail"] = (rep.get("skipped") or [])[:5]
    out["merge_failed_detail"] = (rep.get("failed") or [])[:5]
    out["merge_passes"] = rep.get("passes")
except Exception:
    out["merge_error"] = traceback.format_exc()[-900:]

# ---- PASS B : panels on the merged env ------------------------------------------------------
t1 = time.time()
try:
    TransactionManager.Instance.ForceCloseTransaction()
except Exception:
    pass
try:
    out["pass_B_generators"] = run_panels(doc)
    out["pass_B_panels"] = measure(doc)
    out["pass_B_seconds"] = round(time.time() - t1, 1)
except Exception:
    out["pass_B_error"] = traceback.format_exc()[-900:]

OUT = out
