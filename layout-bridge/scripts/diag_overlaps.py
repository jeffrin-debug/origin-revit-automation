# diag_overlaps.py - read-only: do the walls of a built room actually overlap each other?
# For every pair of walls tagged ORIGIN_LAYOUT_* reports the shared solid volume and how each
# end is joined, so "intrusion" can be measured instead of guessed.
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument


def solids(e):
    opt = Options()
    opt.ComputeReferences = False
    opt.DetailLevel = ViewDetailLevel.Fine
    out = []
    for g in e.get_Geometry(opt):
        if isinstance(g, Solid) and g.Volume > 1e-9:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            for h in g.GetInstanceGeometry():
                if isinstance(h, Solid) and h.Volume > 1e-9:
                    out.append(h)
    return out


walls = []
for w in list(FilteredElementCollector(doc).OfClass(Wall)) + list(FilteredElementCollector(doc).OfClass(DirectShape)):
    c = w.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if c and (c.AsString() or "").startswith("ORIGIN_LAYOUT_"):
        walls.append(w)

info = []
for w in walls:
    ends = []
    for k in (0, 1):
        try:
            joined = [doc.GetElement(x.ElementId) for x in w.Location.ElementsAtJoin[k]
                      if x.ElementId != w.Id] if hasattr(w.Location, "ElementsAtJoin") else []
        except Exception:
            joined = []
        if not isinstance(w, Wall):
            continue
        ends.append({"join_allowed": WallUtils.IsWallJoinAllowedAtEnd(w, k),
                     "joined_to": [j.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString() for j in joined
                                   if j is not None and j.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)]})
    info.append({"mark": w.get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString(),
                 "volume_cuin": round(sum(s.Volume for s in solids(w)) * 1728, 1), "ends": ends})

pairs = []
for i in range(len(walls)):
    for j in range(i + 1, len(walls)):
        v = 0.0
        for a in solids(walls[i]):
            for b in solids(walls[j]):
                try:
                    r = BooleanOperationsUtils.ExecuteBooleanOperation(a, b, BooleanOperationsType.Intersect)
                    v += r.Volume
                except Exception:
                    pass
        if v > 1e-6:
            pairs.append({"a": walls[i].get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString(),
                          "b": walls[j].get_Parameter(BuiltInParameter.ALL_MODEL_MARK).AsString(),
                          "overlap_cuin": round(v * 1728, 1)})

OUT = {"doc": doc.Title, "walls": info, "overlapping_pairs": pairs}
