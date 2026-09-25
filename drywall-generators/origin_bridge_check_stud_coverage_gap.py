# origin_bridge_check_stud_coverage_gap.py - run via the ORIGIN Bridge. READ-ONLY.
# For wall 006 (face A, near DP-006-002A) and wall 023 (face B, near DP-023-006B), checks every
# same-host STUD (not track/header/etc) for whether it is fully covered, along its own X-range and
# full Z-height, by the union of that face's drywall boards - i.e. hunts for an exposed-stud
# coverage gap: "drywall panel ends, small gap, then a stud is visible again" (user report).
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

TARGETS = [
    {"host": "WALL=W380104", "face_suffix": "A", "wall_tag": "006"},
    {"host": "WALL=W401091", "face_suffix": "B", "wall_tag": "023"},
]


def parse_comments(comments):
    tok = {}
    parts = [p.strip() for p in comments.split("|")]
    return parts


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

results = []
for t in TARGETS:
    studs = []
    boards = []
    for ds in all_ds:
        try:
            cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        if not comments or t["host"] not in comments:
            continue
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        if not mark:
            continue
        bb = ds.get_BoundingBox(None)
        if bb is None:
            continue
        if mark.startswith("ST-"):
            parts = parse_comments(comments)
            kind = parts[3] if len(parts) > 3 else None
            if kind != "STUD":
                continue
            studs.append({"mark": mark, "bbox": bb})
        elif mark.startswith("DP-") and mark.endswith(t["face_suffix"]):
            boards.append({"mark": mark, "bbox": bb})

    gaps = []
    for s in studs:
        sb = s["bbox"]
        sx0, sx1 = sb.Min.X, sb.Max.X
        sz0, sz1 = sb.Min.Z, sb.Max.Z
        # Union of Z-coverage from boards whose X-range overlaps this stud's X-range.
        covering_intervals = []
        for b in boards:
            bb2 = b["bbox"]
            if bb2.Max.X < sx0 + 0.02 or bb2.Min.X > sx1 - 0.02:
                continue    # doesn't meaningfully cover this stud's X-span
            covering_intervals.append((max(bb2.Min.Z, sz0), min(bb2.Max.Z, sz1)))
        covering_intervals.sort()
        merged = []
        for (a0, a1) in covering_intervals:
            if merged and a0 <= merged[-1][1] + 1e-6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], a1))
            else:
                merged.append((a0, a1))
        covered = sum(max(0.0, a1 - a0) for (a0, a1) in merged)
        total = sz1 - sz0
        uncovered = total - covered
        if uncovered > 0.02:   # more than ~1/4in of real exposed height
            gaps.append({
                "stud": s["mark"], "stud_x": [round(sx0, 4), round(sx1, 4)],
                "stud_z": [round(sz0, 4), round(sz1, 4)],
                "covered_intervals": [[round(a, 4), round(b, 4)] for (a, b) in merged],
                "uncovered_ft": round(uncovered, 4),
            })
    results.append({
        "wall_tag": t["wall_tag"], "face": t["face_suffix"],
        "stud_count": len(studs), "board_count": len(boards),
        "exposed_studs": gaps,
    })

OUT = {"results": results}
