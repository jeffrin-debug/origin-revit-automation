# wall_ceiling_profile.py - wall drywall follows the ceiling ABOVE EACH STRETCH, not one per face.
#
# The wall generator caps each wall face at ONE height, face_ceiling_cap(): the LOWEST ceiling
# found anywhere along it. A face that runs under two rooms with different ceiling heights is then
# boarded to the lower one along its whole length, leaving bare studs under the taller ceiling
# (1F, wall 008 face A: C002 at 8 ft + C003 at 9 ft -> bare 8-9 ft band; also walls 011/012/016).
# The generator documents the real fix and deferred it (2026-09-15): cap PER BOARD CELL.
#
# User direction 2026-09-25: every room's ceiling sits at that room's own height, so this is now
# needed. The patch, applied to the generator's source string only:
#
#   1. face_ceiling_cap() is replaced for the main pass by a PROFILE of the face: the ceiling above
#      it is probed every PROBE_STEP_FT along the face (same offset and same ceiling_z_at_point()
#      as the generator), and each change of height is pinned down by bisection. The face's course
#      tiling now runs up to the HIGHEST ceiling over it (or the wall top where some stretch has no
#      ceiling), instead of the lowest.
#   2. Each course is broken wherever the profile changes height inside it, the same way a
#      partition junction already breaks it, so no board spans two ceiling heights.
#   3. Each board's top is clamped to the ceiling over ITS OWN stretch.
#
# The generator's safety floor is kept: a ceiling within CEILING_MIN_CAP_FT of the wall base is
# ignored as bad data (the 1F soffit band walls 006/007 rely on this). The corner-infill pass was
# already per point and is untouched.

import traceback

PROBE_STEP_FT = 0.5
BISECT_STEPS = 7                     # 0.5 ft / 2^7 = ~0.05 in

_CAP_CALL = ("_zc = face_ceiling_cap(start, u, _nrm, wall_length,\n"
             "                                                       ceiling_planes, wall_id, warnings)")
_CAP_NEW = ("_zc = _origin_face_cap_profile(start, u, _nrm, wall_length,\n"
            "                                                       ceiling_planes, wall_id, warnings, _side)")
_SPLITS = ("course_splits = unique_sorted([p for (p, z_lo, z_hi) in face_splits\n"
           "                                               if z_lo is None or (z_hi > cy0 and z_lo < cy1)])")
_SPLITS_NEW = ("course_splits = unique_sorted([p for (p, z_lo, z_hi) in face_splits\n"
               "                                               if z_lo is None or (z_hi > cy0 and z_lo < cy1)]\n"
               "                                              + _origin_cap_breaks(wall_id, face_config[\"side\"], cy1))")
_TOP = "                        sy1 = cy1 - g\n"
_TOP_NEW = ("                        sy1 = min(cy1, _origin_cap_at(wall_id, face_config[\"side\"],\n"
            "                                                      (raw_x0 + raw_x1) / 2.0, cy1)) - g\n")

