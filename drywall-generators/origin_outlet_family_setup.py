# origin_outlet_family_setup.py
# ============================================================
# ONE-TIME SETUP for the electrical outlet boxes (run in a Dynamo Python node, any inputs unused).
#
# Builds a Generic Model family "TM_outlet_box.rfa" with SIX types - the TM junction boxes from
# the user's catalog image - saves it into the repo's families\ folder and loads it into the
# current project. The wall assembly script then places one instance per wall (GENERATE_OUTLETS).
#
#   TM-S44    103 x 103 x 38 mm   (default in the wall script)
#   TM-54151   94 x  94 x 38 mm
#   TM-1102    93 x  94 x 52 mm
#   TM-1299    74 x  74 x 35 mm
#   TM-4040A  105 x 105 x 50 mm
#   TM-SG125   72 x  72 x 21 mm
#
# Geometry approach: one fixed-size box extrusion PER MODEL, each bound to a Yes/No family
# parameter via AssociateElementParameterToFamilyParameter on the extrusion's Visible parameter;
# each type turns exactly one box on. (Reliable to build via API - no labeled sketch dimensions.)
# Family origin = center of the box footprint, Z=0 at the box BOTTOM, footprint X = box width
# (along the wall), Y = box depth (into the wall).
# ============================================================

import clr
import os

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
app = doc.Application

RFA_DIR = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\families"
RFA_PATH = os.path.join(RFA_DIR, "TM_outlet_box.rfa")
FAMILY_NAME = "TM_outlet_box"

MM = 1.0 / 304.8   # mm -> feet

# (type name, width mm, height mm, depth mm) - width x height = face, depth goes into the wall
MODELS = [
    ("TM-S44", 103.0, 103.0, 38.0),
    ("TM-54151", 94.0, 94.0, 38.0),
    ("TM-1102", 93.0, 94.0, 52.0),
    ("TM-1299", 74.0, 74.0, 35.0),
    ("TM-4040A", 105.0, 105.0, 50.0),
    ("TM-SG125", 72.0, 72.0, 21.0),
]

result = {"template": "", "rfa_path": "", "types": [], "loaded": False,
          "warnings": [], "notes": []}
warnings = result["warnings"]


def find_template():
    """Locate a Generic Model family template across installed Revit versions."""
    candidates = []
    base = r"C:\ProgramData\Autodesk"
    try:
        for d in sorted(os.listdir(base), reverse=True):
            if not d.startswith("RVT"):
                continue
            for lang in ("English-Imperial", "English", "ENU"):
                p = os.path.join(base, d, "Family Templates", lang, "Generic Model.rft")
                if os.path.exists(p):
                    candidates.append(p)
                p = os.path.join(base, d, "Family Templates", lang, "Metric Generic Model.rft")
                if os.path.exists(p):
                    candidates.append(p)
    except Exception as ex:
        warnings.append("Template scan failed: {}".format(ex))
    try:
        p = app.FamilyTemplatePath
        for name in ("Generic Model.rft", "Metric Generic Model.rft"):
            q = os.path.join(p, name)
            if os.path.exists(q) and q not in candidates:
                candidates.insert(0, q)
    except Exception:
        pass
    return candidates[0] if candidates else None


def box_curves(w_ft, d_ft):
    """Rectangle centered on the origin: X = width, Y = depth."""
    hx = w_ft / 2.0
    hy = d_ft / 2.0
    pts = [XYZ(-hx, -hy, 0), XYZ(hx, -hy, 0), XYZ(hx, hy, 0), XYZ(-hx, hy, 0)]
    arr = CurveArray()
    for i in range(4):
        arr.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    caa = CurveArrArray()
    caa.Append(arr)
    return caa


def main():
    template = find_template()
    if template is None:
        warnings.append("No Generic Model.rft template found under ProgramData\\Autodesk\\RVT* - "
                        "set the path manually in find_template().")
        return
    result["template"] = template

    # Family docs cannot be created while the Dynamo transaction is open on the project doc.
    try:
        TransactionManager.Instance.ForceCloseTransaction()
    except Exception:
        pass

    famdoc = app.NewFamilyDocument(template)
    try:
        t = Transaction(famdoc, "ORIGIN outlet box family")
        t.Start()
        try:
            fm = famdoc.FamilyManager
            plane = Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero)
            sk = SketchPlane.Create(famdoc, plane)

            vis_params = []
            for (name, w_mm, h_mm, d_mm) in MODELS:
                ext = famdoc.FamilyCreate.NewExtrusion(
                    True, box_curves(w_mm * MM, d_mm * MM), sk, h_mm * MM)
                fp = fm.AddParameter("Show {}".format(name),
                                     GroupTypeId.Visibility,
                                     SpecTypeId.Boolean.YesNo, False)
                vis = ext.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
                fm.AssociateElementParameterToFamilyParameter(vis, fp)
                vis_params.append((name, fp))

            for (name, _w, _h, _d) in MODELS:
                fm.NewType(name)
                fm.CurrentType = [ft for ft in fm.Types if ft.Name == name][0]
                for (pname, fp) in vis_params:
                    fm.Set(fp, 1 if pname == name else 0)
                result["types"].append(name)
            t.Commit()
        except Exception as ex:
            t.RollBack()
            raise

        if not os.path.exists(RFA_DIR):
            os.makedirs(RFA_DIR)
        sao = SaveAsOptions()
        sao.OverwriteExistingFile = True
        famdoc.SaveAs(RFA_PATH, sao)
        result["rfa_path"] = RFA_PATH
    finally:
        try:
            famdoc.Close(False)
        except Exception:
            pass

    # Load into the current project (skip if already present - delete the family in Revit's
    # Project Browser first if you need to reload a rebuilt version).
    already = False
    for f in FilteredElementCollector(doc).OfClass(Family):
        if f.Name == FAMILY_NAME:
            already = True
            break
    if already:
        result["notes"].append("Family already loaded in the project; not reloaded. "
                               "Delete it in the Project Browser and re-run to refresh.")
        result["loaded"] = True
    else:
        TransactionManager.Instance.EnsureInTransaction(doc)
        try:
            result["loaded"] = bool(doc.LoadFamily(RFA_PATH))
        finally:
            TransactionManager.Instance.TransactionTaskDone()
        if not result["loaded"]:
            warnings.append("doc.LoadFamily returned False - load families\\TM_outlet_box.rfa "
                            "manually via Insert > Load Family.")


try:
    main()
except Exception as ex:
    warnings.append("FATAL: {}".format(ex))

OUT = result
