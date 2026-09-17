# w1_apply_active.py
# ============================================================
# Run the W1 wall merge on the document currently OPEN IN THE REVIT UI, in place.
#
# A model open in the UI cannot be opened as a background document, so the batch driver skips it.
# This is the path for "I have an env on screen, show me the merge working."
#
# NOTHING IS SAVED. The merge lives only in the open session, so closing the model with
# Don't Save discards it completely. Each chain is still its own Transaction, so Revit's own
# undo stack also holds them individually.
#
# Set "panels": true in _active_config.json to run the five drywall generators afterwards, in
# the same session, so the before/after can be judged on screen rather than from counters.
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

ROOT = r"C:\Users\Origoncad\origin_pipeline"
CORE = os.path.join(ROOT, "w1_core.py")
CFG = os.path.join(ROOT, "_active_config.json")

cfg = {}
if os.path.exists(CFG):
    try:
        cfg = json.load(open(CFG))
    except Exception:
        cfg = {}
DO_MERGE = bool(cfg.get("merge", True))
DO_PANELS = bool(cfg.get("panels", False))

core = {"__name__": "w1_core"}
exec(compile(open(CORE).read(), CORE, "exec"), core)

doc = DocumentManager.Instance.CurrentDBDocument

out = {"doc": doc.Title, "saved": False, "note": "nothing is saved - close with Don't Save to discard"}

# ---- what is wrong, before touching anything -------------------------------------------------
walls0 = core["read_walls"](doc)
chains0 = core["find_chains"](walls0)
out["before"] = {
    "straight_walls": len(walls0),
    "chains": len(chains0),
    "redundant_fragments": sum(len(m) - 1 for m in chains0),
    "stubs_under_half_ft": len([w for w in walls0 if w["len"] < 0.5]),
    "worst_chains": sorted(
        [{"pieces": len(m), "span_ft": round(core["chain_endpoints"](m)[2], 2),
          "lengths_ft": sorted(round(x["len"], 3) for x in m)} for m in chains0],
        key=lambda r: -r["pieces"])[:8],
}

# ---- merge ------------------------------------------------------------------------------------
if DO_MERGE and chains0:
    rep = {}
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    try:
        core["merge_chains"](doc, rep)
        out["merge"] = rep
    except Exception:
        out["merge_error"] = traceback.format_exc()[-900:]
elif not chains0:
    out["merge"] = {"note": "no collinear chains - nothing to merge"}

# ---- optionally run the panels right after, in the same session --------------------------------
if DO_PANELS:
    t0 = time.time()
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    s2_path = os.path.join(ROOT, "stage2_panels.py")
    stage2 = {"__name__": "stage2_panels"}
    try:
        exec(compile(open(s2_path).read(), s2_path, "exec"), stage2)
        rep2 = stage2["run_on_document"](doc)
        gens = rep2.get("generators") or {}
        w = gens.get("walls") or {}
        slim = {}
        if isinstance(w, dict):
            for k in ("walls_processed", "boards_created", "studs_created", "tracks_created",
                      "corner_infill_boards", "drywall_faces_capped_at_ceiling",
                      "walls_missing_coverage"):
                slim[k] = w.get(k)
            slim["warnings"] = len(w.get("warnings") or [])
        out["panels"] = slim
        out["panels_seconds"] = round(time.time() - t0, 1)

        # panel-quality metrics, the same ones used for the before/after comparison
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
            "boards": n,
            "framing": framing,
            "full_8ft_sheets": len([v for v in lens if v >= 7.9]),
            "slivers_under_1ft": len([v for v in lens if v < 1.0]),
            "median_len_ft": (round(lens[n // 2], 3) if n else None),
            "max_len_ft": (round(lens[-1], 3) if n else None),
        }
    except Exception:
        out["panels_error"] = traceback.format_exc()[-900:]

try:
    walls1 = core["read_walls"](doc)
    out["after"] = {"straight_walls": len(walls1),
                    "chains": len(core["find_chains"](walls1))}
except Exception:
    pass

OUT = out
