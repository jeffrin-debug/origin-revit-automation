# origin_paths.py
# ============================================================
# Where everything lives, worked out at run time instead of hard-coded.
#
# Every script used to carry absolute C:\Users\<someone>\... constants, so a clone ran nowhere
# but the machine it was written on. This resolves the same paths from the calling script's OWN
# location, which needs no configuration and survives the folder being renamed, moved or cloned.
#
# Two layouts are supported, because the working copy and the git repo are shaped differently
# and neither is worth breaking:
#
#     working copy        <parent>/origin_pipeline        <parent>/origin_ceiling_rebuild
#     git repo            <repo>/pipeline                 <repo>/ceiling-rebuild
#
# Either way the two roots are SIBLINGS, so each is found from the other by name.
#
# Only genuinely external things stay configurable: the drywall generator repo (a separate
# repository, not ours) and the folder envs are discovered in. Those come from
# origin.config.json next to either root, or from the environment, with this machine's current
# values as the fallback so nothing changes until someone says so.
#
# USAGE - copied into both roots, and loaded the same way every other module here is loaded
# (exec from disk, never `import`: Dynamo caches sys.modules across ticks and a stale module is
# a silent, expensive class of bug):
#
#     import os
#     _ns = {"__name__": "origin_paths"}
#     _pp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")
#     exec(compile(open(_pp).read(), _pp, "exec"), _ns)
#     ROOT         = _ns["PIPELINE_ROOT"]
#     CEILING_ROOT = _ns["CEILING_ROOT"]
#
# Both bridges put __file__ into the namespace they exec a command in, so this works for
# bridge-launched scripts as well as ones run directly.
# ============================================================

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Folder names each root is known by. The working copy and the repo use different ones.
_PIPELINE_NAMES = ("pipeline", "origin_pipeline", "origin-pipeline")
_CEILING_NAMES = ("ceiling-rebuild", "ceiling_rebuild", "origin_ceiling_rebuild")

# Files that prove a folder really is that root, rather than something that merely shares the
# name. Cheap, and it stops a stray "pipeline" folder further up the tree winning.
_PIPELINE_MARKER = "stage2_panels.py"
_CEILING_MARKER = "origin_ceiling_rebuild_core.py"


def _is_root(path, names, marker):
    if not path or not os.path.isdir(path):
        return False
    if os.path.basename(path).lower() not in names:
        return False
    return os.path.exists(os.path.join(path, marker))


def _find_sibling(start, names, marker):
    """Look for the other root beside `start`, then one level up, then under `start`."""
    parent = os.path.dirname(start)

    # Pass 1 - a folder with the expected name AND the marker file. Always preferred, so a
    # correctly-named root beats a renamed one when both somehow exist.
    for base in (parent, os.path.dirname(parent), start):
        if not base or not os.path.isdir(base):
            continue
        for n in names:
            cand = os.path.join(base, n)
            if _is_root(cand, names, marker):
                return cand
        try:
            for entry in os.listdir(base):
                cand = os.path.join(base, entry)
                if _is_root(cand, names, marker):
                    return cand
        except Exception:
            continue

    # Pass 2 - the marker file alone, for a root someone renamed to something unrecognised.
    # Deliberately not extended to the grandparent: that can be C:\Users, and guessing that
    # wide is how you end up bound to a stranger's folder.
    for base in (parent, start):
        if not base or not os.path.isdir(base):
            continue
        try:
            for entry in sorted(os.listdir(base)):
                cand = os.path.join(base, entry)
                if os.path.isdir(cand) and os.path.exists(os.path.join(cand, marker)):
                    return cand
        except Exception:
            continue
    return None


def _resolve_roots(here):
    pipeline = here if _is_root(here, _PIPELINE_NAMES, _PIPELINE_MARKER) else None
    ceiling = here if _is_root(here, _CEILING_NAMES, _CEILING_MARKER) else None

    # Fall back to the marker file alone - covers a root someone renamed entirely.
    if pipeline is None and ceiling is None:
        if os.path.exists(os.path.join(here, _PIPELINE_MARKER)):
            pipeline = here
        elif os.path.exists(os.path.join(here, _CEILING_MARKER)):
            ceiling = here

    if pipeline is None:
        pipeline = _find_sibling(ceiling or here, _PIPELINE_NAMES, _PIPELINE_MARKER)
    if ceiling is None:
        ceiling = _find_sibling(pipeline or here, _CEILING_NAMES, _CEILING_MARKER)
    return pipeline, ceiling


PIPELINE_ROOT, CEILING_ROOT = _resolve_roots(HERE)

# A root that could not be found falls back to HERE rather than None, so a caller gets a wrong
# path it can see in a report rather than a TypeError deep inside a join.
PIPELINE_ROOT = PIPELINE_ROOT or HERE
CEILING_ROOT = CEILING_ROOT or HERE


# ------------------------------------------------------------
# The genuinely external bits
# ------------------------------------------------------------

CONFIG_NAME = "origin.config.json"

# This machine's current values. Kept as the fallback so behaviour is unchanged until someone
# writes a config or sets the environment variable.
_DEFAULTS = {
    "drywall_repo": r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces",
    "input_dir": r"C:\Users\Origoncad\Downloads",
}


def _load_config():
    """origin.config.json, looked for beside either root and in their shared parent."""
    seen = []
    for base in (PIPELINE_ROOT, CEILING_ROOT,
                 os.path.dirname(PIPELINE_ROOT), os.path.dirname(CEILING_ROOT)):
        if not base or base in seen:
            continue
        seen.append(base)
        p = os.path.join(base, CONFIG_NAME)
        if not os.path.exists(p):
            continue
        try:
            f = open(p)
            try:
                return json.load(f), p
            finally:
                f.close()
        except Exception:
            continue
    return {}, None


CONFIG, CONFIG_PATH = _load_config()


def setting(key):
    """Environment wins, then origin.config.json, then this machine's current value."""
    env = os.environ.get("ORIGIN_" + key.upper())
    if env:
        return env
    v = CONFIG.get(key)
    if v:
        return v
    return _DEFAULTS.get(key)


DRYWALL_REPO = setting("drywall_repo")
INPUT_DIR = setting("input_dir")

# Derived locations, so no caller has to join these by hand.
BRIDGE_DIR = os.path.join(PIPELINE_ROOT, "bridge")
REPORT_DIR = os.path.join(PIPELINE_ROOT, "_reports")
CEILING_BRIDGE_DIR = os.path.join(CEILING_ROOT, "bridge")
CEILING_OUT_DIR = os.path.join(CEILING_ROOT, "out")


def describe():
    return {
        "resolved_from": HERE,
        "PIPELINE_ROOT": PIPELINE_ROOT,
        "CEILING_ROOT": CEILING_ROOT,
        "DRYWALL_REPO": DRYWALL_REPO,
        "INPUT_DIR": INPUT_DIR,
        "config_file": CONFIG_PATH,
        "pipeline_root_ok": os.path.exists(os.path.join(PIPELINE_ROOT, _PIPELINE_MARKER)),
        "ceiling_root_ok": os.path.exists(os.path.join(CEILING_ROOT, _CEILING_MARKER)),
        "drywall_repo_ok": bool(DRYWALL_REPO) and os.path.isdir(DRYWALL_REPO),
    }
