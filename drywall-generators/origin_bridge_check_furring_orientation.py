# origin_bridge_check_furring_orientation.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms whether ceiling FURRING/MAIN members are actually oriented N-S (long in Y, narrow in
# X) after flipping FURRING_RUN_NS, by dumping real bboxes for a sample of ST-C*/ST-* ceiling
# framing marks (identified by CEIL comment kind FURRING/MAIN).
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

out = {"FURRING": [], "MAIN": []}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "ORIGIN_CEILING_V1" not in comments:
        continue
    kind = None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok in ("FURRING", "MAIN"):
            kind = tok
    if kind is None or len(out[kind]) >= 5:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    xspan = round(bb.Max.X - bb.Min.X, 3)
    yspan = round(bb.Max.Y - bb.Min.Y, 3)
    out[kind].append({
        "mark": mark, "x_span_ft": xspan, "y_span_ft": yspan,
        "runs_along": "Y (N-S)" if yspan > xspan else "X (E-W)",
    })

OUT = out
