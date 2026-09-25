# origin_bridge_check_wall001_corners.py - run via the ORIGIN Bridge. READ-ONLY.
# DP-001-*B boards on wall 001 (eid 374947) are built with a 2.375in thickness instead of 0.5in,
# while DP-001-*A boards are correct. Checks the wall's own endpoints/orientation and every OTHER
# wall whose endpoint lands near either end, to see if this is a corner-specific condition.
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

WALL_EID = 374947
w = doc.GetElement(ElementId(WALL_EID))
out = {"exists": w is not None}
if w is not None:
    curve = w.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    out["p0"] = [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)]
    out["p1"] = [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)]
    out["width_in"] = round(w.Width * 12.0, 3)
    try:
        out["orientation"] = [round(w.Orientation.X, 4), round(w.Orientation.Y, 4), round(w.Orientation.Z, 4)]
    except Exception:
        pass

    neighbors = []
    tol = 1.0
    for other in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        if other.Id.IntegerValue == WALL_EID if hasattr(other.Id, "IntegerValue") else other.Id.Value == WALL_EID:
            continue
        try:
            oc = other.Location.Curve
            op0 = oc.GetEndPoint(0)
            op1 = oc.GetEndPoint(1)
        except Exception:
            continue
        for myend, mylabel in ((p0, "P0"), (p1, "P1")):
            for oend, olabel in ((op0, "P0"), (op1, "P1")):
                d = ((myend.X - oend.X) ** 2 + (myend.Y - oend.Y) ** 2) ** 0.5
                if d <= tol:
                    try:
                        mk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                        omark = mk.AsString() if mk else None
                    except Exception:
                        omark = None
                    try:
                        oeid = int(other.Id.Value) if hasattr(other.Id, "Value") else int(other.Id.IntegerValue)
                    except Exception:
                        oeid = None
                    try:
                        oorient = other.Orientation
                        oorient_v = [round(oorient.X, 4), round(oorient.Y, 4), round(oorient.Z, 4)]
                    except Exception:
                        oorient_v = None
                    neighbors.append({
                        "my_end": mylabel, "other_end": olabel, "gap_ft": round(d, 4),
                        "other_mark": omark, "other_eid": oeid, "other_orientation": oorient_v,
                        "other_width_in": round(other.Width * 12.0, 3),
                    })
    out["neighbors"] = neighbors

OUT = out
