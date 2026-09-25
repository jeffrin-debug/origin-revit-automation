"""Numeric verification of the per-room ceiling generation (run with local Python, not Revit).

Checks every ceiling record that carries a bbox_ft (boards, furring pieces, carrying mains)
against the room polygons in the ceiling manifest and the wall footprints in the wall manifest:

  1. CROSS-ROOM: no element assigned to room A may reach into room B's polygon.
  2. WALL PENETRATION: no element may overlap a wall's plan footprint.

Because the manifest stores each solid's BOUNDING BOX (not its exact footprint), an element that
was boolean-clipped to a concave room corner can have a bbox that legitimately pokes past the
room line while its actual solid does not. Violations are therefore reported in two tiers:
  DEFINITE - uncut rectangular boards (bbox == real footprint): any hit is a real defect.
  SUSPECT  - clipped boards / furring / mains: verify visually in Revit before treating as real.

Usage:  python origin_ceiling_manifest_check.py [ceiling_manifest.json] [wall_manifest.json]
Defaults to the notaper manifests next to this script. Exit code 1 if any DEFINITE violation.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CEILING_MANIFEST = os.path.join(HERE, "origin_ceiling_manifest_notaper_noscrew_nojoint.json")
WALL_MANIFEST = os.path.join(HERE, "origin_assembly_manifest_notaper_noscrew_nojoint.json")
TOL_FT = 0.03            # ~3/8": shrink each bbox by this before testing, absorbs rounding
SAMPLES = 5              # sample grid per bbox edge for point-in-polygon tests


def point_in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def bbox_samples(b):
    x0, y0, x1, y1 = b[0] + TOL_FT, b[1] + TOL_FT, b[2] - TOL_FT, b[3] - TOL_FT
    if x1 <= x0 or y1 <= y0:
        return []
    pts = []
    for i in range(SAMPLES):
        for j in range(SAMPLES):
            pts.append((x0 + (x1 - x0) * i / (SAMPLES - 1.0),
                        y0 + (y1 - y0) * j / (SAMPLES - 1.0)))
    return pts


def sat_overlap(quad_a, quad_b):
    """Separating-axis overlap test for two convex quads."""
    for quad in (quad_a, quad_b):
        n = len(quad)
        for i in range(n):
            ax, ay = quad[i]
            bx, by = quad[(i + 1) % n]
            nx, ny = -(by - ay), (bx - ax)
            amin = min(p[0] * nx + p[1] * ny for p in quad_a)
            amax = max(p[0] * nx + p[1] * ny for p in quad_a)
            bmin = min(p[0] * nx + p[1] * ny for p in quad_b)
            bmax = max(p[0] * nx + p[1] * ny for p in quad_b)
            if amax <= bmin or bmax <= amin:
                return False
    return True


def bbox_quad(b):
    x0, y0, x1, y1 = b[0] + TOL_FT, b[1] + TOL_FT, b[2] - TOL_FT, b[3] - TOL_FT
    if x1 <= x0 or y1 <= y0:
        return None
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def wall_quads(wall_manifest):
    quads = []
    if not os.path.exists(wall_manifest):
        return quads
    m = json.load(open(wall_manifest, encoding="utf-8"))
    widths = {w.get("wall_number"): w.get("wall_width_in", 0.0) / 12.0
              for w in m.get("walls", [])}
    for e in m.get("corner_debug", []):
        try:
            (x0, y0), (x1, y1) = e["start_xy"], e["end_xy"]
            hw = widths.get(e["wall"], 0.0) / 2.0
            dx, dy = x1 - x0, y1 - y0
            ln = (dx * dx + dy * dy) ** 0.5
            if ln < 1e-6 or hw <= 0.0:
                continue
            nx, ny = -dy / ln * hw, dx / ln * hw
            quads.append((e["wall"], [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                                      (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]))
        except Exception:
            continue
    return quads


def main():
    cpath = sys.argv[1] if len(sys.argv) > 1 else CEILING_MANIFEST
    wpath = sys.argv[2] if len(sys.argv) > 2 else WALL_MANIFEST
    m = json.load(open(cpath, encoding="utf-8"))
    rooms = {r["room_id"]: r["outer_ft"] for r in m.get("rooms", [])}
    walls = wall_quads(wpath)
    print(f"ceiling manifest: {os.path.basename(cpath)}")
    print(f"rooms in manifest: {len(rooms)}, wall footprints: {len(walls)}")

    records = []
    for b in m.get("boards", []):
        records.append(("board", b.get("board_id"), b.get("room_id"), b.get("bbox_ft"),
                        bool(b.get("is_cut", True))))
    for f in m.get("framing", []):
        if f.get("member_type") in ("FURRING", "MAIN"):
            records.append((f["member_type"].lower(), f.get("id"), f.get("room_id"),
                            f.get("bbox_ft"), True))

    definite, suspect, nobox, noroom = [], [], 0, 0
    for kind, rid_, room_id, bbox, clipped in records:
        if not bbox:
            nobox += 1
            continue
        if room_id is None or room_id not in rooms:
            noroom += 1
            continue
        hits = []
        pts = bbox_samples(bbox)
        for other_id, poly in rooms.items():
            if other_id == room_id:
                continue
            if any(point_in_polygon(px, py, poly) for (px, py) in pts):
                hits.append("room " + other_id)
        quad = bbox_quad(bbox)
        if quad:
            for wnum, wq in walls:
                if sat_overlap(quad, wq):
                    hits.append("wall " + str(wnum))
        if hits:
            (suspect if clipped else definite).append((kind, rid_, room_id, hits))

    print(f"records checked: {len(records)}  (no bbox: {nobox}, no room_id: {noroom})")
    print(f"DEFINITE violations (uncut boards): {len(definite)}")
    for v in definite[:20]:
        print("  ", v)
    print(f"SUSPECT hits (clipped elements - bbox may be larger than solid): {len(suspect)}")
    for v in suspect[:20]:
        print("  ", v)
    if noroom:
        print("NOTE: records without room_id mean the legacy (non-per-room) path ran for them.")
    sys.exit(1 if definite else 0)


if __name__ == "__main__":
    main()
