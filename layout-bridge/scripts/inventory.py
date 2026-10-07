# inventory.py - read-only: which model is open and which layout elements it holds, by room tag.
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
cats = {"walls": BuiltInCategory.OST_Walls, "doors": BuiltInCategory.OST_Doors,
        "ceilings": BuiltInCategory.OST_Ceilings, "floors": BuiltInCategory.OST_Floors,
        "rooms": BuiltInCategory.OST_Rooms, "generic_models": BuiltInCategory.OST_GenericModel}
by_tag = {}
untagged = {}
for cname, cat in cats.items():
    for e in FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType():
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        tag = (p.AsString() if p else None) or ""
        if tag.startswith("ORIGIN_LAYOUT_"):
            by_tag.setdefault(tag, {}).setdefault(cname, 0)
            by_tag[tag][cname] += 1
        else:
            untagged[cname] = untagged.get(cname, 0) + 1
rooms = [{"number": r.Number, "name": r.get_Parameter(BuiltInParameter.ROOM_NAME).AsString(),
          "area_sf": round(r.Area, 3)}
         for r in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()]
OUT = {"doc": doc.Title, "path": doc.PathName, "modified": doc.IsModified,
       "layouts": by_tag, "other_elements": untagged, "rooms": rooms}
