# origin_bridge_check_401492_framing.py - run via the ORIGIN Bridge. READ-ONLY.
# Checks whether wall 401492 (the ~1in sliver wall on "Project8") has any real framing members
# (STUD/KINGSTUD/CRIPPLE/TRACK), to confirm it's safe to delete its fully-redundant DP boards
# without leaving a real coverage gap.
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

TARGET_HOST = "WALL=W401492"


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


def kind_of(comments):
    if not comments:
        return None
    toks = [t.strip() for t in comments.split("|")]
    for t in toks:
        if t in ("STUD", "TRACK", "HEADER", "SILL", "KINGSTUD", "CRIPPLE"):
            return t
    return None


out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    if host_of(comments) != TARGET_HOST:
        continue
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    out.append({"mark": mark, "kind": kind_of(comments), "comments": comments})
out.sort(key=lambda r: r["mark"] or "")

OUT = {"host": TARGET_HOST, "elements": out}
