# origin_bridge_check_walls_inside_board.py - run via the ORIGIN Bridge. READ-ONLY.
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

BOARDS = {
    "DP-S001-001": (-50.524, 5.662, -34.524, 15.579),
    "DP-S001-013": (-28.524, 1.913, -15.024, 9.163),
}

results = {}
for name, (bx0, by0, bx1, by1) in BOARDS.items():
    hits = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        try:
            curve = w.Location.Curve
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
        except Exception:
            continue
        wx0, wx1 = sorted([p0.X, p1.X])
        wy0, wy1 = sorted([p0.Y, p1.Y])
        hw = w.Width / 2.0
        wx0 -= hw; wx1 += hw; wy0 -= hw; wy1 += hw
        # does this wall's REAL footprint fall (even partially) within the board's bbox interior
        # (not just touching the very edge)?
        pad = -0.1   # shrink the board slightly so we only catch walls truly INSIDE, not edge-touching
        ibx0, iby0, ibx1, iby1 = bx0 - pad, by0 - pad, bx1 + pad, by1 + pad
        if wx1 <= ibx0 + 0.15 or wx0 >= ibx1 - 0.15 or wy1 <= iby0 + 0.15 or wy0 >= iby1 - 0.15:
            continue
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        try:
            is_curtain = w.WallType.Kind == WallKind.Curtain
        except Exception:
            is_curtain = None
        wbb = w.get_BoundingBox(None)
        hits.append({
            "mark": mark, "eid": w.Id.Value if hasattr(w.Id, "Value") else w.Id.IntegerValue,
            "x": [round(wx0, 3), round(wx1, 3)], "y": [round(wy0, 3), round(wy1, 3)],
            "z": [round(wbb.Min.Z, 3), round(wbb.Max.Z, 3)] if wbb else None,
            "is_curtain": is_curtain,
        })
    results[name] = hits

OUT = results
