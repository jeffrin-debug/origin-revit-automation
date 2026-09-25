# Origin Wall Assembly Generator v4 - PHASE 1: METAL FRAMING ONLY
# Dynamo Python Script node for Revit (target: Revit 2027, PythonNet3 / CPython3 engine).
#
# WHAT THIS IS:
#   Phase 1 of a construction-accurate wall-assembly generator. This phase builds ONLY the
#   metal framing of a light-gauge steel stud wall as DirectShape solids:
#       - Vertical C-studs @ 16" OC (field studs, king studs on opening jambs, cripples
#         above headers / below sills).
#       - U-tracks: continuous bottom track (split around door openings) and top track
#         (continuous, split only if an opening reaches the ceiling).
#       - Opening framing: a flat-laid C header over every opening, a C sill under every
#         window opening, and short jack studs each side of every opening.
#
#   NO drywall / panels / seams / screws are generated here. That is Phase 2.
#
#   Framing members are true light-gauge cold-formed cross-sections (lipped-C studs and
#   plain U-tracks) built by extruding a transcribed 2D profile, not simplified boxes.
#
# REUSE:
#   The wall-reading, coordinate-frame, opening-detection, coloring, cleanup and main-loop
#   machinery is carried over verbatim from origin_drywall_unified_v3.py (proven / tested).
#   The only new geometry primitive is make_profile_solid(), which generalizes v3's
#   make_rect_solid() from a rectangle to an arbitrary closed polygon profile.
#
# STILL APPROXIMATE (documented, inherited from v3):
#   - Straight vertical walls only. Curved / slanted walls are skipped.
#   - Openings are approximated from hosted-insert bounding boxes (may be slightly oversized).
#   - This is layout / visualization geometry, not shop-drawing certification.

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

APP_ID = "ORIGIN_ASSEMBLY_V4"

# Phase 1 is DirectShape-only (self-contained solids, no families needed).
OUTPUT_MODE = "directshape"

# When True, each framing member is placed on its own colored Generic Model subcategory so the
# member types are distinguishable in shaded 3D and can be toggled in Visibility/Graphics.
COLOR_BY_TYPE = True

# Safety behavior.
DELETE_PREVIOUS_ORIGIN_ASSEMBLY = True
PROCESS_ALL_WALLS_IF_NONE_SELECTED = False

# Opening cutout settings (used by get_opening_rects, carried from v3).
CUT_OPENINGS = True
OPENING_CLEARANCE_FT = 0.05              # tolerance added around doors/windows

# ---- Framing dimensions (Revit internal units are feet; inch = 1/12 ft) ----
STUD_SPACING_FT = 16.0 / 12.0            # 16 in. OC
STUD_DEPTH_FT = 3.625 / 12.0            # C-stud through-wall depth (3-5/8" web)
FLANGE_FT = 1.25 / 12.0                 # C-stud flange width
LIP_FT = 0.1875 / 12.0                  # C-stud return lip
MAT_T_FT = 0.0451 / 12.0                # steel material thickness (~18 ga)
TRACK_DEPTH_FT = STUD_DEPTH_FT + 2.0 * MAT_T_FT    # track wraps the stud web
TRACK_FLANGE_FT = 1.25 / 12.0           # track leg height
MIN_SEG_FT = 0.25                       # skip framing pieces shorter than 3 in.

# Dynamo inputs:
#   IN[0] = selected wall(s) (or use current Revit selection if empty)
#   IN[5] = optional delete previous: True/False (overrides DELETE_PREVIOUS_ORIGIN_ASSEMBLY)
# ============================================================


# ============================================================
# Cross-section profiles (local 2D point lists, transcribed from spec)
# ============================================================
# Lipped C-stud. P = through-wall depth (0..STUD_DEPTH_FT), Q = flange direction
# (0..FLANGE_FT). The channel opens toward +Q.
# U-track. P = depth (0..TRACK_DEPTH_FT), R = leg height (0..TRACK_FLANGE_FT). Opens toward +R.

