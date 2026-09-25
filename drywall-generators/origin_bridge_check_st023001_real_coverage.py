# origin_bridge_check_st023001_real_coverage.py - run via the ORIGIN Bridge. READ-ONLY.
# Direct boolean check: is ST-023-001 (wall 023's own end stud) ACTUALLY, physically covered by
# ANY drywall board in the model right now (regardless of host), or is it genuinely exposed?
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


def solids_of(e):
    out = []
    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    out.append(g2)
    return out


stud = None
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark == "ST-023-001":
        stud = ds
        break

out = {"stud_found": stud is not None}
if stud is not None:
    stud_solids = solids_of(stud)
    sbb = stud.get_BoundingBox(None)
    out["stud_bbox"] = {"min": [round(sbb.Min.X, 4), round(sbb.Min.Y, 4), round(sbb.Min.Z, 4)],
                        "max": [round(sbb.Max.X, 4), round(sbb.Max.Y, 4), round(sbb.Max.Z, 4)]}
    pad = 0.05
    coverers = []
    total_covered_solid = None
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if not mark or not mark.startswith("DP-"):
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        if (bb.Max.X < sbb.Min.X - pad or bb.Min.X > sbb.Max.X + pad or
                bb.Max.Y < sbb.Min.Y - pad or bb.Min.Y > sbb.Max.Y + pad or
                bb.Max.Z < sbb.Min.Z - pad or bb.Min.Z > sbb.Max.Z + pad):
            continue
        board_solids = solids_of(ds)
        for ssol in stud_solids:
            for bsol in board_solids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        ssol, bsol, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > 1e-7:
                        coverers.append({"board": mark, "overlap_cf": round(inter.Volume, 6)})
                except Exception as ex:
                    coverers.append({"board": mark, "error": str(ex)})
    out["coverers"] = coverers
    out["stud_volume_cf"] = round(sum(s.Volume for s in stud_solids), 6)

OUT = out
