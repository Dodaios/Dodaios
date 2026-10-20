"""Hangar architecture: deck slabs, hero wall, launch well, hull walls, front band, ceiling.

Bespoke deck geometry built with ``lib.kit.MeshBuilder`` and library
materials. All coordinates go through ``hangar_layout.B`` (plan x, z, height);
plan z grows toward the camera, so anything mounted on a wall face protrudes
toward +z. Every solid a character can stand behind gets a ``UCX_`` box in
``occluders()``.
"""

from __future__ import annotations

import math

import bmesh
import bpy
import hangar_layout as L
import hangar_paint
from lib import kit, materials, scene

B = L.B
CAP = "M_Section_Cap"
PANEL = "M_Wall_PaintedLight"
PANEL_MID = "M_Wall_PaintedMid"
PANEL_DARK = "M_Wall_PaintedDark"
STEEL = "M_Struct_Gunmetal"
TRIM = "M_Trim_BrushedSteel"
RECESS = "M_Recess_Dark"
HULL = "M_Hull_Structure"
RUBBER = "M_Rubber_Black"


# --------------------------------------------------------------------------
# Deck-local materials
# --------------------------------------------------------------------------


@materials.material("M_Hangar_FieldBlue", viewport=(0.1, 0.25, 0.6))
def _field_blue(g) -> None:
    """Containment field over the launch well: faint blue sheet, see-through.

    An even, very faint sheen with a thin glow at the rim (where the emitters
    sit); never a starfield, only the dark shaft below.
    """
    co = g.coord("object", per_instance=False)
    x, y, _ = g.separate(co)
    hx, hy = (L.WELL[1] - L.WELL[0]) / 2, (L.WELL[3] - L.WELL[2]) / 2
    edge_x = g.math("SUBTRACT", hx, g.math("ABSOLUTE", x))
    edge_y = g.math("SUBTRACT", hy, g.math("ABSOLUTE", y))
    edge = g.math("MINIMUM", edge_x, edge_y)
    rim = g.math("EXPONENT", g.mul(edge, -5.0))
    strength = g.mul(rim, 0.18)  # faint cool sheen at the rim only
    emit = g.new("ShaderNodeEmission")
    g.set(emit.inputs["Color"], (0.55, 0.68, 0.85))
    g.set(emit.inputs["Strength"], strength)
    # A tinted sheet: what lies below is dimmed and cooled, so the shaft reads dark.
    clear = g.new("ShaderNodeBsdfTransparent")
    g.set(clear.inputs["Color"], (0.5, 0.52, 0.56))
    add = g.new("ShaderNodeAddShader")
    g.set(add.inputs[0], emit.outputs[0])
    g.set(add.inputs[1], clear.outputs[0])
    g.output(add.outputs[0])
    materials._set_emission_sampling(g.mat, "NONE")


@materials.material("M_Hangar_WellFog", viewport=(0.02, 0.03, 0.05))
def _well_fog(g) -> None:
    """Absorbing dark inside the shaft: depth falls away to black, no scattering."""
    vol = g.new("ShaderNodeVolumeAbsorption")
    g.set(vol.inputs["Color"], (0.04, 0.04, 0.045))
    g.set(vol.inputs["Density"], 0.14)
    g.set(g.out.inputs["Volume"], vol.outputs[0])


@materials.material("M_Hangar_ShaftLamp", viewport=(0.9, 0.95, 1.0))
def _shaft_lamp(g) -> None:
    """Small white lamp on a shaft ring frame."""
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], g.blackbody(6500.0))
    g.set(node.inputs["Strength"], 3.5)
    g.output(node.outputs[0])
    materials._set_emission_sampling(g.mat, "NONE")


@materials.material("M_Hangar_FloorLamp", viewport=(0.9, 0.95, 1.0))
def _floor_lamp(g) -> None:
    """Recessed round deck lamp behind a thick lens."""
    bsdf = g.principled(
        Base_Color=(0.05, 0.05, 0.05),
        Roughness=0.15,
        Coat_Weight=1.0,
        Coat_Roughness=0.03,
        Emission_Color=g.blackbody(6500.0),
        Emission_Strength=3.5,
    )
    g.output(bsdf.outputs[0])
    materials._set_emission_sampling(g.mat, "NONE")


@materials.material("M_Hangar_DoorGlow", viewport=(1.0, 1.0, 1.0))
def _door_glow(g) -> None:
    """Opal light band around the stand-in blast door opening, 6 500 K."""
    materials._emitter(g, 16.0, kelvin=6500.0, falloff=0.03)


@materials.material("M_Hangar_RoomStrip", viewport=(1.0, 1.0, 1.0))
def _room_strip(g) -> None:
    """Room ceiling light panel seen only in the polished floor (area lights light the room)."""
    path = g.new("ShaderNodeLightPath")
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], g.blackbody(6200.0))
    g.set(node.inputs["Strength"], g.mul(path.outputs["Is Glossy Ray"], 3.0))
    g.output(node.outputs[0])
    materials._set_emission_sampling(g.mat, "NONE")


@materials.material("M_Hangar_PierLight", viewport=(1.0, 1.0, 1.0))
def _pier_light(g) -> None:
    """Backlit rectangle of a hero-wall light column, 6 200 K."""
    materials._emitter(g, 9.0, kelvin=6200.0, falloff=0.05)


@materials.material("M_Hangar_FloodLens", viewport=(1.0, 1.0, 0.95))
def _flood_lens(g) -> None:
    """Flood lamp lens face (the spot light inside does the lighting)."""
    materials._emitter(g, 45.0, kelvin=5800.0, falloff=0.08, sampling="NONE")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def box(mb: kit.MeshBuilder, x0, x1, z0, z1, h0, h1, material):
    """Plan box: x0..x1, plan z0..z1 (toward the camera), height h0..h1."""
    mb.box((x0, -z1, h0), (x1, -z0, h1), material)


def _build(mb, name, bevel=0.01, nav=None, collection="Architecture", **props):
    with kit.into(scene.collection(collection)):
        obj = mb.build(name, bevel_width=bevel, **props)
    if obj is not None and nav is not None:
        kit.tag(obj, nav=nav)
    return obj


# --------------------------------------------------------------------------
# Deck slabs
# --------------------------------------------------------------------------


