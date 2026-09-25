# origin_beam_assembly_v1.py
# ============================================================
# ORIGIN drywall assembly - BEAMS v1 (Dynamo Python node, PythonNet3/CPython3)
#
# The BEAMS plugin (split out of the combined beam+column node, user 2026-07-17): every
# structural-framing member gets a soffit-style box along its run - one board under the
# bottom (wrapping under the sides) plus a board on each side face; no top (the beam top
# meets the slab). Runs split into <=16 ft pieces (min 2 ft warned). Boards sit OUTSIDE the
# beam faces by DRYWALL_T_FT.
#
# Conventions: DirectShapes (Generic Models, visible in the ORIGIN Assembly view); host tag
# B### persisted to the Mark; boards DP-<host>-<seq>; comment "APP_ID | HOST=<eid> | ..." is
# the cleanup key; own manifest with warnings. Self-collecting - no node wiring needed.
# Also purges the legacy combined ORIGIN_BEAMCOL_V1 output (one-time migration).
#
# v1 limits: axis-aligned bbox wrap (angled beams get a loose box); no clipping against
# walls/ceilings at junctions.
# ============================================================

import clr
import json

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument

APP_ID = "ORIGIN_BEAM_V1"
LEGACY_APP_IDS = ["ORIGIN_BEAMCOL_V1"]

DELETE_PREVIOUS = True
# Beam boards previously got NO material at all (Revit's undifferentiated default appearance),
# unlike every other generated board in the pipeline. Uses the SAME material/subcategory name
# as the wall script's drywall boards, so Revit reuses the existing one instead of creating a
# duplicate - beam boards now match exactly (2026-07-21, alongside the same fix for columns).
COLOR_BOARDS = True
DRYWALL_STYLE_NAME = "ORIGIN Drywall Base"
DRYWALL_STYLE_RGB = (235, 228, 214)

IN_FT = 1.0 / 12.0
DRYWALL_T_FT = 0.5 * IN_FT
# 16 ft was far larger than a real gypsum sheet (stock is commonly 8 ft, up to 12 ft) - a run
# under 16 ft got ONE giant board per face instead of realistic stacked panels (same fix as the
# column plugin, 2026-07-22). 8 ft matches the wall script's own PANEL_LENGTH_FT convention, so
# any run longer than one standard sheet is guaranteed to split into >= 2 stacked panels.
MAX_BOARD_FT = 8.0
MIN_BOARD_FT = 2.0
MIN_ELEM_FT = 0.5
# Same fix as the column plugin (2026-07-22): the beam's own corner-wrap boards (the faces that
# extend DRYWALL_T_FT past the beam's own footprint so its OWN corners look continuous) have
# nowhere to go but into a neighboring wall's body when the beam sits flush against one. Subtract
# every nearby wall's bounding box from each board so it can never enter a wall.
CLIP_AGAINST_WALLS = True

MANIFEST_PATH = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\origin_beam_manifest.json"

result = {
    "app_id": APP_ID,
    "beams_processed": 0,
    "boards_created": 0,
    "deleted_previous": 0,
    "skipped": [],
    "manifest_path": "",
    "warnings": [],
}
warnings = result["warnings"]
board_records = []


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def el_bbox(e):
    try:
        bb = e.get_BoundingBox(None)
        if bb is None:
            return None
        return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
    except Exception:
        return None


def collect_other_pipeline_solids(warnings):
    """Real solid + bbox of every OTHER Origin-pipeline DirectShape in the model (wall drywall
    boards, studs/tracks, ceiling boards, etc. - anything NOT tagged with THIS script's own
    APP_ID). A wall's raw BOUNDING BOX is too crude to clip against - a beam's thin butt-face
    board can sit entirely inside a wall's bbox while never actually touching the wall's real
    (already-correct) drywall board there, and clipping against the bbox wrongly erases it. The
    wall's actual generated boards/studs are the real geometry that must never be penetrated."""
    solids = []
    try:
        for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
            try:
                p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                comment = (p.AsString() or "") if p else ""
            except Exception:
                comment = ""
            if not comment or comment.startswith(APP_ID + " |"):
                continue        # untagged, or one of THIS beam's own boards (self-overlap is by design)
            try:
                bb = ds.get_BoundingBox(None)
                if bb is None:
                    continue
                box = (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)
            except Exception:
                continue
            opt = Options()
            geo = ds.get_Geometry(opt)
            if geo is None:
                continue
            for g in geo:
                if isinstance(g, Solid) and g.Volume > 1e-9:
                    solids.append((box, g))
    except Exception as ex:
        warnings.append("Nearby-solid collection failed ({})".format(ex))
    return solids


def boxes_overlap(a, b):
    return not (a[3] <= b[0] or b[3] <= a[0] or a[4] <= b[1] or b[4] <= a[1] or a[5] <= b[2] or b[5] <= a[2])


