# origin_bridge_check_flush_against_wall.py - run via the ORIGIN Bridge. READ-ONLY.
# For DP-006-002A (host wall 380104) and DP-023-006B (host wall 401091), compares the board's
# real Y (or X) position against its host wall's true face position, to check whether the board
# actually sits flush on the wall or is floating away from it - the "Walls" category is hidden in
# the ORIGIN Assembly view, so a correctly-flush jamb piece can visually look like it's floating
# with no wall context behind it.
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


def wall_info(wid):
    w = doc.GetElement(ElementId(wid))
    if w is None:
        return {"exists": False}
    curve = w.Location.Curve
    p0 = curve.GetEndPoint(0)
    p1 = curve.GetEndPoint(1)
    width = w.Width
    orient = w.Orientation
    # centerline location -> exterior/interior face offsets (assuming Location Line = wall
    # centerline for this check; face = centerline +/- width/2 along Orientation)
    cx = (p0.X + p1.X) / 2.0
    cy = (p0.Y + p1.Y) / 2.0
    return {
        "exists": True, "p0": [round(p0.X, 4), round(p0.Y, 4)], "p1": [round(p1.X, 4), round(p1.Y, 4)],
        "width_ft": round(width, 4), "orientation": [round(orient.X, 4), round(orient.Y, 4)],
        "face_plus": [round(cx + orient.X * width / 2.0, 4), round(cy + orient.Y * width / 2.0, 4)],
        "face_minus": [round(cx - orient.X * width / 2.0, 4), round(cy - orient.Y * width / 2.0, 4)],
    }


def board_info(eid):
    e = doc.GetElement(ElementId(eid))
    bb = e.get_BoundingBox(None)
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    return {
        "bbox_min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
        "bbox_max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)],
        "comments": comments,
    }


OUT = {
    "DP-006-002A": {"board": board_info(412520), "host_wall_006": wall_info(380104)},
    "DP-023-006B": {"board": board_info(412788), "host_wall_023": wall_info(401091)},
}
