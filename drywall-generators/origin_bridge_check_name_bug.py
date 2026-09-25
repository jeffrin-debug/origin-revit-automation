# origin_bridge_check_name_bug.py - run via the ORIGIN Bridge. READ-ONLY.
# Confirms whether plain .Name access throws in THIS execution context (the bridge's exec()),
# for: a real Wall INSTANCE's own .Name (used by _is_soffit_band_wall), a WallType's .Name (used
# by wall_is_fire_rated's keyword path), and the Fire Rating PARAMETER path (which doesn't use
# .Name at all, so should be unaffected regardless).
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

out = {}
walls = list(FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType())
out["wall_count"] = len(walls)
if walls:
    w = walls[0]

    # 1) Wall INSTANCE's own .Name (what _is_soffit_band_wall actually checks)
    try:
        out["wall_instance_dot_name"] = w.Name
        out["wall_instance_dot_name_error"] = None
    except Exception as ex:
        out["wall_instance_dot_name"] = None
        out["wall_instance_dot_name_error"] = "{}: {}".format(type(ex).__name__, ex)

    # 2) WallType's .Name (what wall_is_fire_rated actually checks, via wt.Name.lower())
    try:
        wt = w.WallType
        out["walltype_dot_name"] = wt.Name
        out["walltype_dot_name_error"] = None
    except Exception as ex:
        out["walltype_dot_name"] = None
        out["walltype_dot_name_error"] = "{}: {}".format(type(ex).__name__, ex)

    # 3) Fire Rating PARAMETER path (no .Name involved at all)
    try:
        wt2 = w.WallType
        p = wt2.get_Parameter(BuiltInParameter.FIRE_RATING)
        out["fire_rating_param_found"] = p is not None
        if p:
            out["fire_rating_param_storage_type"] = str(p.StorageType)
            out["fire_rating_param_as_string"] = p.AsString()
    except Exception as ex:
        out["fire_rating_param_error"] = "{}: {}".format(type(ex).__name__, ex)

    # 4) doc.GetElement(w.GetTypeId()).Name - the exact pattern the inventory script's plain
    #    type_name() used, which threw "property cannot be read" for wall types earlier.
    try:
        t = doc.GetElement(w.GetTypeId())
        out["gettypeid_then_dot_name"] = t.Name
        out["gettypeid_then_dot_name_error"] = None
    except Exception as ex:
        out["gettypeid_then_dot_name"] = None
        out["gettypeid_then_dot_name_error"] = "{}: {}".format(type(ex).__name__, ex)

OUT = out
