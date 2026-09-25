# origin_bridge_measure_wall_ceiling_gap.py - run via the ORIGIN Bridge. READ-ONLY.
# Measures the REAL gap between DP-S001-005 (the soffit ceiling board the user had selected) and
# every nearby wall drywall board - both the Z-gap (wall top vs ceiling bottom) and any X/Y gap,
# to find exactly which mechanism is producing the visible seam reported from the sim.
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

TARGET_MARK = "DP-S001-005"
RADIUS_FT = 5.0


def bbox_center(bb):
    return XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

target = None
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark == TARGET_MARK:
        target = ds
        break

out = {"target_found": target is not None}
if target is not None:
    tbb = target.get_BoundingBox(None)
    tc = bbox_center(tbb)
    out["target_bbox_ft"] = {"min": [round(tbb.Min.X, 4), round(tbb.Min.Y, 4), round(tbb.Min.Z, 4)],
                              "max": [round(tbb.Max.X, 4), round(tbb.Max.Y, 4), round(tbb.Max.Z, 4)]}

    nearby_walls = []
    for ds in all_ds:
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if not mark or not mark.startswith("DP-0"):
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        c = bbox_center(bb)
        if tc.DistanceTo(c) > RADIUS_FT:
            continue
        # Z-gap: wall board's top (Max.Z) vs ceiling board's bottom (Min.Z) - positive = real gap
        z_gap_ft = tbb.Min.Z - bb.Max.Z
        # X/Y overlap check (do the footprints even line up near each other)
        x_overlap = min(tbb.Max.X, bb.Max.X) - max(tbb.Min.X, bb.Min.X)
        y_overlap = min(tbb.Max.Y, bb.Max.Y) - max(tbb.Min.Y, bb.Min.Y)
        nearby_walls.append({
            "mark": mark,
            "bbox_ft": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                        "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
            "z_gap_ft_wall_top_to_ceiling_bottom": round(z_gap_ft, 4),
            "z_gap_in": round(z_gap_ft * 12.0, 3),
            "xy_footprint_overlap_ft": [round(x_overlap, 4), round(y_overlap, 4)],
        })
    nearby_walls.sort(key=lambda r: abs(r["z_gap_ft_wall_top_to_ceiling_bottom"]))
    out["nearby_wall_boards"] = nearby_walls[:15]

OUT = out
