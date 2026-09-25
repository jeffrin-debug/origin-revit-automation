# origin_bridge_check_small_studs.py - run via the ORIGIN Bridge. READ-ONLY.
# User flagged ST-015-003 and ST-053-003 as tiny sliver studs that read as "different" from their
# neighbor wall surface - a sim-robot-relevant concern (a small gap/odd piece could misread as a
# real discontinuity to spray/navigation logic, or break continuous texture application). Ground-
# truths their real geometry, their host wall, their Comments (real member kind), and every other
# framing/drywall element within 1ft, to find WHY each one came out small and whether the pattern
# repeats elsewhere in this building.
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

TARGET_MARKS = ["ST-015-003", "ST-053-003"]

all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
by_mark = {}
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark:
        by_mark[mark] = ds

out = {"targets": {}}


def rec_of(ds):
    bb = ds.get_BoundingBox(None)
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    size = [round(bb.Max.X - bb.Min.X, 4), round(bb.Max.Y - bb.Min.Y, 4), round(bb.Max.Z - bb.Min.Z, 4)]
    return {
        "comments": comments,
        "size_ft": size,
        "bbox": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                 "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]},
    }


for mark in TARGET_MARKS:
    ds = by_mark.get(mark)
    if ds is None:
        out["targets"][mark] = {"error": "not found"}
        continue
    trec = rec_of(ds)
    out["targets"][mark] = trec
    bb = ds.get_BoundingBox(None)
    pad = 1.0
    nearby = []
    for other_mark, ods in by_mark.items():
        if other_mark == mark:
            continue
        obb = ods.get_BoundingBox(None)
        if (obb.Max.X < bb.Min.X - pad or obb.Min.X > bb.Max.X + pad or
                obb.Max.Y < bb.Min.Y - pad or obb.Min.Y > bb.Max.Y + pad or
                obb.Max.Z < bb.Min.Z - pad or obb.Min.Z > bb.Max.Z + pad):
            continue
        nearby.append({"mark": other_mark, **rec_of(ods)})
    trec["nearby_within_1ft"] = nearby

# Also: how many ST-* elements building-wide have a "small" long dimension (< 6in), to see if
# this is a widespread pattern or just these two.
small_studs = []
for mark, ds in by_mark.items():
    if not mark.startswith("ST-"):
        continue
    bb = ds.get_BoundingBox(None)
    size = sorted([bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z])
    long_dim = size[-1]
    short_dims = size[:-1]
    # a "sliver" here means its long dimension itself is small (well under a typical stud run),
    # not just its cross-section - i.e. a stud/track that's short along its own length.
    if long_dim < 1.0:
        small_studs.append({"mark": mark, "long_dim_ft": round(long_dim, 4)})

out["building_wide_ST_elements_with_long_dim_under_1ft"] = {
    "count": len(small_studs),
    "sample": small_studs[:30],
}

OUT = out
