# Origin Wall Assembly Generator v4 - PHASE 1 + PHASE 2 (FRAMING + DRYWALL)  [NO-SCREWS BUILD]
# Dynamo Python Script node for Revit (target: Revit 2027, PythonNet3 / CPython3 engine).
#
# NO-SCREWS VARIANT: identical to origin_wall_assembly_v4_phase2.py (same APP_ID, same
# nomenclature, same cleanup) EXCEPT it never generates screw markers or screw records - useful
# for a lighter Isaac Sim model or when fasteners aren't needed yet. Kept in lockstep with the
# trunk; the ONLY differences are this header, GENERATE_SCREWS = False, and MANIFEST_PATH. Because
# it shares the trunk's APP_ID + ElementId cleanup tokens, running this on a wall REPLACES the
# trunk's assembly on that wall with a screwless one (and vice-versa) - they are interchangeable
# alternates, not additive. (The trunk can also just be run with Dynamo IN[8]=False to skip
# screws; this file exists so you don't have to wire that input.)
#
# WHAT THIS IS:
#   The unified construction-accurate wall-assembly generator. It builds, for each selected
#   straight wall, in ONE run and ONE transaction:
#
#     PHASE 1 - METAL FRAMING (carried over VERBATIM from origin_drywall_assembly_v4.py,
#               which is Revit-confirmed):
#                 - Vertical C-studs @ 16" OC, king studs on jambs, cripples above headers /
#                   below sills, jack studs, flat-laid C headers, window C sills.
#                 - U-tracks: continuous bottom (split at doors) and top (split only if an
#                   opening reaches the ceiling).
#                 - True lipped-C and U cold-formed cross-sections (extruded profiles).
#
#     PHASE 2 - DRYWALL (NEW):
#                 - Horizontal courses of gypsum board on BOTH wall faces.
#                 - Staggered butt joints (per row, per face, and per layer).
#                 - OPENINGS ARE CUT AS A SINGLE CONNECTED PIECE (L / notch / hole), NOT as
#                   separate rectangles split at the opening edges. This honors the locked
#                   drywall-opening rule: hang-over-then-cut-out, joints toward mid-opening,
#                   NEVER a butt joint at an opening corner (renovation-headquarters.com rules).
#                 - Fire-rated walls get 2 layers of 5/8" Type X per side (staggered between
#                   layers); non-rated walls get 1 layer of 1/2". Rating is auto-detected.
#                 - 1/8" code gaps at butt joints; tapered long edges recorded as metadata.
#                 - Board sizes 4x8 (default) or 4x12 (setting).
#                 - Per-board property schema written into the DirectShape Comments so it
#                   survives export (full sidecar JSON manifest is Phase 3).
#
# PHASE 3 (NOT here): fastener solids + coordinates, assembly manifest JSON, export-isolation
#   view that hides the base Revit wall. Hooks are left in place (board records accumulate).
#
# STILL APPROXIMATE (documented, inherited):
#   - Straight vertical walls only. Curved / slanted walls are skipped.
#   - Openings are approximated from hosted-insert bounding boxes (may be slightly oversized).
#   - A single sheet that overlaps MORE THAN ONE opening falls back to rectangular subtraction
#     for that sheet only (rare; reported in OUT["notes"]).
#   - This is layout / visualization geometry, not shop-drawing certification.

import clr
import math
import json
import random

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

APP_ID = "ORIGIN_ASSEMBLY_V4"          # shared with the Phase-1 script so cleanup unifies

# ---- Nomenclature (hierarchical element naming) ----
# Every wall gets a stable, building-unique number NNN (e.g. 001), persisted to the wall's Mark.
# Its generated children are then named under that number so the hierarchy is parseable:
#   drywall panels : DP-<wall>-<seq><face>   e.g. DP-001-001A / DP-001-001B  (A/B = the two faces;
#                                            the seq counts boards per face in install order)
#   framing members: ST-<wall>-<seq>         e.g. ST-001-001, ST-001-002     (one flat per-wall
#                                            sequence for studs/tracks/headers/sills/kings/jacks/
#                                            cripples; the real type lives in the Member_Type field)
#   screws         : SC-<wall>-<seq>         e.g. SC-001-001, SC-001-002      (flat per-wall)
# The name is written to each element's Name AND Mark (schedulable/taggable). The immutable Revit
# ElementId is still kept in the Comments (WALL=W<eid>) so delete-previous stays reliable.

# Phase toggles. This script owns the whole assembly; a rerun rebuilds every enabled phase.
GENERATE_FRAMING = True
GENERATE_DRYWALL = True

# DirectShape-only (self-contained solids, no families needed). Family mode is Phase 3+.
OUTPUT_MODE = "directshape"

# Each member/board type gets its own colored Generic Model subcategory (toggle in V/G).
COLOR_BY_TYPE = True

# Safety.
DELETE_PREVIOUS_ORIGIN_ASSEMBLY = True
PROCESS_ALL_WALLS_IF_NONE_SELECTED = False

# The normal cleanup above only removes previous output for the walls being processed THIS run
# (matched by the host wall's ElementId). If walls were deleted/recreated (their ElementId changed)
# or an older build left elements behind, the old panels become ORPHANS the scoped cleanup can't
# find - they linger and are a common cause of "panels still bleeding" (old untrimmed geometry
# sitting under the new, correctly trimmed geometry). Set this True for ONE run to purge EVERY
# Origin assembly DirectShape in the model (regardless of wall) before regenerating, then set it
# back to False. Dynamo IN[9] also overrides this.
PURGE_ALL_ORIGIN_ELEMENTS = False

# After generating, create/update a dedicated 3D view named "ORIGIN Assembly" that HIDES the base
# Revit wall (plus doors/windows) so only the generated framing + drywall is visible. The
# generated assembly sits flush INSIDE the existing wall, so in a normal view the base wall's
# coincident surface hides it (and z-fights). This isolation view is also the basis for the
# Phase-3 USD/Isaac export. Your other views are left untouched.
CREATE_EXPORT_VIEW = True
EXPORT_VIEW_NAME = "ORIGIN Assembly"

# Corner / wall-join handling. Walls are generated independently, so where two non-parallel walls
# meet, one must run "through" and the other "butt" into it - otherwise their assemblies overlap
# (double material) at the corner. When True, at each joined end the assembly (drywall + framing)
# is pulled back so it stops at the through wall's face. Tiebreak at an L-corner: the higher
# ElementId wall runs through, the lower butts (both walls compute the same decision). A wall that
# ends into the middle of another (T-join stem) always butts. Collinear joins are left alone.
HANDLE_CORNERS = True
# Corner pull-back applies to the FRAMING (studs/tracks) so channels don't collide at a joined
# wall. When True the DRYWALL is trimmed to the SAME pulled-back extents (run_lo/run_hi), so at a
# corner / T-join each wall's boards stop at the face of the wall it butts into instead of running
# the full location-line length and poking through into the adjacent room. This is ON by default
# because leaving it off makes panels overshoot across wall junctions into neighboring spaces.
# (Trade-off: at an OUTSIDE corner it can leave a small gap; the through-wall side of an L-corner
# still laps full because only the butting wall is pulled back - see corner_pullbacks().)
TRIM_DRYWALL_AT_CORNERS = True

# Per-face control of the corner behavior. When a face's entry is False, that face ALWAYS BUTTS
# at the other wall's NEAR face - at outside AND inside corners alike - so a board never crosses
# into the other wall's footprint: zero cross-wall panel overlap for Isaac Sim/robot interaction.
# At a concave corner the butting edge lands exactly on the other wall's finished surface (a real
# drywall inside corner, no gap); at a convex corner the arris is left bare (previously covered
# by the lap). BOTH faces default to False: "exterior" is just the wall's Orientation side, so on
# interior partitions it is a room face too (DP-011-006B penetrated a neighbor via that face).
# Set a face True to restore the original wrap/cover behavior (renders only - overlaps solids).
DRYWALL_CORNER_WRAP_BY_FACE = {
    "interior": False,
    "exterior": False,
}

# Split the drywall at PARTITION junctions: wherever another wall butts into the MIDDLE of this
# wall (a T-join where this wall runs through), force a board joint on the through-wall's drywall at
# that line so no single panel spans across the partition into two rooms. Each room then gets its
# own panels on the shared wall. This is NOT how sheets are hung in reality (a through wall's board
# runs continuously past a partition), but it keeps every panel to a single room - better for
# per-room Isaac Sim object separation. Set False to keep continuous, construction-accurate boards.
SPLIT_DRYWALL_AT_PARTITIONS = True

# Fasteners (drywall screws). Placed along the stud lines crossing each board, on the room-facing
# surface, at SCREW_SPACING_FT vertically. Emitted as small solid markers AND written to the
# manifest as coordinates. To keep geometry light, only the OUTERMOST layer is screwed by default.
# NO-SCREWS BUILD: hard off. (Dynamo IN[8] can still force it on if you ever want screws here.)
GENERATE_SCREWS = False
SCREW_SPACING_FT = 16.0 / 12.0           # field screws 16" OC along each stud (USG, screws to 16" studs)
SCREW_EDGE_SETBACK_FT = 0.5 / 12.0       # set screws back from board edges/ends (USG/GA min 3/8")
SCREW_EDGE_TOL_FT = 0.05                 # a stud within this of a board edge marks a butt joint/end
SCREW_MARKER_SIZE_FT = 0.5 / 12.0        # visual head footprint
SCREW_MARKER_DEPTH_FT = 0.15 / 12.0      # total head thickness (mostly embedded in the board)
SCREW_HEAD_PROUD_FT = 0.02 / 12.0        # how far the head sits proud of the drywall face (subtle)
SCREWS_OUTER_LAYER_ONLY = True
MAX_SCREWS_PER_WALL = 8000               # safety cap per wall

# Electrical outlet boxes (TM junction boxes from the user's catalog). ONE box per wall at a
# RANDOM interior stud, on a random face, at a random height 12-18in to the box bottom: the box's
# side edge starts at the stud's flange face and the box sits ON the drywall surface - fully
# visible on the panel, proud of the finish face (it never cuts into the stud or the cavity).
# Placed as instances of the "TM_outlet_box" FAMILY (run origin_outlet_family_setup.py ONCE to
# create + load families\TM_outlet_box.rfa) so they can be MOVED / SWAPPED / DELETED natively in
# Revit. Re-runs PRESERVE those edits: the host wall's Comments get an ORIGIN_EO_PLACED marker on
# first placement and marked walls are skipped (a deleted box stays deleted). Set
# OUTLET_FORCE_REGENERATE=True to delete a wall's tagged boxes, clear its marker and re-place.
# delete_previous() never touches outlets (it only scans DirectShapes).
GENERATE_OUTLETS = True
# The outlet family is an ELECTRICAL FIXTURE - its own class, separate from the Generic Models
# drywall/framing - so clicking an outlet selects ONLY the outlet (the drywall never comes with
# it) and it can be filtered/hidden independently. New _ef name so the older Generic-Model
# family in already-touched projects cannot shadow it.
OUTLET_FAMILY = "TM_outlet_box_ef"
OUTLET_TYPE = "TM-S44"                   # default box; all catalog types below
# Which face gets the outlet: "inner" = the side whose outward normal points toward the centroid
# of the SELECTED walls (the robot's environment - it must always be able to see the outlet;
# random face selection was putting some outlets on the outside of the building). "random" =
# the old behavior.
OUTLET_FACES = "inner"
OUTLET_MODELS = {                        # width x height x depth, mm
    "TM-S44": (103.0, 103.0, 38.0),
    "TM-54151": (94.0, 94.0, 38.0),
    "TM-1102": (93.0, 94.0, 52.0),
    "TM-1299": (74.0, 74.0, 35.0),
    "TM-4040A": (105.0, 105.0, 50.0),
    "TM-SG125": (72.0, 72.0, 21.0),
}
OUTLET_HEIGHT_MIN_FT = 1.0               # floor to box bottom (12 in)
OUTLET_HEIGHT_MAX_FT = 1.5               # floor to box bottom (18 in)
# "recess" = INTRUSION (the user's need): the face drywall board is cut with the socket-sized
# hole and the TM box sits INSIDE the wall with its front plate at the recess bottom (~70% of
# the wall thickness deep, clamped so nothing ever reaches the far face - invisible from the
# next room). Moving/deleting the box in Revit moves/removes the hole on the next run.
# "box" = the old surface-mounted look (no cut).
OUTLET_STYLE = "recess"
OUTLET_RECESS_FRAC = 0.30                # recess depth as a fraction of the wall thickness
                                         # (user 2026-07-17: 70% read as a barely-visible deep
                                         # pocket; 30% puts the box plate just inside the hole)
OUTLET_MARKER = "ORIGIN_EO_PLACED"
OUTLET_FORCE_REGENERATE = False
OUTLET_RFA_PATH = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\families\TM_outlet_box_ef.rfa"

# Assembly manifest: a sidecar JSON with every element's properties, so metadata survives the USD
# export regardless of exporter. Written once per run.
WRITE_MANIFEST = True
MANIFEST_PATH = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\origin_assembly_manifest_noscrews.json"

# ---- Units: Revit internal units are feet; inch = 1/12 ft ----
IN_FT = 1.0 / 12.0

# ---- Framing dimensions (Phase 1, verbatim from v4) ----
STUD_SPACING_FT = 16.0 * IN_FT          # 16 in. OC
STUD_DEPTH_FT = 3.625 * IN_FT           # nominal/fallback C-stud web depth (used only if not derived)
FLANGE_FT = 1.25 * IN_FT                # C-stud flange width
LIP_FT = 0.1875 * IN_FT                 # C-stud return lip
MAT_T_FT = 0.0451 * IN_FT               # steel material thickness (~18 ga)
TRACK_FLANGE_FT = 1.25 * IN_FT
MIN_SEG_FT = 0.25                       # skip framing pieces shorter than 3 in.

# Stud web depth: when True, depth = wall thickness - drywall on BOTH faces, so the stud web
# butts the back of the drywall and framing+drywall exactly fills the modeled wall. When False,
# use the fixed STUD_DEPTH_FT above. Track depth follows (wraps the stud + 2x material thickness).
DERIVE_STUD_DEPTH_FROM_WALL = True
MIN_STUD_DEPTH_FT = 1.25 * IN_FT        # floor on the derived depth (very thin / over-clad walls)

# ---- Drywall layout (Phase 2) ----
# Board face size. Default 4x8 (8 ft long). Set 12.0 for 4x12 sheets (fewer joints).
PANEL_LENGTH_FT = 8.0
PANEL_HEIGHT_FT = 4.0                    # sheets hung horizontally: 4 ft course height

# Layer build-up. Rated walls: 2 layers of 5/8" Type X. Non-rated: 1 layer of 1/2".
DRYWALL_THICKNESS_STD_FT = 0.5 * IN_FT
DRYWALL_THICKNESS_RATED_FT = 0.625 * IN_FT
DRYWALL_LAYERS_RATED = 2
DRYWALL_LAYERS_STD = 1

