# origin_bridge_identify_selection.py - run via the ORIGIN Bridge. READ-ONLY.
# The user selected something they believe is a wall with no drywall on it, but
# origin_bridge_describe_wall.py found no Wall instance and no tagged DirectShape for the
# current selection. This dumps the raw type/category of whatever is actually selected,
# including a check for RevitLinkInstance (a linked-model wall would resolve to the link
# instance in the host doc, not a real Wall element - which would explain why the generator,
# which only ever collects Wall from the active document, never saw it).
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

out = []
try:
    refs = uidoc.Selection.GetReferences()
except Exception:
    refs = None

ids = uidoc.Selection.GetElementIds()
for eid in ids:
    e = doc.GetElement(eid)
    entry = {"element_id": None, "type": None, "category": None, "is_link": False}
    try:
        entry["element_id"] = int(eid.Value)
    except Exception:
        try:
            entry["element_id"] = int(eid.IntegerValue)
        except Exception:
            entry["element_id"] = None
    if e is None:
        entry["type"] = "None (no element in host doc for this id)"
        out.append(entry)
        continue
    entry["type"] = type(e).__name__
    try:
        entry["category"] = e.Category.Name if e.Category else None
    except Exception:
        entry["category"] = None
    if isinstance(e, RevitLinkInstance):
        entry["is_link"] = True
        try:
            entry["link_doc_title"] = e.GetLinkDocument().Title if e.GetLinkDocument() else None
        except Exception:
            entry["link_doc_title"] = None
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        entry["mark"] = mk.AsString() if mk else None
    except Exception:
        entry["mark"] = None
    try:
        nm = e.Name
    except Exception:
        nm = None
    entry["name"] = nm
    out.append(entry)

link_refs = []
if refs:
    for r in refs:
        try:
            link_refs.append({
                "element_id": (int(r.ElementId.Value) if hasattr(r.ElementId, "Value") else int(r.ElementId.IntegerValue)),
                "linked_element_id": (str(r.LinkedElementId) if r.LinkedElementId else None),
                "uniqueId": r.UniqueId,
            })
        except Exception as ex:
            link_refs.append({"error": str(ex)})

OUT = {"elements": out, "references": link_refs}
