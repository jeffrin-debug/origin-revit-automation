# Origin Ceiling Assembly Generator v1 - FRAMING + DRYWALL (FURRED / SUSPENDED)
# Dynamo Python Script node for Revit. Version-tolerant: runs on Revit 2025 (Dynamo CPython3, the
# Omniverse-export version) AND 2026/2027 (PythonNet3). No f-strings; eid_value() handles the
# ElementId .Value/.IntegerValue change.
#
# WHAT THIS IS:
#   The ceiling counterpart of origin_wall_assembly_v4_phase2.py. For each selected Revit CEILING
#   it builds a construction-accurate gypsum ceiling as DirectShape solids:
#       - Metal FURRING (hat) channels @ 16" OC, run across the ceiling just above the drywall.
#       - REINFORCEMENT for long spans (ASTM C754): a 7/8" furring channel can only span ~4 ft
#         before the gypsum weight sags it, so when the furring run exceeds MAX_FURRING_SPAN_FT the
#         script adds MAIN carrying channels perpendicular to the furring @ <=48" OC (sitting on top
#         of it). HANGER wires are OFF by default (GENERATE_HANGERS) - they only apply when there is
#         a structural deck/slab ABOVE to anchor into; with no deck the mains fasten directly to the
#         joists/trusses. Small ceilings (run <= limit) stay direct-furred with no mains.
#       - GYPSUM board on the underside (single face, room side), laid in a staggered grid,
#         clipped to the ceiling's boundary polygon, cut around holes/fixtures as SINGLE pieces,
#         tapered long edges on full field boards, 2 layers for fire-rated ceilings.
#       - Drywall SCREWS along the furring lines on the room-facing surface (markers + coords).
#       - A sidecar JSON assembly manifest and a base-ceiling-hidden isolation view.
#
# HOW IT DIFFERS FROM THE WALL SCRIPT (by design):
#   - Single-sided (drywall only on the underside; the top faces the plenum).
#   - Horizontal: the layout plane is world X-Y at the ceiling's bottom-face elevation.
#   - Boundary is the ceiling's polygon (any shape, incl. holes/courtyards), not a straight line.
#     Boards/furring are clipped to it with Revit boolean intersect (robust for concave + holes).
#   - Framing is furring hat-channels, not vertical C-studs.
#
# STILL APPROXIMATE (documented):
#   - The board/furring grid is world-X/Y aligned (not rotated to the room's long edge) - fine for
#     axis-aligned rooms; a rotation pass is a later refinement.
#   - Hosted fixtures are cut from their plan bounding box (may be slightly oversized). Holes drawn
#     into the ceiling sketch are handled automatically (they come through as inner boundary loops).
#   - Layout/visualization geometry, not shop-drawing certification.

import clr
import math
import json

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
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

APP_ID = "ORIGIN_CEILING_V1"

GENERATE_FURRING = True
GENERATE_DRYWALL = True
GENERATE_SCREWS = True
COLOR_BY_TYPE = True
DELETE_PREVIOUS = True
PROCESS_ALL_CEILINGS_IF_NONE_SELECTED = False

# Which ceiling elements THIS node processes (per-element "plugin" split, user 2026-07-17):
#   "all"      - every gathered ceiling incl. soffits (legacy single-node behavior)
#   "ceilings" - skip soffit-named elements (the CEILINGS node; soffits have their own node)
#   "soffits"  - ONLY soffit-named elements, self-collected model-wide regardless of the
#                dropdown/selection (the SOFFITS node - like the beams/columns nodes)
PROCESS_MODE = "all"

IN_FT = 1.0 / 12.0

# ---- Furring (hat / DWC channel) ----
FURRING_SPACING_FT = 16.0 * IN_FT        # 16 in. OC (ASTM C754: cross-furring <= 24" OC; 16" for 5/8")
FURRING_FACE_FT = 2.5 * IN_FT            # channel face width (across the run)
FURRING_HEIGHT_FT = 0.875 * IN_FT        # 7/8" DWC furring channel depth
MAT_T_FT = 0.0451 * IN_FT                # steel material thickness (~18 ga)
MIN_SEG_FT = 0.25                        # skip framing/board slivers < 3 in.

# ---- Walls (room separation) ----
# Stop the ceiling drywall at WALLS - same requirement as the wall assembly corners. Every wall's
# plan footprint is subtracted from the clip mask (a board/channel can never enter a wall), and
# the board grid stops-and-restarts at each wall face so no single panel runs under a wall into
# the next room - each room gets its own separate panels for per-room Isaac interaction.
CLIP_CEILING_AT_WALLS = True

# ---- Per-room generation ----
# Generate the ceiling PER ROOM - the same pattern the wall script uses per wall run. Each Revit
# Room's boundary polygon (taken at wall FINISH faces via Room.GetBoundarySegments, continuous
# across doorways because the segments follow the room-bounding walls / room separation lines) is
# an independent bounded region: boards, furring and mains are laid out inside it with their own
# grid origin and are cut at its edges, so nothing is ever generated outside its own room and no
# element spans two rooms. When True this REPLACES the legacy whole-ceiling-grid +
# wall-subtraction path above for any ceiling that has Rooms (set False to compare old vs new
# output on the same model). A ceiling with NO overlapping Room (e.g. a soffit) falls back to
# the legacy path with a warning, so soffits keep working until their own pass. Ceiling area
# covered by no Room gets no panels and is reported in the warnings.
CEILING_PER_ROOM = True
MIN_ROOM_AREA_SF = 1.0        # skip unenclosed/degenerate rooms (Revit reports their area as 0)

# ---- Soffits (separate flow) ----
# A soffit (Ceiling element whose type/family name contains "soffit", host tag S###) is a narrow
# run - straight or L-shaped - spanning from one wall to an adjacent wall. It gets EXACTLY TWO
# custom-cut boards: one per leg of an L (butt joint at the inner corner), or a mid-run split on
# a straight run. Each board must be 2..16 ft (warnings otherwise). Boards clip against the
# wall-subtracted mask so they end at the walls the soffit spans between - no penetration.
# No 4x8 grid, no rooms/zones, no carrying mains (furring only).
SOFFIT_SEPARATE_FLOW = True
SOFFIT_MAX_BOARD_FT = 16.0
SOFFIT_MIN_BOARD_FT = 2.0

# ---- Suspension / reinforcement (ASTM C754) ----
# A 7/8" furring channel can only span so far before the gypsum weight deflects it and the ceiling
# sags. Past MAX_FURRING_SPAN_FT it must be carried by MAIN (carrying) channels at MAIN_SPACING_FT
# perpendicular to the furring (breaking it into <=4 ft spans). Small ceilings (run <= the limit)
# stay direct-furred end-to-end with no mains. ASTM C754 prescriptive limits (non-seismic): furring
# span <= 48", mains <= 48" OC, hangers <= 48" OC and <= 16 sq ft each.
GENERATE_MAINS = True
MAX_FURRING_SPAN_FT = 48.0 * IN_FT       # max unsupported furring span before a main is required
MAIN_SPACING_FT = 48.0 * IN_FT           # carrying channels <= 4 ft OC (perpendicular to furring)
MAIN_DEPTH_FT = 1.5 * IN_FT              # 1-1/2" cold-rolled carrying channel (CRC)
MAIN_FACE_FT = 0.5 * IN_FT               # CRC flange/face width

# HANGER WIRES only exist where the mains can be hung from a structural deck (concrete slab, etc.)
# ABOVE the ceiling. If there is NO deck above (top floor under a roof, or the framing fastens
# DIRECTLY to the joists/trusses above), you don't use hanger rods - leave this False and the mains
# read as direct-fastened to the structure. Set True only when there is a slab/deck above to anchor
# the #12 wires into. ASTM C754 (when used): hangers <= 48" OC along each main, <= 16 sq ft each.
GENERATE_HANGERS = False
HANGER_SPACING_FT = 48.0 * IN_FT         # hanger wires <= 4 ft OC along each main
HANGER_MAX_AREA_SF = 16.0                # informational: each hanger supports <= 16 sq ft
HANGER_DIA_FT = 0.106 / 12.0            # #12 ga hanger wire (~0.106")
HANGER_DROP_FT = 12.0 * IN_FT            # modeled wire length up toward the deck (nominal)
END_SUPPORT_SETBACK_FT = 6.0 * IN_FT     # first hanger within 6" of a main's ends (ASTM C754)

# ---- Splicing: channels ship in stock lengths and are lapped end-to-end, not one long piece ----
# A furring / carrying channel can't be one continuous 40-ft run; it is made of stock-length pieces
# nested/overlapped at each splice and secured (screws / tie wire). Splices are STAGGERED between
# adjacent channels so the joints don't line up. Each stock piece becomes its own element (good for
# per-element sim). ASTM C754 typical: furring lap ~8", carrying-channel lap 12".
SPLICE_CHANNELS = True
FURRING_STOCK_LENGTH_FT = 12.0           # 7/8" furring/hat channel stock length (also 10 ft)
FURRING_SPLICE_LAP_FT = 8.0 * IN_FT      # ~8" nested lap at a furring splice
MAIN_STOCK_LENGTH_FT = 16.0              # 1-1/2" CRC carrying channel stock length (also 20 ft)
MAIN_SPLICE_LAP_FT = 12.0 * IN_FT        # 12" lap at a carrying-channel splice (ASTM C754)
SPLICE_STAGGER_FT = 4.0                  # shift splices this much between adjacent channels
SPLICE_NEST_OFFSET = True                # nudge a lapping piece by one material thickness (nested look)

# ---- Drywall ----
PANEL_LENGTH_FT = 8.0                    # board long dimension (along X); 12.0 for 4x12
PANEL_WIDTH_FT = 4.0                     # board short dimension (course step, along Y)
DRYWALL_THICKNESS_STD_FT = 0.5 * IN_FT
DRYWALL_THICKNESS_RATED_FT = 0.625 * IN_FT
DRYWALL_LAYERS_RATED = 2
DRYWALL_LAYERS_STD = 1
CODE_GAP_FT = (1.0 / 8.0) * IN_FT        # 1/8" total gap between boards
LAYER_H_STAGGER_FT = PANEL_LENGTH_FT / 2.0
LAYER_V_STAGGER_FT = PANEL_WIDTH_FT / 2.0
ODD_ROW_SHIFT_FT = 4.0                   # stagger odd courses

# Maximize whole 4x8 sheets: kill the odd-row stagger so every row starts at its region's origin
# - far fewer cut pieces (a full-sheet grid with a single rip at each far edge). Joints then line
# up row-to-row, which is not how sheets are hung on a real job, but it is what the sim needs
# (user 2026-07-16: "I want 4x8 drywall everywhere possible"). Set False for staggered courses.
MAXIMIZE_WHOLE_PANELS = True
TAPERED_LONG_EDGES = True
TAPER_DEPTH_FT = 0.0625 * IN_FT
TAPER_WIDTH_FT = 2.25 * IN_FT
MIN_PIECE_WIDTH_FT = 0.25
MIN_PIECE_HEIGHT_FT = 0.25