# Joint control.
CODE_GAP_FT = (1.0 / 8.0) * IN_FT        # 1/8" total gap between adjacent boards
LAYER_H_STAGGER_FT = PANEL_LENGTH_FT / 2.0   # shift vertical joints between stacked layers
LAYER_V_STAGGER_FT = PANEL_HEIGHT_FT / 2.0   # shift horizontal joints between stacked layers
AVOID_JOINTS_AT_JAMBS = True             # nudge a course so no butt joint lands on an opening jamb
JOINT_CLEAR_FT = 4.0 * IN_FT             # keep butt joints at least this far from a jamb
# How far the drywall stops back from the ACTUAL opening edge (a small reveal). The framing
# opening_rects are the insert bbox + OPENING_CLEARANCE_FT (rough-opening gap); the drywall must NOT
# inherit that whole gap or it stands ~7/8" off the frame (a visible gap all around the window). So
# the drywall cut is the opening_rect pulled BACK IN to ~this reveal from the insert bbox.
DRYWALL_OPENING_REVEAL_FT = 0.125 * IN_FT   # 1/8" reveal from the opening edge
TAPERED_LONG_EDGES = True                # model the factory taper on full-height field boards
# Taper geometry: the room-facing side recesses near the two long (top/bottom) horizontal edges,
# forming the shallow valley real drywall has for tape + compound. Applied ONLY to full-height,
# un-cut rectangular field boards; partial courses and notched/opening boards stay square (their
# long edge is a cut edge in reality). Set TAPERED_LONG_EDGES = False to disable for Isaac weight.
TAPER_DEPTH_FT = 0.0625 / 12.0           # ~1/16" recess depth at the very edge
TAPER_WIDTH_FT = 2.25 / 12.0             # taper run-in from each long edge

MIN_PIECE_WIDTH_FT = 0.25                # skip board slivers narrower than 3 in.
MIN_PIECE_HEIGHT_FT = 0.25
HOLE_MARGIN_FT = 0.05                    # cutter over-travel for boolean hole cuts

# Both faces are generated. exterior = +Wall.Orientation; interior = -Wall.Orientation.
# base_edge_shift staggers where the first board edge lands; Face B is offset one stud bay so
# the two faces do not simply mirror. odd_row_additional_shift staggers odd courses.
FACE_LAYOUTS = [
    {
        "face_name": "FACE_A_INTERIOR",
        "letter": "A",                       # DP-<wall>-<n>A  (this face)
        "side": "interior",
        "enabled": True,
        "base_edge_shift_ft": 0.0,
        "odd_row_additional_shift_ft": 4.0,
    },
    {
        "face_name": "FACE_B_EXTERIOR",
        "letter": "B",                       # DP-<wall>-<n>B  (other face)
        "side": "exterior",
        "enabled": True,
        "base_edge_shift_ft": 16.0 * IN_FT,
        "odd_row_additional_shift_ft": 4.0,
    },
]

# Opening detection (shared by framing + drywall).
CUT_OPENINGS = True
# Pre-existing MANUAL cutouts (openings/voids cut into walls by hand in Revit, not real doors or
# windows) were being mistaken for windows and wrecking the board layout. The script's outlet
# system replaces them, so remove them during processing (user-approved 2026-07-17). Real Doors
# and Windows (and embedded curtain walls) keep the normal opening-cut behavior.
REMOVE_MANUAL_CUTOUTS = True
# An opening whose bottom lands within this of the floor is a DOOR and is snapped TO the floor.
# Door families whose geometry starts slightly above the floor were otherwise treated like
# windows, so the bottom track (and a board sliver) kept running across the doorway - a
# threshold obstacle in the robot's path between rooms (user report 2026-07-17).
DOOR_FLOOR_SNAP_FT = 0.5
OPENING_CLEARANCE_FT = 0.05

# Fire-rating override: None = auto-detect; True/False = force. (Dynamo IN[7] also overrides.)
FORCE_FIRE_RATED = None

# Dynamo inputs:
#   IN[0] = selected wall(s) (or use current Revit selection if empty)
#   IN[5] = optional delete previous: True/False (overrides DELETE_PREVIOUS_ORIGIN_ASSEMBLY)
#   IN[6] = optional generate drywall: True/False (overrides GENERATE_DRYWALL)
#   IN[7] = optional force fire-rated: True/False (overrides auto-detection)
#   IN[8] = optional generate screws: True/False (overrides GENERATE_SCREWS)
#   IN[9] = optional purge ALL Origin elements first: True/False (overrides PURGE_ALL_ORIGIN_ELEMENTS)
# ============================================================


# ============================================================
# Cross-section profiles (Phase 1, verbatim from v4)
# ============================================================

def build_profiles(stud_depth):
    """Build the lipped-C stud profile and the U-track profile for a given through-wall stud
    depth. Track wraps the stud, so its depth = stud_depth + 2x material thickness. Returns
    (c_profile, u_profile, track_depth)."""
    D = stud_depth
    F = FLANGE_FT
    L = LIP_FT
    t = MAT_T_FT
    c = [(0, 0), (0, F), (L, F), (L, F - t), (t, F - t), (t, t),
         (D - t, t), (D - t, F - t), (D - L, F - t), (D - L, F), (D, F), (D, 0)]

    Dt = D + 2.0 * t
    Ht = TRACK_FLANGE_FT
    u = [(0, 0), (0, Ht), (t, Ht), (t, t), (Dt - t, t), (Dt - t, Ht), (Dt, Ht), (Dt, 0)]
    return c, u, Dt


# ------------------------------------------------------------
# Small vector / input helpers  (VERBATIM)
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
    """Numeric value of an ElementId. Revit 2024+ uses 64-bit .Value (removed .IntegerValue)."""
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
# Nomenclature helpers (hierarchical element naming)
# ------------------------------------------------------------

def letter_seq(n):
    """1->A, 2->B, ... 26->Z, 27->AA, 28->AB, ... (per-wall door/window/face suffix)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def is_category(elem, bic):
    try:
        return elem.Category is not None and elem.Category.Id == ElementId(bic)
    except:
        return False


def set_mark(element, name):
    """Best-effort write of the nomenclature name to an element's Mark (Identity Data), so it is
    schedulable and taggable. Silent on failure (some elements have a read-only/absent Mark)."""
    try:
        mk = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mk and (not mk.IsReadOnly):
            mk.Set(name)
    except:
        pass


def _parse_wall_number(s):
    """The positive int a Mark encodes as an Origin wall number (a pure / zero-padded integer),
    or None if the Mark is not one."""
    if not s:
        return None
    t = s.strip()
    if not t or not all(ch.isdigit() for ch in t):
        return None
    try:
        n = int(t)
    except:
        return None
    return n if n > 0 else None


def _wall_mark_param(wall):
    try:
        return wall.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
    except:
        return None


def _write_wall_mark(wall, number, warnings):
    p = _wall_mark_param(wall)
    if p is None or p.IsReadOnly:
        return
    tag = "{:03d}".format(number)
    try:
        if (p.AsString() or "") != tag:
            p.Set(tag)
    except Exception as ex:
        warnings.append("Could not set Mark on wall {}: {}".format(eid_value(wall.Id), ex))


def assign_wall_numbers(walls, warnings):
    """Give every selected wall a stable, building-unique nomenclature number (the '001' in
    DP-001-..., ST-001-..., SC-001-..., WN-001A, DR-001A). A wall keeps the number already stored
    in its Mark; new numbers are the smallest positive integers not used by ANY wall's Mark in the
    model, written back to Mark so reruns / later runs stay stable. Selected walls are numbered in
    ElementId order for determinism. Returns {wall_eid_value: number}. Must run inside a
    transaction (it writes Mark). Best-effort: Mark write failures are reported, not fatal."""
    taken = set()
    try:
        for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
            p = _wall_mark_param(w)
            n = _parse_wall_number(p.AsString()) if p else None
            if n is not None:
                taken.add(n)
    except Exception as ex:
        warnings.append("Wall-number scan failed (continuing): {}".format(ex))

    selected = sorted(walls, key=lambda w: eid_value(w.Id))
    assigned = {}
    used_here = set()
    # Pass 1: honor each wall's own valid, non-duplicated existing number.
    for w in selected:
        p = _wall_mark_param(w)
        n = _parse_wall_number(p.AsString()) if p else None
        if n is not None and n not in used_here:
            assigned[eid_value(w.Id)] = n
            used_here.add(n)
    # Pass 2: assign the rest the smallest free number; persist all (also normalizes padding).
    nxt = 1
    for w in selected:
        key = eid_value(w.Id)
        if key not in assigned:
            while nxt in taken:
                nxt += 1
            taken.add(nxt)
            assigned[key] = nxt
        _write_wall_mark(w, assigned[key], warnings)
    return assigned


# ------------------------------------------------------------
# Wall reading  (VERBATIM)
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


def wall_is_fire_rated(wall, warnings):
    """Detect a fire-rated wall via the wall type's 'Fire Rating' parameter or type name.
    Returns True/False. Fully best-effort; anything unreadable => False (non-rated, 1 layer).
    Each probe is individually guarded so a missing/odd parameter never raises a warning."""
    try:
        wt = wall.WallType
    except:
        return False
    # 1) 'Fire Rating' parameter on the wall type.
    try:
        p = wt.LookupParameter("Fire Rating")
        if p is not None and p.HasValue:
            st = p.StorageType
            if st == StorageType.String:
                s = p.AsString()
                if s and any(ch.isdigit() for ch in s):
                    return True
            elif st == StorageType.Double:
                if p.AsDouble() > 0.01:
                    return True
            elif st == StorageType.Integer:
                if p.AsInteger() > 0:
                    return True
    except:
        pass
    # 2) Type-name keywords.
    try:
        name = wt.Name.lower()
        for kw in ("fire", "rated", "type x", "type-x", "1 hr", "2 hr", "1-hr", "2-hr", "1hr", "2hr"):
            if kw in name:
                return True
    except:
        pass
    return False


def wall_ref_geometry(wall, width, warnings):
    """Distance from the EXTERIOR face to (Location Line, core mid-plane), both measured toward
    the interior along the exterior normal. Accounts for the Location Line reference and the
    compound structure so faces/studs land on their true surfaces."""
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

    # WallLocationLine: 0 WallCenterline, 1 CoreCenterline, 2 FinishFaceExt, 3 FinishFaceInt,
    #                   4 CoreExt, 5 CoreInt
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
    else:
        d_loc = width / 2.0

    core_center_from_ext = ext_noncore + core_width / 2.0
    return d_loc, core_center_from_ext


def face_normal_and_offset(true_orientation, d_loc, width, side_name):
    """Return (outward_normal, offset_along_that_normal_from_start) for the requested face.
    Exterior face = start + true_orientation * d_loc; interior face = start - true_orientation *
    (width - d_loc)."""
    is_exterior_cfg = str(side_name).lower().startswith("ext")
    if is_exterior_cfg:
        return true_orientation, d_loc
    return xyz_mul(true_orientation, -1.0), (width - d_loc)


# ------------------------------------------------------------
# Corner / wall-join handling
# ------------------------------------------------------------

def _wall_dir(wall):
    d = get_wall_curve_data(wall)
    return d[2] if d else None


def _joined_walls_at(wall, end):
    """Walls (other than self) joined to `wall` at location-curve end (0 or 1)."""
    out = []
    try:
        arr = wall.Location.get_ElementsAtJoin(end)
        for e in arr:
            if isinstance(e, Wall) and e.Id != wall.Id:
                out.append(e)
    except:
        pass
    return out


def _meets_other_end_to_end(other_wall, self_wall):
    """True if other_wall has self_wall joined at one of ITS ends (an L-corner, both end-to-end).
    False means self_wall's end lands mid-span of other_wall (a T-join stem)."""
    for oe in (0, 1):
        for e in _joined_walls_at(other_wall, oe):
            if e.Id == self_wall.Id:
                return True
    return False


# Corner-detection tolerances (feet). A wall end is treated as "meeting" another wall where their
# location lines cross (the walls need NOT be Revit-joined) when the end sits within the window
# [-(wO/2 + CORNER_JOIN_TOL), wO/2 + CORNER_OVERSHOOT_MAX] of that crossing along the wall - i.e.
# up to CORNER_JOIN_TOL short of the other wall, or up to CORNER_OVERSHOOT_MAX past it (a wall drawn
# beyond the corner - this can be large; the through-wall false-trim it used to risk is now ruled out
# by the classification below, so raise it if panels still poke through). If the crossing lands
# within CORNER_END_TOL of the OTHER wall's end the other wall ALSO terminates here.
CORNER_JOIN_TOL_FT = 0.5
CORNER_OVERSHOOT_MAX_FT = 2.0
CORNER_END_TOL_FT = 0.5


def _line_intersect_2d(a, d, p, e):
    """Intersection of the infinite 2D lines a + t*d and p + r*e (XYZ, using X/Y only, since walls
    are vertical). Returns an XYZ (Z copied from a) or None if the lines are parallel."""
    denom = d.X * e.Y - d.Y * e.X
    if abs(denom) < 1e-9:
        return None
    wx = p.X - a.X
    wy = p.Y - a.Y
    t = (wx * e.Y - wy * e.X) / denom
    return XYZ(a.X + d.X * t, a.Y + d.Y * t, a.Z)


def corner_pullbacks(wall, warnings, candidates=None):
    """Return (du0, du1): how far to pull this wall's assembly back at end0/end1 so it butts cleanly
    into any wall it meets there (no material poking into the next room). Detection is GEOMETRIC -
    it does NOT require the walls to be 'joined' in Revit (walls that merely touch are caught) - and
    is unioned with Revit's own join info as a safety net. At an L-corner (both walls end at the
    crossing) only the lower-ElementId wall trims; the other laps through so the corner stays
    covered. At a T-join the stem (this wall, ending mid-span of the other) trims. Parallel /
    collinear meetings are ignored. `candidates` = precomputed [(wall, curve_data, width), ...] for
    every straight wall in the model; built on demand if omitted. Best-effort."""
    du = [0.0, 0.0]
    if not HANDLE_CORNERS:
        return du[0], du[1]
    seg = get_wall_curve_data(wall)
    if seg is None:
        return du[0], du[1]
    start, end_pt, d, length = seg
    ends = [(start, d), (end_pt, xyz_mul(d, -1.0))]     # (endpoint, inward direction) for end0/end1
    my_eid = eid_value(wall.Id)

    # 1) Revit join info (safety net for anything the geometry pass might miss).
    for end in (0, 1):
        for other in _joined_walls_at(wall, end):
            odir = _wall_dir(other)
            if odir is not None and abs(dot(d, odir)) > 0.95:
                continue                                  # collinear continuation - no pull-back
            if _meets_other_end_to_end(other, wall):      # L-corner: higher ElementId runs through
                butt = my_eid < eid_value(other.Id)
            else:                                          # T-join: this wall is the stem -> butt
                butt = True
            if butt:
                du[end] = max(du[end], get_wall_width(other) / 2.0)

    # 2) Geometric detection over every straight wall (catches un-joined, merely-touching walls).
    if candidates is None:
        candidates = []
        try:
            for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
                sg = get_wall_curve_data(w)
                if sg is not None:
                    candidates.append((w, sg, get_wall_width(w)))
        except:
            pass

    for (other, oseg, wO) in candidates:
        if other.Id == wall.Id:
            continue
        ostart, oend, oe, olen = oseg
        if abs(dot(d, oe)) > 0.95:
            continue                                    # parallel / collinear - not a corner
        for ei, (pe, din) in enumerate(ends):
            X = _line_intersect_2d(pe, din, ostart, oe)
            if X is None:
                continue
            s = (X.X - pe.X) * din.X + (X.Y - pe.Y) * din.Y        # inward distance from end to X
            if s < -(wO / 2.0 + CORNER_JOIN_TOL_FT) or s > (wO / 2.0 + CORNER_OVERSHOOT_MAX_FT):
                continue                                # this end isn't at the crossing
            rO = (X.X - ostart.X) * oe.X + (X.Y - ostart.Y) * oe.Y  # param of X along the other wall
            if rO < -CORNER_END_TOL_FT or rO > olen + CORNER_END_TOL_FT:
                continue                                # crossing is off the other wall's extent
            other_ends_here = (rO <= CORNER_END_TOL_FT) or (rO >= olen - CORNER_END_TOL_FT)
            this_end_near = abs(s) <= (wO / 2.0 + CORNER_JOIN_TOL_FT)   # this end is AT the crossing
            if other_ends_here and this_end_near:
                # True L-corner: both walls terminate here. Lower ElementId butts (stops at the other
                # wall's near/room face); the higher laps through (wraps only to its far face). Both
                # forms trim an overshoot; a clean/short end gives pull<=0 -> no trim.
                butt = my_eid < eid_value(other.Id)
                pull = (s + wO / 2.0) if butt else (s - wO / 2.0)
            elif not other_ends_here:
                # This wall's end runs THROUGH the middle of the other wall (a T where THIS wall is
                # the stem - including a big overshoot into the next room). Trim to the other wall's
                # near/room face so nothing pokes past it. This is the main bleed case.
                pull = s + wO / 2.0
            else:
                # The other wall's END lands mid-span of THIS wall (a T where THIS wall runs through
                # and the other butts into it). This wall spans continuously - do NOT trim it here.
                pull = 0.0
            pull = max(0.0, min(pull, wO + CORNER_OVERSHOOT_MAX_FT))
            if pull > 0.0:
                du[ei] = max(du[ei], pull)
    return du[0], du[1]