_HELPER = '''
# ---- injected by origin_pipeline/wall_ceiling_profile.py (not part of this file on disk) ----
_ORIGIN_FACE_PROFILES = {}        # (wall_id, side) -> [(a0, a1, local_cap or None), ...]
_ORIGIN_PROBE_STEP_FT = __STEP__
_ORIGIN_BISECT_STEPS = __BISECT__
_ORIGIN_NONE_MIN_FT = 1.0          # a no-ceiling stretch shorter than this is a probe artefact


def _origin_face_cap_profile(start, u, normal, wall_length, ceiling_planes, wall_id, warnings, side):
    """Profile the ceiling over this face and remember it; return the WORLD Z the course tiling
    should run to - the highest ceiling over the face, or None if some stretch has none."""
    _ORIGIN_FACE_PROFILES[(wall_id, side)] = []
    if not ceiling_planes or wall_length <= 1e-6:
        return None

    def probe(a):
        px = start.X + u.X * a + normal.X * CEILING_PROBE_OFFSET_FT
        py = start.Y + u.Y * a + normal.Y * CEILING_PROBE_OFFSET_FT
        z = ceiling_z_at_point(px, py, ceiling_planes)
        if z is None:
            return None
        local = z - start.Z
        # The generator's own sanity floor: a ceiling this close to the wall base is bad data -
        # EXCEPT on a soffit (stage 2 hands their ids in as ORIGIN_SOFFIT_WALL_IDS), where the
        # ceiling beside it is meant to be just above its bottom and each face stops at its own.
        if local <= CEILING_MIN_CAP_FT and wall_id not in globals().get("ORIGIN_SOFFIT_WALL_IDS", ()):
            return None
        if local <= 1e-3:
            return None
        return round(local, 4)

    n = max(2, int(wall_length / _ORIGIN_PROBE_STEP_FT) + 1)
    xs = [wall_length * i / float(n - 1) for i in range(n)]
    xs[0] = min(0.02, wall_length / 4.0)
    xs[-1] = max(wall_length - 0.02, wall_length * 0.75)
    vals = [probe(a) for a in xs]
    segs = []
    a0 = 0.0
    for i in range(1, n):
        if vals[i] == vals[i - 1]:
            continue
        lo, hi, vlo = xs[i - 1], xs[i], vals[i - 1]
        for _k in range(_ORIGIN_BISECT_STEPS):
            mid = (lo + hi) / 2.0
            if probe(mid) == vlo:
                lo = mid
            else:
                hi = mid
        b = (lo + hi) / 2.0
        segs.append((a0, b, vals[i - 1]))
        a0 = b
    segs.append((a0, wall_length, vals[-1]))
    # A short stretch with NO ceiling is the probe running past a corner or onto a partition at a
    # junction, not open plenum - it takes the lower of its neighbours' heights (seen 2026-09-25:
    # 0.31 ft "none" at every wall end in 1F, which would have run those pieces to the wall top).
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for k, (s0, s1, c) in enumerate(segs):
            if c is not None or (s1 - s0) >= _ORIGIN_NONE_MIN_FT:
                continue
            nb = [segs[j][2] for j in (k - 1, k + 1) if 0 <= j < len(segs) and segs[j][2] is not None]
            if nb:
                segs[k] = (s0, s1, min(nb))
                changed = True
        merged = [segs[0]]
        for s in segs[1:]:
            if s[2] == merged[-1][2]:
                merged[-1] = (merged[-1][0], s[1], s[2])
            else:
                merged.append(s)
        segs = merged
    _ORIGIN_FACE_PROFILES[(wall_id, side)] = segs
    caps = [s[2] for s in segs]
    if len(set(caps)) > 1:
        warnings.append("Wall {}: {} face follows {} ceiling stretches ({}) - each board stops at "
                        "the ceiling over it".format(
                            wall_id, side, len(segs),
                            ", ".join("{:.2f}-{:.2f}ft: {}".format(
                                s[0], s[1], "none" if s[2] is None else "{:.2f}ft".format(s[2]))
                                for s in segs)))
    if any(c is None for c in caps):
        return None
    return max(caps) + start.Z


def _origin_cap_breaks(wall_id, side, cy1):
    """Along-wall positions where the ceiling height changes AND the lower side is below this
    course's top - the course must break there so no board spans two ceiling heights."""
    segs = _ORIGIN_FACE_PROFILES.get((wall_id, side)) or []
    out = []
    for i in range(1, len(segs)):
        caps = [c for c in (segs[i - 1][2], segs[i][2]) if c is not None]
        if caps and min(caps) < cy1 - 1e-4:
            out.append(segs[i][0])
    return out


def _origin_cap_at(wall_id, side, x, default):
    """The ceiling height (wall-local) over along-wall position x, else `default`."""
    for (a0, a1, c) in _ORIGIN_FACE_PROFILES.get((wall_id, side)) or []:
        if a0 - 1e-6 <= x <= a1 + 1e-6:
            return default if c is None else c
    return default
# ---- end injection ----

'''


def apply_to_source(src):
    info = {"applied": False}
    try:
        for label, old in (("cap call", _CAP_CALL), ("course splits", _SPLITS), ("board top", _TOP)):
            n = src.count(old)
            if n != 1:
                info["skipped"] = "expected the {} once, found {}".format(label, n)
                return src, info
        anchor = "\ndef generate_courses("
        i = src.find(anchor)
        if i < 0:
            info["skipped"] = "no generate_courses() to insert before"
            return src, info
        helper = _HELPER.replace("__STEP__", repr(PROBE_STEP_FT)).replace("__BISECT__", repr(BISECT_STEPS))
        src = src[:i + 1] + helper + src[i + 1:]
        src = src.replace(_CAP_CALL, _CAP_NEW, 1)
        src = src.replace(_SPLITS, _SPLITS_NEW, 1)
        src = src.replace(_TOP, _TOP_NEW, 1)
        info["applied"] = True
    except Exception:
        info["error"] = traceback.format_exc()[-600:]
    return src, info