# ---- Fasteners ----
SCREW_SPACING_FT = 12.0 * IN_FT          # field screws 12" OC (ceilings) along each furring line
SCREW_EDGE_SETBACK_FT = 0.5 * IN_FT      # set screws back from board edges/ends (USG/GA min 3/8")
SCREW_EDGE_TOL_FT = 0.05                 # a furring line / board end within this of an edge = a joint
SCREW_MARKER_SIZE_FT = 0.5 * IN_FT
SCREW_MARKER_DEPTH_FT = 0.15 * IN_FT     # total head thickness (mostly embedded)
SCREW_HEAD_PROUD_FT = 0.02 * IN_FT       # subtle proud amount below the drywall
SCREWS_OUTER_LAYER_ONLY = True
MAX_SCREWS_PER_CEILING = 8000

# ---- Openings / fixtures ----
CUT_FIXTURES = True                      # cut around family instances hosted on the ceiling
FIXTURE_CLEARANCE_FT = 0.05

# ---- Fire rating override: None = auto-detect; True/False = force ----
FORCE_FIRE_RATED = None

# ---- Export ----
CREATE_EXPORT_VIEW = True
EXPORT_VIEW_NAME = "ORIGIN Assembly"
WRITE_MANIFEST = True
MANIFEST_PATH = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\origin_ceiling_manifest.json"

HOLE_MARGIN_FT = 0.05

# Dynamo inputs:
#   IN[0] = selected ceiling(s) (or current selection)
#   IN[5] = delete previous (override)
#   IN[6] = generate drywall (override)
#   IN[7] = force fire-rated (override)
#   IN[8] = generate screws (override)
# ============================================================


# ------------------------------------------------------------
# Small helpers  (shared with the wall script)
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
    try:
        return eid.Value
    except:
        pass
    try:
        return eid.IntegerValue
    except:
        return -1


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def unique_sorted(values, tolerance=0.01):
    out = []
    for v in sorted(values):
        if not out or abs(out[-1] - v) > tolerance:
            out.append(v)
    return out


# ------------------------------------------------------------
# Nomenclature helpers (hierarchical element naming)
#   host tag : C### (ceiling) or S### (soffit, type name contains 'soffit'), on the ceiling Mark
#   drywall  : DP-<host>-<seq>        (single underside face -> no face letter)
#   furring  : ST-<host>-<seq>
#   screw    : SC-<host>-<seq>
# ------------------------------------------------------------

def set_mark(element, name):
    """Best-effort write of the nomenclature name to an element's Mark (schedulable/taggable)."""
    try:
        mk = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and (not mk.IsReadOnly):
            mk.Set(name)
    except:
        pass


def _host_mark_param(elem):
    try:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if p:
            return p
    except:
        pass
    try:
        return elem.LookupParameter("Mark")
    except:
        return None


def _parse_ceiling_mark(s):
    """('C'|'S', number) a ceiling Mark encodes (e.g. 'C001', 'S12'), or (None, None)."""
    if not s:
        return None, None
    t = s.strip().upper()
    if len(t) < 2 or t[0] not in ("C", "S") or not t[1:].isdigit():
        return None, None
    try:
        n = int(t[1:])
    except:
        return None, None
    return (t[0], n) if n > 0 else (None, None)


def ceiling_prefix(ceiling):
    """'S' for a soffit (type or family name contains 'soffit'), else 'C'."""
    names = []
    try:
        ct = doc.GetElement(ceiling.GetTypeId())
        if ct is not None:
            try:
                names.append(ct.Name)
            except:
                pass
            try:
                if ct.FamilyName:
                    names.append(ct.FamilyName)
            except:
                pass
    except:
        pass
    for nm in names:
        try:
            if "soffit" in nm.lower():
                return "S"
        except:
            pass
    return "C"


def assign_ceiling_numbers(ceilings, warnings):
    """Give each selected ceiling a stable, per-type-unique host tag: 'C###' (ceiling) or 'S###'
    (soffit). Reuses the tag already in the ceiling's Mark when its prefix still matches the
    element's current type; new numbers are the smallest free within that prefix across ALL
    ceilings in the model, written back to Mark so reruns stay stable. Selected ceilings are
    numbered in ElementId order. Returns {ceiling_eid_value: 'C001'/'S001'}. Runs in a
    transaction. Best-effort: Mark write failures are reported, not fatal."""
    taken = {"C": set(), "S": set()}
    try:
        for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
            p = _host_mark_param(c)
            pr, n = _parse_ceiling_mark(p.AsString()) if p else (None, None)
            if pr in ("C", "S") and n is not None:
                taken[pr].add(n)
    except Exception as ex:
        warnings.append("Ceiling-number scan failed (continuing): {}".format(ex))

    selected = sorted(ceilings, key=lambda c: eid_value(c.Id))
    assigned = {}
    used_here = {"C": set(), "S": set()}
    # Pass 1: honor an existing Mark whose prefix matches the ceiling's current type prefix.
    for c in selected:
        pref = ceiling_prefix(c)
        p = _host_mark_param(c)
        pr, n = _parse_ceiling_mark(p.AsString()) if p else (None, None)
        if pr == pref and n is not None and n not in used_here[pref]:
            assigned[eid_value(c.Id)] = "{}{:03d}".format(pref, n)
            used_here[pref].add(n)
    # Pass 2: assign the rest the smallest free number within their prefix; persist to Mark.
    nxt = {"C": 1, "S": 1}
    for c in selected:
        key = eid_value(c.Id)
        pref = ceiling_prefix(c)
        if key not in assigned:
            while nxt[pref] in taken[pref] or nxt[pref] in used_here[pref]:
                nxt[pref] += 1
            used_here[pref].add(nxt[pref])
            taken[pref].add(nxt[pref])
            assigned[key] = "{}{:03d}".format(pref, nxt[pref])
        tag = assigned[key]
        p = _host_mark_param(c)
        if p is not None and not p.IsReadOnly:
            try:
                if (p.AsString() or "") != tag:
                    p.Set(tag)
            except Exception as ex:
                warnings.append("Could not set Mark on ceiling {}: {}".format(eid_value(c.Id), ex))
    return assigned


# ------------------------------------------------------------
# 2D polygon helpers (world X-Y)
# ------------------------------------------------------------

def poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def point_in_polygon(px, py, poly):
    """Ray-casting point-in-polygon. poly = list of (x, y)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def rects_overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def rect_area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


# ------------------------------------------------------------
# Ceiling reading
# ------------------------------------------------------------

def apply_process_mode(ceilings, warnings):
    """PROCESS_MODE='ceilings' drops soffit-named elements (the Soffits node owns them)."""
    if PROCESS_MODE != "ceilings":
        return ceilings
    kept = [e for e in ceilings if ceiling_prefix(e) != "S"]
    if len(kept) != len(ceilings):
        warnings.append("{} soffit(s) skipped here - the ORIGIN Soffits node handles them".format(
            len(ceilings) - len(kept)))
    return kept


def get_input_ceilings(warnings):
    ceilings = []
    if PROCESS_MODE == "soffits":
        # The Soffits plugin self-collects every soffit-named ceiling, model-wide.
        for e in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
            if ceiling_prefix(e) == "S":
                ceilings.append(e)
        return ceilings
    data = get_in(0)
    if data:
        for item in ensure_list(data):
            e = unwrap(item)
            if isinstance(e, Ceiling):
                ceilings.append(e)
    if ceilings:
        return apply_process_mode(ceilings, warnings)
    try:
        for eid in list(uidoc.Selection.GetElementIds()):
            e = doc.GetElement(eid)
            if isinstance(e, Ceiling):
                ceilings.append(e)
    except Exception as ex:
        warnings.append("Could not read selection: {}".format(ex))
    if ceilings:
        return apply_process_mode(ceilings, warnings)
    if PROCESS_ALL_CEILINGS_IF_NONE_SELECTED:
        for e in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
            ceilings.append(e)
    return apply_process_mode(ceilings, warnings)


def get_ceiling_loops(ceiling, warnings):
    """Return (loops, z) where loops = list of polygons [[(x,y),...], ...] with the LARGEST-area
    loop first (outer) and the rest treated as holes, and z = the bottom-face elevation. Extracted
    from the ceiling's geometry (the downward-facing planar face), tessellating any curved edges."""
    opt = Options()
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False
    try:
        opt.DetailLevel = ViewDetailLevel.Medium
    except:
        pass

    best_face = None
    best_z = None
    try:
        geo = ceiling.get_Geometry(opt)
        for g in geo:
            solid = g if isinstance(g, Solid) else None
            if solid is None or solid.Volume <= 0:
                continue
            for face in solid.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                nrm = face.FaceNormal
                if nrm.Z < -0.9:                       # downward-facing = room-side bottom face
                    z = face.Origin.Z
                    if best_face is None or z < best_z:   # lowest such face
                        best_face = face
                        best_z = z
    except Exception as ex:
        warnings.append("Ceiling {}: geometry read failed ({})".format(eid_value(ceiling.Id), ex))
        return None, None

    if best_face is None:
        return None, None

    loops = []
    try:
        curve_loops = best_face.GetEdgesAsCurveLoops()
        for cl in curve_loops:
            pts = []
            for c in cl:
                try:
                    tess = c.Tessellate()
                except:
                    tess = [c.GetEndPoint(0), c.GetEndPoint(1)]
                for p in tess:
                    if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                        pts.append((p.X, p.Y))
            if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                pts = pts[:-1]
            if len(pts) >= 3:
                loops.append(pts)
    except Exception as ex:
        warnings.append("Ceiling {}: loop extraction failed ({})".format(eid_value(ceiling.Id), ex))
        return None, None

    if not loops:
        return None, None
    loops.sort(key=poly_area, reverse=True)     # largest = outer, rest = holes
    return loops, best_z


def ceiling_is_fire_rated(ceiling, warnings):
    if FORCE_FIRE_RATED is not None:
        return bool(FORCE_FIRE_RATED)
    try:
        ct = doc.GetElement(ceiling.GetTypeId())
    except:
        ct = None
    if ct is None:
        return False
    try:
        p = ct.LookupParameter("Fire Rating")
        if p is not None and p.HasValue:
            st = p.StorageType
            if st == StorageType.String:
                s = p.AsString()
                if s and any(ch.isdigit() for ch in s):
                    return True
            elif st == StorageType.Double and p.AsDouble() > 0.01:
                return True
            elif st == StorageType.Integer and p.AsInteger() > 0:
                return True
    except:
        pass
    try:
        name = ct.Name.lower()
        for kw in ("fire", "rated", "type x", "type-x", "1 hr", "2 hr", "1-hr", "2-hr", "1hr", "2hr"):
            if kw in name:
                return True
    except:
        pass
    return False


