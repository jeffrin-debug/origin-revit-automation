# origin_bridge_check_graphics_style.py - run via the ORIGIN Bridge. READ-ONLY.
# ST-012-003's MATERIAL name was confirmed changed to "ORIGIN Drywall Base" via the API, but the
# user reports zero visible change. This checks the deeper layer: the actual FACE-level
# GraphicsStyleId baked into the solid geometry (which drives subcategory / edge line color in
# Realistic-with-Edges display), the material's real Color property, and whether it has a Revit
# Appearance Asset at all (Realistic display style renders from the Appearance Asset, NOT the
# flat Shading Color, if one exists) - compares ST-012-003 directly against a real drywall board.
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


def inspect(mark):
    target = None
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
        try:
            mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = mk.AsString() if mk else None
        except Exception:
            m = None
        if m == mark:
            target = ds
            break
    if target is None:
        return {"mark": mark, "error": "not found"}

    info = {"mark": mark}
    try:
        mat_ids = target.GetMaterialIds(False)
        mat_info = []
        for mid in mat_ids:
            mat = doc.GetElement(mid)
            entry = {"name": mat.Name, "id": mid.Value if hasattr(mid, "Value") else mid.IntegerValue}
            try:
                c = mat.Color
                entry["shading_color_rgb"] = [c.Red, c.Green, c.Blue]
            except Exception as ex:
                entry["shading_color_ERR"] = str(ex)
            try:
                aid = mat.AppearanceAssetId
                entry["has_appearance_asset"] = aid is not None and aid != ElementId.InvalidElementId
            except Exception as ex:
                entry["appearance_asset_ERR"] = str(ex)
            mat_info.append(entry)
        info["materials"] = mat_info
    except Exception as ex:
        info["materials_ERR"] = str(ex)

    try:
        opt = Options()
        geo = target.get_Geometry(opt)
        face_styles = []
        for g in geo:
            if isinstance(g, Solid):
                for face in g.Faces:
                    try:
                        gsid = face.GraphicsStyleId
                        gs = doc.GetElement(gsid) if gsid and gsid != ElementId.InvalidElementId else None
                        cat_name = None
                        if gs is not None:
                            try:
                                cat_name = gs.GraphicsStyleCategory.Name
                            except Exception:
                                pass
                        face_styles.append({"graphics_style_id": gsid.Value if hasattr(gsid, "Value") else gsid.IntegerValue,
                                             "category_name": cat_name})
                    except Exception as ex:
                        face_styles.append({"ERR": str(ex)})
        # de-dupe identical entries for a compact report
        seen = []
        for fs in face_styles:
            if fs not in seen:
                seen.append(fs)
        info["distinct_face_graphics_styles"] = seen
    except Exception as ex:
        info["geometry_ERR"] = str(ex)

    return info


OUT = {
    "ST_012_003": inspect("ST-012-003"),
    "DP_012_001A_reference_drywall_board": inspect("DP-012-001A"),
}
