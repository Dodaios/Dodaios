"""Reactor shaft, core, control ring and catwalks of the engineering deck.

Deck-side blockout of the reactor assembly. props-industrial owns the hero
pieces; ``build()`` places theirs when the kit module is importable and falls
back to this bespoke geometry otherwise, so the deck always cooks.
"""

from __future__ import annotations

import math

import eng_common as c
from eng_common import Geo, build_into, deck_material, shaft_point
from lib import kit, scene

GUNMETAL = "M_Struct_Gunmetal"
HULL = "M_Hull_Structure"
GRATING = "M_Floor_Grating"
HAZARD = "M_Deck_Hazard"
CORE = "M_Eng_CoreHot"
HAZE = "M_Eng_ShaftHaze"
LAMP_RED = "M_Light_Maint_Red"
LAMP_AMBER = "M_Light_Maint_Amber"


# ---------------------------------------------------------------- materials


@deck_material(CORE, viewport=(1.0, 0.55, 0.25))
def _core_hot(g) -> None:
    """Plasma column seen through its containment: warm white at the top,
    deepening to orange with depth, slow convection cells, no neon."""
    co = g.coord("object", per_instance=False)
    _, _, height = g.separate(co)
    cells = g.noise(g.vmath("MULTIPLY", co, (0.6, 0.6, 0.18)), 1.0, detail=4, rough=0.55)
    fine = g.noise(co, 2.4, detail=2)
    depth = g.remap(height, -c.SHAFT_DEPTH, 1.0, 0.0, 1.0)
    temp = g.add(g.mul(g.math("POWER", depth, 1.6), 0.75), g.mul(cells, 0.25))
    colour = g.mix_color(temp, g.blackbody(1700.0), g.blackbody(3900.0))
    strength = g.mul(
        g.add(0.6, g.mul(cells, 0.3), g.mul(fine, 0.1)),
        g.remap(g.math("POWER", depth, 2.0), 0.0, 1.0, 1.5, 16.0),
    )
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], colour)
    g.set(node.inputs["Strength"], strength)
    g.output(node.outputs[0])
    g.mat.cycles.emission_sampling = "FRONT"


@deck_material(HAZE, viewport=(0.3, 0.25, 0.2))
def _shaft_haze(g) -> None:
    """Thin dust haze in the shaft; the core lights it, depth swallows it."""
    co = g.coord("object", per_instance=False)
    _, _, height = g.separate(co)
    density = g.remap(height, -40.0, -1.0, 0.009, 0.0015, smooth=True)
    vol = g.new("ShaderNodeVolumePrincipled")
    g.set(vol.inputs["Color"], (0.62, 0.6, 0.58))
    g.set(vol.inputs["Density"], density)
    g.set(vol.inputs["Anisotropy"], 0.45)
    g.set(g.out.inputs["Volume"], vol.outputs[0])


# ---------------------------------------------------------------- pieces


def _catwalk_frame(angle: float):
    """(start, direction, side) vectors in Blender XY for a catwalk at `angle`."""
    a = math.radians(angle)
    d = (math.cos(a), math.sin(a))
    s = (-d[1], d[0])
    return d, s


def _quad_box(geo: Geo, angle: float, r0: float, r1: float, w0: float, w1: float,
              y0: float, y1: float, mat: str) -> None:  # fmt: skip
    """Box aligned with a radial direction: radius r0..r1, lateral w0..w1."""
    d, s = _catwalk_frame(angle)
    cx, cy = c.SHAFT_C[0], -c.SHAFT_C[1]
    corners = []
    for r, w in ((r0, w0), (r1, w0), (r1, w1), (r0, w1)):
        corners.append((cx + d[0] * r + s[0] * w, cy + d[1] * r + s[1] * w))
    geo.prism_z(corners, y0, y1, mat)


