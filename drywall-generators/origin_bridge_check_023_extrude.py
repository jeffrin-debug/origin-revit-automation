# origin_bridge_check_023_extrude.py - run via the ORIGIN Bridge. READ-ONLY.
# User-flagged: DP-023-001B and DP-023-002B look like they're "extruding" (sticking out wrong).
# Dumps their real bboxes/solid extents, their host wall's real geometry (width, curve), and the
# host wall's own framing (studs/tracks) for comparison, to find exactly what's wrong.
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

TARGET_MARKS = ["DP-023-001A", "DP-023-001B", "DP-023-002A", "DP-023-002B"]


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

out = []
hosts = set()
ds_by_mark = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in TARGET_MARKS:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    host = host_of(comments)
    if host:
        hosts.add(host)
    ds_by_mark[mark] = ds
    bb = ds.get_BoundingBox(None)
    entry = {
        "mark": mark, "comments": comments, "host": host,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    }
    try:
        opt = Options()
        geo = ds.get_Geometry(opt)
        solids = [g for g in geo if isinstance(g, Solid) and g.Volume > 1e-9] if geo else []
        entry["solid_count"] = len(solids)
        entry["total_volume_cf"] = round(sum(s.Volume for s in solids), 5)
    except Exception as ex:
        entry["geo_error"] = str(ex)
    out.append(entry)
out.sort(key=lambda r: r["mark"])

wall_info = []
for h in sorted(hosts):
    if not h.startswith("WALL=W"):
        continue
    try:
        eid = int(h.replace("WALL=W", ""))
    except Exception:
        continue
    w = doc.GetElement(ElementId(eid))
    if isinstance(w, Wall):
        curve = w.Location.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        wall_info.append({
            "host": h, "eid": eid, "width_in": round(w.Width * 12.0, 3),
            "p0": [round(p0.X, 4), round(p0.Y, 4), round(p0.Z, 4)],
            "p1": [round(p1.X, 4), round(p1.Y, 4), round(p1.Z, 4)],
            "wall_type": w.WallType.Kind.ToString() if w.WallType else None,
        })

# Real framing (studs/tracks) on the same host, for face-position comparison.
framing = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("ST-023-"):
        continue
    bb = ds.get_BoundingBox(None)
    framing.append({
        "mark": mark,
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    })
framing.sort(key=lambda r: r["mark"])

OUT = {"elements": out, "wall_info": wall_info, "framing_sample": framing[:6]}
