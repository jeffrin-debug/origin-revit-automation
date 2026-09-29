# corner_close_active.py - close one OUTSIDE L-corner on the model open in Revit, in place.
#
# C9 2026-09-29, wall 004 (W376331, through) x wall 002 (W375946, butting): wall 004's end stud
# ST-004-001 was centred on the wall's end, so its outer half-flange (0.63in) poked past wall
# 002's outer face into the space wall 002's west board needs. trim_drywall_from_neighbor_studs()
# then cut that board (DP-002-001A/002A) back to wall 004's core, leaving the stud end exposed and
# patched with 0.63in strips (DP-004-004A merged into DP-004-001A, DP-004-004B kept).
#
# Hung the way corner_lap.py hangs every outside corner - the through wall LAPS, the other BUTTS:
#   * the through wall's end stud moves in until its outer flange sits behind the butting board,
#     and its tracks are trimmed to the same line;
#   * the through wall's outer-face boards are trimmed back to the butting wall's outer face;
#   * the butting wall's outer-face boards run on to the back of the lapping boards;
#   * the leftover infill strip is deleted.
# All edits run in one transaction and are rolled back unless every check passes. Read-only
# preview: set DRY_RUN = True.

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

DRY_RUN = False
END_STUD = "ST-004-001"
TRACKS = ["ST-004-008", "ST-004-010"]
LAP_BOARDS = ["DP-004-001A", "DP-004-003A"]        # through wall, outer face (-Y side), trimmed
BUTT_BOARDS = ["DP-002-001A", "DP-002-002A"]       # butting wall, outer face (-X side), extended
DELETE = ["DP-004-004B"]
TOKEN = "CORNER_CLOSED=2026-09-29"

doc = DocumentManager.Instance.CurrentDBDocument
IN = 1.0 / 12.0


def _par(e, bip):
    p = e.get_Parameter(bip)
    return (p.AsString() or "") if p else ""


def _by_mark():
    out = {}
    for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        out[_par(ds, BuiltInParameter.ALL_MODEL_MARK)] = ds
    return out


def _solid(e):
    ss = [g for g in e.get_Geometry(Options()) if isinstance(g, Solid) and g.Volume > 1e-9]
    if len(ss) != 1:
        raise Exception("{} has {} solids".format(_par(e, BuiltInParameter.ALL_MODEL_MARK), len(ss)))
    return ss[0]


def _style(s):
    mat = ElementId.InvalidElementId
    for f in s.Faces:
        if f.MaterialElementId != ElementId.InvalidElementId:
            mat = f.MaterialElementId
            break
    return SolidOptions(mat, s.GraphicsStyleId or ElementId.InvalidElementId)


def _box(x0, x1, y0, y1, z0, z1, opts):
    pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0, opts)


def _set(e, solid, note):
    if len(SolidUtils.SplitVolumes(solid)) != 1:
        raise Exception("{} would not be one piece".format(_par(e, BuiltInParameter.ALL_MODEL_MARK)))
    shape = List[GeometryObject]()
    shape.Add(solid)
    e.SetShape(shape)
    p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(_par(e, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) + " " + TOKEN + ":" + note)


def _bb(e):
    b = e.get_BoundingBox(None)
    return {"x": [round(b.Min.X * 12, 2), round(b.Max.X * 12, 2)],
            "y": [round(b.Min.Y * 12, 2), round(b.Max.Y * 12, 2)],
            "z": [round(b.Min.Z * 12, 2), round(b.Max.Z * 12, 2)]}


def _clash(a, b):
    try:
        r = BooleanOperationsUtils.ExecuteBooleanOperation(_solid(a), _solid(b), BooleanOperationsType.Intersect)
        return r.Volume * 1728.0 if r is not None else 0.0
    except Exception:
        return -1.0


m = _by_mark()
need = [END_STUD] + TRACKS + LAP_BOARDS + BUTT_BOARDS + DELETE
missing = [k for k in need if k not in m]
res = {"doc": doc.Title, "dry_run": DRY_RUN}
if missing:
    res["error"] = "missing: {}".format(missing)
    OUT = res
