# origin_column_assembly_v1.py
# ============================================================
# ORIGIN drywall assembly - COLUMNS (Dynamo Python node, PythonNet3/CPython3)
#
# Every architectural + structural column gets a STUD WRAP on each face that is exposed to a
# room - the same assembly the wall generator builds, nothing different (user 2026-09-28):
#
#   * 3-5/8" lipped C studs at 16" OC between U tracks top and bottom, set OUTSIDE the column
#     (the column itself is never touched - its size, position and type stay exactly as modelled),
#   * 1/2" board over the studs, hung in 4 ft courses of <= 8 ft sheets, every butt joint on a
#     stud, odd courses staggered - the wall generator's own layout rules, copied verbatim below.
#
# A face (or a stretch of one) is NOT wrapped where a wall or another column sits flush against it
# or runs through it - that side is not in a room. On C9 column 390751 this gives the front and
# its two sides; the back, against wall 401103, is not wrapped (the wall's own board there is cut
# back - see below).
#
# Corners follow the wall convention: E/W faces run THROUGH the corner (framing past it by the
# stud depth, board by stud + board so it laps the N/S board's edge), N/S faces BUTT between them.
# Where a wrapped stretch ends against something that does not reach out far enough to hide the
# wrap's end (typically a wall on the adjacent face, flush with the column), a return board closes
# that end so no stud is left showing.
#
# The wrap stops at the underside of the ceiling over it, as walls do. The ceiling generator runs
# first and cuts its boards around the bare column only, so they would run on over the wrap (user
# report 2026-09-28); they are trimmed back to the wrap outline here, leaving the board's cut edge
# flush on the wrap's outer face.
# Unlike a wall, the FRAMING stops there too: a column wrap has nothing to reach in the plenum.
#
# Wall boards lying flat against a column face that a wall covers are cut back to the wrap's outer
# face, so the wall's panels stop where the column's panels meet them (user 2026-09-28, B5 K002 -
# this replaces the earlier "board behind the column stays"). The wall's framing stays.
#
# Walls: once the wrap is planned, every wall-generated stud / track / board (ORIGIN_ASSEMBLY_V4),
# and every generated ceiling board (ORIGIN_CEILING_V1), that intrudes into the column or its wrap is cut back to it, and a piece left wholly inside is
# removed - so a column standing in the middle of a wall run interrupts that wall's panels instead
# of being overlapped by them. Pieces that only TOUCH the column (flush) are left alone. This runs
# here, not in the wall/ceiling generators, because columns come after both in every run; re-running
# walls or ceilings alone puts the overlap back until columns run again.
#
# Conventions: DirectShapes (Generic Models, visible in the ORIGIN Assembly view); host tag K###
# persisted to the column's Mark; boards DP-<host>-<seq><face N/E/S/W>, framing ST-<host>-<seq>;
# comment "APP_ID | HOST=K<eid> | FACE_<f> | <kind> | <name>" is the cleanup key; own manifest.
#
# Limits: axis-aligned columns only (rotated by a multiple of 90 deg is fine) - an angled column is
# skipped with a warning. A wall counts as covering a face only if it spans at least half the
# column's height.
# ============================================================

import clr
import json

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# Offline tests exec this file with ORIGIN_COLUMN_OFFLINE set: only the pure planning functions
# are used, and nothing below touches a document.
OFFLINE = bool(globals().get("ORIGIN_COLUMN_OFFLINE"))

# ORIGIN pipeline: when the pipeline runner injects ORIGIN_TARGET_DOC, generate into that
# (background) document; with nothing injected this behaves exactly as before and uses the
# document open in the Revit UI.
_origin_target_doc = globals().get("ORIGIN_TARGET_DOC")
if OFFLINE:
    doc = None
else:
    doc = _origin_target_doc if _origin_target_doc is not None else DocumentManager.Instance.CurrentDBDocument

APP_ID = "ORIGIN_COLUMN_V1"
LEGACY_APP_IDS = ["ORIGIN_BEAMCOL_V1"]
WALL_APP_ID = "ORIGIN_ASSEMBLY_V4"
CEILING_APP_ID = "ORIGIN_CEILING_V1"

DELETE_PREVIOUS = True
CUT_WALLS_AT_COLUMNS = True       # trim wall pieces and ceiling boards out of the column + its wrap
CLIP_AGAINST_OTHERS = True        # trim column pieces out of any other pipeline geometry
CAP_AT_CEILING = True

MANIFEST_PATH = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\origin_column_manifest.json"

# --- the wall generator's own framing + board sizes (origin_wall_assembly_v4_phase2_*) ---------
IN_FT = 1.0 / 12.0
STUD_SPACING_FT = 16.0 * IN_FT          # 16 in. OC
STUD_DEPTH_FT = 3.625 * IN_FT           # nominal C-stud web depth - the wrap's framing depth
FLANGE_FT = 1.25 * IN_FT                # C-stud flange width
LIP_FT = 0.1875 * IN_FT                 # C-stud return lip
MAT_T_FT = 0.0451 * IN_FT               # steel material thickness (~18 ga)
TRACK_FLANGE_FT = 1.25 * IN_FT
MIN_SEG_FT = 0.25                       # skip framing pieces shorter than 3 in.
MIN_SAFE_SEGMENT_FT = 0.5
PANEL_LENGTH_FT = 8.0
PANEL_HEIGHT_FT = 4.0                   # sheets hung horizontally: 4 ft course height
DRYWALL_T_FT = 0.5 * IN_FT
MIN_PIECE_HEIGHT_FT = 0.25
ODD_ROW_SHIFT_FT = 4.0