def _build_profiles():
    D = STUD_DEPTH_FT
    F = FLANGE_FT
    L = LIP_FT
    t = MAT_T_FT
    c = [(0, 0), (0, F), (L, F), (L, F - t), (t, F - t), (t, t),
         (D - t, t), (D - t, F - t), (D - L, F - t), (D - L, F), (D, F), (D, 0)]

    Dt = TRACK_DEPTH_FT
    Ht = TRACK_FLANGE_FT
    u = [(0, 0), (0, Ht), (t, Ht), (t, t), (Dt - t, t), (Dt - t, Ht), (Dt, Ht), (Dt, 0)]
    return c, u


C_PROFILE, U_PROFILE = _build_profiles()


# ------------------------------------------------------------
# Small vector / input helpers  (VERBATIM from v3)
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
# Wall reading  (VERBATIM from v3)
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
    if curve.GetType().Name != "Line":       # straight walls only
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


# ------------------------------------------------------------
# Openings  (VERBATIM from v3)
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


# ------------------------------------------------------------
# Geometry primitives
# ------------------------------------------------------------

def make_point(origin, u, z, x, y):     # VERBATIM from v3
    return origin.Add(u.Multiply(x)).Add(z.Multiply(y))


def make_profile_solid(origin, ax, ay, points2d, extrude_dir, depth, material_id=None, gstyle_id=None):
    """Generalization of v3's make_rect_solid to an arbitrary closed polygon.

    points2d : list of (p, q). Each 3D vertex = origin + ax*p + ay*q.
    ax, ay, extrude_dir : XYZ unit vectors (ax maps the first profile coord, ay the second).
    Builds a closed CurveLoop of straight lines through the vertices and extrudes it along
    extrude_dir by depth. Tries both winding orders (like make_rect_solid) so the caller need
    not worry about the loop orientation. Returns the Solid, or None on failure.
    """
    if depth <= 0 or points2d is None or len(points2d) < 3:
        return None

    verts = []
    for (p, q) in points2d:
        verts.append(origin.Add(ax.Multiply(p)).Add(ay.Multiply(q)))

    use_options = material_id is not None
    for order in (verts, list(reversed(verts))):
        try:
            loop = CurveLoop()
            n = len(order)
            for i in range(n):
                loop.Append(Line.CreateBound(order[i], order[(i + 1) % n]))
            loops = List[CurveLoop]()
            loops.Add(loop)
            if use_options:
                gs = gstyle_id if gstyle_id is not None else ElementId.InvalidElementId
                opts = SolidOptions(material_id, gs)
                return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth, opts)
            return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth)
        except:
            continue
    return None


def set_comments(element, text):        # VERBATIM from v3
    try:
        p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and (not p.IsReadOnly):
            p.Set(text)
    except:
        pass


def create_directshape(solid, data_id, name, comments, warnings):    # VERBATIM from v3
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
# DirectShape appearance: colored subcategories + materials  (trio VERBATIM from v3,
# with the framing STYLE_SPECS below)
# ------------------------------------------------------------