def get_fixture_rects(ceiling, warnings):
    """Plan-view (x0,y0,x1,y1) bounding rects of family instances hosted on this ceiling
    (lights, diffusers, access panels). Best-effort."""
    rects = []
    if not CUT_FIXTURES:
        return rects
    cid = ceiling.Id
    try:
        col = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()
        for fi in col:
            host = None
            try:
                host = fi.Host
            except:
                host = None
            if host is None or host.Id != cid:
                continue
            try:
                bb = fi.get_BoundingBox(None)
            except:
                bb = None
            if not bb:
                continue
            x0 = bb.Min.X - FIXTURE_CLEARANCE_FT
            y0 = bb.Min.Y - FIXTURE_CLEARANCE_FT
            x1 = bb.Max.X + FIXTURE_CLEARANCE_FT
            y1 = bb.Max.Y + FIXTURE_CLEARANCE_FT
            if (x1 - x0) > 0.1 and (y1 - y0) > 0.1:
                rects.append((x0, y0, x1, y1))
    except Exception as ex:
        warnings.append("Ceiling {}: fixture scan failed ({})".format(eid_value(ceiling.Id), ex))
    return rects


# ------------------------------------------------------------
# Geometry primitives  (shared with the wall script)
# ------------------------------------------------------------

def make_point(origin, u, v, x, y):
    return origin.Add(u.Multiply(x)).Add(v.Multiply(y))


def _extrude_loops(loops, extrude_dir, depth, material_id, gstyle_id):
    if material_id is not None:
        gs = gstyle_id if gstyle_id is not None else ElementId.InvalidElementId
        opts = SolidOptions(material_id, gs)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth, opts)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth)


def make_planar_poly_solid(origin, u, v, normal, pts2d, depth, material_id=None, gstyle_id=None):
    clean = []
    for p in pts2d:
        if not clean or abs(clean[-1][0] - p[0]) > 1e-7 or abs(clean[-1][1] - p[1]) > 1e-7:
            clean.append(p)
    if len(clean) >= 2 and abs(clean[0][0] - clean[-1][0]) < 1e-7 and abs(clean[0][1] - clean[-1][1]) < 1e-7:
        clean = clean[:-1]
    if len(clean) < 3 or depth <= 0:
        return None
    verts = [make_point(origin, u, v, x, y) for (x, y) in clean]
    for order in (verts, list(reversed(verts))):
        try:
            loop = CurveLoop()
            n = len(order)
            for i in range(n):
                loop.Append(Line.CreateBound(order[i], order[(i + 1) % n]))
            loops = List[CurveLoop]()
            loops.Add(loop)
            return _extrude_loops(loops, normal, depth, material_id, gstyle_id)
        except:
            continue
    return None


def make_rect_solid(origin, u, v, normal, rect, depth, material_id=None, gstyle_id=None):
    x0, y0, x1, y1 = rect
    if (x1 - x0) < 0.001 or (y1 - y0) < 0.001 or depth <= 0:
        return None
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return make_planar_poly_solid(origin, u, v, normal, pts, depth, material_id, gstyle_id)


def make_profile_solid(origin, ax, ay, points2d, extrude_dir, depth, material_id=None, gstyle_id=None):
    if depth <= 0 or points2d is None or len(points2d) < 3:
        return None
    verts = [origin.Add(ax.Multiply(p)).Add(ay.Multiply(q)) for (p, q) in points2d]
    for order in (verts, list(reversed(verts))):
        try:
            loop = CurveLoop()
            n = len(order)
            for i in range(n):
                loop.Append(Line.CreateBound(order[i], order[(i + 1) % n]))
            loops = List[CurveLoop]()
            loops.Add(loop)
            return _extrude_loops(loops, extrude_dir, depth, material_id, gstyle_id)
        except:
            continue
    return None


def boolean_op(a, b, op):
    if a is None:
        return None
    if b is None:
        return a
    try:
        return BooleanOperationsUtils.ExecuteBooleanOperation(a, b, op)
    except:
        return a


def solid_ok(s):
    """A usable, non-empty solid (a boolean clip that lands fully outside returns ~0 volume)."""
    try:
        return s is not None and s.Volume > 1e-7
    except:
        return s is not None


def make_tapered_board_solid(origin_at_z, u, v, normal, rect, thickness, material_id=None, gstyle_id=None):
    """Ceiling board whose ROOM-FACING (bottom, -normal) side recesses near its two long edges
    (the factory taper). Built by extruding a (width x thickness) profile along the board LENGTH
    (u = X). normal = +Z (up). The taper is on the bottom, so it recesses at low thickness-q."""
    x0, y0, x1, y1 = rect
    length = x1 - x0
    width = y1 - y0
    if length < 0.001 or width < 0.001 or thickness <= 0:
        return None
    td = min(TAPER_DEPTH_FT, thickness * 0.9)
    tw = TAPER_WIDTH_FT
    if td <= 0 or tw <= 0 or width <= 2.0 * tw + 0.01:
        return make_rect_solid(origin_at_z, u, v, normal, rect, thickness, material_id, gstyle_id)
    origin = make_point(origin_at_z, u, v, x0, y0)
    # profile: (w along v = board width, d along normal = thickness). Room side is d=0 (bottom);
    # it recesses to d=td at the two long edges (w=0 and w=width) over tw. Top (d=thickness) flat.
    profile = [(0.0, td), (tw, 0.0), (width - tw, 0.0), (width, td),
               (width, thickness), (0.0, thickness)]
    return make_profile_solid(origin, v, normal, profile, u, length, material_id, gstyle_id)


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
        try:
            p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if p and not p.IsReadOnly:
                p.Set(comments)
        except:
            pass
        set_mark(ds, name)          # nomenclature also on Mark: schedulable + taggable
        return ds
    except Exception as ex:
        warnings.append("DirectShape create failed for {}: {}".format(data_id, ex))
        return None


# ------------------------------------------------------------
# Colored subcategories + materials  (shared machinery)
# ------------------------------------------------------------

STYLE_SPECS = [
    ("FURRING", "ORIGIN Furring Channel", (150, 155, 165)),
    ("MAIN",    "ORIGIN Carrying Channel", (95, 110, 140)),   # main runners, deeper blue-grey
    ("HANGER",  "ORIGIN Hanger Wire",      (210, 180, 90)),   # hanger wires, brass-ish
    ("GWB",     "ORIGIN Drywall Base",    (235, 228, 214)),
    ("GWB2",    "ORIGIN Drywall Face",    (222, 212, 190)),
    ("SCREW",   "ORIGIN Screw",           (200, 60, 60)),
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
    styles = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
    except Exception as ex:
        warnings.append("Could not access Generic Model category: {}".format(ex))
        return styles
    created = []
    for kind, name, rgb in STYLE_SPECS:
        try:
            mid = get_or_create_material(name, rgb)
            get_or_create_subcategory(gm, name, mid, rgb)
            created.append((kind, name, mid))
        except Exception as ex:
            warnings.append("Coloring for {} failed: {}".format(kind, ex))
    try:
        doc.Regenerate()
    except:
        pass
    subs = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
        for sc in gm.SubCategories:
            subs[sc.Name] = sc
    except:
        pass
    for kind, name, mid in created:
        gsid = ElementId.InvalidElementId
        sub = subs.get(name)
        if sub is not None:
            try:
                gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
                if gs:
                    gsid = gs.Id
            except:
                pass
        styles[kind] = (mid, gsid)
    return styles


styles = {}


# ------------------------------------------------------------
# Cleanup (scoped to processed ceilings)
# ------------------------------------------------------------

def delete_previous(processed_ids, warnings):
    ids = List[ElementId]()
    tokens = ["CEILING=" + c + " " for c in processed_ids]
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
            if comment and any(tok in comment for tok in tokens):
                ids.Add(e.Id)
    except Exception as ex:
        warnings.append("Cleanup failed: {}".format(ex))
    count = ids.Count
    if count > 0:
        doc.Delete(ids)
    return count


def ensure_export_view(warnings):
    if not CREATE_EXPORT_VIEW:
        return "disabled"
    try:
        view = None
        for v in FilteredElementCollector(doc).OfClass(View3D):
            try:
                if (not v.IsTemplate) and v.Name == EXPORT_VIEW_NAME:
                    view = v
                    break
            except:
                pass
        if view is None:
            vft = None
            for t in FilteredElementCollector(doc).OfClass(ViewFamilyType):
                try:
                    if t.ViewFamily == ViewFamily.ThreeDimensional:
                        vft = t
                        break
                except:
                    pass
            if vft is None:
                warnings.append("Export view: no 3D ViewFamilyType found; skipped.")
                return "no_view_type"
            view = View3D.CreateIsometric(doc, vft.Id)
            try:
                view.Name = EXPORT_VIEW_NAME
            except:
                pass
        # Isolate to ONLY the generated assembly: hide every model category except Generic Model,
        # so the base ceiling (and walls/etc.) are absent when you export FROM this view.
        try:
            gm_id = ElementId(BuiltInCategory.OST_GenericModel)
            for cat in doc.Settings.Categories:
                try:
                    if cat.CategoryType != CategoryType.Model or cat.Id == gm_id:
                        continue
                    if view.CanCategoryBeHidden(cat.Id):
                        view.SetCategoryHidden(cat.Id, True)
                except:
                    pass
        except Exception as ex:
            warnings.append("Export view isolation partial: {}".format(ex))
        return EXPORT_VIEW_NAME
    except Exception as ex:
        warnings.append("Export view creation failed: {}".format(ex))
        return "failed"


# ------------------------------------------------------------
# Layout helpers
# ------------------------------------------------------------

def layer_stack(rated):
    if rated:
        return [(DRYWALL_THICKNESS_RATED_FT, True)] * DRYWALL_LAYERS_RATED
    return [(DRYWALL_THICKNESS_STD_FT, False)] * DRYWALL_LAYERS_STD


def furring_profile():
    """Hat/furring channel: closed face at q=0 (drywall side), legs rising to FURRING_HEIGHT."""
    D = FURRING_FACE_FT
    H = FURRING_HEIGHT_FT
    t = MAT_T_FT
    return [(0, 0), (0, H), (t, H), (t, t), (D - t, t), (D - t, H), (D, H), (D, 0)]


def channel_profile(depth, face):
    """Generic open channel (used for the carrying/main channel): back at q=0, legs up to 'depth',
    width 'face'. p across the run, q up."""
    D = face
    H = depth
    t = MAT_T_FT
    return [(0, 0), (0, H), (t, H), (t, t), (D - t, t), (D - t, H), (D, H), (D, 0)]


def splice_segments(lo, hi, stock, lap, stagger):
    """Break a channel run [lo, hi] into stock-length pieces that overlap (nest) by 'lap' at each
    splice - real channels ship in stock lengths and are lapped end-to-end, not one long piece.
    'stagger' shifts the first splice so joints don't line up across adjacent channels. Returns
    overlapping [(a, b), ...] left-to-right (each piece <= stock; interior pieces overlap by lap)."""
    total = hi - lo
    if not SPLICE_CHANNELS or total <= stock + 1e-6:
        return [(lo, hi)]
    step = max(stock - lap, MIN_SEG_FT)
    first = stock - (stagger % step)          # shorten the first piece by the stagger phase
    if first < lap + MIN_SEG_FT:
        first = stock
    segs = []
    a = lo
    b = min(lo + first, hi)
    segs.append((a, b))
    while b < hi - 1e-6:
        a = b - lap                            # next piece laps back over the previous by 'lap'
        b = min(a + stock, hi)
        if b - a < MIN_SEG_FT:
            break
        segs.append((a, b))
    return segs


def normalize_shift(shift, period):
    s = float(shift)
    while s < 0.0:
        s += period
    while s >= period:
        s -= period
    return s


def build_boundary_solid(outer, holes, fixtures, z_lo, tall):
    """Extrude the ceiling outline (outer minus holes minus fixture cutters) into a tall clip mask
    spanning z_lo .. z_lo+tall, used to boolean-clip boards and furring to the room shape."""
    origin = XYZ(0.0, 0.0, z_lo)
    u = XYZ.BasisX
    v = XYZ.BasisY
    up = XYZ.BasisZ
    solid = make_planar_poly_solid(origin, u, v, up, outer, tall)
    if solid is None:
        return None
    for h in holes:
        hs = make_planar_poly_solid(XYZ(0.0, 0.0, z_lo - HOLE_MARGIN_FT), u, v, up, h, tall + 2 * HOLE_MARGIN_FT)
        solid = boolean_op(solid, hs, BooleanOperationsType.Difference)
    for fx in fixtures:
        fs = make_rect_solid(XYZ(0.0, 0.0, z_lo - HOLE_MARGIN_FT), u, v, up, fx, tall + 2 * HOLE_MARGIN_FT)
        solid = boolean_op(solid, fs, BooleanOperationsType.Difference)
    return solid


def collect_room_regions(warnings):
    """Every placed, bounded Room in the model as an independent ceiling region:
    (room_id, number, level_eid, outer_poly, inner_polys, bbox). Boundaries come from
    Room.GetBoundarySegments at FINISH faces, so a room polygon stops at the wall surface and is
    continuous across doorways (segments follow the room-bounding walls / room separation lines).
    Unenclosed or degenerate rooms are skipped with a warning instead of corrupting the run."""
    regions = []
    try:
        col = list(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms)
                   .WhereElementIsNotElementType())
    except Exception as ex:
        warnings.append("Room collection failed: {}".format(ex))
        return regions
    opts = SpatialElementBoundaryOptions()
    try:
        opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish
    except Exception:
        pass
    for r in col:
        rid = "R" + str(eid_value(r.Id))
        try:
            area = r.Area
        except Exception:
            area = 0.0
        if not area or area < MIN_ROOM_AREA_SF:
            warnings.append("Room {} skipped: not enclosed / zero area".format(rid))
            continue
        try:
            loops = r.GetBoundarySegments(opts)
        except Exception as ex:
            warnings.append("Room {}: GetBoundarySegments failed ({})".format(rid, ex))
            continue
        polys = []
        for loop in (loops or []):
            pts = []
            for seg in loop:
                try:
                    for p in seg.GetCurve().Tessellate():
                        if not pts or abs(pts[-1][0] - p.X) > 1e-6 or abs(pts[-1][1] - p.Y) > 1e-6:
                            pts.append((p.X, p.Y))
                except Exception:
                    continue
            if len(pts) >= 3 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
                pts = pts[:-1]
            if len(pts) >= 3:
                polys.append(pts)
        if not polys:
            warnings.append("Room {} skipped: no usable boundary polygon".format(rid))
            continue
        polys.sort(key=poly_area, reverse=True)     # largest loop = the room outline, rest = holes
        num = ""
        try:
            num = r.Number
        except Exception:
            pass
        lev = -1
        try:
            lev = eid_value(r.LevelId)
        except Exception:
            pass
        regions.append((rid, num, lev, polys[0], polys[1:], poly_bbox(polys[0])))
    return regions


