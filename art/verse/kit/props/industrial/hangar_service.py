"""Hangar service pieces (deck 4): landing pad, recessed floor light, portal
gantry crane on floor rails, fuel hydrant, fuel cart, tool cart, and a hose
helper that routes a floor hose along any polyline.

Piece-local frame: centred on X, deck at Z = 0, -Y toward the camera.
"""

from __future__ import annotations

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
