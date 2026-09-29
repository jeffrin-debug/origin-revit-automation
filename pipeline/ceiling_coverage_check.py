# ceiling_coverage_check.py - after every panels run, prove each ceiling is fully boarded.
#
# The ceiling generator has several places where it throws away a piece it thinks is too small
# (MIN_PIECE_* 3 in). Each one that fires inside a room leaves an uncovered hole under the
# furring, and nothing downstream ever noticed: the user found them by eye, one env at a time
# (2026-09-28 - C9 C394087: a 48 x 2.5in strip at a wall corner; 2C C001: a 0.87in last course
# along wall 020). Both causes are fixed in the generator, but the next env will bring the next
# cause. So this is the net under all of them: read-only, it samples every ceiling on a grid and
# reports any point that no room-facing (L0) board covers.
#
# Points are left out where a ceiling is bare BY DESIGN - the generator cuts around these:
#   * walls that reach the ceiling, columns and their stud wraps (ORIGIN_COLUMN_V1), beams,
#   * fixtures hosted on the ceiling (lights, diffusers),
#   * soffit ceilings (their own board flow, DP-S###) are not checked at all.
#
# Result (report["ceiling_coverage"]): ok, ceilings_checked, gaps [{ceiling, mark, points,
# approx_sq_in, bbox_in, near}], unboarded [ceilings with no L0 board at all]. A gap is a
# connected patch of uncovered grid points. Nothing is changed in the model.

import traceback

CFG = {
    "GRID_IN": 1.0,            # sample spacing; a gap narrower than this can slip between samples
    "OBSTACLE_PAD_IN": 0.12,   # boards are cut this close to walls / columns
    "FIXTURE_PAD_IN": 1.0,     # the generator's FIXTURE_CLEARANCE is 0.6in
    "MAX_GAPS": 50,
}


# ------------------------------------------------------------------ pure geometry (offline)

def point_in_poly(x, y, poly):
    c = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
                c = not c
        j = i
    return c


def inside_loops(x, y, loops):
    """Even-odd over every loop, so holes in a face count as outside."""
    k = 0
    for lp in loops:
        if point_in_poly(x, y, lp):
            k += 1
    return k % 2 == 1


def in_any_box(x, y, boxes, pad):
    for b in boxes:
        if b[0] - pad <= x <= b[2] + pad and b[1] - pad <= y <= b[3] + pad:
            return True
    return False


def scan(outline, boards, obstacles, bbox, grid, pad):
    """Uncovered grid points of one ceiling as (i, j) indices + their plan coordinates.
    outline = loops of the ceiling underside; boards = [(plan bbox, loops)]; obstacles = plan
    boxes to skip; bbox = (x0, y0, x1, y1) of the ceiling."""
    x0, y0, x1, y1 = bbox
    miss = {}
    i = 0
    x = x0 + grid / 2.0
    while x < x1:
        j = 0
        y = y0 + grid / 2.0
        while y < y1:
            if inside_loops(x, y, outline) and not in_any_box(x, y, obstacles, pad):
                covered = False
                for (bb, loops) in boards:
                    if bb[0] - 1e-6 <= x <= bb[2] + 1e-6 and bb[1] - 1e-6 <= y <= bb[3] + 1e-6 \
                            and inside_loops(x, y, loops):
                        covered = True
                        break
                if not covered:
                    miss[(i, j)] = (x, y)
            y += grid
            j += 1
        x += grid
        i += 1
    return miss


def patches(miss):
    """Group uncovered grid points into 4-connected patches: [[(x, y), ...], ...], biggest first."""
    seen = set()
    out = []
    for start in miss:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        pts = []
        while stack:
            (i, j) = stack.pop()
            pts.append(miss[(i, j)])
            for nb in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if nb in miss and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        out.append(pts)
    out.sort(key=lambda p: -len(p))
    return out


# ------------------------------------------------------------------ Revit side

def _revit():
    import clr
    clr.AddReference('RevitAPI')
    from Autodesk.Revit import DB
    return DB


def _par(DB, e, bip):
    try:
        p = e.get_Parameter(bip)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def _bottom_loops(DB, e):
    loops = []
    try:
        geo = e.get_Geometry(DB.Options())
    except Exception:
        return loops
    if geo is None:
        return loops
    for s in geo:
        if not isinstance(s, DB.Solid) or s.Volume <= 1e-9:
            continue
        for f in s.Faces:
            try:
                if f.ComputeNormal(DB.UV(0.5, 0.5)).Z > -0.9:
                    continue
                for cl in f.GetEdgesAsCurveLoops():
                    pts = []
                    for cv in cl:
                        for p in list(cv.Tessellate())[:-1]:
                            pts.append((p.X, p.Y))
                    if len(pts) >= 3:
                        loops.append(pts)
            except Exception:
                continue
    return loops


def _box(e):
    try:
        b = e.get_BoundingBox(None)
        if b is None:
            return None
        return (b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z)
    except Exception:
        return None


