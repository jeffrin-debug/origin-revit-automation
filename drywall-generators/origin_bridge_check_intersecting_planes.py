# origin_bridge_check_intersecting_planes.py - run via the ORIGIN Bridge. READ-ONLY.
# User selected DP-S001-003 and DP-021-008A, reporting they intersect and cross a curtain wall.
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


targets = ["DP-S001-003", "DP-021-008A"]
found = {}
elems = {}
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in targets:
        continue
    bb = e.get_BoundingBox(None)
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    found[mark] = {
        "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "comments": comments,
        "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)] if bb else None,
        "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)] if bb else None,
        "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)] if bb else None,
    }
    elems[mark] = e

# Real boolean intersection check between the two.
inter_info = None
if len(elems) == 2:
    s1 = solids_of(elems[targets[0]])
    s2 = solids_of(elems[targets[1]])
    total = 0.0
    for a in s1:
        for b in s2:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
                if inter is not None:
                    total += inter.Volume
            except Exception as ex:
                total = str(ex)
    inter_info = total

# Nearby curtain walls.
curtain_near = []
if "DP-021-008A" in found and found["DP-021-008A"]["x"]:
    bx = found["DP-021-008A"]["x"]
    by = found["DP-021-008A"]["y"]
    pad = 3.0
    rx0, rx1 = bx[0] - pad, bx[1] + pad
    ry0, ry1 = by[0] - pad, by[1] + pad
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            is_curtain = w.WallType.Kind == WallKind.Curtain
        except Exception:
            is_curtain = False
        if not is_curtain:
            continue
        wbb = w.get_BoundingBox(None)
        if wbb is None:
            continue
        if wbb.Max.X < rx0 or wbb.Min.X > rx1 or wbb.Max.Y < ry0 or wbb.Min.Y > ry1:
            continue
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        curtain_near.append({
            "mark": mark, "eid": w.Id.Value if hasattr(w.Id, "Value") else w.Id.IntegerValue,
            "x": [round(wbb.Min.X, 3), round(wbb.Max.X, 3)],
            "y": [round(wbb.Min.Y, 3), round(wbb.Max.Y, 3)],
            "z": [round(wbb.Min.Z, 3), round(wbb.Max.Z, 3)],
        })

OUT = {"found": found, "intersection_volume": inter_info, "curtain_walls_near": curtain_near}
