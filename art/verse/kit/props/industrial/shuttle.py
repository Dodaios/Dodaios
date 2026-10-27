"""The arrival shuttle of the main hangar (deck 4): an original ~20 m gunship.

A faceted wedge-nosed transport parked on three landing legs, its swept wings
out with a little anhedral, two aft engine nacelles and a lit rear ramp
lowered to the deck. It is armed: a twin cannon chin turret, a dorsal turret,
wingtip cannons and missile pods on the sponsons.

The hull is hollow and the cabin is walkable: up the ramp, through the ramp
corridor between the engine housings, into the troop bay (crew seats, weapon
racks, a tactical table), up two steps and through the passage into the
cockpit under the canopy. The hull shell is one object whose inner skin faces
into the cabin, so the nav cook sees a closed solid with a cavity: roof above
the cabin, floor pan below it (see `lib.cook._column_floor`).

Piece-local frame: nose toward +Y (away from the camera), ramp toward -Y (the
camera side), centred on X, deck at Z = 0.
"""

from __future__ import annotations

import math

import bpy
from lib import kit as K
from mathutils import Vector

from . import _geo as G
from ._mats import m

# (y, half width, belly z, roof z) stations of the faceted hull, aft to nose.
STATIONS = (
    (-9.6, 2.25, 1.5, 4.55),
    (-7.2, 2.55, 1.35, 4.95),
    (-2.4, 2.6, 1.3, 5.1),
    (2.4, 2.55, 1.32, 5.0),
    (5.4, 2.35, 1.42, 4.75),
    (7.6, 2.0, 1.6, 4.25),
    (9.4, 1.45, 1.95, 3.6),
    (10.3, 0.95, 2.3, 3.1),
)
# (station, facet) pairs under the canopy glass: the hull is open there.
COCKPIT_FACETS = {
    (4, 3),
    (4, 4),
    (4, 5),
    (5, 3),
    (5, 4),
    (5, 5),
    (6, 2),
    (6, 3),
    (6, 4),
    (6, 5),
    (6, 6),
}

# Cabin (piece-local metres). Floors are the walk surfaces' tops.
CABIN_FLOOR = 1.6
COCKPIT_FLOOR = 2.0
PLATE_T = 0.025  # walk plates on the floor pans
CORRIDOR_Y = (-9.6, -5.0)  # ramp corridor between the engine housings
BAY_Y = (-5.0, 4.33)  # troop bay (ends off the nav sample grid)
PASSAGE_Y = (4.33, 5.4)  # passage up into the cockpit
COCKPIT_Y = (5.4, 8.4)  # cockpit under the canopy, dash at its front
STEPS = ((3.5, 3.9, 1.8), (3.9, 4.33, 2.0))  # (y0, y1, top z) up to the passage
# Shell thickness per facet group: bottom, sides, top (the top leaves room
# for the roof grilles and the spine inside the shell).
INSET = (0.12, 0.2, 0.4)
CORRIDOR = (
    (-0.85, 0.0),
    (0.85, 0.0),
    (0.98, 0.13),
    (0.98, 1.85),
    (0.6, 2.35),
    (-0.6, 2.35),
    (-0.98, 1.85),
    (-0.98, 0.13),
)  # (x, height above CABIN_FLOOR), the same order as a hull section
PASSAGE = (
    (-0.75, 0.0),
    (0.75, 0.0),
    (0.88, 0.13),
    (0.88, 1.7),
    (0.55, 2.15),
    (-0.55, 2.15),
    (-0.88, 1.7),
    (-0.88, 0.13),
)  # (x, height above COCKPIT_FLOOR)
CABIN_CEILING_M = 3.4  # height band of the cabin room above CABIN_FLOOR
TABLE_Y = -1.0  # tactical table in the troop bay

RAMP_WIDTH = 1.76
RAMP_HINGE = (-9.6, CABIN_FLOOR)  # (y, z)
RAMP_LENGTH = 4.4

# Wings: swept back, out in flight position with a slight anhedral.
WING_FOLD_DEG = -6.0  # positive folds the tips up
WING_HINGE_X = 2.75
WING_SPAN = 5.2
WING_ROOT = (2.4, -6.2)  # (leading, trailing) edge y at the root
WING_TIP = (-3.4, -6.0)  # at the tip


# ---------------------------------------------------------------- sections


def _section(y, w, z0, z1):
    """Faceted octagonal hull section (counter-clockwise seen from +Y)."""
    h = z1 - z0
    return [
        (-w * 0.72, y, z0),
        (w * 0.72, y, z0),
        (w, y, z0 + 0.22 * h),
        (w, y, z0 + 0.58 * h),
        (w * 0.56, y, z1),
        (-w * 0.56, y, z1),
        (-w, y, z0 + 0.58 * h),
        (-w, y, z0 + 0.22 * h),
    ]


def _sections():
    return [_section(*s) for s in STATIONS]


def hull_at(y: float):
    """Hull section at any y between the first and last station (linear between)."""
    for a, b in zip(STATIONS, STATIONS[1:], strict=False):
        if a[0] <= y <= b[0]:
            t = (y - a[0]) / (b[0] - a[0])
            return _section(y, *(a[i] + (b[i] - a[i]) * t for i in (1, 2, 3)))
    raise ValueError(f"y {y} outside the hull")


def _line_offset(p, q, d):
    """Edge p->q of a counter-clockwise XZ polygon moved inward by d: (point, direction)."""
    dx, dz = q[0] - p[0], q[1] - p[1]
    n = math.hypot(dx, dz)
    nx, nz = -dz / n, dx / n  # inward normal of a CCW polygon
    return (p[0] + nx * d, p[1] + nz * d), (dx, dz)


def _intersect(l1, l2):
    (px, pz), (dx, dz) = l1
    (qx, qz), (ex, ez) = l2
    det = dx * (-ez) - dz * (-ex)
    t = ((qx - px) * (-ez) - (qz - pz) * (-ex)) / det
    return px + dx * t, pz + dz * t


def cavity_at(y: float, floor: float):
    """Cabin cross-section at y: the hull section moved inward by INSET, cut by the floor.

    Returns 8 (x, y, z) points in hull-section order; the first two lie on the floor.
    """
    sec = [(p[0], p[2]) for p in hull_at(y)]
    bottom, side, top = INSET
    insets = (bottom, bottom, side, top, top, top, side, bottom)
    lines = [_line_offset(sec[j], sec[(j + 1) % 8], insets[j]) for j in range(8)]
    pts = [_intersect(lines[j - 1], lines[j]) for j in range(8)]
    if floor <= pts[1][1] or floor >= pts[2][1]:
        raise ValueError(f"floor {floor} outside the lower bevel at y {y}")
    flat = ((0.0, floor), (1.0, 0.0))
    right = _intersect(flat, lines[1])
    left = _intersect(flat, lines[7])
    out = [left, right, *pts[2:]]
    return [(x, y, z) for x, z in out]


def _fixed(profile, y, floor):
    return [(x, y, floor + h) for x, h in profile]


def bay_at(y: float):
    return cavity_at(y, CABIN_FLOOR)


def cabin_outline():
    """Floor outline of the whole cabin (piece-local XY, counter-clockwise), for its room."""
    c0, c1 = CORRIDOR_Y
    b1 = BAY_Y[1]
    p1 = PASSAGE_Y[1]
    k1 = COCKPIT_Y[1] - 0.3
    bw0, bw1 = bay_at(c1 + 0.01)[1][0], bay_at(b1)[1][0]
    kw0, kw1 = cavity_at(p1, COCKPIT_FLOOR)[1][0], cavity_at(k1, COCKPIT_FLOOR)[1][0]
    cw, pw = CORRIDOR[1][0], PASSAGE[1][0]
    right = [(cw, c0), (cw, c1), (bw0, c1), (bw1, b1), (pw, b1), (pw, p1), (kw0, p1), (kw1, k1)]
    left = [(-x, y) for x, y in reversed(right)]
    return [*right, *left]


# ---------------------------------------------------------------- mesh helpers


def _face(mb, pts, want, material):
    """Add a planar-ish polygon whose normal points along `want` (flipped if needed)."""
    vs = [Vector(p) for p in pts]
    n = Vector()
    for i, a in enumerate(vs):  # Newell normal
        b = vs[(i + 1) % len(vs)]
        n += Vector(
            ((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y))
        )
    if n.length < 1e-9:
        return
    if n.dot(Vector(want)) < 0:
        vs.reverse()
    mb._add(vs, [tuple(range(len(vs)))], material)


