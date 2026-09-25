# origin_bridge_check_black_panel.py - run via the ORIGIN Bridge. READ-ONLY.
# User sees dark/black unshaded surfaces where drywall is expected, status bar showed DP-S001-003.
# Ground-truths: does DP-S001-003 exist, what's its real material/volume/bbox, and are ALL soffit
# boards (DP-S001-*) correctly materialed - looking for any board with a missing/invalid material
# (which renders as flat black/undifferentiated in Revit), same root cause class as the earlier
# "column looked like plain wall" bug (create_ds never assigned a material).
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


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

soffit_boards = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not mark.startswith("DP-S"):
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
    bb = ds.get_BoundingBox(None)
    solids = solids_of(ds)
    soffit_boards.append({
        "mark": mark,
        "comments": comments,
        "materials": mat_names,
        "solid_count": len(solids),
        "total_volume_cf": round(sum(s.Volume for s in solids), 4),
        "bbox_ft": {"min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
                    "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)]} if bb else None,
    })

soffit_boards.sort(key=lambda r: r["mark"])
no_material = [b for b in soffit_boards if not b["materials"]]

OUT = {"soffit_board_count": len(soffit_boards), "boards_with_no_material": no_material,
       "all_soffit_boards": soffit_boards}
