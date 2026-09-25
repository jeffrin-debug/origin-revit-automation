# diag_wall055.py - read-only. What does the wall generator actually see for one wall?
#
# Reports, for the wall carrying a given board mark: the framing run, the stud lines it
# computes, the partition tees it finds, and each face's drywall extent. Enough to tell whether
# a joint that misses a stud is a grid problem, a tee with no framing, or something else.

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

GEN = os.path.join(_paths["DRYWALL_REPO"],
                   "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py")

TARGET_WALL_NUMBER = "055"

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "target": TARGET_WALL_NUMBER}

# Load the generator's own functions without running it: everything up to the first
# "if __name__" style driver is module-level defs, so exec'ing it would run the build. Instead
# read the source and exec ONLY the function/constant definitions by compiling the whole file
# with the driver guarded off is not possible here - so we re-derive using the same rules.
src = open(GEN).read()
res["generator_has_extra_xs"] = "extra_xs" in src
res["generator_has_course_cells"] = "def course_cells_on_studs" in src
res["split_before_studs"] = src.find("split_positions = partition_split_positions") < src.find("stud_xs = stud_lines")

IN_FT = 1.0 / 12.0
STUD_SPACING_FT = 16.0 * IN_FT


def eidv(e):
    try:
        return e.Value
    except Exception:
        return e.IntegerValue


# Find the wall by its ORIGIN mark prefix on a board: DP-055-*
target_wall_id = None
for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mk = p.AsString() if p else None
        if mk and mk.startswith("DP-" + TARGET_WALL_NUMBER + "-"):
            c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            cs = c.AsString() if c else ""
            for tok in (cs or "").split():
                if tok.startswith("WALL=W"):
                    target_wall_id = int(tok[6:])
                    break
        if target_wall_id:
            break
    except Exception:
        continue
res["wall_element_id"] = target_wall_id

if target_wall_id:
    w = doc.GetElement(ElementId(target_wall_id))
    loc = w.Location
    crv = loc.Curve
    a, b = crv.GetEndPoint(0), crv.GetEndPoint(1)
    length = a.DistanceTo(b)
    res["wall"] = {
        "id": target_wall_id,
        "length_ft": round(length, 4),
        "length_in": round(length * 12, 1),
        "start": [round(a.X, 3), round(a.Y, 3)],
        "end": [round(b.X, 3), round(b.Y, 3)],
    }

    # Which other walls tee into this one's mid-span, and where along it.
    d = XYZ((b.X - a.X) / length, (b.Y - a.Y) / length, 0)
    tees = []
    for o in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        if eidv(o.Id) == target_wall_id:
            continue
        try:
            oc = o.Location.Curve
            oa, ob = oc.GetEndPoint(0), oc.GetEndPoint(1)
        except Exception:
            continue
        for pt in (oa, ob):
            s = (pt.X - a.X) * d.X + (pt.Y - a.Y) * d.Y      # along this wall
            perp = abs(-(pt.X - a.X) * d.Y + (pt.Y - a.Y) * d.X)
            if perp < 1.0 and 0.5 < s < length - 0.5:
                tees.append({"other": eidv(o.Id), "at_ft": round(s, 4),
                             "at_in": round(s * 12, 1), "perp_in": round(perp * 12, 2)})
    seen = set()
    uniq = []
    for t in sorted(tees, key=lambda r: r["at_ft"]):
        k = round(t["at_ft"], 2)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    res["partition_tees"] = uniq

    # The studs this wall actually has, read back from the model.
    st = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            c = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            cs = c.AsString() or ""
            if "WALL=W{}".format(target_wall_id) not in cs:
                continue
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = mk.AsString() if mk else ""
            if not m.startswith("ST-"):
                continue
            bb = ds.get_BoundingBox(None)
            cx = (bb.Min.X + bb.Max.X) / 2.0
            cy = (bb.Min.Y + bb.Max.Y) / 2.0
            s = (cx - a.X) * d.X + (cy - a.Y) * d.Y
            st.append(round(s * 12, 1))
        except Exception:
            continue
    res["stud_positions_in"] = sorted(set(st))
    res["stud_count"] = len(res["stud_positions_in"])

OUT = res
