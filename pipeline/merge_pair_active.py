# merge_pair_active.py - fold one wall board into its coplanar neighbour on the model open in Revit.
# C9 2026-09-29: DP-037-003A (1.37in, left by the K004 column trim) into DP-037-002A -> one
# 65.9 x 48in board. Same checks as wall_narrow_merge.py: same plane, touching along the whole
# edge, one 4 x 8 ft sheet, union = one solid with the two volumes' sum. Rolled back otherwise.
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

KEEP, FOLD = "DP-037-002A", "DP-037-003A"
doc = DocumentManager.Instance.CurrentDBDocument
TOL = 0.02 / 12.0


def par(e, b):
    p = e.get_Parameter(b)
    return (p.AsString() or "") if p else ""


def solid(e):
    ss = [g for g in e.get_Geometry(Options()) if isinstance(g, Solid) and g.Volume > 1e-9]
    if len(ss) != 1:
        raise Exception("{} has {} solids".format(par(e, BuiltInParameter.ALL_MODEL_MARK), len(ss)))
    return ss[0]


m = dict((par(d, BuiltInParameter.ALL_MODEL_MARK), d) for d in
         FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType())
k, f = m[KEEP], m[FOLD]
a, b = k.get_BoundingBox(None), f.get_BoundingBox(None)
res = {}
TransactionManager.Instance.EnsureInTransaction(doc)
st = SubTransaction(doc)
st.Start()
try:
    if abs(a.Min.Y - b.Min.Y) > TOL or abs(a.Max.Y - b.Max.Y) > TOL:
        raise Exception("not the same face plane")
    if abs(a.Min.Z - b.Min.Z) > TOL or abs(a.Max.Z - b.Max.Z) > TOL:
        raise Exception("not the same course")
    if abs(a.Min.X - b.Max.X) > TOL and abs(b.Min.X - a.Max.X) > TOL:
        raise Exception("boards do not touch")
    w = (max(a.Max.X, b.Max.X) - min(a.Min.X, b.Min.X)) * 12
    h = (a.Max.Z - a.Min.Z) * 12
    if not ((w <= 96.01 and h <= 48.01) or (w <= 48.01 and h <= 96.01)):
        raise Exception("merged {:.1f} x {:.1f}in is over one sheet".format(w, h))
    sk, sf = solid(k), solid(f)
    u = BooleanOperationsUtils.ExecuteBooleanOperation(sk, sf, BooleanOperationsType.Union)
    if len(SolidUtils.SplitVolumes(u)) != 1:
        raise Exception("union is not one piece")
    if abs(u.Volume - (sk.Volume + sf.Volume)) > 0.01 * (sk.Volume + sf.Volume):
        raise Exception("volumes do not add up")
    shp = List[GeometryObject]()
    shp.Add(u)
    k.SetShape(shp)
    p = k.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    p.Set(par(k, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) + " NARROW_MERGED={}".format(FOLD))
    doc.Delete(f.Id)
    doc.Regenerate()
    bb = k.get_BoundingBox(None)
    st.Commit()
    res = {"ok": True, "board": KEEP, "size_in": [round(w, 2), round(h, 2)],
           "x_in": [round(bb.Min.X * 12, 2), round(bb.Max.X * 12, 2)], "deleted": FOLD}
except Exception as ex:
    st.RollBack()
    res = {"ok": False, "error": str(ex)[:400]}
finally:
    TransactionManager.Instance.TransactionTaskDone()
OUT = res
