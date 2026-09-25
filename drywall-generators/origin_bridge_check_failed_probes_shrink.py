# origin_bridge_check_failed_probes_shrink.py - run via the ORIGIN Bridge. READ-ONLY.
# The direct boolean Intersect/Union both fail on 8 DP/ST pairs with a Revit boolean-engine error
# (coincident/near-coincident faces are the classic cause). Retry the Intersect after shrinking
# each solid by a tiny uniform factor about its own centroid - this nudges faces off exact
# coincidence without changing the real geometry question. If the overlap vanishes once shrunk,
# the pair was only touching (a clean butt/trim, not a defect); if it persists, it's a real clash.
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


def solids_of(e):
    out = []
    opt = Options()
    opt.ComputeReferences = False
    geo = e.get_Geometry(opt)
    if geo is None:
        return out
    for g in geo:
        if isinstance(g, Solid) and g.Volume > 1e-9 and g.Faces.Size > 0:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for g2 in g.GetInstanceGeometry():
                if isinstance(g2, Solid) and g2.Volume > 1e-9 and g2.Faces.Size > 0:
                    out.append(g2)
    return out


def find_by_mark(mark):
    for e in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
        try:
            mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
            m = mk.AsString() if mk else None
        except Exception:
            m = None
        if m == mark:
            return e
    return None


def centroid_of(solid):
    bb = solid.GetBoundingBox()
    tf = solid.GetBoundingBox()
    # Use the solid's own bbox (in its local coord, but our solids come straight from world-space
    # geometry with no instance transform applied) center as a simple, adequate centroid proxy.
    c = XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)
    return c


def shrink(solid, factor):
    c = centroid_of(solid)
    tf = Transform.Identity
    tf.Origin = XYZ(c.X * (1.0 - factor), c.Y * (1.0 - factor), c.Z * (1.0 - factor))
    tf.BasisX = XYZ.BasisX * factor
    tf.BasisY = XYZ.BasisY * factor
    tf.BasisZ = XYZ.BasisZ * factor
    return SolidUtils.CreateTransformed(solid, tf)


PAIRS = [
    ("DP-004-001B", "ST-028-003"),
    ("DP-004-004B", "ST-028-004"),
    ("DP-014-001A", "ST-049-003"),
    ("DP-014-003A", "ST-049-004"),
    ("DP-044-001B", "ST-046-003"),
    ("DP-044-003B", "ST-046-004"),
    ("DP-028-001A", "DP-004-001B"),
    ("DP-046-001A", "DP-044-001B"),
]

FACTOR = 0.995

results = []
for m1, m2 in PAIRS:
    e1 = find_by_mark(m1)
    e2 = find_by_mark(m2)
    rec = {"a": m1, "b": m2}
    if e1 is None or e2 is None:
        rec["error"] = "element not found"
        results.append(rec)
        continue
    s1 = solids_of(e1)
    s2 = solids_of(e2)
    total_shrunk_overlap = 0.0
    errs = []
    tried = 0
    for a in s1:
        for b in s2:
            try:
                sa = shrink(a, FACTOR)
                sb = shrink(b, FACTOR)
                tried += 1
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(sa, sb, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > 1e-9:
                    total_shrunk_overlap += inter.Volume
            except Exception as ex:
                errs.append(str(ex).splitlines()[0])
    rec["pairs_tried"] = tried
    rec["shrunk_overlap_cf"] = round(total_shrunk_overlap, 6)
    rec["errors"] = errs
    results.append(rec)

OUT = {"shrink_factor": FACTOR, "results": results}
