# run_drywall_on_walls.py
# ============================================================
# Run the drywall repo's WALL generator on the current document, so an env ends up with the
# complete assembly: walls panelised here, ceilings panelised by run_drywall_on_ceilings.py.
#
# Same pattern as the ceiling wrapper and equally non-invasive: the generator takes its walls
# from IN[0] (its PROCESS_ALL_WALLS_IF_NONE_SELECTED is False, and driven from a bridge there
# is no UI selection to fall back on), so this collects the document's walls and hands them
# over, then execs the generator's own source. Nothing in the repo is modified.
#
# Its other inputs - IN[5] delete-previous, IN[6] drywall, IN[7] force-rated, IN[8] screws,
# IN[9] purge-all - are left as None so the generator's own defaults apply.
#
# Curtain walls are excluded by the generator itself (_exclude_curtain_walls).
# Output is DirectShapes tagged ORIGIN_ASSEMBLY_V4 - a different APP_ID from the ceiling run,
# so the two do not clean up after each other.
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


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

REPO = _paths["DRYWALL_REPO"]
GENERATOR = os.path.join(REPO, "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")

ROOT = _paths["CEILING_ROOT"]
REPORT_DIR = os.path.join(ROOT, "out", "_reports")

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "generator": os.path.basename(GENERATOR)}
t0 = time.time()


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def count_app_shapes():
    n = 0
    try:
        for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
            try:
                if "ORIGIN_ASSEMBLY" in (ds.ApplicationId or ""):
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


try:
    if not os.path.exists(GENERATOR):
        raise Exception("generator not found: " + GENERATOR)

    walls = list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType())
    res["walls_passed_in"] = len(walls)

    if not walls:
        res["error"] = "no Wall elements in this document"
        OUT = res
    else:
        res["direct_shapes_before"] = count_app_shapes()

        src = open(GENERATOR).read()
        ns = {
            "IN": [walls] + [None] * 9,
            "OUT": None,
            "__name__": "__main__",
            "__file__": GENERATOR,
        }
        exec(compile(src, GENERATOR, "exec"), ns)

        try:
            doc.Regenerate()
        except Exception:
            pass
        res["direct_shapes_after"] = count_app_shapes()
        res["direct_shapes_created"] = res["direct_shapes_after"] - res["direct_shapes_before"]

        gen_out = ns.get("OUT")
        rp = os.path.join(REPORT_DIR, "drywall_on_walls_" +
                          "".join(ch for ch in doc.Title if ch.isalnum() or ch in "-_") + ".json")
        try:
            if not os.path.exists(REPORT_DIR):
                os.makedirs(REPORT_DIR)
            f = open(rp, "w")
            try:
                json.dump({"doc": doc.Title, "generator_out": gen_out}, f, indent=2, default=str)
            finally:
                f.close()
            res["report"] = rp
        except Exception:
            res["report_error"] = traceback.format_exc()[-300:]

        if isinstance(gen_out, dict):
            res["generator_keys"] = sorted(gen_out.keys())
            for k in ("walls_processed", "walls_requested", "walls_skipped", "boards_created",
                      "cut_boards", "studs_created", "tracks_created", "screws_created",
                      "openings_cut", "summary", "counts"):
                if k in gen_out:
                    v = gen_out[k]
                    res["generator_" + k] = v[:20] if isinstance(v, list) else v
            w = gen_out.get("warnings") or []
            res["generator_warnings"] = w[:10] if isinstance(w, list) else str(w)[:300]
        else:
            res["generator_out_preview"] = str(gen_out)[:1500]

        res["status"] = "ok"
        OUT = res
except Exception:
    res["status"] = "error"
    res["error"] = traceback.format_exc()
    OUT = res

res["sec"] = round(time.time() - t0, 2)
