# list_walls.py - read-only: every wall with mark, comment, length, and the z-levels of its solid
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
opt = Options(); opt.DetailLevel = ViewDetailLevel.Fine
out = []
for w in FilteredElementCollector(doc).OfClass(Wall):
    zs, vol = set(), 0.0
    for g in w.get_Geometry(opt):
        if isinstance(g, Solid) and g.Volume > 1e-9:
            vol += g.Volume
            for e in g.Edges:
                for k in (0, 1):
                    zs.add(round(e.AsCurve().GetEndPoint(k).Z * 12, 2))
    out.append({"id": w.Id.Value, "mark": w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString(),
                "comment": w.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString(),
                "len_in": round(w.Location.Curve.Length * 12, 2), "t_in": round(w.Width * 12, 2),
                "z_levels_in": sorted(zs), "vol_cuin": round(vol * 1728, 1)})
OUT = out
