# origin_bridge_check_browser_org.py - run via the ORIGIN Bridge. READ-ONLY.
# The "ORIGIN Assembly" 3D view exists (confirmed) but the user can't find it in the Project
# Browser. Checks the active Browser Organization scheme for 3D views (a custom grouping rule
# could put it somewhere other than the default "3D Views" node), plus the view's own relevant
# parameters (discipline, view template assignment) that a grouping rule might key off.
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

view = None
for v in FilteredElementCollector(doc).OfClass(View):
    try:
        if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
            view = v
            break
    except Exception:
        pass

out["view_found"] = view is not None
if view is not None:
    try:
        out["view_template_id"] = int(view.ViewTemplateId.Value) if hasattr(view.ViewTemplateId, "Value") else int(view.ViewTemplateId.IntegerValue)
    except Exception:
        out["view_template_id"] = None
    try:
        p = view.get_Parameter(BuiltInParameter.VIEW_DISCIPLINE)
        out["discipline"] = p.AsValueString() if p else None
    except Exception:
        out["discipline"] = None
    try:
        out["is_3d_locked"] = view.IsLocked if hasattr(view, "IsLocked") else None
    except Exception:
        pass
    try:
        out["can_be_printed"] = view.CanBePrinted
    except Exception:
        pass
    # Browser organization folder path for this specific view, if computable via BrowserOrganization
    try:
        bo = BrowserOrganization.GetCurrentBrowserOrganizationFor3DViews(doc)
        out["browser_org_name"] = bo.Name if bo else None
        out["browser_org_is_default"] = None
        try:
            folders = bo.GetFolderItems(view.Id)
            out["folder_path"] = [f.Name for f in folders] if folders else []
        except Exception as ex:
            out["folder_path_error"] = str(ex)
    except Exception as ex:
        out["browser_org_error"] = str(ex)

# Also list ALL BrowserOrganization elements in the doc (some templates define multiple schemes)
schemes = []
try:
    for bo in FilteredElementCollector(doc).OfClass(BrowserOrganization):
        try:
            schemes.append({
                "name": bo.Name,
                "is_views": bo.IsValidObject,
            })
        except Exception:
            pass
except Exception as ex:
    out["schemes_error"] = str(ex)
out["schemes"] = schemes

OUT = out
