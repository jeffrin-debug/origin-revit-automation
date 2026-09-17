# ceiling_bridge.py
# ============================================================
# ORIGIN CEILING REBUILD <-> Revit LIVE BRIDGE (Dynamo Python node, PERIODIC mode)
#
# Reference copy of the code embedded in dynamo\ORIGIN Ceiling Bridge.dyn. This project is
# standalone: it has its own bridge folder and its own graph, and shares nothing with the
# drywall repo. Open dynamo\ORIGIN Ceiling Bridge.dyn in Dynamo, set the run mode
# (bottom-left) to PERIODIC (~1000 ms) and leave it running. Every tick this node:
#   1. writes bridge\heartbeat.json  - proof of life: time, open document, active view,
#      selection count, tick counter, last executed command id
#   2. reads  bridge\command.json    - {"id": <n>, "script": "<abs path to .py>",
#      "transaction": false}; when id differs from the last executed id the script FILE is
#      read fresh from disk and exec'd inside Revit (so edited scripts run without any
#      close/reopen), and its OUT lands in bridge\result.json with ok/error/timing.
#
# SELF-DIAGNOSING: a Dynamo node that dies shows only a yellow triangle whose text you have to
# hover to read, which is useless when the node is being driven from outside Revit. So before
# anything that can fail, this writes bridge\node_started.txt, and any exception anywhere lands
# in bridge\node_error.txt. Between those two files the failure is always visible from disk:
#   neither file        -> the node never executed (graph wiring / run mode)
#   started, no error   -> the node ran fine
#   started + error     -> the node ran and threw; the traceback is in node_error.txt
#
# Batch scripts here run with "transaction": false and open their own background documents,
# so they call TransactionManager.Instance.ForceCloseTransaction() themselves before any
# Application.OpenDocumentFile - that call throws if any transaction is open anywhere.
# ============================================================

import os
import time
import traceback

BRIDGE_DIR = r"C:\Users\Origoncad\origin_ceiling_rebuild\bridge"
CMD_PATH = os.path.join(BRIDGE_DIR, "command.json")
RES_PATH = os.path.join(BRIDGE_DIR, "result.json")
HB_PATH = os.path.join(BRIDGE_DIR, "heartbeat.json")
STARTED_PATH = os.path.join(BRIDGE_DIR, "node_started.txt")
ERROR_PATH = os.path.join(BRIDGE_DIR, "node_error.txt")

try:
    if not os.path.exists(BRIDGE_DIR):
        os.makedirs(BRIDGE_DIR)
except Exception:
    pass


def _append(path, text):
    try:
        f = open(path, "a")
        try:
            f.write(text)
        finally:
            f.close()
    except Exception:
        pass


def _write(path, text):
    try:
        f = open(path, "w")
        try:
            f.write(text)
        finally:
            f.close()
    except Exception:
        pass


# Proof the node body executed at all - written before any import that could fail.
# OVERWRITE, not append: this fires every tick, and appending grew the file to 720 KB /
# 21203 lines in a single session. Only the latest entry has any diagnostic value.
_write(STARTED_PATH, time.strftime("%Y-%m-%d %H:%M:%S") + " node entered\n")

try:
    import clr
    import json

    clr.AddReference('RevitAPI')
    clr.AddReference('RevitServices')

    from Autodesk.Revit.DB import *
    from RevitServices.Persistence import DocumentManager
    from RevitServices.Transactions import TransactionManager

    doc = DocumentManager.Instance.CurrentDBDocument
    uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

    def write_json(path, obj):
        tmp = path + ".tmp"
        f = open(tmp, "w")
        try:
            json.dump(obj, f, indent=2, default=str)
        finally:
            f.close()
        try:
            if os.path.exists(path):
                os.remove(path)
            os.rename(tmp, path)
        except Exception:
            pass

    def read_json(path):
        try:
            f = open(path)
            try:
                return json.load(f)
            finally:
                f.close()
        except Exception:
            return None

    def run_command(cmd):
        res = {"id": cmd.get("id"), "ok": False, "out": None, "error": None,
               "script": cmd.get("script"), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        path = cmd.get("script") or ""
        if not os.path.exists(path):
            res["error"] = "script not found: {}".format(path)
            return res
        try:
            src = open(path).read()
            ns = {"IN": [None] * 10, "OUT": None, "__name__": "__main__", "__file__": path}
            wrap = bool(cmd.get("transaction"))
            if wrap:
                TransactionManager.Instance.EnsureInTransaction(doc)
            try:
                exec(compile(src, path, "exec"), ns)
            finally:
                if wrap:
                    TransactionManager.Instance.TransactionTaskDone()
            res["ok"] = True
            res["out"] = ns.get("OUT")
        except Exception:
            res["error"] = traceback.format_exc()
        res["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return res

    last = read_json(RES_PATH)
    last_id = last.get("id") if isinstance(last, dict) else None
    cmd = read_json(CMD_PATH)
    status = "idle"
    if isinstance(cmd, dict) and cmd.get("id") is not None and cmd.get("id") != last_id:
        status = "ran command {}".format(cmd.get("id"))
        write_json(RES_PATH, run_command(cmd))
        last_id = cmd.get("id")

    hb = read_json(HB_PATH) or {}
    tick = int(hb.get("tick", 0)) + 1
    view_name = ""
    sel_count = 0
    try:
        view_name = doc.ActiveView.Name
    except Exception:
        pass
    try:
        sel_count = len(list(uidoc.Selection.GetElementIds()))
    except Exception:
        pass
    write_json(HB_PATH, {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "doc": doc.Title,
        "view": view_name,
        "selection_count": sel_count,
        "tick": tick,
        "last_command_id": last_id,
        "status": status,
    })

    # Clear any stale error from a previous tick now that we know this one succeeded.
    try:
        if os.path.exists(ERROR_PATH):
            os.remove(ERROR_PATH)
    except Exception:
        pass

    OUT = "ceiling bridge alive - tick {} - {}".format(tick, status)

except Exception:
    tb = traceback.format_exc()
    _write(ERROR_PATH, time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + tb)
    OUT = "ceiling bridge FAILED:\n" + tb
