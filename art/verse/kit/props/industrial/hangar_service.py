"""Hangar service pieces (deck 4): landing pad, recessed floor light, portal
gantry crane on floor rails, fuel hydrant, fuel cart, tool cart, and a hose
helper that routes a floor hose along any polyline.

Piece-local frame: centred on X, deck at Z = 0, -Y toward the camera.
"""

from __future__ import annotations

import math

from lib import kit as K
from mathutils import Vector

from . import _geo as G
from ._mats import m

# --------------------------------------------------------------------------
# Landing pad and floor light
# --------------------------------------------------------------------------


def build_landing_pad(radius=7.0, lights=12):
    """Plated round landing pad with concentric seams and recessed edge lights.

    Concentric plate rings only (no radial seams), so from above it never reads
    as a spoked emblem.
    """
    mb, lamps = K.MeshBuilder(), K.MeshBuilder()
    rings = ((0.0, 2.39), (2.41, 4.79), (4.81, radius - 0.42))
    for r0, r1 in rings:
        if r0 == 0.0:
            G.lathe(
                mb,
                [(0.0, 0.02), (r1, 0.02), (r1, -0.05), (0.0, -0.05)],
                m("floor"),
                96,
                closed=True,
            )
        else:
            G.ring(mb, r0, r1, -0.05, 0.02, m("floor"), 96)  # deck plate, own seams
    G.lathe(
        mb,
        [
            (radius - 0.4, -0.05),
            (radius, -0.05),
            (radius, 0.0),
            (radius - 0.06, 0.035),
            (radius - 0.4, 0.035),
        ],
        m("tread"),
        128,
        closed=True,
    )
    for i in range(lights):
        with G.xf(lamps, G.Rz(360.0 * (i + 0.5) / lights)):
            lamps.box((radius - 0.3, -0.12, 0.036), (radius - 0.16, 0.12, 0.04), m("lamp_band"))
    mb.build("SM_landingpad_body", bevel_width=0.006, nav="walk")
    lamps.build("SM_landingpad_lamps", bevel_width=0.0, nav="none")


def build_floor_light(radius=0.3):
    """Round recessed floor light: steel bezel and a frosted up-light lens."""
    mb, lamps = K.MeshBuilder(), K.MeshBuilder()
    G.lathe(
        mb,
        [
            (radius - 0.06, -0.04),
            (radius, -0.04),
            (radius, 0.0),
            (radius - 0.02, 0.004),
            (radius - 0.06, 0.004),
        ],
        m("dark_steel"),
        32,
        closed=True,
    )
    G.annulus(lamps, 0.0, radius - 0.06, 0.001, m("lamp_white"), 32)
    mb.build("SM_floorlight_bezel", bevel_width=0.0, nav="none")
    lamps.build("SM_floorlight_lens", bevel_width=0.0, nav="none")


K.register_variant("SM_Hangar_LandingPad", build_landing_pad, dims=(14.0, 14.0, 0.04), nav="walk")
K.register_variant("SM_Hangar_FloorLight", build_floor_light, dims=(0.6, 0.6, 0.004), nav="none")


# --------------------------------------------------------------------------
# Portal gantry crane on floor rails
# --------------------------------------------------------------------------


def build_gantry_rail(length=12.0):
    """Flush crane rail channel along local Y (cut into the deck)."""
    mb = K.MeshBuilder()
    hl = length / 2
    mb.box((-0.18, -hl, -0.05), (0.18, hl, 0.003), m("dark_steel"))
    mb.box((-0.04, -hl, 0.003), (0.04, hl, 0.06), m("gunmetal"))
    for i in range(int(length / 1.2)):
        y = -hl + 0.6 + i * 1.2
        for sx in (-0.13, 0.13):
            G.tube_z(mb, 0.02, 0.003, 0.012, m("gunmetal"), 8, x=sx, y=y)
    mb.build("SM_gantryrail_body", bevel_width=0.003, nav="none")


