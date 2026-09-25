# origin_bridge_check_view_style2.py - run via the ORIGIN Bridge. READ-ONLY.
# Reports the ACTIVE view's real Revit DisplayStyle/ViewType/DetailLevel by NAME (resolved against
# the actual enum members, not raw ints), plus whether Reveal Hidden Elements / Temporary
# Hide-Isolate are active - rules out a view-state false alarm before assuming a code bug.
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


def resolve(enum_type, value):
    try:
        target = int(value)
    except Exception:
        return "int() failed on {}".format(value)
    for name in dir(enum_type):
        if name.startswith("_"):
            continue
        try:
            member = getattr(enum_type, name)
            if int(member) == target:
                return name
        except Exception:
            continue
    return "NO MATCH for {}".format(target)


v = doc.ActiveView
out = {
    "doc_title": target_title,
    "view_name": v.Name,
    "view_type_resolved": resolve(ViewType, v.ViewType),
    "display_style_resolved": resolve(DisplayStyle, v.DisplayStyle),
    "detail_level_resolved": resolve(ViewDetailLevel, v.DetailLevel),
}
try:
    out["is_temporary_hide_isolate_active"] = v.IsTemporaryHideIsolateActive()
except Exception as ex:
    out["is_temporary_hide_isolate_active_ERR"] = str(ex)
try:
    out["are_graphics_overrides_allowed"] = v.AreGraphicsOverridesAllowed()
except Exception:
    pass

OUT = out