def clip_against_others(solid, box, other_solids):
    """Subtract every nearby real solid from solid so it can never overlap already-placed
    drywall/framing. Unlike a bbox clip, an empty/near-zero result here is TRUSTED (it means
    this board is genuinely, fully covered by something already there) rather than reverted -
    the caller drops the board in that case."""
    if not other_solids:
        return solid
    for (obox, osolid) in other_solids:
        if not boxes_overlap(box, obox):
            continue
        try:
            clipped = BooleanOperationsUtils.ExecuteBooleanOperation(
                solid, osolid, BooleanOperationsType.Difference)
        except Exception:
            continue
        if clipped is not None:
            solid = clipped
        if solid is None or solid.Volume <= 1e-9:
            return solid
    return solid


def get_or_create_material(name, rgb):
    for m in FilteredElementCollector(doc).OfClass(Material):
        if m.Name == name:
            return m.Id
    mid = Material.Create(doc, name)
    try:
        m = doc.GetElement(mid)
        m.Color = Color(rgb[0], rgb[1], rgb[2])
        m.Transparency = 0
    except Exception:
        pass
    return mid


def get_or_create_subcategory(parent_cat, name, material_id, rgb):
    try:
        for sc in parent_cat.SubCategories:
            if sc.Name == name:
                return sc
    except Exception:
        pass
    sc = doc.Settings.Categories.NewSubcategory(parent_cat, name)
    try:
        sc.LineColor = Color(rgb[0], rgb[1], rgb[2])
    except Exception:
        pass
    try:
        if material_id and material_id != ElementId.InvalidElementId:
            sc.Material = doc.GetElement(material_id)
    except Exception:
        pass
    return sc


def setup_board_style(warnings):
    """Create/find the shared drywall-colored Generic Model subcategory + material (same name
    as the wall script uses) so beam boards match the rest of the model. Returns
    (material_id, graphics_style_id); (None, None) on any failure - boards stay uncolored."""
    if not COLOR_BOARDS:
        return None, None
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
        mat_id = get_or_create_material(DRYWALL_STYLE_NAME, DRYWALL_STYLE_RGB)
        sub = get_or_create_subcategory(gm, DRYWALL_STYLE_NAME, mat_id, DRYWALL_STYLE_RGB)
        try:
            doc.Regenerate()
        except Exception:
            pass
        gsid = None
        gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
        if gs:
            gsid = gs.Id
        return mat_id, gsid
    except Exception as ex:
        warnings.append("Board coloring setup failed: {}".format(ex))
        return None, None


def make_box(x0, y0, z0, x1, y1, z1, material_id=None, gstyle_id=None):
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4 or z1 - z0 < 1e-4:
        return None
    pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
    lines = []
    for i in range(4):
        lines.append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loop = CurveLoop.Create(lines)
    from System.Collections.Generic import List as NetList
    nl = NetList[CurveLoop]()
    nl.Add(loop)
    if material_id is not None and gstyle_id is not None:
        opts = SolidOptions(material_id, gstyle_id)
        return GeometryCreationUtilities.CreateExtrusionGeometry(nl, XYZ.BasisZ, z1 - z0, opts)
    return GeometryCreationUtilities.CreateExtrusionGeometry(nl, XYZ.BasisZ, z1 - z0)


def create_ds(solid, name, comment):
    try:
        ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
        ds.SetShape([solid])
        try:
            p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if p:
                p.Set(comment)
            m = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            if m:
                m.Set(name)
            ds.Name = name
        except Exception:
            pass
        return ds
    except Exception as ex:
        warnings.append("{}: DirectShape failed ({})".format(name, ex))
        return None


def split_len(lo, hi):
    total = hi - lo
    n = 1
    while total / n > MAX_BOARD_FT:
        n += 1
    step = total / n
    return [(lo + i * step, lo + (i + 1) * step) for i in range(n)]


def set_mark(e, tag):
    try:
        m = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if m and not m.IsReadOnly:
            m.Set(tag)
    except Exception:
        pass


