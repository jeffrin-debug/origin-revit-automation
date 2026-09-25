# origin_bridge_describe_wall.py - run via the ORIGIN Bridge. READ-ONLY.
# Full inspection of the currently-selected wall (or a DP-*/ST-* DirectShape whose WALL= tag
# resolves to one), for the wall-by-wall rule-gathering review: real wall geometry/type/openings,
# its immediate neighbors at each end (corner/T-junction conditions), and every already-generated
# ST-*/DP-* element tagged to it (so we can compare real geometry vs current script output).
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


def eid_value(eid):
    try:
        return int(eid.Value)
    except Exception:
        pass
    try:
        return int(eid.IntegerValue)
    except Exception:
        return None


def safe_name(el):
    try:
        return el.Name
    except Exception:
        pass
    try:
        p = el.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p:
            return p.AsString()
    except Exception:
        pass
    try:
        p = el.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p:
            return p.AsString()
    except Exception:
        pass
    return None


def safe_str_param(el, bip):
    try:
        p = el.get_Parameter(bip)
        return p.AsString() if p else None
    except Exception:
        return None


def safe_double_param(el, bip):
    try:
        p = el.get_Parameter(bip)
        return p.AsDouble() if p else None
    except Exception:
        return None


def wall_endpoints(w):
    try:
        loc = w.Location
        curve = loc.Curve
        p0 = curve.GetEndPoint(0)
        p1 = curve.GetEndPoint(1)
        return (p0.X, p0.Y, p0.Z), (p1.X, p1.Y, p1.Z)
    except Exception:
        return None, None


