# origin_bridge_check_wall001_new_env.py - run via the ORIGIN Bridge. READ-ONLY.
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


targets = ["ST-001-001", "DP-001-001A", "DP-001-001B"]
found = {}
wall_eid = None
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
    if mark == "ST-001-001" and comments:
        for tok in comments.split("|"):
            tok = tok.strip()
            if tok.startswith("WALL=W"):
                wall_eid = int(tok[6:])
    found[mark] = {
        "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "comments": comments,
        "x": [round(bb.Min.X, 4), round(bb.Max.X, 4)] if bb else None,
        "y": [round(bb.Min.Y, 4), round(bb.Max.Y, 4)] if bb else None,
        "z": [round(bb.Min.Z, 4), round(bb.Max.Z, 4)] if bb else None,
    }

out = {"found": found}
if wall_eid is not None:
    w = doc.GetElement(ElementId(wall_eid))
    if w is not None:
        out["wall_width_in"] = round(w.Width * 12.0, 4)
        try:
            wt = doc.GetElement(w.GetTypeId())
            out["wall_type_name"] = wt.Name if wt else None
        except Exception:
            pass

if "ST-001-001" in found and "DP-001-001A" in found:
    st = None
    dp = None
    for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if mark == "ST-001-001":
            st = e
        elif mark == "DP-001-001A":
            dp = e
    if st and dp:
        ssolids = solids_of(st)
        dsolids = solids_of(dp)
        total = 0.0
        for a in ssolids:
            for b in dsolids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
                    if inter is not None:
                        total += inter.Volume
                except Exception:
                    pass
        out["st_vs_dpA_overlap_cf"] = total

OUT = out
