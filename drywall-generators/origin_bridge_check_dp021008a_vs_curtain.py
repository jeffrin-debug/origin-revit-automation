# origin_bridge_check_dp021008a_vs_curtain.py - run via the ORIGIN Bridge. READ-ONLY.
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


board = None
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark == "DP-021-008A":
        board = e
        break

curtain = doc.GetElement(ElementId(388950))

out = {"board_found": board is not None, "curtain_found": curtain is not None}
if board is not None and curtain is not None:
    board_solids = solids_of(board)
    curtain_solids = []
    try:
        cg = curtain.CurtainGrid
        if cg is not None:
            for eid in list(cg.GetPanelIds()) + list(cg.GetMullionIds()):
                el = doc.GetElement(eid)
                if el is not None:
                    curtain_solids.extend(solids_of(el))
    except Exception as ex:
        out["curtain_geo_error"] = str(ex)
    if not curtain_solids:
        curtain_solids = solids_of(curtain)
    out["curtain_solid_count"] = len(curtain_solids)
    total = 0.0
    errs = []
    for a in board_solids:
        for b in curtain_solids:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
                if inter is not None:
                    total += inter.Volume
            except Exception as ex:
                errs.append(str(ex))
    out["overlap_cf"] = total
    out["errors"] = errs
    # Also just compare bboxes directly.
    bb = board.get_BoundingBox(None)
    cbb = curtain.get_BoundingBox(None)
    out["board_bbox"] = {"min": [round(bb.Min.X,4), round(bb.Min.Y,4), round(bb.Min.Z,4)],
                          "max": [round(bb.Max.X,4), round(bb.Max.Y,4), round(bb.Max.Z,4)]}
    out["curtain_wall_bbox"] = {"min": [round(cbb.Min.X,4), round(cbb.Min.Y,4), round(cbb.Min.Z,4)],
                                "max": [round(cbb.Max.X,4), round(cbb.Max.Y,4), round(cbb.Max.Z,4)]}

OUT = out