# The wrap's framing zone is [0, STUD_DEPTH_FT] out from the column face. The track fills it
# exactly; the stud sits inside the track's U, so its web is two material thicknesses shallower.
WRAP_FRAME_FT = STUD_DEPTH_FT
WRAP_T_FT = WRAP_FRAME_FT + DRYWALL_T_FT

# --- coverage / ceiling ------------------------------------------------------------------------
TOUCH_TOL_FT = 0.1 * IN_FT              # "flush" = within 0.1 in
MIN_EXPOSED_FT = 1.0 * IN_FT            # an exposed stretch narrower than this is ignored
COVER_MIN_Z_FRAC = 0.5                  # a wall covers a face only if it spans >= half the column
CEILING_PROBE_OFFSET_FT = 0.75          # same as the wall generator
CEILING_MIN_DROP_FT = 0.25
CEILING_MIN_CAP_FT = 1.0
ANGLE_TOL_DEG = 0.5
WALL_BOARD_ZONE_FT = 2.0 * IN_FT        # a wall's board layers within this of a covered column face
BOARD_FLAT_TOL_FT = 1.5 * IN_FT         # a board is "flat against" a face if it is this thin along its normal

DRYWALL_STYLE_RGB = (235, 228, 214)
STYLE_SPECS = [                          # same names as the wall generator -> same colours
    ("STUD",  "ORIGIN Stud",         (150, 155, 165)),
    ("TRACK", "ORIGIN Track",        (90, 95, 105)),
    ("GWB",   "ORIGIN Drywall Base", DRYWALL_STYLE_RGB),
]

FACES = ("N", "E", "S", "W")
RUN_THROUGH = ("E", "W")                 # these wrap the corners; N/S butt between them

# (face, end) -> (adjacent face, its end) at that corner. end 0 = low along-coordinate.
CORNER_NEIGHBOUR = {
    ("E", 0): ("S", 1), ("E", 1): ("N", 1),
    ("W", 0): ("S", 0), ("W", 1): ("N", 0),
    ("N", 0): ("W", 1), ("N", 1): ("E", 1),
    ("S", 0): ("W", 0), ("S", 1): ("E", 0),
}


# ============================================================
# Pure planning - plain tuples, no Revit API (exercised offline)
# ============================================================

def face_geom(fp, f):
    """Plane coordinate, outward sign, normal axis index (0=x, 1=y) and along range of face f of
    footprint fp = (x0, y0, x1, y1). E/W faces run along y, N/S along x."""
    x0, y0, x1, y1 = fp
    return {"E": (x1, +1, 0, y0, y1), "W": (x0, -1, 0, y0, y1),
            "N": (y1, +1, 1, x0, x1), "S": (y0, -1, 1, x0, x1)}[f]


def to_box(fp, f, a0, a1, d0, d1, z0, z1):
    """World box (x0, y0, z0, x1, y1, z1) for along [a0, a1] x depth [d0, d1] (out from face f)."""
    plane, sign, ax, _, _ = face_geom(fp, f)
    n0, n1 = sorted((plane + sign * d0, plane + sign * d1))
    a0, a1 = sorted((a0, a1))
    if ax == 0:
        return (n0, a0, z0, n1, a1, z1)
    return (a0, n0, z0, a1, n1, z1)


def _z_covers(ob, z0, z1):
    return min(ob[5], z1) - max(ob[2], z0) >= COVER_MIN_Z_FRAC * (z1 - z0) - 1e-9


def _normal_along(fp, f, ob):
    """(nlo, nhi, alo, ahi) of an obstacle box in face f's normal/along coordinates."""
    _, _, ax, _, _ = face_geom(fp, f)
    if ax == 0:
        return ob[0], ob[3], ob[1], ob[4]
    return ob[1], ob[4], ob[0], ob[3]


def _outward_extent(fp, f, ob):
    """How far an obstacle reaches OUT from face f's plane, if it starts at (or behind) that plane
    - i.e. it is flush against or runs through the face. None when it does not touch the plane."""
    plane, sign, _, _, _ = face_geom(fp, f)
    nlo, nhi, _, _ = _normal_along(fp, f, ob)
    if sign > 0:
        if nlo <= plane + TOUCH_TOL_FT and nhi > plane + TOUCH_TOL_FT:
            return nhi - plane
    else:
        if nhi >= plane - TOUCH_TOL_FT and nlo < plane - TOUCH_TOL_FT:
            return plane - nlo
    return None


def subtract_intervals(lo, hi, cuts):
    segs = [(lo, hi)]
    for (c0, c1) in sorted(cuts):
        nxt = []
        for (s0, s1) in segs:
            if c1 <= s0 or c0 >= s1:
                nxt.append((s0, s1))
                continue
            if c0 > s0:
                nxt.append((s0, c0))
            if c1 < s1:
                nxt.append((c1, s1))
        segs = nxt
    return segs