def shaft() -> None:
    wall = Geo()
    depth = -c.SHAFT_DEPTH
    wall.sector(c.SHAFT_R, c.SHAFT_WALL_R, depth, -c.SLAB_T, HULL, segments=192)
    # Vertical ribs every 15 degrees.
    for i in range(24):
        a = i * 15.0 + 7.5
        _quad_box(wall, a, c.SHAFT_R - 0.45, c.SHAFT_R + 0.05, -0.18, 0.18, depth, -1.2, GUNMETAL)
    # Service rings (galleries) every 9.6 m down.
    for k in range(1, 6):
        y = -9.6 * k + 1.2
        wall.sector(c.SHAFT_R - 1.5, c.SHAFT_R, y - 0.35, y, GUNMETAL, segments=192)
        wall.sector(c.SHAFT_R - 1.55, c.SHAFT_R - 1.47, y, y + 1.0, GUNMETAL, segments=192)
        wall.sector(c.SHAFT_R - 0.1, c.SHAFT_R + 0.05, y + 2.2, y + 2.6, GUNMETAL, segments=192)
    wall.sector(0.0, c.SHAFT_WALL_R, depth - 1.0, depth, HULL, segments=96)
    # Radial conduits from the shaft wall to the core at two depths.
    for y in (-16.4, -33.2):
        for i in range(8):
            a = i * 45.0 + 22.5
            _quad_box(wall, a, c.CORE_R + 0.3, c.SHAFT_R, -0.42, 0.42, y - 0.84, y, GUNMETAL)
            _quad_box(wall, a, c.CORE_R + 0.3, c.SHAFT_R, -0.6, 0.6, y - 0.3, y - 0.18, GUNMETAL)
    obj = build_into("Architecture", wall, "SM_Eng_ShaftWall", bevel_width=0.01)
    kit.tag(obj, nav="none")

    # Pipe bundles riding the shaft wall between the ribs.
    pipes = Geo()
    for i in range(24):
        a = i * 15.0
        for j, off in enumerate((-0.9, -0.55, 0.55)):
            r = c.SHAFT_R - 0.22
            px, py, _ = shaft_point(r, a + math.degrees(off / r))
            radius = 0.14 if j else 0.2
            pipes.tube((px, py, depth), (px, py, -1.0), radius, "M_Hull_Pipe", 12)
    obj = build_into("Architecture", pipes, "SM_Eng_ShaftPipes", bevel_width=0.0)
    kit.tag(obj, nav="none")

    lamps = Geo()
    for k in range(1, 6):
        y = -9.6 * k + 1.2
        for i in range(24):
            a = i * 15.0
            px, py, _ = shaft_point(c.SHAFT_R - 1.56, a)
            if i % 2:
                continue
            mat = LAMP_AMBER if i % 6 == 0 else LAMP_RED
            lamps.box((px - 0.07, py - 0.07, y + 0.78), (px + 0.07, py + 0.07, y + 0.9), mat)
            wx, wy, _ = shaft_point(c.SHAFT_R - 0.12, a + 7.5)
            lamps.box((wx - 0.25, wy - 0.06, y + 2.0), (wx + 0.25, wy + 0.06, y + 2.12),
                      "M_Light_WallStrip")  # fmt: skip
    obj = build_into("Props", lamps, "SM_Eng_ShaftLamps", bevel_width=0.0)
    kit.tag(obj, nav="none")

    haze = Geo()
    haze.sector(0.0, c.SHAFT_R - 0.05, depth + 0.05, -0.6, HAZE, segments=96)
    obj = build_into("Props", haze, "SM_Eng_ShaftHaze", bevel_width=0.0)
    obj.visible_shadow = False
    kit.tag(obj, nav="none")


def core() -> None:
    column = Geo()
    column.sector(0.0, c.CORE_R, -c.SHAFT_DEPTH, 0.6, CORE, segments=96)
    obj = build_into("Props", column, "SM_Eng_CoreColumn", bevel_width=0.0)
    kit.tag(obj, nav="none")

    cage = Geo()
    y = -c.SHAFT_DEPTH + 1.0
    while y < -0.8:
        cage.sector(c.CORE_R - 0.02, c.CORE_R + 0.32, y, y + 0.45, GUNMETAL, segments=96)
        y += 4.8
    # Containment cap: collar, slotted drum, low dome.
    cage.sector(c.CORE_R - 0.1, c.CORE_R + 0.55, -0.8, 0.7, GUNMETAL, segments=96)
    cage.sector(0.0, c.CORE_R + 0.35, 0.7, 1.9, "M_Wall_PaintedDark", segments=96)
    cage.sector(0.0, c.CORE_R - 0.4, 1.9, 2.5, GUNMETAL, segments=96)
    for i in range(8):
        a = i * 45.0 + 22.5
        _quad_box(cage, a, c.CORE_R + 0.2, c.CORE_R + 0.7, -0.22, 0.22, -0.6, 2.1, GUNMETAL)
    obj = build_into("Props", cage, "SM_Eng_CoreCage", bevel_width=0.012)
    kit.tag(obj, nav="block")
    slots = Geo()
    for i in range(16):
        a = i * 22.5
        _quad_box(slots, a, c.CORE_R + 0.33, c.CORE_R + 0.37, -0.12, 0.12, 0.95, 1.65, CORE)
    obj = build_into("Props", slots, "SM_Eng_CoreSlots", bevel_width=0.0)
    kit.tag(obj, nav="none")


