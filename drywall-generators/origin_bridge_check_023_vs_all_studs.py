# origin_bridge_check_023_vs_all_studs.py - run via the ORIGIN Bridge. READ-ONLY.
# Directly tests DP-023-001B and DP-023-002B against EVERY ST-* stud/track in the document (any
# host) for a real boolean intersection - the overlap sweep's dp_vs_dp findings don't cover
# DP-vs-ST, and its sample list is truncated, so this checks exhaustively rather than trusting
# the sample.
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

TARGET_BOARDS = ["DP-023-001B", "DP-023-002B"]

boards = {}
studs = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    if mark in TARGET_BOARDS:
        boards[mark] = {"ds": ds, "bbox": bb}
    elif mark.startswith("ST-"):
        studs.append({"ds": ds, "mark": mark, "bbox": bb})


def solids_of(ds):
    opt = Options()
    geo = ds.get_Geometry(opt)
    return [g for g in geo if isinstance(g, Solid) and g.Volume > 1e-9] if geo else []


pad = 0.02
out = {}
for bmark, binfo in boards.items():
    bb = binfo["bbox"]
    candidates = []
    for s in studs:
        sbb = s["bbox"]
        if (sbb.Max.X < bb.Min.X - pad or sbb.Min.X > bb.Max.X + pad or
                sbb.Max.Y < bb.Min.Y - pad or sbb.Min.Y > bb.Max.Y + pad or
                sbb.Max.Z < bb.Min.Z - pad or sbb.Min.Z > bb.Max.Z + pad):
            continue
        candidates.append(s)
    real_hits = []
    b_solids = solids_of(binfo["ds"])
    for s in candidates:
        s_solids = solids_of(s["ds"])
        total = 0.0
        failed = False
        for bs in b_solids:
            for ss in s_solids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(bs, ss, BooleanOperationsType.Intersect)
                    if inter is not None:
                        total += inter.Volume
                except Exception:
                    failed = True
        real_hits.append({"stud_mark": s["mark"], "overlap_cf": round(total, 6), "boolean_failed": failed})
    out[bmark] = {"bbox_candidates": len(candidates), "real_hits": real_hits}

OUT = out
