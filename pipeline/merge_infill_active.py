# merge_infill_active.py - run infill_merge on the model open in Revit, without regenerating.
#
#   .\send_command.ps1 merge_infill_active.py
#
# Folds every CORNERINFILL strip into the board beside it (see infill_merge.py). Nothing is
# saved - File > Save in Revit to keep it; rerunning the walls brings the generator's strips back
# and stage 2 folds them in again.

import os
import traceback

import clr
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

DRY_RUN = False         # True: only list the strips and what would happen; False: merge them

doc = DocumentManager.Instance.CurrentDBDocument

# Paths resolve from this file's own location - see origin_paths.py.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)
ROOT = _paths["PIPELINE_ROOT"]

_m = {"__name__": "infill_merge"}
_mp = os.path.join(ROOT, "infill_merge.py")
_m["__file__"] = _mp
exec(compile(open(_mp).read(), _mp, "exec"), _m)

MANIFEST = os.path.join(_paths["DRYWALL_REPO"], "origin_assembly_manifest_notaper_noscrew_nojoint.json")

try:
    if DRY_RUN:
        OUT = {"doc": doc.Title, "dry_run": True, "plan": _m["plan"](doc)}
    else:
        OUT = {"doc": doc.Title, "report": _m["run"](doc, MANIFEST), "saved": False,
               "note": "nothing was saved - use File > Save in Revit to keep this"}
except Exception:
    OUT = {"error": traceback.format_exc()[-1200:]}