def _centre(sec):
    xs = [p[0] for p in sec]
    zs = [p[2] for p in sec]
    return Vector((0.0, sec[0][1], (min(zs) + max(zs)) / 2)) if xs else Vector()


def _band(mb, a, b, materials, inward, skip=()):
    """Quads between two 8-point sections; normals toward (inward) or away from the axis."""
    ca, cb = _centre(a), _centre(b)
    for j in range(8):
        if j in skip:
            continue
        j2 = (j + 1) % 8
        quad = [a[j], a[j2], b[j2], b[j]]
        mid = sum((Vector(p) for p in quad), Vector()) / 4
        axis = (ca + cb) / 2
        axis.y = mid.y
        want = (axis - mid) if inward else (mid - axis)
        _face(mb, quad, want, materials[j])


def _annulus(mb, outer, inner, want, material, skip=()):
    """Planar ring between two 8-point sections at the same y."""
    for j in range(8):
        if j in skip:
            continue
        j2 = (j + 1) % 8
        _face(mb, [outer[j], outer[j2], inner[j2], inner[j]], want, material)


def _slab(mb, quad, lift, material):
    """Raised plate on a quad: top face lifted along its normal, with sides."""
    q = [Vector(p) for p in quad]
    n = (q[1] - q[0]).cross(q[2] - q[1]).normalized()
    q = [p + n * 0.002 for p in q]  # off the skin: a coplanar underside would hide from rays
    top = [p + n * lift for p in q]
    mb._add(
        [*q, *top],
        [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)],
        material,
    )


def _cell(a, b, c, d, u0, u1, v0, v1, inset):
    """Bilinear sub-quad of quad (a, b, c, d) with an absolute inset in metres."""

    def lerp(u, v):
        return (a * (1 - u) + b * u) * (1 - v) + (d * (1 - u) + c * u) * v

    p = [lerp(u0, v0), lerp(u1, v0), lerp(u1, v1), lerp(u0, v1)]
    centre = sum(p, Vector()) / 4
    return [q + (centre - q).normalized() * min(inset, (centre - q).length * 0.4) for q in p]


def _toward(p, c, d):
    """Point p moved distance d toward c (XZ plane, same y)."""
    v = Vector((c[0] - p[0], 0.0, c[2] - p[2]))
    if v.length < 1e-9:
        return Vector(p)
    return Vector(p) + v.normalized() * d


# ---------------------------------------------------------------- the piece


def build_shuttle() -> None:
    """Original faceted gunship: hollow walkable hull, ramp down, armed, lit cabin."""
    rnd = G.rng("shuttle")
    secs = _sections()

    shell = K.MeshBuilder()  # explicit winding: the inner skin faces into the cabin
    _shell(shell, secs)
    shell.build("SM_Hangar_Shuttle_shell", bevel_width=0.015, angle_deg=25.0, recalc_normals=False)

    body = K.MeshBuilder()
    _door_frame(body)
    _sponsons(body, rnd)
    _nacelles(body)
    _hinges_and_wings(body)
    body.build("SM_Hangar_Shuttle_hull", bevel_width=0.02, angle_deg=25.0)

    # Skin details and roof gear: none of it reaches down to a floor's
    # headroom, and its open or coplanar faces would confuse the nav rays.
    skin = K.MeshBuilder()
    _plate_hull(skin, secs, rnd)
    _spine(skin)
    _canopy_frame(skin, secs)
    _dorsal_turret(skin)
    skin.build("SM_Hangar_Shuttle_skin", bevel_width=0.02, angle_deg=25.0, nav="none")

    arms = K.MeshBuilder()
    _chin_turret(arms)
    _missile_pods(arms)
    arms.build("SM_Hangar_Shuttle_weapons", bevel_width=0.008, angle_deg=30.0)

    gear = K.MeshBuilder()
    for x, y, z in ((0.0, 7.0, STATIONS[4][2]), (-2.0, -5.0, 1.33), (2.0, -5.0, 1.33)):
        _leg(gear, x, y, z)
    gear.build("SM_Hangar_Shuttle_gear", bevel_width=0.01, nav="block")
    ramp = K.MeshBuilder()
    _ramp(ramp)
    ramp.build("SM_Hangar_Shuttle_ramp", bevel_width=0.01, nav="walk")  # crew walk up it
    rails = K.MeshBuilder()
    _ramp_rails(rails)
    # The ramp's open sides already end the walkable floor; the rails only show it.
    rails.build("SM_Hangar_Shuttle_ramp_rails", bevel_width=0.004, nav="none")
    intake = K.MeshBuilder()  # fuel intake on the starboard sponson (hoses end here)
    intake.box((3.05, -5.9, 1.55), (3.1, -5.1, 2.05), m("dark_steel"))
    intake.tube((3.1, -5.5, 1.8), (3.28, -5.5, 1.8), 0.11, m("gunmetal"), 14)
    intake.box((3.06, -5.95, 2.1), (3.1, -5.05, 2.16), m("hazard"))
    # dorsal service hatch with grab handle (port side of the spine)
    intake.box((-1.35, 0.4, 5.105), (-0.75, 1.5, 5.15), m("dark_steel"))
    intake.box((-1.2, 0.6, 5.15), (-0.9, 0.66, 5.19), m("gunmetal"))
    intake.build("SM_Hangar_Shuttle_intake", bevel_width=0.006, nav="block")

    floors = K.MeshBuilder()
    _cabin_floors(floors)
    floors.build("SM_Hangar_Shuttle_floor", bevel_width=0.004, recalc_normals=False, nav="walk")

    cabin = K.MeshBuilder()
    frames = K.MeshBuilder()  # ribs and panels: explicit winding, open strips
    _corridor_fit(cabin, frames)
    _bay_fit(cabin, frames)
    _cockpit_fit(cabin)
    cabin.build("SM_Hangar_Shuttle_cabin", bevel_width=0.006, angle_deg=30.0, nav="block")
    frames.build(
        "SM_Hangar_Shuttle_frames",
        bevel_width=0.006,
        angle_deg=30.0,
        recalc_normals=False,
        nav="block",
    )

    glass = K.MeshBuilder()
    _cockpit(glass, secs)
    glass.build("SM_Hangar_Shuttle_glass", bevel_width=0.0, nav="none")

    lamps = K.MeshBuilder()
    _cabin_and_lamps(lamps)
    lamps.build("SM_Hangar_Shuttle_lamps", bevel_width=0.0, nav="none")

    marks = K.MeshBuilder()
    _markings(marks, secs)
    marks.build("SM_Hangar_Shuttle_marks", bevel_width=0.0, nav="none")

    _cabin_lights()
    hy, hz = RAMP_HINGE
    foot = hy - RAMP_LENGTH * math.cos(math.asin(hz / RAMP_LENGTH))
    K.socket("spawn", "arrival", K.socket_matrix((0.0, foot - 0.8, 0.0), (0, 0, 1), up=(0, 1, 0)))
    K.socket("waypoint", "ramp_top", K.socket_matrix((0.0, hy + 1.0, hz), (0, 0, 1), up=(0, 1, 0)))
    K.socket("light", "cabin", K.socket_matrix((0.0, hy + 2.0, 3.2), (0, -1, 0)))
    _occluders(secs)


# ---------------------------------------------------------------- shell


SHELL_MATS = {
    # cavity facet j -> material: floor pan, kick bevels, walls, upper chines, ceiling
    "bay": (
        "M_Wall_PaintedDark",
        "M_Wall_Charcoal",
        "M_Wall_PaintedDark",
        "M_Wall_Charcoal",
        "M_Ceiling_Panel",
        "M_Wall_Charcoal",
        "M_Wall_PaintedDark",
        "M_Wall_Charcoal",
    ),
}


