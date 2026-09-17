# diag_rough_opening_params.py - READ-ONLY.
# Do this model's window/door families actually carry a rough-opening size? If they do, the
# drywall cut can be sized from that instead of from the instance bounding box, which is what
# currently swallows the jamb studs at windows.
#
# Reports, per insert: the bbox width/height measured along its host wall, and every candidate
# size parameter, so the gap between "what the family says" and "what the bbox says" is visible.
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
IN = 12.0

# Built-in parameter names differ between Revit versions - FAMILY_ROUGH_WIDTH does not exist in
# this one - so every candidate is resolved through getattr and simply skipped if absent, and the
# real answer comes from enumerating whatever the families actually carry (see dump_params).
CANDIDATE_BIP_NAMES = [
    "FAMILY_ROUGH_WIDTH", "FAMILY_ROUGH_HEIGHT",
    "WINDOW_WIDTH", "WINDOW_HEIGHT",
    "DOOR_WIDTH", "DOOR_HEIGHT",
    "GENERIC_WIDTH", "GENERIC_HEIGHT",
    "FAMILY_WIDTH_PARAM", "FAMILY_HEIGHT_PARAM",
]
TYPE_PARAMS = []
for _n in CANDIDATE_BIP_NAMES:
    _b = getattr(BuiltInParameter, _n, None)
    if _b is not None:
        TYPE_PARAMS.append((_n, _b))


def dump_params(el, want=("rough", "width", "height", "opening")):
    """Every parameter whose NAME mentions a size concept, with its value in inches. This is what
    actually tells us which families carry a usable rough-opening dimension."""
    out = {}
    if el is None:
        return out
    try:
        for p in el.Parameters:
            try:
                nm = p.Definition.Name
            except Exception:
                continue
            low = nm.lower()
            if not any(w in low for w in want):
                continue
            try:
                if not p.HasValue:
                    continue
                if p.StorageType == StorageType.Double:
                    out[nm] = round(p.AsDouble() * IN, 3)
                elif p.StorageType == StorageType.String:
                    out[nm] = p.AsString()
                elif p.StorageType == StorageType.Integer:
                    out[nm] = p.AsInteger()
            except Exception:
                continue
    except Exception:
        pass
    return out


def pnum(el, bip):
    try:
        p = el.get_Parameter(bip)
        if p is None or not p.HasValue:
            return None
        v = p.AsDouble()
        return round(v * IN, 3) if v else None
    except Exception:
        return None


def by_name(el, name):
    try:
        p = el.LookupParameter(name)
        if p is None or not p.HasValue:
            return None
        return round(p.AsDouble() * IN, 3)
    except Exception:
        return None


rows = []
for bic in (BuiltInCategory.OST_Windows, BuiltInCategory.OST_Doors):
    for e in (FilteredElementCollector(doc).OfCategory(bic)
              .WhereElementIsNotElementType()):
        rec = {"category": ("Window" if bic == BuiltInCategory.OST_Windows else "Door")}
        try:
            rec["id"] = e.Id.IntegerValue if hasattr(e.Id, "IntegerValue") else e.Id.Value
        except Exception:
            pass
        sym = None
        try:
            sym = e.Symbol
            rec["family"] = sym.Family.Name
            rec["type"] = sym.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        except Exception:
            pass

        # bbox measured ALONG the host wall, which is what the generator uses today
        try:
            host = e.Host
            crv = host.Location.Curve
            p0 = crv.GetEndPoint(0)
            p1 = crv.GetEndPoint(1)
            L = crv.Length
            ux, uy = (p1.X - p0.X) / L, (p1.Y - p0.Y) / L
            bb = e.get_BoundingBox(None)
            ts = []
            for (x, y) in ((bb.Min.X, bb.Min.Y), (bb.Max.X, bb.Min.Y),
                           (bb.Max.X, bb.Max.Y), (bb.Min.X, bb.Max.Y)):
                ts.append((x - p0.X) * ux + (y - p0.Y) * uy)
            rec["bbox_width_in"] = round((max(ts) - min(ts)) * IN, 3)
            rec["bbox_height_in"] = round((bb.Max.Z - bb.Min.Z) * IN, 3)
            rec["host_wall"] = (host.Id.IntegerValue if hasattr(host.Id, "IntegerValue")
                                else host.Id.Value)
        except Exception:
            rec["bbox_width_in"] = None

        found = {}
        for (nm, bip) in TYPE_PARAMS:
            v = pnum(e, bip)          # instance first
            if v is None and sym is not None:
                v = pnum(sym, bip)    # then type
            if v is not None:
                found[nm] = v
        for nm in ("Rough Width", "Rough Height", "Width", "Height"):
            v = by_name(e, nm)
            if v is None and sym is not None:
                v = by_name(sym, nm)
            if v is not None:
                found[nm] = v
        rec["params_in"] = found
        rec["instance_size_params"] = dump_params(e)
        rec["type_size_params"] = dump_params(sym)

        rw = (found.get("FAMILY_ROUGH_WIDTH") or found.get("Rough Width")
              or rec["type_size_params"].get("Rough Width")
              or rec["instance_size_params"].get("Rough Width"))
        if rw and rec.get("bbox_width_in"):
            rec["bbox_minus_rough_in"] = round(rec["bbox_width_in"] - rw, 3)
        rows.append(rec)

wins = [r for r in rows if r["category"] == "Window"]
doors = [r for r in rows if r["category"] == "Door"]


def coverage(lst, key):
    return len([r for r in lst if r["params_in"].get(key) is not None])


OUT = {
    "doc": doc.Title,
    "windows": len(wins),
    "doors": len(doors),
    "windows_with_FAMILY_ROUGH_WIDTH": coverage(wins, "FAMILY_ROUGH_WIDTH"),
    "windows_with_Rough_Width_by_name": coverage(wins, "Rough Width"),
    "doors_with_FAMILY_ROUGH_WIDTH": coverage(doors, "FAMILY_ROUGH_WIDTH"),
    "rows": rows,
}
