# origin_bridge_check_export_view.py - run via the ORIGIN Bridge. READ-ONLY.
# The user can't find the "ORIGIN Assembly" view in this Revit 2027 environment. Checks whether
# it exists at all, whether it's a template, and dumps every view in the doc whose name contains
# "ORIGIN" or "Assembly" (case-insensitive) to catch a naming mismatch/duplicate.
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

out = {"doc_title": target_title, "revit_version": app.VersionNumber, "revit_build": app.VersionBuild}

exact = []
partial = []
all_views_sample = []
total_views = 0
for v in FilteredElementCollector(doc).OfClass(View):
    total_views += 1
    try:
        nm = v.Name
    except Exception:
        nm = None
    try:
        is_template = v.IsTemplate
    except Exception:
        is_template = None
    entry = {
        "name": nm, "is_template": is_template, "view_type": str(v.ViewType),
        "id": int(v.Id.Value) if hasattr(v.Id, "Value") else int(v.Id.IntegerValue),
    }
    if nm == "ORIGIN Assembly":
        exact.append(entry)
    elif nm and ("origin" in nm.lower() or "assembly" in nm.lower()):
        partial.append(entry)
    if len(all_views_sample) < 15:
        all_views_sample.append({"name": nm, "is_template": is_template, "view_type": str(v.ViewType)})

out["total_views"] = total_views
out["exact_match"] = exact
out["partial_matches"] = partial
out["sample_of_all_views"] = all_views_sample

OUT = out
