# diag_doors_batch.py
# ============================================================
# Run the ceiling-direction resolver against EVERY env, read-only, to see where the rule holds
# and where it does not - without opening each one by hand.
#
# Each file is opened as a background document, resolved, and closed WITHOUT saving. No
# transaction is opened at all: resolve_direction only reads collectors and geometry.
#
# Answers one question: on how many envs does the main door actually decide the direction, and
# on which ones does it fall through to the generator's default or to a guess.
# ============================================================

import clr
import os
import re
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
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

ROOT = _paths["PIPELINE_ROOT"]
SEARCH_DIRS = [
    _paths["INPUT_DIR"],
    os.path.join(_paths["CEILING_ROOT"], "out"),
]
MAX_MB = 50.0

ns = {"__name__": "ceiling_direction"}
p = os.path.join(ROOT, "ceiling_direction.py")
ns["__file__"] = p
exec(compile(open(p).read(), p, "exec"), ns)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

open_titles = []
for d in app.Documents:
    try:
        open_titles.append(d.Title)
    except Exception:
        pass

# Background opens raise plain task dialogs that FailureHandlingOptions never sees; unanswered
# they freeze the batch at zero CPU with nobody at the keyboard.
dialogs = []


def _on_dialog(sender, args):
    try:
        dialogs.append(str(args.DialogId))
    except Exception:
        dialogs.append("<unknown>")
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

backup = re.compile(r"\.\d{4}\.rvt$", re.IGNORECASE)
targets = []
seen = set()
for d in SEARCH_DIRS:
    if not os.path.exists(d):
        continue
    for dirpath, dirnames, filenames in os.walk(d):
        for n in sorted(filenames):
            if not n.lower().endswith(".rvt") or backup.search(n):
                continue
            fp = os.path.join(dirpath, n)
            key = n.lower()
            if key in seen:
                continue
            try:
                if os.path.getsize(fp) / (1024.0 * 1024.0) > MAX_MB:
                    continue
            except Exception:
                continue
            seen.add(key)
            targets.append(fp)

rows = []
for path in targets:
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    row = {"file": name}
    if stem in open_titles:
        row["status"] = "skipped (open in UI)"
        rows.append(row)
        continue

    nd = None
    t0 = time.time()
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        oo = OpenOptions()
        try:
            oo.Audit = False
        except Exception:
            pass
        nd = app.OpenDocumentFile(
            ModelPathUtils.ConvertUserVisiblePathToModelPath(path), oo)

        res = ns["resolve_direction"](nd)
        doors = res.get("doors") or []
        md = res.get("main_door") or {}
        row.update({
            "status": "ok" if res.get("ok") else "UNRESOLVED",
            "doors": len(doors),
            "nearest_m": res.get("nearest_door_m"),
            "band_m": res.get("edge_band_m"),
            "perimeter_doors": len([d for d in doors if d.get("exterior")]),
            "main_width_mm": md.get("width_mm"),
            "main_edge_m": md.get("dist_to_edge_m"),
            "axis": res.get("walk_in_axis"),
            "off_axis_deg": res.get("off_axis_deg"),
            "FURRING_RUN_NS": res.get("furring_run_ns"),
            "footprint": res.get("footprint_source"),
            "warnings": res.get("warnings") or [],
            "reason": res.get("reason"),
        })
    except Exception:
        tb = traceback.format_exc()
        if "later version of Revit" in tb or "CorruptModelException" in tb:
            row["status"] = "quarantined (newer Revit)"
        else:
            row["status"] = "error"
            row["error"] = tb[-400:]
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
    row["sec"] = round(time.time() - t0, 2)
    rows.append(row)

if hooked:
    try:
        uiapp.DialogBoxShowing -= _on_dialog
    except Exception:
        pass

done = [r for r in rows if r.get("status") in ("ok", "UNRESOLVED")]
OUT = {
    "envs_found": len(targets),
    "dialogs_auto_answered": dialogs,
    "totals": {
        "decided_by_a_door": len([r for r in done if r.get("status") == "ok"]),
        "unresolved_no_usable_door": len([r for r in done if r.get("status") == "UNRESOLVED"]),
        "warned": len([r for r in done if r.get("warnings")]),
        "rotated_over_20deg": len([r for r in done
                                   if (r.get("off_axis_deg") or 0) > 20.0]),
        "furring_X": len([r for r in done if r.get("FURRING_RUN_NS") is True]),
        "furring_Y": len([r for r in done if r.get("FURRING_RUN_NS") is False]),
        "skipped": len([r for r in rows if "skipped" in str(r.get("status"))]),
        "quarantined": len([r for r in rows if "quarantined" in str(r.get("status"))]),
        "errors": len([r for r in rows if r.get("status") == "error"]),
    },
    "envs": rows,
}
