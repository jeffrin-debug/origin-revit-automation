# origin_bridge_debug_001_018.py - run via the ORIGIN Bridge. READ-ONLY.
# Reproduces _safe_trim's exact sequence of boolean attempts for DP-018-003A (cut) vs
# DP-001-008B (other) - the one remaining overlap that survived both the direct-order and
# swapped-order Intersect retry plus the Difference fallback - to see exactly which step fails
# and with what message, so the next fallback can be chosen deliberately instead of guessing.
import clr
import traceback

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

ds_by_mark = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark in ("DP-018-003A", "DP-001-008B"):
        ds_by_mark[mark] = ds


def solids_of(ds):
    opt = Options()
    geo = ds.get_Geometry(opt)
    return [g for g in geo if isinstance(g, Solid) and g.Volume > 1e-9]


cut_solids = solids_of(ds_by_mark["DP-018-003A"])
other_solids = solids_of(ds_by_mark["DP-001-008B"])

out = {"cut_solid_count": len(cut_solids), "other_solid_count": len(other_solids), "attempts": []}

cut = cut_solids[0]
other = other_solids[0]
out["cut_volume"] = cut.Volume
out["other_volume"] = other.Volume

for label, op, args in [
    ("intersect(cut,other)", BooleanOperationsType.Intersect, (cut, other)),
    ("intersect(other,cut)", BooleanOperationsType.Intersect, (other, cut)),
    ("difference(cut,other)", BooleanOperationsType.Difference, (cut, other)),
    ("difference(other,cut)", BooleanOperationsType.Difference, (other, cut)),
    ("union(cut,other)", BooleanOperationsType.Union, (cut, other)),
]:
    try:
        r = BooleanOperationsUtils.ExecuteBooleanOperation(args[0], args[1], op)
        out["attempts"].append({"label": label, "ok": True, "volume": r.Volume if r else None})
    except Exception as ex:
        out["attempts"].append({"label": label, "ok": False, "error": str(ex).splitlines()[0]})

# Workaround test: compute the overlap region itself as an intermediate solid (via the order that
# succeeded), then try subtracting THAT small solid from cut instead of the full `other` solid -
# sometimes avoids the exact coincident-edge condition that made the direct Difference fail.
try:
    overlap_solid = BooleanOperationsUtils.ExecuteBooleanOperation(other, cut, BooleanOperationsType.Intersect)
    try:
        r2 = BooleanOperationsUtils.ExecuteBooleanOperation(cut, overlap_solid, BooleanOperationsType.Difference)
        out["workaround_diff_cut_minus_overlap"] = {"ok": True, "volume": r2.Volume if r2 else None}
    except Exception as ex:
        out["workaround_diff_cut_minus_overlap"] = {"ok": False, "error": str(ex).splitlines()[0]}
except Exception as ex:
    out["workaround_intersect_failed"] = str(ex).splitlines()[0]

OUT = out
