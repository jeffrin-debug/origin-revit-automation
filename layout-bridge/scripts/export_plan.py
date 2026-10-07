# export_plan.py - export the L1 floor plan as a PNG so the layout can be checked from outside Revit.
import os
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument
OUT_DIR = r"C:\Users\Origoncad\origin_layout_bridge\renders"
if not os.path.exists(OUT_DIR):
    os.makedirs(OUT_DIR)

view = next(v for v in FilteredElementCollector(doc).OfClass(ViewPlan)
            if not v.IsTemplate and v.ViewType == ViewType.FloorPlan and v.GenLevel is not None
            and v.GenLevel.Name == "L1")
opts = ImageExportOptions()
opts.ExportRange = ExportRange.SetOfViews
opts.SetViewsAndSheets([view.Id])
opts.FilePath = os.path.join(OUT_DIR, "plan")
opts.ZoomType = ZoomFitType.FitToPage
opts.PixelSize = 8000
opts.HLRandWFViewsFileType = ImageFileType.PNG
opts.ImageResolution = ImageResolution.DPI_300
doc.ExportImage(opts)
OUT = {"view": view.Name, "files": [f for f in os.listdir(OUT_DIR)]}
