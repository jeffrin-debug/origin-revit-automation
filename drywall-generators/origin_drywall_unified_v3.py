# Origin Drywall Panel Generator v3 - Unified
# Dynamo Python Script node for Revit (target: Revit 2025/2026, CPython3 engine).
#
# WHAT THIS IS:
#   A single, self-contained merge of the two earlier lineages:
#     - Lineage A "DirectShape"      (origin_drywall_dynamo_v2_two_faces.py)
#     - Lineage B "Family instances" (ORG_Generate_Drywall_System_V1_2.py + the Word plan)
#   It creates horizontal staggered drywall panels on BOTH faces of selected straight walls
#   in one run, plus optional metal studs, seam strips, and lightweight screw markers.
#
# TWO OUTPUT MODES (set OUTPUT_MODE below):
#   "directshape" (default): builds raw DirectShape solids. No pre-made families needed.
#                            Runs anywhere. Tagged with ApplicationId = APP_ID.
#   "family":                places instances of ORG_MetalStud / ORG_GWB_Panel /
#                            ORG_GWB_ScrewMarker (wired to IN[1..3]). Gives schedulable
#                            parameters. Requires those families loaded. Tagged with the
#                            "Generated_By" instance parameter.
#
# CORRECTNESS FIXES OVER v1/v2 (this is the point of the merge):
#   1. TRUE WALL-FACE OFFSET. v1/v2 assumed the wall Location Line was the centerline and
#      placed panels at start +/- width/2. That is wrong whenever the Location Line is a
#      finish/core face. v3 reads BuiltInParameter.WALL_KEY_REF_PARAM and the compound
#      structure and places each face on its real surface.
#   2. SAFE TWO-SIDED CLEANUP. Both faces regenerate in ONE transaction, so "delete previous
#      then rebuild" can no longer wipe the opposite side (the old family script deleted all
#      Generated_By objects regardless of side).
#   3. LEVEL-Z GUARD (family mode). Level-based family placement can snap instances to the
#      level elevation and ignore the intended Z. v3 detects and corrects that.
#   4. DIAGNOSTICS. Skipped walls and failed geometry are reported in OUT["warnings"] instead
#      of being silently swallowed.
#   5. SCREW SPACING unified to 9 in. OC vertical + 1 in. top/bottom offset (the plan spec).
#
# STILL APPROXIMATE (documented, unchanged from v1/v2):
#   - Straight vertical walls only. Curved/slanted walls are skipped.
#   - Openings are approximated from hosted-insert bounding boxes (may overcut near swings).
#   - This is visualization / layout geometry, not shop-drawing certification.
#
# FAMILY-MODE CONTRACT (family mode fails silently if these are wrong):
#   - Panel/stud/screw families must be modeled with origin at the geometric CENTER.
#   - Panel family geometry must be driven by Panel_Length / Panel_Height / Panel_Thickness.
#   - Stud family geometry must be driven by Stud_Height (and Stud_Width / Stud_Depth).
#   See README_v3.md for the full family parameter list.

import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

try:
    clr.AddReference('RevitNodes')
    import Revit
    clr.ImportExtensions(Revit.Elements)
except:
    pass

from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

# ============================================================
# USER SETTINGS
# ============================================================

APP_ID = "ORIGIN_DRYWALL_V3"

# "directshape" = self-contained solids (no families needed).
# "family"      = place ORG_ family instances from IN[1..3].
OUTPUT_MODE = "directshape"

# Both faces are generated in ONE run. Set "enabled": False to skip a face.
#   exterior = same direction as Wall.Orientation
#   interior = opposite direction of Wall.Orientation
# base_edge_shift_ft shifts the first board edge; odd_row_additional_shift_ft staggers odd rows.
# Face B is shifted one 16 in. stud bay so the two faces do not simply mirror each other.
FACE_LAYOUTS = [
    {
        "face_name": "FACE_A_INTERIOR",
        "side": "interior",
        "enabled": True,
        "base_edge_shift_ft": 0.0,
        "odd_row_additional_shift_ft": 4.0,
        "description": "Interior face. Standard horizontal 4x8 stagger from wall start."
    },
    {
        "face_name": "FACE_B_EXTERIOR",
        "side": "exterior",
        "enabled": True,
        "base_edge_shift_ft": 16.0 / 12.0,
        "odd_row_additional_shift_ft": 4.0,
        "description": "Exterior face. Shifted one stud bay to avoid mirroring Face A."
    }
]

# What to generate.
GENERATE_STUDS = True     # studs are placed ONCE per wall (shared by both faces)
GENERATE_SEAMS = True     # directshape mode only (no seam family in family mode yet)
GENERATE_SCREWS = True    # per-face, along stud lines

# DirectShape appearance. When True, panels/seams/screws/studs are placed on their own colored
# Generic Model subcategories, so they are distinguishable in shaded 3D and can be toggled
# independently in Visibility/Graphics (e.g. hide screws for speed). No effect in family mode
# (family colors come from the families themselves).
COLOR_BY_TYPE = True

# Board layout. Revit internal units are feet.
PANEL_LENGTH_FT = 8.0
PANEL_HEIGHT_FT = 4.0
PANEL_THICKNESS_FT = 0.5 / 12.0          # 1/2 inch
PANEL_GAP_FROM_WALL_FACE_FT = 0.01       # small visual offset off the true wall face
MIN_PIECE_WIDTH_FT = 0.25                # skip slivers narrower than 3 inches
MIN_PIECE_HEIGHT_FT = 0.25