def describe_wall(w):
    rec = {"element_id": eid_value(w.Id)}
    try:
        mk = w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        rec["mark"] = mk.AsString() if mk else None
    except Exception:
        rec["mark"] = None
    rec["instance_name"] = safe_name(w)
    wt = None
    try:
        wt = doc.GetElement(w.GetTypeId())
    except Exception:
        pass
    rec["wall_type_name"] = safe_name(wt) if wt is not None else None
    rec["width_in"] = round(w.Width * 12.0, 3) if hasattr(w, "Width") else None
    try:
        rec["unconnected_height_in"] = round(safe_double_param(w, BuiltInParameter.WALL_USER_HEIGHT_PARAM) * 12.0, 2)
    except Exception:
        rec["unconnected_height_in"] = None
    try:
        rec["base_offset_in"] = round(safe_double_param(w, BuiltInParameter.WALL_BASE_OFFSET) * 12.0, 2)
    except Exception:
        rec["base_offset_in"] = None
    try:
        rec["top_offset_in"] = round(safe_double_param(w, BuiltInParameter.WALL_TOP_OFFSET) * 12.0, 2)
    except Exception:
        rec["top_offset_in"] = None
    try:
        rec["structural_usage"] = str(w.StructuralUsage)
    except Exception:
        rec["structural_usage"] = None
    try:
        rec["is_exterior"] = str(w.WallType.Function) if wt is None else str(wt.Function)
    except Exception:
        rec["is_exterior"] = None
    try:
        fr = wt.get_Parameter(BuiltInParameter.FIRE_RATING) if wt is not None else None
        rec["fire_rating_param"] = fr.AsString() if fr else None
    except Exception:
        rec["fire_rating_param"] = None
    p0, p1 = wall_endpoints(w)
    rec["loc_p0"] = [round(v, 3) for v in p0] if p0 else None
    rec["loc_p1"] = [round(v, 3) for v in p1] if p1 else None
    if p0 and p1:
        rec["length_ft"] = round(((p1[0]-p0[0])**2 + (p1[1]-p0[1])**2) ** 0.5, 3)
    bb = w.get_BoundingBox(None)
    if bb is not None:
        rec["bbox"] = {"min": [round(bb.Min.X, 3), round(bb.Min.Y, 3), round(bb.Min.Z, 3)],
                        "max": [round(bb.Max.X, 3), round(bb.Max.Y, 3), round(bb.Max.Z, 3)]}

    # Hosted openings (doors/windows) on this wall
    openings = []
    try:
        for e in FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType():
            try:
                host = e.Host
            except Exception:
                host = None
            if host is None or eid_value(host.Id) != eid_value(w.Id):
                continue
            try:
                cat = e.Category.Name if e.Category else None
            except Exception:
                cat = None
            if cat not in ("Doors", "Windows"):
                continue
            osym = e.Symbol
            ow = safe_double_param(osym, BuiltInParameter.DOOR_WIDTH) or safe_double_param(osym, BuiltInParameter.WINDOW_WIDTH)
            oh = safe_double_param(osym, BuiltInParameter.DOOR_HEIGHT) or safe_double_param(osym, BuiltInParameter.WINDOW_HEIGHT)
            sill = safe_double_param(e, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
            openings.append({
                "category": cat, "type_name": safe_name(osym),
                "width_in": round(ow * 12.0, 2) if ow else None,
                "height_in": round(oh * 12.0, 2) if oh else None,
                "sill_height_in": round(sill * 12.0, 2) if sill is not None else None,
            })
    except Exception as ex:
        openings = [{"error": str(ex)}]
    rec["openings"] = openings

    return rec


def find_neighbors(w, tol=1.0):
    """Every OTHER wall whose location-line endpoint lands within tol ft of either of this
    wall's own endpoints - a corner/T-junction candidate."""
    p0, p1 = wall_endpoints(w)
    if p0 is None:
        return []
    neighbors = []
    for other in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        if eid_value(other.Id) == eid_value(w.Id):
            continue
        op0, op1 = wall_endpoints(other)
        if op0 is None:
            continue
        for myend, mylabel in ((p0, "P0"), (p1, "P1")):
            for oend, olabel in ((op0, "P0"), (op1, "P1")):
                d = ((myend[0]-oend[0])**2 + (myend[1]-oend[1])**2) ** 0.5
                if d <= tol:
                    try:
                        mk = other.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
                        omark = mk.AsString() if mk else None
                    except Exception:
                        omark = None
                    wt = None
                    try:
                        wt = doc.GetElement(other.GetTypeId())
                    except Exception:
                        pass
                    neighbors.append({
                        "my_end": mylabel, "other_end": olabel, "gap_ft": round(d, 3),
                        "other_mark": omark, "other_element_id": eid_value(other.Id),
                        "other_wall_type": safe_name(wt) if wt is not None else None,
                    })
    return neighbors


def find_generated_elements(w):
    """Every ST-*/DP-* DirectShape already tagged WALL=W<eid> for this wall."""
    tag = "WALL=W" + str(eid_value(w.Id))
    out = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        if not comments or tag not in comments:
            continue
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            mark = mk.AsString() if mk else None
        except Exception:
            mark = None
        bb = ds.get_BoundingBox(None)
        out.append({
            "mark": mark, "comments": comments,
            "size_ft": None if bb is None else [round(bb.Max.X-bb.Min.X, 3), round(bb.Max.Y-bb.Min.Y, 3), round(bb.Max.Z-bb.Min.Z, 3)],
        })
    out.sort(key=lambda r: r["mark"] or "")
    return out


ids = uidoc.Selection.GetElementIds()
result = {"selection_count": len(ids), "walls": []}
seen_walls = set()
for eid in ids:
    e = doc.GetElement(eid)
    if e is None:
        continue
    w = None
    if isinstance(e, Wall):
        w = e
    else:
        try:
            cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            comments = cm.AsString() if cm else None
        except Exception:
            comments = None
        if comments:
            for tok in comments.split("|"):
                tok = tok.strip()
                if tok.startswith("WALL=W"):
                    try:
                        wid = int(tok[6:])
                        cand = doc.GetElement(ElementId(wid))
                        if isinstance(cand, Wall):
                            w = cand
                    except Exception:
                        pass
    if w is None:
        continue
    wid = eid_value(w.Id)
    if wid in seen_walls:
        continue
    seen_walls.add(wid)
    entry = describe_wall(w)
    entry["neighbors"] = find_neighbors(w)
    entry["generated_elements"] = find_generated_elements(w)
    entry["generated_element_count"] = len(entry["generated_elements"])
    result["walls"].append(entry)

OUT = result