def _is_soffit(DB, doc, c):
    try:
        if c.Category is not None and "soffit" in (c.Category.Name or "").lower():
            return True
    except Exception:
        pass
    try:
        t = doc.GetElement(c.GetTypeId())
        for nm in (DB.Element.Name.GetValue(t), getattr(t, "FamilyName", "")):
            if nm and "soffit" in nm.lower():
                return True
    except Exception:
        pass
    return False


def run(doc, cfg=None):
    cfg = dict(CFG, **(cfg or {}))
    DB = _revit()
    grid = cfg["GRID_IN"] / 12.0
    pad = cfg["OBSTACLE_PAD_IN"] / 12.0
    fpad = cfg["FIXTURE_PAD_IN"] / 12.0
    res = {"ok": True, "grid_in": cfg["GRID_IN"], "ceilings_checked": 0, "gaps": [],
           "unboarded": [], "skipped_soffits": []}
    try:
        # bare-by-design areas, as 3D boxes (filtered per ceiling by height)
        solid_obs = []
        for w in DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType():
            b = _box(w)
            if b:
                solid_obs.append(("W" + str(w.Id.Value) + " " + _par(DB, w, DB.BuiltInParameter.ALL_MODEL_MARK), b))
        for bic in (DB.BuiltInCategory.OST_Columns, DB.BuiltInCategory.OST_StructuralColumns,
                    DB.BuiltInCategory.OST_StructuralFraming):
            for e in DB.FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType():
                b = _box(e)
                if b:
                    solid_obs.append(("K" + str(e.Id.Value), b))
        boards, fixtures = {}, {}
        for ds in DB.FilteredElementCollector(doc).OfClass(DB.DirectShape):
            cm = _par(DB, ds, DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if cm.startswith("ORIGIN_COLUMN_V1 |"):
                b = _box(ds)
                if b:
                    solid_obs.append(("wrap", b))
            elif cm.startswith("ORIGIN_CEILING_V1 |") and "| DRYWALL |" in cm and "| L0 |" in cm \
                    and "CEILING=" in cm:
                host = cm.split("CEILING=")[1].split(" ")[0]
                b = _box(ds)
                if b:
                    boards.setdefault(host, []).append(((b[0], b[1], b[3], b[4]), _bottom_loops(DB, ds)))
        for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
            try:
                h = fi.Host
            except Exception:
                h = None
            if h is not None and isinstance(h, DB.Ceiling):
                b = _box(fi)
                if b:
                    fixtures.setdefault(h.Id.Value, []).append((b[0], b[1], b[3], b[4]))

        for c in DB.FilteredElementCollector(doc).OfClass(DB.Ceiling).WhereElementIsNotElementType():
            host = "C" + str(c.Id.Value)
            mark = _par(DB, c, DB.BuiltInParameter.ALL_MODEL_MARK)
            if _is_soffit(DB, doc, c):
                res["skipped_soffits"].append(host)
                continue
            cb = _box(c)
            outline = _bottom_loops(DB, c)
            if cb is None or not outline:
                continue
            res["ceilings_checked"] += 1
            bl = boards.get(host, [])
            if not bl:
                res["unboarded"].append({"ceiling": host, "mark": mark})
                res["ok"] = False
                continue
            cz = cb[2]
            near = [(n, b) for (n, b) in solid_obs
                    if b[2] <= cz + 0.02 and b[5] >= cz - 0.02
                    and not (b[3] < cb[0] or b[0] > cb[3] or b[4] < cb[1] or b[1] > cb[4])]
            obs = [(b[0], b[1], b[3], b[4]) for (n, b) in near]
            miss = scan(outline, bl, obs, (cb[0], cb[1], cb[3], cb[4]), grid, pad)
            fx = fixtures.get(c.Id.Value, [])
            if fx:
                miss = dict((k, p) for k, p in miss.items() if not in_any_box(p[0], p[1], fx, fpad))
            for pts in patches(miss):
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                bx = (min(xs), min(ys), max(xs), max(ys))
                walls = sorted(set(n for (n, b) in near if n.startswith("W") and
                                   b[0] - 0.5 <= bx[2] and b[3] + 0.5 >= bx[0] and
                                   b[1] - 0.5 <= bx[3] and b[4] + 0.5 >= bx[1]))
                res["gaps"].append({
                    "ceiling": host, "mark": mark, "points": len(pts),
                    "approx_sq_in": round(len(pts) * cfg["GRID_IN"] ** 2, 1),
                    "bbox_in": [round(v * 12.0, 2) for v in bx],
                    "near": [w.strip() for w in walls][:4]})
            if miss:
                res["ok"] = False
        res["gaps"].sort(key=lambda g: -g["points"])
        res["gap_count"] = len(res["gaps"])
        res["gaps"] = res["gaps"][:cfg["MAX_GAPS"]]
    except Exception:
        res["ok"] = False
        res["error"] = traceback.format_exc()[-800:]
    return res