# kind -> (subcategory name, RGB). Reused/looked up by name, so reruns don't duplicate.
STYLE_SPECS = [
    ("STUD",     "ORIGIN Stud",         (150, 155, 165)),
    ("KINGSTUD", "ORIGIN King Stud",    (120, 140, 180)),
    ("JACK",     "ORIGIN Jack Stud",    (120, 170, 140)),
    ("CRIPPLE",  "ORIGIN Cripple Stud", (170, 170, 120)),
    ("TRACK",    "ORIGIN Track",        (90, 95, 105)),
    ("HEADER",   "ORIGIN Header",       (200, 140, 80)),
    ("SILL",     "ORIGIN Sill",         (200, 140, 80)),
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
    """Create (or find) a colored Generic Model subcategory + material per member type. Returns
    {kind: (material_id, graphics_style_id)} for make_profile_solid. Best-effort: on any failure
    the element is still created, just uncolored."""
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
# Cleanup  (VERBATIM from v3; scoped to the walls being processed)
# ------------------------------------------------------------

def delete_previous(processed_ids, warnings):
    """Delete prior v4-generated elements, SCOPED to the walls now being processed. Scoping is
    the fix for the old document-wide delete, which could wipe output on other walls. Deletes all
    v4 output on the processed walls; the framing is then rebuilt in the same run."""
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


# ------------------------------------------------------------
# Framing geometry helpers
# ------------------------------------------------------------

def stud_lines(wall_length, opening_rects):
    """Stud x-positions: 16" OC from x=0, an end stud at wall_length, plus jamb lines at every
    opening's x0 and x1. unique_sorted, clamped to [0, wall_length]. (Same intent as v3's
    stud_positions_for_wall.)"""
    xs = []
    x = 0.0
    while x <= wall_length + 0.001:
        xs.append(x)
        x += STUD_SPACING_FT
    if not xs:
        xs.append(0.0)
    if abs(xs[-1] - wall_length) > 0.1:
        xs.append(wall_length)

    for (ox0, oy0, ox1, oy1) in opening_rects:
        xs.append(clamp(ox0, 0.0, wall_length))
        xs.append(clamp(ox1, 0.0, wall_length))

    return unique_sorted([clamp(v, 0.0, wall_length) for v in xs])


def stud_segments(sx, wall_height, opening_rects):
    """Vertical (y0, y1) segments for a stud at position sx, with any portion that falls inside
    an opening removed -- so studs no longer run through doors/windows. Cripple segments remain
    above the header and below the sill. A stud sitting on an opening's jamb edge stays full
    height (it's the king stud).  (VERBATIM logic from v3.)"""
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


def is_jamb_line(sx, opening_rects, tol=0.02):
    """True if the stud line coincides with any opening jamb (x0 or x1) -> king stud."""
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if abs(sx - ox0) <= tol or abs(sx - ox1) <= tol:
            return True
    return False


def is_interior_line(sx, opening_rects):
    """True if the stud line falls strictly inside any opening width -> cripple studs."""
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if ox0 + 0.01 < sx < ox1 - 0.01:
            return True
    return False


def subtract_intervals(full_lo, full_hi, cuts):
    """Return [full_lo, full_hi] with each (clo, chi) cut range removed, as a list of (lo, hi)."""
    segments = [(full_lo, full_hi)]
    for (clo, chi) in cuts:
        new_segs = []
        for (lo, hi) in segments:
            if chi <= lo or clo >= hi:            # no overlap
                new_segs.append((lo, hi))
                continue
            if clo > lo:
                new_segs.append((lo, clo))
            if chi < hi:
                new_segs.append((chi, hi))
        segments = new_segs
    return segments


def ds_comment(wall_id, face_name, kind, eid):     # VERBATIM from v3
    """DirectShape Comments tag. Includes a delimited WALL=<id> token so cleanup can be scoped
    to specific walls (the trailing ' ' delimiter prevents W1 matching W12)."""
    return "{} | WALL={} | {} | {} | {}".format(APP_ID, wall_id, face_name, kind, eid)


# {kind: (material_id, graphics_style_id)} for DirectShape coloring; populated in the transaction.
styles = {}


def emit_member(origin, ax, ay, extrude_dir, depth, profile, kind, member_id, wall_id, warnings):
    """Build one framing member as a colored DirectShape. Returns 1 on success, 0 otherwise."""
    if depth < MIN_SEG_FT:
        return 0
    mat_id, gs_id = styles.get(kind, (None, None))
    solid = make_profile_solid(origin, ax, ay, profile, extrude_dir, depth, mat_id, gs_id)
    ds = create_directshape(
        solid, member_id, "{} {}".format(kind, member_id),
        ds_comment(wall_id, "-", kind, member_id), warnings)
    return 1 if ds else 0


def emit_framing(wall_id, start, u, z, orientation, center_off, wall_length, wall_height,
                 opening_rects, warnings):
    """Generate all Phase-1 metal framing for one wall. Returns a counts dict."""
    counts = {"studs": 0, "cripples": 0, "kings": 0, "jacks": 0,
              "tracks": 0, "headers": 0, "sills": 0}

    down = XYZ(0, 0, -1)
    depth_off = orientation.Multiply(center_off - STUD_DEPTH_FT / 2.0)      # C-stud depth centered on core
    track_off = orientation.Multiply(center_off - TRACK_DEPTH_FT / 2.0)     # track depth centered on core

    # ---- 2. Vertical C-studs (field studs / king studs / cripples) ----
    xs = stud_lines(wall_length, opening_rects)
    for si, sx in enumerate(xs):
        jamb = is_jamb_line(sx, opening_rects)
        interior = is_interior_line(sx, opening_rects)
        seg_i = 0
        for (sy0, sy1) in stud_segments(sx, wall_height, opening_rects):
            if (sy1 - sy0) < MIN_SEG_FT:
                continue
            seg_i += 1
            if jamb:
                kind, key = "KINGSTUD", "kings"
            elif interior:
                kind, key = "CRIPPLE", "cripples"
            else:
                kind, key = "STUD", "studs"
            member_id = "{}-{}-{:03d}-{}".format(wall_id, kind, si + 1, seg_i)
            origin = start.Add(u.Multiply(sx - FLANGE_FT / 2.0)).Add(depth_off).Add(z.Multiply(sy0))
            # ax = orientation maps profile P (depth); ay = u maps profile Q (flange); extrude up z.
            counts[key] += emit_member(origin, orientation, u, z, sy1 - sy0,
                                       C_PROFILE, kind, member_id, wall_id, warnings)

    # ---- 3. Bottom track: continuous, split around door openings (bottom reaches floor) ----
    door_cuts = [(ox0, ox1) for (ox0, oy0, ox1, oy1) in opening_rects if oy0 <= 0.05]
    ti = 0
    for (x0, x1) in subtract_intervals(0.0, wall_length, door_cuts):
        if (x1 - x0) < MIN_SEG_FT:
            continue
        ti += 1
        member_id = "{}-BTRK-{}".format(wall_id, ti)
        origin = start.Add(u.Multiply(x0)).Add(track_off).Add(z.Multiply(0.0))
        # ax = orientation maps P (depth); ay = z maps R (leg height, up); extrude along u.
        counts["tracks"] += emit_member(origin, orientation, z, u, x1 - x0,
                                        U_PROFILE, "TRACK", member_id, wall_id, warnings)

    # ---- 4. Top track: continuous, split only if an opening reaches the ceiling; legs point down ----
    ceil_cuts = [(ox0, ox1) for (ox0, oy0, ox1, oy1) in opening_rects if oy1 >= wall_height - 0.05]
    ti = 0
    for (x0, x1) in subtract_intervals(0.0, wall_length, ceil_cuts):
        if (x1 - x0) < MIN_SEG_FT:
            continue
        ti += 1
        member_id = "{}-TTRK-{}".format(wall_id, ti)
        origin = start.Add(u.Multiply(x0)).Add(track_off).Add(z.Multiply(wall_height))
        # same as bottom track but R grows downward (ay = -Z), so flanges point down.
        counts["tracks"] += emit_member(origin, orientation, down, u, x1 - x0,
                                        U_PROFILE, "TRACK", member_id, wall_id, warnings)

    # ---- 5/6/7. Per-opening framing: header, sill (windows), jack studs ----
    oi = 0
    for (ox0, oy0, ox1, oy1) in opening_rects:
        oi += 1
        span = ox1 - ox0
        is_window = oy0 > 0.05

        # 5. Header: flat-laid C over the opening, at z = oy1 (just above the opening head).
        if span >= MIN_SEG_FT:
            member_id = "{}-HDR-{}".format(wall_id, oi)
            origin = start.Add(u.Multiply(ox0)).Add(depth_off).Add(z.Multiply(oy1))
            # ax = orientation maps P (depth); ay = z maps Q (flange, up); extrude along u.
            counts["headers"] += emit_member(origin, orientation, z, u, span,
                                             C_PROFILE, "HEADER", member_id, wall_id, warnings)

        # 6. Sill: only for windows, flat-laid C just below the sill (z = oy0 - FLANGE_FT).
        if is_window and span >= MIN_SEG_FT:
            member_id = "{}-SILL-{}".format(wall_id, oi)
            origin = start.Add(u.Multiply(ox0)).Add(depth_off).Add(z.Multiply(oy0 - FLANGE_FT))
            counts["sills"] += emit_member(origin, orientation, z, u, span,
                                           C_PROFILE, "SILL", member_id, wall_id, warnings)

        # 7. Jack studs: one each side, just inside the jamb, from floor/sill-top up to header underside.
        jack_bottom = oy0 if is_window else 0.0
        jack_h = oy1 - jack_bottom
        if jack_h >= MIN_SEG_FT:
            jx_positions = [clamp(ox0 + FLANGE_FT, 0.0, wall_length),
                            clamp(ox1 - FLANGE_FT, 0.0, wall_length)]
            for jn, jx in enumerate(jx_positions):
                member_id = "{}-JACK-{}-{}".format(wall_id, oi, jn + 1)
                origin = start.Add(u.Multiply(jx - FLANGE_FT / 2.0)).Add(depth_off).Add(
                    z.Multiply(jack_bottom))
                counts["jacks"] += emit_member(origin, orientation, u, z, jack_h,
                                               C_PROFILE, "JACK", member_id, wall_id, warnings)

    return counts


# ============================================================
# MAIN
# ============================================================

result = {
    "app_id": APP_ID,
    "output_mode": "directshape",
    "phase": "1_metal_framing",
    "deleted_previous": 0,
    "walls_requested": 0,
    "walls_processed": 0,
    "walls_skipped": [],
    "studs_created": 0,       # field studs (not on jamb lines, not inside openings)
    "cripples_created": 0,    # stud segments above headers / below sills
    "kings_created": 0,       # studs sitting on opening jamb lines (full height)
    "jacks_created": 0,
    "tracks_created": 0,
    "headers_created": 0,
    "sills_created": 0,
    "warnings": [],
    "notes": []
}
warnings = result["warnings"]

do_delete = as_bool(get_in(5), DELETE_PREVIOUS_ORIGIN_ASSEMBLY)

walls = get_input_walls(warnings)
result["walls_requested"] = len(walls)

if len(walls) == 0:
    OUT = "No walls found. Select one or more straight walls in Revit, then run Dynamo again."
else:
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        processed_ids = set("W" + str(eid_value(w.Id)) for w in walls)
        if do_delete:
            result["deleted_previous"] = delete_previous(processed_ids, warnings)

        if COLOR_BY_TYPE:
            styles = setup_styles(warnings)     # reassigns the module global read by emit_member

        z = XYZ.BasisZ

        for wall in walls:
            wall_id = "W" + str(eid_value(wall.Id))
            try:
                curve_data = get_wall_curve_data(wall)
                if not curve_data:
                    result["walls_skipped"].append(wall_id + ": not a straight wall")
                    continue

                start, end, u, wall_length = curve_data
                orientation = safe_normalize(wall.Orientation)     # raw exterior normal
                if orientation is None:
                    result["walls_skipped"].append(wall_id + ": cannot read Orientation")
                    continue

                wall_height = get_wall_height(wall)
                width = get_wall_width(wall)

                # True face-offset geometry (fixes the centerline assumption). Framing centers on core.
                d_loc, core_center = wall_ref_geometry(wall, width, warnings)
                center_off = d_loc - core_center                   # Location Line -> core mid-plane

                opening_rects = get_opening_rects(wall, start, u, wall_length, wall_height, warnings)

                counts = emit_framing(
                    wall_id, start, u, z, orientation, center_off,
                    wall_length, wall_height, opening_rects, warnings)

                result["studs_created"] += counts["studs"]
                result["cripples_created"] += counts["cripples"]
                result["kings_created"] += counts["kings"]
                result["jacks_created"] += counts["jacks"]
                result["tracks_created"] += counts["tracks"]
                result["headers_created"] += counts["headers"]
                result["sills_created"] += counts["sills"]
                result["walls_processed"] += 1

            except Exception as wall_ex:
                result["walls_skipped"].append(wall_id + ": error - " + str(wall_ex))
                warnings.append("Wall {} failed mid-processing: {}".format(wall_id, wall_ex))
                continue

    except Exception as ex:
        result["notes"].append("FATAL: " + str(ex))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    OUT = result