# Opening cutout settings.
CUT_OPENINGS = True
OPENING_CLEARANCE_FT = 0.05              # tolerance added around doors/windows

# Seam visualization (directshape mode).
SEAM_WIDTH_FT = 0.02                     # ~1/4 inch strip
SEAM_THICKNESS_FT = 0.01                 # raised line depth

# Studs.
STUD_SPACING_FT = 16.0 / 12.0            # 16 in. OC
STUD_WIDTH_FT = 1.25 / 12.0              # flange width along the wall
STUD_DEPTH_FT = 3.625 / 12.0            # depth through the wall cavity

# Screws (unified to the plan spec: 9 in. vertical OC, 1 in. from panel top/bottom).
SCREW_SPACING_VERTICAL_FT = 9.0 / 12.0
SCREW_TOP_BOTTOM_OFFSET_FT = 1.0 / 12.0
SCREW_MARKER_SIZE_FT = 0.04              # visual square marker (directshape)
SCREW_MARKER_THICKNESS_FT = 0.006
MAX_SCREWS_PER_RUN = 7000                # safety guard across both faces

# Safety behavior.
DELETE_PREVIOUS_ORIGIN_DRYWALL = True
PROCESS_ALL_WALLS_IF_NONE_SELECTED = False

# Dynamo inputs:
#   IN[0] = selected wall(s) (or use current Revit selection if empty)
#   IN[1] = ORG_MetalStud family type        (family mode only)
#   IN[2] = ORG_GWB_Panel family type         (family mode only)
#   IN[3] = ORG_GWB_ScrewMarker family type   (family mode only)
#   IN[4] = optional normal flip: 1 (default) or -1, if Orientation is unexpectedly reversed
#   IN[5] = optional delete previous: True/False (overrides DELETE_PREVIOUS_ORIGIN_DRYWALL)
#   IN[6] = optional generate screws: True/False (overrides GENERATE_SCREWS)
# ============================================================


# ------------------------------------------------------------
# Small vector / input helpers
# ------------------------------------------------------------

def unwrap(item):
    try:
        return UnwrapElement(item)
    except:
        return item


def get_in(index, default=None):
    try:
        val = IN[index]
    except:
        return default
    return val if val is not None else default


def ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ["true", "yes", "1", "y"]
    return default


def eid_value(eid):
    """Numeric value of an ElementId, across Revit versions. Revit 2024+ uses the 64-bit
    .Value and removed the older .IntegerValue, so try Value first."""
    try:
        return eid.Value
    except:
        pass
    try:
        return eid.IntegerValue
    except:
        return -1


def xyz_sub(a, b):
    return XYZ(a.X - b.X, a.Y - b.Y, a.Z - b.Z)


def xyz_mul(v, s):
    return XYZ(v.X * s, v.Y * s, v.Z * s)


def dot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def safe_normalize(v):
    length = math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
    if length < 1e-9:
        return None
    return XYZ(v.X / length, v.Y / length, v.Z / length)


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def unique_sorted(values, tolerance=0.01):
    out = []
    for v in sorted(values):
        if not out or abs(out[-1] - v) > tolerance:
            out.append(v)
    return out


# ------------------------------------------------------------
# Wall reading
# ------------------------------------------------------------

def get_input_walls(warnings):
    walls = []

    input_data = get_in(0)
    if input_data:
        for item in ensure_list(input_data):
            e = unwrap(item)
            if isinstance(e, Wall):
                walls.append(e)
    if walls:
        return walls

    try:
        for eid in list(uidoc.Selection.GetElementIds()):
            e = doc.GetElement(eid)
            if isinstance(e, Wall):
                walls.append(e)
    except Exception as ex:
        warnings.append("Could not read Revit selection: {}".format(ex))
    if walls:
        return walls

    if PROCESS_ALL_WALLS_IF_NONE_SELECTED:
        for e in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            walls.append(e)

    return walls


def get_wall_curve_data(wall):
    loc = wall.Location
    if not loc or not hasattr(loc, "Curve"):
        return None

    curve = loc.Curve
    if curve.GetType().Name != "Line":       # v3 supports straight walls only
        return None

    start = curve.GetEndPoint(0)
    end = curve.GetEndPoint(1)
    length = curve.Length
    direction = safe_normalize(xyz_sub(end, start))
    if direction is None or length <= 0:
        return None

    return start, end, direction, length


def get_wall_height(wall):
    try:
        hp = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        if hp:
            h = hp.AsDouble()
            if h and h > 0.1:
                return h
    except:
        pass
    try:
        bb = wall.get_BoundingBox(None)
        if bb:
            h = bb.Max.Z - bb.Min.Z
            if h and h > 0.1:
                return h
    except:
        pass
    return 9.0


def get_wall_width(wall):
    try:
        wt = wall.WallType
        if wt and wt.Width and wt.Width > 0:
            return wt.Width
    except:
        pass
    try:
        if wall.Width and wall.Width > 0:
            return wall.Width
    except:
        pass
    return 0.5


