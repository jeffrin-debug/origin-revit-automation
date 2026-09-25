# origin_bridge_probe_selection3.py - run via the ORIGIN Bridge. READ-ONLY.
# Reports the currently selected DirectShape board(s) - mark, comments, real bbox/size - plus,
# for any board belonging to a Ceiling host, the real host Ceiling's own footprint and every wall
# whose bbox overlaps that footprint, so we can see exactly which walls are chopping the ceiling
# into small pieces.
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

ids = uidoc.Selection.GetElementIds()
out = {"count": len(ids), "elements": []}
host_eids = set()
for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    bb = e.get_BoundingBox(None)
    rec = {"mark": mark, "comments": comments}
    if bb is not None:
        size = [round(bb.Max.X - bb.Min.X, 3), round(bb.Max.Y - bb.Min.Y, 3), round(bb.Max.Z - bb.Min.Z, 3)]
        rec["size_ft"] = size
        rec["area_sf_largest_face"] = round(sorted(size)[2] * sorted(size)[1], 3)
        rec["bbox"] = {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                        "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}
    out["elements"].append(rec)
    if comments and "CEILING=" in comments:
        try:
            token = [t.strip() for t in comments.split("|") if "CEILING=" in t][0]
            host_eids.add(int(token.split("=")[1].replace("C", "")))
        except Exception:
            pass

# For the host ceiling(s), report its real footprint and every overlapping wall's bbox.
out["host_ceilings"] = []
for heid in host_eids:
    c = doc.GetElement(ElementId(heid))
    if c is None:
        continue
    bb = c.get_BoundingBox(None)
    crec = {"eid": heid,
            "bbox": {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                     "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}}
    overlapping_walls = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        wbb = w.get_BoundingBox(None)
        if wbb is None:
            continue
        if (wbb.Max.X < bb.Min.X or wbb.Min.X > bb.Max.X or
                wbb.Max.Y < bb.Min.Y or wbb.Min.Y > bb.Max.Y):
            continue
        try:
            mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            wtag = mk.AsString() if mk else None
        except Exception:
            wtag = None
        overlapping_walls.append({
            "wall_tag": wtag,
            "bbox_xy": {"min": [round(wbb.Min.X, 3), round(wbb.Min.Y, 3)],
                        "max": [round(wbb.Max.X, 3), round(wbb.Max.Y, 3)]},
        })
    crec["overlapping_wall_count"] = len(overlapping_walls)
    crec["overlapping_walls"] = overlapping_walls
    out["host_ceilings"].append(crec)

OUT = out
