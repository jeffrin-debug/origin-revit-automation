# diag_ceiling_joints.py - read-only: every ceiling butt joint vs the furring channels in the model.
# The checker half of ceiling_joints_on_furring.py, runnable on its own through the bridge.

import os

_here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else r"C:\Users\Origoncad\origin_pipeline"
_p = os.path.join(_here, "ceiling_joints_on_furring.py")
_ns = {"__name__": "ceiling_joints_on_furring", "__file__": _p}
exec(compile(open(_p).read(), _p, "exec"), _ns)

from RevitServices.Persistence import DocumentManager
doc = DocumentManager.Instance.CurrentDBDocument
OUT = dict(_ns["check"](doc), doc=doc.Title)
