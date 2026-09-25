"""Thorough end-to-end verification of the whole pipeline state."""
import ast
import hashlib
import json
import os
import py_compile
import sys

REPO = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces"
DYN = os.path.join(REPO, "dynamo", "Automated Panels and Studs no screws - wall and ceilings.dyn")
DOC_DYN = r"C:\Users\Origoncad\Documents\Automated Panels and Studs no screws - wall and ceilings.dyn"

WALLS = ["origin_wall_assembly_v4_phase2.py", "origin_wall_assembly_v4_phase2_r2025.py",
         "origin_wall_assembly_v4_phase2_noscrews.py",
         "origin_wall_assembly_v4_phase2_notaper_noscrew_nojoint.py"]
CEILS = ["origin_ceiling_assembly_v1.py", "origin_ceiling_assembly_v1_noscrews.py",
         "origin_soffit_assembly_v1.py",
         "origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py"]
OTHER = ["origin_outlet_family_setup.py", "origin_ceiling_manifest_check.py",
         "origin_beam_assembly_v1.py", "origin_column_assembly_v1.py"]

WALL_FEATURES = ["GENERATE_OUTLETS", "def emit_outlet(", "\"outlets\": outlet_records",
                 "DRYWALL_CORNER_WRAP_BY_FACE", "ORIGIN_EO_PLACED"]
CEIL_FEATURES = ["CEILING_PER_ROOM", "SOFFIT_SEPARATE_FLOW", "truly severs",
                 "SolidUtils.SplitVolumes", "get_BoundingBox(None)", "MAXIMIZE_WHOLE_PANELS"]

WALL_SLICES = [("emit_outlet", "\ndef emit_outlet(", "\ndef delete_previous("),
               ("outlet-settings", "GENERATE_OUTLETS = True", "OUTLET_RFA_PATH = r\"")]
CEIL_SLICES = [("emit-region", "                if is_soffit:\n", "\n\n                result[\"ceilings_processed\"] += 1"),
               ("emit_drywall", "\ndef emit_drywall(", "\ndef simplify_rectilinear("),
               ("soffit-funcs", "\ndef simplify_rectilinear(", "\n# ============================================================\n# MAIN"),
               ("emit_furring", "\ndef emit_furring(", "\ndef furring_lines(")]

fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def norm(path):
    return open(path, encoding="utf-8").read().replace("\r\n", "\n")


def get_slice(text, a, b):
    if text.count(a) != 1 or text.count(b) != 1:
        return None
    i, j = text.index(a), text.index(b)
    return text[i:j] if j > i else None


# 1. every script compiles
for f in WALLS + CEILS + OTHER:
    p = os.path.join(REPO, f)
    try:
        py_compile.compile(p, doraise=True)
        check(True, f"compiles: {f}")
    except Exception as ex:
        check(False, f"compiles: {f} ({ex})")

# 2. feature presence per build
for f in WALLS:
    src = norm(os.path.join(REPO, f))
    missing = [k for k in WALL_FEATURES if k not in src]
    check(not missing, f"wall features in {f}" + (f" MISSING {missing}" if missing else ""))
for f in CEILS:
    src = norm(os.path.join(REPO, f))
    missing = [k for k in CEIL_FEATURES if k not in src]
    check(not missing, f"ceiling features in {f}" + (f" MISSING {missing}" if missing else ""))

# 3. cross-build byte-equality of critical regions
wref = norm(os.path.join(REPO, WALLS[3]))
for (label, a, b) in WALL_SLICES:
    ref = get_slice(wref, a, b)
    check(ref is not None, f"wall slice '{label}' resolvable in notaper")
    for f in WALLS[:3]:
        s = get_slice(norm(os.path.join(REPO, f)), a, b)
        check(s == ref, f"wall '{label}' identical: {f}")
cref = norm(os.path.join(REPO, CEILS[3]))
for (label, a, b) in CEIL_SLICES:
    ref = get_slice(cref, a, b)
    check(ref is not None, f"ceiling slice '{label}' resolvable in notaper")
    for f in CEILS[:3]:
        s = get_slice(norm(os.path.join(REPO, f)), a, b)
        check(s == ref, f"ceiling '{label}' identical: {f}")

# 4. graph nodes: valid JSON, parse, byte-identical to the active builds
j = json.load(open(DYN, encoding="utf-8-sig"))
check(True, "graph JSON valid")
for n in j["Nodes"]:
    if "Python" not in n.get("ConcreteType", ""):
        continue
    code = n["Code"]
    try:
        ast.parse(code)
        okp = True
    except Exception:
        okp = False
    nid = n["Id"][:8]
    check(okp, f"graph node {nid} parses")
    ncode = code.replace("\r\n", "\n").strip()
    if nid == "b3bcefac":
        check(ncode == wref.strip(), "wall node byte-identical to notaper wall build")
        check("GENERATE_OUTLETS" in code, "wall node carries outlet feature")
    elif nid == "44442cfb":
        check(ncode == cref.strip(), "ceiling node byte-identical to notaper ceiling build")
        check('PROCESS_MODE = "ceilings"' in code, "ceiling node is ceilings-mode")
    elif 'PROCESS_MODE = "soffits"' in code:
        check(ncode == norm(os.path.join(REPO, "origin_soffit_assembly_v1.py")).strip(),
              "soffit node byte-identical to soffit build")
    elif "ORIGIN_BEAM_V1" in code:
        check(ncode == norm(os.path.join(REPO, "origin_beam_assembly_v1.py")).strip(),
              "beam node byte-identical to beam build")
    elif "ORIGIN_COLUMN_V1" in code:
        check(ncode == norm(os.path.join(REPO, "origin_column_assembly_v1.py")).strip(),
              "column node byte-identical to column build")

# 5. Documents mirror identical
h1 = hashlib.md5(open(DYN, "rb").read()).hexdigest()
h2 = hashlib.md5(open(DOC_DYN, "rb").read()).hexdigest() if os.path.exists(DOC_DYN) else None
check(h1 == h2, "Documents mirror byte-identical to repo graph")

# 6. family status (informational - user must run setup once)
rfa = os.path.join(REPO, "families", "TM_outlet_box.rfa")
print(("INFO families\\TM_outlet_box.rfa exists" if os.path.exists(rfa)
       else "INFO families\\TM_outlet_box.rfa NOT YET CREATED - user must run origin_outlet_family_setup.py once"))

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
