# verify_stage2.py
# ============================================================
# One cheap, decisive check before trusting the pipeline with a batch.
#
# Opens ONE env as a background document, runs the panel generators against it, reports what
# they produced, and closes WITHOUT SAVING. Nothing on disk changes.
#
# It proves the two things that had never been done before this pipeline existed:
#   - the generators honour an injected target document (ORIGIN_TARGET_DOC) instead of the
#     document open in the Revit UI;
#   - Dynamo's TransactionManager commits against a background document.
#
# Point TARGET at whichever env you want, and narrow ONLY to a single generator while you are
# still shaking things out - e.g. ONLY = ["walls"].
# ============================================================

import clr
import os
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

TARGET = os.path.join(_paths["CEILING_ROOT"], "out", "Testing_Env.rvt")
ONLY = None          # e.g. ["walls"] to run just one generator

stage2 = {"__name__": "stage2_panels"}
stage2_path = os.path.join(ROOT, "stage2_panels.py")
stage2["__file__"] = stage2_path
exec(compile(open(stage2_path).read(), stage2_path, "exec"), stage2)

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application

dialogs_seen = []


def _on_dialog(sender, args):
    try:
        dialogs_seen.append(str(args.DialogId))
    except Exception:
        dialogs_seen.append("<unknown dialog>")
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

result = {"target": TARGET, "only": ONLY}
nd = None
t0 = time.time()

try:
    if not os.path.exists(TARGET):
        raise Exception("target not found: {}".format(TARGET))

    mtime_before = os.path.getmtime(TARGET)
    active_title = None
    try:
        active_title = DocumentManager.Instance.CurrentDBDocument.Title
    except Exception:
        pass

    TransactionManager.Instance.ForceCloseTransaction()
    oo = OpenOptions()
    try:
        oo.Audit = False
    except Exception:
        pass
    nd = app.OpenDocumentFile(ModelPathUtils.ConvertUserVisiblePathToModelPath(TARGET), oo)

    result["background_doc"] = nd.Title
    result["active_doc"] = active_title
    # If these are equal the test proves nothing - it would just be the ordinary live path.
    result["is_really_background"] = (nd.Title != active_title)

    rep = stage2["run_on_document"](nd, manifest_dir=None, only=ONLY)
    result["panels"] = rep

    # Count what actually landed in the BACKGROUND document. This is the real evidence: if the
    # injection had failed, the generators would have written into the UI's document and these
    # would be zero.
    made = {}
    for ds in FilteredElementCollector(nd).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mark = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mark.AsString() if mark else None
        except Exception:
            mark = None
        key = (mark or "?")[:2]
        made[key] = made.get(key, 0) + 1
    result["directshapes_in_background_doc_by_mark_prefix"] = made
    result["directshapes_total"] = sum(made.values())
    result["source_unmodified"] = (os.path.getmtime(TARGET) == mtime_before)

except Exception:
    result["FATAL"] = traceback.format_exc()
finally:
    try:
        if nd is not None:
            nd.Close(False)          # discard everything - this is a test
            result["closed_without_saving"] = True
    except Exception:
        result["close_error"] = traceback.format_exc()
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    if hooked:
        try:
            uiapp.DialogBoxShowing -= _on_dialog
        except Exception:
            pass

result["sec"] = round(time.time() - t0, 2)
result["dialogs_auto_answered"] = dialogs_seen
OUT = result