def partition_split_positions(wall, candidates):
    """[(along_wall_pos_ft, side_x, side_y), ...] for each place another wall butts into the MIDDLE
    of this wall (a T-join with this wall as the through wall). (side_x, side_y) points from the
    crossing INTO that wall's body, so a given face is split only when its outward normal points the
    same way (the partition is on THAT face's side) - the opposite face is left continuous and lays
    out on its own. Corners (crossings at this wall's own ends) are excluded (handled by the
    pull-back). Best-effort; empty if disabled."""
    if not SPLIT_DRYWALL_AT_PARTITIONS:
        return []
    seg = get_wall_curve_data(wall)
    if seg is None:
        return []
    start, end_pt, d, length = seg
    out = []
    for (other, oseg, wO) in candidates:
        if other.Id == wall.Id:
            continue
        ostart, oend, oe, olen = oseg
        if abs(dot(d, oe)) > 0.95:
            continue                                    # parallel / collinear - not a junction
        X = _line_intersect_2d(start, d, ostart, oe)
        if X is None:
            continue
        p = (X.X - start.X) * d.X + (X.Y - start.Y) * d.Y     # along-wall pos of the crossing
        if p < MIN_SEG_FT or p > length - MIN_SEG_FT:
            continue                                    # crossing at (or past) this wall's end = a corner
        rO = (X.X - ostart.X) * oe.X + (X.Y - ostart.Y) * oe.Y
        if rO < -CORNER_END_TOL_FT or rO > olen + CORNER_END_TOL_FT:
            continue                                    # crossing off the other wall's extent
        other_ends_here = (rO <= CORNER_END_TOL_FT) or (rO >= olen - CORNER_END_TOL_FT)
        if not other_ends_here:                         # not an end-into-mid-span junction
            continue
        side_x = (ostart.X + oend.X) / 2.0 - X.X        # from the crossing toward the partition body
        side_y = (ostart.Y + oend.Y) / 2.0 - X.Y
        out.append((p, side_x, side_y))
    return out


def split_interval(lo, hi, positions):
    """Split [lo, hi] at each position strictly inside it; returns [(a, b), ...] left-to-right."""
    cuts = sorted(p for p in positions if lo + 1e-4 < p < hi - 1e-4)
    out = []
    a = lo
    for c in cuts:
        out.append((a, c))
        a = c
    out.append((a, hi))
    return out


def corner_face_extents(wall, candidates):
    """Per-face along-wall drywall extents (feet from this wall's start) that make corners behave
    like real drywall: an OUTSIDE (convex) corner WRAPS - one panel runs past the wall end to the
    adjacent wall's outer drywall face and the other butts under it - while an INSIDE (concave)
    corner BUTTS. Returns {"interior": (lo, hi), "exterior": (lo, hi)}; values may be <0 or >length
    where a face wraps past the end. Framing keeps using corner_pullbacks (butt only)."""
    seg = get_wall_curve_data(wall)
    if seg is None:
        return None
    start, end_pt, d, length = seg
    n = safe_normalize(wall.Orientation)
    if n is None:
        return None
    faces = (("exterior", n), ("interior", xyz_mul(n, -1.0)))   # outward normal per side
    t = DRYWALL_THICKNESS_STD_FT
    ext = {"interior": [0.0, length], "exterior": [0.0, length]}
    my_eid = eid_value(wall.Id)
    for (pe, din, ei) in [(start, d, 0), (end_pt, xyz_mul(d, -1.0), 1)]:
        best = None
        for (other, oseg, wO) in candidates:
            if other.Id == wall.Id:
                continue
            ostart, oend, oe, olen = oseg
            if abs(dot(d, oe)) > 0.95:
                continue                                # parallel / collinear
            X = _line_intersect_2d(pe, din, ostart, oe)
            if X is None:
                continue
            s = (X.X - pe.X) * din.X + (X.Y - pe.Y) * din.Y
            if s < -(wO / 2.0 + CORNER_JOIN_TOL_FT) or s > (wO / 2.0 + CORNER_OVERSHOOT_MAX_FT):
                continue                                # this end isn't at the crossing
            rO = (X.X - ostart.X) * oe.X + (X.Y - ostart.Y) * oe.Y
            if rO < -CORNER_END_TOL_FT or rO > olen + CORNER_END_TOL_FT:
                continue
            other_ends_here = (rO <= CORNER_END_TOL_FT) or (rO >= olen - CORNER_END_TOL_FT)
            this_end_near = abs(s) <= (wO / 2.0 + CORNER_JOIN_TOL_FT)
            if other_ends_here and this_end_near:
                scenario = "L"                          # both walls end here (L-corner)
            elif not other_ends_here:
                scenario = "stem"                       # this end pokes into the other wall's mid-span
            else:
                continue                                # this wall runs through a mid-span T -> no adj.
            Xp = (X.X - start.X) * d.X + (X.Y - start.Y) * d.Y
            sx = (ostart.X + oend.X) / 2.0 - X.X        # toward the other wall's body
            sy = (ostart.Y + oend.Y) / 2.0 - X.Y
            cand = (abs(s), scenario, Xp, sx, sy, wO / 2.0, my_eid > eid_value(other.Id))
            if best is None or cand[0] < best[0]:
                best = cand
        if best is None:
            continue
        _, scenario, Xp, sx, sy, hwO, role_through = best
        for (side, nF) in faces:
            if not DRYWALL_CORNER_WRAP_BY_FACE.get(side, True):
                # No-wrap face: ALWAYS butt at the other wall's NEAR face, at inside AND outside
                # corners alike - the board never crosses into the other wall's footprint; at a
                # concave corner the edge lands exactly on the other wall's finished surface.
                val = (Xp + hwO) if ei == 0 else (Xp - hwO)
            elif scenario == "stem":
                val = (Xp + hwO) if ei == 0 else (Xp - hwO)     # butt into the through wall's face
            else:
                inside = (nF.X * sx + nF.Y * sy) > 0.0
                if inside:
                    if role_through:
                        val = Xp                                # run to the corner (cover concave)
                    else:
                        val = (Xp + hwO) if ei == 0 else (Xp - hwO)   # butt the through wall's face
                else:                                           # OUTSIDE / convex -> wrap the arris
                    wrap = hwO if role_through else (hwO - t)    # laps to outer face / butts its back
                    val = (Xp - wrap) if ei == 0 else (Xp + wrap)
            if ei == 0:
                ext[side][0] = val
            else:
                ext[side][1] = val
    return {"interior": (ext["interior"][0], ext["interior"][1]),
            "exterior": (ext["exterior"][0], ext["exterior"][1])}


# ------------------------------------------------------------
# Openings  (VERBATIM)
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

    door_id = ElementId(BuiltInCategory.OST_Doors)
    win_id = ElementId(BuiltInCategory.OST_Windows)
    wall_id_cat = ElementId(BuiltInCategory.OST_Walls)
    removed = 0
    for eid in insert_ids:
        e = doc.GetElement(eid)
        if not e:
            continue
        # Only REAL doors/windows (and embedded curtain walls) are openings the drywall must
        # wrap. Any other insert is a pre-existing MANUAL cutout - the outlet system replaces
        # those, so delete it instead of treating it as a window.
        is_opening = False
        try:
            c = e.Category
            if c is not None and (c.Id == door_id or c.Id == win_id or c.Id == wall_id_cat):
                is_opening = True
        except Exception:
            is_opening = False
        if not is_opening:
            if REMOVE_MANUAL_CUTOUTS:
                try:
                    doc.Delete(e.Id)
                    removed += 1
                except Exception as dex:
                    warnings.append("Wall {}: could not remove manual cutout {} ({})".format(
                        eid_value(wall.Id), eid_value(eid), dex))
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
        if y0 <= DOOR_FLOOR_SNAP_FT:
            y0 = 0.0        # floor-reaching opening = DOOR: snap to the floor so the bottom
                            # track splits and no board/track sliver crosses the doorway

        if (x1 - x0) > 0.1 and (y1 - y0) > 0.1:
            rects.append((x0, y0, x1, y1))

    if removed:
        warnings.append("Wall {}: removed {} pre-existing manual cutout(s) (non-door/window inserts)".format(
            eid_value(wall.Id), removed))

    return rects


def name_openings(wall, wall_id, wall_tag, orecords, warnings):
    """Give each door / window hosted in this wall a hierarchical Mark: WN-<wall><letter> for
    windows, DR-<wall><letter> for doors (letter enumerates that type on the wall: A, B, C...).
    Written to the instance Mark (schedulable / taggable) and Comments, and recorded in the
    manifest so the door/window <-> wall relationship survives export. Best-effort. Returns
    {"doors": n, "windows": n}."""
    counts = {"doors": 0, "windows": 0}
    try:
        insert_ids = wall.FindInserts(True, True, True, True)
    except Exception as ex:
        warnings.append("Wall {}: FindInserts (naming) failed ({})".format(eid_value(wall.Id), ex))
        return counts

    door_i = 0
    win_i = 0
    for eid in insert_ids:
        e = doc.GetElement(eid)
        if e is None:
            continue
        if is_category(e, BuiltInCategory.OST_Doors):
            door_i += 1
            name, kind = "DR-{}{}".format(wall_tag, letter_seq(door_i)), "DOOR"
            counts["doors"] += 1
        elif is_category(e, BuiltInCategory.OST_Windows):
            win_i += 1
            name, kind = "WN-{}{}".format(wall_tag, letter_seq(win_i)), "WINDOW"
            counts["windows"] += 1
        else:
            continue
        set_mark(e, name)
        set_comments(e, "{} | WALL={} | {} | {}".format(APP_ID, wall_id, kind, name))
        orecords.append({
            "id": name, "wall_number": wall_tag, "host_wall": wall_id,
            "type": kind, "element_id": eid_value(e.Id),
        })
    return counts


# ------------------------------------------------------------
# Rectangle helpers (drywall)
# ------------------------------------------------------------

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
    """v3-style rectangular subtraction. Used ONLY as a fallback for sheets that overlap more
    than one opening (rare). Returns up to 4 rectangles."""
    inter = rect_intersection(rect, cut)
    if not inter:
        return [rect]

    x0, y0, x1, y1 = rect
    ix0, iy0, ix1, iy1 = inter

    pieces = []
    if iy0 > y0:
        pieces.append((x0, y0, x1, iy0))
    if iy1 < y1:
        pieces.append((x0, iy1, x1, y1))
    if ix0 > x0:
        pieces.append((x0, iy0, ix0, iy1))
    if ix1 < x1:
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


def rect_area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def cut_sheet_single_opening(S, O):
    """Cut ONE opening O out of sheet S, keeping the result as a SINGLE connected piece wherever
    that is physically what happens (notch / L / hole). Returns a list of "shapes":
        ("rect", (x0,y0,x1,y1))              - a plain rectangle
        ("poly", [(x,y), ...])               - a single rectilinear polygon (notch or L)
        ("hole", outer_rect, hole_rect)      - rectangle with an interior rectangular hole
    A course that the opening spans full-height (or full-width) legitimately becomes two
    separate boards (left/right or top/bottom) - those ARE separate boards in the field."""
    inter = rect_intersection(S, O)
    if not inter:
        return [("rect", S)]

    sx0, sy0, sx1, sy1 = S
    ix0, iy0, ix1, iy1 = inter
    tol = 1e-4

    full_w = (ix0 <= sx0 + tol) and (ix1 >= sx1 - tol)
    full_h = (iy0 <= sy0 + tol) and (iy1 >= sy1 - tol)

    if full_w and full_h:
        return []                                   # sheet fully consumed by the opening

    if full_w:                                      # horizontal band removed -> top/bottom boards
        out = []
        if (iy0 - sy0) >= MIN_PIECE_HEIGHT_FT:
            out.append(("rect", (sx0, sy0, sx1, iy0)))
        if (sy1 - iy1) >= MIN_PIECE_HEIGHT_FT:
            out.append(("rect", (sx0, iy1, sx1, sy1)))
        return out

    if full_h:                                      # vertical band removed -> left/right boards
        out = []
        if (ix0 - sx0) >= MIN_PIECE_WIDTH_FT:
            out.append(("rect", (sx0, sy0, ix0, sy1)))
        if (sx1 - ix1) >= MIN_PIECE_WIDTH_FT:
            out.append(("rect", (ix1, sy0, sx1, sy1)))
        return out

    # Neither full: the opening bites a notch/corner/hole out of the sheet -> ONE piece.
    tL = ix0 <= sx0 + tol
    tR = ix1 >= sx1 - tol
    tB = iy0 <= sy0 + tol
    tT = iy1 >= sy1 - tol

    if not (tL or tR or tB or tT):                  # interior opening -> rectangle with a hole
        return [("hole", S, inter)]

    # Build the single rectilinear outer ring for the notch / L cases.
    if tB and tL:                                   # remove bottom-left corner -> L
        ring = [(ix1, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1), (sx0, iy1), (ix1, iy1)]
    elif tB and tR:                                 # remove bottom-right corner -> L
        ring = [(sx0, sy0), (ix0, sy0), (ix0, iy1), (sx1, iy1), (sx1, sy1), (sx0, sy1)]
    elif tT and tL:                                 # remove top-left corner -> L
        ring = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (ix1, sy1), (ix1, iy0), (sx0, iy0)]
    elif tT and tR:                                 # remove top-right corner -> L
        ring = [(sx0, sy0), (sx1, sy0), (sx1, iy0), (ix0, iy0), (ix0, sy1), (sx0, sy1)]
    elif tB:                                        # notch from the bottom edge
        ring = [(sx0, sy0), (ix0, sy0), (ix0, iy1), (ix1, iy1), (ix1, sy0),
                (sx1, sy0), (sx1, sy1), (sx0, sy1)]
    elif tT:                                        # notch from the top edge
        ring = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (ix1, sy1), (ix1, iy0),
                (ix0, iy0), (ix0, sy1), (sx0, sy1)]
    elif tL:                                        # notch from the left edge
        ring = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1), (sx0, iy1),
                (ix1, iy1), (ix1, iy0), (sx0, iy0)]
    else:                                           # tR: notch from the right edge
        ring = [(sx0, sy0), (sx1, sy0), (sx1, iy0), (ix0, iy0), (ix0, iy1),
                (sx1, iy1), (sx1, sy1), (sx0, sy1)]

    return [("poly", ring)]


