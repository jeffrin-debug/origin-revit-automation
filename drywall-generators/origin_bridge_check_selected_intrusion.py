# origin_bridge_check_selected_intrusion.py - run via the ORIGIN Bridge. READ-ONLY.
# Reads whatever is CURRENTLY selected live in Revit (expects exactly 2 DP-*/ST-* DirectShapes
# that meet at a corner) and reports the real boolean intersection between them: volume, the
# overlap region's own bounding box (so we can see which axis/direction the intrusion runs
# along), and that thickness converted to mm/inches for a human-scale read.
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


def mark_of(e):
    try:
        mk = e.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        return mk.AsString() if mk else None
    except Exception:
        return None


def comments_of(e):
    try:
        cm = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return cm.AsString() if cm else None
    except Exception:
        return None


FT_TO_MM = 304.8

sel_ids = list(uidoc.Selection.GetElementIds())
sel = [doc.GetElement(i) for i in sel_ids]
sel = [e for e in sel if e is not None]

out = {"selection_count": len(sel), "selected": []}
for e in sel:
    bb = e.get_BoundingBox(None)
    out["selected"].append({
        "eid": e.Id.Value if hasattr(e.Id, "Value") else e.Id.IntegerValue,
        "mark": mark_of(e),
        "comments": comments_of(e),
        "bbox": None if bb is None else {
            "min": [round(bb.Min.X, 4), round(bb.Min.Y, 4), round(bb.Min.Z, 4)],
            "max": [round(bb.Max.X, 4), round(bb.Max.Y, 4), round(bb.Max.Z, 4)],
        },
    })

if len(sel) == 2:
    a, b = sel
    a_solids = solids_of(a)
    b_solids = solids_of(b)
    total_vol = 0.0
    ov_min = [None, None, None]
    ov_max = [None, None, None]
    errs = []
    for sa in a_solids:
        for sb in b_solids:
            try:
                inter = BooleanOperationsUtils.ExecuteBooleanOperation(sa, sb, BooleanOperationsType.Intersect)
                if inter is not None and inter.Volume > 1e-9:
                    total_vol += inter.Volume
                    ibb = inter.GetBoundingBox()
                    # inter bbox is in the solid's own transform space; combine via inter.GetOutline if needed
                    tf = inter.GetBoundingBox()
            except Exception as ex:
                errs.append(str(ex))

    out["overlap_volume_cf"] = round(total_vol, 6)
    out["overlap_errors"] = errs

    # Also compute overlap region bbox directly from the two solids' own bboxes (world-space
    # DirectShape bboxes), which is a good enough proxy for "how far into each other are they".
    bbA = a.get_BoundingBox(None)
    bbB = b.get_BoundingBox(None)
    if bbA is not None and bbB is not None:
        ov_lo = [max(bbA.Min.X, bbB.Min.X), max(bbA.Min.Y, bbB.Min.Y), max(bbA.Min.Z, bbB.Min.Z)]
        ov_hi = [min(bbA.Max.X, bbB.Max.X), min(bbA.Max.Y, bbB.Max.Y), min(bbA.Max.Z, bbB.Max.Z)]
        dims_ft = [ov_hi[k] - ov_lo[k] for k in range(3)]
        out["bbox_overlap_region"] = {
            "min_ft": [round(v, 4) for v in ov_lo],
            "max_ft": [round(v, 4) for v in ov_hi],
            "dims_ft": [round(v, 4) for v in dims_ft],
            "dims_mm": [round(v * FT_TO_MM, 2) for v in dims_ft],
        }

OUT = out
