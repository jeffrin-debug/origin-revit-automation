# scan_exposed_studs.py - READ-ONLY.
# Find every generated framing member that has NO drywall in front of it, model-wide.
#
# The wall generator has its own self-check (validate_wall_coverage) but it only asks "does this
# wall have ANY drywall at all" - a wall 80% covered passes it. This asks the question per
# MEMBER, on each face, with real geometry.
#
# Method: a thin probe slab is built just outside the member on each side of the wall, spanning
# the member's own Z range, and intersected with nearby board solids. Bounding-box overlap does
# not count as coverage.
import clr
import math
import time

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

APP_ID = "ORIGIN_ASSEMBLY_V4"
PROBE_HALF = 0.06
OFFSETS = (0.12, 0.28)     # how far outside the member to look, in feet
SEARCH_FT = 2.5
KINDS = ("STUD", "KINGSTUD", "JACK", "CRIPPLE")   # tracks/headers sit behind board by design


def eidv(e):
    return e.IntegerValue if hasattr(e, "IntegerValue") else e.Value


def comment_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return (p.AsString() or "") if p else ""
    except Exception:
        return ""


def mark_of(e):
    try:
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return p.AsString() if p else None
    except Exception:
        return None


def solids_of(e):
    """Solids one level down through GeometryInstance too - a loaded family's real geometry is
    nested, so a flat scan finds nothing for doors and windows."""
    out = []
    try:
        opt = Options()
        try:
            opt.DetailLevel = ViewDetailLevel.Fine
        except Exception:
            pass
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
            elif isinstance(g, GeometryInstance):
                try:
                    for g2 in g.GetInstanceGeometry():
                        if isinstance(g2, Solid) and g2.Volume > 1e-9:
                            out.append(g2)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def box(e):
    bb = e.get_BoundingBox(None)
    if bb is None:
        return None
    return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)


def make_box(x0, y0, z0, x1, y1, z1):
    try:
        pts = [XYZ(x0, y0, z0), XYZ(x1, y0, z0), XYZ(x1, y1, z0), XYZ(x0, y1, z0)]
        loop = CurveLoop()
        for i in range(4):
            loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
        loops = List[CurveLoop]()
        loops.Add(loop)
        return GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, z1 - z0)
    except Exception:
        return None


t0 = time.time()

boards = []
members = []
for ds in FilteredElementCollector(doc).OfClass(DirectShape).ToElements():
    c = comment_of(ds)
    if not c.startswith(APP_ID + " |"):
        continue
    b = box(ds)
    if b is None:
        continue
    # What counts as "something is in front of this stud". Drywall obviously; but a door's real
    # frame is cloned in as DOORFRAME and a curtain wall's glass as GLASS, and in the real
    # assembly those cover the jamb framing exactly as they do on site. Counting only drywall
    # over-reports bare studs at door openings.
    if "| DRYWALL" in c:
        boards.append({"el": ds, "mark": mark_of(ds), "box": b, "cover": "drywall"})
        continue
    if "| DOORFRAME" in c:
        boards.append({"el": ds, "mark": mark_of(ds), "box": b, "cover": "doorframe"})
        continue
    if "| GLASS" in c:
        boards.append({"el": ds, "mark": mark_of(ds), "box": b, "cover": "glass"})
        continue
    kind = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok in ("STUD", "TRACK", "HEADER", "SILL", "KINGSTUD", "JACK", "CRIPPLE"):
            kind = tok
    if kind not in KINDS:
        continue
    host = None
    for tok in c.split("|"):
        tok = tok.strip()
        if tok.startswith("WALL=W"):
            try:
                host = int(tok[len("WALL=W"):])
            except Exception:
                pass
    members.append({"el": ds, "mark": mark_of(ds), "box": b, "kind": kind, "host": host})

