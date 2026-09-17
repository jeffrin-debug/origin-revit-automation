# Offline test of the path resolver.
#
# Builds throwaway folder trees in a temp dir and checks origin_paths.py finds both roots from
# either side, in both the working-copy layout and the git-repo layout. No Revit, no network.
#
#   python test_origin_paths_offline.py

import json
import os
import shutil
import sys
import tempfile

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "origin_paths.py")

fails = []


def check(label, cond, extra=""):
    fails.append(bool(cond))
    line = "  {}  {}".format("PASS" if cond else "FAIL", label)
    if extra:
        line += "\n          {}".format(extra)
    print(line)


def build(root, pipeline_name, ceiling_name, config=None):
    """A minimal pair of roots: the marker file each is recognised by, plus the resolver."""
    p = os.path.join(root, pipeline_name)
    c = os.path.join(root, ceiling_name)
    os.makedirs(p)
    os.makedirs(c)
    open(os.path.join(p, "stage2_panels.py"), "w").close()
    open(os.path.join(c, "origin_ceiling_rebuild_core.py"), "w").close()
    shutil.copy(SRC, os.path.join(p, "origin_paths.py"))
    shutil.copy(SRC, os.path.join(c, "origin_paths.py"))
    if config is not None:
        with open(os.path.join(root, "origin.config.json"), "w") as f:
            json.dump(config, f)
    return p, c


def resolve(folder):
    """Load the resolver exactly as the real scripts do."""
    path = os.path.join(folder, "origin_paths.py")
    ns = {"__name__": "origin_paths", "__file__": path}
    exec(compile(open(path).read(), path, "exec"), ns)
    return ns["describe"](), ns


tmp = tempfile.mkdtemp(prefix="origin_paths_test_")
try:
    # ---- working-copy layout ------------------------------------------------------------
    root = os.path.join(tmp, "workingcopy")
    os.makedirs(root)
    p, c = build(root, "origin_pipeline", "origin_ceiling_rebuild")
    print("WORKING-COPY LAYOUT  (origin_pipeline + origin_ceiling_rebuild, siblings)")
    for name, folder in (("from pipeline", p), ("from ceiling-rebuild", c)):
        d, _ = resolve(folder)
        ok = (os.path.normcase(d["PIPELINE_ROOT"]) == os.path.normcase(p)
              and os.path.normcase(d["CEILING_ROOT"]) == os.path.normcase(c))
        check("{:<22} finds both roots".format(name), ok,
              "" if ok else "got {} / {}".format(d["PIPELINE_ROOT"], d["CEILING_ROOT"]))
        check("{:<22} both marked healthy".format(name),
              d["pipeline_root_ok"] and d["ceiling_root_ok"])

    # ---- git-repo layout ----------------------------------------------------------------
    root = os.path.join(tmp, "clone")
    os.makedirs(root)
    p, c = build(root, "pipeline", "ceiling-rebuild")
    print("\nGIT-REPO LAYOUT  (pipeline + ceiling-rebuild, as cloned)")
    for name, folder in (("from pipeline", p), ("from ceiling-rebuild", c)):
        d, _ = resolve(folder)
        ok = (os.path.normcase(d["PIPELINE_ROOT"]) == os.path.normcase(p)
              and os.path.normcase(d["CEILING_ROOT"]) == os.path.normcase(c))
        check("{:<22} finds both roots".format(name), ok,
              "" if ok else "got {} / {}".format(d["PIPELINE_ROOT"], d["CEILING_ROOT"]))

    # ---- cloned somewhere with a completely different name -------------------------------
    root = os.path.join(tmp, "some user", "My Projects", "revit stuff")
    os.makedirs(root)
    p, c = build(root, "pipeline", "ceiling-rebuild")
    print("\nCLONED INTO A PATH WITH SPACES AND A DIFFERENT PARENT")
    d, _ = resolve(p)
    check("still resolves - nothing depends on the parent's name",
          os.path.normcase(d["CEILING_ROOT"]) == os.path.normcase(c), d["CEILING_ROOT"])

    # ---- a root renamed entirely ---------------------------------------------------------
    root = os.path.join(tmp, "renamed")
    os.makedirs(root)
    p, c = build(root, "pipeline", "ceiling-rebuild")
    c2 = os.path.join(root, "totally-different-name")
    os.rename(c, c2)
    print("\nONE ROOT RENAMED TO SOMETHING UNRECOGNISED")
    d, _ = resolve(p)
    check("found by its marker file rather than its folder name",
          os.path.normcase(d["CEILING_ROOT"]) == os.path.normcase(c2), d["CEILING_ROOT"])

    # ---- config file ---------------------------------------------------------------------
    root = os.path.join(tmp, "configured")
    os.makedirs(root)
    fake_repo = os.path.join(root, "my-drywall-scripts")
    os.makedirs(fake_repo)
    p, c = build(root, "pipeline", "ceiling-rebuild",
                 config={"drywall_repo": fake_repo, "input_dir": root})
    print("\norigin.config.json BESIDE THE ROOTS")
    d, _ = resolve(p)
    check("drywall_repo comes from the config",
          os.path.normcase(d["DRYWALL_REPO"]) == os.path.normcase(fake_repo), d["DRYWALL_REPO"])
    check("input_dir comes from the config",
          os.path.normcase(d["INPUT_DIR"]) == os.path.normcase(root))
    check("config file is reported so a wrong one is findable",
          d["config_file"] is not None and d["config_file"].endswith("origin.config.json"))
    check("the configured repo is checked for existence", d["drywall_repo_ok"])

    # ---- environment beats the config ----------------------------------------------------
    print("\nENVIRONMENT OVERRIDE")
    os.environ["ORIGIN_DRYWALL_REPO"] = r"X:\somewhere\else"
    try:
        d, _ = resolve(p)
        check("ORIGIN_DRYWALL_REPO wins over the config file",
              d["DRYWALL_REPO"] == r"X:\somewhere\else", d["DRYWALL_REPO"])
        check("a path that does not exist is reported, not hidden", not d["drywall_repo_ok"])
    finally:
        del os.environ["ORIGIN_DRYWALL_REPO"]

    # ---- no hard-coded user path survives -------------------------------------------------
    print("\nNO ABSOLUTE USER PATH LEAKS INTO A CLONE")
    d, _ = resolve(p)
    leaked = [k for k, v in d.items()
              if isinstance(v, str) and "Origoncad" in v]
    check("nothing resolved under a clone points back at the author's machine",
          not leaked, "leaked: {}".format(leaked))

finally:
    shutil.rmtree(tmp, ignore_errors=True)

bad = len([f for f in fails if not f])
print("\n{} / {} checks passed".format(len(fails) - bad, len(fails)))
sys.exit(1 if bad else 0)
