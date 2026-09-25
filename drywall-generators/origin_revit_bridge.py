# origin_revit_bridge.py
# ============================================================
# ORIGIN <-> Revit LIVE BRIDGE (Dynamo Python node, runs in PERIODIC mode)
#
# Open dynamo\ORIGIN Bridge.dyn in Dynamo, set the run mode (bottom-left) to PERIODIC
# (interval ~1000 ms) and leave it running. Every tick this node:
#   1. writes bridge\heartbeat.json  - proof of life: time, open document, active view,
#      current selection count, tick counter, last executed command id
#   2. reads  bridge\command.json    - {"id": <n>, "script": "<abs path to .py>",
#      "transaction": false}; when id differs from the last executed id, the script FILE is
#      read fresh from disk and exec'd inside Revit (so edited scripts run without any
#      close/reopen), and its OUT lands in bridge\result.json together with ok/error/timing.
#
# The command scripts are ordinary Dynamo-style scripts: they may import clr, take doc from
# DocumentManager, and set OUT. Scripts that need a transaction manage it themselves the same
# way the generators do (TransactionManager.EnsureInTransaction/TransactionTaskDone); for
# small snippets "transaction": true makes the bridge wrap the exec instead.
# ============================================================

import clr
import json
import os
import traceback
import time

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

BRIDGE_DIR = r"C:\Users\Origoncad\Downloads\origin_revit_drywall_scripts_v2_two_faces\bridge"
CMD_PATH = os.path.join(BRIDGE_DIR, "command.json")
RES_PATH = os.path.join(BRIDGE_DIR, "result.json")
HB_PATH = os.path.join(BRIDGE_DIR, "heartbeat.json")

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

if not os.path.exists(BRIDGE_DIR):
    os.makedirs(BRIDGE_DIR)


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

OUT = "bridge alive - tick {} - {}".format(tick, status)
