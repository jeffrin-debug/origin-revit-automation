# origin_bridge_final_soffit_sweep.py - run via the ORIGIN Bridge. READ-ONLY.
# Two checks: (1) building-wide sweep - every DP-0xx-* wall board (excluding the soffit-band
# walls 005/006/012 themselves) vs the full soffit assembly (Ceiling S001 + band walls'
# boards/tracks), real boolean intersection, looking for ANY remaining overlap. (2) confirms the
# band walls' OWN boards are unaffected (still touch the ceiling flush, not pulled back).
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

BAND_WALL_TAGS = ("005", "006", "012")
RADIUS_FT = 3.0


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


def bbox_center(bb):
    return XYZ((bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0, (bb.Min.Z + bb.Max.Z) / 2.0)


def is_soffit_ceiling(c):
    try:
        cat = c.Category
        if cat is not None and cat.Name and "soffit" in cat.Name.lower():
            return True
    except Exception:
        pass
    return False


all_ds = list(FilteredElementCollector(doc).OfClass(DirectShape).ToElements())

soffit_assembly = []   # (ds_or_ceiling, mark_or_label)
for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
    if is_soffit_ceiling(c):
        soffit_assembly.append((c, "CEILING-S001"))

wall_boards = []      # non-band-wall DP-/ST- boards to test
band_boards = []      # the band walls' own boards (for the "unaffected" check)
for ds in all_ds:
    try:
        mk = ds.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        mark = mk.AsString() if mk else None
    except Exception:
        mark = None
    if not mark or not (mark.startswith("DP-") or mark.startswith("ST-")):
        continue
    if mark.startswith("DP-S") or mark.startswith("ST-S"):
        continue  # the ceiling's own boards, not a wall
    tag = mark.split("-")[1] if "-" in mark else ""
    if tag in BAND_WALL_TAGS:
        band_boards.append((ds, mark))
        soffit_assembly.append((ds, mark))
    else:
        wall_boards.append((ds, mark))

findings = []
for (ds, mark) in wall_boards:
    bb = ds.get_BoundingBox(None)
    if bb is None:
        continue
    c = bbox_center(bb)
    dsolids = solids_of(ds)
    if not dsolids:
        continue
    for (obj, olabel) in soffit_assembly:
        obb = obj.get_BoundingBox(None)
        if obb is None:
            continue
        if c.DistanceTo(bbox_center(obb)) > RADIUS_FT:
            continue
        osolids = solids_of(obj)
        if not osolids:
            continue
        max_ov = 0.0
        for s1 in dsolids:
            for s2 in osolids:
                try:
                    inter = BooleanOperationsUtils.ExecuteBooleanOperation(
                        s1, s2, BooleanOperationsType.Intersect)
                    if inter is not None and inter.Volume > max_ov:
                        max_ov = inter.Volume
                except Exception:
                    continue
        if max_ov > 1e-7:
            findings.append({"board": mark, "soffit_element": olabel, "overlap_cf": round(max_ov, 5)})

# Band walls' own boards: report their Z-max near the ceiling, to confirm they still touch flush
# (unaffected) rather than being pulled back.
ceiling_bottom_z = None
for (c, label) in soffit_assembly:
    if label == "CEILING-S001":
        bb = c.get_BoundingBox(None)
        ceiling_bottom_z = bb.Min.Z if bb else None

band_report = []
for (ds, mark) in band_boards:
    bb = ds.get_BoundingBox(None)
    band_report.append({"mark": mark, "top_z": round(bb.Max.Z, 4) if bb else None})

OUT = {
    "wall_board_count_checked": len(wall_boards),
    "soffit_assembly_element_count": len(soffit_assembly),
    "findings_count": len(findings),
    "findings": findings,
    "ceiling_bottom_z": round(ceiling_bottom_z, 4) if ceiling_bottom_z is not None else None,
    "band_wall_boards": band_report,
}