def _shell(mb, secs):
    """Outer skin, aft face around the door, and the cabin's inner skin, one solid."""
    hull = m("hull_paint")
    inner = SHELL_MATS["bay"]
    bulkhead = "M_Wall_PaintedDark"
    # outer skin, open under the canopy
    for s in range(len(secs) - 1):
        skip = {j for (ss, j) in COCKPIT_FACETS if ss == s}
        _band(mb, secs[s], secs[s + 1], [hull] * 8, inward=False, skip=skip)
    _face(mb, secs[-1], (0, 1, 0), hull)  # nose cap

    c0, c1 = CORRIDOR_Y
    corridor_a = _fixed(CORRIDOR, c0, CABIN_FLOOR)
    corridor_b = _fixed(CORRIDOR, c1, CABIN_FLOOR)
    _annulus(mb, secs[0], corridor_a, (0, -1, 0), hull)  # aft face, the door is the corridor
    _band(mb, corridor_a, corridor_b, inner, inward=True)

    bay_ys = (BAY_Y[0], -2.4, 2.4, BAY_Y[1])
    bay = [bay_at(y) for y in bay_ys]
    _annulus(mb, bay[0], corridor_b, (0, 1, 0), bulkhead)  # aft bay bulkhead
    for a, b in zip(bay, bay[1:], strict=False):
        _band(mb, a, b, inner, inward=True)

    p0, p1 = PASSAGE_Y
    passage_a = _fixed(PASSAGE, p0, COCKPIT_FLOOR)
    passage_b = _fixed(PASSAGE, p1, COCKPIT_FLOOR)
    _annulus(mb, bay[-1], passage_a, (0, -1, 0), bulkhead)  # forward bay bulkhead
    _band(mb, passage_a, passage_b, inner, inward=True)

    # cockpit: open top under the canopy; a sill joins its walls to the hull opening
    ys = (COCKPIT_Y[0], STATIONS[5][0], COCKPIT_Y[1])
    pit = [cavity_at(y, COCKPIT_FLOOR) for y in ys]
    rim = [hull_at(y) for y in ys]
    for a, b in zip(pit, pit[1:], strict=False):
        _band(mb, a, b, inner, inward=True, skip={3, 4, 5})
    for a, b, ra, rb in zip(pit, pit[1:], rim, rim[1:], strict=False):
        for j in (3, 6):
            _face(mb, [a[j], ra[j], rb[j], b[j]], (0, 0, 1), "M_Wall_Charcoal")
    # header over the passage: from the passage top up to the canopy's aft edge
    hd, pa = rim[0], pit[0]
    _face(mb, [passage_b[1], pa[1], pa[2], passage_b[2]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[0], pa[0], pa[7], passage_b[7]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[2], pa[2], pa[3], passage_b[3]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[7], pa[7], pa[6], passage_b[6]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[3], pa[3], hd[3], hd[4], passage_b[4]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[4], hd[4], hd[5], passage_b[5]], (0, 1, 0), bulkhead)
    _face(mb, [passage_b[5], hd[5], hd[6], pa[6], passage_b[6]], (0, 1, 0), bulkhead)
    # dash front, glare shield, and the deck under the nose window
    end = pit[-1]
    _face(mb, [end[0], end[1], end[2], end[3], end[6], end[7]], (0, -1, 0), "M_Console_Body")
    n6 = secs[6]
    _face(mb, [end[6], end[3], n6[3], n6[6]], (0, 0, 1), "M_Console_Body")
    _face(mb, [rim[-1][3], end[3], n6[3]], (0, 0, 1), "M_Console_Body")
    _face(mb, [rim[-1][6], end[6], n6[6]], (0, 0, 1), "M_Console_Body")
    _face(mb, [n6[2], n6[3], n6[6], n6[7]], (0, 1, 0), "M_Console_Body")
    n7 = secs[7]
    _face(mb, [n6[7], n6[2], n7[2], n7[7]], (0, 0, 1), "M_Console_Body")


def _door_frame(mb):
    """Heavy frame around the aft door, amber-striped threshold."""
    steel = m("dark_steel")
    y = CORRIDOR_Y[0]
    z0 = CABIN_FLOOR
    top = z0 + CORRIDOR[4][1]
    hw = CORRIDOR[2][0]
    mb.box((-hw - 0.24, y - 0.16, z0 - 0.1), (-hw, y + 0.04, top + 0.1), steel)
    mb.box((hw, y - 0.16, z0 - 0.1), (hw + 0.24, y + 0.04, top + 0.1), steel)
    mb.box((-hw - 0.24, y - 0.16, top - 0.12), (hw + 0.24, y + 0.04, top + 0.2), steel)


# ---------------------------------------------------------------- outer details


def _plate_hull(mb, secs, rnd):
    """Panel plating on every facet: raised plates, vents and hatches."""
    hull, steel = m("hull_paint"), m("dark_steel")
    for s in range(len(secs) - 1):
        for j in range(8):
            if (s, j) in COCKPIT_FACETS:
                continue
            a, b = Vector(secs[s][j]), Vector(secs[s][(j + 1) % 8])
            d, c = Vector(secs[s + 1][j]), Vector(secs[s + 1][(j + 1) % 8])
            span = (d - a).length
            width = (b - a).length
            if j == 0 or width < 0.4:  # belly: plain
                continue
            rows = max(1, round(span / 1.6))
            cols = max(1, round(width / 1.4))
            for r in range(rows):
                for k in range(cols):
                    roll = rnd.random()
                    if roll < 0.12:
                        continue
                    quad = _cell(
                        a, b, c, d, k / cols, (k + 1) / cols, r / rows, (r + 1) / rows, 0.035
                    )
                    _slab(
                        mb,
                        quad[::-1],
                        0.018 if roll < 0.85 else 0.03,
                        hull if roll < 0.9 else steel,
                    )


def _spine(mb):
    """Dorsal spine, sensor housing, heat exchanger grilles and antennae."""
    hull, steel, metal = m("hull_paint"), m("dark_steel"), m("gunmetal")
    roof = 5.1
    G.prism_z_any(
        mb,
        [(-0.55, -8.4), (0.55, -8.4), (0.7, 3.0), (0.3, 5.0), (-0.3, 5.0), (-0.7, 3.0)],
        roof - 0.2,
        roof + 0.32,
        hull,
    )
    G.chamfer_box(mb, (-0.45, -1.0, roof + 0.3), (0.45, 1.4, roof + 0.62), 0.18, steel)
    G.lathe(mb, [(0.0, roof + 0.95), (0.32, roof + 0.88), (0.42, roof + 0.62)], metal, 24)
    for sx in (-1, 1):  # heat exchanger grilles, aft roof
        x0, x1 = (0.85, 1.55) if sx > 0 else (-1.55, -0.85)
        mb.box((x0, -8.0, roof - 0.3), (x1, -4.0, roof - 0.02), steel)
        for k in range(14):
            yy = -7.85 + k * 0.27
            mb.box((x0 + 0.05, yy, roof - 0.02), (x1 - 0.05, yy + 0.12, roof + 0.05), metal)
    mb.tube((0.25, -8.1, roof + 0.3), (0.25, -8.1, roof + 1.4), 0.025, metal, 8)
    mb.tube((-0.25, -8.4, roof + 0.3), (-0.25, -8.4, roof + 1.0), 0.02, metal, 8)


def _nacelles(mb):
    """Two aft engine nacelles flanking the ramp, three nozzles each."""
    hull, steel, metal = m("hull_paint"), m("dark_steel"), m("gunmetal")
    for sx in (-1, 1):
        cx = sx * 1.95
        G.chamfer_box(mb, (cx - 0.95, -10.3, 1.75), (cx + 0.95, -5.2, 3.75), 0.32, hull)
        G.chamfer_box(mb, (cx - 0.8, -10.5, 1.9), (cx + 0.8, -10.25, 3.6), 0.28, steel)
        for k, (dx, dz) in enumerate(((-0.4, 2.3), (0.4, 2.3), (0.0, 3.15))):
            px, pz = cx + dx * sx, dz
            G.lathe_y(
                mb,
                px,
                pz,
                -10.5,
                [(0.36, 0.0), (0.36, 0.35), (0.3, 0.42), (0.22, 0.1), (0.0, 0.05)],
                metal if k < 2 else steel,
            )
        for k in range(6):  # intake fins on the outboard face
            zz = 2.0 + k * 0.28
            x_out = cx + sx * 0.95
            mb.box(
                (min(x_out, x_out + sx * 0.06), -8.8, zz),
                (max(x_out, x_out + sx * 0.06), -6.0, zz + 0.12),
                steel,
            )