def wall_ref_geometry(wall, width, warnings):
    """Compute the wall's reference geometry along the exterior normal.

    Returns (d_loc, core_center_from_ext):
      d_loc               = distance from the EXTERIOR face to the Location Line, toward the
                            interior (0 => on exterior face, width => on interior face).
      core_center_from_ext= distance from the EXTERIOR face to the CORE mid-plane. Studs are
                            centered here (they occupy the structural core, not the total-wall
                            mid-plane), which matters for asymmetric compound walls.

    This is the fix for the old centerline assumption: it accounts for whichever reference the
    wall's Location Line uses and for the compound structure of the wall type.
    """
    ext_noncore = 0.0
    int_noncore = 0.0
    core_width = width

    try:
        cs = wall.WallType.GetCompoundStructure()
        if cs:
            layers = cs.GetLayers()
            first_core = cs.GetFirstCoreLayerIndex()
            last_core = cs.GetLastCoreLayerIndex()
            idx = 0
            for layer in layers:                 # ordered exterior -> interior
                w = layer.Width
                if idx < first_core:
                    ext_noncore += w
                elif idx > last_core:
                    int_noncore += w
                idx += 1
            core_width = width - ext_noncore - int_noncore
    except Exception as ex:
        warnings.append("Wall {}: compound structure unreadable, assuming single layer ({})".format(
            eid_value(wall.Id), ex))

    ref = 0
    try:
        p = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
        if p:
            ref = p.AsInteger()
    except:
        pass

    # WallLocationLine enum: 0 WallCenterline, 1 CoreCenterline, 2 FinishFaceExterior,
    #                        3 FinishFaceInterior, 4 CoreExterior, 5 CoreInterior
    if ref == 1:
        d_loc = ext_noncore + core_width / 2.0
    elif ref == 2:
        d_loc = 0.0
    elif ref == 3:
        d_loc = width
    elif ref == 4:
        d_loc = ext_noncore
    elif ref == 5:
        d_loc = width - int_noncore
    else:                                        # 0 (or unknown) => wall centerline
        d_loc = width / 2.0

    core_center_from_ext = ext_noncore + core_width / 2.0
    return d_loc, core_center_from_ext


def face_normal_and_offset(true_orientation, d_loc, width, side_name, global_flip):
    """Given the TRUE exterior normal (raw Wall.Orientation) and d_loc (distance from the
    exterior face to the Location Line), return (outward_normal, offset_along_normal) for the
    requested face. global_flip == -1 swaps which physical side is treated as exterior/interior
    (a safety valve for models whose Orientation is not what the user expects).

    Fext = start + true_orientation * d_loc         (exterior face)
    Fint = start - true_orientation * (width-d_loc)  (interior face)
    """
    is_exterior_cfg = str(side_name).lower().startswith("ext")
    # normal (global_flip==1) â†’ exterior cfg uses the true exterior face; flip swaps it.
    use_true_exterior = is_exterior_cfg if global_flip == 1 else (not is_exterior_cfg)

    if use_true_exterior:
        return true_orientation, d_loc
    # interior face: outward normal points opposite the true exterior
    return xyz_mul(true_orientation, -1.0), (width - d_loc)


# ------------------------------------------------------------
# Openings
# ------------------------------------------------------------

def get_bbox_corners(bb):
    return [
        XYZ(bb.Min.X, bb.Min.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Min.Y, bb.Max.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Min.Z),
        XYZ(bb.Min.X, bb.Max.Y, bb.Max.Z),
        XYZ(bb.Max.X, bb.Min.Y, bb.Min.Z),
        XYZ(bb.Max.X, bb.Min.Y, bb.Max.Z),
        XYZ(bb.Max.X, bb.Max.Y, bb.Min.Z),
        XYZ(bb.Max.X, bb.Max.Y, bb.Max.Z)
    ]


def get_opening_rects(wall, start, u, wall_length, wall_height, warnings):
    rects = []
    if not CUT_OPENINGS:
        return rects

    try:
        insert_ids = wall.FindInserts(True, True, True, True)
    except Exception as ex:
        warnings.append("Wall {}: FindInserts failed ({})".format(eid_value(wall.Id), ex))
        insert_ids = []

    for eid in insert_ids:
        e = doc.GetElement(eid)
        if not e:
            continue
        try:
            bb = e.get_BoundingBox(None)
        except:
            bb = None
        if not bb:
            continue

        xs = []
        ys = []
        for p in get_bbox_corners(bb):
            local = xyz_sub(p, start)
            xs.append(dot(local, u))
            ys.append(p.Z - start.Z)

        x0 = max(0.0, min(xs) - OPENING_CLEARANCE_FT)
        x1 = min(wall_length, max(xs) + OPENING_CLEARANCE_FT)
        y0 = max(0.0, min(ys) - OPENING_CLEARANCE_FT)
        y1 = min(wall_height, max(ys) + OPENING_CLEARANCE_FT)

        if (x1 - x0) > 0.1 and (y1 - y0) > 0.1:
            rects.append((x0, y0, x1, y1))

    return rects


