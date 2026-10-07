# probe.py - report what the open model offers for building a layout (read-only).
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

def name(e):
    try:
        return e.Name
    except Exception:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME) or e.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        return p.AsString() if p else "?"

levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
wall_types = [wt for wt in FilteredElementCollector(doc).OfClass(WallType) if wt.Kind == WallKind.Basic]
door_syms = FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(BuiltInCategory.OST_Doors)
ceil_types = FilteredElementCollector(doc).OfClass(CeilingType)
floor_types = FilteredElementCollector(doc).OfClass(FloorType)

OUT = {
    "doc": doc.Title,
    "path": doc.PathName,
    "units_length": str(doc.GetUnits().GetFormatOptions(SpecTypeId.Length).GetUnitTypeId().TypeId),
    "levels": [[name(l), round(l.Elevation, 4)] for l in levels],
    "wall_types": [[name(w), round(w.Width * 12, 3)] for w in wall_types],
    "door_types": ["{} : {}".format(s.Family.Name, name(s)) for s in door_syms],
    "ceiling_types": [name(c) for c in ceil_types],
    "floor_types": [name(f) for f in floor_types],
    "walls_in_model": FilteredElementCollector(doc).OfClass(Wall).GetElementCount(),
}
