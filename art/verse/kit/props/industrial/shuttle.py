"""The arrival shuttle of the main hangar (deck 4): an original ~20 m design.

A faceted wedge-nosed transport parked on three landing legs with its two
gull wings folded up, two aft engine nacelles and a lit rear ramp lowered to
the deck. New agents walk down the ramp: ``SOCKET_spawn_arrival`` sits at its
foot.

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


RAMP_WIDTH = 1.76
RAMP_HINGE = (-9.6, 1.5)  # (y, z)
RAMP_LENGTH = 4.4
WING_FOLD_DEG = 56.0


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


def _slab(mb, quad, lift, material):
    """Raised plate on a quad: top face lifted along its normal, with sides."""
    q = [Vector(p) for p in quad]
    n = (q[1] - q[0]).cross(q[2] - q[1]).normalized()
    top = [p + n * lift for p in q]
    mb._add(
        [*q, *top], [(4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], material
    )


def _cell(a, b, c, d, u0, u1, v0, v1, inset):
    """Bilinear sub-quad of quad (a, b, c, d) with an absolute inset in metres."""

    def lerp(u, v):
        return (a * (1 - u) + b * u) * (1 - v) + (d * (1 - u) + c * u) * v

    p = [lerp(u0, v0), lerp(u1, v0), lerp(u1, v1), lerp(u0, v1)]
    centre = sum(p, Vector()) / 4
    return [q + (centre - q).normalized() * min(inset, (centre - q).length * 0.4) for q in p]


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


def build_shuttle() -> None:
    """Original faceted shuttle, wings folded, ramp down, lit cabin."""
    rnd = G.rng("shuttle")
    secs = _sections()
    hull = m("hull_paint")

    body = K.MeshBuilder()
    G.loft(body, secs, hull, closed_ends=False)
    body._add([Vector(p) for p in secs[-1]], [tuple(range(8))], hull)  # nose cap
    _rear_bulkhead(body, secs[0])
    _plate_hull(body, secs, rnd)
    _spine(body)
    _sponsons(body, rnd)
    _nacelles(body)
    _hinges_and_wings(body)
    body.build("SM_Hangar_Shuttle_hull", bevel_width=0.02, angle_deg=25.0)

    gear = K.MeshBuilder()
    for x, y, z in ((0.0, 7.0, STATIONS[4][2]), (-2.0, -5.0, 1.33), (2.0, -5.0, 1.33)):
        _leg(gear, x, y, z)
    gear.build("SM_Hangar_Shuttle_gear", bevel_width=0.01, nav="block")
    ramp = K.MeshBuilder()
    _ramp(ramp)
    ramp.build("SM_Hangar_Shuttle_ramp", bevel_width=0.01, nav="walk")  # crew walk down it
    intake = K.MeshBuilder()  # fuel intake on the starboard sponson (hoses end here)
    intake.box((3.05, -5.9, 1.55), (3.1, -5.1, 2.05), m("dark_steel"))
    intake.tube((3.1, -5.5, 1.8), (3.28, -5.5, 1.8), 0.11, m("gunmetal"), 14)
    intake.box((3.06, -5.95, 2.1), (3.1, -5.05, 2.16), m("hazard"))
    # dorsal service hatch with grab handle (port side of the spine)
    intake.box((-1.35, 0.4, 5.1), (-0.75, 1.5, 5.15), m("dark_steel"))
    intake.box((-1.2, 0.6, 5.15), (-0.9, 0.66, 5.19), m("gunmetal"))
    intake.build("SM_Hangar_Shuttle_intake", bevel_width=0.006, nav="block")

    glass = K.MeshBuilder()
    _cockpit(glass, secs)
    glass.build("SM_Hangar_Shuttle_glass", bevel_width=0.0, nav="none")

    lamps = K.MeshBuilder()
    _cabin_and_lamps(lamps)
    lamps.build("SM_Hangar_Shuttle_lamps", bevel_width=0.0, nav="none")

    marks = K.MeshBuilder()
    _markings(marks, secs)
    marks.build("SM_Hangar_Shuttle_marks", bevel_width=0.0, nav="none")

    _cabin_light()
    hy, hz = RAMP_HINGE
    foot = hy - RAMP_LENGTH * math.cos(math.asin(hz / RAMP_LENGTH))
    K.socket("spawn", "arrival", K.socket_matrix((0.0, foot - 0.8, 0.0), (0, 0, 1), up=(0, 1, 0)))
    K.socket("waypoint", "ramp_top", K.socket_matrix((0.0, hy + 1.0, hz), (0, 0, 1), up=(0, 1, 0)))
    K.socket("light", "cabin", K.socket_matrix((0.0, hy + 2.0, 3.2), (0, -1, 0)))
    _occluders(secs)


def _rear_bulkhead(mb, sec):
    """Aft face with the door opening (x +-ramp/2, from the belly to 3.5 m)."""
    hw = RAMP_WIDTH / 2
    y = sec[0][1]
    top = 3.5
    pts = [sec[0], (-hw, y, sec[0][2]), (-hw, y, top), (hw, y, top), (hw, y, sec[0][2]), *sec[1:]]
    mb._add([Vector(p) for p in pts], [tuple(reversed(range(len(pts))))], m("hull_paint"))
    # heavy door frame and a cabin box (open toward -Y)
    steel = m("dark_steel")
    z0 = sec[0][2]
    mb.box((-hw - 0.22, y - 0.12, z0), (-hw, y + 0.02, top + 0.22), steel)
    mb.box((hw, y - 0.12, z0), (hw + 0.22, y + 0.02, top + 0.22), steel)
    mb.box((-hw - 0.22, y - 0.12, top), (hw + 0.22, y + 0.02, top + 0.22), steel)
    cab = m("panel_light")
    depth = 4.2
    mb.box((-hw - 0.05, y, z0 - 0.08), (hw + 0.05, y + depth, z0), m("panel_dark"))
    mb.box((-hw - 0.08, y, z0), (-hw, y + depth, top), cab)
    mb.box((hw, y, z0), (hw + 0.08, y + depth, top), cab)
    mb.box((-hw, y + depth, z0), (hw, y + depth + 0.08, top), cab)
    mb.box((-hw - 0.05, y, top), (hw + 0.05, y + depth, top + 0.08), cab)
    for i in range(4):  # cabin seats along both walls
        yy = y + 0.7 + i * 0.85
        for sx in (-1, 1):
            x0 = sx * (hw - 0.05)
            mb.box(
                (min(x0, x0 - sx * 0.45), yy - 0.25, z0 + 0.42),
                (max(x0, x0 - sx * 0.45), yy + 0.25, z0 + 0.5),
                m("panel_dark"),
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
    mb.tube((0.25, -6.2, roof + 0.3), (0.25, -6.2, roof + 1.4), 0.025, metal, 8)
    mb.tube((-0.25, -6.6, roof + 0.3), (-0.25, -6.6, roof + 1.0), 0.02, metal, 8)


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


def _hinges_and_wings(mb):
    """Gull wings hinged at the upper chines, folded up and outward."""
    hull, steel, metal = m("hull_paint"), m("dark_steel"), m("gunmetal")
    z_hinge = STATIONS[2][2] + 0.58 * (STATIONS[2][3] - STATIONS[2][2])
    for sx in (-1, 1):
        x_h = sx * 2.62
        mb.tube((x_h, -6.4, z_hinge), (x_h, 1.8, z_hinge), 0.3, metal, 16)
        for yy in (-5.6, -2.2, 1.0):
            G.chamfer_box(
                mb,
                (x_h - 0.35, yy - 0.4, z_hinge - 0.55),
                (x_h + 0.35, yy + 0.4, z_hinge + 0.3),
                0.12,
                steel,
            )
        frame = G.T(x_h, 0.0, z_hinge) @ G.Ry(-sx * WING_FOLD_DEG)
        if sx < 0:
            frame = frame @ G.S(-1.0, 1.0, 1.0)
        with G.xf(mb, frame):
            _wing_mesh(mb, (1.6, -6.2), (-0.8, -4.6), 5.4, 0.42, 0.18, hull)
            mb.box((5.3, -4.7, -0.14), (5.55, -0.7, 0.14), steel)  # tip rail


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
    frame = G.T(0.0, hy, hz) @ G.Rx(-math.degrees(ang))
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


def _cockpit(mb, secs):
    """Canopy panes on the nose's upper facets with mullions between them."""
    glass = m("glass_dark")
    for s, j in sorted(COCKPIT_FACETS):
        a, b = Vector(secs[s][j]), Vector(secs[s][(j + 1) % 8])
        d, c = Vector(secs[s + 1][j]), Vector(secs[s + 1][(j + 1) % 8])
        quad = _cell(a, b, c, d, 0.0, 1.0, 0.0, 1.0, 0.07)[::-1]  # outward winding
        n = (quad[1] - quad[0]).cross(quad[2] - quad[1]).normalized()
        mb.quad([p + n * 0.01 for p in quad], glass)


