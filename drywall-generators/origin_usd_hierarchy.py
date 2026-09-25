# origin_usd_hierarchy.py
# ---------------------------------------------------------------------------------------------------
# POST-PROCESS for the Omniverse Revit Connector export: turn the FLAT prim list into a collapsible
# hide/unhide HIERARCHY in the USD stage, driven by the generator's BIM:Instance:Mark nomenclature -
# AND rename each element (and its Mesh geometry) from the connector's generic tn__<id>_/Mesh_<n>
# names to the real DP-/ST-/SC- nomenclature (USD-safe: hyphens -> underscores), so both the
# Omniverse/Isaac Sim outliner AND any downstream tooling (e.g. a texture pipeline that follows stud
# geometry to place screws) can identify elements by name, not by opaque Revit element id.
#
# WHY: the connector exports every generated element as a flat Xform under one "GenericModels" scope,
# named by Revit element id (tn__<id>_), with its actual renderable geometry as a child Mesh prim
# that gets an unrelated auto-generated name (Mesh_<n>); our nomenclature (DP/ST/SC-<host>-...) rides
# along only as the BIM:Instance:Mark attribute. A flat, opaquely-named stage can't be collapsed/
# hidden by wall or type, and can't be identified by eye or by name in a downstream pipeline. This
# tool reparents AND renames each element under real, named group Xforms so toggling a branch's eye
# in the Omniverse Stage hides/unhides the whole group, and every leaf reads as e.g. DP_008_002B /
# ST_009_001 instead of tn__529375_ / Mesh_528388:
#
#   <defaultPrim>/Origin/
#     Wall_001/   Drywall/FaceA   Drywall/FaceB   Framing/Stud  Framing/Track  Framing/Header ...
#     Wall_002/   ...
#     Ceiling_C001/  Drywall   Furring   Mains   Hangers
#     Soffit_S001/   Drywall   Furring   Mains   Hangers
#     Column_K001/   Drywall
#     Beam_B001/     Drywall
#     _Unsorted/     (any prim whose Mark didn't parse)
#
# Every renamed prim also gets a new BIM:Instance:MemberType attribute (STUD/TRACK/HEADER/SILL/
# KINGSTUD/CRIPPLE/FURRING/MAIN/HANGER/DRYWALL/SCREW), parsed once from the existing Comments string,
# so a downstream pipeline can filter by real type without re-parsing Comments itself - e.g. "only
# real studs, not tracks/headers" for a screw-placement pass.
#
# It is NON-DESTRUCTIVE: writes a NEW "<name>_hierarchy.usd" next to the source (which references the
# same ./Families, so keep it in the same folder). Re-run after each re-export.
#
# REQUIRES: usd-core   ->   py -m pip install usd-core   (standalone; no Omniverse/Revit needed)
# USAGE:
#   python origin_usd_hierarchy.py                       # uses DEFAULT_SRC below
#   python origin_usd_hierarchy.py "<in.usd>"            # writes "<in>_hierarchy.usd"
#   python origin_usd_hierarchy.py "<in.usd>" "<out.usd>"
#
# NOTES / LIMITS:
#   - Per-TYPE hide/unhide (all studs, all drywall, ...) also works WITHOUT this tool via the colored
#     subcategories the generator makes (the connector emits them under /Looks + as material groups).
#     This tool adds the per-WALL / per-ROOM / per-FACE / per-MEMBER-TYPE grouping AND naming that
#     colors/materials alone can't give you.
#   - Material bindings are absolute (/.../Looks/...) so they survive the move; unaffected by renaming.
#   - Reparent+rename of each element Xform is one atomic Sdf batch on the root layer (with a
#     per-prim NamespaceEditor fallback that isolates any bad entry), applied and saved FIRST. Mesh
#     child renaming is a SEPARATE second batch run afterward, once the element paths are stable -
#     avoids any ambiguity about ordering a parent rename together with a descendant rename in one
#     batch. A element can have more than one Mesh child (seen on a real export: 1081 meshes across
#     1018 elements) - each gets an index suffix (_0, _1, ...) when there's more than one.
# ---------------------------------------------------------------------------------------------------

import sys, os, re, collections, shutil
from pxr import Usd, UsdGeom, Sdf

DEFAULT_SRC = r"C:\Users\Origoncad\Documents\Omniverse\Revit\ORIGIN Assembly\ORIGIN Assembly.usd"

MARK_ATTR = "BIM:Instance:Mark"
COMMENTS_ATTR = "BIM:Instance:Comments"
MEMBER_TYPE_ATTR = "BIM:Instance:MemberType"
NOMEN = re.compile(r"^(DP|ST|SC)-")

