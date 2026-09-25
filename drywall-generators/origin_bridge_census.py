# origin_bridge_census.py - read-only model census, run via the ORIGIN Bridge.
# Proves the live link and gives an instant inventory of the open model.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def count(bic):
    try:
        return FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().GetElementCount()
    except Exception:
        return -1


def count_cls(cls):
    try:
        return FilteredElementCollector(doc).OfClass(cls).WhereElementIsNotElementType().GetElementCount()
    except Exception:
        return -1


walls = []
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        bo = w.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        walls.append({
            "id": w.Id.Value if hasattr(w.Id, "Value") else w.Id.IntegerValue,
            "type": w.Name,
            "base_offset_ft": round(bo.AsDouble(), 2) if bo else 0.0,
        })
    except Exception:
        continue

OUT = {
    "doc": doc.Title,
    "active_view": doc.ActiveView.Name,
    "selection": len(list(uidoc.Selection.GetElementIds())),
    "counts": {
        "walls": count_cls(Wall),
        "ceilings": count_cls(Ceiling),
        "columns": count(BuiltInCategory.OST_Columns),
        "structural_columns": count(BuiltInCategory.OST_StructuralColumns),
        "structural_framing": count(BuiltInCategory.OST_StructuralFraming),
        "rooms": count(BuiltInCategory.OST_Rooms),
        "doors": count(BuiltInCategory.OST_Doors),
        "windows": count(BuiltInCategory.OST_Windows),
        "electrical_fixtures": count(BuiltInCategory.OST_ElectricalFixtures),
        "generic_models": count(BuiltInCategory.OST_GenericModel),
    },
    "walls_detail": walls,
}