def _cabin_and_lamps(mb):
    hw = RAMP_WIDTH / 2
    hy, hz = RAMP_HINGE
    mb.box((-hw + 0.2, hy + 0.3, 3.38), (hw - 0.2, hy + 4.0, 3.42), m("cabin_glow"))
    for sx in (-1, 1):  # nav lights at the wing tips and nacelle tops
        mb.box(
            (sx * 1.95 - 0.06, -10.0, 3.75),
            (sx * 1.95 + 0.06, -9.8, 3.8),
            m("lamp_red" if sx < 0 else "lamp_green"),
        )
    mb.box((-0.08, -8.6, 5.42), (0.08, -8.4, 5.47), m("lamp_white"))
    mb.box((-hw - 0.2, hy - 0.13, 3.6), (hw + 0.2, hy - 0.12, 3.66), m("lamp_amber"))


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
        G.text(mb, "NO STEP", 0.18, stencil, G.T(sx * 1.2, -6.1, 5.12))
        mb.quad(
            [
                (sx * 2.0 - 0.05, -9.95, 2.0),
                (sx * 2.0 + 0.05, -9.95, 2.0),
                (sx * 2.0 + 0.05, -9.95, 3.4),
                (sx * 2.0 - 0.05, -9.95, 3.4),
            ],
            stencil,
        )