def face_exposure(fp, z0, z1, f, obstacles):
    """Exposed along-intervals of face f and the ids covering the rest."""
    _, _, _, lo, hi = face_geom(fp, f)
    cuts, by = [], []
    for ob in obstacles:
        box = ob["box"]
        if not _z_covers(box, z0, z1):
            continue
        if _outward_extent(fp, f, box) is None:
            continue
        _, _, alo, ahi = _normal_along(fp, f, box)
        c0, c1 = max(lo, alo), min(hi, ahi)
        if c1 - c0 > TOUCH_TOL_FT:
            cuts.append((c0, c1))
            by.append(ob["id"])
    segs = [(a, b) for (a, b) in subtract_intervals(lo, hi, cuts) if b - a >= MIN_EXPOSED_FT]
    return segs, by


def end_cover_extent(fp, z0, z1, f, p, side, obstacles):
    """How far out (depth) something already closes the wrap's end at along = p. side -1 looks at
    along < p, +1 at along > p. 0 = nothing there."""
    probe0, probe1 = (p - DRYWALL_T_FT, p) if side < 0 else (p, p + DRYWALL_T_FT)
    best = 0.0
    for ob in obstacles:
        box = ob["box"]
        if not _z_covers(box, z0, z1):
            continue
        _, _, alo, ahi = _normal_along(fp, f, box)
        if min(ahi, probe1) - max(alo, probe0) < 0.5 * DRYWALL_T_FT:
            continue
        e = _outward_extent(fp, f, box)
        if e is None:
            # flush on the ADJACENT face only: occupies the along-range but starts at the plane
            plane, sign, _, _, _ = face_geom(fp, f)
            nlo, nhi, _, _ = _normal_along(fp, f, box)
            if sign > 0 and abs(nlo - plane) <= TOUCH_TOL_FT:
                e = nhi - plane
            elif sign < 0 and abs(nhi - plane) <= TOUCH_TOL_FT:
                e = plane - nlo
        if e is not None:
            best = max(best, e)
    return best


def unique_sorted(values, tolerance=0.01):
    out = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tolerance:
            out.append(v)
    return out


def stud_centres(ra, rb):
    """16" OC from ra plus an end stud at rb (stud_lines() of the wall generator), each held a half
    flange inside the run so no stud hangs past the wrap's end."""
    if rb - ra < FLANGE_FT:
        return []
    xs = []
    x = ra
    while x <= rb + 0.001:
        xs.append(x)
        x += STUD_SPACING_FT
    if abs(xs[-1] - rb) > 0.1:
        xs.append(rb)
    h = FLANGE_FT / 2.0
    return unique_sorted([min(max(v, ra + h), rb - h) for v in xs])


def normalize_shift(shift):
    s = float(shift or 0.0)
    while s < 0.0:
        s += PANEL_LENGTH_FT
    while s >= PANEL_LENGTH_FT:
        s -= PANEL_LENGTH_FT
    return s


def generate_courses(height, v_start=0.0):
    """Horizontal 4 ft course bands over [0, height] (wall generator, verbatim)."""
    rows = []
    y = v_start
    while y > 0.0:
        y -= PANEL_HEIGHT_FT
    row = 0
    cy = y
    while cy < height - 1e-4:
        cy0 = max(0.0, cy)
        cy1 = min(height, cy + PANEL_HEIGHT_FT)
        if (cy1 - cy0) >= MIN_PIECE_HEIGHT_FT:
            rows.append((cy0, cy1, row))
        cy += PANEL_HEIGHT_FT
        row += 1
    return rows


def course_cells_on_studs(flo, fhi, row_shift, stud_xs):
    """Board cells across one course whose every internal joint lands on a stud (wall generator,
    verbatim)."""
    if fhi - flo <= 1e-6:
        return [], 0
    studs = sorted(set(float(s) for s in (stud_xs or [])))
    cells = []
    off_stud = 0
    x = flo
    limit = x + PANEL_LENGTH_FT - (row_shift or 0.0)
    while True:
        if fhi - x <= PANEL_LENGTH_FT + 1e-6:
            cells.append((x, fhi))
            break
        reach = min(limit, x + PANEL_LENGTH_FT)
        usable = [s for s in studs if x + MIN_SAFE_SEGMENT_FT <= s <= reach + 1e-6]
        if usable:
            nxt = usable[-1]
        else:
            nxt = reach
            off_stud += 1
        if nxt <= x + 1e-6 or nxt >= fhi - 1e-6:
            cells.append((x, fhi))
            break
        cells.append((x, nxt))
        x = nxt
        limit = x + PANEL_LENGTH_FT
    return cells, off_stud