def collect_wall_plans(warnings):
    """Plan footprint of every straight wall in the model, for clipping the ceiling drywall at
    walls: returns a list of (poly4, bbox, axis, f_lo, f_hi) where axis is 'x' when the wall runs
    along Y (its two faces are the X lines f_lo/f_hi), 'y' when it runs along X, or None for an
    oblique wall (clip-only - no forced board joints)."""
    plans = []
    try:
        wcol = FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType()
    except Exception as ex:
        warnings.append("Wall collection for ceiling clipping failed: {}".format(ex))
        return plans
    for w in wcol:
        try:
            loc = w.Location
            crv = loc.Curve if isinstance(loc, LocationCurve) else None
            if not isinstance(crv, Line):
                continue
            p0 = crv.GetEndPoint(0)
            p1 = crv.GetEndPoint(1)
            dx = p1.X - p0.X
            dy = p1.Y - p0.Y
            ln = math.sqrt(dx * dx + dy * dy)
            if ln < 1e-6:
                continue
            ux = dx / ln
            uy = dy / ln
            hw = w.Width / 2.0
            nx = -uy
            ny = ux
            # A footprint from the LOCATION LINE assumes the line is the wall CENTERLINE - false
            # when the wall's Location Line is set to a face (the subtraction then misses half
            # the wall and ceiling boards penetrate it). For axis-aligned walls use the element's
            # model bbox instead: exact faces regardless of location-line setting or joins.
            poly = None
            axis, f_lo, f_hi = None, 0.0, 0.0
            if abs(ux) < 0.02 or abs(uy) < 0.02:
                try:
                    bb = w.get_BoundingBox(None)
                except Exception:
                    bb = None
                if bb is not None:
                    x0, y0, x1, y1 = bb.Min.X, bb.Min.Y, bb.Max.X, bb.Max.Y
                    poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    if abs(ux) < 0.02:          # wall runs along Y -> faces are X lines
                        axis, f_lo, f_hi = "x", x0, x1
                    else:                       # wall runs along X -> faces are Y lines
                        axis, f_lo, f_hi = "y", y0, y1
            if poly is None:                    # oblique wall, or bbox unavailable
                poly = [(p0.X + nx * hw, p0.Y + ny * hw), (p1.X + nx * hw, p1.Y + ny * hw),
                        (p1.X - nx * hw, p1.Y - ny * hw), (p0.X - nx * hw, p0.Y - ny * hw)]
                if abs(ux) < 0.02:
                    axis, f_lo, f_hi = "x", p0.X - hw, p0.X + hw
                elif abs(uy) < 0.02:
                    axis, f_lo, f_hi = "y", p0.Y - hw, p0.Y + hw
            plans.append((poly, poly_bbox(poly), axis, f_lo, f_hi))
        except Exception:
            continue
    return plans


def board_fully_inside(rect, outer, holes, fixtures):
    """True if the board rect is safely inside the outer polygon and clear of every hole/fixture,
    so it can be emitted whole (and tapered) with no boolean clip. Corner test + overlap test;
    a concave outer edge cutting through an all-corners-inside rect is a rare unhandled case."""
    x0, y0, x1, y1 = rect
    for (cx, cy) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
        if not point_in_polygon(cx, cy, outer):
            return False
    for h in holes:
        if rects_overlap(rect, poly_bbox(h)):
            return False
    for fx in fixtures:
        if rects_overlap(rect, fx):
            return False
    return True


# ------------------------------------------------------------
# Emit
# ------------------------------------------------------------

def ds_comment(ceiling_id, kind, eid):
    return "{} | CEILING={} | {} | {}".format(APP_ID, ceiling_id, kind, eid)


def emit_furring(ceiling_id, host_tag, st_counter, z_top, boundary_solid, xlo, xhi, ylo, yhi,
                 warnings, frecords, room_id=None):
    """Furring hat-channels @16" OC running along X, just above the drywall (bottom face at z_top).
    Long lines are spliced into stock-length pieces that lap at each joint (splice_segments), with
    the splices staggered row-to-row. Each piece is clipped to the ceiling outline and named
    ST-<host>-<n> (flat per-ceiling framing sequence). Returns (pieces_made, splice_joints)."""
    if not GENERATE_FURRING:
        return 0, 0
    mat, gs = styles.get("FURRING", (None, None))
    prof = furring_profile()
    made = 0
    splices = 0
    fi = 0
    y = ylo
    while y <= yhi + 1e-6:
        if (xhi - xlo) >= MIN_SEG_FT:
            # A long furring line ships as stock-length pieces lapped at each splice; stagger the
            # splices row-to-row so joints don't line up. cross-section (p across Y, q up Z),
            # centered on the furring line y; extrude along X.
            segs = splice_segments(xlo, xhi, FURRING_STOCK_LENGTH_FT, FURRING_SPLICE_LAP_FT,
                                   fi * SPLICE_STAGGER_FT)
            if len(segs) > 1:
                splices += len(segs) - 1
            for si, (ax, bx) in enumerate(segs):
                seg_len = bx - ax
                if seg_len < MIN_SEG_FT:
                    continue
                dz = MAT_T_FT if (SPLICE_NEST_OFFSET and si % 2 == 1) else 0.0   # nested-lap look
                origin = XYZ(ax, y - FURRING_FACE_FT / 2.0, z_top + dz)
                raw = make_profile_solid(origin, XYZ.BasisY, XYZ.BasisZ, prof, XYZ.BasisX, seg_len, mat, gs)
                clipped = boolean_op(raw, boundary_solid, BooleanOperationsType.Intersect)
                if not solid_ok(clipped):
                    continue
                name = "ST-{}-{:03d}".format(host_tag, st_counter[0] + 1)
                ds = create_directshape(clipped, name, name,
                                        ds_comment(ceiling_id, "FURRING", name), warnings)
                if ds:
                    st_counter[0] += 1
                    made += 1
                    try:
                        fbb = clipped.GetBoundingBox()
                        fmn = fbb.Transform.OfPoint(fbb.Min)
                        fmx = fbb.Transform.OfPoint(fbb.Max)
                        fbox = [round(fmn.X, 3), round(fmn.Y, 3), round(fmx.X, 3), round(fmx.Y, 3)]
                    except Exception:
                        fbox = None
                    frecords.append({
                        "id": name, "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                        "member_type": "FURRING",
                        "profile": "HAT", "depth_in": round(FURRING_HEIGHT_FT * 12.0, 3),
                        "face_in": round(FURRING_FACE_FT * 12.0, 3),
                        "length_in": round(seg_len * 12.0, 3), "line_y_in": round(y * 12.0, 2),
                        "piece": si + 1, "pieces": len(segs),
                        "bbox_ft": fbox, "room_id": room_id,
                        "install_order": len(frecords) + 1,
                    })
        fi += 1
        y += FURRING_SPACING_FT
    return made, splices


