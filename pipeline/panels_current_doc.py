# panels_current_doc.py
# ============================================================
# Run the drywall panel generators on the model CURRENTLY OPEN in Revit, so you can watch it
# happen. Nothing is saved - the change lands in the open session and you save it yourself if
# you like the result.
#
# This is the live twin of stage 2 in the pipeline: it goes through stage2_panels, so the walls
# and ceilings are passed explicitly and Dynamo's transaction is force-closed at the end. That
# last part matters here - without it the document keeps an open transaction and your own
# File > Save As is refused with "Unable to close all open transaction phases!".
#
# The pipeline's own runs are unaffected by this file; it exists for interactive checking.
# ============================================================

import clr
import os
import time

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

ROOT = r"C:\Users\Origoncad\origin_pipeline"

stage2 = {"__name__": "stage2_panels"}
stage2_path = os.path.join(ROOT, "stage2_panels.py")
exec(compile(open(stage2_path).read(), stage2_path, "exec"), stage2)

doc = DocumentManager.Instance.CurrentDBDocument

t0 = time.time()
report = stage2["run_on_document"](doc, manifest_dir=None)
report["document"] = doc.Title
report["saved"] = False
report["note"] = "nothing was saved - use File > Save As in Revit to keep this"
report["sec"] = round(time.time() - t0, 2)

OUT = report
