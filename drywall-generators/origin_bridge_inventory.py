# origin_bridge_inventory.py - run via the ORIGIN Bridge. READ-ONLY.
# Quick survey of a new/unfamiliar environment before running the full pipeline on it:
# counts of walls, ceilings (split soffit vs ordinary by the same name-substring test the
# real pipeline uses), columns, beams, rooms, plus a sample of each category's type names so
# any naming-convention mismatch (fire rating, soffit detection, band-wall type) can be spotted
# up front rather than discovered as a silent misclassification later.
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


_name_err = [None]


def type_name(e):
    try:
        t = doc.GetElement(e.GetTypeId())
        if t is None:
            _name_err[0] = _name_err[0] or "GetElement(TypeId) returned None"
            return None
        try:
            return t.Name
        except Exception as ex1:
            _name_err[0] = _name_err[0] or "plain .Name -> {}: {}".format(type(ex1).__name__, ex1)
        try:
            p = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM) or t.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            if p:
                return p.AsString()
        except Exception as ex2:
            _name_err[0] = (_name_err[0] or "") + " | param fallback -> {}: {}".format(type(ex2).__name__, ex2)
        return None
    except Exception as ex:
        _name_err[0] = _name_err[0] or "outer: {}: {}".format(type(ex).__name__, ex)
        return None


def family_name(e):
    try:
        t = doc.GetElement(e.GetTypeId())
        fam = t.Family if (t and hasattr(t, "Family")) else None
        return fam.Name if fam else None
    except Exception:
        return None


out = {"document": target_title}

walls = list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType())
out["walls"] = {"count": len(walls), "sample_type_names": sorted(set(type_name(w) for w in walls))[:20]}

ceilings = list(FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType())
soffit_like = []
ordinary = []
for c in ceilings:
    tn = (type_name(c) or "")
    fn = (family_name(c) or "")
    if "soffit" in tn.lower() or "soffit" in fn.lower():
        soffit_like.append((tn, fn))
    else:
        ordinary.append((tn, fn))
out["ceilings"] = {
    "count": len(ceilings),
    "classified_as_soffit_by_current_name_test": len(soffit_like),
    "classified_as_ordinary": len(ordinary),
    "sample_type_names": sorted(set(type_name(c) for c in ceilings))[:20],
}

cols = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Columns).WhereElementIsNotElementType())
scols = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType())
out["columns"] = {
    "OST_Columns": len(cols), "OST_StructuralColumns": len(scols),
    "sample_type_names": sorted(set(type_name(e) for e in (cols + scols)))[:20],
}

beams = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType())
out["beams"] = {"OST_StructuralFraming": len(beams), "sample_type_names": sorted(set(type_name(e) for e in beams))[:20]}

rooms = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType())
placed_rooms = [r for r in rooms if r.Area > 0.1]
out["rooms"] = {"total": len(rooms), "placed_and_enclosed": len(placed_rooms)}

# Fire-rated wall types: does any wall type's name match the pipeline's keyword list, or carry
# a real "Fire Rating" parameter?
KEYWORDS = ("fire", "rated", "type x", "type-x", "1 hr", "2 hr", "1-hr", "2-hr", "1hr", "2hr")
rated_by_name = set()
rated_by_param = set()
for w in walls:
    tn = (type_name(w) or "").lower()
    if any(k in tn for k in KEYWORDS):
        rated_by_name.add(type_name(w))
    try:
        wt = doc.GetElement(w.GetTypeId())
        p = wt.LookupParameter("Fire Rating") if wt else None
        if p:
            v = p.AsString() or ""
            if any(ch.isdigit() for ch in v):
                rated_by_param.add(type_name(w))
    except Exception:
        pass
out["fire_rating_signals"] = {
    "wall_types_matching_keyword_list": sorted(rated_by_name),
    "wall_types_with_fire_rating_param_set": sorted(rated_by_param),
}

out["_name_lookup_error_sample"] = _name_err[0]

OUT = out
