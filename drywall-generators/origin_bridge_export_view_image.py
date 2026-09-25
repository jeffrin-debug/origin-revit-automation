# origin_bridge_export_view_image.py - READ-ONLY (no document modification).
# Export the ORIGIN Assembly 3D view to a PNG so the visibility fix can be checked on screen
# instead of only through category counters.
import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

VIEW_NAME = "ORIGIN Assembly"
OUT_DIR = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\bridge\shots"

if not os.path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)

view = None
for v in FilteredElementCollector(doc).OfClass(View3D):
    try:
        if (not v.IsTemplate) and v.Name == VIEW_NAME:
            view = v
            break
    except Exception:
        pass

if view is None:
    OUT = {"error": "view not found: " + VIEW_NAME}
else:
    # Clear anything already in the folder so the new file is unambiguous.
    for f in os.listdir(OUT_DIR):
        try:
            os.remove(os.path.join(OUT_DIR, f))
        except Exception:
            pass

    base = os.path.join(OUT_DIR, "origin_assembly")
    opts = ImageExportOptions()
    opts.ExportRange = ExportRange.SetOfViews
    ids = List[ElementId]()
    ids.Add(view.Id)
    opts.SetViewsAndSheets(ids)
    opts.FilePath = base
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ImageResolution = ImageResolution.DPI_150
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = 1800

    err = None
    try:
        doc.ExportImage(opts)
    except Exception as ex:
        err = str(ex)

    made = []
    try:
        for f in sorted(os.listdir(OUT_DIR)):
            p = os.path.join(OUT_DIR, f)
            made.append({"file": p, "bytes": os.path.getsize(p)})
    except Exception:
        pass

    OUT = {
        "view": VIEW_NAME,
        "view_id": view.Id.IntegerValue if hasattr(view.Id, "IntegerValue") else view.Id.Value,
        "detail_level": str(view.DetailLevel),
        "display_style": str(view.DisplayStyle),
        "export_error": err,
        "files": made,
    }
