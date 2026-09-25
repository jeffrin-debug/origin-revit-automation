# origin_bridge_check_stud_material.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms ST-012-003 (and the rest of the soffit band walls' framing) now carries the drywall
# material instead of "ORIGIN Stud", and that a NORMAL wall's stud is UNCHANGED (still steel-colored)
# - proves the fix is scoped to soffit band walls only, not applied building-wide.
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

CHECK_MARKS = ["ST-012-003", "ST-012-001", "ST-005-001", "ST-006-001", "ST-001-001", "ST-003-001"]

out = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if mark not in CHECK_MARKS:
        continue
    try:
        cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        comments = cm.AsString() if cm else None
    except Exception:
        comments = None
    try:
        mat_ids = ds.GetMaterialIds(False)
        mat_names = [doc.GetElement(m).Name for m in mat_ids]
    except Exception as ex:
        mat_names = ["ERR: {}".format(ex)]
    out.append({"mark": mark, "comments": comments, "materials": mat_names})

OUT = {"results": out}
