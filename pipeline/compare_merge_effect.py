# compare_merge_effect.py
# ============================================================
# Did merging the walls actually make the panels better?
#
# Runs stage 2 against BOTH versions of the same env - the original, and the 00_normalized copy
# whose collinear wall fragments have been merged - and measures the panel layout each produces.
# Both documents are opened in the background and closed WITHOUT saving, so this proves the
# point without producing anything anyone has to clean up.
#
# The metric that matters is not board count. A fragmented wall produces MORE boards, not fewer,
# and most of the extra ones are slivers that no installer would ever cut. So: how many boards
# are full sheets, how many are slivers, and how long is a typical board.
# ============================================================

import clr
import json
import math
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

ROOT = r"C:\Users\Origoncad\origin_pipeline"
OUT_DIR = os.path.join(ROOT, "_reports", "conformance")
CONFIG_PATH = os.path.join(ROOT, "_compare_config.json")

APP_ID = "ORIGIN_ASSEMBLY_V4"
FULL_SHEET_FT = 8.0
FULL_TOL_FT = 0.1
SLIVER_FT = 1.0

cfg = json.load(open(CONFIG_PATH))
PAIRS = cfg.get("pairs") or []          # [{"name":..,"original":path,"normalized":path}, ...]

stage2 = {"__name__": "stage2_panels"}
s2_path = os.path.join(ROOT, "stage2_panels.py")
exec(compile(open(s2_path).read(), s2_path, "exec"), stage2)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

dialogs = []


def _on_dialog(sender, args):
    try:
        dialogs.append(str(args.DialogId))
    except Exception:
        pass
    try:
        args.OverrideResult(1)
    except Exception:
        pass


hooked = False
try:
    uiapp.DialogBoxShowing += _on_dialog
    hooked = True
except Exception:
    pass


def measure_panels(doc):
    """Board-length distribution of the generated wall drywall, plus framing totals."""
    lens = []
    framing = 0
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ""
        except Exception:
            continue
        if not c.startswith(APP_ID + " |"):
            continue
        if "| DRYWALL" not in c:
            framing += 1
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        dx = bb.Max.X - bb.Min.X
        dy = bb.Max.Y - bb.Min.Y
        lens.append(max(dx, dy))          # a wall board is thin across the wall
    lens.sort()
    n = len(lens)
    return {
        "boards": n,
        "framing": framing,
        "full_sheets": len([v for v in lens if v >= FULL_SHEET_FT - FULL_TOL_FT]),
        "slivers_under_1ft": len([v for v in lens if v < SLIVER_FT]),
        "median_len_ft": (round(lens[n // 2], 3) if n else None),
        "mean_len_ft": (round(sum(lens) / n, 3) if n else None),
        "max_len_ft": (round(lens[-1], 3) if n else None),
        "min_len_ft": (round(lens[0], 3) if n else None),
    }


def run_one(path, tag):
    row = {"tag": tag, "file": os.path.basename(path), "path": path}
    stem = os.path.splitext(os.path.basename(path))[0]
    if not os.path.exists(path):
        row["status"] = "missing"
        return row
    if stem in open_titles:
        row["status"] = "skipped (open in UI)"
        return row
    nd = None
    mtime_before = os.path.getmtime(path)
    t0 = time.time()
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(path), oo)
        row["walls_in_model"] = len(list(
            FilteredElementCollector(nd).OfClass(Wall).WhereElementIsNotElementType()))
        rep = stage2["run_on_document"](nd)
        row["stage2_ok"] = not bool(rep.get("fatal"))
        gens = rep.get("generators") or {}
        w = gens.get("walls") or {}
        if isinstance(w, dict):
            row["walls_processed"] = w.get("walls_processed")
            row["gen_boards"] = w.get("boards_created")
            row["gen_studs"] = w.get("studs_created")
            row["gen_tracks"] = w.get("tracks_created")
            row["warnings"] = len(w.get("warnings") or [])
        row["panels"] = measure_panels(nd)
        row["status"] = "done"
    except Exception:
        row["status"] = "error"
        row["error"] = traceback.format_exc()[-700:]
    finally:
        try:
            if nd is not None:
                nd.Close(False)
        except Exception:
            pass
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass
    try:
        row["source_untouched"] = (os.path.getmtime(path) == mtime_before)
    except Exception:
        row["source_untouched"] = None
    row["seconds"] = round(time.time() - t0, 1)
    return row


results = []
for pair in PAIRS:
    a = run_one(pair["original"], "original")
    b = run_one(pair["normalized"], "merged")
    entry = {"env": pair.get("name"), "original": a, "merged": b}
    pa = a.get("panels") or {}
    pb = b.get("panels") or {}
    if pa and pb:
        entry["delta"] = {
            "walls": (b.get("walls_in_model"), a.get("walls_in_model")),
            "boards": (pa.get("boards"), pb.get("boards")),
            "full_sheets": (pa.get("full_sheets"), pb.get("full_sheets")),
            "slivers": (pa.get("slivers_under_1ft"), pb.get("slivers_under_1ft")),
            "median_len": (pa.get("median_len_ft"), pb.get("median_len_ft")),
            "framing": (pa.get("framing"), pb.get("framing")),
        }
    results.append(entry)

if hooked:
    try:
        uiapp.DialogBoxShowing -= _on_dialog
    except Exception:
        pass

with open(os.path.join(OUT_DIR, "_merge_effect.json"), "w") as f:
    json.dump(results, f, indent=2)

OUT = {"pairs": len(results), "dialogs": len(dialogs), "results": results}
