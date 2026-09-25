# origin_bridge_check_exposed_studs.py - run via the ORIGIN Bridge. READ-ONLY.
# For each reported "exposed stud" mark, finds its real bbox and its host wall's own DP-* board
# coverage range on the relevant axis, to confirm whether the stud's own width overhangs past
# where the drywall boards on its host wall actually reach.
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

TARGET_STUDS = ["ST-070-002", "ST-067-002"]


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


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

out = []
for sm in TARGET_STUDS:
    ds = by_mark.get(sm)
    if ds is None:
        out.append({"stud": sm, "error": "not found"})
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    host = host_of(comments)
    bb = ds.get_BoundingBox(None)
    stud_bbox = {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                 "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]}

    board_bboxes = []
    if host is not None:
        for ds2 in all_ds:
            try:
                mk2 = ds2.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                mark2 = mk2.AsString() if mk2 else None
            except Exception:
                mark2 = None
            if not mark2 or not mark2.startswith("DP-"):
                continue
            try:
                cm2 = ds2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                comments2 = cm2.AsString() if cm2 else None
            except Exception:
                comments2 = None
            if host_of(comments2) != host:
                continue
            bb2 = ds2.get_BoundingBox(None)
            board_bboxes.append({
                "mark": mark2,
                "min": [round(bb2.Min.X, 4), round(bb2.Min.Y, 4), round(bb2.Min.Z, 4)],
                "max": [round(bb2.Max.X, 4), round(bb2.Max.Y, 4), round(bb2.Max.Z, 4)],
            })

    out.append({"stud": sm, "host": host, "stud_bbox": stud_bbox, "host_boards": board_bboxes})

OUT = {"results": out}