def _gantry_leg(mb, x, height, depth):
    """A-frame leg standing on a bogie that rides the rail at local x."""
    metal, steel = m("gunmetal"), m("dark_steel")
    hd = depth / 2
    G.chamfer_box(
        mb, (x - 0.45, -hd - 0.6, 0.06), (x + 0.45, hd + 0.6, 0.85), 0.12, m("container_grey")
    )
    for sy in (-1, 1):
        for k in (-1, 1):  # wheels
            mb.tube(
                (x - 0.42, sy * hd + k * 0.35, 0.3),
                (x + 0.42, sy * hd + k * 0.35, 0.3),
                0.26,
                steel,
                18,
            )
        G.beam(mb, (x, sy * (hd - 0.1), 0.85), (x, sy * 0.35, height - 1.0), 0.45, 0.45, metal)
    mb.box((x - 0.4, -0.9, height - 1.3), (x + 0.4, 0.9, height - 0.9), metal)
    mb.box((x - 0.46, -hd - 0.6, 0.6), (x + 0.46, -hd - 0.55, 0.85), m("hazard"))
    mb.box((x - 0.46, hd + 0.55, 0.6), (x + 0.46, hd + 0.6, 0.85), m("hazard"))


def build_portal_gantry(span=16.0, height=10.0, depth=2.4, hook_drop=5.0):
    """Portal gantry crane: two A-frame legs on rail bogies, twin box girders,
    a hoist trolley with a hook block and a small operator cab."""
    legs, bridge, lamps = K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    hs = span / 2
    for sx in (-1, 1):
        _gantry_leg(legs, sx * hs, height, depth)
    for sy in (-0.55, 0.55):
        G.chamfer_box(
            bridge,
            (-hs - 0.6, sy - 0.3, height - 0.9),
            (hs + 0.6, sy + 0.3, height + 0.2),
            0.08,
            metal,
        )
    for i in range(int(span / 1.2) + 1):
        x = -hs + i * 1.2
        bridge.box((x - 0.05, -0.85, height - 0.85), (x + 0.05, 0.85, height - 0.75), steel)
    G.chamfer_box(
        bridge, (-0.9, -1.0, height + 0.2), (0.9, 1.0, height + 1.0), 0.15, m("container_grey")
    )
    for sx in (-0.18, 0.18):
        bridge.tube((sx, 0.0, height - 0.9), (sx, 0.0, height - hook_drop), 0.02, metal, 6)
    G.chamfer_box(
        bridge,
        (-0.38, -0.28, height - hook_drop - 0.7),
        (0.38, 0.28, height - hook_drop),
        0.1,
        m("hazard"),
    )
    bridge.tube(
        (0.0, 0.0, height - hook_drop - 0.7), (0.0, 0.0, height - hook_drop - 1.0), 0.06, metal, 10
    )
    G.chamfer_box(
        bridge,
        (hs - 1.6, -1.6, height - 2.9),
        (hs - 0.5, -0.6, height - 1.3),
        0.1,
        m("container_grey"),
    )
    bridge.box((hs - 1.55, -1.62, height - 2.3), (hs - 0.55, -1.6, height - 1.5), m("glass_dark"))
    for sx in (-1, 1):
        lamps.box(
            (sx * hs - 0.1, -0.86, height - 0.6),
            (sx * hs + 0.1, -0.85, height - 0.45),
            m("lamp_red"),
        )
    lamps.box((-0.6, -1.01, height + 0.5), (0.6, -1.0, height + 0.56), m("lamp_amber"))
    legs.build("SM_portalgantry_legs", bevel_width=0.008, nav="block")
    bridge.build("SM_portalgantry_bridge", bevel_width=0.008, nav="none")  # overhead
    lamps.build("SM_portalgantry_lamps", bevel_width=0.0, nav="none")
    for sx in (-1, 1):
        K.occluder(
            ((sx * hs - 0.6, -depth / 2 - 0.7, 0.0), (sx * hs + 0.6, depth / 2 + 0.7, height)),
            nav="block",
        )
    K.occluder(((-hs - 0.6, -0.9, height - 0.9), (hs + 0.6, 0.9, height + 1.0)), nav="none")


K.register_variant("SM_Hangar_GantryRail", build_gantry_rail, dims=(0.36, 12.0, 0.06), nav="none")
K.register_variant("SM_Hangar_PortalGantry", build_portal_gantry, dims=(17.2, 3.6, 11.0))


# --------------------------------------------------------------------------
# Fuel hydrant, fuel cart, tool cart
# --------------------------------------------------------------------------


