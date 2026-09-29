# corner_close_butt_stud.py - second half of corner_close_active.py (C9, wall 004 x 002).
# The butting wall's end stud ST-002-003 was centred on its framing end (wall 004's north face),
# so half its flange poked 0.63in into wall 004's core - where ST-004-001 now sits. Inset it so its
# flange ends at its own tracks' end, check real-solid clashes, and select both end studs so
# diag_exposed_studs.py can verify coverage.
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
STUD, TRACK, OTHER = "ST-002-003", "ST-002-004", "ST-004-001"
TOKEN = "CORNER_CLOSED=2026-09-29"


def par(e, b):
    p = e.get_Parameter(b)
    return (p.AsString() or "") if p else ""


def solid(e):
    return [g for g in e.get_Geometry(Options()) if isinstance(g, Solid) and g.Volume > 1e-9][0]


m = dict((par(d, BuiltInParameter.ALL_MODEL_MARK), d) for d in
         FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType())
s, t = m[STUD], m[TRACK]
shift = t.get_BoundingBox(None).Min.Y - s.get_BoundingBox(None).Min.Y
res = {"shift_in": round(shift * 12, 3)}
TransactionManager.Instance.EnsureInTransaction(doc)
st = SubTransaction(doc)
st.Start()
try:
    shp = List[GeometryObject]()
    shp.Add(SolidUtils.CreateTransformed(solid(s), Transform.CreateTranslation(XYZ(0, shift, 0))))
    s.SetShape(shp)
    p = s.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    p.Set(par(s, BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) + " {}:moved+{:.3f}in".format(TOKEN, shift * 12))
    doc.Regenerate()
    b = s.get_BoundingBox(None)
    zone = Outline(b.Min.Subtract(XYZ(0.5, 0.5, 0.5)), b.Max.Add(XYZ(0.5, 0.5, 0.5)))
    clashes = []
    for o in FilteredElementCollector(doc).OfClass(DirectShape).WherePasses(BoundingBoxIntersectsFilter(zone)):
        k = par(o, BuiltInParameter.ALL_MODEL_MARK)
        if k == STUD or k[:3] not in ("DP-", "ST-"):
            continue
        r = BooleanOperationsUtils.ExecuteBooleanOperation(solid(s), solid(o), BooleanOperationsType.Intersect)
        v = r.Volume * 1728.0 if r is not None else 0.0
        if v > 0.001:
            clashes.append({"with": k, "cuin": round(v, 4)})
    res["clashes"] = clashes
    if any(c["with"].startswith("DP-") or c["with"] == OTHER for c in clashes):
        raise Exception("still clashing: {}".format(clashes))
    st.Commit()
    res["ok"] = True
    res["bbox_y_in"] = [round(b.Min.Y * 12, 2), round(b.Max.Y * 12, 2)]
except Exception as ex:
    st.RollBack()
    res["ok"] = False
    res["error"] = str(ex)[:500]
finally:
    TransactionManager.Instance.TransactionTaskDone()
ids = List[ElementId]()
ids.Add(m[OTHER].Id)
ids.Add(s.Id)
uidoc.Selection.SetElementIds(ids)
OUT = res
