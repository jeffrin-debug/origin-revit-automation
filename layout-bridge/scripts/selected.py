# selected.py - report the currently selected elements (read-only).
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def ename(e):
    try:
        return e.Name
    except Exception:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME) or e.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() if p else "?"


def pval(e, bip):
    p = e.get_Parameter(bip)
    return None if p is None else p.AsDouble()


out = []
for eid in uidoc.Selection.GetElementIds():
    e = doc.GetElement(eid)
    item = {"id": eid.Value, "category": e.Category.Name if e.Category else None}
    if isinstance(e, Wall):
        c = e.Location.Curve
        item.update({
            "mark": e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString(),
            "type": ename(e.WallType),
            "length_param_in": round(pval(e, BuiltInParameter.CURVE_ELEM_LENGTH) * 12, 3),
            "centerline_in": round(c.Length * 12, 3),
            "unconnected_height_in": round(pval(e, BuiltInParameter.WALL_USER_HEIGHT_PARAM) * 12, 3),
            "base_offset_in": round(pval(e, BuiltInParameter.WALL_BASE_OFFSET) * 12, 3),
            "top_constraint": str(e.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE).AsValueString()),
            "thickness_in": round(e.Width * 12, 3),
        })
    out.append(item)
OUT = {"doc": doc.Title, "selected": out}