def floors(well_piece: bool = False) -> None:
    hangar_paint.build_masks()
    mb = kit.MeshBuilder()
    deck = "M_Hangar_Deck"
    x0w, x1w, z0w, z1w = L.WELL
    if well_piece:
        # The kit well's rim covers a chamfered outline 1.2 m wider.
        x0w, x1w, z0w, z1w = x0w - 1.2, x1w + 1.2, z0w - 1.2, z1w + 1.2
        c = 2.4 + 1.2 * 0.414
        for cx, cz, sx, sz in (
            (x0w, z0w, 1, 1),
            (x1w, z0w, -1, 1),
            (x0w, z1w, 1, -1),
            (x1w, z1w, -1, -1),
        ):
            tri = [(cx, -cz), (cx + sx * c, -cz), (cx, -(cz + sz * c))]
            mb.prism_z(tri, -0.6, 0.0, deck)
    xa, xb = L.SIDE_T, L.WIDTH - L.SIDE_T
    zf = L.WALL_FACE_Z - 0.2
    # Flight deck around the well, plus the crew bay of the front band.
    box(mb, xa, xb, zf, z0w, -0.6, 0.0, deck)
    box(mb, xa, xb, z1w, L.FRONT_Z, -0.6, 0.0, deck)
    box(mb, xa, x0w, z0w, z1w, -0.6, 0.0, deck)
    box(mb, x1w, xb, z0w, z1w, -0.6, 0.0, deck)
    box(mb, L.BOOTH[1], L.ARRIVALS[0], L.FRONT_Z, L.NEAR_WALL_Z[0], -0.6, 0.0, deck)
    box(mb, xa, L.BOOTH[0], L.FRONT_Z, L.NEAR_WALL_Z[0], -0.6, 0.0, deck)
    box(mb, L.BOOTH[0], L.BOOTH[1], L.FRONT_Z, L.BOOTH[2], -0.6, 0.0, deck)
    _build(mb, "SM_Hangar_FlightDeck", bevel=0.0, nav="walk", room="flight_deck")

    # Satin plate in the arrivals hall, polished black in the lift lobby.
    satin_a = kit.MeshBuilder()
    box(
        satin_a,
        L.ARRIVALS[0],
        L.ARRIVALS[1],
        L.FRONT_Z,
        L.NEAR_WALL_Z[0],
        -0.6,
        0.0,
        "M_Floor_SatinDark",
    )
    _build(satin_a, "SM_Hangar_ArrivalsFloor", bevel=0.0, nav="walk", room="arrivals")
    gloss = kit.MeshBuilder()
    box(gloss, L.LOBBY[0], L.LOBBY[1], L.FRONT_Z, L.NEAR_WALL_Z[0], -0.6, 0.0, "M_Floor_GlossBlack")
    _build(gloss, "SM_Hangar_LobbyFloor", bevel=0.0, nav="walk", room="lift_lobby")
    satin = kit.MeshBuilder()
    box(
        satin,
        L.ARMOURY[0],
        L.WIDTH - L.SIDE_T,
        L.FRONT_Z,
        L.NEAR_WALL_Z[0],
        -0.6,
        0.0,
        "M_Floor_SatinDark",
    )
    _build(satin, "SM_Hangar_ArmouryFloor", bevel=0.0, nav="walk", room="armoury")

    inlay = kit.MeshBuilder()
    for x in (L.ARRIVALS[0] + 1.2, L.ARRIVALS[1] - 1.2):
        box(
            inlay,
            x - 0.06,
            x + 0.06,
            L.FRONT_Z + 1.0,
            L.NEAR_WALL_Z[0] - 0.6,
            -0.01,
            0.002,
            "M_Light_FloorInlay",
        )
    _build(inlay, "SM_Hangar_ArrivalsInlay", bevel=0.0, nav="none")
    deck_lamps()

    # Hull below and in front of the near wall (fills the frame margin).
    hull = kit.MeshBuilder()
    box(hull, -2.0, L.WIDTH + 2.0, L.NEAR_WALL_Z[1], L.DEPTH + 3.0, -2.0, -0.04, HULL)
    for x in range(0, int(L.WIDTH) + 1, 6):
        box(hull, x - 0.2, x + 0.2, L.NEAR_WALL_Z[1], L.DEPTH + 3.0, -0.04, 0.12, STEEL)
    _build(hull, "SM_Hangar_HullApron", bevel=0.01, nav="none")