def plan_column(fp, z0, z1, obstacles, cap_fn=None):
    """Everything to build for one column, as plain data.

    fp = (x0, y0, x1, y1) footprint, z0/z1 its bottom/top. obstacles = [{"id", "box"}] for every
    wall and OTHER column nearby. cap_fn(face, a, b) -> ceiling underside z over that stretch, or
    None. Returns {"faces": {...}, "pieces": [...], "cutters": [...], "off_stud_joints": n}.

    Piece kinds: STUD {face, along, z0, z1}, TRACK {face, a, b, z, up}, GWB {face}. Every piece
    carries its world "box"; the Revit side builds the real profiles from the other fields."""
    s, T, t = WRAP_FRAME_FT, WRAP_T_FT, DRYWALL_T_FT
    faces = {}
    for f in FACES:
        segs, by = face_exposure(fp, z0, z1, f, obstacles)
        faces[f] = {"exposed": segs, "covered_by": sorted(set(by))}

    def exposed_at(f, end):
        _, _, _, lo, hi = face_geom(fp, f)
        p = lo if end == 0 else hi
        return any(abs((a if end == 0 else b) - p) <= TOUCH_TOL_FT for (a, b) in faces[f]["exposed"])

    pieces, cutters = [], []
    off_stud_total = 0
    for f in FACES:
        _, _, _, lo, hi = face_geom(fp, f)
        through = f in RUN_THROUGH
        runs = []
        for (a, b) in faces[f]["exposed"]:
            ext = {}
            for end, p in ((0, a), (1, b)):
                at_corner = abs(p - (lo if end == 0 else hi)) <= TOUCH_TOL_FT
                wraps = at_corner and exposed_at(*CORNER_NEIGHBOUR[(f, end)])
                if wraps:
                    ext[end] = (s if through else 0.0, T if through else s, None)
                else:
                    side = -1 if end == 0 else +1
                    e = end_cover_extent(fp, z0, z1, f, p, side, obstacles)
                    cap = (e, T) if e < T - TOUCH_TOL_FT else None
                    ext[end] = (0.0, 0.0, cap)
            ra, rb = a - ext[0][0], b + ext[1][0]
            ba, bb = a - ext[0][1], b + ext[1][1]

            ztop = z1
            if cap_fn is not None:
                cz = cap_fn(f, a, b)
                if (cz is not None and cz > z0 + CEILING_MIN_CAP_FT
                        and cz < z1 - CEILING_MIN_DROP_FT):
                    ztop = cz
            runs.append({"a": a, "b": b, "frame": (ra, rb), "board": (ba, bb), "z_top": ztop,
                         "end_caps": [ext[0][2], ext[1][2]]})

            # framing: studs inside U tracks, all within depth [0, s]
            studs = stud_centres(ra, rb)
            for sx in studs:
                if ztop - z0 < MIN_SEG_FT:
                    continue
                pieces.append({"kind": "STUD", "face": f, "along": sx, "z0": z0, "z1": ztop,
                               "box": to_box(fp, f, sx - FLANGE_FT / 2.0, sx + FLANGE_FT / 2.0,
                                             MAT_T_FT, s - MAT_T_FT, z0, ztop)})
            if rb - ra >= 1e-3:
                for (z, up) in ((z0, True), (ztop, False)):
                    zz0, zz1 = (z, z + TRACK_FLANGE_FT) if up else (z - TRACK_FLANGE_FT, z)
                    pieces.append({"kind": "TRACK", "face": f, "a": ra, "b": rb, "z": z,
                                   "up": up, "box": to_box(fp, f, ra, rb, 0.0, s, zz0, zz1)})

            # boards: the wall generator's course / cell layout over [ba, bb]
            for (cy0, cy1, row) in generate_courses(ztop - z0):
                shift = normalize_shift(ODD_ROW_SHIFT_FT if row % 2 == 1 else 0.0)
                cells, off = course_cells_on_studs(ba, bb, shift, studs)
                off_stud_total += off
                for (c0, c1) in cells:
                    pieces.append({"kind": "GWB", "face": f, "row": row,
                                   "box": to_box(fp, f, c0, c1, s, T, z0 + cy0, z0 + cy1)})
            # return boards closing an end the neighbour does not hide
            for end, capd in ((0, ext[0][2]), (1, ext[1][2])):
                if capd is None:
                    continue
                p = a if end == 0 else b
                a0, a1 = (p - t, p) if end == 0 else (p, p + t)
                for (cy0, cy1, row) in generate_courses(ztop - z0):
                    pieces.append({"kind": "GWB", "face": f, "row": row, "end_cap": True,
                                   "box": to_box(fp, f, a0, a1, capd[0], capd[1],
                                                 z0 + cy0, z0 + cy1)})
            # full column height, not ztop: the ceiling board over the wrap sits just above it
            cutters.append(to_box(fp, f, min(ba, ra), max(bb, rb), 0.0, T, z0, z1))
            for end, capd in ((0, ext[0][2]), (1, ext[1][2])):
                if capd is not None:
                    p = a if end == 0 else b
                    a0, a1 = (p - t, p) if end == 0 else (p, p + t)
                    cutters.append(to_box(fp, f, a0, a1, capd[0], capd[1], z0, z1))
        faces[f]["runs"] = runs
    cutters.append((fp[0], fp[1], z0, fp[2], fp[3], z1))

    # Wall boards stop where the column's panels meet them (user 2026-09-28, B5 K002): on a face a
    # wall sits flush against, that wall's BOARDS - only the ones lying flat against the face - are
    # cut from the column face out through the board layers, along the face and on past each
    # corner: by the wrap's thickness where the next face is wrapped, so the wall board ends flush
    # with the wrap's outer face, or by the board zone where the next face is a wall too, which
    # takes the wall's corner lap. Framing is left alone.
    board_cutters = []
    for f in FACES:
        if not faces[f]["covered_by"]:
            continue
        _, _, ax, lo, hi = face_geom(fp, f)
        ext = []
        for end in (0, 1):
            ext.append(T if exposed_at(*CORNER_NEIGHBOUR[(f, end)]) else WALL_BOARD_ZONE_FT)
        board_cutters.append({"face": f, "normal_axis": ax,
                              "box": to_box(fp, f, lo - ext[0], hi + ext[1], 0.0,
                                            WALL_BOARD_ZONE_FT, z0, z1)})
    return {"faces": faces, "pieces": pieces, "cutters": cutters,
            "board_cutters": board_cutters, "off_stud_joints": off_stud_total}