def furring_lines(ylo, yhi):
    ys = []
    y = ylo
    while y <= yhi + 1e-6:
        ys.append(y)
        y += FURRING_SPACING_FT
    return ys


def point_inside_room(px, py, outer, holes, fixtures):
    """True if (px, py) is inside the ceiling outline and clear of holes/fixtures."""
    if not point_in_polygon(px, py, outer):
        return False
    for h in holes:
        if point_in_polygon(px, py, h):
            return False
    for fx in fixtures:
        if fx[0] < px < fx[2] and fx[1] < py < fx[3]:
            return False
    return True


def emit_mains(ceiling_id, host_tag, st_counter, z_top, boundary_solid, outer, holes, fixtures,
               xlo, xhi, ylo, yhi, warnings, frecords, room_id=None):
    """Reinforcement for long spans: when the furring run (xhi-xlo) exceeds MAX_FURRING_SPAN_FT, the
    furring can't carry the gypsum without sagging, so add MAIN carrying channels perpendicular to
    the furring at MAIN_SPACING_FT (sitting just above the furring), each hung from the structure by
    HANGER wires at HANGER_SPACING_FT. Furring then spans <= MAX_FURRING_SPAN_FT between mains. Mains
    are clipped to the ceiling outline; hangers are placed only where they land inside the room.
    Mains ship in stock lengths too, so long ones are spliced (lapped) and staggered between mains.
    Named ST-<host>-<n> (shared framing sequence). Returns (mains_made, hangers_made, splice_joints)."""
    if not GENERATE_MAINS or (xhi - xlo) <= MAX_FURRING_SPAN_FT + 1e-6:
        return 0, 0, 0
    mat, gs = styles.get("MAIN", (None, None))
    hmat, hgs = styles.get("HANGER", (None, None))
    prof = channel_profile(MAIN_DEPTH_FT, MAIN_FACE_FT)
    z_main = z_top + FURRING_HEIGHT_FT          # mains sit on top of the furring
    z_hang = z_main + MAIN_DEPTH_FT             # hanger wires rise from the top of the main
    mains = 0
    hangers = 0
    splices = 0

    # Interior main x-positions every MAIN_SPACING; the furring is also supported at the two ends
    # (perimeter), so only interior supports are needed.
    mx = xlo + MAIN_SPACING_FT
    mi = 0
    while mx < xhi - 1e-6:
        if (yhi - ylo) >= MIN_SEG_FT:
            # A long carrying channel also ships in stock lengths, lapped at each splice; stagger
            # the splices between adjacent mains.
            segs = splice_segments(ylo, yhi, MAIN_STOCK_LENGTH_FT, MAIN_SPLICE_LAP_FT,
                                   mi * SPLICE_STAGGER_FT)
            if len(segs) > 1:
                splices += len(segs) - 1
            made_here = False
            for si, (ay, by) in enumerate(segs):
                seg_len = by - ay
                if seg_len < MIN_SEG_FT:
                    continue
                dz = MAT_T_FT if (SPLICE_NEST_OFFSET and si % 2 == 1) else 0.0
                origin = XYZ(mx - MAIN_FACE_FT / 2.0, ay, z_main + dz)
                raw = make_profile_solid(origin, XYZ.BasisX, XYZ.BasisZ, prof, XYZ.BasisY, seg_len, mat, gs)
                clipped = boolean_op(raw, boundary_solid, BooleanOperationsType.Intersect)
                if not solid_ok(clipped):
                    continue
                name = "ST-{}-{:03d}".format(host_tag, st_counter[0] + 1)
                ds = create_directshape(clipped, name, name,
                                        ds_comment(ceiling_id, "MAIN", name), warnings)
                if ds:
                    st_counter[0] += 1
                    mains += 1
                    made_here = True
                    try:
                        mbb = clipped.GetBoundingBox()
                        mmn = mbb.Transform.OfPoint(mbb.Min)
                        mmx = mbb.Transform.OfPoint(mbb.Max)
                        mbox = [round(mmn.X, 3), round(mmn.Y, 3), round(mmx.X, 3), round(mmx.Y, 3)]
                    except Exception:
                        mbox = None
                    frecords.append({
                        "id": name, "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                        "member_type": "MAIN", "profile": "CRC",
                        "depth_in": round(MAIN_DEPTH_FT * 12.0, 3),
                        "face_in": round(MAIN_FACE_FT * 12.0, 3),
                        "length_in": round(seg_len * 12.0, 3), "line_x_in": round(mx * 12.0, 2),
                        "piece": si + 1, "pieces": len(segs),
                        "bbox_ft": mbox, "room_id": room_id,
                        "install_order": len(frecords) + 1,
                    })
            # Hanger wires along this main line - only when there is a deck above to anchor into
            # (GENERATE_HANGERS). Within 6" of ends, then every HANGER_SPACING.
            if made_here and GENERATE_HANGERS:
                hpos = [ylo + END_SUPPORT_SETBACK_FT]
                yy = ylo + END_SUPPORT_SETBACK_FT + HANGER_SPACING_FT
                while yy < yhi - END_SUPPORT_SETBACK_FT + 1e-6:
                    hpos.append(yy)
                    yy += HANGER_SPACING_FT
                hpos.append(yhi - END_SUPPORT_SETBACK_FT)
                half = HANGER_DIA_FT / 2.0
                for hy in unique_sorted(hpos):
                    if not point_inside_room(mx, hy, outer, holes, fixtures):
                        continue
                    hrect = (mx - half, hy - half, mx + half, hy + half)
                    hs = make_rect_solid(XYZ(0.0, 0.0, z_hang), XYZ.BasisX, XYZ.BasisY,
                                         XYZ.BasisZ, hrect, HANGER_DROP_FT, hmat, hgs)
                    if not solid_ok(hs):
                        continue
                    hname = "ST-{}-{:03d}".format(host_tag, st_counter[0] + 1)
                    hds = create_directshape(hs, hname, hname,
                                             ds_comment(ceiling_id, "HANGER", hname), warnings)
                    if hds:
                        st_counter[0] += 1
                        hangers += 1
                        frecords.append({
                            "id": hname, "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                            "member_type": "HANGER", "gauge": "#12", "room_id": room_id,
                            "x_in": round(mx * 12.0, 2), "y_in": round(hy * 12.0, 2),
                            "drop_in": round(HANGER_DROP_FT * 12.0, 2),
                            "install_order": len(frecords) + 1,
                        })
        mx += MAIN_SPACING_FT
        mi += 1
    return mains, hangers, splices