def cut_sheet(S, opening_rects):
    """Cut all overlapping openings out of sheet S. 0 or 1 overlap uses the single-piece logic;
    2+ overlaps fall back to rectangular subtraction (documented, rare). Returns (shapes, multi)."""
    overlaps = [O for O in opening_rects if rect_intersection(S, O) is not None]
    if not overlaps:
        return [("rect", S)], False
    if len(overlaps) == 1:
        return cut_sheet_single_opening(S, overlaps[0]), False
    # Multiple openings on one sheet: cut them all out with a boolean difference so the board
    # stays a single connected piece (notches / L's / holes) rather than rectangles split at the
    # opening corners.
    return [("multicut", S, overlaps)], True


# ------------------------------------------------------------
# Geometry primitives
# ------------------------------------------------------------

def make_point(origin, u, z, x, y):
    return origin.Add(u.Multiply(x)).Add(z.Multiply(y))


def _extrude_loops(loops, extrude_dir, depth, material_id, gstyle_id):
    if material_id is not None:
        gs = gstyle_id if gstyle_id is not None else ElementId.InvalidElementId
        opts = SolidOptions(material_id, gs)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth, opts)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth)


def make_profile_solid(origin, ax, ay, points2d, extrude_dir, depth, material_id=None, gstyle_id=None):
    """Extrude an arbitrary closed polygon profile (used by framing). ax/ay map the two profile
    coords; tries both windings so the caller need not worry about loop orientation."""
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


def make_rect_solid(origin, u, z, normal, rect, depth, material_id=None, gstyle_id=None):
    x0, y0, x1, y1 = rect
    if (x1 - x0) < 0.001 or (y1 - y0) < 0.001 or depth <= 0:
        return None
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return make_planar_poly_solid(origin, u, z, normal, pts, depth, material_id, gstyle_id)


def make_planar_poly_solid(origin, u, z, normal, pts2d, depth, material_id=None, gstyle_id=None):
    """Extrude a single planar rectilinear polygon (given as (x,y) in the u/z plane) along the
    normal by depth. Dedupes coincident consecutive points; tries both windings."""
    clean = []
    for p in pts2d:
        if not clean or abs(clean[-1][0] - p[0]) > 1e-7 or abs(clean[-1][1] - p[1]) > 1e-7:
            clean.append(p)
    if len(clean) >= 2 and abs(clean[0][0] - clean[-1][0]) < 1e-7 and abs(clean[0][1] - clean[-1][1]) < 1e-7:
        clean = clean[:-1]
    if len(clean) < 3 or depth <= 0:
        return None

    verts = [make_point(origin, u, z, x, y) for (x, y) in clean]
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


def make_hole_solid(origin, u, z, normal, outer_rect, hole_rect, depth, material_id=None, gstyle_id=None):
    """Rectangle with an interior rectangular hole, via a real 3D boolean difference (the
    hang-over-then-cut-out operation). Returns the cut Solid, or None on failure."""
    outer = make_rect_solid(origin, u, z, normal, outer_rect, depth, material_id, gstyle_id)
    if outer is None:
        return None
    cutter_origin = origin.Add(normal.Multiply(-HOLE_MARGIN_FT))
    cutter = make_rect_solid(cutter_origin, u, z, normal, hole_rect, depth + 2.0 * HOLE_MARGIN_FT)
    if cutter is None:
        return outer
    try:
        return BooleanOperationsUtils.ExecuteBooleanOperation(
            outer, cutter, BooleanOperationsType.Difference)
    except:
        return outer          # keep the uncut board rather than losing it


def make_multicut_solid(origin, u, z, normal, sheet_rect, cut_rects, depth,
                        material_id=None, gstyle_id=None):
    """Sheet rectangle with MULTIPLE openings cut out via chained boolean differences, so the
    board stays a SINGLE connected piece (notches / L's / holes) instead of rectangles split at
    the opening corners. (A course an opening spans full-height may come back as one solid with
    two lumps; that rare case is the exception.) Returns the cut Solid, or None on failure."""
    solid = make_rect_solid(origin, u, z, normal, sheet_rect, depth, material_id, gstyle_id)
    if solid is None:
        return None
    cutter_origin = origin.Add(normal.Multiply(-HOLE_MARGIN_FT))
    for cr in cut_rects:
        inter = rect_intersection(sheet_rect, cr)
        if not inter:
            continue
        cutter = make_rect_solid(cutter_origin, u, z, normal, inter, depth + 2.0 * HOLE_MARGIN_FT)
        if cutter is None:
            continue
        try:
            solid = BooleanOperationsUtils.ExecuteBooleanOperation(
                solid, cutter, BooleanOperationsType.Difference)
        except:
            pass          # skip this cutter; keep the board built so far
    return solid


def make_tapered_board_solid(layer_origin, u, z, normal, rect, thickness,
                             material_id=None, gstyle_id=None):
    """Rectangular board whose ROOM-FACING side (the +normal end) recesses near its two long
    (top & bottom) horizontal edges - the factory taper that forms the taped valley between
    stacked courses. Built by extruding a (height x thickness) profile along the board LENGTH.
    Falls back to a flat box if the board is too short to hold the taper. Returns the Solid."""
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    if width < 0.001 or height < 0.001 or thickness <= 0:
        return None
    td = min(TAPER_DEPTH_FT, thickness * 0.9)
    tw = TAPER_WIDTH_FT
    if td <= 0 or tw <= 0 or height <= 2.0 * tw + 0.01:
        return make_rect_solid(layer_origin, u, z, normal, rect, thickness, material_id, gstyle_id)
    origin = make_point(layer_origin, u, z, x0, y0)
    # Profile in (h along z = height, d along normal = thickness). Back face d=0; room face d=thk
    # in the middle, recessing to (thk - td) at the very top and bottom edges over tw.
    profile = [(0.0, 0.0), (height, 0.0), (height, thickness - td),
               (height - tw, thickness), (tw, thickness), (0.0, thickness - td)]
    return make_profile_solid(origin, z, normal, profile, u, width, material_id, gstyle_id)


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
        set_mark(ds, name)          # nomenclature also on Mark: schedulable + taggable
        return ds
    except Exception as ex:
        warnings.append("DirectShape create failed for {}: {}".format(data_id, ex))
        return None


# ------------------------------------------------------------
# DirectShape appearance: colored subcategories + materials  (VERBATIM machinery)
# ------------------------------------------------------------