def _wing_mesh(mb, root, tip, span, t_root, t_tip, material):
    """Wing in local frame: span along +X, chord along Y, thickness along Z,
    with raised panels on the upper skin."""

    def foil(x, lead, trail, t):
        c = lead - trail
        return [
            (x, lead, 0.0),
            (x, lead - 0.25 * c, t / 2),
            (x, trail + 0.12 * c, t * 0.3),
            (x, trail, 0.0),
            (x, trail + 0.12 * c, -t * 0.3),
            (x, lead - 0.25 * c, -t / 2),
        ]

    r_sec, t_sec = foil(0.0, *root, t_root), foil(span, *tip, t_tip)
    G.loft(mb, [r_sec, t_sec], material)
    a, b = Vector(r_sec[2]), Vector(r_sec[1])
    d, c = Vector(t_sec[2]), Vector(t_sec[1])
    for r in range(3):
        for k in range(2):
            quad = _cell(a, b, c, d, k / 2, (k + 1) / 2, r / 3, (r + 1) / 3, 0.06)
            _slab(mb, list(reversed(quad)), 0.014, material)


def _wingtip_cannon(mb, span, tip):
    """Long-barrelled cannon pod on the wing tip, firing forward."""
    steel, metal = m("dark_steel"), m("gunmetal")
    lead, trail = tip
    x = span + 0.1
    G.chamfer_box(
        mb, (span - 0.12, trail + 0.1, -0.17), (span + 0.32, lead + 0.7, 0.17), 0.07, steel
    )
    y0, y1 = lead + 0.7, lead + 3.6
    mb.tube((x, y0, 0.0), (x, y1, 0.0), 0.065, metal, 14)
    for k in range(4):  # cooling rings
        yy = y0 + 0.25 + k * 0.32
        mb.tube((x, yy, 0.0), (x, yy + 0.08, 0.0), 0.1, steel, 14)
    mb.tube((x, y1 - 0.05, 0.0), (x, y1 + 0.3, 0.0), 0.095, steel, 14)  # muzzle brake
    mb.box((x - 0.12, y1 + 0.12, -0.025), (x + 0.12, y1 + 0.2, 0.025), metal)


def _hinges_and_wings(mb):
    """Wing roots at the upper chines; swept wings out, cannons on the tips."""
    hull, steel, metal = m("hull_paint"), m("dark_steel"), m("gunmetal")
    z_hinge = STATIONS[2][2] + 0.58 * (STATIONS[2][3] - STATIONS[2][2])
    for sx in (-1, 1):
        x_h = sx * WING_HINGE_X
        mb.tube((x_h, -6.4, z_hinge), (x_h, 2.0, z_hinge), 0.22, metal, 16)
        for yy in (-5.6, -2.2, 1.0):
            G.chamfer_box(
                mb,
                (x_h - 0.28, yy - 0.4, z_hinge - 0.5),
                (x_h + 0.28, yy + 0.4, z_hinge + 0.28),
                0.1,
                steel,
            )
        frame = G.T(x_h, 0.0, z_hinge) @ G.Ry(-sx * WING_FOLD_DEG)
        if sx < 0:
            frame = frame @ G.S(-1.0, 1.0, 1.0)
        with G.xf(mb, frame):
            _wing_mesh(mb, WING_ROOT, WING_TIP, WING_SPAN, 0.42, 0.16, hull)
            _wingtip_cannon(mb, WING_SPAN, WING_TIP)


def _sponsons(mb, rnd):
    """Side cargo sponsons along the lower hull with hatches and vents."""
    hull, steel = m("hull_paint"), m("dark_steel")
    for sx in (-1, 1):
        x0 = sx * 2.45
        x1 = sx * 3.05
        xa, xb = sorted((x0, x1))
        G.chamfer_box(mb, (xa, -6.6, 1.25), (xb, 4.2, 2.75), 0.18, hull)
        G.chamfer_box(mb, (xa + 0.06, -6.3, 2.75), (xb - 0.06, 3.9, 2.85), 0.15, hull)
        for k in range(4):  # hatch plates on the outer face
            y = -5.8 + k * 2.5
            xo = sx * 3.05
            mb.box(
                (min(xo, xo + sx * 0.02), y, 1.45),
                (max(xo, xo + sx * 0.02), y + 2.0, 2.55),
                hull if k % 2 else steel,
            )
        for k in range(6):  # top vent slots
            y = -5.6 + k * 0.35
            mb.box((xa + 0.15, y, 2.85), (xb - 0.15, y + 0.18, 2.88), steel)


def _chin_turret(mb):
    """Twin heavy cannons in a ball mount under the nose."""
    steel, metal = m("dark_steel"), m("gunmetal")
    cx, cy, cz = 0.0, 8.3, 1.62
    with G.xf(mb, G.T(cx, cy, cz)):
        G.lathe(
            mb,
            [(0.0, -0.42), (0.3, -0.38), (0.46, -0.2), (0.5, 0.05), (0.42, 0.28), (0.0, 0.32)],
            steel,
            24,
        )
    mb.box((-0.36, cy - 0.3, cz + 0.2), (0.36, cy + 0.4, STATIONS[5][2] + 0.08), steel)
    for sx in (-1, 1):
        x = sx * 0.2
        mb.box((x - 0.11, cy + 0.2, cz - 0.15), (x + 0.11, cy + 0.9, cz + 0.08), metal)
        mb.tube((x, cy + 0.9, cz - 0.04), (x, cy + 3.1, cz - 0.04), 0.055, metal, 14)
        mb.tube((x, cy + 0.9, cz - 0.04), (x, cy + 1.8, cz - 0.04), 0.085, steel, 14)
        mb.tube((x, cy + 3.0, cz - 0.04), (x, cy + 3.3, cz - 0.04), 0.08, steel, 14)


def _dorsal_turret(mb):
    """Twin-barrel turret on the aft spine."""
    steel, metal = m("dark_steel"), m("gunmetal")
    top = 5.42
    cy = -5.6
    with G.xf(mb, G.T(0.0, cy, top)):
        G.lathe(mb, [(0.0, 0.0), (0.72, 0.0), (0.72, 0.12), (0.62, 0.22), (0.0, 0.22)], metal, 32)
    G.chamfer_box(mb, (-0.58, cy - 0.7, top + 0.2), (0.58, cy + 0.75, top + 0.68), 0.16, steel)
    G.chamfer_box(mb, (-0.4, cy - 0.5, top + 0.66), (0.4, cy + 0.4, top + 0.8), 0.06, metal)
    for sx in (-1, 1):
        x = sx * 0.24
        mb.box((x - 0.1, cy + 0.7, top + 0.36), (x + 0.1, cy + 1.2, top + 0.56), metal)
        mb.tube((x, cy + 1.2, top + 0.46), (x, cy + 3.4, top + 0.46), 0.05, metal, 12)
        mb.tube((x, cy + 1.2, top + 0.46), (x, cy + 2.0, top + 0.46), 0.08, steel, 12)
        mb.tube((x, cy + 3.3, top + 0.46), (x, cy + 3.55, top + 0.46), 0.075, steel, 12)


def _missile_pods(mb):
    """Missile pods on the forward ends of the sponsons, six cells each."""
    steel, void = m("dark_steel"), m("void_black")
    for sx in (-1, 1):
        xa, xb = sorted((sx * 2.5, sx * 3.0))
        y0, y1 = 2.6, 4.5
        z0, z1 = 2.85, 3.28
        G.chamfer_box(mb, (xa, y0, z0), (xb, y1, z1), 0.06, steel)
        w, h = (xb - xa) / 3, (z1 - z0) / 2
        for i in range(3):
            for k in range(2):
                cx = xa + w * (i + 0.5)
                cz = z0 + h * (k + 0.5)
                mb.box(
                    (cx - w * 0.36, y1 - 0.02, cz - h * 0.34),
                    (cx + w * 0.36, y1 + 0.01, cz + h * 0.34),
                    void,
                )
        mb.box((xa + 0.05, y0 - 0.05, z0 + 0.06), (xb - 0.05, y0 + 0.02, z1 - 0.06), m("gunmetal"))


