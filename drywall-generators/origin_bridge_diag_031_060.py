# origin_bridge_diag_031_060.py - run via the ORIGIN Bridge. READ-ONLY.
# Targeted diagnostic for the one remaining DP-031-003A / DP-060-002A overlap (0.034722 cf) that
# survives close_small_cross_wall_gaps()'s final audit-and-revert pass. Reports each board's host,
# bbox, comments/mark, plain-box status, and the real boolean overlap - to find why the audit's
# broad-phase pre-filter or overlap check didn't catch and revert this specific pair.
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

TARGETS = ["DP-031-003A", "DP-060-002A"]


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


found = {}
ds_by_mark = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGETS:
        continue
    ds_by_mark[mark] = ds
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = ds.get_BoundingBox(None)
    solids = solids_of(ds)
    vol = sum(s.Volume for s in solids)
    bbox_vol = None
    is_plain_box = None
    if bb is not None:
        bbox_vol = (max(0.0, bb.Max.X - bb.Min.X) * max(0.0, bb.Max.Y - bb.Min.Y) *
                    max(0.0, bb.Max.Z - bb.Min.Z))
        is_plain_box = bbox_vol > 1e-9 and abs(vol - bbox_vol) < max(1e-6, bbox_vol * 0.01)
    found[mark] = {
        "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 5), round(bb.Min.Y, 5), round(bb.Min.Z, 5)],
            "max": [round(bb.Max.X, 5), round(bb.Max.Y, 5), round(bb.Max.Z, 5)],
        },
        "solid_count": len(solids),
        "volume_cf": round(vol, 6),
        "bbox_vol_cf": None if bbox_vol is None else round(bbox_vol, 6),
        "is_plain_box": is_plain_box,
    }

max_ov = 0.0
if len(found) == 2:
    ds_a = ds_by_mark[TARGETS[0]]
    ds_b = ds_by_mark[TARGETS[1]]
    for s1 in solids_of(ds_a):
        for s2 in solids_of(ds_b):
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(s1, s2, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > max_ov:
                    max_ov = inter.Volume
            except Exception:
                continue

OUT = {"found": found, "real_overlap_cf": round(max_ov, 6)}