STYLE_SPECS = [
    ("STUD",     "ORIGIN Stud",         (150, 155, 165)),
    ("KINGSTUD", "ORIGIN King Stud",    (120, 140, 180)),
    ("JACK",     "ORIGIN Jack Stud",    (120, 170, 140)),
    ("CRIPPLE",  "ORIGIN Cripple Stud", (170, 170, 120)),
    ("TRACK",    "ORIGIN Track",        (90, 95, 105)),
    ("HEADER",   "ORIGIN Header",       (200, 140, 80)),
    ("SILL",     "ORIGIN Sill",         (200, 140, 80)),
    ("GWB",      "ORIGIN Drywall Base", (235, 228, 214)),   # base layer, warm off-white
    ("GWB2",     "ORIGIN Drywall Face", (222, 212, 190)),   # 2nd (face) layer, slightly darker
    ("SCREW",    "ORIGIN Screw",        (200, 60, 60)),     # fastener markers, red
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
    """Create/find a colored Generic Model subcategory + material per kind. Returns
    {kind: (material_id, graphics_style_id)}. Best-effort; on failure elements are uncolored."""
    styles = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
    except Exception as ex:
        warnings.append("Could not access Generic Model category for coloring: {}".format(ex))
        return styles

    created = []
    for kind, name, rgb in STYLE_SPECS:
        try:
            mat_id = get_or_create_material(name, rgb)
            get_or_create_subcategory(gm, name, mat_id, rgb)
            created.append((kind, name, mat_id))
        except Exception as ex:
            warnings.append("Coloring for {} failed: {}".format(kind, ex))

    try:
        doc.Regenerate()
    except:
        pass

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
        styles[kind] = (mat_id, gsid)
    return styles


# ------------------------------------------------------------
# Cleanup  (VERBATIM; scoped to the walls being processed)
# ------------------------------------------------------------

def ensure_outlet_rfa(warnings):
    """Create families\\TM_outlet_box.rfa AUTOMATICALLY when it does not exist yet, so outlets
    work without any manual setup step. One fixed-size box extrusion per TM model, each bound to
    a Yes/No visibility parameter; each type shows exactly one box. MUST run before the Dynamo
    transaction opens (family documents cannot be created while one is active)."""
    import os
    if os.path.exists(OUTLET_RFA_PATH):
        return True
    app = doc.Application
    template = None
    try:
        cands = []
        base = r"C:\ProgramData\Autodesk"
        for d in sorted(os.listdir(base), reverse=True):
            if d.startswith("RVT"):
                for lang in ("English-Imperial", "English", "ENU"):
                    for nm in ("Generic Model.rft", "Metric Generic Model.rft"):
                        p = os.path.join(base, d, "Family Templates", lang, nm)
                        if os.path.exists(p):
                            cands.append(p)
        try:
            fp = app.FamilyTemplatePath
            for nm in ("Generic Model.rft", "Metric Generic Model.rft"):
                q = os.path.join(fp, nm)
                if os.path.exists(q):
                    cands.insert(0, q)
        except Exception:
            pass
        template = cands[0] if cands else None
    except Exception as ex:
        warnings.append("Outlet family template scan failed: {}".format(ex))
    if template is None:
        warnings.append("No Generic Model.rft template found - outlets skipped "
                        "(run origin_outlet_family_setup.py with a manual template path)")
        return False
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass
    try:
        famdoc = app.NewFamilyDocument(template)
    except Exception as ex:
        warnings.append("NewFamilyDocument failed ({}) - outlets skipped".format(ex))
        return False
    try:
        t = Transaction(famdoc, "ORIGIN outlet box family")
        t.Start()
        try:
            # Electrical Fixture category: the outlet is its OWN class, separate from the
            # Generic Models drywall, so it selects/moves/filters independently.
            try:
                famdoc.OwnerFamily.FamilyCategory = famdoc.Settings.Categories.get_Item(
                    BuiltInCategory.OST_ElectricalFixtures)
            except Exception as cex:
                warnings.append("Outlet family category set failed ({}); staying Generic Model".format(cex))
            fm = famdoc.FamilyManager
            sk = SketchPlane.Create(famdoc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
            vis_params = []
            for name in sorted(OUTLET_MODELS.keys()):
                (w_mm, h_mm, d_mm) = OUTLET_MODELS[name]
                hx = (w_mm / 304.8) / 2.0
                hy = (d_mm / 304.8) / 2.0
                pts = [XYZ(-hx, -hy, 0), XYZ(hx, -hy, 0), XYZ(hx, hy, 0), XYZ(-hx, hy, 0)]
                arr = CurveArray()
                for i in range(4):
                    arr.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
                caa = CurveArrArray()
                caa.Append(arr)
                ext = famdoc.FamilyCreate.NewExtrusion(True, caa, sk, h_mm / 304.8)
                fpar = fm.AddParameter("Show {}".format(name), GroupTypeId.Visibility,
                                       SpecTypeId.Boolean.YesNo, False)
                fm.AssociateElementParameterToFamilyParameter(
                    ext.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM), fpar)
                vis_params.append((name, fpar))
            for name in sorted(OUTLET_MODELS.keys()):
                fm.NewType(name)
                fm.CurrentType = [ft for ft in fm.Types if ft.Name == name][0]
                for (pn, fpar) in vis_params:
                    fm.Set(fpar, 1 if pn == name else 0)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        rdir = os.path.dirname(OUTLET_RFA_PATH)
        if not os.path.exists(rdir):
            os.makedirs(rdir)
        sao = SaveAsOptions()
        sao.OverwriteExistingFile = True
        famdoc.SaveAs(OUTLET_RFA_PATH, sao)
        return True
    except Exception as ex:
        warnings.append("Outlet family build failed ({}) - outlets skipped".format(ex))
        return False
    finally:
        try:
            famdoc.Close(False)
        except Exception:
            pass


def _bip_str(el, bip):
    """Parameter-based string read (reliable under PythonNet, unlike .Name on some types)."""
    try:
        p = el.get_Parameter(bip)
        if p:
            s = p.AsString()
            if s:
                return s
    except Exception:
        pass
    return None


def _el_name(el):
    """Element/type name that works in Dynamo CPython: direct .Name access on FamilySymbol /
    Family can throw under PythonNet, which made the outlet symbol lookup fail silently."""
    s = _bip_str(el, BuiltInParameter.SYMBOL_NAME_PARAM)
    if s:
        return s
    try:
        return Element.Name.__get__(el)
    except Exception:
        pass
    try:
        return el.Name
    except Exception:
        return None


def preload_outlet_family(warnings):
    """Load the outlet family into the PROJECT before the main Dynamo transaction opens, in its
    own short transaction (loading a family from inside the already-open transaction is the
    fragile path). No-op when the family is already in the project."""
    try:
        for f in FilteredElementCollector(doc).OfClass(Family):
            if _el_name(f) == OUTLET_FAMILY:
                return True
    except Exception:
        pass
    t = None
    try:
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass
        t = Transaction(doc, "ORIGIN load outlet family")
        t.Start()
        loaded = doc.LoadFamily(OUTLET_RFA_PATH)
        t.Commit()
        if not loaded:
            warnings.append("Outlet family preload: LoadFamily returned False")
        return bool(loaded)
    except Exception as ex:
        warnings.append("Outlet family preload failed: {}".format(ex))
        try:
            if t is not None:
                t.RollBack()
        except Exception:
            pass
        return False


_outlet_symbol_cache = [None, False]     # [symbol, resolved?] - one lookup per run


def outlet_symbol(warnings):
    """The TM_outlet_box family symbol (OUTLET_TYPE), loading families\\TM_outlet_box.rfa on
    demand. Returns None (with one warning) when the family is not available yet."""
    if _outlet_symbol_cache[1]:
        return _outlet_symbol_cache[0]
    _outlet_symbol_cache[1] = True

    def find():
        fallback = None
        for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
            try:
                fam = _bip_str(fs, BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if fam is None:
                    try:
                        fam = fs.FamilyName
                    except Exception:
                        fam = None
                if fam != OUTLET_FAMILY:
                    continue
                if fallback is None:
                    fallback = fs
                if _el_name(fs) == OUTLET_TYPE:
                    return fs
            except Exception:
                continue
        if fallback is not None:
            warnings.append("Outlet type '{}' not matched by name; using the family's first "
                            "type instead".format(OUTLET_TYPE))
        return fallback

    fs = find()
    if fs is None:
        try:
            import os
            if os.path.exists(OUTLET_RFA_PATH):
                doc.LoadFamily(OUTLET_RFA_PATH)
                fs = find()
        except Exception as ex:
            warnings.append("Outlet family load failed: {}".format(ex))
    if fs is None:
        warnings.append("Outlet family '{}' type '{}' not available - run "
                        "origin_outlet_family_setup.py once in a Dynamo Python node, then "
                        "re-run this graph.".format(OUTLET_FAMILY, OUTLET_TYPE))
    else:
        try:
            if not fs.IsActive:
                fs.Activate()
        except Exception:
            pass
    _outlet_symbol_cache[0] = fs
    return fs


def rects_overlap(a, b):
    """Axis-aligned rect overlap (x0, y0, x1, y1). Used by the outlet candidate filter - this
    helper existed only in the ceiling script; its absence here made every wall fail mid-run
    with NameError the moment the outlet family finally loaded (zero drywall, framing only)."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def find_wall_outlets(wall_id):
    """Existing tagged outlet instances hosted on this wall (survive re-runs by design)."""
    tag = "WALL={} | OUTLET".format(wall_id)
    out = []
    for fi in FilteredElementCollector(doc).OfClass(FamilyInstance):
        try:
            c = fi.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if c and tag in (c.AsString() or ""):
                out.append(fi)
        except Exception:
            continue
    return out


def outlet_cutouts_from_existing(wall_id, start, u, orientation, d_loc, width):
    """Cut rects for outlets already on this wall. Position, face and size are derived from each
    tagged instance, so when the user MOVES or type-swaps a box in Revit the recess hole follows
    it on the next run; a deleted box leaves no hole."""
    if OUTLET_STYLE != "recess":
        return []
    cuts = []
    wall_center = d_loc - width / 2.0
    for fi in find_wall_outlets(wall_id):
        try:
            p = fi.Location.Point
        except Exception:
            continue
        tname = None
        try:
            tname = _el_name(fi.Symbol)
        except Exception:
            pass
        (bw_mm, bh_mm, _bd_mm) = OUTLET_MODELS.get(tname, OUTLET_MODELS.get(OUTLET_TYPE, (103.0, 103.0, 38.0)))
        bw = bw_mm / 304.8
        bh = bh_mm / 304.8
        cx = (p.X - start.X) * u.X + (p.Y - start.Y) * u.Y
        zb = p.Z - start.Z
        s = (p.X - start.X) * orientation.X + (p.Y - start.Y) * orientation.Y
        side = "exterior" if s >= wall_center else "interior"
        cuts.append((side, (cx - bw / 2.0, zb, cx + bw / 2.0, zb + bh)))
    return cuts


def emit_outlet(wall, wall_id, wall_tag, start, u, orientation, d_loc, width, stud_xs,
                opening_rects, wall_height, run_lo, run_hi, outlet_records, warnings,
                env_centroid=None):
    """Place ONE outlet on this wall at a random interior stud / face / height. Style "recess"
    (the intrusion the user asked for): the face drywall board gets a socket-sized HOLE and the
    TM box sits INSIDE the wall, front plate at ~OUTLET_RECESS_FRAC of the wall depth (clamped
    so nothing reaches the far face). Style "box": the old surface-mounted look. The wall's
    Comments carry OUTLET_MARKER afterwards, so later runs leave the user's moves/deletes alone
    (the recess hole is re-derived from the existing instance every run and follows it).
    Returns (boxes_placed, [(face_side, cut_rect), ...])."""
    try:
        _bp = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
        if _bp and abs(_bp.AsDouble() or 0.0) > 0.5:
            return 0, []        # elevated band (beam/soffit wall) - no receptacle belongs here
    except Exception:
        pass
    cp = None
    try:
        cp = wall.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    except Exception:
        cp = None
    marked = False
    try:
        marked = cp is not None and OUTLET_MARKER in (cp.AsString() or "")
    except Exception:
        marked = False
    if marked and not OUTLET_FORCE_REGENERATE:
        # Requirement: exactly ONE cutout per wall - keep the first box, drop any extras.
        existing_all = find_wall_outlets(wall_id)
        if len(existing_all) > 1:
            for fi in existing_all[1:]:
                try:
                    doc.Delete(fi.Id)
                except Exception:
                    pass
            warnings.append("Wall {}: {} outlets found; trimmed to one".format(wall_id, len(existing_all)))
        # Migration: a preserved box sitting OUTSIDE the wall body is from the old
        # surface-mounted style, and a box whose DEPTH no longer matches OUTLET_RECESS_FRAC is
        # from an older depth setting (depth is script-managed; position/face/type are the
        # user's). Either way: delete it and fall through to place a fresh recessed one.
        stale = []
        if OUTLET_STYLE == "recess":
            for fi in find_wall_outlets(wall_id):
                try:
                    p0 = fi.Location.Point
                    s = (p0.X - start.X) * orientation.X + (p0.Y - start.Y) * orientation.Y
                except Exception:
                    continue
                if s > d_loc + 1e-3 or s < d_loc - width - 1e-3:
                    stale.append(fi.Id)
                    continue
                tname = None
                try:
                    tname = _el_name(fi.Symbol)
                except Exception:
                    pass
                (_wm, _hm, dmm) = OUTLET_MODELS.get(tname, OUTLET_MODELS.get(OUTLET_TYPE, (103.0, 103.0, 38.0)))
                bd0 = dmm / 304.8
                if s >= d_loc - width / 2.0:                    # exterior-side box
                    depth_now = d_loc - (s + bd0 / 2.0)
                else:                                           # interior-side box
                    depth_now = (s - bd0 / 2.0) - (d_loc - width)
                depth_want = min(OUTLET_RECESS_FRAC * width, width - bd0 - 0.02)
                if abs(depth_now - depth_want) > 0.04:
                    stale.append(fi.Id)
        if stale:
            for sid in stale:
                try:
                    doc.Delete(sid)
                except Exception:
                    pass
        else:
            # Preserved wall: no new box, but the recess hole must FOLLOW the existing box
            # (the user may have moved or type-swapped it since the last run).
            return 0, outlet_cutouts_from_existing(wall_id, start, u, orientation, d_loc, width)
    if marked and OUTLET_FORCE_REGENERATE:
        for sid in [fi.Id for fi in find_wall_outlets(wall_id)]:
            try:
                doc.Delete(sid)
            except Exception:
                pass
    fs = outlet_symbol(warnings)
    if fs is None:
        return 0, []
    (bw_mm, bh_mm, bd_mm) = OUTLET_MODELS.get(OUTLET_TYPE, (103.0, 103.0, 38.0))
    bw = bw_mm / 304.8
    bh = bh_mm / 304.8
    bd = bd_mm / 304.8
    # Candidate studs: interior field studs only - not jambs, not inside an opening span, box
    # fully inside the run and clear of every opening across the whole 12-18in height band.
    cands = []
    for sx in stud_xs:
        if is_jamb_line(sx, opening_rects) or is_interior_line(sx, opening_rects):
            continue
        x0 = sx + FLANGE_FT / 2.0            # box starts at the stud's flange face
        x1 = x0 + bw
        if x0 < run_lo + 0.1 or x1 > run_hi - 0.1:
            continue
        band = (x0 - 0.05, OUTLET_HEIGHT_MIN_FT - 0.05, x1 + 0.05,
                OUTLET_HEIGHT_MAX_FT + bh + 0.05)
        ok = True
        for orect in opening_rects:
            if rects_overlap(band, orect):
                ok = False
                break
        if ok:
            cands.append(sx)
    if not cands:
        warnings.append("Wall {}: no stud available for an outlet (openings/corners); skipped".format(wall_id))
        return 0, []
    sx = random.choice(cands)
    if OUTLET_FACES == "inner" and env_centroid is not None:
        # Face the environment: pick the side whose outward normal points toward the centroid
        # of the selected walls, so the robot (inside) can always see the outlet.
        mx = start.X + u.X * (run_lo + run_hi) / 2.0
        my = start.Y + u.Y * (run_lo + run_hi) / 2.0
        toward = (env_centroid[0] - mx) * orientation.X + (env_centroid[1] - my) * orientation.Y
        side = "exterior" if toward > 0.0 else "interior"
    else:
        side = random.choice(["interior", "exterior"])
    hbot = OUTLET_HEIGHT_MIN_FT + random.random() * (OUTLET_HEIGHT_MAX_FT - OUTLET_HEIGHT_MIN_FT)
    normal, face_off = face_normal_and_offset(orientation, d_loc, width, side)
    cx = sx + FLANGE_FT / 2.0 + bw / 2.0
    recess_depth = 0.0
    if OUTLET_STYLE == "recess":
        # INTRUSION: the box sits inside the wall, front plate at ~OUTLET_RECESS_FRAC of the
        # wall thickness (clamped so the box back never reaches the far face). The face board
        # gets a matching hole (returned as a cut rect), so you look INTO the wall and see the
        # box plate as the recess bottom. Nothing shows on the other side of the wall.
        recess_depth = min(OUTLET_RECESS_FRAC * width, width - bd - 0.02)
        if recess_depth < 0.0:
            recess_depth = max(0.0, width - bd - 0.02)
        off_center = face_off - recess_depth - bd / 2.0
    else:
        # Surface-mounted: box center sits bd/2 OUTSIDE the finish plane, fully proud.
        off_center = face_off + bd / 2.0
    p = XYZ(start.X + u.X * cx + normal.X * off_center,
            start.Y + u.Y * cx + normal.Y * off_center,
            start.Z + hbot)
    try:
        from Autodesk.Revit.DB.Structure import StructuralType
        fi = doc.Create.NewFamilyInstance(p, fs, StructuralType.NonStructural)
        ang = math.atan2(u.Y, u.X)
        if abs(ang) > 1e-9:
            axis = Line.CreateBound(p, XYZ(p.X, p.Y, p.Z + 1.0))
            ElementTransformUtils.RotateElement(doc, fi.Id, axis, ang)
    except Exception as ex:
        warnings.append("Wall {}: outlet placement failed ({})".format(wall_id, ex))
        return 0, []
    oid = "EO-{}-001".format(wall_tag)
    comment = "{} | WALL={} | OUTLET | {} | {}".format(APP_ID, wall_id, oid, OUTLET_TYPE)
    try:
        mp = fi.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if mp:
            mp.Set(oid)
        cpi = fi.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if cpi:
            cpi.Set(comment)
    except Exception:
        pass
    if cp is not None:
        try:
            old = cp.AsString() or ""
            cp.Set((old + " " if old else "") + OUTLET_MARKER)
        except Exception:
            warnings.append("Wall {}: could not write the outlet marker (a re-run may add a second box)".format(wall_id))
    outlet_records.append({
        "outlet_id": oid, "wall_number": wall_tag, "host_wall": wall_id,
        "type": OUTLET_TYPE, "size_mm": list(OUTLET_MODELS.get(OUTLET_TYPE, ())),
        "stud_x_in": round(sx * 12.0, 2), "face": side,
        "height_to_bottom_in": round(hbot * 12.0, 2),
        "style": OUTLET_STYLE, "recess_depth_in": round(recess_depth * 12.0, 2),
        "world_xyz": [round(p.X, 3), round(p.Y, 3), round(p.Z, 3)],
    })
    cuts = []
    if OUTLET_STYLE == "recess":
        x0 = sx + FLANGE_FT / 2.0
        cuts.append((side, (x0, hbot, x0 + bw, hbot + bh)))
    return 1, cuts


def delete_previous(processed_ids, warnings, purge_all=False):
    """Delete previously generated Origin DirectShapes. Normally scoped to the walls being processed
    this run (matched by the host wall's ElementId token WALL=W<eid>). When purge_all=True, remove
    EVERY Origin element in the model regardless of wall - use this to clear orphans left when walls
    were recreated (new ElementIds) or an older build ran."""
    ids = List[ElementId]()
    wall_tokens = ["WALL=" + w + " " for w in processed_ids]

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

            if purge_all or (comment and any(tok in comment for tok in wall_tokens)):
                ids.Add(e.Id)
    except Exception as ex:
        warnings.append("Cleanup (DirectShape) failed: {}".format(ex))

    try:
        col = FilteredElementCollector(doc).OfCategory(
            BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()
        for e in col:
            try:
                pg = e.LookupParameter("Generated_By")
                if not (pg and pg.AsString() == APP_ID):
                    continue
                if purge_all:
                    ids.Add(e.Id)
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
# Export-isolation view (Phase 3 hook)
# ------------------------------------------------------------

def ensure_export_view(warnings):
    """Create (or reuse) a 3D view named EXPORT_VIEW_NAME with the base Walls/Doors/Windows
    categories hidden, so only the generated framing + drywall (Generic Models) is visible. The
    assembly sits flush inside the existing wall, so the base wall otherwise hides / z-fights with
    it. This is also the isolation view the Phase-3 USD/Isaac export will use. Best-effort: any
    failure is reported but never aborts generation. Returns a short status string."""
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
        # so the base wall (and doors/windows/floors/etc.) are absent when you export FROM this
        # view. Guarantees the old wall is not seen in the sim.
        try:
            gm_id = ElementId(BuiltInCategory.OST_GenericModel)
            ef_id = ElementId(BuiltInCategory.OST_ElectricalFixtures)   # outlets stay visible
            for cat in doc.Settings.Categories:
                try:
                    if cat.CategoryType != CategoryType.Model or cat.Id == gm_id or cat.Id == ef_id:
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
# Framing geometry helpers  (Phase 1, VERBATIM from v4)
# ------------------------------------------------------------

def stud_lines(run_lo, run_hi, opening_rects):
    """Stud x-positions across the assembly run [run_lo, run_hi]: 16" OC from run_lo, an end stud
    at run_hi, plus a stud line at every opening jamb. run_lo/run_hi are pulled in from the wall
    ends at corners so studs don't run past where the assembly stops."""
    xs = []
    x = run_lo
    while x <= run_hi + 0.001:
        xs.append(x)
        x += STUD_SPACING_FT
    if not xs:
        xs.append(run_lo)
    if abs(xs[-1] - run_hi) > 0.1:
        xs.append(run_hi)
    for (ox0, oy0, ox1, oy1) in opening_rects:
        xs.append(clamp(ox0, run_lo, run_hi))
        xs.append(clamp(ox1, run_lo, run_hi))
    return unique_sorted([clamp(v, run_lo, run_hi) for v in xs])


def board_bbox(shape):
    """Bounding rect (x0,y0,x1,y1) of any board shape, for screw placement."""
    if shape[0] == "poly":
        xs = [p[0] for p in shape[1]]
        ys = [p[1] for p in shape[1]]
        return (min(xs), min(ys), max(xs), max(ys))
    return shape[1]        # rect / hole / multicut all carry the outer/sheet rect first


def screw_points(bx, stud_xs, opening_rects):
    """Screw (x, y) columns along each stud line crossing board-bbox bx. Per USG/GA-216, every
    screw is set back at least SCREW_EDGE_SETBACK_FT from the board's edges and ends. A stud that
    lands on a board's left/right edge carries a BUTT JOINT (or wall end): its screw column is
    shifted INTO this board by the setback, so the screw sits beside the joint - never on it - and
    the neighboring board straddles the joint from its own side (a screw each side, as required).
    Interior (field) studs get a column on the stud line. Points inside openings are skipped."""
    x0, y0, x1, y1 = bx
    sb = SCREW_EDGE_SETBACK_FT
    tol = SCREW_EDGE_TOL_FT
    pts = []
    for sx in stud_xs:
        if sx < x0 - tol or sx > x1 + tol:
            continue
        if abs(sx - x0) <= tol:
            colx = x0 + sb          # left edge / butt joint -> set back into this board
        elif abs(sx - x1) <= tol:
            colx = x1 - sb          # right edge / butt joint -> set back into this board
        else:
            colx = sx               # field stud
        if colx <= x0 + 1e-3 or colx >= x1 - 1e-3:
            continue
        lo = y0 + sb
        hi = y1 - sb
        cand = []
        if hi < lo:
            cand.append((y0 + y1) / 2.0)      # board too short: one screw at mid-height
        else:
            v = lo
            while v <= hi + 1e-6:
                cand.append(v)
                v += SCREW_SPACING_FT
            if not cand or abs(cand[-1] - hi) > 1e-3:
                cand.append(hi)               # perimeter screw near the far edge, set back
        for cy in cand:
            inside = False
            for (ox0, oy0, ox1, oy1) in opening_rects:
                if ox0 - 0.01 < colx < ox1 + 0.01 and oy0 - 0.01 < cy < oy1 + 0.01:
                    inside = True
                    break
            if not inside:
                pts.append((colx, cy))
    return pts


def stud_segments(sx, wall_height, opening_rects):
    blocks = []
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if ox0 + 0.01 < sx < ox1 - 0.01:
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
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if abs(sx - ox0) <= tol or abs(sx - ox1) <= tol:
            return True
    return False


def is_interior_line(sx, opening_rects):
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if ox0 + 0.01 < sx < ox1 - 0.01:
            return True
    return False


def subtract_intervals(full_lo, full_hi, cuts):
    segments = [(full_lo, full_hi)]
    for (clo, chi) in cuts:
        new_segs = []
        for (lo, hi) in segments:
            if chi <= lo or clo >= hi:
                new_segs.append((lo, hi))
                continue
            if clo > lo:
                new_segs.append((lo, clo))
            if chi < hi:
                new_segs.append((chi, hi))
        segments = new_segs
    return segments


def ds_comment(wall_id, face_name, kind, eid):
    return "{} | WALL={} | {} | {} | {}".format(APP_ID, wall_id, face_name, kind, eid)


# {kind: (material_id, graphics_style_id)}; populated in the transaction.
styles = {}


def jamb_flip(sx, opening_rects, tol=0.02):
    """A jamb stud should present its WEB (closed back of the C) to the opening so the frame/trim
    bears on and fastens to solid steel. The C-profile's web is on the -u side by default (mouth
    opens toward +u), which is correct for a RIGHT jamb (opening on the -u side). For a LEFT jamb
    (opening on the +u side, i.e. sx coincides with an opening's ox0), the stud must be flipped so
    its web faces +u toward the opening. Returns True to flip. A stud that is a right jamb for any
    opening stays un-flipped (can't face two ways; the -u opening wins)."""
    left = False
    right = False
    for (ox0, oy0, ox1, oy1) in opening_rects:
        if abs(sx - ox1) <= tol:
            right = True
        if abs(sx - ox0) <= tol:
            left = True
    return left and not right


def emit_member(origin, ax, ay, extrude_dir, depth, profile, kind, wall_id, wall_tag,
                st_counter, warnings):
    """Build one framing member. It is named ST-<wall>-<n> from the flat per-wall framing counter
    st_counter (a 1-element list); the number is consumed only when the DirectShape is actually
    created, so names stay contiguous. The member's true type is passed on in the Comments (kind).
    Returns (created 1/0, name or None)."""
    if depth < MIN_SEG_FT:
        return 0, None
    mat_id, gs_id = styles.get(kind, (None, None))
    solid = make_profile_solid(origin, ax, ay, profile, extrude_dir, depth, mat_id, gs_id)
    if solid is None:
        return 0, None
    name = "ST-{}-{:03d}".format(wall_tag, st_counter[0] + 1)
    ds = create_directshape(solid, name, name, ds_comment(wall_id, "-", kind, name), warnings)
    if not ds:
        return 0, None
    st_counter[0] += 1
    return 1, name


def emit_framing(wall_id, wall_tag, st_counter, start, u, z, orientation, stud_inner_off,
                 track_inner_off, c_profile, u_profile, stud_depth, stud_xs, run_lo, run_hi,
                 wall_height, opening_rects, frecords, warnings):
    """Emit all Phase-1 framing across the assembly run [run_lo, run_hi] (pulled in from the wall
    ends at corners so it doesn't overlap a joined wall). stud_inner_off / track_inner_off are
    signed offsets from the Location Line to the interior face of the stud / track; c_profile /
    u_profile carry the through-wall depth. Every member is named ST-<wall>-<n> in one flat
    per-wall sequence (st_counter); its real type is preserved in the Member_Type record field.
    Appends a manifest record per member to frecords."""
    counts = {"studs": 0, "cripples": 0, "kings": 0, "jacks": 0,
              "tracks": 0, "headers": 0, "sills": 0}

    down = XYZ(0, 0, -1)
    depth_off = orientation.Multiply(stud_inner_off)
    track_off = orientation.Multiply(track_inner_off)
    u_neg = u.Multiply(-1.0)     # flange axis for flipped (left-jamb) studs: web faces the opening

    def rec(name, kind, profile, length_ft, grid_index):
        frecords.append({
            "id": name, "wall_number": wall_tag, "host_wall": wall_id,
            "member_type": kind, "function": kind,
            "profile": profile, "web_depth_in": round(stud_depth * 12.0, 3),
            "flange_in": round(FLANGE_FT * 12.0, 3), "lip_in": round(LIP_FT * 12.0, 3),
            "gauge_mils": int(round(MAT_T_FT * 12.0 * 1000.0)),
            "length_in": round(length_ft * 12.0, 3), "grid_index": grid_index,
            "install_order": len(frecords) + 1,
        })

    for si, sx in enumerate(stud_xs):
        jamb = is_jamb_line(sx, opening_rects)
        interior = is_interior_line(sx, opening_rects)
        flip = jamb and jamb_flip(sx, opening_rects)   # left-jamb studs turn their web to the opening
        for (sy0, sy1) in stud_segments(sx, wall_height, opening_rects):
            if (sy1 - sy0) < MIN_SEG_FT:
                continue
            if jamb:
                kind, key = "KINGSTUD", "kings"
            elif interior:
                kind, key = "CRIPPLE", "cripples"
            else:
                kind, key = "STUD", "studs"
            # Flipping the flange axis mirrors the C about sx, so shift the origin +F/2 (not -F/2)
            # to keep the stud centered on the stud line.
            su = (sx + FLANGE_FT / 2.0) if flip else (sx - FLANGE_FT / 2.0)
            flange_axis = u_neg if flip else u
            origin = start.Add(u.Multiply(su)).Add(depth_off).Add(z.Multiply(sy0))
            n, name = emit_member(origin, orientation, flange_axis, z, sy1 - sy0,
                                  c_profile, kind, wall_id, wall_tag, st_counter, warnings)
            counts[key] += n
            if n:
                rec(name, kind, "C", sy1 - sy0, si)

    door_cuts = [(ox0, ox1) for (ox0, oy0, ox1, oy1) in opening_rects if oy0 <= 0.05]
    for (x0, x1) in subtract_intervals(run_lo, run_hi, door_cuts):
        if (x1 - x0) < MIN_SEG_FT:
            continue
        origin = start.Add(u.Multiply(x0)).Add(track_off).Add(z.Multiply(0.0))
        n, name = emit_member(origin, orientation, z, u, x1 - x0,
                              u_profile, "TRACK", wall_id, wall_tag, st_counter, warnings)
        counts["tracks"] += n
        if n:
            rec(name, "TRACK", "U", x1 - x0, -1)

    ceil_cuts = [(ox0, ox1) for (ox0, oy0, ox1, oy1) in opening_rects if oy1 >= wall_height - 0.05]
    for (x0, x1) in subtract_intervals(run_lo, run_hi, ceil_cuts):
        if (x1 - x0) < MIN_SEG_FT:
            continue
        origin = start.Add(u.Multiply(x0)).Add(track_off).Add(z.Multiply(wall_height))
        n, name = emit_member(origin, orientation, down, u, x1 - x0,
                              u_profile, "TRACK", wall_id, wall_tag, st_counter, warnings)
        counts["tracks"] += n
        if n:
            rec(name, "TRACK", "U", x1 - x0, -1)

    for (ox0, oy0, ox1, oy1) in opening_rects:
        span = ox1 - ox0
        is_window = oy0 > 0.05

        if span >= MIN_SEG_FT:
            origin = start.Add(u.Multiply(ox0)).Add(depth_off).Add(z.Multiply(oy1))
            n, name = emit_member(origin, orientation, z, u, span,
                                  c_profile, "HEADER", wall_id, wall_tag, st_counter, warnings)
            counts["headers"] += n
            if n:
                rec(name, "HEADER", "C", span, -1)

        if is_window and span >= MIN_SEG_FT:
            origin = start.Add(u.Multiply(ox0)).Add(depth_off).Add(z.Multiply(oy0 - FLANGE_FT))
            n, name = emit_member(origin, orientation, z, u, span,
                                  c_profile, "SILL", wall_id, wall_tag, st_counter, warnings)
            counts["sills"] += n
            if n:
                rec(name, "SILL", "C", span, -1)

        jack_bottom = oy0 if is_window else 0.0
        jack_h = oy1 - jack_bottom
        if jack_h >= MIN_SEG_FT:
            jx_positions = [clamp(ox0 + FLANGE_FT, run_lo, run_hi),
                            clamp(ox1 - FLANGE_FT, run_lo, run_hi)]
            for jn, jx in enumerate(jx_positions):
                # jn == 0 is the left jamb jack (opening on its +u side) -> flip so the web faces
                # the opening; jn == 1 is the right jamb jack -> default orientation.
                jflip = (jn == 0)
                jsu = (jx + FLANGE_FT / 2.0) if jflip else (jx - FLANGE_FT / 2.0)
                jaxis = u_neg if jflip else u
                origin = start.Add(u.Multiply(jsu)).Add(depth_off).Add(z.Multiply(jack_bottom))
                n, name = emit_member(origin, orientation, jaxis, z, jack_h,
                                      c_profile, "JACK", wall_id, wall_tag, st_counter, warnings)
                counts["jacks"] += n
                if n:
                    rec(name, "JACK", "C", jack_h, -1)

    return counts


# ------------------------------------------------------------
# Drywall layout  (Phase 2, NEW)
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


def generate_courses(wall_height, v_start):
    """Horizontal course bands covering [0, wall_height]. Boundaries at v_start + k*PANEL_HEIGHT
    (v_start staggers courses between stacked layers). Returns [(cy0, cy1, row), ...]."""
    rows = []
    y = v_start
    while y > 0.0:
        y -= PANEL_HEIGHT_FT
    row = 0
    cy = y
    while cy < wall_height - 1e-4:
        cy0 = max(0.0, cy)
        cy1 = min(wall_height, cy + PANEL_HEIGHT_FT)
        if (cy1 - cy0) >= MIN_PIECE_HEIGHT_FT:
            rows.append((cy0, cy1, row))
        cy += PANEL_HEIGHT_FT
        row += 1
    return rows


def row_joint_xs(row_shift, wall_length):
    """Interior vertical butt-joint x-positions for a course laid with the given left shift."""
    xs = []
    x = -row_shift + PANEL_LENGTH_FT
    while x < wall_length - 1e-4:
        if x > 1e-4:
            xs.append(x)
        x += PANEL_LENGTH_FT
    return xs


def joints_conflict(xs, opening_rects, clear):
    for xj in xs:
        for (ox0, oy0, ox1, oy1) in opening_rects:
            if abs(xj - ox0) < clear or abs(xj - ox1) < clear:
                return True
    return False


def adjust_row_shift(row_shift, wall_length, opening_rects):
    """Nudge a course's left shift so no butt joint lands within JOINT_CLEAR_FT of an opening
    jamb (the 'joints toward mid-opening, never at corners' rule). Heuristic; if no nudge clears
    every jamb it returns the original shift."""
    if not AVOID_JOINTS_AT_JAMBS or not opening_rects:
        return row_shift, False
    if not joints_conflict(row_joint_xs(row_shift, wall_length), opening_rects, JOINT_CLEAR_FT):
        return row_shift, False
    for d in (JOINT_CLEAR_FT * 1.5, -JOINT_CLEAR_FT * 1.5, JOINT_CLEAR_FT * 3.0,
              -JOINT_CLEAR_FT * 3.0, PANEL_LENGTH_FT * 0.25, PANEL_LENGTH_FT * 0.5):
        cand = normalize_shift(row_shift + d)
        if not joints_conflict(row_joint_xs(cand, wall_length), opening_rects, JOINT_CLEAR_FT):
            return cand, True
    return row_shift, False


def layer_stack(rated):
    """Return [(thickness_ft, type_x_bool), ...] from bottom (against studs) outward."""
    if rated:
        return [(DRYWALL_THICKNESS_RATED_FT, True)] * DRYWALL_LAYERS_RATED
    return [(DRYWALL_THICKNESS_STD_FT, False)] * DRYWALL_LAYERS_STD


def board_comment(wall_id, face_name, board_id, li, t_ft, type_x, is_cut, tapered, waste_sf):
    return ("{} | WALL={} | {} | DRYWALL | {} | L{} | t={}in | typeX={} | cut={} | "
            "taper={} | waste={}sf").format(
        APP_ID, wall_id, face_name, board_id, li, round(t_ft * 12.0, 3),
        int(bool(type_x)), int(bool(is_cut)), int(bool(tapered)), round(waste_sf, 2))


def emit_board(layer_origin, u, z, normal, shape, thickness, kind, wall_id, wall_tag, face_name,
               face_letter, face_seq, li, type_x, is_cut, waste_sf, taper, warnings):
    """Build one drywall board (rect / poly / hole / multicut) as a colored DirectShape. When taper
    is True (the board sits in a full 4-ft course, so its top & bottom edges are factory edges) the
    two long horizontal edges get the factory taper - directly for a plain rectangle, and for an
    opening-notched board by intersecting a tapered full-course rectangle with the cut footprint so
    the SURVIVING top/bottom edges keep the taper. Named DP-<wall>-<n><face_letter> from the per-face
    counter face_seq; the number is consumed only on a successful create. Returns (1/0, board_id)."""
    mat_id, gs_id = styles.get(kind, (None, None))
    kind_tag, a, b = (shape[0], shape[1], shape[2] if len(shape) > 2 else None)

    if kind_tag == "rect":
        if taper:
            solid = make_tapered_board_solid(layer_origin, u, z, normal, a, thickness, mat_id, gs_id)
        else:
            solid = make_rect_solid(layer_origin, u, z, normal, a, thickness, mat_id, gs_id)
    elif kind_tag == "poly":
        solid = make_planar_poly_solid(layer_origin, u, z, normal, a, thickness, mat_id, gs_id)
    elif kind_tag == "hole":
        solid = make_hole_solid(layer_origin, u, z, normal, a, b, thickness, mat_id, gs_id)
    elif kind_tag == "multicut":
        solid = make_multicut_solid(layer_origin, u, z, normal, a, b, thickness, mat_id, gs_id)
    else:
        return 0, None
    if solid is None:
        return 0, None

    # Opening-notched board in a full course: rebuild it as a tapered full-course rectangle clipped
    # to the cut footprint, so the surviving factory top/bottom edges keep the taper (flat notched
    # solid above is the fallback if the boolean fails).
    if taper and kind_tag != "rect":
        bxr = board_bbox(shape)
        tap = make_tapered_board_solid(layer_origin, u, z, normal, bxr, thickness, mat_id, gs_id)
        if tap is not None:
            fo = layer_origin.Add(normal.Multiply(-HOLE_MARGIN_FT))
            fd = thickness + 2.0 * HOLE_MARGIN_FT           # over-thick so it envelops the taper in Z
            if kind_tag == "poly":
                foot = make_planar_poly_solid(fo, u, z, normal, a, fd)
            elif kind_tag == "hole":
                foot = make_hole_solid(fo, u, z, normal, a, b, fd)
            else:
                foot = make_multicut_solid(fo, u, z, normal, a, b, fd)
            if foot is not None:
                try:
                    cut = BooleanOperationsUtils.ExecuteBooleanOperation(
                        tap, foot, BooleanOperationsType.Intersect)
                    if cut is not None:
                        solid = cut
                except:
                    pass

    seq = face_seq.get(face_letter, 0) + 1
    board_id = "DP-{}-{:03d}{}".format(wall_tag, seq, face_letter)
    comment = board_comment(wall_id, face_name, board_id, li, thickness, type_x,
                            is_cut, taper, waste_sf)
    ds = create_directshape(solid, board_id, board_id, comment, warnings)
    if not ds:
        return 0, None
    face_seq[face_letter] = seq
    return 1, board_id


def emit_drywall(wall_id, wall_tag, start, u, z, true_orientation, d_loc, width, face_extents,
                 wall_length, wall_height, opening_rects, rated, stud_xs, install_ref, records,
                 screw_records, do_screws, split_positions, warnings, face_extra_cuts=None):
    """Generate layered, staggered drywall on both faces. Each face lays out over its OWN along-wall
    extent face_extents[side] = (lo, hi) so outside corners wrap and inside corners butt (see
    corner_face_extents). Openings are cut as single connected pieces. Places screws along the stud
    lines on the outermost layer. Boards are named DP-<wall>-<n><face> (per-face counter); screws
    SC-<wall>-<n> (flat per-wall). split_positions = along-wall lines where a partition butts in; a
    board is broken there so no panel spans two rooms. Returns a counts dict; install_ref mutable."""
    counts = {"boards": 0, "cut_boards": 0, "hole_boards": 0, "multi_boolean": 0,
              "nudged_rows": 0, "layers": 0, "screws": 0, "partition_splits": 0}
    face_seq = {}          # per-face board counter: {"A": n, "B": n} -> DP-<wall>-<n><face>
    screw_seq = [0]        # flat per-wall screw counter -> SC-<wall>-<n>

    layers = layer_stack(rated)
    outer_li = 0     # li == 0 is the room-facing layer (its outer surface = the finish face)
    full_sheet_area = PANEL_LENGTH_FT * PANEL_HEIGHT_FT

    for face_config in FACE_LAYOUTS:
        if not face_config.get("enabled", True):
            continue
        face_name = face_config["face_name"]
        face_letter = face_config.get("letter", "A")
        normal, face_offset = face_normal_and_offset(true_orientation, d_loc, width,
                                                      face_config["side"])
        origin_face = start.Add(normal.Multiply(face_offset))
        # This face's own along-wall extent (outside corners wrap past the end; inside corners butt).
        flo, fhi = face_extents.get(face_config["side"], (0.0, wall_length))
        # Split THIS face only where a partition is on this face's side (its outward normal points
        # toward the partition body). The other face is unaffected and follows its own layout.
        face_splits = unique_sorted([p for (p, sdx, sdy) in split_positions
                                     if (sdx * normal.X + sdy * normal.Y) > 1e-6])
        # Face-specific extra cutouts (outlet recess holes): cut ONLY into this face's boards.
        f_cuts = list(face_extra_cuts.get(face_config["side"], [])) if face_extra_cuts else []

        cum_before = 0.0     # thickness of layers already placed (closer to the finish face)
        for li, (t, type_x) in enumerate(layers):
            counts["layers"] += 1
            # Layer occupies [face - (cum_before + t), face - cum_before] along the outward
            # normal (i.e. stacked inward toward the studs). Extrude +normal by t from the inner
            # start so the outermost layer's face is flush with the wall finish face.
            layer_origin = origin_face.Add(normal.Multiply(-(cum_before + t)))
            kind = "GWB" if li == 0 else "GWB2"

            base_shift = face_config.get("base_edge_shift_ft", 0.0) + li * LAYER_H_STAGGER_FT
            odd_shift = face_config.get("odd_row_additional_shift_ft", 4.0)
            v_start = li * LAYER_V_STAGGER_FT

            for (cy0, cy1, row) in generate_courses(wall_height, v_start):
                row_shift = normalize_shift(base_shift + (odd_shift if row % 2 == 1 else 0.0))
                row_shift, nudged = adjust_row_shift(row_shift, fhi, opening_rects)
                if nudged:
                    counts["nudged_rows"] += 1

                x = flo - row_shift
                col = 0
                while x < fhi - 1e-4:
                    cell_x0 = max(flo, x)
                    cell_x1 = min(fhi, x + PANEL_LENGTH_FT)
                    x += PANEL_LENGTH_FT
                    col += 1
                    # Break the course cell at each partition junction ON THIS FACE so no board
                    # spans two rooms; the opposite face uses its own (possibly empty) split set.
                    subcells = split_interval(cell_x0, cell_x1, face_splits)
                    if len(subcells) > 1:
                        counts["partition_splits"] += len(subcells) - 1
                    for (raw_x0, raw_x1) in subcells:
                        # Apply the code gap by insetting the sheet on all sides.
                        g = CODE_GAP_FT / 2.0
                        sx0 = raw_x0 + g
                        sx1 = raw_x1 - g
                        sy0 = cy0 + g
                        sy1 = cy1 - g
                        if (sx1 - sx0) < MIN_PIECE_WIDTH_FT or (sy1 - sy0) < MIN_PIECE_HEIGHT_FT:
                            continue

                        sheet = (sx0, sy0, sx1, sy1)
                        # The framing opening_rects = insert bbox + OPENING_CLEARANCE (rough-opening
                        # gap). Pull the DRYWALL cut back IN so it returns to ~DRYWALL_OPENING_REVEAL
                        # from the insert instead of inheriting the full framing clearance (which left
                        # a ~7/8" gap around the window). Never inset past an opening's centre.
                        _inset = max(0.0, OPENING_CLEARANCE_FT - DRYWALL_OPENING_REVEAL_FT)
                        expanded = [(o[0] + _inset, o[1] + _inset, o[2] - _inset, o[3] - _inset)
                                    for o in opening_rects] + f_cuts
                        shapes, multi = cut_sheet(sheet, expanded)
                        if multi:
                            counts["multi_boolean"] += 1

                        # Waste = this piece's nominal area minus the area actually placed (cutouts).
                        placed_area = 0.0
                        for sh in shapes:
                            if sh[0] == "rect":
                                placed_area += rect_area(sh[1])
                            elif sh[0] == "poly":
                                placed_area += poly_area(sh[1])
                            elif sh[0] == "hole":
                                placed_area += rect_area(sh[1]) - rect_area(sh[2])
                            elif sh[0] == "multicut":
                                pa = rect_area(sh[1])
                                for cr in sh[2]:
                                    it = rect_intersection(sh[1], cr)
                                    if it:
                                        pa -= rect_area(it)
                                placed_area += max(0.0, pa)
                        sheet_waste = max(0.0, (sx1 - sx0) * (sy1 - sy0) - placed_area)

                        # A full-height course keeps its factory top & bottom (long) edges, so those
                        # taper. Partial courses (ripped to fit) and notched/opening boards do not.
                        full_course = abs((cy1 - cy0) - PANEL_HEIGHT_FT) < 0.02

                        piece_i = 0
                        for sh in shapes:
                            piece_i += 1
                            is_cut = not (sh[0] == "rect"
                                          and abs((sh[1][2] - sh[1][0]) - (PANEL_LENGTH_FT - CODE_GAP_FT)) < 0.02
                                          and abs((sh[1][3] - sh[1][1]) - (PANEL_HEIGHT_FT - CODE_GAP_FT)) < 0.02)
                            # Any board in a full 4-ft course tapers its top/bottom (factory) edges -
                            # including opening-notched boards (emit_board keeps the taper on the
                            # surviving edges). Partial (<4 ft) courses stay square.
                            board_tapered = TAPERED_LONG_EDGES and full_course
                            waste = sheet_waste if piece_i == 1 else 0.0
                            made, board_id = emit_board(layer_origin, u, z, normal, sh, t, kind,
                                                        wall_id, wall_tag, face_name, face_letter,
                                                        face_seq, li, type_x, is_cut, waste,
                                                        board_tapered, warnings)
                            counts["boards"] += made
                            if made:
                                install_ref[0] += 1
                                if sh[0] == "hole":
                                    counts["hole_boards"] += 1
                                elif is_cut:
                                    counts["cut_boards"] += 1
                                # Along-wall extent (local x from the wall start) + world XY of the two
                                # ends of the board footprint, for bleed diagnosis in the manifest.
                                bxr = board_bbox(sh)
                                wp0 = make_point(start, u, z, bxr[0], 0.0)
                                wp1 = make_point(start, u, z, bxr[2], 0.0)
                                records.append({
                                    "board_id": board_id, "wall_number": wall_tag, "host_wall": wall_id,
                                    "face": face_name, "layer": li, "type_x": bool(type_x),
                                    "thickness_in": round(t * 12.0, 3),
                                    "is_cut": bool(is_cut), "tapered": bool(board_tapered),
                                    "shape": sh[0], "install_order": install_ref[0],
                                    "waste_sf": round(waste, 2),
                                    "x_start_in": round(bxr[0] * 12.0, 1), "x_end_in": round(bxr[2] * 12.0, 1),
                                    "y_start_in": round(bxr[1] * 12.0, 1), "y_end_in": round(bxr[3] * 12.0, 1),
                                    "wx0": round(wp0.X, 3), "wy0": round(wp0.Y, 3),
                                    "wx1": round(wp1.X, 3), "wy1": round(wp1.Y, 3),
                                })

                                # Fasteners: screws along the stud lines on the room-facing surface,
                                # outermost layer only (keeps geometry light). Recorded as coordinates.
                                if do_screws and (li == outer_li or not SCREWS_OUTER_LAYER_ONLY):
                                    bx = board_bbox(sh)
                                    if bx is not None:
                                        # Head sits flush: mostly embedded in the board, protruding
                                        # only SCREW_HEAD_PROUD_FT past the room-facing surface.
                                        surf = layer_origin.Add(normal.Multiply(t))
                                        screw_origin = surf.Add(normal.Multiply(
                                            SCREW_HEAD_PROUD_FT - SCREW_MARKER_DEPTH_FT))
                                        half = SCREW_MARKER_SIZE_FT / 2.0
                                        smat, sgs = styles.get("SCREW", (None, None))
                                        for (spx, spy) in screw_points(bx, stud_xs, opening_rects + f_cuts):
                                            if counts["screws"] >= MAX_SCREWS_PER_WALL:
                                                break
                                            srect = (spx - half, spy - half, spx + half, spy + half)
                                            ssolid = make_rect_solid(screw_origin, u, z, normal, srect,
                                                                     SCREW_MARKER_DEPTH_FT, smat, sgs)
                                            if ssolid is None:
                                                continue
                                            sid = "SC-{}-{:03d}".format(wall_tag, screw_seq[0] + 1)
                                            sds = create_directshape(
                                                ssolid, sid, sid,
                                                ds_comment(wall_id, face_name, "SCREW", sid), warnings)
                                            if sds:
                                                screw_seq[0] += 1
                                                counts["screws"] += 1
                                                pt = make_point(surf, u, z, spx, spy)   # record at the surface
                                                screw_records.append({
                                                    "screw_id": sid, "board_id": board_id,
                                                    "wall_number": wall_tag, "host_wall": wall_id,
                                                    "face": face_name, "layer": li,
                                                    "x_in": round(spx * 12.0, 2), "y_in": round(spy * 12.0, 2),
                                                    "world_x": round(pt.X, 4), "world_y": round(pt.Y, 4),
                                                    "world_z": round(pt.Z, 4),
                                                    "spacing_in": round(SCREW_SPACING_FT * 12.0, 2),
                                                    "length_in": round(t * 12.0 + 0.625, 3),
                                                })

            cum_before += t

    return counts


# ============================================================
# MAIN
# ============================================================

result = {
    "app_id": APP_ID,
    "output_mode": "directshape",
    "phase": "1_framing+2_drywall",
    "generate_framing": GENERATE_FRAMING,
    "generate_drywall": GENERATE_DRYWALL,
    "deleted_previous": 0,
    "walls_requested": 0,
    "walls_processed": 0,
    "walls_skipped": [],
    "wall_numbers": {},                # {W<eid>: "001"} nomenclature number per processed wall
    "rated_walls": 0,
    # openings (existing doors/windows given hierarchical Marks WN-/DR-)
    "doors_named": 0,
    "windows_named": 0,
    "framing_stud_depth_in": 0.0,      # derived stud web depth (last wall processed)
    "wall_diagnostics": [],            # per-wall thickness accounting (see notes if mismatch)
    # framing
    "studs_created": 0,
    "cripples_created": 0,
    "kings_created": 0,
    "jacks_created": 0,
    "tracks_created": 0,
    "headers_created": 0,
    "sills_created": 0,
    # drywall
    "boards_created": 0,
    "cut_boards": 0,
    "hole_boards": 0,
    "drywall_layers": 0,
    "multi_opening_boolean_sheets": 0,
    "jamb_nudged_courses": 0,
    "partition_split_boards": 0,       # extra board joints added where a partition butts in
    "board_records": 0,
    # fasteners
    "screws_created": 0,
    # corners / manifest / view
    "corners_trimmed": 0,              # wall ends pulled back to butt a joined wall
    "corner_debug": [],                # per-wall pull-backs (find a bleeding wall by its Mark number)
    "framing_records": 0,
    "screw_records": 0,
    "opening_records": 0,
    "outlets_created": 0,              # TM outlet boxes placed this run (preserved walls add 0)
    "manifest_path": "",
    "export_view": "",                 # name/status of the base-wall-hidden isolation view
    "warnings": [],
    "notes": []
}
warnings = result["warnings"]

do_delete = as_bool(get_in(5), DELETE_PREVIOUS_ORIGIN_ASSEMBLY)
do_drywall = as_bool(get_in(6), GENERATE_DRYWALL)
force_rated_in = get_in(7)
do_screws = as_bool(get_in(8), GENERATE_SCREWS)
purge_all = as_bool(get_in(9), PURGE_ALL_ORIGIN_ELEMENTS)

walls = get_input_walls(warnings)
result["walls_requested"] = len(walls)

board_records = []
framing_records = []
screw_records = []
opening_records = []
opening_rect_records = []
outlet_records = []

if len(walls) == 0:
    OUT = "No walls found. Select one or more straight walls in Revit, then run Dynamo again."
else:
    # The outlet family file must exist before we open the transaction (family documents cannot
    # be created while one is active). Builds families\TM_outlet_box.rfa automatically on the
    # first run, so no manual setup step is needed.
    if GENERATE_OUTLETS:
        if ensure_outlet_rfa(warnings):
            preload_outlet_family(warnings)
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        processed_ids = set("W" + str(eid_value(w.Id)) for w in walls)
        if do_delete or purge_all:
            result["deleted_previous"] = delete_previous(processed_ids, warnings, purge_all)
            if purge_all:
                result["notes"].append(
                    "PURGE_ALL: removed every Origin assembly element in the model (not just the "
                    "processed walls) - clears orphans from recreated walls / older runs.")

        if COLOR_BY_TYPE:
            styles = setup_styles(warnings)     # reassigns the module global read by emitters

        # Assign each selected wall its stable nomenclature number (persisted to the wall Mark).
        wall_numbers = assign_wall_numbers(walls, warnings)

        # Precompute geometry for EVERY straight wall in the model once, for corner detection.
        # Neighbors a processed wall butts into may be outside the selection, so scan them all.
        corner_candidates = []
        if HANDLE_CORNERS:
            try:
                for _cw in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
                    _csg = get_wall_curve_data(_cw)
                    if _csg is not None:
                        corner_candidates.append((_cw, _csg, get_wall_width(_cw)))
            except Exception as _cex:
                warnings.append("Corner candidate scan failed (continuing): {}".format(_cex))

        z = XYZ.BasisZ

        # Centroid of the SELECTED walls = the robot's environment; OUTLET_FACES="inner" places
        # every outlet on the face looking toward it (never on the outside of the building).
        env_centroid = None
        if GENERATE_OUTLETS and OUTLET_FACES == "inner":
            _pts = []
            for _w in walls:
                _cd = get_wall_curve_data(_w)
                if _cd:
                    _pts.append(((_cd[0].X + _cd[1].X) / 2.0, (_cd[0].Y + _cd[1].Y) / 2.0))
            if _pts:
                env_centroid = (sum(p[0] for p in _pts) / len(_pts),
                                sum(p[1] for p in _pts) / len(_pts))
            if len(_pts) < 2:
                warnings.append("OUTLET_FACES='inner' with fewer than 2 selected walls: the "
                                "inner side is ambiguous; falling back may pick either face")

        for wall in walls:
            wall_id = "W" + str(eid_value(wall.Id))
            wall_tag = "{:03d}".format(wall_numbers.get(eid_value(wall.Id), 0))
            result["wall_numbers"][wall_id] = wall_tag
            try:
                curve_data = get_wall_curve_data(wall)
                if not curve_data:
                    result["walls_skipped"].append(wall_id + ": not a straight wall")
                    continue

                start, end, u, wall_length = curve_data
                # Respect the wall's Base Offset: the location line sits at the LEVEL, so an
                # elevated band (e.g. a 2 ft "beam"/soffit wall with Base Offset 8') was getting
                # its whole assembly generated at the floor, 8 ft below the real element
                # (user report 2026-07-17). Shift the vertical origin to the true base.
                base_off = 0.0
                try:
                    _bp = wall.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET)
                    if _bp:
                        base_off = _bp.AsDouble() or 0.0
                except Exception:
                    base_off = 0.0
                if abs(base_off) > 1e-6:
                    start = XYZ(start.X, start.Y, start.Z + base_off)
                    end = XYZ(end.X, end.Y, end.Z + base_off)
                orientation = safe_normalize(wall.Orientation)
                if orientation is None:
                    result["walls_skipped"].append(wall_id + ": cannot read Orientation")
                    continue

                wall_height = get_wall_height(wall)
                width = get_wall_width(wall)

                d_loc, core_center = wall_ref_geometry(wall, width, warnings)

                opening_rects = get_opening_rects(wall, start, u, wall_length, wall_height, warnings)
                if opening_rects:
                    opening_rect_records.append({
                        "wall_number": wall_tag, "host_wall": wall_id,
                        "rects_in": [[round(v * 12.0, 1) for v in r] for r in opening_rects],
                    })

                # Name the existing doors/windows hosted in this wall (WN-<wall><letter> /
                # DR-<wall><letter>) so their relationship to the wall is explicit.
                oc = name_openings(wall, wall_id, wall_tag, opening_records, warnings)
                result["doors_named"] += oc["doors"]
                result["windows_named"] += oc["windows"]

                if force_rated_in is not None:
                    rated = as_bool(force_rated_in, False)
                elif FORCE_FIRE_RATED is not None:
                    rated = bool(FORCE_FIRE_RATED)
                else:
                    rated = wall_is_fire_rated(wall, warnings)
                if rated:
                    result["rated_walls"] += 1

                # The whole assembly is CENTERED on the existing wall (symmetric, no offset to
                # either side): drywall sits flush inside each finish face, and the stud is
                # centered on the wall's center plane. Stud web depth = wall thickness - drywall on
                # both faces, so the stud butts the back of the drywall and framing + drywall
                # exactly fills the wall. Both framing and drywall reference this one center plane.
                half_w = width / 2.0
                wall_center_off = d_loc - half_w            # Location Line -> wall center, along +normal
                dw_per_face = sum(t for (t, _tx) in layer_stack(rated))
                if DERIVE_STUD_DEPTH_FROM_WALL:
                    stud_depth = width - 2.0 * dw_per_face
                    if stud_depth < MIN_STUD_DEPTH_FT:
                        warnings.append(
                            "Wall {}: derived stud depth {:.2f}in below minimum; clamped to "
                            "{:.2f}in (wall {:.2f}in, drywall {:.2f}in/side). Assembly will exceed "
                            "the wall - model the wall thicker or force non-rated.".format(
                                wall_id, stud_depth * 12.0, MIN_STUD_DEPTH_FT * 12.0,
                                width * 12.0, dw_per_face * 12.0))
                        stud_depth = MIN_STUD_DEPTH_FT
                else:
                    stud_depth = STUD_DEPTH_FT
                stud_inner_off = wall_center_off - stud_depth / 2.0   # stud centered on the wall
                track_inner_off = stud_inner_off - MAT_T_FT           # track wraps the stud
                c_profile, u_profile, track_depth = build_profiles(stud_depth)
                result["framing_stud_depth_in"] = round(stud_depth * 12.0, 3)

                # Per-wall thickness accounting so any mismatch is visible in the Watch output.
                ref_code = -1
                try:
                    _rp = wall.get_Parameter(BuiltInParameter.WALL_KEY_REF_PARAM)
                    if _rp:
                        ref_code = _rp.AsInteger()
                except:
                    pass
                assembly_total = 2.0 * dw_per_face + stud_depth
                result["wall_diagnostics"].append({
                    "wall_id": wall_id,
                    "wall_number": wall_tag,
                    "wall_width_in": round(width * 12.0, 3),
                    # location_line_ref: 0=Centerline 1=CoreCenter 2=FinishExt 3=FinishInt 4=CoreExt 5=CoreInt
                    "location_line_ref": ref_code,
                    "wall_center_off_from_location_in": round(wall_center_off * 12.0, 3),
                    "rated": bool(rated),
                    "drywall_per_face_in": round(dw_per_face * 12.0, 3),
                    "stud_depth_in": round(stud_depth * 12.0, 3),
                    "assembly_total_in": round(assembly_total * 12.0, 3),
                    "assembly_equals_wall": abs(assembly_total - width) < 1e-4,
                })

                # Corner handling: pull the assembly back at any end that meets a perpendicular
                # wall (joined OR merely touching) so it butts cleanly into it (no material poking
                # into the next room). run_lo/run_hi bound both framing and drywall; stud_xs is the
                # shared stud grid (also used for screws).
                du0, du1 = corner_pullbacks(wall, warnings, corner_candidates)
                run_lo = du0
                run_hi = wall_length - du1
                degenerate = False
                if run_hi - run_lo < MIN_SEG_FT:
                    run_lo, run_hi = 0.0, wall_length      # degenerate pull-back; use full length
                    degenerate = True
                if du0 > 1e-4:
                    result["corners_trimmed"] += 1
                if du1 > 1e-4:
                    result["corners_trimmed"] += 1
                # Diagnostics: which wall (by its Mark number) got how much pull-back. If a bleeding
                # wall shows end0/end1 = 0 here, its corner wasn't detected (widen CORNER_* / check
                # the wall is straight + non-parallel); if it shows a value but still bleeds, the
                # pull-back is too small.
                result["corner_debug"].append({
                    "wall": wall_tag, "host": wall_id,
                    "length_in": round(wall_length * 12.0, 1),
                    "pull_end0_in": round(du0 * 12.0, 2),
                    "pull_end1_in": round(du1 * 12.0, 2),
                    "run_lo_in": round(run_lo * 12.0, 1), "run_hi_in": round(run_hi * 12.0, 1),
                    "start_xy": [round(start.X, 3), round(start.Y, 3)],
                    "end_xy": [round(end.X, 3), round(end.Y, 3)],
                    "degenerate_reset": degenerate,
                })
                stud_xs = stud_lines(run_lo, run_hi, opening_rects)

                if GENERATE_FRAMING:
                    st_counter = [0]     # flat per-wall framing counter -> ST-<wall>-<n>
                    fc = emit_framing(wall_id, wall_tag, st_counter, start, u, z, orientation,
                                      stud_inner_off, track_inner_off, c_profile, u_profile,
                                      stud_depth, stud_xs, run_lo, run_hi, wall_height,
                                      opening_rects, framing_records, warnings)
                    result["studs_created"] += fc["studs"]
                    result["cripples_created"] += fc["cripples"]
                    result["kings_created"] += fc["kings"]
                    result["jacks_created"] += fc["jacks"]
                    result["tracks_created"] += fc["tracks"]
                    result["headers_created"] += fc["headers"]
                    result["sills_created"] += fc["sills"]

                outlet_cuts = {}
                if GENERATE_OUTLETS:
                    # The outlet step must NEVER take the wall's drywall down with it: any
                    # failure here is warned and the wall continues without an outlet.
                    try:
                        oc_made, oc_list = emit_outlet(
                            wall, wall_id, wall_tag, start, u, orientation, d_loc, width, stud_xs,
                            opening_rects, wall_height, run_lo, run_hi, outlet_records, warnings,
                            env_centroid)
                        result["outlets_created"] += oc_made
                        for (oside, orect) in oc_list:
                            outlet_cuts.setdefault(oside, []).append(orect)
                    except Exception as oex:
                        warnings.append("Wall {}: outlet step failed ({}); wall continues without an outlet".format(wall_id, oex))
                        outlet_cuts = {}

                if do_drywall:
                    install_ref = [0]
                    # Per-face drywall extents: OUTSIDE corners wrap to the arris, INSIDE corners
                    # butt (framing is butt-trimmed separately via corner_pullbacks). With corner
                    # trimming off, each face just runs the full wall length.
                    face_extents = corner_face_extents(wall, corner_candidates) if TRIM_DRYWALL_AT_CORNERS else None
                    if not face_extents:
                        face_extents = {"interior": (0.0, wall_length), "exterior": (0.0, wall_length)}
                    # Along-wall lines where a partition butts into this wall's mid-span; the drywall
                    # breaks a board there so no panel spans two rooms.
                    split_positions = partition_split_positions(wall, corner_candidates)
                    dc = emit_drywall(wall_id, wall_tag, start, u, z, orientation, d_loc, width,
                                      face_extents, wall_length, wall_height, opening_rects, rated,
                                      stud_xs, install_ref, board_records, screw_records,
                                      do_screws, split_positions, warnings, outlet_cuts)
                    result["boards_created"] += dc["boards"]
                    result["cut_boards"] += dc["cut_boards"]
                    result["hole_boards"] += dc["hole_boards"]
                    result["drywall_layers"] += dc["layers"]
                    result["multi_opening_boolean_sheets"] += dc["multi_boolean"]
                    result["jamb_nudged_courses"] += dc["nudged_rows"]
                    result["screws_created"] += dc["screws"]
                    result["partition_split_boards"] += dc["partition_splits"]

                result["walls_processed"] += 1

            except Exception as wall_ex:
                result["walls_skipped"].append(wall_id + ": error - " + str(wall_ex))
                warnings.append("Wall {} failed mid-processing: {}".format(wall_id, wall_ex))
                continue

        # Isolation view: hide the base wall so the generated assembly is visible on both faces.
        result["export_view"] = ensure_export_view(warnings)

    except Exception as ex:
        result["notes"].append("FATAL: " + str(ex))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    result["board_records"] = len(board_records)
    result["framing_records"] = len(framing_records)
    result["screw_records"] = len(screw_records)
    result["opening_records"] = len(opening_records)
    if result["multi_opening_boolean_sheets"] > 0:
        result["notes"].append(
            "{} sheet(s) overlapped >1 opening and were cut with a boolean difference "
            "(single connected board, no joints at opening corners).".format(
                result["multi_opening_boolean_sheets"]))

    # Assembly manifest JSON: sidecar with every element's properties, so metadata survives the
    # USD export regardless of exporter. Written after the transaction (file IO needs no txn).
    if WRITE_MANIFEST:
        manifest = {
            "app_id": APP_ID,
            "schema": "origin_wall_assembly_v4_phase2",
            "units": "world coords in feet; member/board dims in inches",
            "nomenclature": {
                "wall": "NNN (persisted to the wall Mark)",
                "drywall_panel": "DP-<wall>-<seq><face>  (face A/B; seq per face)",
                "framing_member": "ST-<wall>-<seq>  (type in member_type)",
                "screw": "SC-<wall>-<seq>",
                "window": "WN-<wall><letter>",
                "door": "DR-<wall><letter>",
                "outlet": "EO-<wall>-001  (TM box family instance; movable/deletable, preserved on re-runs)",
            },
            "summary": dict((k, result[k]) for k in (
                "walls_processed", "rated_walls", "studs_created", "cripples_created",
                "kings_created", "jacks_created", "tracks_created", "headers_created",
                "sills_created", "boards_created", "screws_created", "corners_trimmed",
                "doors_named", "windows_named")),
            "walls": result["wall_diagnostics"],
            "corner_debug": result["corner_debug"],
            "framing": framing_records,
            "boards": board_records,
            "screws": screw_records,
            "openings": opening_records,
            "opening_rects": opening_rect_records,
            "outlets": outlet_records,
            "warnings": warnings,
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

    if result["corners_trimmed"] > 0:
        result["notes"].append(
            "{} wall end(s) pulled back at corners to butt a joined wall (no double material). "
            "Verify corner fit in Revit; tiebreak = higher ElementId runs through.".format(
                result["corners_trimmed"]))
    OUT = result
