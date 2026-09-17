# inspect_output.py
# ============================================================
# Independent proof: open a FINISHED file from out\ as a background document and list what is
# actually in it. Reads nothing from the rebuild run - this is the saved file speaking for
# itself. Read-only, no transaction, closed without saving.
# ============================================================

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

ROOT = _paths["CEILING_ROOT"]
PAIRS = [
    ("BEFORE (original)", os.path.join(_paths["INPUT_DIR"], "B1-a.rvt")),
    ("AFTER  (rebuilt)", os.path.join(ROOT, "out", "B1-a.rvt")),
]

uiapp = DocumentManager.Instance.CurrentUIApplication
app = uiapp.Application


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


out = {}
for label, path in PAIRS:
    if not os.path.exists(path):
        out[label] = {"error": "missing: " + path}
        continue
    nd = None
    try:
        TransactionManager.Instance.ForceCloseTransaction()
        mp = ModelPathUtils.ConvertUserVisiblePathToModelPath(path)
        nd = app.OpenDocumentFile(mp, OpenOptions())

        rows = []
        for c in FilteredElementCollector(nd).OfClass(Ceiling).WhereElementIsNotElementType():
            row = {"id": eid_value(c.Id)}
            try:
                row["category"] = c.Category.Name
            except Exception:
                row["category"] = "?"
            try:
                p = c.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED)
                row["area_sf"] = round(p.AsDouble(), 2) if p else None
            except Exception:
                row["area_sf"] = None
            try:
                bb = c.get_BoundingBox(None)
                row["bottom_mm"] = round(bb.Min.Z * 304.8, 1) if bb else None
            except Exception:
                row["bottom_mm"] = None
            rows.append(row)
        rows.sort(key=lambda r: -(r.get("area_sf") or 0))

        out[label] = {
            "file": path,
            "ceiling_count": len(rows),
            "total_area_sf": round(sum(r.get("area_sf") or 0 for r in rows), 2),
            "ceilings": rows,
        }
    except Exception as ex:
        out[label] = {"error": str(ex)}
    finally:
        try:
            if nd is not None:
                nd.Close(False)
        except Exception:
            pass
        try:
            TransactionManager.Instance.ForceCloseTransaction()
        except Exception:
            pass

OUT = out