def emit_drywall(ceiling_id, host_tag, z_bottom, outer, holes, fixtures, boundary_solid, rated,
                 records, screw_records, do_screws, warnings,
                 wall_x_cuts=(), wall_y_cuts=(), wall_bboxes=(),
                 room_id=None, board_seq=None, screw_seq=None, force_clip=False):
    """Single-face gypsum on the underside: staggered board grid in world X-Y, clipped to the
    ceiling outline. Boards are hung with their bottom face flush at z_bottom, thickness upward.
    Layer 0 is the room-facing layer. Boards are named DP-<host>-<n> (single face -> no letter);
    screws SC-<host>-<n> (flat per-ceiling). Returns a counts dict."""
    counts = {"boards": 0, "cut_boards": 0, "layers": 0, "screws": 0}
    if board_seq is None:
        board_seq = [0]    # per-ceiling board counter -> DP-<host>-<n>
    if screw_seq is None:
        screw_seq = [0]    # flat per-ceiling screw counter -> SC-<host>-<n>
    bx0, by0, bx1, by1 = poly_bbox(outer)
    layers = layer_stack(rated)
    u = XYZ.BasisX
    v = XYZ.BasisY
    up = XYZ.BasisZ
    down = XYZ(0, 0, -1)
    fur_ys = furring_lines(by0, by1)

    cum_below = 0.0     # thickness already placed BELOW (closer to room) - layer 0 is room-facing
    for li, (t, type_x) in enumerate(layers):
        counts["layers"] += 1
        # Layer 0 bottom flush at z_bottom; each further layer sits above the previous.
        z0 = z_bottom + cum_below
        origin_z = XYZ(0.0, 0.0, z0)
        kind = "GWB" if li == 0 else "GWB2"
        base_shift = li * LAYER_H_STAGGER_FT
        v_off = li * LAYER_V_STAGGER_FT

        # courses step in Y by PANEL_WIDTH, offset by v_off for layer staggering
        ystart = by0 + v_off
        while ystart > by0:
            ystart -= PANEL_WIDTH_FT
        row = 0
        cy = ystart
        while cy < by1 - 1e-4:
            cy0 = max(by0, cy)
            cy1 = min(by1, cy + PANEL_WIDTH_FT)
            cy += PANEL_WIDTH_FT
            row += 1
            if (cy1 - cy0) < MIN_PIECE_HEIGHT_FT:
                continue
            full_course = abs((cy1 - cy0) - PANEL_WIDTH_FT) < 0.02
            if MAXIMIZE_WHOLE_PANELS:
                row_shift = 0.0
            else:
                row_shift = normalize_shift(base_shift + (ODD_ROW_SHIFT_FT if row % 2 == 1 else 0.0),
                                            PANEL_LENGTH_FT)
            x = bx0 - row_shift
            col = 0
            while x < bx1 - 1e-4:
                rx0 = max(bx0, x)
                rx1 = min(bx1, x + PANEL_LENGTH_FT)
                x += PANEL_LENGTH_FT
                col += 1
                # Split this cell ONLY where a wall truly severs it: a face line splits a piece
                # just when that wall's run fully covers the piece on the other axis; where a
                # wall ENDS inside a piece, the piece first splits at the wall's END line so the
                # part beyond the stub stays whole. This keeps exactly ONE pair of face lines
                # (the track-width gap) along real wall runs - no doubled joints elsewhere.
                pieces = []
                stack = [(rx0, cy0, rx1, cy1)]
                guard = 0
                while stack and guard < 256:
                    guard += 1
                    (px0, py0, px1, py1) = stack.pop()
                    did = False
                    for (c, w0, w1) in wall_x_cuts:
                        if not (px0 + 1e-6 < c < px1 - 1e-6):
                            continue
                        if w0 > py1 - 1e-6 or w1 < py0 + 1e-6:
                            continue                        # wall nowhere in this piece's y-range
                        if w0 > py0 + 1e-6:                 # wall STARTS inside: split at its end line
                            stack.append((px0, py0, px1, w0))
                            stack.append((px0, w0, px1, py1))
                        elif w1 < py1 - 1e-6:               # wall ENDS inside: split at its end line
                            stack.append((px0, py0, px1, w1))
                            stack.append((px0, w1, px1, py1))
                        else:                               # wall severs the piece: split at the face
                            stack.append((px0, py0, c, py1))
                            stack.append((c, py0, px1, py1))
                        did = True
                        break
                    if did:
                        continue
                    for (c, w0, w1) in wall_y_cuts:
                        if not (py0 + 1e-6 < c < py1 - 1e-6):
                            continue
                        if w0 > px1 - 1e-6 or w1 < px0 + 1e-6:
                            continue
                        if w0 > px0 + 1e-6:
                            stack.append((px0, py0, w0, py1))
                            stack.append((w0, py0, px1, py1))
                        elif w1 < px1 - 1e-6:
                            stack.append((px0, py0, w1, py1))
                            stack.append((w1, py0, px1, py1))
                        else:
                            stack.append((px0, py0, px1, c))
                            stack.append((px0, c, px1, py1))
                        did = True
                        break
                    if not did:
                        pieces.append((px0, py0, px1, py1))
                for (px0, py0, px1, py1) in pieces:
                    g = CODE_GAP_FT / 2.0
                    sx0 = px0 + g
                    sx1 = px1 - g
                    sy0 = py0 + g
                    sy1 = py1 - g
                    if (sx1 - sx0) < MIN_PIECE_WIDTH_FT or (sy1 - sy0) < MIN_PIECE_HEIGHT_FT:
                        continue
                    rect = (sx0, sy0, sx1, sy1)
                    if not rects_overlap(rect, (bx0, by0, bx1, by1)):
                        continue

                    mat, gs = styles.get(kind, (None, None))
                    # force_clip: the caller's outer is only a bbox approximation of the region
                    # (fallback zones), so every board must take the boolean path against the mask
                    whole = (not force_clip) and board_fully_inside(rect, outer, holes, fixtures)
                    if whole:
                        for wb in wall_bboxes:          # near/over a wall -> take the boolean path so
                            if rects_overlap(rect, wb):  # the wall subtraction in the mask trims it
                                whole = False
                                break
                    is_full_size = (abs((sx1 - sx0) - (PANEL_LENGTH_FT - CODE_GAP_FT)) < 0.02 and
                                    abs((sy1 - sy0) - (PANEL_WIDTH_FT - CODE_GAP_FT)) < 0.02)
                    # Taper is WIDTH-gated (the rule: "if any part of the board is in a full 4-ft course,
                    # its top/bottom horizontal edges are factory-tapered"). ANY board in a full 4-ft
                    # course tapers - including a boundary-clipped one (the tapered rect is clipped to the
                    # outline, so the surviving factory edges keep the taper). Only ripped (<4 ft width)
                    # courses are square.
                    board_tapered = TAPERED_LONG_EDGES and full_course

                    if whole:
                        if board_tapered:
                            solid = make_tapered_board_solid(origin_z, u, v, up, rect, t, mat, gs)
                        else:
                            solid = make_rect_solid(origin_z, u, v, up, rect, t, mat, gs)
                        is_cut = not is_full_size
                    else:
                        if board_tapered:
                            raw = make_tapered_board_solid(origin_z, u, v, up, rect, t, mat, gs)
                        else:
                            raw = make_rect_solid(origin_z, u, v, up, rect, t, mat, gs)
                        solid = boolean_op(raw, boundary_solid, BooleanOperationsType.Intersect)
                        is_cut = True

                    if not solid_ok(solid):        # None, or clipped away to nothing (board outside)
                        continue
                    board_id = "DP-{}-{:03d}".format(host_tag, board_seq[0] + 1)
                    comment = "{} | CEILING={} | {} | DRYWALL | {} | L{} | t={}in | typeX={} | cut={} | taper={}".format(
                        APP_ID, ceiling_id, "-", board_id, li, round(t * 12.0, 3),
                        int(bool(type_x)), int(bool(is_cut)), int(bool(board_tapered)))
                    ds = create_directshape(solid, board_id, board_id, comment, warnings)
                    if not ds:
                        continue
                    board_seq[0] += 1
                    counts["boards"] += 1
                    if is_cut:
                        counts["cut_boards"] += 1
                    try:
                        sbb = solid.GetBoundingBox()
                        smn = sbb.Transform.OfPoint(sbb.Min)
                        smx = sbb.Transform.OfPoint(sbb.Max)
                        sbox = [round(smn.X, 3), round(smn.Y, 3), round(smx.X, 3), round(smx.Y, 3)]
                    except Exception:
                        sbox = None
                    records.append({
                        "board_id": board_id, "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                        "layer": li, "type_x": bool(type_x), "thickness_in": round(t * 12.0, 3),
                        "is_cut": bool(is_cut), "tapered": bool(board_tapered),
                        "bbox_ft": sbox, "room_id": room_id,
                        "install_order": len(records) + 1,
                    })

                    # Screws: on the room-facing (bottom) surface of layer 0, along furring lines. Per
                    # USG/GA, set back >= 3/8" from board edges/ends. A furring line on the board's
                    # Y-edge carries the tapered long-edge joint: offset the screw INTO the board
                    # (staying within the ~2.5" furring face so it still bites steel), so it sits beside
                    # the joint - never on it - and the neighbor board straddles from its side.
                    if do_screws and (li == 0 or not SCREWS_OUTER_LAYER_ONLY):
                        smat, sgs = styles.get("SCREW", (None, None))
                        half = SCREW_MARKER_SIZE_FT / 2.0
                        sb = SCREW_EDGE_SETBACK_FT
                        tol = SCREW_EDGE_TOL_FT
                        for fy in fur_ys:
                            if fy < sy0 - tol or fy > sy1 + tol:
                                continue
                            if abs(fy - sy0) <= tol:
                                coly = sy0 + sb
                            elif abs(fy - sy1) <= tol:
                                coly = sy1 - sb
                            else:
                                coly = fy
                            if coly <= sy0 + 1e-3 or coly >= sy1 - 1e-3:
                                continue
                            sxp = sx0 + sb
                            xend = sx1 - sb
                            cand = []
                            if xend < sxp:
                                cand.append((sx0 + sx1) / 2.0)
                            else:
                                vx = sxp
                                while vx <= xend + 1e-6:
                                    cand.append(vx)
                                    vx += SCREW_SPACING_FT
                                if not cand or abs(cand[-1] - xend) > 1e-3:
                                    cand.append(xend)
                            for sxx in cand:
                                if counts["screws"] >= MAX_SCREWS_PER_CEILING:
                                    break
                                inside_fx = False
                                for fx in fixtures:
                                    if fx[0] - 0.01 < sxx < fx[2] + 0.01 and fx[1] - 0.01 < coly < fx[3] + 0.01:
                                        inside_fx = True
                                        break
                                if inside_fx:
                                    continue
                                # marker sits at the bottom face (z0), protruding down by proud, most
                                # of its depth embedded upward into the board.
                                sz = z0 - SCREW_HEAD_PROUD_FT
                                sorigin = XYZ(0.0, 0.0, sz)
                                srect = (sxx - half, coly - half, sxx + half, coly + half)
                                ssolid = make_rect_solid(sorigin, u, v, up, srect, SCREW_MARKER_DEPTH_FT, smat, sgs)
                                if ssolid is None:
                                    continue
                                sid = "SC-{}-{:03d}".format(host_tag, screw_seq[0] + 1)
                                sds = create_directshape(ssolid, sid, sid,
                                                         ds_comment(ceiling_id, "SCREW", sid), warnings)
                                if sds:
                                    screw_seq[0] += 1
                                    counts["screws"] += 1
                                    screw_records.append({
                                        "screw_id": sid, "board_id": board_id, "room_id": room_id,
                                        "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                                        "x_in": round(sxx * 12.0, 2), "y_in": round(coly * 12.0, 2),
                                        "world_x": round(sxx, 4), "world_y": round(coly, 4),
                                        "world_z": round(z0, 4),
                                        "spacing_in": round(SCREW_SPACING_FT * 12.0, 2),
                                        "length_in": round(t * 12.0 + 0.625, 3),
                                    })
        cum_below += t
    return counts


def simplify_rectilinear(poly, tol=0.02):
    """Drop collinear/duplicate vertices from a tessellated rectilinear outline."""
    pts = []
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i - 1]
        bx, by = poly[i]
        cx, cy = poly[(i + 1) % n]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) > tol:
            pts.append((bx, by))
    return pts


def soffit_board_rects(outer, warnings, tag):
    """Exactly TWO board rectangles covering a soffit run: an L-shaped outline (6 rectilinear
    corners) splits at its inner corner - one board per leg, butt joint between them; a straight
    rectangle splits at mid-run. Anything else falls back to bbox halves with a warning (the
    mask still clips the boards to the true shape)."""
    bx0, by0, bx1, by1 = poly_bbox(outer)
    pts = simplify_rectilinear(outer)
    if len(pts) == 6:
        reflex = None
        for (px, py) in pts:
            if bx0 + 0.05 < px < bx1 - 0.05 and by0 + 0.05 < py < by1 - 0.05:
                reflex = (px, py)
                break
        missing = None
        eps = 0.05
        for (qx, qy) in [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]:
            tx = qx + (eps if qx == bx0 else -eps)
            ty = qy + (eps if qy == by0 else -eps)
            if not point_in_polygon(tx, ty, outer):
                missing = (qx, qy)
                break
        if reflex is not None and missing is not None:
            cx, cy = reflex
            mx, my = missing
            if mx == bx1 and my == by1:        # notch top-right
                return [(bx0, by0, cx, by1), (cx, by0, bx1, cy)]
            if mx == bx1 and my == by0:        # notch bottom-right
                return [(bx0, by0, cx, by1), (cx, cy, bx1, by1)]
            if mx == bx0 and my == by1:        # notch top-left
                return [(cx, by0, bx1, by1), (bx0, by0, cx, cy)]
            if mx == bx0 and my == by0:        # notch bottom-left
                return [(cx, by0, bx1, by1), (bx0, cy, cx, by1)]
        warnings.append("Soffit {}: could not resolve the L corner; using bbox halves".format(tag))
    elif len(pts) != 4:
        warnings.append("Soffit {}: outline has {} corners (expected 4 or 6); using bbox halves".format(tag, len(pts)))
    if (bx1 - bx0) >= (by1 - by0):
        xm = (bx0 + bx1) / 2.0
        return [(bx0, by0, xm, by1), (xm, by0, bx1, by1)]
    ym = (by0 + by1) / 2.0
    return [(bx0, by0, bx1, ym), (bx0, ym, bx1, by1)]


