# origin_bridge_dump_view_params.py - run via the ORIGIN Bridge. READ-ONLY.
# The active Browser Organization scheme is "all" and "ORIGIN Assembly" already resolves to the
# standard "3D Views" folder path under it - so Discipline grouping doesn't explain why the user
# couldn't find it in THIS session. Dumps every parameter on the view (name/value) looking for a
# "hidden in browser" style flag or anything else unusual, plus basic view-visibility state.
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

view = None
for v in FilteredElementCollector(doc).OfClass(View):
    try:
        if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
            view = v
            break
    except Exception:
        pass

out = {"view_found": view is not None}
if view is not None:
    params = []
    for p in view.Parameters:
        try:
            name = p.Definition.Name
        except Exception:
            name = "?"
        try:
            if p.StorageType == StorageType.String:
                val = p.AsString()
            elif p.StorageType == StorageType.Integer:
                val = p.AsInteger()
            elif p.StorageType == StorageType.Double:
                val = p.AsDouble()
            elif p.StorageType == StorageType.ElementId:
                eid = p.AsElementId()
                val = (int(eid.Value) if hasattr(eid, "Value") else int(eid.IntegerValue)) if eid else None
            else:
                val = str(p.AsValueString())
        except Exception as ex:
            val = "err:{}".format(ex)
        if name and ("brows" in name.lower() or "hidden" in name.lower() or "visib" in name.lower()):
            params.append({"name": name, "value": val})
    out["browser_hidden_visib_params"] = params

    try:
        out["is_valid_object"] = view.IsValidObject
    except Exception:
        pass
    try:
        out["view_activated"] = uidoc.ActiveView.Id == view.Id
    except Exception:
        pass
    try:
        out["can_be_activated"] = True
        uidoc.ActiveView  # just confirm no throw
    except Exception as ex:
        out["active_view_error"] = str(ex)
    try:
        out["window_count"] = len(list(uidoc.Application.Application.Documents))
    except Exception:
        pass
    # Is it a dependent view / assigned to a viewport already?
    try:
        out["is_dependent"] = view.GetPrimaryViewId().IntegerValue != -1 if hasattr(view, "GetPrimaryViewId") else None
    except Exception:
        out["is_dependent"] = None

# Also confirm how many Revit documents are open right now, and each one's title
try:
    docs = []
    for d in app.Documents:
        try:
            docs.append({"title": d.Title, "is_target": d.Title == target_title})
        except Exception:
            pass
    out["open_documents"] = docs
except Exception as ex:
    out["open_documents_error"] = str(ex)

OUT = out