def build_fuel_hydrant():
    """Floor fuel manifold: riser with three outlet valves, meter box, guard posts."""
    mb, lamps = K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    mb.box((-0.6, -0.6, -0.02), (0.6, 0.6, 0.02), steel)
    G.tube_z(mb, 0.14, 0.02, 0.75, m("container_grey"), 20)
    with G.xf(mb, G.T(0.0, 0.0, 0.75)):
        G.lathe(mb, [(0.0, 0.12), (0.18, 0.1), (0.2, 0.0), (0.14, -0.05)], metal, 20)
    for i, a in enumerate((-90.0, 30.0, 150.0)):  # three outlets with valve wheels
        d = Vector(G.polar(1.0, a))
        mb.tube(Vector((0, 0, 0.45)) + d * 0.1, Vector((0, 0, 0.45)) + d * 0.42, 0.06, metal, 12)
        with G.xf(mb, G.T(*(Vector((0, 0, 0.45)) + d * 0.42)) @ G.Rz(a) @ G.Ry(90.0)):
            G.ring(mb, 0.1, 0.13, -0.02, 0.02, m("stencil_red" if i == 0 else "stencil_amber"), 20)
    G.chamfer_box(mb, (0.22, 0.15, 0.3), (0.5, 0.42, 0.75), 0.03, m("panel_dark"))
    lamps.box((0.3, 0.145, 0.6), (0.42, 0.15, 0.68), m("screen_dim"))
    for sx in (-1, 1):
        for sy in (-1, 1):
            G.tube_z(mb, 0.05, 0.02, 0.9, m("hazard"), 12, x=sx * 0.52, y=sy * 0.52)
    mb.build("SM_hydrant_body", bevel_width=0.005)
    lamps.build("SM_hydrant_lamps", bevel_width=0.0, nav="none")
    K.occluder(((-0.6, -0.6, 0.0), (0.6, 0.6, 0.95)), nav="block")


def _wheels(mb, xs, ys, r, z=None):
    for x in xs:
        for y in ys:
            s = 1 if y > 0 else -1
            mb.tube((x, y, z or r), (x, y + s * 0.08, z or r), r, m("rubber"), 16)


def build_fuel_cart():
    """Towable fuel bowser: horizontal tank on a chassis, hose reel, tow bar."""
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    G.chamfer_box(mb, (-1.0, -0.5, 0.25), (1.0, 0.5, 0.4), 0.06, steel)
    mb.tube((-0.85, 0.0, 0.8), (0.65, 0.0, 0.8), 0.42, m("container_grey"), 24)
    for x in (-0.85, 0.65):
        with G.xf(mb, G.T(x, 0.0, 0.8) @ G.Ry(90.0 if x > 0 else -90.0)):
            G.lathe(
                mb, [(0.42, 0.0), (0.36, 0.1), (0.2, 0.15), (0.0, 0.16)], m("container_grey"), 24
            )
    for x in (-0.5, 0.0, 0.4):
        mb.tube((x - 0.03, 0.0, 0.8), (x + 0.03, 0.0, 0.8), 0.44, metal, 24)
    with G.xf(mb, G.T(0.9, 0.0, 0.62) @ G.Rx(90.0)):
        G.ring(mb, 0.1, 0.24, -0.2, 0.2, m("rubber"), 24)
        G.ring(mb, 0.24, 0.26, -0.22, 0.22, metal, 24)
    mb.box((-1.6, -0.05, 0.28), (-1.0, 0.05, 0.36), steel)
    mb.tube((-1.6, 0.0, 0.2), (-1.6, 0.0, 0.4), 0.05, metal, 10)
    _wheels(mb, (-0.65, 0.65), (-0.5, 0.5), 0.2)
    mb.build("SM_fuelcart_body", bevel_width=0.006)
    st = K.MeshBuilder()
    G.text(st, "FUEL", 0.14, m("stencil_dark"), G.on_face((-0.1, -0.425, 0.8), "-Y"))
    st.build("SM_fuelcart_stencil", bevel_width=0.0, nav="none")
    K.occluder(((-1.65, -0.6, 0.0), (1.2, 0.6, 1.25)), nav="block")