else:
    butt_bb = m[BUTT_BOARDS[0]].get_BoundingBox(None)
    lap_bb = m[LAP_BOARDS[0]].get_BoundingBox(None)
    face_x = butt_bb.Min.X                   # butting wall's outer finished face (lap boards end here)
    back_x = butt_bb.Max.X                   # back of the butting board (framing starts here)
    lap_back_y = lap_bb.Max.Y                # back of the lapping boards (butt boards run to here)
    stud_bb = m[END_STUD].get_BoundingBox(None)
    shift = back_x - stud_bb.Min.X
    res["plan"] = {"face_x_in": round(face_x * 12, 3), "back_x_in": round(back_x * 12, 3),
                   "lap_back_y_in": round(lap_back_y * 12, 3), "stud_shift_in": round(shift * 12, 3)}
    res["before"] = dict((k, _bb(m[k])) for k in need)
    if DRY_RUN:
        OUT = res
    else:
        TransactionManager.Instance.EnsureInTransaction(doc)
        st = SubTransaction(doc)
        st.Start()
        try:
            BIG = 100.0
            # 1. end stud behind the butting board
            s = _solid(m[END_STUD])
            _set(m[END_STUD], SolidUtils.CreateTransformed(s, Transform.CreateTranslation(XYZ(shift, 0, 0))),
                 "moved+{:.3f}in".format(shift * 12))
            # 2. tracks trimmed to the same line
            for k in TRACKS:
                s = _solid(m[k])
                cut = _box(face_x - BIG, back_x, s.GetBoundingBox().Min.Y - BIG, s.GetBoundingBox().Max.Y + BIG,
                           -BIG, BIG, _style(s))
                _set(m[k], BooleanOperationsUtils.ExecuteBooleanOperation(s, cut, BooleanOperationsType.Difference),
                     "trimmed_to_x={:.2f}in".format(back_x * 12))
            # 3. lapping boards back to the butting wall's outer face
            for k in LAP_BOARDS:
                s = _solid(m[k])
                cut = _box(face_x - BIG, face_x, -BIG, BIG, -BIG, BIG, _style(s))
                _set(m[k], BooleanOperationsUtils.ExecuteBooleanOperation(s, cut, BooleanOperationsType.Difference),
                     "trimmed_to_x={:.2f}in".format(face_x * 12))
            # 4. butting boards on to the back of the lapping boards
            for k in BUTT_BOARDS:
                e = m[k]
                s = _solid(e)
                b = e.get_BoundingBox(None)
                add = _box(b.Min.X, b.Max.X, lap_back_y, b.Min.Y + 0.001 * IN, b.Min.Z, b.Max.Z, _style(s))
                u = BooleanOperationsUtils.ExecuteBooleanOperation(s, add, BooleanOperationsType.Union)
                want = s.Volume + add.Volume - 0.001 * IN * (b.Max.X - b.Min.X) * (b.Max.Z - b.Min.Z)
                if abs(u.Volume - want) > 0.01 * want:
                    raise Exception("{} union volume off ({:.4f} vs {:.4f})".format(k, u.Volume, want))
                _set(e, u, "extended_to_y={:.2f}in".format(lap_back_y * 12))
            # 5. leftover infill strip
            for k in DELETE:
                doc.Delete(m[k].Id)
            doc.Regenerate()

            # checks: real-solid clashes among everything touched and its neighbours
            touched = [END_STUD] + TRACKS + LAP_BOARDS + BUTT_BOARDS
            zone = Outline(XYZ(face_x - 2 * IN, lap_bb.Min.Y - 2 * IN, -1.0),
                           XYZ(back_x + 6 * IN, butt_bb.Min.Y + 6 * IN, 20.0))
            near = [ds for ds in FilteredElementCollector(doc).OfClass(DirectShape)
                    .WherePasses(BoundingBoxIntersectsFilter(zone)).ToElements()
                    if _par(ds, BuiltInParameter.ALL_MODEL_MARK)[:3] in ("DP-", "ST-")]
            clashes = []
            for k in touched:
                for o in near:
                    ok = _par(o, BuiltInParameter.ALL_MODEL_MARK)
                    if ok == k:
                        continue
                    v = _clash(m[k], o)
                    if v > 0.001 or v < 0:
                        clashes.append({"a": k, "b": ok, "cuin": round(v, 4)})
            res["clashes"] = clashes
            bad = [c for c in clashes if (c["a"].startswith("DP-") or c["b"].startswith("DP-"))]
            if bad:
                raise Exception("board clash after edit: {}".format(bad))
            st.Commit()
            res["after"] = dict((k, _bb(m[k])) for k in touched)
            res["deleted"] = DELETE
            res["ok"] = True
        except Exception as ex:
            st.RollBack()
            res["ok"] = False
            res["error"] = str(ex)[:600]
        finally:
            TransactionManager.Instance.TransactionTaskDone()
        OUT = res
