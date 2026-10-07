# diag_wall_solids.py - read-only: bounding boxes (inches) of every solid of one wall, by mark.
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
import os, json
_cfg = os.path.join(os.path.dirname(__file__), "diag_wall_solids.json")
MARK = json.load(open(_cfg))["mark"]   # diag_wall_solids.json: {"mark": "<wall Mark>"}
w = next(x for x in FilteredElementCollector(doc).OfClass(Wall)
         if (x.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString() or "") == MARK)
opt = Options(); opt.DetailLevel = ViewDetailLevel.Fine
out = []
for g in w.get_Geometry(opt):
    if isinstance(g, Solid) and g.Volume > 1e-9:
        bb = g.GetBoundingBox(); t = bb.Transform
        mn, mx = t.OfPoint(bb.Min), t.OfPoint(bb.Max)
        xs = sorted(set(round(e.AsCurve().GetEndPoint(k).X * 12, 2) for e in g.Edges for k in (0, 1)))
        zs = sorted(set(round(e.AsCurve().GetEndPoint(k).Z * 12, 2) for e in g.Edges for k in (0, 1)))
        out.append({"vol_cuin": round(g.Volume * 1728, 1), "distinct_z_in": zs,
                    "min": [round(mn.X * 12, 2), round(mn.Y * 12, 2), round(mn.Z * 12, 2)],
                    "max": [round(mx.X * 12, 2), round(mx.Y * 12, 2), round(mx.Z * 12, 2)],
                    "distinct_x_in": xs})
c = w.Location.Curve
OUT = {"mark": MARK, "loc": [[round(c.GetEndPoint(k).X * 12, 2), round(c.GetEndPoint(k).Y * 12, 2)] for k in (0, 1)],
       "solids": out, "inserts": [doc.GetElement(i).Name for i in w.FindInserts(True, True, True, True)]}
