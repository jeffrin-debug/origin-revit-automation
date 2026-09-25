# origin_bridge_read_selection.py - READ-ONLY. What is currently selected in the Revit UI?
# Reports enough to identify generated ORIGIN elements (host wall, face, kind, board id) as well as
# plain Revit elements (category + type).
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

items = []
ids = []
try:
    ids = list(uidoc.Selection.GetElementIds())
except Exception as ex:
    items.append({"error": "cannot read selection: " + str(ex)})


def eid_value(e):
    return e.IntegerValue if hasattr(e, "IntegerValue") else e.Value


for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    rec = {"id": eid_value(eid)}
    try:
        rec["class"] = e.GetType().Name
    except Exception:
        pass
    try:
        cat = e.Category
        rec["category"] = cat.Name if cat is not None else None
    except Exception:
        rec["category"] = None
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        rec["mark"] = p.AsString() if p else None
    except Exception:
        rec["mark"] = None
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        rec["comment"] = p.AsString() if p else None
    except Exception:
        rec["comment"] = None
    try:
        rec["name"] = e.Name
    except Exception:
        pass
    try:
        t = doc.GetElement(e.GetTypeId())
        if t is not None:
            tp = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
            rec["type"] = tp.AsString() if tp else None
    except Exception:
        pass
    try:
        bb = e.get_BoundingBox(None)
        if bb is not None:
            rec["bbox"] = [round(v, 3) for v in (bb.Min.X, bb.Min.Y, bb.Min.Z,
                                                 bb.Max.X, bb.Max.Y, bb.Max.Z)]
            rec["size_ft"] = [round(bb.Max.X - bb.Min.X, 3),
                              round(bb.Max.Y - bb.Min.Y, 3),
                              round(bb.Max.Z - bb.Min.Z, 3)]
    except Exception:
        pass
    # parse the ORIGIN comment schema when present
    c = rec.get("comment") or ""
    if "|" in c:
        toks = [t.strip() for t in c.split("|")]
        rec["origin"] = {"app_id": toks[0] if toks else None}
        for t in toks[1:]:
            if t.startswith("WALL="):
                rec["origin"]["host_wall"] = t[len("WALL="):]
            elif t.startswith("HOST="):
                rec["origin"]["host"] = t[len("HOST="):]
            elif t in ("DRYWALL", "GWB", "GWB2", "STUD", "TRACK", "HEADER", "SILL",
                       "KINGSTUD", "CRIPPLE", "GLASS", "FRAME", "COLUMN", "BEAM"):
                rec["origin"]["kind"] = t
            elif t.startswith("FACE_"):
                rec["origin"]["face"] = t
            elif t.startswith("t="):
                rec["origin"]["thickness"] = t[2:]
            elif t.startswith("cut="):
                rec["origin"]["is_cut"] = t[4:]
            elif t.startswith("typeX="):
                rec["origin"]["type_x"] = t[6:]
            elif t.startswith("waste="):
                rec["origin"]["waste"] = t[6:]
    items.append(rec)

# host walls referenced by the selection
hosts = {}
for it in items:
    hw = (it.get("origin") or {}).get("host_wall")
    if not hw:
        continue
    if hw in hosts:
        continue
    try:
        w = doc.GetElement(ElementId(int(hw.lstrip("W"))))
        if w is None:
            continue
        h = {"name": None, "mark": None, "width_in": None, "height_ft": None}
        try:
            h["name"] = w.Name
        except Exception:
            pass
        try:
            p = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            h["mark"] = p.AsString() if p else None
        except Exception:
            pass
        try:
            h["width_in"] = round(w.WallType.Width * 12.0, 2)
        except Exception:
            pass
        try:
            p = w.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
            h["height_ft"] = round(p.AsDouble(), 3) if p else None
        except Exception:
            pass
        hosts[hw] = h
    except Exception:
        pass

OUT = {"doc": doc.Title, "selection_count": len(ids), "items": items, "host_walls": hosts}
