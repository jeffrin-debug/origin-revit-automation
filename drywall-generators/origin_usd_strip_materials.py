# origin_usd_strip_materials.py
# ---------------------------------------------------------------------------------------------------
# POST-PROCESS for the Omniverse Revit Connector export: remove every Material/Shader prim (the
# generator's colored-subcategory materials, e.g. "ORIGIN Stud"/"ORIGIN Drywall Base") and clear any
# material:binding relationships pointing at them. For a pipeline whose own downstream texture/
# material step (Isaac Sim) replaces these anyway, the exported materials are dead weight - this
# strips them out so the USD is smaller and free of bindings the sim pipeline doesn't use.
#
# It is NON-DESTRUCTIVE: writes a NEW "<name>_nomat.usd" next to the source (same convention as
# origin_usd_hierarchy.py - keep it in the same folder so relative references like ./Families still
# resolve). Geometry (Mesh/Xform) and all naming/metadata are left completely untouched; only
# Material/Shader prims and material:binding relationships are removed.
#
# REQUIRES: usd-core   ->   py -m pip install usd-core
# USAGE:
#   python origin_usd_strip_materials.py                       # uses DEFAULT_SRC below
#   python origin_usd_strip_materials.py "<in.usd>"            # writes "<in>_nomat.usd"
#   python origin_usd_strip_materials.py "<in.usd>" "<out.usd>"
# ---------------------------------------------------------------------------------------------------

import sys, os, shutil
from pxr import Usd

DEFAULT_SRC = r"C:\Users\Origoncad\Documents\Omniverse\Revit\ORIGIN Assembly\ORIGIN Assembly.usd"

MATERIAL_TYPES = ("Material", "Shader")


def strip_materials(src, out):
    shutil.copyfile(src, out)                      # never touch the original
    stage = Usd.Stage.Open(out)

    # 1) clear every material:binding relationship first (targets are about to disappear).
    unbound = 0
    for p in stage.Traverse():
        rel = p.GetRelationship("material:binding")
        if rel and rel.IsValid() and rel.GetTargets():
            rel.ClearTargets(True)
            unbound += 1

    # 2) remove every Material/Shader prim, top-down (removing a parent drops its children too,
    #    so skip anything already covered by an earlier removal in this pass).
    candidates = sorted(
        (p.GetPath() for p in stage.Traverse() if p.GetTypeName() in MATERIAL_TYPES),
        key=lambda pth: len(pth.pathString))
    removed = []
    for pth in candidates:
        if any(pth.HasPrefix(r) for r in removed):
            continue
        if stage.GetPrimAtPath(pth):
            stage.RemovePrim(pth)
            removed.append(pth)

    stage.GetRootLayer().Save()
    return len(removed), unbound


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if len(sys.argv) > 2:
        out = sys.argv[2]
    else:
        base, ext = os.path.splitext(src)
        out = base + "_nomat" + ext
    if not os.path.isfile(src):
        print("Source USD not found:", src)
        return
    print("Source :", src)
    print("Output :", out)
    removed, unbound = strip_materials(src, out)
    print("Material/Shader prims removed:", removed)
    print("material:binding relationships cleared:", unbound)
    print("Size before: {:,} bytes".format(os.path.getsize(src)))
    print("Size after : {:,} bytes".format(os.path.getsize(out)))


if __name__ == "__main__":
    main()
