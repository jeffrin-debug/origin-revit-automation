# save_model.py - save the open model. New (never-saved) models go to models\<name>.rvt, where
# <name> comes from save_model.json {"name": ...} next to this script, else the document title;
# already-saved models are saved in place. Never overwrites an existing file on SaveAs.
import os
import json
from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
OUT_DIR = r"C:\Users\Origoncad\origin_layout_bridge\models"

TransactionManager.Instance.ForceCloseTransaction()   # SaveAs throws if any transaction is open
if doc.PathName:
    doc.Save()
    OUT = {"saved_in_place": doc.PathName}
else:
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR)
    _cfg = os.path.join(os.path.dirname(__file__), "save_model.json")
    name = json.load(open(_cfg))["name"] if os.path.exists(_cfg) else doc.Title
    path = os.path.join(OUT_DIR, name + ".rvt")
    if os.path.exists(path):
        OUT = {"error": "file already exists, not overwritten: " + path}
    else:
        opts = SaveAsOptions()
        opts.OverwriteExistingFile = False
        doc.SaveAs(path, opts)
        OUT = {"saved_as": doc.PathName, "title": doc.Title,
               "size_kb": round(os.path.getsize(path) / 1024.0, 1)}