def build_tool_cart():
    """Wheeled tool cart: drawer chest, top tray with tools, push handle."""
    rnd = G.rng("toolcart")
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    G.chamfer_box(mb, (-0.55, -0.3, 0.15), (0.55, 0.3, 0.9), 0.03, m("stencil_red"))
    for k in range(5):  # drawer fronts
        z = 0.2 + k * 0.14
        mb.box((-0.5, -0.31, z), (0.5, -0.3, z + 0.12), m("stencil_red"))
        mb.box((-0.2, -0.33, z + 0.07), (0.2, -0.31, z + 0.09), metal)
    mb.box((-0.58, -0.33, 0.9), (0.58, 0.33, 0.95), steel)
    for i in range(6):
        x = -0.45 + i * 0.17
        mb.box(
            (x, -0.2, 0.95), (x + 0.03 + rnd.random() * 0.05, 0.2 - rnd.random() * 0.1, 0.98), metal
        )
    mb.tube((0.6, -0.25, 0.95), (0.6, 0.25, 0.95), 0.02, metal, 8)
    _wheels(mb, (-0.45, 0.45), (-0.25, 0.25), 0.07)
    mb.build("SM_toolcart_body", bevel_width=0.004)
    K.occluder(((-0.6, -0.35, 0.0), (0.62, 0.35, 1.0)), nav="block")


# --------------------------------------------------------------------------
# Fuel bowser: the crew bay's self-driving refuelling truck
# --------------------------------------------------------------------------

# Octagonal tank section (y, z): 2.1 m wide, 1.0..2.75 m high, 0.34 m chamfers.
_TANK_Y, _TANK_Z0, _TANK_Z1, _TANK_C = 1.05, 1.0, 2.75, 0.34


def _octagon(scale=1.0, grow=0.0):
    """Tank cross-section around its axis, scaled and grown outward by ``grow``."""
    zc = (_TANK_Z0 + _TANK_Z1) / 2
    hy = _TANK_Y * scale + grow
    hz = (_TANK_Z1 - _TANK_Z0) / 2 * scale + grow
    c = _TANK_C * scale + grow * 0.41
    return [
        (-hy + c, zc - hz),
        (hy - c, zc - hz),
        (hy, zc - hz + c),
        (hy, zc + hz - c),
        (hy - c, zc + hz),
        (-hy + c, zc + hz),
        (-hy, zc + hz - c),
        (-hy, zc - hz + c),
    ]


def _bowser_wheel(mb, x, side):
    """Tyre, hub and hub cap on the ``side`` (-1 camera side, +1 far side)."""
    r, zc = 0.44, 0.44
    mb.tube((x, side * 0.84, zc), (x, side * 1.14, zc), r, m("rubber"), 28)
    mb.tube((x, side * 1.14, zc), (x, side * 1.155, zc), 0.27, m("gunmetal"), 24)
    mb.tube((x, side * 1.155, zc), (x, side * 1.175, zc), 0.11, m("dark_steel"), 16)
    for k in range(6):  # wheel nuts
        a = math.radians(60.0 * k)
        px, pz = x + math.cos(a) * 0.18, zc + math.sin(a) * 0.18
        mb.tube((px, side * 1.155, pz), (px, side * 1.17, pz), 0.022, m("dark_steel"), 8)


def _bowser_arch(mb, x0, x1, r=0.6):
    """Armoured fender over the wheels from ``x0`` to ``x1`` (one axle when
    equal, a tandem otherwise), both sides: two quarter arcs and a flat top."""
    white = m("hull_paint")
    for side in (-1, 1):
        y0, y1 = sorted((side * 0.82, side * 1.24))
        for x, a0, a1 in ((x0, 90.0, 180.0), (x1, 0.0, 90.0)):
            with G.xf(mb, G.T(x, y1, 0.44) @ G.Rx(90.0)):
                G.ring(mb, r, r + 0.08, 0.0, y1 - y0, white, 16, a0, a1)
        if x1 > x0:
            mb.box((x0, y0, 0.44 + r), (x1, y1, 0.52 + r), white)
        mb.box((x0 - r - 0.08, y0, 0.36), (x0 - r, y1, 0.44), white)
        mb.box((x1 + r, y0, 0.36), (x1 + r + 0.08, y1, 0.44), white)