def _leg(mb, x, y, z_belly):
    """Landing leg: oleo strut, drag brace, foot pad and gear bay doors."""
    metal, steel = m("gunmetal"), m("dark_steel")
    mb.tube((x, y, z_belly), (x, y, 0.75), 0.17, metal, 14)
    mb.tube((x, y, 0.8), (x, y, 0.2), 0.11, m("panel_light"), 14)
    with G.xf(mb, G.T(x, y, 0.0)):
        G.lathe(
            mb,
            [(0.0, 0.0), (0.55, 0.0), (0.55, 0.1), (0.4, 0.18), (0.12, 0.22), (0.0, 0.22)],
            steel,
            24,
        )
    mb.tube((x, y + 1.1, z_belly), (x, y + 0.05, 0.9), 0.07, metal, 10)
    for sx in (-1, 1):
        mb.box(
            (x + sx * 0.45 - 0.03, y - 0.9, z_belly - 0.85),
            (x + sx * 0.45 + 0.03, y + 0.9, z_belly - 0.02),
            m("hull_paint"),
        )


def _ramp(mb):
    """Rear ramp lowered to the deck, with treads, side skirts and rams."""
    hy, hz = RAMP_HINGE
    ang = math.asin(hz / RAMP_LENGTH)
    hw = RAMP_WIDTH / 2
    frame = G.T(0.0, hy, hz) @ G.Rx(math.degrees(ang))  # the free end down on the deck
    metal = m("gunmetal")
    with G.xf(mb, frame):
        mb.box((-hw, -RAMP_LENGTH, -0.14), (hw, 0.0, 0.0), m("panel_dark"))
        for k in range(11):
            yy = -RAMP_LENGTH + 0.25 + k * 0.38
            mb.box((-hw + 0.12, yy, 0.0), (hw - 0.12, yy + 0.07, 0.025), metal)
        for sx in (-1, 1):
            x0 = sx * hw
            mb.box(
                (min(x0, x0 - sx * 0.07), -RAMP_LENGTH, -0.14),
                (max(x0, x0 - sx * 0.07), 0.0, 0.12),
                m("hull_paint"),
            )
    for sx in (-1, 1):
        mb.tube(
            (sx * (hw - 0.2), hy + 0.6, hz - 0.05),
            (sx * (hw - 0.2), hy - 1.9, hz - 1.9 * math.tan(ang) - 0.2),
            0.05,
            metal,
            10,
        )


def _ramp_rails(mb):
    """Hand rails down both sides of the ramp: you can see you cannot step off it.

    Vertical gunmetal posts stand on the side skirts; a top rail at hand
    height and a knee rail run parallel to the ramp, and a small amber lamp
    marks each post head.
    """
    hy, hz = RAMP_HINGE
    ang = math.asin(hz / RAMP_LENGTH)
    hw = RAMP_WIDTH / 2
    skirt = 0.12  # top of the side skirts above the ramp plate
    top, knee = 0.95, 0.5  # rail heights above the ramp surface

    def on_ramp(t, x, lift):
        """World point `t` metres down the ramp from the hinge, `lift` metres above it."""
        return (x, hy - t * math.cos(ang), hz - t * math.sin(ang) + lift)

    stations = (0.2, 1.55, 2.9, 4.2)
    metal = m("gunmetal")
    for sx in (-1, 1):
        x = sx * (hw - 0.035)
        for t in stations:
            base = on_ramp(t, x, skirt)
            head = on_ramp(t, x, top + 0.03)
            mb.box((x - 0.03, base[1] - 0.03, base[2]), (x + 0.03, base[1] + 0.03, head[2]), metal)
            mb.box(
                (x - 0.022, head[1] - 0.022, head[2]),
                (x + 0.022, head[1] + 0.022, head[2] + 0.025),
                m("lamp_amber"),
            )
        a, b = stations[0], stations[-1]
        mb.tube(on_ramp(a - 0.12, x, top), on_ramp(b + 0.08, x, top), 0.026, metal, 14)
        mb.tube(on_ramp(a, x, knee), on_ramp(b, x, knee), 0.014, metal, 10)


def _cockpit(mb, secs):
    """Canopy panes on the nose's upper facets with mullions between them."""
    glass = "M_Glass_Viewport"  # see-through: the hangar lights the cockpit, the crew look out
    for s, j in sorted(COCKPIT_FACETS):
        a, b = Vector(secs[s][j]), Vector(secs[s][(j + 1) % 8])
        d, c = Vector(secs[s + 1][j]), Vector(secs[s + 1][(j + 1) % 8])
        quad = _cell(a, b, c, d, 0.0, 1.0, 0.0, 1.0, 0.07)[::-1]  # outward winding
        n = (quad[1] - quad[0]).cross(quad[2] - quad[1]).normalized()
        mb.quad([p + n * 0.01 for p in quad], glass)


def _canopy_frame(mb, secs):
    """Hull-white mullions along the canopy's facet edges (the panes sit between them)."""
    hull = m("hull_paint")
    edges = set()
    for s, j in COCKPIT_FACETS:
        for a, b in (
            ((s, j), (s, (j + 1) % 8)),
            ((s + 1, j), (s + 1, (j + 1) % 8)),
            ((s, j), (s + 1, j)),
            ((s, (j + 1) % 8), (s + 1, (j + 1) % 8)),
        ):
            edges.add(tuple(sorted((a, b))))
    for (s0, j0), (s1, j1) in sorted(edges):
        p, q = Vector(secs[s0][j0]), Vector(secs[s1][j1])
        mid = (p + q) / 2
        up = (mid - Vector((0.0, mid.y, 2.6))).normalized()
        G.beam(mb, p + up * 0.012, q + up * 0.012, 0.15, 0.035, hull, up=up)


# ---------------------------------------------------------------- cabin


def _plate(mb, poly_xy, z0, z1, material):
    """Prism with explicit outward faces: the nav cook reads the top's normal."""
    lo = [(x, y, z0) for x, y in poly_xy]
    hi = [(x, y, z1) for x, y in poly_xy]
    cx = sum(x for x, _ in poly_xy) / len(poly_xy)
    cy = sum(y for _, y in poly_xy) / len(poly_xy)
    _face(mb, hi, (0, 0, 1), material)
    _face(mb, lo, (0, 0, -1), material)
    n = len(poly_xy)
    for i in range(n):
        a, b = poly_xy[i], poly_xy[(i + 1) % n]
        out = ((a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy, 0.0)
        _face(mb, [lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]], out, material)


def _rect(mb, lo, hi, material):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    _plate(mb, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z0, z1, material)


def _cabin_floors(mb):
    """Walk plates: corridor tread, bay deck with a grating aisle, steps, cockpit deck."""
    t = PLATE_T
    c0, c1 = CORRIDOR_Y
    cw = CORRIDOR[1][0]
    _rect(mb, (-cw, c0 - 0.05, CABIN_FLOOR - t), (cw, c1 + 0.05, CABIN_FLOOR), m("tread"))
    b0, b1 = BAY_Y
    ys = (b0, -2.4, 2.4, b1)
    right = [(bay_at(y)[1][0], y) for y in ys]
    poly = [*right, *[(-x, y) for x, y in reversed(right)]]
    _plate(mb, poly, CABIN_FLOOR - t, CABIN_FLOOR, m("floor"))
    _rect(mb, (-0.42, b0, CABIN_FLOOR), (0.42, STEPS[0][0], CABIN_FLOOR + 0.006), m("grating"))
    pw = PASSAGE[1][0] + 0.1
    for y0, y1, top in STEPS:
        _rect(mb, (-pw, y0, CABIN_FLOOR - t), (pw, y1, top), m("tread"))
    p0, p1 = PASSAGE_Y
    pw = PASSAGE[1][0]
    _rect(mb, (-pw, p0 - 0.02, COCKPIT_FLOOR - t), (pw, p1 + 0.05, COCKPIT_FLOOR), m("tread"))
    ys = (COCKPIT_Y[0], STATIONS[5][0], COCKPIT_Y[1])
    right = [(cavity_at(y, COCKPIT_FLOOR)[1][0], y) for y in ys]
    poly = [*right, *[(-x, y) for x, y in reversed(right)]]
    _plate(mb, poly, COCKPIT_FLOOR - t, COCKPIT_FLOOR, m("floor"))