def emit_soffit_boards(ceiling_id, host_tag, z_bottom, rects, boundary_solid, rated,
                       records, board_seq, warnings):
    """Emit the soffit's TWO custom-cut boards per layer, boolean-clipped to the wall-subtracted
    mask (a board ends at the wall it spans to - it can never penetrate it). Warns when a board
    leg is longer than SOFFIT_MAX_BOARD_FT, shorter than SOFFIT_MIN_BOARD_FT, or when a layer
    does not come out at exactly two boards."""
    made = 0
    layers = layer_stack(rated)
    u = XYZ.BasisX
    v = XYZ.BasisY
    up = XYZ.BasisZ
    cum_below = 0.0
    for li, (t, type_x) in enumerate(layers):
        z0 = z_bottom + cum_below
        origin_z = XYZ(0.0, 0.0, z0)
        kind = "GWB" if li == 0 else "GWB2"
        mat, gs = styles.get(kind, (None, None))
        made_layer = 0
        for (px0, py0, px1, py1) in rects:
            long_ft = max(px1 - px0, py1 - py0)
            if long_ft > SOFFIT_MAX_BOARD_FT + 1e-6:
                warnings.append("Soffit {}: board leg {:.1f} ft exceeds the {} ft max".format(
                    ceiling_id, long_ft, SOFFIT_MAX_BOARD_FT))
            if long_ft < SOFFIT_MIN_BOARD_FT - 1e-6:
                warnings.append("Soffit {}: board leg {:.1f} ft is under the {} ft min".format(
                    ceiling_id, long_ft, SOFFIT_MIN_BOARD_FT))
            raw = make_rect_solid(origin_z, u, v, up, (px0, py0, px1, py1), t, mat, gs)
            solid = boolean_op(raw, boundary_solid, BooleanOperationsType.Intersect)
            if not solid_ok(solid):
                continue
            board_id = "DP-{}-{:03d}".format(host_tag, board_seq[0] + 1)
            comment = "{} | CEILING={} | {} | DRYWALL | {} | L{} | t={}in | typeX={} | cut=1 | taper=0".format(
                APP_ID, ceiling_id, "-", board_id, li, round(t * 12.0, 3), int(bool(type_x)))
            ds = create_directshape(solid, board_id, board_id, comment, warnings)
            if not ds:
                continue
            board_seq[0] += 1
            made += 1
            made_layer += 1
            try:
                sbb = solid.GetBoundingBox()
                smn = sbb.Transform.OfPoint(sbb.Min)
                smx = sbb.Transform.OfPoint(sbb.Max)
                sbox = [round(smn.X, 3), round(smn.Y, 3), round(smx.X, 3), round(smx.Y, 3)]
            except Exception:
                sbox = None
            records.append({
                "board_id": board_id, "ceiling_number": host_tag, "host_ceiling": ceiling_id,
                "layer": li, "type_x": bool(type_x), "thickness_in": round(t * 12.0, 3),
                "is_cut": True, "tapered": False,
                "bbox_ft": sbox, "room_id": "SOFFIT",
                "install_order": len(records) + 1,
            })
        if made_layer != 2:
            warnings.append("Soffit {}: layer {} produced {} boards (expected exactly 2)".format(
                ceiling_id, li, made_layer))
        cum_below += t
    return made


# ============================================================
# MAIN
# ============================================================

result = {
    "app_id": APP_ID,
    "output_mode": "directshape",
    "phase": "ceiling_v1_furred",
    "deleted_previous": 0,
    "ceilings_requested": 0,
    "ceilings_processed": 0,
    "ceilings_skipped": [],
    "ceiling_numbers": {},             # {C<eid>: "C001"/"S001"} nomenclature host tag per ceiling
    "rated_ceilings": 0,
    "furring_created": 0,
    "mains_created": 0,                 # carrying channels added where the furring span needs support
    "hangers_created": 0,              # hanger wires holding the mains up
    "reinforced_ceilings": 0,          # ceilings whose span required mains
    "splice_joints": 0,                # lap splices where channels join end-to-end (stock lengths)
    "boards_created": 0,
    "cut_boards": 0,
    "screws_created": 0,
    "drywall_layers": 0,
    "fixtures_cut": 0,
    "rooms_found": 0,                  # bounded Rooms collected for per-room generation
    "rooms_used": 0,                   # room regions that actually met a processed ceiling
    "soffits_processed": 0,            # ceilings routed through the separate soffit flow
    "board_records": 0,
    "framing_records": 0,
    "screw_records": 0,
    "manifest_path": "",
    "export_view": "",
    "warnings": [],
    "notes": []
}
warnings = result["warnings"]

do_delete = as_bool(get_in(5), DELETE_PREVIOUS)
do_drywall = as_bool(get_in(6), GENERATE_DRYWALL)
do_screws = as_bool(get_in(8), GENERATE_SCREWS)

ceilings = get_input_ceilings(warnings)
result["ceilings_requested"] = len(ceilings)

board_records = []
framing_records = []
screw_records = []
room_records = []

if len(ceilings) == 0:
    OUT = "No ceilings found. Select one or more Revit Ceiling elements, then run Dynamo again."
