# shot_assembly_active.py - render the ORIGIN Assembly view of the ACTIVE document.
# Duplicates the view so the real one is never modified, hides the level/grid datums whose huge
# extents otherwise shrink the building to a speck under ZoomFitType.FitToPage, section-boxes to
# the walls, exports a PNG, then deletes the duplicate.
import clr
import json
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

VIEW_NAME = "ORIGIN Assembly"
OUT_DIR = r"C:\Users\Origoncad\origin_pipeline\_reports\shots"
PAD_FT = 3.0

cfg_path = r"C:\Users\Origoncad\origin_pipeline\_shot_config.json"
ZOOM = None
if os.path.exists(cfg_path):
    try:
        ZOOM = json.load(open(cfg_path)).get("zoom")   # optional [x0,y0,x1,y1] in feet
    except Exception:
        ZOOM = None

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

info = {"doc": doc.Title, "view": VIEW_NAME, "files": [], "error": None}

bb = None
for w in FilteredElementCollector(doc).OfClass(Wall).WhereElementIsNotElementType():
    try:
        b = w.get_BoundingBox(None)
        if b is None:
            continue
        if bb is None:
            bb = [b.Min.X, b.Min.Y, b.Min.Z, b.Max.X, b.Max.Y, b.Max.Z]
        else:
            bb[0] = min(bb[0], b.Min.X); bb[1] = min(bb[1], b.Min.Y); bb[2] = min(bb[2], b.Min.Z)
            bb[3] = max(bb[3], b.Max.X); bb[4] = max(bb[4], b.Max.Y); bb[5] = max(bb[5], b.Max.Z)
    except Exception:
        pass

if src is None:
    info["error"] = "view not found"
elif bb is None:
    info["error"] = "no walls"
else:
    if ZOOM:
        bb[0], bb[1], bb[3], bb[4] = ZOOM[0], ZOOM[1], ZOOM[2], ZOOM[3]
    info["bbox_ft"] = [round(v, 2) for v in bb]
    tmp_id = None
    TransactionManager.Instance.EnsureInTransaction(doc)
    try:
        tmp_id = src.Duplicate(ViewDuplicateOption.Duplicate)
        tmp = doc.GetElement(tmp_id)
        try:
            tmp.Name = "ORIGIN _tmp_shot"
        except Exception:
            pass
        for bic in (BuiltInCategory.OST_Levels, BuiltInCategory.OST_Grids):
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
            opts.FilePath = os.path.join(OUT_DIR, "assembly")
            opts.HLRandWFViewsFileType = ImageFileType.PNG
            opts.ShadowViewsFileType = ImageFileType.PNG
            opts.ImageResolution = ImageResolution.DPI_150
            opts.ZoomType = ZoomFitType.FitToPage
            opts.PixelSize = 1800
            doc.ExportImage(opts)
        except Exception as ex:
            info["error"] = "export failed: " + str(ex)
        TransactionManager.Instance.EnsureInTransaction(doc)
        try:
            doc.Delete(tmp_id)
            info["temp_view_deleted"] = True
        except Exception as ex:
            info["temp_view_deleted"] = "FAILED " + str(ex)
        finally:
            TransactionManager.Instance.TransactionTaskDone()

try:
    for f in sorted(os.listdir(OUT_DIR)):
        info["files"].append(os.path.join(OUT_DIR, f))
except Exception:
    pass

OUT = info