def build_fuel_bowser():
    """Self-driving fuel bowser of the ground crew: a wedge cab with a dark
    canopy, an armoured octagonal tank in white plates and gunmetal bands,
    a railed walkway on top, a rear hose reel and valve manifold, six wheels
    under armoured arches.

    Long axis on X with the cab at +X; 7.3 x 2.5 x 3.2 m.
    """
    body, frame, lamps, decal = K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder()
    white, metal, steel = m("hull_paint"), m("gunmetal"), m("dark_steel")
    dark, glass = m("panel_dark"), m("glass_dark")

    # Chassis spine, bumpers and the running gear.
    G.chamfer_box(frame, (-3.55, -0.95, 0.3), (3.5, 0.95, 0.66), 0.12, steel)
    G.chamfer_box(frame, (3.45, -1.15, 0.36), (3.66, 1.15, 0.72), 0.08, metal)  # front bumper
    G.chamfer_box(frame, (-3.7, -1.15, 0.36), (-3.5, 1.15, 0.7), 0.08, metal)  # rear bumper
    frame.box((-3.71, -1.0, 0.4), (-3.7, 1.0, 0.48), m("hazard"))  # thin worn band
    wheel_xs = (-2.95, -1.8, 2.45)
    for x in wheel_xs:
        for side in (-1, 1):
            _bowser_wheel(frame, x, side)
        frame.tube((x, -0.84, 0.44), (x, 0.84, 0.44), 0.07, steel, 10)  # axle
    _bowser_arch(body, -2.95, -1.8)
    _bowser_arch(body, 2.45, 2.45)
    # Skirts between the arches and the fender line above them.
    for side in (-1, 1):
        y0, y1 = sorted((side * 0.96, side * 1.24))
        for x0, x1 in ((-1.12, 1.77), (3.13, 3.45)):
            body.box((x0, y0, 0.36), (x1, y1, 1.08), white)
        body.box((-3.6, y0, 1.08), (3.45, y1, 1.16), metal)  # fender rail
        # Equipment lockers in the skirt: dark doors with steel pulls.
        d0, d1 = sorted((side * 1.235, side * 1.245))
        p0, p1 = sorted((side * 1.245, side * 1.26))
        for lx in (-0.95, 0.05, 1.0):
            body.box((lx, d0, 0.48), (lx + 0.7, d1, 0.98), dark)
            frame.box((lx + 0.25, p0, 0.86), (lx + 0.45, p1, 0.9), steel)

    # Cab: one wedge profile, dark canopy, roof sensor bar and beacon.
    cab = [
        (1.78, 0.66),
        (3.5, 0.66),
        (3.62, 1.2),
        (3.48, 1.42),
        (2.98, 2.5),
        (2.6, 2.78),
        (1.78, 2.78),
    ]
    body.prism_y(cab, -1.18, 1.18, white)
    # Canopy glass sits proud of the slope, framed by a dark visor band.
    slope = [(3.5, 1.46), (3.0, 2.52), (2.98, 2.5)]
    n = Vector((slope[1][1] - slope[0][1], -(slope[1][0] - slope[0][0]))).normalized()
    a0 = Vector(slope[0]) + n * 0.012
    a1 = Vector(slope[1]) + n * 0.012
    canopy = [tuple(a0), tuple(a1), tuple(a1 + n * 0.03), tuple(a0 + n * 0.03)]
    body.prism_y(canopy, -1.02, 1.02, glass)
    pillar = [
        tuple(a0 + n * 0.02),
        tuple(a1 + n * 0.02),
        tuple(a1 + n * 0.05),
        tuple(a0 + n * 0.05),
    ]
    body.prism_y(pillar, -0.04, 0.04, white)  # centre pillar
    visor = [tuple(a1 - n * 0.01), (2.6, 2.79), (2.62, 2.84), tuple(a1 + n * 0.06)]
    body.prism_y(visor, -1.12, 1.12, dark)
    for side in (-1, 1):  # side windows and a thin red trim line
        y0, y1 = sorted((side * 1.18, side * 1.195))
        body.box((2.0, y0, 1.78), (2.8, y1, 2.5), glass)
        body.box((1.85, y0, 1.6), (3.3, y1, 1.63), "M_Light_RedTrim")
        d0, d1 = sorted((side * 1.18, side * 1.2))
        for dx in (1.92, 2.92):  # door seams and sill
            body.box((dx, d0, 0.95), (dx + 0.02, d1, 2.6), dark)
        body.box((1.92, d0, 0.95), (2.94, d1, 0.97), dark)
        body.box((2.12, d0 - 0.01 * (side < 0), 1.38), (2.3, d1 + 0.01 * (side > 0), 1.42), steel)
    G.chamfer_box(body, (2.0, -0.9, 2.78), (2.45, 0.9, 2.9), 0.06, dark)  # sensor bar
    G.tube_z(lamps, 0.07, 2.9, 3.04, m("lamp_amber"), 14, x=2.22, y=0.55)
    G.tube_z(frame, 0.012, 2.9, 3.2, steel, 6, x=2.1, y=-0.75)  # antenna
    for k in range(5):  # intake slats on the sloped nose
        z = 0.8 + k * 0.07
        x = 3.5 + 0.12 * (z - 0.66) / 0.54
        body.box((x - 0.02, -0.72, z), (x + 0.02, 0.72, z + 0.035), dark)
    for sy in (-1, 1):  # head and tail lights
        y0, y1 = sorted((sy * 0.62, sy * 1.0))
        lamps.box((3.63, y0, 1.2), (3.64, y1, 1.27), m("lamp_white"))
        lamps.box((-3.715, y0, 0.56), (-3.705, y1, 0.62), m("lamp_red"))

    # Tank: octagonal body with chamfered ends, gunmetal bands, dark side panels.
    sections = []
    for x, s in ((-3.42, 0.8), (-3.22, 1.0), (1.42, 1.0), (1.62, 0.82)):
        sections.append([(x, y, z) for y, z in _octagon(s)])
    G.loft(body, sections, white)
    for bx in (-2.38, -0.82, 0.74):
        G.wedge_x(frame, _octagon(1.0, 0.035), bx - 0.09, bx + 0.09, metal)
    for side in (-1, 1):
        y0, y1 = sorted((side * _TANK_Y, side * (_TANK_Y + 0.008)))
        for p0, p1 in ((-3.0, -2.55), (-2.2, -1.0), (-0.64, 0.56), (0.92, 1.3)):
            body.box((p0, y0, 1.42), (p1, y1, 1.86), dark)
        # Level gauge: a column of five lit cells, the top one dark (part full).
        for k in range(5):
            z = 1.5 + k * 0.15
            g0, g1 = sorted((side * (_TANK_Y + 0.008), side * (_TANK_Y + 0.014)))
            target, mat = (lamps, m("lamp_white")) if k < 4 else (body, dark)
            target.box((1.05, g0, z), (1.18, g1, z + 0.1), mat)
        # Two service pipes along the tank's lower chamfer.
        for dz, rr in ((1.12, 0.05), (1.26, 0.035)):
            frame.tube((-3.4, side * 1.0, dz), (1.5, side * 1.0, dz), rr, metal, 10)
    ink, face = m("stencil_dark"), _TANK_Y + 0.012
    G.text(decal, "FUEL", 0.34, ink, G.on_face((-1.6, -face, 2.13), "-Y"))
    G.text(decal, "B-02", 0.2, ink, G.on_face((-0.1, -face, 2.13), "-Y"))
    G.text(decal, "FUEL", 0.34, ink, G.on_face((-1.6, face, 2.13), "+Y"))

    # Walkway on the tank roof with rails, and a filler hatch.
    top = _TANK_Z1
    frame.box((-3.0, -0.45, top), (1.1, 0.45, top + 0.05), m("tread"))
    for side in (-1, 1):
        y = side * 0.42
        frame.tube((-2.9, y, top + 0.95), (1.0, y, top + 0.95), 0.022, steel, 8)
        frame.tube((-2.9, y, top + 0.5), (1.0, y, top + 0.5), 0.016, steel, 8)
        for px in (-2.9, -1.6, -0.3, 1.0):
            frame.tube((px, y, top + 0.05), (px, y, top + 0.97), 0.022, steel, 8)
    with G.xf(frame, G.T(-0.95, 0.0, top + 0.05)):
        G.lathe(frame, [(0.0, 0.16), (0.24, 0.14), (0.3, 0.06), (0.3, 0.0)], metal, 24)
    lamps.box((1.0, -0.06, top + 0.98), (1.06, 0.06, top + 1.02), m("lamp_red"))

    # Rear service end: hose reel, valve manifold, ladder to the walkway.
    with G.xf(frame, G.T(-3.55, 0.0, 1.1) @ G.Rx(90.0)):
        G.ring(frame, 0.16, 0.36, -0.55, 0.55, m("rubber"), 28)
        G.ring(frame, 0.36, 0.39, -0.6, -0.54, metal, 28)
        G.ring(frame, 0.36, 0.39, 0.54, 0.6, metal, 28)
    frame.tube((-3.55, -0.62, 1.1), (-3.55, 0.62, 1.1), 0.05, steel, 10)
    G.chamfer_box(frame, (-3.62, 0.62, 0.7), (-3.32, 1.0, 1.0), 0.04, dark)
    for k, vz in enumerate((0.78, 0.92)):
        frame.tube((-3.62, 0.7 + k * 0.16, vz), (-3.72, 0.7 + k * 0.16, vz), 0.035, metal, 10)
        with G.xf(frame, G.T(-3.73, 0.7 + k * 0.16, vz) @ G.Ry(90.0)):
            G.ring(frame, 0.05, 0.065, -0.01, 0.01, m("stencil_red"), 16)
    for ly in (-0.95, -0.6):
        frame.tube((-3.48, ly, 0.7), (-3.48, ly, top + 0.98), 0.02, steel, 8)
    for k in range(9):
        z = 0.95 + k * 0.24
        frame.tube((-3.48, -0.95, z), (-3.48, -0.6, z), 0.016, steel, 6)

    body.build("SM_fuelbowser_body", bevel_width=0.01)
    frame.build("SM_fuelbowser_frame", bevel_width=0.004)
    lamps.build("SM_fuelbowser_lamps", bevel_width=0.0, nav="none")
    decal.build("SM_fuelbowser_stencil", bevel_width=0.0, nav="none")
    K.occluder(((-3.75, -1.26, 0.0), (3.67, 1.26, 3.0)), nav="block")


