# origin_bridge_debug_curtain_geometry.py - run via the ORIGIN Bridge. READ-ONLY.
# The GL-016-001/GL-017-001 glass pass-through meshes were created (curtain_glass_created: 2) but
# report a null bbox - something about the extracted "solids" isn't real geometry. Dumps exactly
# what get_Geometry() returns for the curtain wall itself, at every nesting level, to find out
# what's actually there.
import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
app = DocumentManager.Instance.CurrentUIApplication.Application
target_title = uidoc.Document.Title
doc = uidoc.Document
for d in app.Documents:
    if d.Title == target_title:
        doc = d
        break

TARGETS = [373548, 373575]


def _opt_cr():
    o = Options()
    o.ComputeReferences = True
    try:
        o.DetailLevel = ViewDetailLevel.Fine
    except Exception:
        pass
    return o


def _opt_view():
    v = uidoc.ActiveView
    if v is None:
        return None
    o = Options()
    o.View = v
    o.ComputeReferences = True
    return o

out = {}
for eid in TARGETS:
    w = doc.GetElement(ElementId(eid))
    entry = {"exists": w is not None}
    if w is None:
        out[str(eid)] = entry
        continue
    try:
        opt = Options()
        try:
            opt.DetailLevel = ViewDetailLevel.Fine
        except Exception:
            pass
        geo = w.get_Geometry(opt)
        items = []
        if geo is not None:
            for g in geo:
                item = {"type": type(g).__name__}
                if isinstance(g, Solid):
                    item["volume"] = g.Volume
                    item["face_count"] = g.Faces.Size
                elif isinstance(g, GeometryInstance):
                    try:
                        inst_geo = g.GetInstanceGeometry()
                        sub = []
                        for g2 in inst_geo:
                            sub_item = {"type": type(g2).__name__}
                            if isinstance(g2, Solid):
                                sub_item["volume"] = g2.Volume
                                sub_item["face_count"] = g2.Faces.Size
                            sub.append(sub_item)
                        item["instance_geometry"] = sub
                        try:
                            sym = g.GetSymbolGeometry()
                            item["symbol_geometry_count"] = len(list(sym)) if sym else 0
                        except Exception:
                            pass
                    except Exception as ex:
                        item["instance_geometry_error"] = str(ex)
                items.append(item)
        entry["top_level_items"] = items
        entry["top_level_count"] = len(items)
    except Exception as ex:
        import traceback
        entry["error"] = traceback.format_exc()

    # Also check curtain grid panels/mullions as SEPARATE elements
    try:
        cg = w.CurtainGrid
        if cg is not None:
            panel_ids = list(cg.GetPanelIds())
            mullion_ids = list(cg.GetMullionIds())
            entry["panel_count"] = len(panel_ids)
            entry["mullion_count"] = len(mullion_ids)
            panel_info = []
            for pid in panel_ids[:3]:
                pe = doc.GetElement(pid)
                pinfo = {"type": type(pe).__name__ if pe else None}
                if pe is not None:
                    for opt_label, mk_opt in [
                        ("default", lambda: Options()),
                        ("compute_refs", lambda: _opt_cr()),
                        ("view_based", lambda: _opt_view()),
                    ]:
                        try:
                            o = mk_opt()
                            if o is None:
                                pinfo[opt_label] = "n/a"
                                continue
                            pg = pe.get_Geometry(o)
                            items = []
                            if pg is not None:
                                for g in pg:
                                    if isinstance(g, Solid):
                                        items.append(("Solid", g.Volume, g.Faces.Size))
                                    elif isinstance(g, GeometryInstance):
                                        try:
                                            sub = list(g.GetInstanceGeometry())
                                            sub_solids = [(type(x).__name__, x.Volume, x.Faces.Size)
                                                         for x in sub if isinstance(x, Solid)]
                                            items.append(("GeometryInstance", len(sub), sub_solids))
                                        except Exception as ex2:
                                            items.append(("GeometryInstance-error", str(ex2)))
                                    else:
                                        items.append((type(g).__name__,))
                            pinfo[opt_label] = items
                        except Exception as ex:
                            pinfo[opt_label + "_error"] = str(ex)
                panel_info.append(pinfo)
            entry["sample_panels"] = panel_info

            mullion_info = []
            for mid in mullion_ids[:2]:
                me = doc.GetElement(mid)
                minfo = {"type": type(me).__name__ if me else None}
                if me is not None:
                    try:
                        mg = me.get_Geometry(Options())
                        msolids = [g for g in mg if isinstance(g, Solid) and g.Volume > 1e-9] if mg else []
                        minfo["solid_count"] = len(msolids)
                        minfo["total_volume"] = sum(s.Volume for s in msolids)
                    except Exception as ex:
                        minfo["geo_error"] = str(ex)
                mullion_info.append(minfo)
            entry["sample_mullions"] = mullion_info
    except Exception as ex:
        entry["curtain_grid_error"] = str(ex)

    out[str(eid)] = entry

OUT = out