# The real element kind, as embedded verbatim (4th |-token) in Comments by the generator scripts -
# see ds_comment()/board_comment() in the wall/ceiling/soffit builds.
KNOWN_KINDS = ("STUD", "KINGSTUD", "JACK", "CRIPPLE", "TRACK", "HEADER", "SILL",
               "FURRING", "MAIN", "HANGER", "DRYWALL", "SCREW", "DOOR", "WINDOW", "OUTLET")

# Wall-framing sub-groups under Framing/ - mirrors the Furring/Mains/Hangers split ceilings already
# get, just applied to the wall side (which previously dumped every framing kind into one bucket).
WALL_FRAMING_GROUP = {
    "STUD": "Stud", "KINGSTUD": "KingStud", "JACK": "Jack", "CRIPPLE": "Cripple",
    "TRACK": "Track", "HEADER": "Header", "SILL": "Sill",
}
CEILING_FRAMING_GROUP = {"FURRING": "Furring", "MAIN": "Mains", "HANGER": "Hangers"}


def sanitize(tok):
    """USD prim names must be valid identifiers."""
    return re.sub(r"[^A-Za-z0-9_]", "_", tok)


def member_kind(comments):
    """The real element kind (STUD/TRACK/.../DRYWALL/...) from Comments, or None if it doesn't
    parse / isn't one of the known kinds."""
    for p in [x.strip() for x in (comments or "").split("|")]:
        if p in KNOWN_KINDS:
            return p
    return None


def target_group(mark, comments):
    """Sub-path (list of prim names under /Origin) for a Mark, or None if it doesn't parse.
    Mark forms: DP-<host>-<seq>[A|B], ST-<host>-<seq>, SC-<host>-<seq>. host = NNN (wall),
    C### (ceiling), S### (soffit), K### (column), or B### (beam)."""
    parts = mark.split("-")
    if len(parts) < 3:
        return None
    prefix, host, seqface = parts[0], parts[1], parts[2]
    if host[:1] == "C":
        hostgrp = "Ceiling_" + host
    elif host[:1] == "S":
        hostgrp = "Soffit_" + host
    elif host[:1] == "K":
        hostgrp = "Column_" + host
    elif host[:1] == "B":
        hostgrp = "Beam_" + host
    elif host.isdigit():
        hostgrp = "Wall_" + host
    else:
        return None
    is_ceiling = host[:1] in ("C", "S")
    if prefix == "DP":
        if is_ceiling:
            return [hostgrp, "Drywall"]
        face = seqface[-1:] if seqface[-1:] in ("A", "B") else ""
        return [hostgrp, "Drywall", "Face" + face] if face else [hostgrp, "Drywall"]
    if prefix == "SC":
        return [hostgrp, "Screws"]
    if prefix == "ST":
        kind = member_kind(comments)
        if is_ceiling:
            return [hostgrp, CEILING_FRAMING_GROUP.get(kind, "Framing")]
        if kind in WALL_FRAMING_GROUP:
            return [hostgrp, "Framing", WALL_FRAMING_GROUP[kind]]
        return [hostgrp, "Framing"]
    return None