K.register_variant("SM_Hangar_FuelBowser", build_fuel_bowser, dims=(7.4, 2.52, 3.2))
K.register_variant("SM_Hangar_FuelHydrant", build_fuel_hydrant, dims=(1.2, 1.2, 0.95))
K.register_variant("SM_Hangar_FuelCart", build_fuel_cart, dims=(2.85, 1.2, 1.25))
K.register_variant("SM_Hangar_ToolCart", build_tool_cart, dims=(1.22, 0.7, 1.0))


# --------------------------------------------------------------------------
# Hose helper (not a piece: routes a hose along any polyline)
# --------------------------------------------------------------------------


def build_hose(
    name: str, points, radius: float = 0.075, couplings: bool = True, room: str | None = None
):
    """Create a floor hose object along ``points`` ((x, y) or (x, y, z), Blender
    world metres) in the current kit collection. The polyline is smoothed
    (Catmull-Rom); the hose lies on the deck unless z values are given (use z
    for the rise into a shuttle intake). Returns the object (nav "none").
    """
    pts = [Vector((p[0], p[1], p[2] if len(p) > 2 else 0.0)) for p in points]
    smooth = G.catmull_rom(pts, 10)
    path = [Vector((p.x, p.y, max(p.z, 0.0) + radius)) for p in smooth]
    mb = K.MeshBuilder()
    G.sweep(mb, path, radius, m("rubber"), 12)
    if couplings:
        for a, b in ((path[0], path[1]), (path[-1], path[-2])):
            d = (b - a).normalized()
            mb.tube(a, a + d * 0.3, radius * 1.45, m("gunmetal"), 14)
            mb.tube(a + d * 0.12, a + d * 0.18, radius * 1.75, m("dark_steel"), 14)
    obj = mb.build(name, bevel_width=0.0, nav="none")
    if room:
        K.tag(obj, room=room)
    return obj


LOOKDEV = {
    "SM_Hangar_PortalGantry": {"focus": (8.0, -1.6, 7.0), "crop_size": (3.0, 1.9), "max_px": 2400},
    "SM_Hangar_LandingPad": {"focus": (0.0, -6.8, 0.0), "crop_size": (3.0, 1.9)},
}