def _cabin_light():
    """Warm light inside the cabin spilling down the ramp (part of the piece)."""
    data = bpy.data.lights.new("SM_Hangar_Shuttle_cabin_light", "AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = 1.4, 3.2
    data.energy = 220.0
    data.color = (1.0, 0.86, 0.7)
    ob = bpy.data.objects.new(data.name, data)
    hy, _ = RAMP_HINGE
    ob.location = (0.0, hy + 2.0, 3.3)
    ob.visible_camera = False
    K.link(ob)


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
    z_h = 3.6
    c, s = math.cos(math.radians(WING_FOLD_DEG)), math.sin(math.radians(WING_FOLD_DEG))
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 2.62, sx * (2.62 + 5.4 * c)))
        K.occluder(((x0, -6.2, z_h - 0.3), (x1, 1.6, z_h + 5.4 * s)), nav="block")
    K.occluder(((-2.9, -10.5, 1.75), (2.9, -5.2, 3.75)), nav="block")


K.register_variant("SM_Hangar_Shuttle", build_shuttle, dims=(11.0, 24.7, 9.2), nav="block")

LOOKDEV = {
    "SM_Hangar_Shuttle": {"focus": (0.0, -9.6, 3.0), "crop_size": (4.0, 2.6), "max_px": 2400},
}