def _rib(mb, sec, y, depth, inset, material, joints=(1, 2, 3, 4, 5, 6, 7)):
    """Structural frame hugging a cabin section's walls and ceiling (not the floor)."""
    c = _centre(sec)
    c.y = y
    pts = [_toward(Vector((p[0], y, p[2])), c, 0.003) for p in sec]  # off the skin
    inner = [_toward(p, c, inset) for p in pts]
    for j in joints:
        a, b = pts[j], pts[(j + 1) % 8]
        ia, ib = inner[j], inner[(j + 1) % 8]
        if (b - a).length < 0.05:
            continue
        y0, y1 = y - depth / 2, y + depth / 2

        def at(p, yy):
            return Vector((p.x, yy, p.z))

        mid = (ia + ib) / 2
        _face(mb, [at(ia, y0), at(ib, y0), at(ib, y1), at(ia, y1)], c - mid, material)
        _face(mb, [at(a, y0), at(b, y0), at(ib, y0), at(ia, y0)], (0, -1, 0), material)
        _face(mb, [at(a, y1), at(b, y1), at(ib, y1), at(ia, y1)], (0, 1, 0), material)
        _face(mb, [at(a, y0), at(b, y0), at(b, y1), at(a, y1)], (a + b) / 2 - c, material)


def _wall_panels(mb, a, b, j, material, rows=1, cols=1, lift=0.012):
    """Inset panels on facet j between two cabin sections (faces into the cabin)."""
    pa, pb = Vector(a[j]), Vector(a[(j + 1) % 8])
    pd, pc = Vector(b[j]), Vector(b[(j + 1) % 8])
    c = (_centre(a) + _centre(b)) / 2
    for r in range(rows):
        for k in range(cols):
            quad = _cell(pa, pb, pc, pd, r / rows, (r + 1) / rows, k / cols, (k + 1) / cols, 0.06)
            n = (quad[1] - quad[0]).cross(quad[2] - quad[1])
            mid = sum(quad, Vector()) / 4
            c.y = mid.y
            if n.dot(c - mid) < 0:
                quad = quad[::-1]
            _slab(mb, quad, lift, material)


def _lerp_sec(a, b, t):
    return [
        tuple(pa[i] + (pb[i] - pa[i]) * t for i in range(3)) for pa, pb in zip(a, b, strict=True)
    ]


def _corridor_fit(mb, frames):
    """Ramp corridor: frames, wall panels, a door control panel, low red guide lights."""
    c0, c1 = CORRIDOR_Y
    metal = "M_Struct_Gunmetal"
    for k in range(1, 5):
        y = c0 + k * (c1 - c0) / 5
        _rib(frames, _fixed(CORRIDOR, y, CABIN_FLOOR), y, 0.14, 0.07, metal)
    a, b = _fixed(CORRIDOR, c0 + 0.2, CABIN_FLOOR), _fixed(CORRIDOR, c1 - 0.2, CABIN_FLOOR)
    for j in (2, 6):
        _wall_panels(frames, a, b, j, "M_Wall_PaintedMid", rows=1, cols=5)
    # door control panel on the starboard wall, by the door
    x = CORRIDOR[2][0]
    z = CABIN_FLOOR + 1.15
    mb.box((x - 0.06, c0 + 0.5, z), (x - 0.01, c0 + 0.95, z + 0.55), "M_Console_Body")
    mb.box((x - 0.065, c0 + 0.56, z + 0.2), (x - 0.06, c0 + 0.89, z + 0.48), "M_Screen")
    mb.box((x - 0.07, c0 + 0.6, z + 0.06), (x - 0.06, c0 + 0.85, z + 0.15), "M_Console_Keys")
    # fire suppression bottle on the port wall
    xp = -CORRIDOR[2][0] + 0.12
    mb.tube(
        (xp, c1 - 0.6, CABIN_FLOOR + 0.25),
        (xp, c1 - 0.6, CABIN_FLOOR + 0.85),
        0.09,
        "M_Paint_TrimRed",
        14,
    )


def _crew_seat(mb, x_wall, y, sx):
    """Fold-down crew seat against the wall at x_wall (sx: side, +1 starboard)."""
    z0 = CABIN_FLOOR
    metal, pad = "M_Struct_Gunmetal", "M_Seat_Upholstery"
    xw = x_wall - sx * 0.02

    def xs(a, b):
        p, q = xw - sx * a, xw - sx * b
        return min(p, q), max(p, q)

    x0, x1 = xs(0.0, 0.1)
    mb.box((x0, y - 0.28, z0 + 0.2), (x1, y + 0.28, z0 + 1.55), metal)  # back frame
    x0, x1 = xs(0.08, 0.2)
    mb.box((x0, y - 0.24, z0 + 0.52), (x1, y + 0.24, z0 + 1.3), pad)  # back pad
    mb.box((x0, y - 0.16, z0 + 1.36), (x1, y + 0.16, z0 + 1.62), pad)  # head rest
    x0, x1 = xs(0.1, 0.58)
    mb.box((x0, y - 0.25, z0 + 0.44), (x1, y + 0.25, z0 + 0.53), pad)  # seat pan
    x0, x1 = xs(0.1, 0.6)
    mb.box((x0, y - 0.27, z0 + 0.38), (x1, y + 0.27, z0 + 0.44), metal)
    for dy in (-0.25, 0.25):  # legs
        xx = xw - sx * 0.54
        mb.tube((xx, y + dy, z0 + 0.38), (xx, y + dy, z0 + 0.01), 0.025, metal, 8)
    for dy in (-0.11, 0.11):  # harness straps over the pad
        x0, x1 = xs(0.2, 0.215)
        mb.box((x0, y + dy - 0.03, z0 + 0.6), (x1, y + dy + 0.03, z0 + 1.32), "M_Rubber_Black")


def _rifle(mb, x_wall, y, z, sx):
    """Blaster rifle stowed upright in a wall clamp."""
    x = x_wall - sx * 0.12
    dark, metal = "M_Plastic_BlackSatin", "M_Struct_Gunmetal"
    mb.box((x - 0.035, y - 0.05, z), (x + 0.035, y + 0.05, z + 0.32), dark)  # stock
    mb.box((x - 0.045, y - 0.07, z + 0.32), (x + 0.045, y + 0.07, z + 0.68), metal)  # body
    mb.box((x - 0.03, y + 0.06, z + 0.4), (x + 0.03, y + 0.16, z + 0.55), dark)  # magazine
    mb.tube((x, y, z + 0.68), (x, y, z + 1.05), 0.018, metal, 8)  # barrel
    mb.box((x - 0.025, y - 0.035, z + 0.7), (x + 0.025, y + 0.035, z + 0.82), dark)  # sight