else:
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        processed_ids = set("C" + str(eid_value(c.Id)) for c in ceilings)
        if do_delete:
            result["deleted_previous"] = delete_previous(processed_ids, warnings)
        if COLOR_BY_TYPE:
            styles = setup_styles(warnings)

        # Assign each ceiling its stable nomenclature host tag (C###/S###), persisted to the Mark.
        ceiling_numbers = assign_ceiling_numbers(ceilings, warnings)

        # Wall plan footprints for clipping the ceiling drywall at walls (collected once per run).
        wall_plans = collect_wall_plans(warnings) if CLIP_CEILING_AT_WALLS else []

        # Room boundary polygons for per-room generation (collected once per run).
        room_regions = collect_room_regions(warnings) if CEILING_PER_ROOM else []
        result["rooms_found"] = len(room_regions)

        for ceiling in ceilings:
            cid = "C" + str(eid_value(ceiling.Id))
            host_tag = ceiling_numbers.get(eid_value(ceiling.Id), "C000")
            result["ceiling_numbers"][cid] = host_tag
            is_soffit = SOFFIT_SEPARATE_FLOW and host_tag.startswith("S")
            try:
                loops, z_bottom = get_ceiling_loops(ceiling, warnings)
                if not loops or z_bottom is None:
                    result["ceilings_skipped"].append(cid + ": could not read boundary")
                    continue
                outer = loops[0]
                holes = loops[1:]

                rated = ceiling_is_fire_rated(ceiling, warnings)
                if rated:
                    result["rated_ceilings"] += 1
                fixtures = get_fixture_rects(ceiling, warnings)
                result["fixtures_cut"] += len(fixtures)

                layers = layer_stack(rated)
                dw_total = sum(t for (t, _tx) in layers)
                # Clip mask spans from just below the drywall bottom up past the furring AND the main
                # carrying channels (which sit on top of the furring) so the mains aren't clipped.
                tall = dw_total + FURRING_HEIGHT_FT + MAIN_DEPTH_FT + 4.0 * HOLE_MARGIN_FT
                boundary_solid = build_boundary_solid(outer, holes, fixtures,
                                                      z_bottom - HOLE_MARGIN_FT, tall)
                if boundary_solid is None:
                    result["ceilings_skipped"].append(cid + ": boundary solid failed")
                    continue

                # Per-room mode: pick this ceiling's rooms (same level first, any level as a
                # fallback). A ceiling with no overlapping Room (e.g. a soffit) falls back to the
                # legacy whole-grid path below so it still gets generated.
                per_room_regions = None
                if CEILING_PER_ROOM and room_regions and not is_soffit:
                    obb_c = poly_bbox(outer)
                    clev = -1
                    try:
                        clev = eid_value(ceiling.LevelId)
                    except Exception:
                        pass
                    regions = [rg for rg in room_regions
                               if rg[2] == clev and rects_overlap(rg[5], obb_c)]
                    if not regions:
                        regions = [rg for rg in room_regions if rects_overlap(rg[5], obb_c)]
                        if regions:
                            warnings.append("Ceiling {}: no Rooms on its own level; using {} plan-overlapping room(s) from other levels".format(cid, len(regions)))
                    if regions:
                        per_room_regions = regions
                    else:
                        warnings.append("Ceiling {}: no Room overlaps it - falling back to the legacy whole-grid path".format(cid))

                # Legacy path only: subtract every intersecting wall's footprint from the clip
                # mask and note the wall-face lines so the board grid stops at them.
                wall_x_cuts = []
                wall_y_cuts = []
                wall_bboxes = []
                if per_room_regions is None and CLIP_CEILING_AT_WALLS and wall_plans:
                    obb = poly_bbox(outer)
                    for (wpoly, wbb, waxis, f_lo, f_hi) in wall_plans:
                        if not rects_overlap(wbb, obb):
                            continue
                        cutter = make_planar_poly_solid(XYZ(0.0, 0.0, z_bottom - HOLE_MARGIN_FT),
                                                        XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ,
                                                        wpoly, tall)
                        if cutter is not None:
                            cut = boolean_op(boundary_solid, cutter, BooleanOperationsType.Difference)
                            if solid_ok(cut):
                                boundary_solid = cut
                        wall_bboxes.append(wbb)
                        # keep each cut LOCAL: carry the wall's extent along the other axis so a
                        # face line only cuts the rows/courses that wall actually crosses
                        if waxis == "x":
                            wall_x_cuts.extend([(f_lo, wbb[1], wbb[3]), (f_hi, wbb[1], wbb[3])])
                        elif waxis == "y":
                            wall_y_cuts.extend([(f_lo, wbb[0], wbb[2]), (f_hi, wbb[0], wbb[2])])
                    wall_x_cuts.sort()
                    wall_y_cuts.sort()

                if is_soffit:
                    # SOFFIT FLOW: exactly TWO custom-cut boards per soffit - one per leg of an
                    # L-shaped run (butt joint at the inner corner) or a mid-run split on a
                    # straight run - clipped against the wall-subtracted mask so they end at the
                    # walls the soffit spans between. No 4x8 grid, no rooms/zones, no mains.
                    result["soffits_processed"] += 1
                    z_top = z_bottom + dw_total
                    st_counter = [0]
                    board_seq = [0]
                    if do_drywall:
                        rects = soffit_board_rects(outer, warnings, cid)
                        made = emit_soffit_boards(cid, host_tag, z_bottom, rects, boundary_solid,
                                                  rated, board_records, board_seq, warnings)
                        result["boards_created"] += made
                        result["cut_boards"] += made
                        result["drywall_layers"] += len(layer_stack(rated))
                    if GENERATE_FURRING:
                        sbx0, sby0, sbx1, sby1 = poly_bbox(outer)
                        f_made, f_spl = emit_furring(
                            cid, host_tag, st_counter, z_top, boundary_solid,
                            sbx0, sbx1, sby0, sby1, warnings, framing_records, room_id="SOFFIT")
                        result["furring_created"] += f_made
                        result["splice_joints"] += f_spl
                elif per_room_regions is not None:
                    # PER-ROOM generation: each room polygon is its own bounded region (the same
                    # role a wall run plays in the wall script). Boards/furring/mains are laid out
                    # on the room's own bbox/grid and cut at the room boundary by the room mask -
                    # nothing exists outside its room, so there is nothing to subtract afterward.
                    z_top = z_bottom + dw_total     # furring bottom sits on top of the drywall
                    st_counter = [0]     # flat per-ceiling framing counter -> ST-<host>-<n>
                    board_seq = [0]      # flat per-ceiling board counter (shared across rooms)
                    screw_seq = [0]
                    covered = 0.0
                    for (rid, rnum, rlev, r_outer, r_inners, rbb) in per_room_regions:
                        room_prism = make_planar_poly_solid(
                            XYZ(0.0, 0.0, z_bottom - HOLE_MARGIN_FT),
                            XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ, r_outer, tall)
                        if room_prism is None:
                            warnings.append("Room {}: boundary prism failed; room skipped".format(rid))
                            continue
                        for ip in r_inners:
                            ips = make_planar_poly_solid(
                                XYZ(0.0, 0.0, z_bottom - 2.0 * HOLE_MARGIN_FT),
                                XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ, ip, tall + 4.0 * HOLE_MARGIN_FT)
                            room_prism = boolean_op(room_prism, ips, BooleanOperationsType.Difference)
                        room_mask = boolean_op(room_prism, boundary_solid,
                                               BooleanOperationsType.Intersect)
                        if not solid_ok(room_mask):
                            continue                # this room does not actually meet this ceiling
                        covered += room_mask.Volume
                        result["rooms_used"] += 1
                        room_records.append({
                            "room_id": rid, "room_number": rnum, "host_ceiling": cid,
                            "outer_ft": [[round(px, 3), round(py, 3)] for (px, py) in r_outer],
                        })
                        rholes = holes + r_inners
                        rbx0, rby0, rbx1, rby1 = rbb
                        if do_drywall:
                            dc = emit_drywall(cid, host_tag, z_bottom, r_outer, rholes, fixtures,
                                              room_mask, rated, board_records, screw_records,
                                              do_screws, warnings, (), (), (),
                                              room_id=rid, board_seq=board_seq, screw_seq=screw_seq)
                            result["boards_created"] += dc["boards"]
                            result["cut_boards"] += dc["cut_boards"]
                            result["drywall_layers"] += dc["layers"]
                            result["screws_created"] += dc["screws"]
                        if GENERATE_FURRING:
                            f_made, f_spl = emit_furring(
                                cid, host_tag, st_counter, z_top, room_mask, rbx0, rbx1, rby0, rby1,
                                warnings, framing_records, room_id=rid)
                            result["furring_created"] += f_made
                            result["splice_joints"] += f_spl
                            m_made, h_made, m_spl = emit_mains(
                                cid, host_tag, st_counter, z_top, room_mask, r_outer, rholes,
                                fixtures, rbx0, rbx1, rby0, rby1, warnings, framing_records,
                                room_id=rid)
                            result["mains_created"] += m_made
                            result["hangers_created"] += h_made
                            result["splice_joints"] += m_spl
                            if m_made > 0:
                                result["reinforced_ceilings"] += 1
                    try:
                        if boundary_solid.Volume > 1e-6 and covered < 0.98 * boundary_solid.Volume:
                            pct = 100.0 * (1.0 - covered / boundary_solid.Volume)
                            warnings.append("Ceiling {}: {:.1f}% of its area is covered by no Room - that area got no boards/furring".format(cid, pct))
                    except Exception:
                        pass
                else:
                    # FALLBACK ZONES: after the wall subtraction the clip mask is a set of
                    # disconnected room-shaped volumes. Split it into those zones and anchor a
                    # fresh full-sheet grid at EACH zone's own corner (same idea as per-room mode
                    # with real Rooms) - maximum whole 4x8 sheets per enclosed area, and no
                    # element can span two zones because each is laid out and clipped separately.
                    vols = [boundary_solid]
                    try:
                        sv = SolidUtils.SplitVolumes(boundary_solid)
                        if sv is not None and sv.Count > 0:
                            vols = list(sv)
                    except Exception as ex:
                        warnings.append("Ceiling {}: SplitVolumes failed ({}); one zone".format(cid, ex))
                    z_top = z_bottom + dw_total     # furring bottom sits on top of the drywall
                    st_counter = [0]     # flat per-ceiling framing counter -> ST-<host>-<n>
                    board_seq = [0]      # flat per-ceiling board counter (shared across zones)
                    screw_seq = [0]
                    zi = 0
                    for vol in vols:
                        if not solid_ok(vol):
                            continue
                        zi += 1
                        zid = "{}-Z{:02d}".format(cid, zi)
                        try:
                            vbb = vol.GetBoundingBox()
                            vmn = vbb.Transform.OfPoint(vbb.Min)
                            vmx = vbb.Transform.OfPoint(vbb.Max)
                        except Exception:
                            warnings.append("Zone {}: no bbox; skipped".format(zid))
                            continue
                        zx0, zy0, zx1, zy1 = vmn.X, vmn.Y, vmx.X, vmx.Y
                        if (zx1 - zx0) < 0.5 or (zy1 - zy0) < 0.5:
                            warnings.append("Zone {} skipped: sliver {:.2f} x {:.2f} ft (ceiling overhang past a wall?)".format(zid, zx1 - zx0, zy1 - zy0))
                            continue
                        zouter = [(zx0, zy0), (zx1, zy0), (zx1, zy1), (zx0, zy1)]
                        # Per-zone wall cuts: ONLY walls that actually TOUCH this zone may split
                        # its boards - a stub poking into the zone must end the board on both
                        # sides (no panel ever sits on two sides of a wall), while a NEIGHBORING
                        # zone's wall in a bbox-overlap area must not (those false splits were
                        # shredding whole sheets). The exact wall footprint was subtracted from
                        # the mask, so touching is tested with a slightly inflated prism.
                        zx_cuts = []
                        zy_cuts = []
                        for (wpoly, wbb, waxis, f_lo, f_hi) in wall_plans:
                            if not rects_overlap(wbb, (zx0, zy0, zx1, zy1)):
                                continue
                            tol = 0.25
                            grown = [(wbb[0] - tol, wbb[1] - tol), (wbb[2] + tol, wbb[1] - tol),
                                     (wbb[2] + tol, wbb[3] + tol), (wbb[0] - tol, wbb[3] + tol)]
                            gp = make_planar_poly_solid(XYZ(0.0, 0.0, z_bottom - HOLE_MARGIN_FT),
                                                        XYZ.BasisX, XYZ.BasisY, XYZ.BasisZ,
                                                        grown, tall)
                            if gp is None:
                                continue
                            touch = boolean_op(gp, vol, BooleanOperationsType.Intersect)
                            if not solid_ok(touch):
                                continue
                            if waxis == "x":
                                zx_cuts.extend([(f_lo, wbb[1], wbb[3]), (f_hi, wbb[1], wbb[3])])
                            elif waxis == "y":
                                zy_cuts.extend([(f_lo, wbb[0], wbb[2]), (f_hi, wbb[0], wbb[2])])
                        zx_cuts.sort()
                        zy_cuts.sort()
                        if do_drywall:
                            dc = emit_drywall(cid, host_tag, z_bottom, zouter, holes, fixtures,
                                              vol, rated, board_records, screw_records,
                                              do_screws, warnings,
                                              zx_cuts, zy_cuts, (),
                                              room_id=zid, board_seq=board_seq,
                                              screw_seq=screw_seq, force_clip=True)
                            result["boards_created"] += dc["boards"]
                            result["cut_boards"] += dc["cut_boards"]
                            result["drywall_layers"] += dc["layers"]
                            result["screws_created"] += dc["screws"]
                        if GENERATE_FURRING:
                            f_made, f_spl = emit_furring(
                                cid, host_tag, st_counter, z_top, vol, zx0, zx1, zy0, zy1,
                                warnings, framing_records, room_id=zid)
                            result["furring_created"] += f_made
                            result["splice_joints"] += f_spl
                            # Reinforce: carrying channels + hangers when the span needs support.
                            m_made, h_made, m_spl = emit_mains(
                                cid, host_tag, st_counter, z_top, vol, zouter, holes, fixtures,
                                zx0, zx1, zy0, zy1, warnings, framing_records, room_id=zid)
                            result["mains_created"] += m_made
                            result["hangers_created"] += h_made
                            result["splice_joints"] += m_spl
                            if m_made > 0:
                                result["reinforced_ceilings"] += 1

                result["ceilings_processed"] += 1
            except Exception as cex:
                result["ceilings_skipped"].append(cid + ": error - " + str(cex))
                warnings.append("Ceiling {} failed: {}".format(cid, cex))
                continue

        result["export_view"] = ensure_export_view(warnings)
    except Exception as ex:
        result["notes"].append("FATAL: " + str(ex))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    result["board_records"] = len(board_records)
    result["framing_records"] = len(framing_records)
    result["screw_records"] = len(screw_records)

    if WRITE_MANIFEST:
        manifest = {
            "app_id": APP_ID,
            "schema": "origin_ceiling_assembly_v1",
            "units": "world coords in feet; member/board dims in inches",
            "nomenclature": {
                "host": "C### (ceiling) / S### (soffit), persisted to the ceiling Mark",
                "drywall_panel": "DP-<host>-<seq>  (single underside face; no face letter)",
                "framing_member": "ST-<host>-<seq>  (member_type = FURRING / MAIN / HANGER)",
                "screw": "SC-<host>-<seq>",
            },
            "summary": dict((k, result[k]) for k in (
                "ceilings_processed", "rated_ceilings", "furring_created", "mains_created",
                "hangers_created", "reinforced_ceilings", "splice_joints", "boards_created",
                "screws_created", "fixtures_cut", "rooms_found", "rooms_used",
                "soffits_processed")),
            "rooms": room_records,
            "framing": framing_records,
            "boards": board_records,
            "screws": screw_records,
        }
        try:
            f = open(MANIFEST_PATH, "w")
            try:
                json.dump(manifest, f, indent=2)
            finally:
                f.close()
            result["manifest_path"] = MANIFEST_PATH
        except Exception as ex:
            result["manifest_path"] = "failed"
            warnings.append("Manifest write failed: {}".format(ex))

    OUT = result