def build_hierarchy(src, out):
    shutil.copyfile(src, out)                      # never touch the original
    stage = Usd.Stage.Open(out)
    root = stage.GetDefaultPrim() or stage.GetPseudoRoot().GetChildren()[0]
    origin = root.GetPath().AppendChild("Origin")

    # 1) collect (oldPath, group-names, newName) for every nomenclature-bearing prim, and stamp a
    #    BIM:Instance:MemberType attribute while we still have the Comments string in hand (this
    #    attribute rides along with the prim through the reparent/rename below, same as Mark today).
    moves, counts = [], collections.Counter()
    for p in stage.Traverse():
        a = p.GetAttribute(MARK_ATTR)
        mark = a.Get() if a and a.IsValid() else None
        if not (isinstance(mark, str) and NOMEN.match(mark)):
            continue
        ca = p.GetAttribute(COMMENTS_ATTR)
        comments = ca.Get() if ca and ca.IsValid() else ""
        grp = target_group(mark, comments) or ["_Unsorted"]
        grp = [sanitize(g) for g in grp]
        kind = member_kind(comments) or mark.split("-")[0]
        p.CreateAttribute(MEMBER_TYPE_ATTR, Sdf.ValueTypeNames.String).Set(kind)
        moves.append((p.GetPath(), grp, sanitize(mark)))
        counts["/".join(grp)] += 1
    if not moves:
        print("No prims with a %s of DP/ST/SC-... found. Is this an Origin export?" % MARK_ATTR)
        return None, counts

    # 2) pre-create the group Xforms (destinations must exist before the reparent)
    UsdGeom.Xform.Define(stage, origin)
    gpaths = set()
    for _, grp, _ in moves:
        acc = origin
        for g in grp:
            acc = acc.AppendChild(g)
            gpaths.add(acc)
    for gp in sorted(gpaths, key=lambda x: x.pathString):
        UsdGeom.Xform.Define(stage, gp)

    def newpath(grp, name):
        acc = origin
        for g in grp:
            acc = acc.AppendChild(g)
        return acc.AppendChild(name)

    # 3) reparent + rename each element Xform - one atomic Sdf batch on the root layer, with a
    #    per-prim fallback. A differing leaf name on either side of a namespace edit does a rename
    #    and a move in the same op, so this is the same mechanism as before, just with a real name.
    layer = stage.GetRootLayer()
    edit = Sdf.BatchNamespaceEdit()
    for oldp, grp, name in moves:
        edit.Add(oldp.pathString, newpath(grp, name).pathString)
    ok = fail = 0
    if layer.Apply(edit):
        ok = len(moves)
    else:
        ed = Usd.NamespaceEditor(stage)
        for oldp, grp, name in moves:
            try:
                if ed.MovePrimAtPath(oldp.pathString, newpath(grp, name).pathString) and ed.ApplyEdits():
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
    stage.GetRootLayer().Save()

    # 4) rename each element's own Mesh descendant(s) to match, as a SEPARATE pass now that the
    #    element paths are stable (avoids ordering ambiguity within one batch). Re-traverses the
    #    SAME stage - element paths changed above, but Mark/MemberType rode along with the move, so
    #    they're found again at their new location by the same attribute check.
    mesh_pairs = []
    for p in stage.Traverse():
        a = p.GetAttribute(MARK_ATTR)
        mark = a.Get() if a and a.IsValid() else None
        if not (isinstance(mark, str) and NOMEN.match(mark)):
            continue
        mt = p.GetAttribute(MEMBER_TYPE_ATTR)
        kind_val = mt.Get() if mt and mt.IsValid() else None
        meshes = sorted(
            (d for d in Usd.PrimRange(p) if d.GetPath() != p.GetPath() and d.IsA(UsdGeom.Mesh)),
            key=lambda d: d.GetPath().pathString)
        base = sanitize(mark)
        for i, m in enumerate(meshes):
            new_name = base if len(meshes) == 1 else "{}_{}".format(base, i)
            newp = m.GetPath().GetParentPath().AppendChild(new_name)
            if newp == m.GetPath():
                continue
            if kind_val:
                m.CreateAttribute(MEMBER_TYPE_ATTR, Sdf.ValueTypeNames.String).Set(kind_val)
            mesh_pairs.append((m.GetPath().pathString, newp.pathString))

    mesh_ok = mesh_fail = 0
    if mesh_pairs:
        medit = Sdf.BatchNamespaceEdit()
        for oldps, newps in mesh_pairs:
            medit.Add(oldps, newps)
        if layer.Apply(medit):
            mesh_ok = len(mesh_pairs)
        else:
            ed = Usd.NamespaceEditor(stage)
            for oldps, newps in mesh_pairs:
                try:
                    if ed.MovePrimAtPath(oldps, newps) and ed.ApplyEdits():
                        mesh_ok += 1
                    else:
                        mesh_fail += 1
                except Exception:
                    mesh_fail += 1
        stage.GetRootLayer().Save()

    return (ok, fail, mesh_ok, mesh_fail), counts


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if len(sys.argv) > 2:
        out = sys.argv[2]
    else:
        base, ext = os.path.splitext(src)
        out = base + "_hierarchy" + ext
    if not os.path.isfile(src):
        print("Source USD not found:", src)
        return
    print("Source :", src)
    print("Output :", out)
    res, counts = build_hierarchy(src, out)
    if res is None:
        return
    ok, fail, mesh_ok, mesh_fail = res
    print("Elements reparented+renamed ok:", ok, " failed:", fail)
    print("Mesh children renamed ok:", mesh_ok, " failed:", mesh_fail)
    print("Groups created:")
    for k in sorted(counts):
        print("   %-32s %d" % (k, counts[k]))
    print("\nOpen the *_hierarchy.usd in Omniverse/Isaac; collapse or toggle the eye on any")
    print("/Origin/Wall_### (or Ceiling_/Soffit_/Column_/Beam_) branch to hide/unhide that group.")
    print("Every element and its geometry now reads as its real DP_/ST_/SC_ name, and carries a")
    print("BIM:Instance:MemberType attribute (STUD/TRACK/HEADER/... ) for filtering by real type.")


if __name__ == "__main__":
    main()