def emit_board(host_tag, host_eid, seq, box, material_id=None, gstyle_id=None, other_solids=None):
    solid = make_box(*box, material_id=material_id, gstyle_id=gstyle_id)
    if solid is None:
        return 0
    solid = clip_against_others(solid, box, other_solids)
    if solid is None or solid.Volume <= 1e-9:
        warnings.append("{}-{:03d}: fully covered by existing drywall/framing - board omitted".format(host_tag, seq))
        return 0
    name = "DP-{}-{:03d}".format(host_tag, seq)
    comment = "{} | HOST={} | DRYWALL | BEAM | {}".format(APP_ID, host_eid, name)
    if create_ds(solid, name, comment) is None:
        return 0
    long_ft = max(box[3] - box[0], box[4] - box[1], box[5] - box[2])
    if long_ft > MAX_BOARD_FT + 1e-6:
        warnings.append("{}: board {:.1f} ft exceeds {} ft".format(name, long_ft, MAX_BOARD_FT))
    if long_ft < MIN_BOARD_FT - 1e-6:
        warnings.append("{}: board {:.1f} ft is under the {} ft min".format(name, long_ft, MIN_BOARD_FT))
    try:
        sbb = solid.GetBoundingBox()
        smn = sbb.Transform.OfPoint(sbb.Min)
        smx = sbb.Transform.OfPoint(sbb.Max)
        real_bbox = [round(smn.X, 3), round(smn.Y, 3), round(smn.Z, 3),
                     round(smx.X, 3), round(smx.Y, 3), round(smx.Z, 3)]
    except Exception:
        real_bbox = [round(v, 3) for v in box]
    board_records.append({
        "board_id": name, "host": host_tag, "host_eid": host_eid,
        "bbox_ft": real_bbox,
        "thickness_in": round(DRYWALL_T_FT * 12.0, 2),
    })
    return 1


def wrap_beam(e, host_tag, material_id=None, gstyle_id=None, other_solids=None):
    bb = el_bbox(e)
    if bb is None:
        result["skipped"].append("{}: no bbox".format(host_tag))
        return 0
    x0, y0, z0, x1, y1, z1 = bb
    if (z1 - z0) < 0.05:
        result["skipped"].append("{}: degenerate body".format(host_tag))
        return 0
    t = DRYWALL_T_FT
    along_x = (x1 - x0) >= (y1 - y0)
    if max(x1 - x0, y1 - y0) < MIN_ELEM_FT:
        result["skipped"].append("{}: too short".format(host_tag))
        return 0
    made = 0
    seq = 0
    host_eid = "B" + str(eid_value(e.Id))
    if along_x:
        for (a, b) in split_len(x0, x1):
            for box in [
                (a, y0 - t, z0 - t, b, y1 + t, z0),
                (a, y0 - t, z0, b, y0, z1),
                (a, y1, z0, b, y1 + t, z1),
            ]:
                seq += 1
                made += emit_board(host_tag, host_eid, seq, box, material_id, gstyle_id, other_solids)
    else:
        for (a, b) in split_len(y0, y1):
            for box in [
                (x0 - t, a, z0 - t, x1 + t, b, z0),
                (x0 - t, a, z0, x0, b, z1),
                (x1, a, z0, x1 + t, b, z1),
            ]:
                seq += 1
                made += emit_board(host_tag, host_eid, seq, box, material_id, gstyle_id, other_solids)
    return made


def delete_previous():
    n = 0
    tags = [APP_ID + " |"] + [t + " |" for t in LEGACY_APP_IDS]
    stale = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape):
        try:
            p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            s = (p.AsString() or "") if p else ""
            if any(s.startswith(t) for t in tags):
                stale.append(ds.Id)
        except Exception:
            continue
    for sid in stale:
        try:
            doc.Delete(sid)
            n += 1
        except Exception:
            pass
    return n


TransactionManager.Instance.EnsureInTransaction(doc)
try:
    if DELETE_PREVIOUS:
        result["deleted_previous"] = delete_previous()
    mat_id, gstyle_id = setup_board_style(warnings)
    other_solids = collect_other_pipeline_solids(warnings) if CLIP_AGAINST_WALLS else []
    beams = []
    try:
        beams = list(FilteredElementCollector(doc)
                     .OfCategory(BuiltInCategory.OST_StructuralFraming)
                     .WhereElementIsNotElementType())
    except Exception as ex:
        warnings.append("Beam collection failed ({})".format(ex))
    bi = 0
    for e in beams:
        bi += 1
        tag = "B{:03d}".format(bi)
        set_mark(e, tag)
        made = wrap_beam(e, tag, mat_id, gstyle_id, other_solids)
        if made:
            result["beams_processed"] += 1
            result["boards_created"] += made
except Exception as ex:
    warnings.append("FATAL: {}".format(ex))
finally:
    TransactionManager.Instance.TransactionTaskDone()

try:
    manifest = {
        "app_id": APP_ID,
        "nomenclature": {"beam": "B###", "board": "DP-<host>-<seq>"},
        "summary": {k: result[k] for k in ("beams_processed", "boards_created", "deleted_previous")},
        "boards": board_records,
        "skipped": result["skipped"],
        "warnings": warnings,
    }
    f = open(MANIFEST_PATH, "w")
    try:
        json.dump(manifest, f, indent=2)
    finally:
        f.close()
    result["manifest_path"] = MANIFEST_PATH
except Exception as ex:
    warnings.append("Manifest write failed: {}".format(ex))

OUT = result