def _bay_fit(mb, frames):
    """Troop bay: frames, panels, crew seats, lockers, weapon racks, tactical table."""
    b0, b1 = BAY_Y
    metal = "M_Struct_Gunmetal"
    ys = (b0, -2.4, 2.4, b1)
    secs = [bay_at(y) for y in ys]

    def sec_at(y):
        for (ya, a), (yb, b) in zip(
            zip(ys, secs, strict=True), zip(ys[1:], secs[1:], strict=True), strict=False
        ):
            if ya <= y <= yb:
                return _lerp_sec(a, b, (y - ya) / (yb - ya))
        raise ValueError(y)

    ribs = [b0 + 0.25 + k * 1.2 for k in range(8)]
    for y in ribs:
        _rib(frames, sec_at(y), y, 0.16, 0.09, metal)
    for ya, yb in zip(ribs, ribs[1:], strict=False):
        a, b = sec_at(ya + 0.1), sec_at(yb - 0.1)
        for j in (3, 5):
            _wall_panels(frames, a, b, j, "M_Wall_PaintedMid")
    # conduits along the upper chines
    for j in (3, 6):
        pts = []
        for y in (b0 + 0.1, b1 - 0.1):
            s = sec_at(y)
            c = _centre(s)
            c.y = y
            pts.append(_toward(s[j], c, 0.16))
        mb.tube(pts[0], pts[1], 0.06, "M_Hull_PipeInsulated", 12)
        mb.tube(pts[0] + Vector((0, 0, -0.14)), pts[1] + Vector((0, 0, -0.14)), 0.035, metal, 10)
    # crew seats and overhead lockers along both walls
    seat_ys = [b0 + 0.85 + k * 0.92 for k in range(6)]
    for sx in (-1, 1):
        for y in seat_ys:
            s = sec_at(y)
            _crew_seat(mb, sx * abs(s[2][0]), y, sx)
        ya, yb = seat_ys[0] - 0.4, seat_ys[-1] + 0.4
        s = sec_at((ya + yb) / 2)
        xw = abs(s[3][0])
        z0 = s[3][2] - 0.55
        x0, x1 = sorted((sx * (xw - 0.02), sx * (xw - 0.5)))
        mb.box((x0, ya, z0), (x1, yb, z0 + 0.5), "M_Wall_PaintedDark")
        for k in range(5):
            yy = ya + 0.1 + k * (yb - ya - 0.2) / 5
            xa, xb = sorted((sx * (xw - 0.5), sx * (xw - 0.52)))
            mb.box(
                (xa, yy + 0.04, z0 + 0.04),
                (xb, yy + (yb - ya - 0.2) / 5 - 0.04, z0 + 0.46),
                "M_Wall_PaintedMid",
            )
            mb.box(
                (xa - 0.01 * sx, yy + 0.25, z0 + 0.06), (xb - 0.01 * sx, yy + 0.4, z0 + 0.1), metal
            )
    # weapon racks forward of the seats
    rack_y = (seat_ys[-1] + 0.6, BAY_Y[1] - 1.0)
    for sx in (-1, 1):
        s = sec_at(sum(rack_y) / 2)
        xw = sx * abs(s[2][0])
        x0, x1 = sorted((xw, xw - sx * 0.06))
        mb.box(
            (x0, rack_y[0], CABIN_FLOOR + 0.5),
            (x1, rack_y[1], CABIN_FLOOR + 1.85),
            "M_Wall_Charcoal",
        )
        x0, x1 = sorted((xw - sx * 0.06, xw - sx * 0.2))
        for z in (CABIN_FLOOR + 0.62, CABIN_FLOOR + 1.45):
            mb.box((x0, rack_y[0] + 0.05, z), (x1, rack_y[1] - 0.05, z + 0.05), metal)
        n = 4
        for k in range(n):
            y = rack_y[0] + (k + 0.5) * (rack_y[1] - rack_y[0]) / n
            _rifle(mb, xw, y, CABIN_FLOOR + 0.6, sx)
    # tactical table: pedestal, ring, glass top over a screen, a live hologram above
    ty = TABLE_Y
    with G.xf(mb, G.T(0.0, ty, CABIN_FLOOR)):
        G.lathe(
            mb,
            [(0.0, 0.0), (0.5, 0.0), (0.5, 0.06), (0.26, 0.14), (0.22, 0.78), (0.0, 0.78)],
            "M_Console_Body",
            24,
        )
        G.lathe(
            mb,
            [(0.0, 0.78), (0.6, 0.78), (0.62, 0.86), (0.62, 0.92), (0.0, 0.92)],
            "M_Console_Deck",
            32,
        )
    with G.xf(mb, G.T(0.0, ty, CABIN_FLOOR + 0.925)):
        G.lathe(mb, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.004), (0.0, 0.004)], "M_Screen", 32)
    K.socket(
        "holo",
        "tactical",
        K.socket_matrix((0.0, ty, CABIN_FLOOR + 0.93), (0, 0, 1), up=(0, 1, 0)),
        radius=0.5,
        height=0.8,
    )
    # big screens on the forward bulkhead, either side of the passage
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 1.0, sx * 1.75))
        y = BAY_Y[1] - 0.03
        mb.box(
            (x0 - 0.05, y - 0.04, CABIN_FLOOR + 0.95),
            (x1 + 0.05, y, CABIN_FLOOR + 1.85),
            "M_Console_Body",
        )
        mb.box((x0, y - 0.05, CABIN_FLOOR + 1.0), (x1, y - 0.04, CABIN_FLOOR + 1.8), "M_Screen")
    # passage frame
    pw = PASSAGE[2][0]
    y = BAY_Y[1]
    top = COCKPIT_FLOOR + PASSAGE[4][1]
    for sx in (-1, 1):
        x0, x1 = sorted((sx * pw, sx * (pw + 0.16)))
        mb.box((x0, y - 0.12, CABIN_FLOOR), (x1, y + 0.02, top + 0.12), metal)
    mb.box((-pw - 0.16, y - 0.12, top), (pw + 0.16, y + 0.02, top + 0.14), metal)
    # aft bulkhead: equipment lockers either side of the corridor opening
    y = BAY_Y[0]
    cw = CORRIDOR[2][0]
    for sx in (-1, 1):
        s = sec_at(y + 0.4)
        xo = abs(s[2][0]) - 0.05
        x0, x1 = sorted((sx * (cw + 0.2), sx * xo))
        mb.box((x0, y, CABIN_FLOOR), (x1, y + 0.45, CABIN_FLOOR + 2.0), "M_Wall_PaintedDark")
        for k in range(2):
            xa = min(x0, x1) + 0.05 + k * (abs(x1 - x0) - 0.1) / 2
            xb = xa + (abs(x1 - x0) - 0.1) / 2 - 0.04
            mb.box(
                (xa, y + 0.45, CABIN_FLOOR + 0.08),
                (xb, y + 0.47, CABIN_FLOOR + 1.92),
                "M_Wall_PaintedMid",
            )
            mb.box(
                (xb - 0.08, y + 0.47, CABIN_FLOOR + 0.9),
                (xb - 0.05, y + 0.5, CABIN_FLOOR + 1.2),
                metal,
            )


def _pilot_seat(mb, x, y):
    """Flight seat on a pedestal, with arm consoles."""
    z0 = COCKPIT_FLOOR
    metal, pad = "M_Struct_Gunmetal", "M_Seat_Upholstery"
    mb.box((x - 0.14, y - 0.14, z0), (x + 0.14, y + 0.14, z0 + 0.42), metal)
    mb.box((x - 0.3, y - 0.3, z0 + 0.42), (x + 0.3, y + 0.28, z0 + 0.56), pad)
    mb.box((x - 0.28, y - 0.42, z0 + 0.5), (x + 0.28, y - 0.28, z0 + 1.3), pad)
    mb.box((x - 0.16, y - 0.44, z0 + 1.32), (x + 0.16, y - 0.3, z0 + 1.55), pad)
    mb.box((x - 0.3, y - 0.46, z0 + 0.46), (x + 0.3, y - 0.42, z0 + 1.34), metal)
    for sx in (-1, 1):  # arm consoles
        xa = x + sx * 0.36
        mb.box((xa - 0.07, y - 0.25, z0 + 0.4), (xa + 0.07, y + 0.35, z0 + 0.72), "M_Console_Body")
        mb.box((xa - 0.06, y - 0.1, z0 + 0.72), (xa + 0.06, y + 0.3, z0 + 0.735), "M_Console_Keys")


def _cockpit_fit(mb):
    """Cockpit: two flight seats, centre console, the dash with its screens."""
    k0, k1 = COCKPIT_Y
    end = cavity_at(k1, COCKPIT_FLOOR)
    seat_y = k1 - 1.55
    for sx in (-1, 1):
        _pilot_seat(mb, sx * 0.7, seat_y)
    # centre console between the seats
    mb.box(
        (-0.2, seat_y - 0.4, COCKPIT_FLOOR), (0.2, k1 - 0.6, COCKPIT_FLOOR + 0.7), "M_Console_Body"
    )
    mb.box(
        (-0.17, seat_y - 0.3, COCKPIT_FLOOR + 0.7),
        (0.17, k1 - 0.7, COCKPIT_FLOOR + 0.715),
        "M_Console_Keys",
    )
    # dash: a sloped deck below the glare shield with a screen per seat and a centre stack
    zt = end[3][2]
    xw = abs(end[2][0]) - 0.05
    yb = k1 - 0.6
    zb = COCKPIT_FLOOR + 0.75
    G.wedge_x(
        mb,
        [(yb, COCKPIT_FLOOR), (k1, COCKPIT_FLOOR), (k1, zt - 0.02), (yb, zb)],
        -xw,
        xw,
        "M_Console_Body",
    )
    for x0, x1 in ((-1.05, -0.35), (-0.25, 0.25), (0.35, 1.05)):
        t0, t1 = 0.15, 0.85
        p = [
            (x0, yb + (k1 - yb) * t0, zb + (zt - 0.02 - zb) * t0),
            (x1, yb + (k1 - yb) * t0, zb + (zt - 0.02 - zb) * t0),
            (x1, yb + (k1 - yb) * t1, zb + (zt - 0.02 - zb) * t1),
            (x0, yb + (k1 - yb) * t1, zb + (zt - 0.02 - zb) * t1),
        ]
        n = Vector((0.0, -(zt - 0.02 - zb), k1 - yb)).normalized() * 0.012
        _face(mb, [Vector(q) + n for q in p], n, "M_Screen")


