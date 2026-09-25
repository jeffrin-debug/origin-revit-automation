# origin_bridge_debug_corner_extents.py - run via the ORIGIN Bridge. READ-ONLY.
# Loads ONLY the function/constant definitions from the real wall script (everything before its
# "MAIN" section, which starts building/deleting real elements) into a sandbox namespace, then
# calls the REAL corner_face_extents()/get_wall_curve_data() against the two live walls reported
# by the user (W380854, W404773) to see exactly what extents the live algorithm computes - no
# hand-derivation, no risk of a live rebuild.
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

SCRIPT = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py"
src = open(SCRIPT).read()
marker = "# ============================================================\n# MAIN\n"
idx = src.find(marker)
defs_src = src[:idx]

ns = {"__name__": "origin_wall_defs_sandbox", "doc": doc, "uidoc": uidoc}
exec(compile(defs_src, SCRIPT, "exec"), ns)

Wall_ = ns["Wall"]
FilteredElementCollector_ = ns["FilteredElementCollector"]
get_wall_curve_data = ns["get_wall_curve_data"]
get_wall_width = ns["get_wall_width"]
corner_face_extents = ns["corner_face_extents"]
corner_pullbacks = ns["corner_pullbacks"]
_is_curtain_wall = ns["_is_curtain_wall"]
eid_value = ns["eid_value"]

corner_candidates = []
for _cw in FilteredElementCollector_(doc).OfClass(Wall_).WhereElementIsNotElementType():
    if _is_curtain_wall(_cw):
        continue
    _csg = get_wall_curve_data(_cw)
    if _csg is not None:
        corner_candidates.append((_cw, _csg, get_wall_width(_cw)))

out = {"corner_candidates_count": len(corner_candidates)}

for tag, wid in [("W380854", 380854), ("W404773", 404773)]:
    w = doc.GetElement(ElementId(wid))
    seg = get_wall_curve_data(w)
    start, end_pt, dvec, length = seg
    fe = corner_face_extents(w, corner_candidates)
    pb = corner_pullbacks(w, [], corner_candidates)
    info = {
        "start": [round(start.X, 4), round(start.Y, 4)],
        "end": [round(end_pt.X, 4), round(end_pt.Y, 4)],
        "dir": [round(dvec.X, 4), round(dvec.Y, 4)],
        "length": round(length, 4),
        "width_ft": round(get_wall_width(w), 4),
        "face_extents": fe,
        "framing_pullbacks": pb,
    }
    # Convert face_extents lo/hi (along-wall coords) to world XY for both faces, for direct
    # comparison against the actual board bboxes already captured.
    for side in ("interior", "exterior"):
        lo, hi = fe[side]
        p_lo = (round(start.X + dvec.X * lo, 4), round(start.Y + dvec.Y * lo, 4))
        p_hi = (round(start.X + dvec.X * hi, 4), round(start.Y + dvec.Y * hi, 4))
        info["{}_world".format(side)] = {"lo_pt": p_lo, "hi_pt": p_hi}
    out[tag] = info

OUT = out
