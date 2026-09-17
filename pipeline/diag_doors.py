# diag_doors.py - what does the direction resolver actually see in the open document?
# Read-only. Dumps every door with the numbers the tie-break uses, so a wrong pick is visible.

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

ROOT = r"C:\Users\Origoncad\origin_pipeline"

ns = {"__name__": "ceiling_direction"}
p = os.path.join(ROOT, "ceiling_direction.py")
exec(compile(open(p).read(), p, "exec"), ns)

doc = DocumentManager.Instance.CurrentDBDocument
res = ns["resolve_direction"](doc)

doors = res.pop("doors", [])
foot, fsrc = ns["building_footprint"](doc)
bb = ns["poly_bbox"](foot) if foot else None

rows = []
for d in sorted(doors, key=lambda r: -(r.get("width_ft") or 0)):
    rows.append({
        "id": d["id"],
        "family": d.get("name"),
        "width_mm": d.get("width_mm"),
        "xy": [d.get("x"), d.get("y")],
        "facing": d.get("facing"),
        "facing_src": d.get("facing_source"),
        "edge_m": d.get("dist_to_edge_m"),
        "exterior": d.get("exterior"),
        "usable": d.get("usable"),
        "host_wall": d.get("host_wall_id"),
    })

# Every distinct width present, so "all doors are the same size" is obvious at a glance.
widths = {}
for d in doors:
    w = d.get("width_mm")
    widths[w] = widths.get(w, 0) + 1

OUT = {
    "doc": doc.Title,
    "footprint_source": fsrc,
    "footprint_bbox_ft": None if bb is None else [round(v, 2) for v in bb],
    "footprint_size_ft": None if bb is None else [round(bb[2] - bb[0], 2), round(bb[3] - bb[1], 2)],
    "doors_total": len(doors),
    "distinct_widths_mm": widths,
    "decision": res,
    "doors": rows,
    "walls": FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType().GetElementCount(),
    "ceilings": FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType().GetElementCount(),
}