def box_overlap_volume(a, b):
    dx = min(a[3], b[3]) - max(a[0], b[0])
    dy = min(a[4], b[4]) - max(a[1], b[1])
    dz = min(a[5], b[5]) - max(a[2], b[2])
    if dx <= 0 or dy <= 0 or dz <= 0:
        return 0.0
    return dx * dy * dz


# ============================================================
# Revit side
# ============================================================

result = {
    "app_id": APP_ID,
    "columns_processed": 0,
    "boards_created": 0,
    "framing_created": 0,
    "wall_pieces_trimmed": 0,
    "wall_pieces_removed": 0,
    "deleted_previous": 0,
    "columns_unchanged": None,
    "skipped": [],
    "manifest_path": "",
    "warnings": [],
}
warnings = result["warnings"]
board_records = []
framing_records = []
column_records = []
styles = {}


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


def comment_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def mark_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
            elif isinstance(g, GeometryInstance):
                for h in g.GetInstanceGeometry():
                    if isinstance(h, Solid) and h.Volume > 1e-9:
                        out.append(h)
    except Exception:
        pass
    return out


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


def setup_styles():
    """{kind: (material_id, graphics_style_id)} using the wall generator's names, so column framing
    and boards read exactly like wall framing and boards."""
    out = {}
    try:
        gm = doc.Settings.Categories.get_Item(BuiltInCategory.OST_GenericModel)
        made = []
        for kind, name, rgb in STYLE_SPECS:
            mat_id = get_or_create_material(name, rgb)
            get_or_create_subcategory(gm, name, mat_id, rgb)
            made.append((kind, name, mat_id))
        try:
            doc.Regenerate()
        except Exception:
            pass
        subs = {}
        for sc in gm.SubCategories:
            subs[sc.Name] = sc
        for kind, name, mat_id in made:
            gsid = ElementId.InvalidElementId
            sub = subs.get(name)
            if sub is not None:
                gs = sub.GetGraphicsStyle(GraphicsStyleType.Projection)
                if gs:
                    gsid = gs.Id
            out[kind] = (mat_id, gsid)
    except Exception as ex:
        warnings.append("Style setup failed ({}); pieces stay uncoloured".format(ex))
    return out


def _extrude(loop_pts, extrude_dir, depth, kind):
    from System.Collections.Generic import List as NetList
    mat_id, gs_id = styles.get(kind, (None, None))
    for order in (loop_pts, list(reversed(loop_pts))):
        try:
            loop = CurveLoop()
            n = len(order)
            for i in range(n):
                loop.Append(Line.CreateBound(order[i], order[(i + 1) % n]))
            loops = NetList[CurveLoop]()
            loops.Add(loop)
            if mat_id is not None:
                opts = SolidOptions(mat_id, gs_id if gs_id is not None else ElementId.InvalidElementId)
                return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth, opts)
            return GeometryCreationUtilities.CreateExtrusionGeometry(loops, extrude_dir, depth)
        except Exception:
            continue
    return None


def box_solid(box, kind="GWB"):
    x0, y0, z0, x1, y1, z1 = box
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4 or z1 - z0 < 1e-4:
        return None
    pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
    return _extrude(pts, XYZ.BasisZ, z1 - z0, kind)


def build_profiles(stud_depth):
    """Lipped-C stud + U-track wrapping it (wall generator's build_profiles, verbatim)."""
    D, F, L, t = stud_depth, FLANGE_FT, LIP_FT, MAT_T_FT
    c = [(0, 0), (0, F), (L, F), (L, F - t), (t, F - t), (t, t),
         (D - t, t), (D - t, F - t), (D - L, F - t), (D - L, F), (D, F), (D, 0)]
    Dt = D + 2.0 * t
    Ht = TRACK_FLANGE_FT
    u = [(0, 0), (0, Ht), (t, Ht), (t, t), (Dt - t, t), (Dt - t, Ht), (Dt, Ht), (Dt, 0)]
    return c, u


C_PROFILE, U_PROFILE = build_profiles(WRAP_FRAME_FT - 2.0 * MAT_T_FT)


def face_axes(fp, f):
    """(world point fn(along, depth, z), normal XYZ, along XYZ) for face f."""
    plane, sign, ax, _, _ = face_geom(fp, f)
    if ax == 0:
        return (lambda a, d, z: XYZ(plane + sign * d, a, z)), XYZ(sign, 0, 0), XYZ.BasisY
    return (lambda a, d, z: XYZ(a, plane + sign * d, z)), XYZ(0, sign, 0), XYZ.BasisX


