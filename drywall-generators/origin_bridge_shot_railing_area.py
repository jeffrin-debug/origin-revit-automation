# origin_bridge_shot_railing_area.py
# Verification shot: prove the railing + floor are really visible in the ORIGIN Assembly view.
# Duplicates that view (so its own settings are inherited verbatim), hides the annotation datums
# that were blowing the export extents out, section-boxes the railing area, exports a PNG, then
# DELETES the duplicate. The ORIGIN Assembly view itself is never modified.
import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

VIEW_NAME = "ORIGIN Assembly"
OUT_DIR = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\bridge\shots"
PAD_FT = 2.5

if not os.path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)
for f in os.listdir(OUT_DIR):
    try:
        os.remove(os.path.join(OUT_DIR, f))
    except Exception:
        pass

src = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    try:
        if (not v.IsTemplate) and v.Name == VIEW_NAME:
            src = v
            break
    except Exception:
        pass

info = {"view": VIEW_NAME, "files": [], "error": None}

# Target bbox = the railing plus every floor, so the shot frames exactly what was missing.
targets = []
for bic in (BuiltInCategory.OST_StairsRailing, BuiltInCategory.OST_Railings,
            BuiltInCategory.OST_RailingHandRail, BuiltInCategory.OST_RailingTopRail):
    try:
        for e in (FilteredElementCollector(doc).OfCategory(bic)
                  .WhereElementIsNotElementType()):
            targets.append(e)
    except Exception:
        pass

bb = None
for e in targets:
    try:
        b = e.get_BoundingBox(None)
        if b is None:
            continue
        if bb is None:
            bb = [b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z]
        else:
            bb[0] = min(bb[0], b.Min.X); bb[1] = min(bb[1], b.Min.Y); bb[2] = min(bb[2], b.Min.Z)
            bb[3] = max(bb[3], b.Max.X); bb[4] = max(bb[4], b.Max.Y); bb[5] = max(bb[5], b.Max.Z)
    except Exception:
        pass

info["target_count"] = len(targets)
info["bbox_ft"] = bb

if src is None:
    info["error"] = "source view not found"
elif bb is None:
    info["error"] = "no railing/floor bounding box"
else:
    tmp_id = None
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        tmp_id = src.Duplicate(ViewDuplicateOption.Duplicate)
        tmp = doc.GetElement(tmp_id)
        try:
            tmp.Name = "ORIGIN _tmp_shot"
        except Exception:
            pass
        # The dash-dot level datums are annotation, not model, so the visibility fix never touched
        # them - but ZoomFitType.FitToPage includes their huge extents and shrinks the building to
        # a speck. Hide them in the throwaway view only.
        for bic in (BuiltInCategory.OST_Levels, BuiltInCategory.OST_Grids,
                    BuiltInCategory.OST_SectionBox):
            try:
                cid = ElementId(bic)
                if tmp.CanCategoryBeHidden(cid):
                    tmp.SetCategoryHidden(cid, True)
            except Exception:
                pass
        try:
            sb = BoundingBoxXYZ()
            sb.Min = XYZ(bb[0] - PAD_FT, bb[1] - PAD_FT, bb[2] - PAD_FT)
            sb.Max = XYZ(bb[3] + PAD_FT, bb[4] + PAD_FT, bb[5] + PAD_FT)
            tmp.SetSectionBox(sb)
            tmp.IsSectionBoxActive = True
        except Exception as ex:
            info["section_box_error"] = str(ex)
        doc.Regenerate()
    except Exception as ex:
        info["error"] = "temp view setup failed: " + str(ex)
    finally:
        TransactionManager.Instance.TransactionTaskDone()

    if tmp_id is not None and info.get("error") is None:
        try:
            opts = ImageExportOptions()
            opts.ExportRange = ExportRange.SetOfViews
            ids = List[ElementId]()
            ids.Add(tmp_id)
            opts.SetViewsAndSheets(ids)
            opts.FilePath = os.path.join(OUT_DIR, "railing_area")
            opts.HLRandWFViewsFileType = ImageFileType.PNG
            opts.ShadowViewsFileType = ImageFileType.PNG
            opts.ImageResolution = ImageResolution.DPI_150
            opts.ZoomType = ZoomFitType.FitToPage
            opts.PixelSize = 1600
            doc.ExportImage(opts)
        except Exception as ex:
            info["error"] = "export failed: " + str(ex)

        # Always remove the throwaway view.
        TransactionManager.Instance.EnsureInTransaction(doc)
        try:
            doc.Delete(tmp_id)
            info["temp_view_deleted"] = True
        except Exception as ex:
            info["temp_view_deleted"] = "FAILED: " + str(ex)
        finally:
            TransactionManager.Instance.TransactionTaskDone()

try:
    for f in sorted(os.listdir(OUT_DIR)):
        p = os.path.join(OUT_DIR, f)
        info["files"].append({"file": p, "bytes": os.path.getsize(p)})
except Exception:
    pass

OUT = info
