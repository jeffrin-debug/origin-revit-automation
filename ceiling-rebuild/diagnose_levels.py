# diagnose_levels.py
# ============================================================
# What does each level in the current document actually look like? Deciding which levels are
# real storeys is the thing that keeps going wrong, so this dumps every signal at once:
# elevation, Building Story flag, walls based on it, walls spanning it, floor slabs at it,
# ceilings at it, and plan views. Read-only.
# ============================================================

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


levels = sorted(FilteredElementCollector(doc).OfClass(Level).WhereElementIsNotElementType(),
                key=lambda l: l.Elevation)

walls = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        bb = w.get_BoundingBox(None)
        walls.append({"level_id": eid_value(w.LevelId),
                      "zlo": None if bb is None else bb.Min.Z,
                      "zhi": None if bb is None else bb.Max.Z})
    except Exception:
        continue

floors = []
for f in FilteredElementCollector(doc).OfClass(Floor).WhereElementIsNotElementType():
    try:
        bb = f.get_BoundingBox(None)
        floors.append({"zlo": bb.Min.Z, "zhi": bb.Max.Z})
    except Exception:
        continue

ceilings = []
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    try:
        bb = c.get_BoundingBox(None)
        p = c.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)
        ceilings.append({"level_id": eid_value(c.LevelId),
                         "bottom_mm": round(bb.Min.Z * 304.8, 1) if bb else None,
                         "area_sf": round(p.AsDouble(), 1) if p else None,
                         "category": c.Category.Name})
    except Exception:
        continue

rows = []
for lv in levels:
    lid = eid_value(lv.Id)
    e_ft = lv.Elevation
    row = {
        "name": lv.Name,
        "id": lid,
        "elev_mm": round(e_ft * 304.8, 1),
        "walls_based_here": len([w for w in walls if w["level_id"] == lid]),
        "walls_spanning_here": len([w for w in walls
                                    if w["zlo"] is not None
                                    and w["zlo"] <= e_ft + 1e-6 <= w["zhi"] + 1e-6]),
        "floor_slab_top_at_level": len([f for f in floors if abs(f["zhi"] - e_ft) <= 0.5]),
        "ceilings_on_level": len([c for c in ceilings if c["level_id"] == lid]),
    }
    for bip, key in ((BuiltInParameter.LEVEL_IS_BUILDING_STORY, "is_building_story"),):
        try:
            p = lv.get_Parameter(bip)
            row[key] = None if p is None else p.AsInteger()
        except Exception:
            row[key] = "error"
    try:
        p = lv.get_Parameter(BuiltInParameter.LEVEL_ROOM_COMPUTATION_HEIGHT)
        row["computation_height_mm"] = round(p.AsDouble() * 304.8, 1) if p else None
    except Exception:
        row["computation_height_mm"] = None
    rows.append(row)

OUT = {
    "doc": doc.Title,
    "levels": rows,
    "floor_slabs": [{"bottom_mm": round(f["zlo"] * 304.8, 1),
                     "top_mm": round(f["zhi"] * 304.8, 1)} for f in floors],
    "ceilings": ceilings,
    "wall_count": len(walls),
}