def profile_solid(origin, ax, ay, pts2d, extrude_dir, depth, kind):
    verts = [origin.Add(ax.Multiply(p)).Add(ay.Multiply(q)) for (p, q) in pts2d]
    return _extrude(verts, extrude_dir, depth, kind)


def piece_solid(fp, pc):
    kind = pc["kind"]
    if kind == "GWB":
        return box_solid(pc["box"], "GWB")
    at, normal, along = face_axes(fp, pc["face"])
    if kind == "STUD":
        origin = at(pc["along"] - FLANGE_FT / 2.0, MAT_T_FT, pc["z0"])
        return profile_solid(origin, normal, along, C_PROFILE, XYZ.BasisZ, pc["z1"] - pc["z0"], "STUD")
    if kind == "TRACK":
        origin = at(pc["a"], 0.0, pc["z"])
        ay = XYZ.BasisZ if pc["up"] else XYZ(0, 0, -1)
        return profile_solid(origin, normal, ay, U_PROFILE, along, pc["b"] - pc["a"], "TRACK")
    return None


def safe_trim(cut, other):
    """cut minus other, only where they really overlap (the wall generator's _safe_trim, compact).
    Returns (solid, status) with status trimmed / unchanged / would_erase / boolean_failed."""
    inter_vol, overlap = None, None
    for (p, q) in ((cut, other), (other, cut)):
        try:
            inter = BooleanOperationsUtils.ExecuteBooleanOperation(p, q, BooleanOperationsType.Intersect)
            inter_vol = inter.Volume if inter is not None else 0.0
            overlap = inter
            break
        except Exception:
            continue
    if inter_vol is not None and inter_vol <= 1e-7:
        return cut, "unchanged"
    diff = None
    for q in (other, overlap):
        if q is None:
            continue
        try:
            diff = BooleanOperationsUtils.ExecuteBooleanOperation(cut, q, BooleanOperationsType.Difference)
            break
        except Exception:
            diff = None
    if diff is None:
        return cut, ("boolean_failed" if inter_vol is None else "unchanged")
    if diff.Volume <= 1e-7:
        return cut, "would_erase"
    if diff.Volume >= cut.Volume - 1e-7:
        return cut, "unchanged"
    return diff, "trimmed"


def create_ds(solid, name, comment):
    try:
        ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
        ds.ApplicationId = APP_ID
        ds.ApplicationDataId = name
        ds.SetShape([solid])
        p = ds.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p:
            p.Set(comment)
        m = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if m:
            m.Set(name)
        try:
            ds.Name = name
        except Exception:
            pass
        return ds
    except Exception as ex:
        warnings.append("{}: DirectShape failed ({})".format(name, ex))
        return None


def set_mark(e, tag):
    try:
        m = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if m and not m.IsReadOnly:
            m.Set(tag)
    except Exception:
        pass


def delete_previous():
    n = 0
    tags = [APP_ID + " |"] + [t + " |" for t in LEGACY_APP_IDS]
    stale = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape):
        s = comment_of(ds)
        if any(s.startswith(t) for t in tags):
            stale.append(ds.Id)
    for sid in stale:
        try:
            doc.Delete(sid)
            n += 1
        except Exception:
            pass
    return n


def collect_ceilings():
    out = []
    if not CAP_AT_CEILING:
        return out
    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        try:
            cat = c.Category
            if cat is not None and cat.Name and "soffit" in cat.Name.lower():
                continue
        except Exception:
            pass
        sols = solids_of(c)
        box = el_bbox(c)
        if sols and box:
            out.append({"z": box[2], "box": box, "solids": sols})
    return out


def ceiling_z_at_point(px, py, ceilings):
    """Lowest ceiling underside whose real solid covers (px, py) - same probe as the walls."""
    best = None
    for cp in ceilings:
        box = cp["box"]
        if px < box[0] or px > box[3] or py < box[1] or py > box[4]:
            continue
        zc = cp["z"]
        if best is not None and zc >= best:
            continue
        probe = box_solid((px - 0.05, py - 0.05, zc + 0.01, px + 0.05, py + 0.05, zc + 0.05))
        if probe is None:
            continue
        for s in cp["solids"]:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(probe, s, BooleanOperationsType.Intersect)
            except Exception:
                continue
            if inter is not None and inter.Volume > 1e-9:
                best = zc
                break
    return best


def is_ceiling_board(cm):
    return cm.startswith(CEILING_APP_ID + " |") and "| DRYWALL |" in cm


def make_cap_fn(fp, ceilings):
    """Where the wrap stops: the underside of the ceiling over it - as the walls stop. The ceiling
    generator runs first and cuts its boards around the bare column only; cut_hosts() trims them
    back to the wrap outline, so the board's cut edge sits flush on the wrap's outer face."""
    def cap(f, a, b):
        if not ceilings:
            return None
        plane, sign, ax, _, _ = face_geom(fp, f)
        zs = []
        for frac in (0.25, 0.5, 0.75):
            al = a + (b - a) * frac
            n = plane + sign * CEILING_PROBE_OFFSET_FT
            px, py = (n, al) if ax == 0 else (al, n)
            z = ceiling_z_at_point(px, py, ceilings)
            if z is not None:
                zs.append(z)
        return min(zs) if zs else None
    return cap