def ring_and_catwalks() -> None:
    ring = Geo()
    r0, r1 = c.RING_R
    ring.sector(r0, r1, -0.12, 0.0, GRATING, segments=160)
    ring.sector(r0 + 0.15, r1 - 0.15, -0.9, -0.12, GUNMETAL, segments=160)
    obj = build_into("Architecture", ring, "SM_Eng_ControlRing", bevel_width=0.006)
    kit.tag(obj, nav="walk")

    under = Geo()
    for i in range(8):
        a = i * 45.0 + 22.5
        _quad_box(under, a, c.CORE_R + 0.6, r0 + 0.3, -0.1, 0.1, -1.6, -0.9, GUNMETAL)
    obj = build_into("Architecture", under, "SM_Eng_RingBraces", bevel_width=0.006)
    kit.tag(obj, nav="none")

    walks = Geo()
    trusses = Geo()
    edges = Geo()
    half = c.CATWALK_W / 2
    for a in c.CATWALK_ANGLES:
        _quad_box(walks, a, r1 - 0.1, c.SHAFT_R + 0.25, -half, half, -0.1, 0.0, GRATING)
        for w in (-half + 0.05, half - 0.2):
            _quad_box(trusses, a, r1 - 0.1, c.SHAFT_R + 0.25, w, w + 0.15, -0.65, -0.1, GUNMETAL)
        for w in (-half, half - 0.06):
            _quad_box(edges, a, r1, c.SHAFT_R, w, w + 0.06, 0.0, 0.004, HAZARD)
    obj = build_into("Architecture", walks, "SM_Eng_Catwalks", bevel_width=0.004)
    kit.tag(obj, nav="walk")
    obj = build_into("Architecture", trusses, "SM_Eng_CatwalkTruss", bevel_width=0.006)
    kit.tag(obj, nav="none")
    obj = build_into("Props", edges, "SM_Eng_CatwalkEdges", bevel_width=0.0)
    kit.tag(obj, nav="none")


def rim() -> None:
    kerb = Geo()
    gap = math.degrees((c.CATWALK_GAP / 2) / c.SHAFT_R)
    angles = sorted(c.CATWALK_ANGLES)
    for i, a in enumerate(angles):
        b = angles[(i + 1) % len(angles)] + (360.0 if i == len(angles) - 1 else 0.0)
        kerb.sector(*c.KERB_R, 0.0, c.KERB_H, GUNMETAL, a + gap, b - gap, top="M_Section_Cap")
    obj = build_into("Architecture", kerb, "SM_Eng_Kerb", bevel_width=0.01)
    kit.tag(obj, nav="block")
    band = Geo()
    band.sector(*c.HAZARD_R, 0.0, 0.004, HAZARD, segments=192)
    obj = build_into("Props", band, "SM_Eng_RimHazard", bevel_width=0.0)
    kit.tag(obj, nav="none")


POWER_UNITS = ((77.4, 12.0), (77.4, 22.0), (77.4, 32.0))


def hall_equipment() -> None:
    """East of the shaft: power conduit banks rising to the ceiling, fed by
    coolant runs from the collar (kit pieces); blockout octagons otherwise."""
    if c.KIT_REACTOR:
        with kit.into(scene.collection("Props")):
            for i, (x, z) in enumerate(POWER_UNITS):
                kit.place("SM_Eng_PowerConduit_Triple", c.b(x + 1.2, z), 90.0, room="reactor",
                          id=f"EngHallConduit_{i}")  # fmt: skip
                kit.place("SM_Eng_CoolantPipes", c.b(73.2, z), 0.0, room="reactor",
                          id=f"EngHallCoolant_{i}")  # fmt: skip
        return
    units = Geo()
    glow = Geo()
    trench = Geo()
    for x, z in POWER_UNITS:
        centre = (x, -z)
        units.sector(0.0, 1.55, 0.0, 0.25, GUNMETAL, segments=8, centre=centre)
        units.sector(0.0, 1.3, 0.25, 2.6, "M_Wall_PaintedMid", segments=8, centre=centre)
        units.sector(0.0, 1.38, 2.6, 2.9, GUNMETAL, segments=8, centre=centre)
        units.sector(0.0, 0.9, 2.9, 3.15, "M_Wall_PaintedDark", segments=8, centre=centre)
        for k, y0 in enumerate((0.9, 1.55)):
            glow.box3(x - 0.42, x + 0.42, z + 1.2, z + 1.24, y0, y0 + 0.45,
                      "M_Screen" if k else "M_Console_Keys")  # fmt: skip
        dz = z - c.SHAFT_C[1]
        x_rim = c.SHAFT_C[0] + math.sqrt(max(c.HAZARD_R[1] ** 2 - dz * dz, 0.0))
        if c.KIT_REACTOR:
            x_rim = c.SHAFT_C[0] + c.COLLAR_HALF
        trench.box3(x_rim + 0.2, x - 1.55, z - 0.3, z + 0.3, -0.02, 0.003, GRATING)
    obj = build_into("Props", units, "SM_Eng_PowerUnits", bevel_width=0.01)
    kit.tag(obj, nav="block")
    build_into("Props", glow, "SM_Eng_PowerUnitPanels", bevel_width=0.0)
    obj = build_into("Props", trench, "SM_Eng_TrenchCovers", bevel_width=0.003)
    kit.tag(obj, nav="none")


def build() -> None:
    hall_equipment()
    if c.KIT_REACTOR:
        from kit.props.industrial import reactor

        cx, cz = c.SHAFT_C
        with kit.into(scene.collection("Architecture")):
            reactor.place_reactor(c.b(cx, cz), room="reactor", prefix="reactor")
        return
    shaft()
    core()
    ring_and_catwalks()
    rim()
