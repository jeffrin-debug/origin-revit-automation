# origin_bridge_check_active_browser_org.py - run via the ORIGIN Bridge. READ-ONLY.
# Finds the ACTIVE Browser Organization scheme for Views (not just the list of schemes that
# exist), and computes the exact folder path "ORIGIN Assembly" would sit under in the Project
# Browser tree today, so we can tell the user precisely where to look.
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

# Try every plausible static accessor name across Revit API versions.
candidates = [
    "GetCurrentBrowserOrganizationForViews",
    "GetCurrentBrowserOrganizationFor3DViews",
    "GetCurrentBrowserOrganizationForSheets",
]
found_method = None
for name in candidates:
    if hasattr(BrowserOrganization, name):
        found_method = name
out["available_static_methods"] = [n for n in candidates if hasattr(BrowserOrganization, n)]

active = None
if hasattr(BrowserOrganization, "GetCurrentBrowserOrganizationForViews"):
    try:
        active = BrowserOrganization.GetCurrentBrowserOrganizationForViews(doc)
    except Exception as ex:
        out["active_lookup_error"] = str(ex)

if active is not None:
    out["active_scheme_name"] = active.Name
    view = None
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.Name == "ORIGIN Assembly" and not v.IsTemplate:
                view = v
                break
        except Exception:
            pass
    if view is not None:
        try:
            folders = list(active.GetFolderItems(view.Id))
            out["folder_path_for_ORIGIN_Assembly"] = [f.Name for f in folders]
        except Exception as ex:
            out["folder_path_error"] = str(ex)
else:
    out["active_scheme_name"] = None

OUT = out