def is_axis_aligned(e):
    try:
        import math
        bx = e.GetTransform().BasisX
        ang = math.degrees(math.atan2(bx.Y, bx.X)) % 90.0
        return ang < ANGLE_TOL_DEG or ang > 90.0 - ANGLE_TOL_DEG
    except Exception:
        return True


def collect_obstacles(cols):
    obs = []
    for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
        box = el_bbox(w)
        if box:
            obs.append({"id": "W{}".format(eid_value(w.Id)), "box": box})
    for c in cols:
        box = el_bbox(c)
        if box:
            obs.append({"id": "K{}".format(eid_value(c.Id)), "box": box})
    return obs


def pipeline_pieces(prefix_ok):
    """[(ds, comment, box)] for pipeline DirectShapes whose comment passes prefix_ok."""
    out = []
    for ds in FilteredElementCollector(doc).OfClass(DirectShape):
        cm = comment_of(ds)
        if not cm or not prefix_ok(cm):
            continue
        box = el_bbox(ds)
        if box is None:
            continue
        out.append((ds, cm, box))
    return out


def board_cut_applies(box, bc):
    """A wall board lies flat against the covered column face bc (thin along its normal) and
    reaches into bc's cut zone. Boards of a wall meeting the column END-ON are never flat."""
    ax = bc["normal_axis"]
    thick = box[3 + ax] - box[ax]
    return thick <= BOARD_FLAT_TOL_FT and box_overlap_volume(box, bc["box"]) > 1e-7


def cut_hosts(cutters_by_col, board_cutters=()):
    """Trim every wall-generated piece, and every generated ceiling BOARD, out of each column's
    footprint + wrap zone; and wall BOARDS lying flat against a covered column face back to the
    wrap's outer face (board_cutters). Ceiling furring sits above the board, clear of the wrap,
    and is left; so is wall framing behind a column."""
    touched = []
    all_cutters = [c for cutters in cutters_by_col for c in cutters]
    for (ds, cm, box) in pipeline_pieces(lambda cm: cm.startswith(WALL_APP_ID + " |") or is_ceiling_board(cm)):
        hits = [c for c in all_cutters if box_overlap_volume(box, c) > 1e-7]
        if cm.startswith(WALL_APP_ID + " |") and "| DRYWALL |" in cm:
            hits += [bc["box"] for bc in board_cutters if board_cut_applies(box, bc)]
        if not hits:
            continue
        sols = solids_of(ds)
        if not sols:
            continue
        mark = mark_of(ds)
        changed = False
        new = []
        for s in sols:
            cur = s
            gone = False
            for c in hits:
                cs = box_solid(c, "GWB")
                if cs is None:
                    continue
                cur2, st = safe_trim(cur, cs)
                if st == "trimmed":
                    cur, changed = cur2, True
                elif st == "would_erase":
                    gone = True
                    break
                elif st == "boolean_failed":
                    warnings.append("{}: boolean failed cutting it at a column".format(mark))
            if gone:
                changed = True
                continue
            new.append(cur)
        if not changed:
            continue
        if not new:
            try:
                doc.Delete(ds.Id)
                result["wall_pieces_removed"] += 1
                touched.append({"mark": mark, "action": "removed (wholly behind / inside a column)"})
            except Exception as ex:
                warnings.append("{}: could not remove ({})".format(mark, ex))
            continue
        try:
            ds.SetShape(new)
            result["wall_pieces_trimmed"] += 1
            touched.append({"mark": mark, "action": "trimmed at a column"})
        except Exception as ex:
            warnings.append("{}: SetShape after column cut failed ({})".format(mark, ex))
    return touched


def column_snapshot(cols):
    snap = {}
    for c in cols:
        box = el_bbox(c)
        try:
            tid = eid_value(c.GetTypeId())
        except Exception:
            tid = None
        snap[eid_value(c.Id)] = (tuple(round(v, 6) for v in box) if box else None, tid)
    return snap


