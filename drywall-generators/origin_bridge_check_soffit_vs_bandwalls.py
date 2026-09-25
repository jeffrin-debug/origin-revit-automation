# origin_bridge_check_soffit_vs_bandwalls.py - run via the ORIGIN Bridge. READ-ONLY.
# After re-applying the Z-blind wall-clip fix, confirm the new soffit boards (which now flow over
# the band walls 005/006/012 instead of being excluded around them) have zero real 3D overlap with
# those same band walls' own generated boards/framing.
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

BAND_TAGS = ("005", "006", "012")


def solids_of(e):
    out = []
    try:
        opt = Options()
        geo = e.get_Geometry(opt)
        if geo is None:
            return out
        for g in geo:
            if isinstance(g, Solid) and g.Volume > 1e-9:
                out.append(g)
    except Exception:
        pass
    return out


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())
soffit_boards = []
band_elems = []
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark:
        continue
    if mark.startswith("DP-S"):
        soffit_boards.append((mark, ds))
    elif mark.startswith(tuple("DP-{}-".format(t) for t in BAND_TAGS)) or \
            mark.startswith(tuple("ST-{}-".format(t) for t in BAND_TAGS)):
        band_elems.append((mark, ds))

out = {"soffit_boards": len(soffit_boards), "band_elements": len(band_elems), "overlaps": []}

for smark, sds in soffit_boards:
    sbb = sds.get_BoundingBox(None)
    ssolids = None
    for bmark, bds in band_elems:
        bbb = bds.get_BoundingBox(None)
        if (sbb.Max.X < bbb.Min.X or sbb.Min.X > bbb.Max.X or
                sbb.Max.Y < bbb.Min.Y or sbb.Min.Y > bbb.Max.Y or
                sbb.Max.Z < bbb.Min.Z or sbb.Min.Z > bbb.Max.Z):
            continue
        if ssolids is None:
            ssolids = solids_of(sds)
        max_ov = 0.0
        for s1 in ssolids:
            for s2 in solids_of(bds):
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        out["overlaps"].append({"soffit_board": smark, "band_elem": bmark, "real_overlap_cf": round(max_ov, 8)})

OUT = out
