# origin_bridge_check_failed_boolean_probes.py - run via the ORIGIN Bridge. READ-ONLY.
# The wall run logged 8 "boolean probe failed (Revit boolean engine error) - left untouched, may
# still overlap" warnings. Intersect can fail on Revit's boolean engine (often exactly-coincident
# faces from a clean butt joint) even when there's no real overlap. Cross-check each pair with a
# volume-conservation approach instead: Union volume should equal Vol(A)+Vol(B) if truly disjoint;
# any shortfall is the real overlap. Also report bbox clearance as a second, purely-numeric signal.
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

results = []
for m1, m2 in PAIRS:
    e1 = find_by_mark(m1)
    e2 = find_by_mark(m2)
    rec = {"a": m1, "b": m2, "a_found": e1 is not None, "b_found": e2 is not None}
    if e1 is not None and e2 is not None:
        bb1 = e1.get_BoundingBox(None)
        bb2 = e2.get_BoundingBox(None)
        sep = (bb1.Max.X <= bb2.Min.X or bb2.Max.X <= bb1.Min.X or
               bb1.Max.Y <= bb2.Min.Y or bb2.Max.Y <= bb1.Min.Y or
               bb1.Max.Z <= bb2.Min.Z or bb2.Max.Z <= bb1.Min.Z)
        rec["bbox_separated"] = sep
        s1 = solids_of(e1)
        s2 = solids_of(e2)
        vol1 = sum(s.Volume for s in s1)
        vol2 = sum(s.Volume for s in s2)
        rec["vol_a"] = round(vol1, 6)
        rec["vol_b"] = round(vol2, 6)
        union_vol = None
        union_err = None
        try:
            u = None
            for a in s1:
                for b in s2:
                    piece = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Union)
                    if piece is not None:
                        u = piece if u is None else BooleanOperationsUtils.ExecuteBooleanOperation(u, piece, BooleanOperationsType.Union)
            if u is not None:
                union_vol = u.Volume
        except Exception as ex:
            union_err = str(ex)
        rec["union_vol"] = round(union_vol, 6) if union_vol is not None else None
        rec["union_error"] = union_err
        if union_vol is not None:
            rec["implied_overlap_cf"] = round((vol1 + vol2) - union_vol, 6)
        rec["min_gap_ft"] = {
            "x": round(max(bb2.Min.X - bb1.Max.X, bb1.Min.X - bb2.Max.X), 4),
            "y": round(max(bb2.Min.Y - bb1.Max.Y, bb1.Min.Y - bb2.Max.Y), 4),
            "z": round(max(bb2.Min.Z - bb1.Max.Z, bb1.Min.Z - bb2.Max.Z), 4),
        }
    results.append(rec)

OUT = {"results": results}