def main():
    global styles
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        if DELETE_PREVIOUS:
            result["deleted_previous"] = delete_previous()
        styles = setup_styles()
        cols = []
        for bic in (BuiltInCategory.OST_Columns, BuiltInCategory.OST_StructuralColumns):
            try:
                cols.extend(list(FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType()))
            except Exception as ex:
                warnings.append("Column collection failed ({})".format(ex))
        before = column_snapshot(cols)
        obstacles = collect_obstacles(cols)
        ceilings = collect_ceilings()

        plans = []
        ki = 0
        for e in cols:
            ki += 1
            tag = "K{:03d}".format(ki)
            set_mark(e, tag)
            host = "K{}".format(eid_value(e.Id))
            bb = el_bbox(e)
            if bb is None:
                result["skipped"].append("{} ({}): no bounding box".format(tag, host))
                continue
            if not is_axis_aligned(e):
                result["skipped"].append("{} ({}): angled column - not wrapped".format(tag, host))
                continue
            x0, y0, z0, x1, y1, z1 = bb
            if min(x1 - x0, y1 - y0) < 0.05 or (z1 - z0) < 0.5:
                result["skipped"].append("{} ({}): degenerate body".format(tag, host))
                continue
            fp = (x0, y0, x1, y1)
            others = [o for o in obstacles if o["id"] != host]
            plan = plan_column(fp, z0, z1, others, make_cap_fn(fp, ceilings))
            plans.append((e, tag, host, fp, plan))

        if CUT_WALLS_AT_COLUMNS:
            result["walls_cut"] = cut_hosts([p[4]["cutters"] for p in plans],
                                           [bc for p in plans for bc in p[4]["board_cutters"]])
            try:
                doc.Regenerate()
            except Exception:
                pass

        others_solids = []
        if CLIP_AGAINST_OTHERS:
            for (ds, cm, box) in pipeline_pieces(lambda cm: not cm.startswith(APP_ID + " |")):
                for s in solids_of(ds):
                    others_solids.append((box, s))

        for (e, tag, host, fp, plan) in plans:
            made_b = made_f = 0
            seq_b = {}
            seq_f = [0]
            for pc in plan["pieces"]:
                solid = piece_solid(fp, pc)
                if solid is None:
                    continue
                clipped = False
                for (obox, osol) in others_solids:
                    if box_overlap_volume(pc["box"], obox) <= 1e-7:
                        continue
                    s2, st = safe_trim(solid, osol)
                    if st == "trimmed":
                        solid, clipped = s2, True
                    elif st == "would_erase":
                        solid = None
                        break
                if solid is None:
                    warnings.append("{}: a {} on face {} is fully inside existing pipeline geometry - omitted"
                                    .format(tag, pc["kind"], pc["face"]))
                    continue
                f = pc["face"]
                if pc["kind"] == "GWB":
                    n = seq_b.get(f, 0) + 1
                    name = "DP-{}-{:03d}{}".format(tag, n, f)
                    comment = "{} | HOST={} | FACE_{} | DRYWALL | {} | L0 | t={}in{}".format(
                        APP_ID, host, f, name, round(DRYWALL_T_FT * 12.0, 3),
                        " | END_RETURN" if pc.get("end_cap") else "")
                    if create_ds(solid, name, comment) is None:
                        continue
                    seq_b[f] = n
                    made_b += 1
                    board_records.append({"board_id": name, "host": tag, "host_eid": host, "face": f,
                                          "end_return": bool(pc.get("end_cap")), "clipped": clipped,
                                          "bbox_in": [round(v * 12.0, 2) for v in pc["box"]],
                                          "thickness_in": round(DRYWALL_T_FT * 12.0, 3)})
                else:
                    name = "ST-{}-{:03d}".format(tag, seq_f[0] + 1)
                    comment = "{} | HOST={} | FACE_{} | {} | {}".format(APP_ID, host, f, pc["kind"], name)
                    if create_ds(solid, name, comment) is None:
                        continue
                    seq_f[0] += 1
                    made_f += 1
                    framing_records.append({"id": name, "host": tag, "host_eid": host, "face": f,
                                            "member_type": pc["kind"], "clipped": clipped,
                                            "web_depth_in": round((WRAP_FRAME_FT - 2 * MAT_T_FT) * 12.0, 3),
                                            "bbox_in": [round(v * 12.0, 2) for v in pc["box"]]})
            if plan["off_stud_joints"]:
                warnings.append("{}: {} board joint(s) off a stud".format(tag, plan["off_stud_joints"]))
            if made_b or made_f:
                result["columns_processed"] += 1
            result["boards_created"] += made_b
            result["framing_created"] += made_f
            column_records.append({
                "tag": tag, "host_eid": host,
                "footprint_in": [round(v * 12.0, 2) for v in fp],
                "faces": dict((f, {"exposed_in": [[round(a * 12, 2), round(b * 12, 2)]
                                                  for (a, b) in plan["faces"][f]["exposed"]],
                                   "covered_by": plan["faces"][f]["covered_by"],
                                   "top_in": [round(r["z_top"] * 12, 2) for r in plan["faces"][f]["runs"]]})
                              for f in FACES),
                "boards": made_b, "framing": made_f})

        after = column_snapshot(cols)
        moved = [k for k in before if before[k] != after.get(k)]
        result["columns_unchanged"] = not moved
        if moved:
            warnings.append("Column geometry/type changed during the run: {}".format(moved))
    except Exception:
        import traceback
        warnings.append("FATAL: {}".format(traceback.format_exc()))
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    try:
        manifest = {
            "app_id": APP_ID,
            "nomenclature": {"column": "K###", "board": "DP-<host>-<seq><face N/E/S/W>",
                             "framing": "ST-<host>-<seq>"},
            "summary": dict((k, result[k]) for k in ("columns_processed", "boards_created",
                                                     "framing_created", "wall_pieces_trimmed",
                                                     "wall_pieces_removed", "deleted_previous",
                                                     "columns_unchanged")),
            "columns": column_records,
            "boards": board_records,
            "framing": framing_records,
            "walls_cut": result.get("walls_cut", []),
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


if not OFFLINE:
    main()

OUT = result
