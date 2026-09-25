# origin_bridge_find_host008.py - run via the ORIGIN Bridge. READ-ONLY.
# Finds the real Wall element behind host tag "008" (via ST-008-001's WALL= tag), dumps its full
# geometry/neighbors, and lists every ST-*/DP-* element currently tagged to it.
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


def eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        pass
    try:
        return int(eid.IntegerValue)
    except Exception:
        return None


wall_eid = None
elements = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-008-") or mark.startswith("ST-008-")):
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if wall_eid is None and comments:
        for tok in comments.split("|"):
            tok = tok.strip()
            if tok.startswith("WALL=W"):
                try:
                    wall_eid = int(tok[6:])
                except Exception:
                    pass
    bb = ds.get_BoundingBox(None)
    elements.append({
        "mark": mark, "comments": comments,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
            "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
    })
elements.sort(key=lambda r: r["mark"])

wall_info = None
neighbors = []
if wall_eid is not None:
    w = doc.GetElement(ElementId(wall_eid))
    if isinstance(w, Wall):
        loc = w.Location
        curve = loc.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        bb = w.get_BoundingBox(None)
        wall_info = {
            "element_id": wall_eid,
            "width_in": round(w.Width * 12.0, 3),
            "loc_p0": [round(p0.X, 3), round(p0.Y, 3), round(p0.Z, 3)],
            "loc_p1": [round(p1.X, 3), round(p1.Y, 3), round(p1.Z, 3)],
            "length_ft": round(((p1.X - p0.X) ** 2 + (p1.Y - p0.Y) ** 2) ** 0.5, 4),
            "bbox": None if bb is None else {
                "min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]},
        }
        tol = 1.0
        for other in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            if eid_value(other.Id) == wall_eid:
                continue
            oloc = other.Location
            ocurve = oloc.Curve
            op0 = ocurve.GetEndPoint(0)
            op1 = ocurve.GetEndPoint(1)
            for myend, mylabel in ((p0, "P0"), (p1, "P1")):
                for oend, olabel in ((op0, "P0"), (op1, "P1")):
                    dd = ((myend.X - oend.X) ** 2 + (myend.Y - oend.Y) ** 2) ** 0.5
                    if dd <= tol:
                        neighbors.append({
                            "my_end": mylabel, "other_end": olabel, "gap_ft": round(dd, 3),
                            "other_element_id": eid_value(other.Id),
                            "other_width_in": round(other.Width * 12.0, 3),
                        })

OUT = {"wall_eid": wall_eid, "wall_info": wall_info, "neighbors": neighbors, "elements": elements}
