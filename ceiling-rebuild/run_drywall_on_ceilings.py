# run_drywall_on_ceilings.py
# ============================================================
# Run the EXISTING drywall panel generator against the per-room ceilings this project builds.
#
# Nothing in the drywall repo is modified. That generator takes its ceilings from IN[0] (its
# PROCESS_ALL_CEILINGS_IF_NONE_SELECTED is False, and driven from a bridge there is no UI
# selection to fall back on), so this wrapper simply collects the document's Ceiling elements
# and hands them over, then execs the generator's own source.
#
# Its other inputs - IN[5] delete-previous, IN[6] drywall, IN[8] screws - are left as None so
# the generator's own defaults apply (furring + drywall on, screws off, previous output
# cleaned up via its APP_ID).
#
# The generator manages its own transaction (TransactionManager.EnsureInTransaction), so send
# this with "transaction": false. Its output is DirectShapes tagged ORIGIN_CEILING_V1, so
# re-running replaces rather than duplicates.
# ============================================================

import clr
import json
import os
import time
import traceback

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager


# Paths resolve from this file's own location - see origin_paths.py. Nothing below is tied to
# the machine this was written on.
_paths = {"__name__": "origin_paths"}
_pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
_paths["__file__"] = _pp
exec(compile(open(_pp).read(), _pp, "exec"), _paths)

REPO = _paths["DRYWALL_REPO"]
GENERATOR = os.path.join(REPO, "origin_ceiling_assembly_v1_notaper_noscrew_nojoint.py")

# Make the ceiling boards follow the WALL script's layout rules.
#
# Diffing the two config blocks, this is the only genuine layout difference. The ceiling script
# sets MAXIMIZE_WHOLE_PANELS = True, which kills the odd-row stagger so every course starts at
# the region origin and joints line up row-to-row - added 2026-07-16 on the request "I want 4x8
# drywall everywhere possible". The wall script has no such flag: it always staggers odd courses.
#
# Everything else that differs is not a layout difference: LAYER_V_STAGGER_FT is 2.0 ft in both
# (walls call the short dimension HEIGHT, ceilings WIDTH), the SCREW_*/TAPER_* values are equal
# and merely written as 0.5/12.0 vs 0.5*IN_FT, SCREW_SPACING is deliberately tighter on ceilings
# (12" vs 16" OC, per code - and screws are off in this build), and the wall-only JOINT_CLEAR /
# AVOID_JOINTS_AT_JAMBS / TRIM_AT_CORNERS settings concern jambs and wall corners, for which the
# ceiling script already has FIXTURE_CLEARANCE_FT, COLUMN_BEAM_CLEARANCE_FT and
# CLIP_CEILING_AT_WALLS.
#
# Applied by patching the assignment in the source STRING before exec - the repo file itself is
# never modified.
# As of 2026-09-16 the generator itself carries MAXIMIZE_WHOLE_PANELS = False, so the wall-style
# stagger is now the default on every route into it - this wrapper, the Dynamo pipeline graph,
# everything. Nothing needs overriding. The mechanism is kept because it is the safe way to try
# a layout change: it patches the source string in memory and never touches the repo file.
FOLLOW_WALL_LAYOUT = True
OVERRIDES = {}

# Asserted after the source is read, so a silent revert in the repo cannot go unnoticed.
EXPECTED = {"MAXIMIZE_WHOLE_PANELS": "False"}

ROOT = _paths["CEILING_ROOT"]
REPORT_DIR = os.path.join(ROOT, "out", "_reports")

doc = DocumentManager.Instance.CurrentDBDocument
res = {"doc": doc.Title, "generator": os.path.basename(GENERATOR)}
t0 = time.time()


def eid_value(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def count_app_shapes():
    """DirectShapes the generator tags with its own APP_ID, i.e. its output."""
    n = 0
    try:
        for ds in FilteredElementCollector(doc).OfClass(DirectShape).WhereElementIsNotElementType():
            try:
                if "ORIGIN_CEILING" in (ds.ApplicationId or ""):
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return n


try:
    if not os.path.exists(GENERATOR):
        raise Exception("generator not found: " + GENERATOR)

    ceilings = []
    for c in FilteredElementCollector(doc).OfClass(Ceiling).WhereElementIsNotElementType():
        ceilings.append(c)
    res["ceilings_passed_in"] = len(ceilings)
    res["ceiling_ids"] = [eid_value(c.Id) for c in ceilings]

    if not ceilings:
        res["error"] = "no Ceiling elements in this document - run the ceiling rebuild first"
        OUT = res
    else:
        res["direct_shapes_before"] = count_app_shapes()

        src = open(GENERATOR).read()

        applied = {}
        if FOLLOW_WALL_LAYOUT:
            import re as _re
            for name, value in OVERRIDES.items():
                pat = _re.compile(r"^(" + name + r")\s*=\s*[^\n#]+", _re.MULTILINE)
                m = pat.search(src)
                if m is None:
                    applied[name] = "NOT FOUND in generator"
                    continue
                before = m.group(0).split("=", 1)[1].strip()
                src = pat.sub(name + " = " + value, src, count=1)
                applied[name] = "{} -> {}".format(before, value)
        res["layout_overrides"] = applied

        import re as _re2
        checks = {}
        for name, want in EXPECTED.items():
            m = _re2.search(r"^" + name + r"\s*=\s*([^\n#]+)", src, _re2.MULTILINE)
            got = m.group(1).strip() if m else "NOT FOUND"
            checks[name] = {"expected": want, "actual": got, "ok": got == want}
        res["layout_checks"] = checks
        if any(not v["ok"] for v in checks.values()):
            res["layout_warning"] = ("generator layout settings are not what this project "
                                     "expects - ceilings may not match the wall layout")

        ns = {
            "IN": [ceilings] + [None] * 9,
            "OUT": None,
            "__name__": "__main__",
            "__file__": GENERATOR,
        }
        exec(compile(src, GENERATOR, "exec"), ns)

        try:
            doc.Regenerate()
        except Exception:
            pass
        res["direct_shapes_after"] = count_app_shapes()
        res["direct_shapes_created"] = res["direct_shapes_after"] - res["direct_shapes_before"]

        gen_out = ns.get("OUT")
        rp = os.path.join(REPORT_DIR, "drywall_on_ceilings_" +
                          "".join(ch for ch in doc.Title if ch.isalnum() or ch in "-_") + ".json")
        try:
            if not os.path.exists(REPORT_DIR):
                os.makedirs(REPORT_DIR)
            f = open(rp, "w")
            try:
                json.dump({"doc": doc.Title, "generator_out": gen_out}, f, indent=2, default=str)
            finally:
                f.close()
            res["report"] = rp
        except Exception:
            res["report_error"] = traceback.format_exc()[-300:]

        # The generator's OUT can be very large; keep only what fits a bridge result.
        if isinstance(gen_out, dict):
            res["generator_keys"] = sorted(gen_out.keys())
            for k in ("summary", "counts", "totals", "warnings", "errors", "stats"):
                if k in gen_out:
                    v = gen_out[k]
                    if isinstance(v, list):
                        res["generator_" + k] = v[:20]
                    else:
                        res["generator_" + k] = v
        else:
            res["generator_out_type"] = str(type(gen_out))
            res["generator_out_preview"] = str(gen_out)[:1500]

        res["status"] = "ok"
        OUT = res
except Exception:
    res["status"] = "error"
    res["error"] = traceback.format_exc()
    OUT = res

res["sec"] = round(time.time() - t0, 2)