def deck_lamps() -> None:
    """Round recessed deck lamps: the pad ring, the walkway, the door threshold."""
    mb = kit.MeshBuilder()
    rim = kit.MeshBuilder()

    def lamp(x, z, r=0.13):
        n = 16
        ring = [
            (x + r * math.cos(2 * math.pi * i / n), -z + r * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ]
        mb.prism_z(ring, -0.01, 0.004, "M_Hangar_FloorLamp")
        outer = [
            (
                x + (r + 0.05) * math.cos(2 * math.pi * i / n),
                -z + (r + 0.05) * math.sin(2 * math.pi * i / n),
            )
            for i in range(n)
        ]
        rim.prism_z(outer, -0.01, 0.003, TRIM)

    cx, cz = L.PAD_C
    import hangar_props

    if not hangar_props.USE_LANDING_PAD:  # the kit pad has its own edge lights
        for i in range(32):
            a = 2 * math.pi * (i + 0.5) / 32
            lamp(cx + (L.PAD_R + 2.0) * math.cos(a), cz - (L.PAD_R + 2.0) * math.sin(a))
    for z in range(int(L.WALKWAY_Z[0]) + 1, int(L.WALKWAY_Z[1]), 2):
        lamp(L.WALKWAY_X[0] - 0.45, z + 0.5, 0.1)
        lamp(L.WALKWAY_X[1] + 0.45, z + 0.5, 0.1)
    for x in range(int(L.DOOR_X[0]) - 1, int(L.DOOR_X[1]) + 2, 3):
        lamp(x + 0.5, 6.4, 0.11)
    x0, x1, z0, z1 = L.WELL
    for x in [x0 - 0.9 + i * (x1 - x0 + 1.8) / 12 for i in range(13)]:
        lamp(x, z0 - 0.9, 0.1)
        lamp(x, z1 + 0.9, 0.1)
    _build(mb, "SM_Hangar_DeckLamps", bevel=0.0, nav="none")
    _build(rim, "SM_Hangar_DeckLampRims", bevel=0.0, nav="none")


# --------------------------------------------------------------------------
# Hero wall (z = 0..3): blast door, piers, panelling, light columns, rail, floods
# --------------------------------------------------------------------------

PIER_XS = (6.0, 13.2, 20.4, 79.6, 86.8, 94.0)


def hero_wall(door_piece: bool = False) -> list[tuple[float, float, float]]:
    """Build the hero wall; return flood light mounts (plan x, z, height)."""
    face = L.WALL_FACE_Z
    dx0, dx1 = L.DOOR_X
    ox0, ox1 = dx0 - L.FRAME_W, dx1 + L.FRAME_W
    top = L.DOOR_H + L.FRAME_W
    mb = kit.MeshBuilder()
    # Structural mass behind the face, with a pocket for the blast door body.
    box(mb, -2.0, ox0, -1.0, face - 0.05, 0.0, L.WALL_TOP, RECESS)
    box(mb, ox1, L.WIDTH + 2.0, -1.0, face - 0.05, 0.0, L.WALL_TOP, RECESS)
    box(mb, ox0, ox1, -1.0, face - 0.05, top, L.WALL_TOP, RECESS)
    box(mb, ox0, ox1, -1.0, 0.0, 0.0, top, RECESS)
    _build(mb, "SM_Hangar_HeroWallMass", bevel=0.0)
    sill = kit.MeshBuilder()
    box(sill, dx0, dx1, 0.5, face - 0.19, -0.6, 0.0, STEEL)
    for x in [dx0 + 0.6 + 1.2 * i for i in range(int((dx1 - dx0) / 1.2))]:
        box(sill, x - 0.03, x + 0.03, 0.55, face - 0.2, -0.004, 0.003, RECESS)
    _build(sill, "SM_Hangar_DoorSill", bevel=0.004, nav="walk")

    _panelling(face, (L.SIDE_T - 0.5, ox0), "W")
    _panelling(face, (ox1, L.WIDTH - L.SIDE_T + 0.5), "E")
    _upper_band(face)
    mounts = []
    for i, x in enumerate(PIER_XS):
        _pier(f"SM_Hangar_Pier_{i + 1:02d}", x, face)
        mounts.append((x, 2.05 + 0.5, 12.3))
    if door_piece:
        # The piece carries its own light band in the frame.
        with kit.into(scene.collection("Architecture")):
            kit.place(
                "SM_Hangar_BlastDoor",
                B(50.0, face, 0.0),
                0.0,
                id="BlastDoor_Bay4",
                room="flight_deck",
            )
    else:
        _blast_door_placeholder(face)
    _gantry_rail(face)
    return mounts


def _panelling(face: float, span: tuple[float, float], side: str) -> None:
    """Dark gunmetal/charcoal panel field on the 2.4 m module with light-column bays."""
    x0, x1 = span
    panels = kit.MeshBuilder()
    trims = kit.MeshBuilder()
    lights = kit.MeshBuilder()
    gap = 0.012
    zf = face  # plan z of the panel fronts; fittings protrude toward +z
    depth = 0.06
    bands = [
        (0.0, 0.32, STEEL, 2.4),
        (0.32, 1.26, STEEL, 2.4),
        (1.36, 3.76, PANEL_DARK, 2.4),
        (3.76, 6.16, PANEL_DARK, 2.4),
        (6.56, 8.96, STEEL, 1.2),
        (8.96, 11.36, PANEL_DARK, 2.4),
        (11.36, 13.76, PANEL_DARK, 2.4),
        (13.76, 15.2, STEEL, 2.4),
    ]
    start = math.floor(x0 / 1.2) * 1.2
    for h0, h1, mat, module in bands:
        x = start
        while x < x1 - 1e-6:
            a, b = max(x, x0), min(x + module, x1)
            if b - a > 0.2:
                box(panels, a + gap, b - gap, zf - depth, zf, h0 + gap, h1 - gap, mat)
            x += module
    # Dado rail and a mid-height rib.
    box(trims, x0, x1, zf, zf + 0.1, 1.26, 1.36, TRIM)
    box(trims, x0, x1, zf, zf + 0.3, 6.16, 6.24, STEEL)
    box(trims, x0, x1, zf, zf + 0.3, 6.48, 6.56, STEEL)
    box(trims, x0, x1, zf - 0.02, zf + 0.01, 6.24, 6.48, RECESS)
    # Small red and green service lamps in the base band.
    x = start + 1.8
    k = 0
    while x < x1 - 0.8:
        if x > x0 + 0.4 and k % 2:
            box(trims, x - 0.3, x + 0.3, zf, zf + 0.03, 0.5, 1.0, RECESS)
            box(
                lights,
                x - 0.2,
                x - 0.12,
                zf + 0.03,
                zf + 0.04,
                0.9,
                0.95,
                "M_Indicator_Green" if k % 3 else "M_Indicator_Red",
            )
        k += 1
        x += 2.4
    # Recessed bays between the piers: a column of stacked backlit rectangles,
    # flanked by dark grilles (the hall's signature motif).
    for bx0, bx1 in _bays(x0, x1):
        mid = (bx0 + bx1) / 2
        _light_column(trims, lights, mid, zf)
        for gx in (mid - 1.55, mid + 1.55):
            if bx0 + 0.3 < gx - 0.45 and gx + 0.45 < bx1 - 0.3:
                _grille(trims, gx, zf)
    _build(panels, f"SM_Hangar_WallPanels_{side}", bevel=0.006)
    _build(trims, f"SM_Hangar_WallTrims_{side}", bevel=0.004)
    _build(lights, f"SM_Hangar_WallLights_{side}", bevel=0.0)


def _bays(x0: float, x1: float) -> list[tuple[float, float]]:
    """Wall bays between consecutive piers inside the span x0..x1."""
    edges = [x0] + [x for x in PIER_XS if x0 < x < x1] + [x1]
    return [(a + 0.7, b - 0.7) for a, b in zip(edges[:-1], edges[1:], strict=False) if b - a > 3.0]


def _light_column(trims, lights, x: float, zf: float, h0: float = 1.7, h1: float = 13.5):
    """Recessed column of stacked backlit rectangles in a steel frame."""
    w = 0.86
    box(trims, x - w / 2 - 0.08, x + w / 2 + 0.08, zf, zf + 0.09, h0 - 0.12, h1 + 0.12, STEEL)
    box(trims, x - w / 2, x + w / 2, zf + 0.06, zf + 0.1, h0, h1, RECESS)
    pitch = 0.62
    n = int((h1 - h0) / pitch)
    for k in range(n):
        hz = h0 + 0.08 + k * pitch
        box(lights, x - 0.3, x + 0.3, zf + 0.1, zf + 0.11, hz, hz + 0.44, "M_Hangar_PierLight")


def _grille(trims, x: float, zf: float, h0: float = 1.7, h1: float = 13.5):
    """Dark vent grille: horizontal slats over a black recess."""
    box(trims, x - 0.45, x + 0.45, zf, zf + 0.02, h0, h1, RECESS)
    hz = h0 + 0.1
    while hz < h1 - 0.1:
        box(trims, x - 0.42, x + 0.42, zf + 0.02, zf + 0.06, hz, hz + 0.07, STEEL)
        hz += 0.22


def _upper_band(face: float) -> None:
    """Dark ribbed structure above 15 m: the hangar's upper girders."""
    ox0, ox1 = L.DOOR_X[0] - L.FRAME_W - 0.6, L.DOOR_X[1] + L.FRAME_W + 0.6
    door_top = L.DOOR_H + L.FRAME_W + 2.0  # clear of the door's light band

    def base(x):
        return door_top if ox0 < x < ox1 else 15.6

    mb = kit.MeshBuilder()
    for a, b in ((-2.0, ox0), (ox1, L.WIDTH + 2.0)):
        box(mb, a, b, face, face + 0.25, 15.2, 15.6, STEEL)
        box(mb, a, b, face, face + 0.6, 16.4, 16.9, STEEL)
    box(mb, -2.0, L.WIDTH + 2.0, face - 0.02, face, 15.6, L.WALL_TOP, PANEL_DARK)
    box(mb, ox0, ox1, face, face + 0.3, door_top - 0.2, door_top, STEEL)
    for x in [i * 2.4 for i in range(43)]:
        box(mb, x - 0.12, x + 0.12, face, face + 0.45, base(x), L.WALL_TOP, STEEL)
    box(mb, -2.0, L.WIDTH + 2.0, face, face + 0.6, 20.4, 20.9, STEEL)
    _build(mb, "SM_Hangar_UpperBand", bevel=0.01)
    lamps = kit.MeshBuilder()
    for x in [3.6 + i * 7.2 for i in range(14)]:
        if ox0 < x < ox1:
            continue
        box(lamps, x - 0.08, x + 0.08, face + 0.6, face + 0.62, 16.0, 16.15, "M_Indicator_Red")
    _build(lamps, "SM_Hangar_UpperLamps", bevel=0.0)


def _pier(name: str, x: float, face: float) -> None:
    """Angled gunmetal wall pier (a structural rib) carrying a flood lamp."""
    w = 1.3
    front0, front1 = L.PIER_FRONT_Z, face + 0.55
    top = 15.2
    mb = kit.MeshBuilder()
    # Profile in Blender (y, z): slanted front from the deck to 9 m, then vertical.
    profile = [
        (-face + 0.02, 0.0),
        (-front0, 0.0),
        (-front0, 0.5),
        (-front1, 9.0),
        (-front1, top),
        (-face + 0.02, top),
    ]
    mb.prism_x(profile, x - w / 2, x + w / 2, STEEL)
    box(mb, x - w / 2 - 0.05, x + w / 2 + 0.05, face, front0 + 0.08, 0.0, 0.42, STEEL)
    box(mb, x - w / 2 - 0.04, x + w / 2 + 0.04, face, front1 + 0.1, top - 0.4, top, STEEL)
    _build(mb, name, bevel=0.02)
    # Flood lamp housing near the top, tilted down at the deck.
    flood = kit.MeshBuilder()
    fz = front1 + 0.1
    box(flood, x - 0.55, x + 0.55, fz, fz + 0.7, 12.1, 12.9, STEEL)
    box(flood, x - 0.12, x + 0.12, fz, fz + 0.3, 12.9, 13.4, STEEL)
    _build(flood, f"{name}_Flood", bevel=0.01)
    lens = kit.MeshBuilder()
    lens.quad(
        [
            (x - 0.45, -fz - 0.62, 12.08),
            (x + 0.45, -fz - 0.62, 12.08),
            (x + 0.45, -fz - 0.12, 12.08),
            (x - 0.45, -fz - 0.12, 12.08),
        ],
        "M_Hangar_FloodLens",
    )
    _build(lens, f"{name}_FloodLens", bevel=0.0)


def _blast_door_placeholder(face: float) -> None:
    """Pressure frame, glow band and two closed leaves (when the kit door is missing)."""
    x0, x1 = L.DOOR_X
    fw = L.FRAME_W
    h = L.DOOR_H
    ch = 2.2  # top corner chamfer of the opening
    out = [
        (x0 - fw, 0.0),
        (x1 + fw, 0.0),
        (x1 + fw, h + fw - ch * 0.4),
        (x1 + fw - ch - fw * 0.6, h + fw + 0.6),
        (x0 - fw + ch + fw * 0.6, h + fw + 0.6),
        (x0 - fw, h + fw - ch * 0.4),
    ]
    inner = [(x0, 0.0), (x1, 0.0), (x1, h - ch), (x1 - ch, h), (x0 + ch, h), (x0, h - ch)]
    frame_front = face + 1.4
    _frame_ring("SM_Hangar_DoorFrame", out, inner, -face + 0.02, -frame_front, PANEL_MID)
    glow_in = _offset_poly(inner, 0.45)
    glow_out = _offset_poly(inner, 0.85)
    _frame_ring(
        "SM_Hangar_DoorGlow",
        glow_out,
        glow_in,
        -frame_front + 0.04,
        -frame_front - 0.005,
        "M_Hangar_DoorGlow",
        bevel=0.0,
    )
    mb = kit.MeshBuilder()
    box(mb, x0 - fw - 0.6, x0 - fw, face, frame_front + 0.3, 0.0, h + 1.2, STEEL)
    box(mb, x1 + fw, x1 + fw + 0.6, face, frame_front + 0.3, 0.0, h + 1.2, STEEL)
    box(mb, x0 - fw - 0.6, x1 + fw + 0.6, face, face + 1.0, h + fw + 0.6, h + fw + 1.4, STEEL)
    _build(mb, "SM_Hangar_DoorJambs", bevel=0.015)
    leaves = kit.MeshBuilder()
    door_face = face - 0.6
    box(leaves, x0, x1, door_face - 0.2, door_face, 0.0, h, PANEL_DARK)
    for k in range(int(h / 1.2)):
        hz = 0.6 + k * 1.2
        box(leaves, x0 + 0.3, x1 - 0.3, door_face, door_face + 0.12, hz, hz + 0.32, STEEL)
    box(leaves, 49.92, 50.08, door_face, door_face + 0.16, 0.0, h, RECESS)
    _build(leaves, "SM_Hangar_DoorLeaves", bevel=0.01)


def _offset_poly(poly, d):
    """Offset a convex counter-clockwise (x, height) polygon outward by d."""
    n = len(poly)
    lines = []
    for i in range(n):
        (ax, ay), (bx, by) = poly[i], poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        ln = math.hypot(ex, ey)
        nx, ny = ey / ln, -ex / ln
        lines.append(((ax + nx * d, ay + ny * d), (ex, ey)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            out.append(p2)
            continue
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    # Keep the sill corners on the deck.
    return [(x, 0.0 if poly[i][1] <= 0.0 else y) for i, (x, y) in enumerate(out)]


def _frame_ring(name, outer, inner, y_back, y_front, material, bevel=0.02):
    """Solid between two (x, height) outlines with equal vertex counts, along Blender Y."""
    bm = bmesh.new()
    n = len(outer)
    rings_o = [[bm.verts.new((x, y, h)) for x, h in outer] for y in (y_back, y_front)]
    rings_i = [[bm.verts.new((x, y, h)) for x, h in inner] for y in (y_back, y_front)]

    def face(verts):
        if max(v.co.z for v in verts) < 1e-4:
            return  # faces lying on the deck would z-fight with the floor
        try:
            bm.faces.new(verts)
        except ValueError:
            pass

    for layer in (0, 1):
        for i in range(n):
            j = (i + 1) % n
            face((rings_o[layer][i], rings_o[layer][j], rings_i[layer][j], rings_i[layer][i]))
    for rings in (rings_o, rings_i):
        for i in range(n):
            j = (i + 1) % n
            face((rings[0][i], rings[0][j], rings[1][j], rings[1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(materials.get(material))
    obj = bpy.data.objects.new(name, mesh)
    scene.collection("Architecture").objects.link(obj)
    if bevel > 0:
        kit.bevel(obj, bevel)
    return obj


def _gantry_rail(face: float) -> None:
    """Crane rail girder along the whole wall on brackets every 7.2 m."""
    mb = kit.MeshBuilder()
    rz0 = 19.0
    box(mb, -2.0, L.WIDTH + 2.0, face + 0.9, face + 1.6, rz0, rz0 + 0.12, STEEL)
    box(mb, -2.0, L.WIDTH + 2.0, face + 1.2, face + 1.3, rz0 + 0.12, rz0 + 0.9, STEEL)
    box(mb, -2.0, L.WIDTH + 2.0, face + 0.9, face + 1.6, rz0 + 0.9, rz0 + 1.02, STEEL)
    box(mb, -2.0, L.WIDTH + 2.0, face + 1.15, face + 1.35, rz0 + 1.02, rz0 + 1.12, TRIM)
    for x in [i * 7.2 + 2.4 for i in range(14)]:
        mb.prism_x(
            [
                (-face, rz0 - 1.6),
                (-face, rz0 + 1.02),
                (-face - 1.3, rz0 + 1.02),
                (-face - 1.3, rz0 + 0.12),
            ],
            x - 0.18,
            x + 0.18,
            STEEL,
        )
    _build(mb, "SM_Hangar_GantryRail", bevel=0.008)


# --------------------------------------------------------------------------
# Side hull walls
# --------------------------------------------------------------------------

SIDE_CUT_H = 4.5


def side_walls() -> None:
    mb = kit.MeshBuilder()
    for x0, x1 in ((-2.0, L.SIDE_T), (L.WIDTH - L.SIDE_T, L.WIDTH + 2.0)):
        # Cut at room height over the flight deck so the section cap catches
        # the high-bay light; the cut faces are section caps.
        mb.box((x0, -L.FRONT_Z, 0.0), (x1, 0.0, SIDE_CUT_H), HULL)
        box(mb, x0, x1, 0.0, L.FRONT_Z, SIDE_CUT_H, SIDE_CUT_H + 0.02, CAP)
        box(mb, x0, x1, L.FRONT_Z - 0.02, L.FRONT_Z, 0.0, SIDE_CUT_H, CAP)
        # Cut at 1.1 m in the front band.
        box(mb, x0, x1, L.FRONT_Z, L.NEAR_WALL_Z[1], 0.0, L.CUT_H, PANEL_MID)
        box(mb, x0, x1, L.FRONT_Z, L.NEAR_WALL_Z[1], L.CUT_H, L.CUT_H + 0.02, CAP)
    _build(mb, "SM_Hangar_SideWalls", bevel=0.01)
    det = kit.MeshBuilder()
    for x_face, s in ((L.SIDE_T, 1), (L.WIDTH - L.SIDE_T, -1)):
        lo, hi = sorted((x_face, x_face + s * 0.25))
        box(det, lo, hi, L.WALL_FACE_Z, L.FRONT_Z, 0.0, 0.3, STEEL)
        for k, hz in enumerate((2.2, 2.6, 3.0)):
            xx = x_face + s * (0.18 + 0.02 * k)
            det.tube((xx, -L.WALL_FACE_Z, hz), (xx, -L.FRONT_Z + 0.2, hz), 0.08, "M_Hull_Pipe")
        for z in range(4, 46, 6):
            lo, hi = sorted((x_face, x_face + s * 0.6))
            box(det, lo, hi, z - 0.6, z + 0.6, 0.3, 2.1, PANEL_MID)
            lo, hi = sorted((x_face + s * 0.6, x_face + s * 0.62))
            box(det, lo, hi, z - 0.1, z + 0.1, 1.6, 1.7, "M_Indicator_Amber")
    _build(det, "SM_Hangar_SideDetail", bevel=0.006)


# --------------------------------------------------------------------------
# Launch well
# --------------------------------------------------------------------------


def launch_well(well_piece: bool = False) -> None:
    """Ventral launch shaft: deep and dark, framed inner walls, descending light rings.

    Art direction: a field is a faint translucent sheen, not a coloured slab;
    the shaft shows its structure near the top and falls away into darkness.
    """
    x0, x1, z0, z1 = L.WELL
    if well_piece:
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        with kit.into(scene.collection("Architecture")):
            kit.place(
                "SM_Hangar_LaunchWell", B(cx, cz, 0.0), 0.0, id="LaunchWell_2", room="flight_deck"
            )
        return
    d = L.WELL_DEPTH
    t = 0.6
    shell = kit.MeshBuilder()
    frames = kit.MeshBuilder()
    lamps = kit.MeshBuilder()
    box(shell, x0 - t, x1 + t, z0 - t, z0, -d, -0.6, PANEL_DARK)
    box(shell, x0 - t, x1 + t, z1, z1 + t, -d, -0.6, PANEL_DARK)
    box(shell, x0 - t, x0, z0, z1, -d, -0.6, PANEL_DARK)
    box(shell, x1, x1 + t, z0, z1, -d, -0.6, PANEL_DARK)
    box(shell, x0, x1, z0, z1, -d - 0.4, -d, HULL)
    # Vertical ribs on every inner face, 2.4 m apart.
    for x in [x0 + 1.2 + i * 2.4 for i in range(int((x1 - x0) / 2.4))]:
        box(frames, x - 0.14, x + 0.14, z0, z0 + 0.22, -d, -0.6, STEEL)
        box(frames, x - 0.14, x + 0.14, z1 - 0.22, z1, -d, -0.6, STEEL)
    for z in [z0 + 1.2 + i * 2.4 for i in range(int((z1 - z0) / 2.4))]:
        box(frames, x0, x0 + 0.22, z - 0.14, z + 0.14, -d, -0.6, STEEL)
        box(frames, x1 - 0.22, x1, z - 0.14, z + 0.14, -d, -0.6, STEEL)
    # Ring frames every 3 m down, each with a ring of small lamps on its lip.
    ring_w = 0.42
    for k in range(int((d - 2.0) / 4.5)):
        hz = -2.4 - 4.5 * k
        for a, b_, za, zb in ((x0, x1, z0, z0 + ring_w), (x0, x1, z1 - ring_w, z1)):
            box(frames, a, b_, za, zb, hz - 0.3, hz, STEEL)
        for za, zb in ((z0 + ring_w, z1 - ring_w),):
            box(frames, x0, x0 + ring_w, za, zb, hz - 0.3, hz, STEEL)
            box(frames, x1 - ring_w, x1, za, zb, hz - 0.3, hz, STEEL)
        n = int((x1 - x0) / 3.6)
        for i in range(n):
            lx = x0 + 1.8 + i * 3.6
            box(
                lamps,
                lx - 0.07,
                lx + 0.07,
                z0 + ring_w,
                z0 + ring_w + 0.02,
                hz - 0.2,
                hz - 0.1,
                "M_Hangar_ShaftLamp",
            )
        for z in [z0 + 3.0 + i * 3.0 for i in range(int((z1 - z0) / 3.0) - 1)]:
            box(
                lamps,
                x0 + ring_w,
                x0 + ring_w + 0.02,
                z - 0.07,
                z + 0.07,
                hz - 0.2,
                hz - 0.1,
                "M_Hangar_ShaftLamp",
            )
            box(
                lamps,
                x1 - ring_w - 0.02,
                x1 - ring_w,
                z - 0.07,
                z + 0.07,
                hz - 0.2,
                hz - 0.1,
                "M_Hangar_ShaftLamp",
            )
    _build(shell, "SM_Hangar_WellShaft", bevel=0.01, nav="none")
    _build(frames, "SM_Hangar_WellFrames", bevel=0.01, nav="none")
    lamps.bm.free()  # no lamp grid: the shaft falls to near-black (art direction)
    # Low kerb around the opening (tall enough to block the nav).
    kerb = kit.MeshBuilder()
    k = 0.45
    kh = 0.22
    box(kerb, x0 - k, x1 + k, z0 - k, z0, -0.6, kh, STEEL)
    box(kerb, x0 - k, x1 + k, z1, z1 + k, -0.6, kh, STEEL)
    box(kerb, x0 - k, x0, z0, z1, -0.6, kh, STEEL)
    box(kerb, x1, x1 + k, z0, z1, -0.6, kh, STEEL)
    _build(kerb, "SM_Hangar_WellKerb", bevel=0.012)
    # Field emitters: a slim dark rail inside the coaming, the sheet just below.
    rail = kit.MeshBuilder()
    box(rail, x0, x1, z0, z0 + 0.12, -0.5, -0.25, RECESS)
    box(rail, x0, x1, z1 - 0.12, z1, -0.5, -0.25, RECESS)
    box(rail, x0, x0 + 0.12, z0, z1, -0.5, -0.25, RECESS)
    box(rail, x1 - 0.12, x1, z0, z1, -0.5, -0.25, RECESS)
    _build(rail, "SM_Hangar_WellFieldRail", bevel=0.0, nav="none")
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    hx, hz_ = (x1 - x0) / 2, (z1 - z0) / 2
    field = kit.MeshBuilder()
    field.quad(
        [(-hx, -hz_, 0.0), (hx, -hz_, 0.0), (hx, hz_, 0.0), (-hx, hz_, 0.0)], "M_Hangar_FieldBlue"
    )
    obj = _build(field, "SM_Hangar_Field", bevel=0.0, nav="none")
    obj.location = B(cx, cz, -0.32)
    obj.visible_shadow = False
    fog = kit.MeshBuilder()
    fog.box((-hx, -hz_, -d + 0.2), (hx, hz_, -0.7), "M_Hangar_WellFog")
    obj = _build(fog, "SM_Hangar_WellFog", bevel=0.0, nav="none")
    obj.location = B(cx, cz, 0.0)


# --------------------------------------------------------------------------
# Front band: booth, crew bay, arrivals, lobby, armoury, near wall
# --------------------------------------------------------------------------


def front_band() -> None:
    cut = L.CUT_H
    walls = kit.MeshBuilder()
    caps = kit.MeshBuilder()

    def cut_wall(x0, x1, z0, z1, base=0.0, mat=PANEL_MID, top=None):
        top = base + cut if top is None else top
        box(walls, x0, x1, z0, z1, 0.0, top, mat)
        box(caps, x0, x1, z0, z1, top, top + 0.02, CAP)

    # Near hull wall (its outer face toward the camera is hull structure).
    nz0, nz1 = L.NEAR_WALL_Z
    box(walls, -2.0, L.WIDTH + 2.0, nz0 + 0.3, nz1, 0.0, cut, HULL)
    box(walls, -2.0, L.WIDTH + 2.0, nz0, nz0 + 0.3, 0.0, cut, PANEL_MID)
    box(caps, -2.0, L.WIDTH + 2.0, nz0, nz1, cut, cut + 0.02, CAP)
    # Booth: raised podium, window wall, side walls.
    bx0, bx1, bz0, _ = L.BOOTH
    bf = L.BOOTH_FLOOR
    cut_wall(bx0, bx0 + 0.3, bz0, nz0, base=bf)
    cut_wall(bx1 - 0.3, bx1, bz0, 53.4, base=bf)
    cut_wall(bx1 - 0.3, bx1, 57.6, nz0, base=bf)
    cut_wall(bx0, bx1, bz0, bz0 + 0.35, top=bf + 0.9)
    glass = kit.MeshBuilder()
    box(glass, bx0 + 0.3, bx1 - 0.3, bz0 + 0.12, bz0 + 0.2, bf + 0.9, bf + cut, "M_Glass_Viewport")
    _build(glass, "SM_Hangar_BoothGlazing", bevel=0.0)
    for x in [bx0 + 0.3 + i * 2.4 for i in range(10)]:
        box(walls, x - 0.06, x + 0.06, bz0 + 0.05, bz0 + 0.3, bf + 0.9, bf + cut, STEEL)
        box(caps, x - 0.06, x + 0.06, bz0 + 0.05, bz0 + 0.3, bf + cut, bf + cut + 0.02, CAP)
    # Armoury: north wall with a door gap, west wall.
    ax0, ax1, az0, _ = L.ARMOURY
    cut_wall(ax0, 78.6, az0, az0 + 0.3)
    cut_wall(81.2, ax1, az0, az0 + 0.3)
    cut_wall(ax0, ax0 + 0.3, az0, nz0)
    # Lobby / arrivals divider stub.
    cut_wall(L.LOBBY[0] - 0.15, L.LOBBY[0] + 0.15, 52.8, nz0)
    _build(walls, "SM_Hangar_FrontWalls", bevel=0.008)
    _build(caps, "SM_Hangar_FrontCaps", bevel=0.0)

    pod = kit.MeshBuilder()
    box(pod, bx0, bx1, bz0, nz0, -0.6, bf, "M_Floor_GlossBlack")
    _build(pod, "SM_Hangar_BoothPodium", bevel=0.006, nav="walk", room="booth")
    stair = kit.MeshBuilder()
    for i in range(6):
        top = 0.2 * (i + 1)
        sx1 = bx1 + 3.6 - 0.6 * i
        box(stair, sx1 - 0.6, sx1, 53.7, 57.3, -0.6, top, STEEL)
        box(stair, sx1 - 0.6, sx1 - 0.55, 53.7, 57.3, top - 0.01, top + 0.004, "M_Deck_Hazard")
    _build(stair, "SM_Hangar_BoothStair", bevel=0.006, nav="walk", room="crew_bay")
    rail = kit.MeshBuilder()
    for z in (53.6, 57.4):
        rail.tube(B(bx1 + 3.6, z, 1.0), B(bx1, z, 2.2), 0.03, TRIM)
        for x in (bx1 + 3.4, bx1 + 1.8):
            hgt = 0.2 * (bx1 + 3.6 - x) / 0.6
            rail.tube(B(x, z, hgt), B(x, z, hgt + 1.0), 0.025, TRIM)
    _build(rail, "SM_Hangar_BoothStairRail", bevel=0.0)
    lift_housing()


def lift_housing() -> None:
    """Deck-lift vestibule: two lift doors facing the camera, header light, roof plant."""
    x0, x1, z0, z1 = L.LIFT_HOUSING
    h = L.LIFT_HOUSING_H
    mb = kit.MeshBuilder()
    box(mb, x0, x1, z0, z1, 0.0, h, PANEL)
    box(mb, x0 - 0.1, x1 + 0.1, z0 - 0.1, z1 + 0.1, h - 0.3, h, STEEL)
    box(mb, x0 - 0.05, x1 + 0.05, z1 - 0.2, z1 + 0.05, 0.0, 0.25, STEEL)
    for x in (x0 + 0.25, x1 - 0.25):
        box(mb, x - 0.25, x + 0.25, z1 - 0.1, z1 + 0.12, 0.0, h - 0.3, STEEL)
    box(mb, x0 + 0.6, x1 - 0.6, z0 + 0.4, z1 - 0.6, h, h + 0.3, STEEL)
    box(mb, x0 + 1.2, x0 + 3.0, z0 + 0.6, z1 - 0.9, h + 0.3, h + 0.6, PANEL_MID)
    box(mb, x1 - 3.0, x1 - 1.2, z0 + 0.6, z1 - 0.9, h + 0.3, h + 0.6, PANEL_MID)
    _build(mb, "SM_Hangar_LiftHousing", bevel=0.012)
    doors = kit.MeshBuilder()
    lamps = kit.MeshBuilder()
    for cx in (68.0, 72.0):
        box(doors, cx - 1.25, cx + 1.25, z1, z1 + 0.06, 0.0, 2.9, STEEL)
        box(doors, cx - 1.0, cx - 0.01, z1 + 0.06, z1 + 0.1, 0.02, 2.6, PANEL_MID)
        box(doors, cx + 0.01, cx + 1.0, z1 + 0.06, z1 + 0.1, 0.02, 2.6, PANEL_MID)
        box(doors, cx - 1.0, cx + 1.0, z1 + 0.06, z1 + 0.1, 2.6, 2.75, RECESS)
        box(lamps, cx - 0.9, cx + 0.9, z1 + 0.1, z1 + 0.11, 2.63, 2.72, "M_Light_WallStrip")
        box(doors, cx + 1.35, cx + 1.6, z1 + 0.06, z1 + 0.12, 1.1, 1.5, RECESS)
        box(lamps, cx + 1.42, cx + 1.53, z1 + 0.12, z1 + 0.13, 1.32, 1.42, "M_Indicator_Green")
    box(lamps, x0 + 0.5, x1 - 0.5, z1 + 0.11, z1 + 0.12, 3.15, 3.45, "M_Light_WallStrip")
    _build(doors, "SM_Hangar_LiftDoors", bevel=0.006)
    _build(lamps, "SM_Hangar_LiftLamps", bevel=0.0)


# --------------------------------------------------------------------------
# Ceiling (camera-invisible): slab, girders, light bank frames
# --------------------------------------------------------------------------

CEILING_H = 21.0
BANK_XS = [7.2 + 14.4 * i for i in range(7)]
BANK_ZS = [9.6, 24.0, 38.4]
BANK_H = CEILING_H - 1.77


def ceiling() -> None:
    mb = kit.MeshBuilder()
    box(mb, -2.0, L.WIDTH + 2.0, -1.0, L.FRONT_Z, CEILING_H, CEILING_H + 0.4, "M_Ceiling_Panel")
    for z in [3.6 + 7.2 * i for i in range(7)]:
        box(mb, -2.0, L.WIDTH + 2.0, z - 0.4, z + 0.4, CEILING_H - 1.6, CEILING_H, STEEL)
    for x in [2.4 + 7.2 * i for i in range(14)]:
        box(mb, x - 0.3, x + 0.3, -1.0, L.FRONT_Z, CEILING_H - 1.0, CEILING_H, STEEL)
    # Lower ceilings of the front band rooms, with rows of light strips that
    # the polished black floors mirror.
    box(mb, -2.0, L.WIDTH + 2.0, L.FRONT_Z, L.NEAR_WALL_Z[1], 4.7, 5.0, "M_Ceiling_Panel")
    _build(mb, "SM_Hangar_Ceiling", bevel=0.0, collection="Ceiling")
    strips = kit.MeshBuilder()
    for x0, x1, h in (
        (L.BOOTH[0] + 1.0, L.BOOTH[1] - 1.0, L.BOOTH_FLOOR + 3.45),
        (L.CREW_BAY[0] + 0.6, L.CREW_BAY[1] - 0.6, 4.65),
        (L.ARRIVALS[0] + 0.6, L.LOBBY[1] - 0.6, 4.65),
        (L.ARMOURY[0] + 0.6, L.ARMOURY[1] - 0.6, 4.65),
    ):
        for z in (49.8, 54.6, 59.4):
            x = x0 + 1.2
            while x + 1.2 <= x1:
                strips.quad(
                    [
                        B(x - 0.6, z + 0.3, h),
                        B(x + 0.6, z + 0.3, h),
                        B(x + 0.6, z - 0.3, h),
                        B(x - 0.6, z - 0.3, h),
                    ],
                    "M_Hangar_RoomStrip",
                )
                x += 4.8
    obj = _build(strips, "SM_Hangar_RoomStrips", bevel=0.0, collection="Ceiling")
    obj.visible_shadow = False
    frames = kit.MeshBuilder()
    for x in BANK_XS:
        for z in BANK_ZS:
            box(
                frames,
                x - 0.35,
                x + 0.35,
                z - 2.7,
                z + 2.7,
                CEILING_H - 1.75,
                CEILING_H - 1.6,
                STEEL,
            )
    _build(frames, "SM_Hangar_LightBankFrames", bevel=0.0, collection="Ceiling")
    panels = kit.MeshBuilder()
    for x in BANK_XS:
        for z in BANK_ZS:
            panels.quad(
                [
                    B(x - 0.16, z + 2.5, BANK_H),
                    B(x + 0.16, z + 2.5, BANK_H),
                    B(x + 0.16, z - 2.5, BANK_H),
                    B(x - 0.16, z - 2.5, BANK_H),
                ],
                "M_Hangar_BankPanel",
            )
    obj = _build(panels, "SM_Hangar_LightBankPanels", bevel=0.0, collection="Ceiling")
    obj.visible_shadow = False
    for o in scene.objects_in("Ceiling"):
        o.visible_camera = False


# --------------------------------------------------------------------------
# Occluders (depth-only proxies for the runtime)
# --------------------------------------------------------------------------


def ucx(name, x0, x1, z0, z1, h0, h1):
    scene.add_ucx_box(name, (x0, -z1, h0), (x1, -z0, h1))


def occluders(well_piece: bool = False) -> None:
    face = L.WALL_FACE_Z
    ucx("hero_wall", -2.0, L.WIDTH + 2.0, -1.0, face, 0.0, L.WALL_TOP)
    for i, x in enumerate(PIER_XS):
        ucx(f"pier_{i + 1:02d}", x - 0.7, x + 0.7, face, L.PIER_FRONT_Z, 0.0, 15.2)
    ucx("door_frame_w", L.DOOR_X[0] - L.FRAME_W - 0.6, L.DOOR_X[0], face, face + 1.7, 0.0, 17.0)
    ucx("door_frame_e", L.DOOR_X[1], L.DOOR_X[1] + L.FRAME_W + 0.6, face, face + 1.7, 0.0, 17.0)
    ucx("side_w", -2.0, L.SIDE_T, 0.0, L.FRONT_Z, 0.0, SIDE_CUT_H)
    ucx("side_e", L.WIDTH - L.SIDE_T, L.WIDTH + 2.0, 0.0, L.FRONT_Z, 0.0, SIDE_CUT_H)
    ucx("side_w_cut", -2.0, L.SIDE_T, L.FRONT_Z, L.NEAR_WALL_Z[1], 0.0, L.CUT_H)
    ucx("side_e_cut", L.WIDTH - L.SIDE_T, L.WIDTH + 2.0, L.FRONT_Z, L.NEAR_WALL_Z[1], 0.0, L.CUT_H)
    ucx("near_wall", -2.0, L.WIDTH + 2.0, L.NEAR_WALL_Z[0], L.NEAR_WALL_Z[1], 0.0, L.CUT_H)
    bx0, bx1, bz0, _ = L.BOOTH
    bf = L.BOOTH_FLOOR
    ucx("booth_sill", bx0, bx1, bz0, bz0 + 0.35, 0.0, bf + L.CUT_H)
    ucx("booth_podium", bx0, bx1, bz0, L.NEAR_WALL_Z[0], 0.0, bf)
    ucx("booth_wall_w", bx0, bx0 + 0.3, bz0, L.NEAR_WALL_Z[0], 0.0, bf + L.CUT_H)
    ucx("booth_wall_e1", bx1 - 0.3, bx1, bz0, 53.4, 0.0, bf + L.CUT_H)
    ucx("booth_wall_e2", bx1 - 0.3, bx1, 57.6, L.NEAR_WALL_Z[0], 0.0, bf + L.CUT_H)
    ax0, ax1, az0, _ = L.ARMOURY
    ucx("armoury_wall_a", ax0, 78.6, az0, az0 + 0.3, 0.0, L.CUT_H)
    ucx("armoury_wall_b", 81.2, ax1, az0, az0 + 0.3, 0.0, L.CUT_H)
    ucx("armoury_wall_w", ax0, ax0 + 0.3, az0, L.NEAR_WALL_Z[0], 0.0, L.CUT_H)
    ucx("lobby_divider", L.LOBBY[0] - 0.15, L.LOBBY[0] + 0.15, 52.8, L.NEAR_WALL_Z[0], 0.0, L.CUT_H)
    x0, x1, z0, z1 = L.LIFT_HOUSING
    ucx("lift_housing", x0, x1, z0, z1 + 0.12, 0.0, L.LIFT_HOUSING_H + 0.6)
    if well_piece:
        return
    wx0, wx1, wz0, wz1 = L.WELL
    ucx("well_kerb_n", wx0 - 0.45, wx1 + 0.45, wz0 - 0.45, wz0, -0.6, 0.22)
    ucx("well_kerb_s", wx0 - 0.45, wx1 + 0.45, wz1, wz1 + 0.45, -0.6, 0.22)