def rect_intersection(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return None
    return (ix0, iy0, ix1, iy1)


def subtract_rect(rect, cut):
    inter = rect_intersection(rect, cut)
    if not inter:
        return [rect]

    x0, y0, x1, y1 = rect
    ix0, iy0, ix1, iy1 = inter

    pieces = []
    if iy0 > y0:                       # bottom strip
        pieces.append((x0, y0, x1, iy0))
    if iy1 < y1:                       # top strip
        pieces.append((x0, iy1, x1, y1))
    if ix0 > x0:                       # left strip across the middle band
        pieces.append((x0, iy0, ix0, iy1))
    if ix1 < x1:                       # right strip across the middle band
        pieces.append((ix1, iy0, x1, iy1))

    return [r for r in pieces
            if (r[2] - r[0]) >= MIN_PIECE_WIDTH_FT and (r[3] - r[1]) >= MIN_PIECE_HEIGHT_FT]


def subtract_openings_from_panel(panel_rect, opening_rects):
    pieces = [panel_rect]
    for opening in opening_rects:
        new_pieces = []
        for piece in pieces:
            new_pieces.extend(subtract_rect(piece, opening))
        pieces = new_pieces
        if not pieces:
            break
    return pieces


# ------------------------------------------------------------
# Panel grid + stud lines
# ------------------------------------------------------------

def normalize_shift(shift):
    try:
        s = float(shift)
    except:
        s = 0.0
    while s < 0.0:
        s += PANEL_LENGTH_FT
    while s >= PANEL_LENGTH_FT:
        s -= PANEL_LENGTH_FT
    return s


def generate_raw_panel_rects(wall_length, wall_height, base_edge_shift_ft, odd_row_additional_shift_ft):
    rects = []
    y = 0.0
    row = 0
    while y < wall_height - 0.001:
        row_y0 = y
        row_y1 = min(y + PANEL_HEIGHT_FT, wall_height)

        row_shift = base_edge_shift_ft
        if row % 2 == 1:
            row_shift += odd_row_additional_shift_ft
        row_shift = normalize_shift(row_shift)

        x = -row_shift
        col = 0
        while x < wall_length - 0.001:
            x0 = max(0.0, x)
            x1 = min(wall_length, x + PANEL_LENGTH_FT)
            if (x1 - x0) >= MIN_PIECE_WIDTH_FT and (row_y1 - row_y0) >= MIN_PIECE_HEIGHT_FT:
                rects.append((x0, row_y0, x1, row_y1, row, row_shift, col))
            x += PANEL_LENGTH_FT
            col += 1

        y += PANEL_HEIGHT_FT
        row += 1

    return rects


def stud_positions_for_wall(wall_length, opening_rects):
    xs = []
    x = 0.0
    while x <= wall_length + 0.001:
        xs.append(x)
        x += STUD_SPACING_FT
    if not xs:
        xs.append(0.0)
    if abs(xs[-1] - wall_length) > 0.1:
        xs.append(wall_length)

    # add opening jamb lines
    for (ox0, oy0, ox1, oy1) in opening_rects:
        xs.append(clamp(ox0, 0.0, wall_length))
        xs.append(clamp(ox1, 0.0, wall_length))

    return unique_sorted([clamp(v, 0.0, wall_length) for v in xs])


def screw_points_for_piece(piece_rect, stud_xs):
    x0, y0, x1, y1 = piece_rect
    pts = []
    for sx in stud_xs:
        if sx < x0 - 0.01 or sx > x1 + 0.01:
            continue
        top = y1 - SCREW_TOP_BOTTOM_OFFSET_FT
        yy = y0 + SCREW_TOP_BOTTOM_OFFSET_FT
        if top < yy:
            pts.append((sx, (y0 + y1) / 2.0))     # piece too short: one screw at center
            continue
        while yy <= top + 0.001:
            pts.append((sx, yy))
            yy += SCREW_SPACING_VERTICAL_FT
    return pts


# ------------------------------------------------------------
# DirectShape emit
# ------------------------------------------------------------

def make_point(origin, u, z, x, y):
    return origin.Add(u.Multiply(x)).Add(z.Multiply(y))


def make_rect_solid(origin, u, z, normal, rect, depth, material_id=None, gstyle_id=None):
    x0, y0, x1, y1 = rect
    if (x1 - x0) < 0.001 or (y1 - y0) < 0.001 or depth <= 0:
        return None

    p0 = make_point(origin, u, z, x0, y0)
    p1 = make_point(origin, u, z, x1, y0)
    p2 = make_point(origin, u, z, x1, y1)
    p3 = make_point(origin, u, z, x0, y1)

    use_options = material_id is not None
    for order in ((p0, p1, p2, p3), (p0, p3, p2, p1)):
        try:
            loop = CurveLoop()
            loop.Append(Line.CreateBound(order[0], order[1]))
            loop.Append(Line.CreateBound(order[1], order[2]))
            loop.Append(Line.CreateBound(order[2], order[3]))
            loop.Append(Line.CreateBound(order[3], order[0]))
            loops = List[CurveLoop]()
            loops.Add(loop)
            if use_options:
                gs = gstyle_id if gstyle_id is not None else ElementId.InvalidElementId
                opts = SolidOptions(material_id, gs)
                return GeometryCreationUtilities.CreateExtrusionGeometry(loops, normal, depth, opts)
            return GeometryCreationUtilities.CreateExtrusionGeometry(loops, normal, depth)
        except:
            continue
    return None


def set_comments(element, text):
    try:
        p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and (not p.IsReadOnly):
            p.Set(text)
    except:
        pass


def create_directshape(solid, data_id, name, comments, warnings):
    if solid is None:
        return None
    try:
        ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
        ds.ApplicationId = APP_ID
        ds.ApplicationDataId = data_id
        shape = List[GeometryObject]()
        shape.Add(solid)
        ds.SetShape(shape)
        try:
            ds.Name = name
        except:
            pass
        set_comments(ds, comments)
        return ds
    except Exception as ex:
        warnings.append("DirectShape create failed for {}: {}".format(data_id, ex))
        return None


# ------------------------------------------------------------
# DirectShape appearance: colored subcategories + materials
# ------------------------------------------------------------

# kind -> (subcategory name, RGB). Reused/looked up by name, so reruns don't duplicate.
STYLE_SPECS = [
    ("PANEL", "ORIGIN Drywall Panel", (235, 228, 214)),   # warm off-white
    ("SEAM",  "ORIGIN Drywall Seam",  (60, 120, 220)),    # blue
    ("SCREW", "ORIGIN Drywall Screw", (200, 60, 60)),     # red
    ("STUD",  "ORIGIN Metal Stud",    (150, 155, 165)),   # steel gray
]


def get_or_create_material(name, rgb):
    for m in FilteredElementCollector(doc).OfClass(Material):
        if m.Name == name:
            return m.Id
    mid = Material.Create(doc, name)
    try:
        m = doc.GetElement(mid)
        m.Color = Color(rgb[0], rgb[1], rgb[2])
        m.Transparency = 0
    except:
        pass
    return mid


def get_or_create_subcategory(parent_cat, name, material_id, rgb):
    try:
        for sc in parent_cat.SubCategories:
            if sc.Name == name:
                return sc
    except:
        pass
    sc = doc.Settings.Categories.NewSubcategory(parent_cat, name)
    try:
        sc.LineColor = Color(rgb[0], rgb[1], rgb[2])
    except:
        pass
    try:
        if material_id and material_id != ElementId.InvalidElementId:
            sc.Material = doc.GetElement(material_id)
    except:
        pass
    return sc


def setup_styles(warnings):
    """Create (or find) a colored Generic Model subcategory + material per element type. Returns
    {kind: (material_id, graphics_style_id)} for make_rect_solid. Best-effort: on any failure the
    element is still created, just uncolored."""
    styles = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
    except Exception as ex:
        warnings.append("Could not access Generic Model category for coloring: {}".format(ex))
        return styles

    # Phase 1: create/find materials and subcategories.
    created = []
    for kind, name, rgb in STYLE_SPECS:
        try:
            mat_id = get_or_create_material(name, rgb)
            get_or_create_subcategory(gm, name, mat_id, rgb)
            created.append((kind, name, mat_id))
        except Exception as ex:
            warnings.append("Coloring for {} failed: {}".format(kind, ex))

    # Regenerate so brand-new subcategories expose their graphics styles on this first run,
    # not only on a later run.
    try:
        doc.Regenerate()
    except:
        pass

    # Phase 2: resolve each subcategory's projection graphics-style id (re-fetch the category).
    subs_by_name = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
        for sc in gm.SubCategories:
            subs_by_name[sc.Name] = sc
    except:
        pass

    for kind, name, mat_id in created:
        gsid = ElementId.InvalidElementId
        sub = subs_by_name.get(name)
        if sub is not None:
            try:
                gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
                if gs:
                    gsid = gs.Id
            except:
                pass
        styles[kind] = (mat_id, gsid)     # material color always applies; gsid enables the toggle
    return styles


# ------------------------------------------------------------
# Family emit
# ------------------------------------------------------------

def set_param(elem, name, value):
    p = elem.LookupParameter(name)
    if not p or p.IsReadOnly:
        return
    try:
        if isinstance(value, bool):
            p.Set(1 if value else 0)
        elif isinstance(value, (int, float)):
            p.Set(value)
        else:
            p.Set(str(value))
    except:
        pass


def activate_symbol(symbol):
    if symbol and not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def local_center_to_world(origin_face, u, z, normal, rect, depth):
    cx = (rect[0] + rect[2]) / 2.0
    cy = (rect[1] + rect[3]) / 2.0
    # family origin sits at the piece center, pushed out half its own depth off the face
    return origin_face.Add(normal.Multiply(depth / 2.0)).Add(u.Multiply(cx)).Add(z.Multiply(cy))


def place_family(symbol, point, wall_dir, level, warnings):
    if symbol is None:
        return None
    inst = None
    try:
        if level:
            inst = doc.Create.NewFamilyInstance(point, symbol, level, StructuralType.NonStructural)
        else:
            inst = doc.Create.NewFamilyInstance(point, symbol, StructuralType.NonStructural)
    except Exception:
        try:
            inst = doc.Create.NewFamilyInstance(point, symbol, StructuralType.NonStructural)
        except Exception as ex:
            warnings.append("Family placement failed at {},{},{}: {}".format(
                round(point.X, 2), round(point.Y, 2), round(point.Z, 2), ex))
            return None

    # align local X to the wall direction (rotate about a vertical axis; Z-invariant)
    try:
        angle = math.atan2(wall_dir.Y, wall_dir.X)
        axis = Line.CreateBound(point, XYZ(point.X, point.Y, point.Z + 10.0))
        ElementTransformUtils.RotateElement(doc, inst.Id, axis, angle)
    except Exception as ex:
        warnings.append("Family rotate failed for {}: {}".format(eid_value(inst.Id), ex))

    # LEVEL-Z GUARD: level-based placement can ignore point.Z and snap to the level plane.
    try:
        loc = inst.Location
        if isinstance(loc, LocationPoint):
            dz = point.Z - loc.Point.Z
            if abs(dz) > 1e-4:
                ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(0.0, 0.0, dz))
    except Exception as ex:
        warnings.append("Family Z-correction failed for {}: {}".format(eid_value(inst.Id), ex))

    return inst


# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

def delete_previous(processed_ids, warnings):
    """Delete prior v3-generated elements, SCOPED to the walls now being processed. Scoping is
    the fix for the old document-wide delete, which could wipe drywall on other walls (and on
    faces disabled for this run). Deletes all v3 output on the processed walls (studs + both
    faces); the enabled faces are then rebuilt in the same run."""
    ids = List[ElementId]()
    wall_tokens = ["WALL=" + w + " " for w in processed_ids]   # delimited, avoids W1 vs W12

    # DirectShapes: ours if ApplicationId or Comments carry APP_ID; in scope if the Comments
    # carry a WALL token for a processed wall.
    try:
        for e in FilteredElementCollector(doc).OfClass(DirectShape):
            comment = None
            try:
                p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                comment = p.AsString() if p else None
            except:
                comment = None

            is_ours = False
            try:
                if e.ApplicationId == APP_ID:
                    is_ours = True
            except:
                pass
            if not is_ours and comment and APP_ID in comment:
                is_ours = True
            if not is_ours:
                continue

            if comment and any(tok in comment for tok in wall_tokens):
                ids.Add(e.Id)
            # if ours but no readable WALL token, leave it (can't confirm scope safely)
    except Exception as ex:
        warnings.append("Cleanup (DirectShape) failed: {}".format(ex))

    # Family instances: ours via Generated_By; in scope via the Wall_ID parameter.
    try:
        col = FilteredElementCollector(doc).OfCategory(
            BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
        for e in col:
            try:
                pg = e.LookupParameter("Generated_By")
                if not (pg and pg.AsString() == APP_ID):
                    continue
                pw = e.LookupParameter("Wall_ID")
                wid = pw.AsString() if pw else None
                if wid and wid in processed_ids:
                    ids.Add(e.Id)
            except:
                pass
    except Exception as ex:
        warnings.append("Cleanup (family) failed: {}".format(ex))

    count = ids.Count
    if count > 0:
        doc.Delete(ids)
    return count


# ============================================================
# MAIN
# ============================================================

result = {
    "app_id": APP_ID,
    "output_mode": OUTPUT_MODE,
    "mode": "two_faces_unified",
    "deleted_previous": 0,
    "walls_requested": 0,
    "walls_processed": 0,
    "walls_skipped": [],
    "faces_processed": 0,
    "studs_created": 0,
    "panels_created": 0,
    "seams_created": 0,
    "screws_created": 0,
    "notes": [],
    "warnings": []
}
warnings = result["warnings"]

# Resolve inputs / overrides.
mode = str(OUTPUT_MODE).strip().lower()
if mode not in ("directshape", "family"):
    warnings.append("Unknown OUTPUT_MODE '{}', defaulting to directshape.".format(OUTPUT_MODE))
    mode = "directshape"
    result["output_mode"] = "directshape"

stud_symbol = unwrap(get_in(1))
panel_symbol = unwrap(get_in(2))
screw_symbol = unwrap(get_in(3))

try:
    global_flip = int(get_in(4, 1))
except:
    global_flip = 1
if global_flip not in (1, -1):
    global_flip = 1

do_delete = as_bool(get_in(5), DELETE_PREVIOUS_ORIGIN_DRYWALL)
do_screws = as_bool(get_in(6), GENERATE_SCREWS)

# {kind: (material_id, graphics_style_id)} for DirectShape coloring; populated in the transaction.
styles = {}

walls = get_input_walls(warnings)
result["walls_requested"] = len(walls)

if mode == "family":
    missing = [n for n, s in [("stud", stud_symbol), ("panel", panel_symbol), ("screw", screw_symbol)]
               if s is None]
    if panel_symbol is None:
        warnings.append("Family mode: no panel family on IN[2]. No panels will be created.")
    if missing:
        result["notes"].append("Family mode missing symbols for: " + ", ".join(missing))
    if GENERATE_SEAMS:
        result["notes"].append("Seams are skipped in family mode (no seam family). "
                               "Use directshape mode for seam strips.")


def ds_comment(wall_id, face_name, kind, eid):
    """DirectShape Comments tag. Includes a delimited WALL=<id> token so cleanup can be scoped
    to specific walls (the trailing ' |' delimiter prevents W1 matching W12)."""
    return "{} | WALL={} | {} | {} | {}".format(APP_ID, wall_id, face_name, kind, eid)


def emit_panel(origin_face, u, z, normal, rect, level, ids, face_name):
    """Create one panel piece in the active mode. Returns 1 on success, 0 otherwise."""
    wall_id, side, row, col, is_cut, is_opening_cut, panel_id = ids
    if mode == "directshape":
        mat_id, gs_id = styles.get("PANEL", (None, None))
        solid = make_rect_solid(origin_face, u, z, normal, rect, PANEL_THICKNESS_FT, mat_id, gs_id)
        ds = create_directshape(
            solid, panel_id, "Drywall Panel " + panel_id,
            ds_comment(wall_id, face_name, "PANEL", panel_id), warnings)
        return 1 if ds else 0
    else:
        if panel_symbol is None:
            return 0
        pt = local_center_to_world(origin_face, u, z, normal, rect, PANEL_THICKNESS_FT)
        inst = place_family(panel_symbol, pt, u, level, warnings)
        if not inst:
            return 0
        set_param(inst, "Generated_By", APP_ID)
        set_param(inst, "Panel_Length", rect[2] - rect[0])
        set_param(inst, "Panel_Height", rect[3] - rect[1])
        set_param(inst, "Panel_Thickness", PANEL_THICKNESS_FT)
        set_param(inst, "Wall_ID", wall_id)
        set_param(inst, "Side", side)
        set_param(inst, "Panel_Row", row)
        set_param(inst, "Panel_Column", col)
        set_param(inst, "Panel_ID", panel_id)
        set_param(inst, "Is_Cut_Panel", is_cut)
        set_param(inst, "Is_Opening_Cut", is_opening_cut)
        return 1


def emit_seams(origin_face, u, z, normal, rect, panel_id, face_name, wall_id):
    """Directshape-only seam strips around a panel piece. Returns count created."""
    if not GENERATE_SEAMS or mode != "directshape":
        return 0
    x0, y0, x1, y1 = rect
    seam_origin = origin_face.Add(normal.Multiply(PANEL_THICKNESS_FT + 0.002))
    seam_rects = [
        (x0 - SEAM_WIDTH_FT / 2.0, y0, x0 + SEAM_WIDTH_FT / 2.0, y1),
        (x1 - SEAM_WIDTH_FT / 2.0, y0, x1 + SEAM_WIDTH_FT / 2.0, y1),
        (x0, y0 - SEAM_WIDTH_FT / 2.0, x1, y0 + SEAM_WIDTH_FT / 2.0),
        (x0, y1 - SEAM_WIDTH_FT / 2.0, x1, y1 + SEAM_WIDTH_FT / 2.0)
    ]
    mat_id, gs_id = styles.get("SEAM", (None, None))
    made = 0
    idx = 1
    for sr in seam_rects:
        solid = make_rect_solid(seam_origin, u, z, normal, sr, SEAM_THICKNESS_FT, mat_id, gs_id)
        data_id = panel_id + "-SEAM-" + str(idx)
        ds = create_directshape(
            solid, data_id, "Drywall Seam " + data_id,
            ds_comment(wall_id, face_name, "SEAM", panel_id), warnings)
        if ds:
            made += 1
        idx += 1
    return made


def emit_screws(origin_face, u, z, normal, piece_rect, stud_xs, panel_id, face_name, side,
                wall_id, level, screw_counter):
    """Per-face screw markers along stud lines within one panel piece."""
    if not do_screws:
        return 0, screw_counter
    made = 0
    half = SCREW_MARKER_SIZE_FT / 2.0
    screw_origin = origin_face.Add(normal.Multiply(PANEL_THICKNESS_FT + SEAM_THICKNESS_FT + 0.004))
    pts = screw_points_for_piece(piece_rect, stud_xs)

    for (sx, sy) in pts:
        if screw_counter >= MAX_SCREWS_PER_RUN:
            break
        if mode == "family" and screw_symbol is None:
            break
        # advance the counter per attempt so data_ids stay unique even if a create fails
        screw_counter += 1
        data_id = panel_id + "-SCR-" + str(screw_counter)
        if mode == "directshape":
            mat_id, gs_id = styles.get("SCREW", (None, None))
            sr = (sx - half, sy - half, sx + half, sy + half)
            solid = make_rect_solid(screw_origin, u, z, normal, sr, SCREW_MARKER_THICKNESS_FT, mat_id, gs_id)
            ds = create_directshape(
                solid, data_id, "Drywall Screw " + data_id,
                ds_comment(wall_id, face_name, "SCREW", panel_id), warnings)
            if ds:
                made += 1
        else:
            pt = origin_face.Add(normal.Multiply(PANEL_THICKNESS_FT)).Add(
                u.Multiply(sx)).Add(z.Multiply(sy))
            inst = place_family(screw_symbol, pt, u, level, warnings)
            if inst:
                set_param(inst, "Generated_By", APP_ID)
                set_param(inst, "Screw_ID", data_id)
                set_param(inst, "Panel_ID", panel_id)
                set_param(inst, "Wall_ID", wall_id)
                set_param(inst, "Side", side)
                made += 1
    return made, screw_counter


def stud_segments(sx, wall_height, opening_rects):
    """Vertical (y0, y1) segments for a stud at position sx, with any portion that falls inside
    an opening removed -- so studs no longer run through doors/windows. Cripple segments remain
    above the header and below the sill. A stud sitting on an opening's jamb edge stays full
    height (it's the king stud)."""
    blocks = []
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if ox0 + 0.01 < sx < ox1 - 0.01:          # strictly inside the opening width
            b0 = max(0.0, oy0)
            b1 = min(wall_height, oy1)
            if b1 > b0:
                blocks.append((b0, b1))
    if not blocks:
        return [(0.0, wall_height)]

    blocks.sort()
    segments = []
    cur = 0.0
    for (b0, b1) in blocks:
        if b0 > cur:
            segments.append((cur, b0))
        cur = max(cur, b1)
    if cur < wall_height:
        segments.append((cur, wall_height))
    return segments


def emit_studs(start, u, z, true_orientation, center_off, wall_height, stud_xs,
               opening_rects, level, wall_id):
    """Studs are placed ONCE per wall, centered on the structural CORE (shared by both faces).
    center_off is the signed distance from the Location Line to the core mid-plane along the
    TRUE orientation, so studs land correctly regardless of the global flip and of asymmetric
    non-core layers. Studs are interrupted at openings (cripples above header / below sill)."""
    if not GENERATE_STUDS:
        return 0
    orientation = true_orientation
    mat_id, gs_id = styles.get("STUD", (None, None))
    made = 0
    half_w = STUD_WIDTH_FT / 2.0
    back = start.Add(orientation.Multiply(center_off - STUD_DEPTH_FT / 2.0))
    for si, sx in enumerate(stud_xs):
        seg_i = 0
        for (sy0, sy1) in stud_segments(sx, wall_height, opening_rects):
            if (sy1 - sy0) < MIN_PIECE_HEIGHT_FT:
                continue
            seg_i += 1
            stud_id = "{}-ST{:03d}-{}".format(wall_id, si + 1, seg_i)
            if mode == "directshape":
                rect = (sx - half_w, sy0, sx + half_w, sy1)
                solid = make_rect_solid(back, u, z, orientation, rect, STUD_DEPTH_FT, mat_id, gs_id)
                ds = create_directshape(
                    solid, stud_id, "Metal Stud " + stud_id,
                    ds_comment(wall_id, "-", "STUD", stud_id), warnings)
                if ds:
                    made += 1
            else:
                if stud_symbol is None:
                    return made
                seg_h = sy1 - sy0
                pt = start.Add(u.Multiply(sx)).Add(orientation.Multiply(center_off)).Add(
                    z.Multiply((sy0 + sy1) / 2.0))
                inst = place_family(stud_symbol, pt, u, level, warnings)
                if inst:
                    set_param(inst, "Generated_By", APP_ID)
                    set_param(inst, "Stud_Width", STUD_WIDTH_FT)
                    set_param(inst, "Stud_Depth", STUD_DEPTH_FT)
                    set_param(inst, "Stud_Height", seg_h)
                    set_param(inst, "Wall_ID", wall_id)
                    set_param(inst, "Stud_Index", si)
                    set_param(inst, "Stud_ID", stud_id)
                    made += 1
    return made


if len(walls) == 0:
    OUT = "No walls found. Select one or more straight walls in Revit, then run Dynamo again."
else:
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        if mode == "family":
            activate_symbol(stud_symbol)
            activate_symbol(panel_symbol)
            activate_symbol(screw_symbol)

        processed_ids = set("W" + str(eid_value(w.Id)) for w in walls)
        if do_delete:
            result["deleted_previous"] = delete_previous(processed_ids, warnings)

        if mode == "directshape" and COLOR_BY_TYPE:
            styles = setup_styles(warnings)     # reassigns the module global read by emit_*

        screw_counter = 0
        z = XYZ.BasisZ

        for wall in walls:
            wall_id = "W" + str(eid_value(wall.Id))
            try:
                curve_data = get_wall_curve_data(wall)
                if not curve_data:
                    result["walls_skipped"].append(wall_id + ": not a straight wall")
                    continue

                start, end, u, wall_length = curve_data
                true_orientation = safe_normalize(wall.Orientation)   # raw exterior normal
                if true_orientation is None:
                    result["walls_skipped"].append(wall_id + ": cannot read Orientation")
                    continue

                wall_height = get_wall_height(wall)
                width = get_wall_width(wall)
                level = doc.GetElement(wall.LevelId) if (mode == "family" and wall.LevelId) else None

                # True face-offset geometry, computed ONCE per wall (fixes the centerline assumption).
                d_loc, core_center = wall_ref_geometry(wall, width, warnings)   # both from ext face
                center_off = d_loc - core_center                               # Location Line -> core center

                opening_rects = get_opening_rects(wall, start, u, wall_length, wall_height, warnings)
                stud_xs = stud_positions_for_wall(wall_length, opening_rects)

                # Studs: once per wall, centered on the core, interrupted at openings.
                result["studs_created"] += emit_studs(
                    start, u, z, true_orientation, center_off, wall_height,
                    stud_xs, opening_rects, level, wall_id)

                wall_has_face = False
                for face_config in FACE_LAYOUTS:
                    if not face_config.get("enabled", True):
                        continue
                    face_name = face_config["face_name"]
                    side = face_config["side"]

                    normal, face_offset = face_normal_and_offset(
                        true_orientation, d_loc, width, side, global_flip)

                    origin_face = start.Add(normal.Multiply(face_offset + PANEL_GAP_FROM_WALL_FACE_FT))
                    base_shift = face_config.get("base_edge_shift_ft", 0.0)
                    odd_shift = face_config.get("odd_row_additional_shift_ft", 4.0)
                    raw_rects = generate_raw_panel_rects(wall_length, wall_height, base_shift, odd_shift)

                    panel_index = 0
                    for raw in raw_rects:
                        x0, y0, x1, y1, row, row_shift, col = raw
                        pieces = subtract_openings_from_panel((x0, y0, x1, y1), opening_rects)
                        piece_index = 0
                        for piece in pieces:
                            piece_index += 1
                            panel_index += 1
                            panel_id = "{}-{}-R{}-C{}-P{}".format(
                                face_name, wall_id, row + 1, col + 1, piece_index)
                            is_cut = (abs((piece[2] - piece[0]) - PANEL_LENGTH_FT) > 0.01 or
                                      abs((piece[3] - piece[1]) - PANEL_HEIGHT_FT) > 0.01)
                            is_opening_cut = len(pieces) > 1

                            result["panels_created"] += emit_panel(
                                origin_face, u, z, normal, piece, level,
                                (wall_id, side, row, col, is_cut, is_opening_cut, panel_id),
                                face_name)
                            result["seams_created"] += emit_seams(
                                origin_face, u, z, normal, piece, panel_id, face_name, wall_id)
                            made, screw_counter = emit_screws(
                                origin_face, u, z, normal, piece, stud_xs, panel_id, face_name,
                                side, wall_id, level, screw_counter)
                            result["screws_created"] += made

                    wall_has_face = True
                    result["faces_processed"] += 1

                if wall_has_face:
                    result["walls_processed"] += 1

            except Exception as wall_ex:
                result["walls_skipped"].append(wall_id + ": error - " + str(wall_ex))
                warnings.append("Wall {} failed mid-processing: {}".format(wall_id, wall_ex))
                continue

        if do_screws and result["screws_created"] >= MAX_SCREWS_PER_RUN:
            result["notes"].append(
                "Screw creation stopped at MAX_SCREWS_PER_RUN ({}).".format(MAX_SCREWS_PER_RUN))

    except Exception as ex:
        result["notes"].append("FATAL: " + str(ex))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    OUT = result
