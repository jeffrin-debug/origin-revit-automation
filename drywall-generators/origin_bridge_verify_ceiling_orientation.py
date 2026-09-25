# origin_bridge_verify_ceiling_orientation.py - run via the ORIGIN Bridge. READ-ONLY.
# For every ceiling host, dumps the long-axis orientation of its drywall boards vs its furring
# members, to confirm they are now PERPENDICULAR (the corrected rule) rather than parallel.
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

by_host = {}
for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if not comments or "CEILING=" not in comments:
        continue
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    host = None
    kind = None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("CEILING="):
            host = tok
        if tok in ("DRYWALL", "FURRING", "MAIN", "HANGER"):
            kind = tok
    if host is None or kind not in ("DRYWALL", "FURRING", "MAIN"):
        continue
    bb = e.get_BoundingBox(None)
    if bb is None:
        continue
    xs = bb.Max.X - bb.Min.X
    ys = bb.Max.Y - bb.Min.Y
    long_axis = "X" if xs >= ys else "Y"
    rec = by_host.setdefault(host, {"DRYWALL": [], "FURRING": [], "MAIN": []})
    rec[kind].append({"mark": mark, "x_span": round(xs, 3), "y_span": round(ys, 3), "long_axis": long_axis})

out = {}
for host, rec in by_host.items():
    dp_axes = set(r["long_axis"] for r in rec["DRYWALL"])
    fur_axes = set(r["long_axis"] for r in rec["FURRING"])
    main_axes = set(r["long_axis"] for r in rec["MAIN"])
    out[host] = {
        "drywall_long_axes": sorted(dp_axes), "furring_long_axes": sorted(fur_axes),
        "main_long_axes": sorted(main_axes),
        "furring_perpendicular_to_drywall": (len(dp_axes) == 1 and len(fur_axes) == 1 and
                                             list(dp_axes)[0] != list(fur_axes)[0]) if dp_axes and fur_axes else None,
        "sample_drywall": rec["DRYWALL"][:2], "sample_furring": rec["FURRING"][:2],
        "sample_main": rec["MAIN"][:2],
    }

OUT = out
