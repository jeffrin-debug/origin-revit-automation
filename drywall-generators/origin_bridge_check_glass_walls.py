# origin_bridge_check_glass_walls.py - run via the ORIGIN Bridge. READ-ONLY.
# The user flagged generated drywall on host walls "016"/"017" as wrong - those walls are
# actually glass (e.g. storefront/curtain glazing), not real gypsum walls. Finds the real Wall
# elements behind those host tags and dumps everything that might reliably distinguish "glass"
# from a normal wall: wall type name/family, CurtainGrid presence, and each material layer's
# actual Material (checking for glass/transparent material class or name).
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

TARGET_HOSTS = ["016", "017"]


def host_of(comments):
    if not comments:
        return None
    for tok in comments.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL="):
            return tok
    return None


host_eids = {}
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    for h in TARGET_HOSTS:
        if mark.startswith("DP-{}-".format(h)) or mark.startswith("ST-{}-".format(h)):
            try:
                cm = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                comments = cm.AsString() if cm else None
            except Exception:
                comments = None
            wtag = host_of(comments)
            if wtag and wtag.startswith("WALL=W"):
                try:
                    host_eids[h] = int(wtag.replace("WALL=W", ""))
                except Exception:
                    pass

out = []
for h, eid in host_eids.items():
    w = doc.GetElement(ElementId(eid))
    entry = {"tag": h, "eid": eid}
    if not isinstance(w, Wall):
        entry["error"] = "not a Wall: {}".format(type(w).__name__)
        out.append(entry)
        continue
    wt = doc.GetElement(w.GetTypeId())
    try:
        entry["type_name_param"] = wt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
    except Exception:
        entry["type_name_param"] = None
    try:
        entry["family_name"] = wt.FamilyName
    except Exception:
        entry["family_name"] = None
    try:
        entry["kind"] = str(wt.Kind)
    except Exception:
        entry["kind"] = None
    try:
        entry["is_curtain_wall"] = isinstance(w, Wall) and wt.Kind == WallKind.Curtain
    except Exception:
        entry["is_curtain_wall"] = None
    try:
        cg = w.CurtainGrid
        entry["has_curtain_grid"] = cg is not None
    except Exception:
        entry["has_curtain_grid"] = None
    try:
        entry["function"] = str(wt.Function)
    except Exception:
        entry["function"] = None
    layers = []
    try:
        cs = wt.GetCompoundStructure()
        if cs is not None:
            for li in cs.GetLayers():
                mid = li.MaterialId
                mat = doc.GetElement(mid) if mid and mid != ElementId.InvalidElementId else None
                lname = None
                mclass = None
                transparency = None
                if mat is not None:
                    try:
                        lname = mat.Name
                    except Exception:
                        pass
                    try:
                        mclass = mat.MaterialClass
                    except Exception:
                        pass
                    try:
                        transparency = mat.Transparency
                    except Exception:
                        pass
                layers.append({
                    "function": str(li.Function), "width_in": round(li.Width * 12.0, 3),
                    "material_name": lname, "material_class": mclass, "transparency": transparency,
                })
    except Exception as ex:
        layers = [{"error": str(ex)}]
    entry["layers"] = layers
    out.append(entry)

OUT = {"host_eids": host_eids, "walls": out}