def _cabin_and_lamps(mb):
    """Emitters: cabin ceiling strips, floor guide lights, step nosings, nav lights."""
    c0, c1 = CORRIDOR_Y
    zc = CABIN_FLOOR + CORRIDOR[4][1] - 0.012
    mb.box((-0.22, c0 + 0.25, zc - 0.01), (0.22, c1 - 0.25, zc), "M_Light_CeilingPanel")
    cw = CORRIDOR[1][0] - 0.04
    for sx in (-1, 1):  # low red guide lights along the corridor
        x0, x1 = sorted((sx * cw, sx * (cw - 0.03)))
        mb.box(
            (x0, c0 + 0.1, CABIN_FLOOR + 0.14),
            (x1, c1 - 0.1, CABIN_FLOOR + 0.17),
            "M_Light_RedTrim",
        )
    b0, b1 = BAY_Y
    for y0, y1 in zip(
        [b0 + 0.25 + k * 1.2 for k in range(7)],
        [b0 + 0.25 + k * 1.2 for k in range(1, 8)],
        strict=True,
    ):
        for x in (-0.55, 0.55):
            ya, yb = y0 + 0.14, y1 - 0.14
            z = min(bay_at(ya)[4][2], bay_at(yb)[4][2]) - 0.015
            mb.box((x - 0.14, ya, z - 0.01), (x + 0.14, yb, z), "M_Light_CeilingPanel")
    seat_ys = [b0 + 0.85 + k * 0.92 for k in range(6)]
    ya, yb = seat_ys[0] - 0.35, seat_ys[-1] + 0.35
    s = bay_at((ya + yb) / 2)
    xw, z0 = abs(s[3][0]), s[3][2] - 0.55
    for sx in (-1, 1):  # warm strips under the overhead lockers, a blue lamp per seat
        x0, x1 = sorted((sx * (xw - 0.42), sx * (xw - 0.47)))
        mb.box((x0, ya, z0 - 0.012), (x1, yb, z0), "M_Light_Maint_Amber")
        for y in seat_ys:
            x0, x1 = sorted((sx * (xw - 0.49), sx * (xw - 0.505)))
            mb.box((x0, y - 0.05, z0 + 0.2), (x1, y + 0.05, z0 + 0.26), "M_Indicator_Blue")
    for x in (-0.44, 0.44):  # floor inlays along the grating aisle
        mb.box(
            (x - 0.015, b0 + 0.1, CABIN_FLOOR),
            (x + 0.015, STEPS[0][0] - 0.1, CABIN_FLOOR + 0.008),
            "M_Light_FloorInlay",
        )
    pw = PASSAGE[1][0] + 0.1
    for y0, _y1, top in STEPS:  # step nosings
        mb.box((-pw, y0, top - 0.03), (pw, y0 + 0.02, top), "M_Light_Maint_Amber")
    # amber lamp over the aft door, inside and out
    top = CABIN_FLOOR + CORRIDOR[4][1]
    mb.box((-0.5, c0 - 0.17, top - 0.02), (0.5, c0 - 0.16, top + 0.06), m("lamp_amber"))
    mb.box((-0.3, c0 + 0.05, top - 0.12), (0.3, c0 + 0.09, top - 0.06), "M_Light_Maint_Amber")
    for sx in (-1, 1):  # nav lights on the nacelle tops
        mb.box(
            (sx * 1.95 - 0.06, -10.0, 3.75),
            (sx * 1.95 + 0.06, -9.8, 3.8),
            m("lamp_red" if sx < 0 else "lamp_green"),
        )
    mb.box((-0.08, -8.9, 5.42), (0.08, -8.7, 5.47), m("lamp_white"))


def _markings(mb, secs):
    stencil = m("stencil_dark")
    G.text(mb, "07", 1.1, stencil, G.T(-1.1, -3.4, 5.13) @ G.Rz(0.0))
    for sx in (-1, 1):  # exhaust soot creeping forward over the nacelle tops
        cx = sx * 1.95
        mb.quad(
            [
                (cx - 0.75, -10.3, 3.753),
                (cx + 0.75, -10.3, 3.753),
                (cx + 0.6, -8.4, 3.753),
                (cx - 0.6, -8.4, 3.753),
            ],
            stencil,
        )
    G.text(mb, "FLT-2207", 0.32, stencil, G.T(1.2, 3.0, 5.0) @ G.Rz(90.0))
    for sx in (-1, 1):
        G.text(mb, "NO STEP", 0.18, stencil, G.T(sx * 1.2, -7.1, 5.0))
        mb.quad(
            [
                (sx * 2.0 - 0.05, -9.95, 2.0),
                (sx * 2.0 + 0.05, -9.95, 2.0),
                (sx * 2.0 + 0.05, -9.95, 3.4),
                (sx * 2.0 - 0.05, -9.95, 3.4),
            ],
            stencil,
        )


def _area_light(name, location, size, energy, color, rot=(0.0, 0.0, 0.0)):
    data = bpy.data.lights.new(name, "AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = size
    data.energy = energy
    data.color = color
    ob = bpy.data.objects.new(data.name, data)
    ob.location = location
    ob.rotation_euler = rot
    ob.visible_camera = False
    K.link(ob)
    return ob


def _cabin_lights():
    """Light inside the cabin (part of the piece); the corridor's spills down the ramp."""
    cool, warm = (0.86, 0.93, 1.0), (1.0, 0.86, 0.7)
    c0, c1 = CORRIDOR_Y
    zc = CABIN_FLOOR + CORRIDOR[4][1] - 0.05
    _area_light("SM_Hangar_Shuttle_cabin_light", (0.0, (c0 + c1) / 2, zc), (0.5, 3.6), 80.0, warm)
    b0, b1 = BAY_Y
    for k, y in enumerate((b0 + 1.6, (b0 + b1) / 2, b1 - 1.6)):
        z = bay_at(y)[4][2] - 0.06
        _area_light(f"SM_Hangar_Shuttle_bay_light_{k}", (0.0, y, z), (1.4, 2.2), 70.0, cool)
    k0, k1 = COCKPIT_Y
    _area_light(
        "SM_Hangar_Shuttle_cockpit_light", (0.0, (k0 + k1) / 2 - 0.3, 4.0), (1.6, 1.4), 160.0, cool
    )


def _occluders(secs):
    """Coarse hull and wing proxies for the runtime depth pass."""
    verts = [Vector(p) for sec in secs for p in sec]
    faces = []
    n = 8
    for s in range(len(secs) - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((s * n + j, s * n + j2, (s + 1) * n + j2, (s + 1) * n + j))
    faces += [tuple(reversed(range(n))), tuple(range((len(secs) - 1) * n, len(secs) * n))]
    proxy = K.mesh_object("_tmp_ucx", verts, faces, m("dark_steel"))
    K.occluder(proxy, nav="block")
    bpy.data.objects.remove(proxy, do_unlink=True)
    z_h = 3.5
    reach = WING_SPAN * math.cos(math.radians(WING_FOLD_DEG)) + 0.3
    drop = WING_SPAN * math.sin(math.radians(WING_FOLD_DEG))
    for sx in (-1, 1):
        x0, x1 = sorted((sx * WING_HINGE_X, sx * (WING_HINGE_X + reach)))
        K.occluder(
            ((x0, WING_TIP[1], z_h + min(drop, 0.0) - 0.2), (x1, WING_ROOT[0], z_h + 0.2)),
            nav="block",
        )
    K.occluder(((-2.9, -10.5, 1.75), (2.9, -5.2, 3.75)), nav="block")


K.register_variant("SM_Hangar_Shuttle", build_shuttle, dims=(17.0, 24.7, 7.0), nav="block")

LOOKDEV = {
    "SM_Hangar_Shuttle": {"focus": (0.0, -9.6, 3.0), "crop_size": (4.0, 2.6), "max_px": 2400},
}
