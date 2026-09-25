# origin_bridge_scan_all_corner_gaps.py - run via the ORIGIN Bridge. READ-ONLY.
# Model-wide scan: for every pair of DP-* drywall boards belonging to DIFFERENT wall hosts, whose
# bboxes overlap in Z and are within a small XY distance of each other (candidate neighbors at a
# corner/junction), measures the real bbox gap. Reports every pair with a small (0 < gap <= 6in)
# real gap - the exact class of "uncovered notch" issue found at wall 014's corner - so we know
# the true extent of the pattern across this whole environment before designing a general fix.
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


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


def min_face_gap_xy(b1, b2):
    gaps = []
    for lo1, hi1, lo2, hi2 in [(b1.Min.X, b1.Max.X, b2.Min.X, b2.Max.X),
                                (b1.Min.Y, b1.Max.Y, b2.Min.Y, b2.Max.Y)]:
        gaps.append(max(lo1 - hi2, lo2 - hi1, 0.0))
    return max(gaps)


def z_overlaps(b1, b2):
    return not (b1.Max.Z <= b2.Min.Z or b2.Max.Z <= b1.Min.Z)


boards = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-"):
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    host = host_of(comments)
    if host is None:
        continue
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    boards.append((mark, host, bb))

pad = 0.5
findings = []
seen_pairs = set()
for i in range(len(boards)):
    m1, h1, b1 = boards[i]
    for j in range(i + 1, len(boards)):
        m2, h2, b2 = boards[j]
        if h1 == h2:
            continue  # same wall, not a cross-wall corner condition
        if not z_overlaps(b1, b2):
            continue
        # broad-phase XY reject
        if (b1.Max.X < b2.Min.X - pad or b2.Max.X < b1.Min.X - pad or
                b1.Max.Y < b2.Min.Y - pad or b2.Max.Y < b1.Min.Y - pad):
            continue
        gap_ft = min_face_gap_xy(b1, b2)
        gap_in = gap_ft * 12.0
        if 0.05 < gap_in <= 6.0:  # a real, small, nonzero gap - not touching, not far
            key = tuple(sorted([m1, m2]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            findings.append({
                "a": m1, "a_host": h1, "b": m2, "b_host": h2,
                "gap_in": round(gap_in, 4),
            })

findings.sort(key=lambda f: f["gap_in"])
OUT = {"total_boards_scanned": len(boards), "small_gap_pair_count": len(findings), "findings": findings[:60]}