# The REAL doors and windows count as coverage too. They are FamilyInstances, not DirectShapes,
# so an earlier version of this scan could not see them at all and reported jamb studs as bare
# with a window frame sitting right in front of them. They ARE visible in the ORIGIN Assembly
# view - OST_Windows is deliberately not in that view's hide list - so whatever covers a stud on
# screen has to count here.
for _bic in (BuiltInCategory.OST_Windows, BuiltInCategory.OST_Doors):
    for _fi in (FilteredElementCollector(doc).OfCategory(_bic)
                .WhereElementIsNotElementType()):
        _b = box(_fi)
        if _b is None:
            continue
        boards.append({"el": _fi,
                       "mark": mark_of(_fi) or ("real-" + str(eidv(_fi.Id))),
                       "box": _b,
                       "cover": ("window" if _bic == BuiltInCategory.OST_Windows else "door")})

# cache each wall's outward normal once
normals = {}
for m in members:
    h = m["host"]
    if h is None or h in normals:
        continue
    w = doc.GetElement(ElementId(h))
    try:
        o = w.Orientation
        normals[h] = (o.X, o.Y, w.Name)
    except Exception:
        normals[h] = None

board_solids = {}


def solids_for(bd):
    k = eidv(bd["el"].Id)
    if k not in board_solids:
        board_solids[k] = solids_of(bd["el"])
    return board_solids[k]


exposed = []
checked = 0
for m in members:
    n = normals.get(m["host"])
    if not n:
        continue
    nx, ny, wname = n
    b = m["box"]
    cx = (b[0] + b[3]) / 2.0
    cy = (b[1] + b[4]) / 2.0
    near = []
    for bd in boards:
        q = bd["box"]
        if (q[3] < b[0] - SEARCH_FT or q[0] > b[3] + SEARCH_FT or
                q[4] < b[1] - SEARCH_FT or q[1] > b[4] + SEARCH_FT or
                q[5] < b[2] - 0.3 or q[2] > b[5] + 0.3):
            continue
        near.append(bd)
    checked += 1
    bare = []
    for side, sgn in (("exterior", 1.0), ("interior", -1.0)):
        found = None
        for dist in OFFSETS:
            px = cx + nx * sgn * dist
            py = cy + ny * sgn * dist
            probe = make_box(px - PROBE_HALF, py - PROBE_HALF, b[2] + 0.08,
                             px + PROBE_HALF, py + PROBE_HALF, b[5] - 0.08)
            if probe is None:
                continue
            for bd in near:
                for s in solids_for(bd):
                    try:
                        inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                            probe, s, BooleanOperationsType.Intersect)
                    except Exception:
                        continue
                    if inter is not None and inter.Volume > 1e-9:
                        found = "{} ({})".format(bd["mark"], bd.get("cover"))
                        break
                if found:
                    break
            if found:
                break
        if not found:
            bare.append(side)
    if bare:
        # is this member at an opening (a door/window frame clone sits nearby) or in open wall?
        near_frame = any(bd.get("cover") in ("doorframe", "glass") for bd in near)
        exposed.append({
            "member": m["mark"], "kind": m["kind"], "host_wall": m["host"],
            "wall_type": wname,
            "frame_clone_nearby": near_frame,
            "bare_faces": bare,
            "z_ft": [round(b[2], 2), round(b[5], 2)],
            "at_xy": [round(cx, 2), round(cy, 2)],
            "boards_nearby": len(near),
        })

by_wall = {}
for e in exposed:
    by_wall.setdefault(e["host_wall"], 0)
    by_wall[e["host_wall"]] += 1

by_kind = {}
for e in exposed:
    by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1

OUT = {
    "doc": doc.Title,
    "seconds": round(time.time() - t0, 1),
    "covering_elements": len(boards),
    "covering_breakdown": {
        "drywall": len([b for b in boards if b.get("cover") == "drywall"]),
        "doorframe": len([b for b in boards if b.get("cover") == "doorframe"]),
        "glass": len([b for b in boards if b.get("cover") == "glass"]),
    },
    "exposed_by_kind": by_kind,
    "exposed_with_frame_nearby": len([e for e in exposed if e["frame_clone_nearby"]]),
    "exposed_with_no_frame_nearby": len([e for e in exposed if not e["frame_clone_nearby"]]),
    "boards": len(boards),
    "members_checked": checked,
    "exposed_members": len(exposed),
    "exposed_both_faces": len([e for e in exposed if len(e["bare_faces"]) == 2]),
    "worst_walls": sorted(by_wall.items(), key=lambda kv: -kv[1])[:10],
    "detail": exposed[:40],
}
