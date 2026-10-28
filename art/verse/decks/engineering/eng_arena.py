"""The Reactor Shaft hall dressed as the duel arena (combat/arenaReactor.ts).

PR #1021 fitted out the rest of the engineering deck and left this hall
alone; at eye level it read as a dim, empty grey box around a warm core.
This module makes it the deck's set piece, with the same kits
(``kit.architecture.cladding``, ``kit.props.fitout``):

* **Energy column.** A cold white-blue beam rises from the core's aperture
  to an injector hung in the ceiling plenum, inside a sheath of light and a
  stack of containment rings whose glow steps up the column (a frozen
  pulse), held by four rails. Three cold point lights make it the hall's key
  light. Ceiling ghosts: the plate keeps its top-down read of the core.
* **Cover** (``Props``, nav ``block``; each one has a collider of the same
  name in arenaReactor.ts), mirrored about both axes: four coolant-tank
  pairs flanking the spawns (tall cover in the core's sight shadow) and four
  chest-high blast barriers on the north and south walks.
* **Edges.** Guard rails with hazard kick plates along both sides of every
  catwalk and round the drop between them, hazard bands across each catwalk
  entry, beacon posts at the catwalk heads.
* **Walls and overhead** (ghosts): the east wall in the hall cladding with
  light columns, heat vents and status boards; flood fixtures high on the
  walls, raking the floor (spot lights) so pools of light alternate with
  dark; red warning beacons; two insulated coolant mains on a pipe bridge
  across the ceiling.

Everything stays clear of the duel consoles on the control ring, of the
spawns (38.8, 22) and (69.2, 22) and of the lines the combat tests shoot
along (the x 38.8 column of the west floor, the catwalk axes, the doorways).
"""

from __future__ import annotations

import math

import bpy
import eng_common as c
from eng_common import Geo, build_into, deck_material, shaft_point
from kit.architecture import cladding as C
from kit.props import fitout as F
from kit.props.industrial._mats import m
from lib import kit, scene
from mathutils import Matrix, Vector

ROOM = "reactor"
GUNMETAL = "M_Struct_Gunmetal"
STEEL = "M_Trim_BrushedSteel"
DARK = "M_Wall_PaintedDark"
RECESS = "M_Recess_Dark"
HAZARD = "M_Paint_Hazard"
PIPE_INS = "M_Hull_PipeInsulated"
PIPE = "M_Hull_Pipe"
BEAM = "M_Eng_EnergyBeam"
SHEATH = "M_Eng_EnergySheath"
RING_GLOW = "M_Eng_EnergyRing"
BEACON = "M_Eng_BeaconRed"
BEACON_AMBER = "M_Indicator_Amber"

SX, SZ = c.SHAFT_C
COLUMN_TOP = c.HALL_H + 3.4  # into the plenum (eng_upper.shaft_plenum)
BEAM_R = 0.7
SHEATH_R = 1.05  # the light filaments round the beam
RING_R = (1.3, 1.68)
RAIL_R = 1.8

# ---------------------------------------------------------------- cover
# Plan (x, z) centres. Keep in step with the colliders in
# dodaios/ui/web/frontend/src/components/society/verse/combat/arenaReactor.ts.
# Tall cover flanks each spawn inside the core's sight shadow: from the other
# spawn the core hides it, so it shelters a player without becoming a
# pre-aimed hold on the far spawn (on the diagonals it did: the "watcher"
# trick then beat the hard bot, docs/verse/combat.md).
TANK_PAIRS = (  # (id, x, z, yaw): sight glasses toward the shaft
    ("tanks_nw", 35.6, 17.2, 90.0),
    ("tanks_sw", 35.6, 26.8, 90.0),
    ("tanks_ne", 72.4, 17.2, -90.0),
    ("tanks_se", 72.4, 26.8, -90.0),
)
TANK_HALF = (1.4, 0.75)  # footprint half sizes (along, across)
TANK_H = 2.7
BARRIERS = (  # (id, x, z, yaw): chest-high blast barriers on the north and south walks
    ("barrier_nw", 46.8, 8.1, 0.0),
    ("barrier_ne", 61.2, 8.1, 0.0),
    ("barrier_sw", 46.8, 35.9, 180.0),
    ("barrier_se", 61.2, 35.9, 180.0),
)
BARRIER_HALF = (1.2, 0.3)
BARRIER_H = 1.2


# ---------------------------------------------------------------- materials


@deck_material(BEAM, viewport=(0.85, 0.92, 1.0))
def _energy_beam(g) -> None:
    """The column's core: cold white-blue, streaming streaks along its length
    and slow brighter bands (a pulse caught mid-climb)."""
    co = g.coord("object", per_instance=False)
    _, _, height = g.separate(co)
    streak = g.noise(g.vmath("MULTIPLY", co, (2.2, 2.2, 0.08)), 2.0, detail=4, rough=0.65)
    hot = g.remap(streak, 0.42, 0.68, 0.0, 1.0, smooth=True)
    wave = g.remap(g.math("SINE", g.mul(height, 1.6)), -1.0, 1.0, 0.0, 1.0)
    pulse = g.add(0.65, g.mul(g.math("POWER", wave, 6.0), 1.3))
    tint = g.mix_color(hot, (0.16, 0.38, 1.0), (0.7, 0.85, 1.0))
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], tint)
    g.set(node.inputs["Strength"], g.mul(g.mul(pulse, g.add(0.35, hot)), 5.0))
    g.output(node.outputs[0])
    g.mat.cycles.emission_sampling = "FRONT"


@deck_material(SHEATH, viewport=(0.45, 0.62, 1.0))
def _energy_sheath(g) -> None:
    """The glow round the beam: a thin blue field, brighter in rising bands,
    never a flat coloured slab (ART_DIRECTION: a field is a faint sheen)."""
    co = g.coord("object", per_instance=False)
    _, _, height = g.separate(co)
    flow = g.noise(g.vmath("MULTIPLY", co, (1.6, 1.6, 0.22)), 1.4, detail=4, rough=0.55)
    band = g.remap(g.math("SINE", g.add(g.mul(height, 1.3), 0.6)), -1.0, 1.0, 0.45, 1.0)
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], (0.36, 0.58, 1.0))
    g.set(node.inputs["Strength"], g.mul(g.mul(band, g.add(0.5, flow)), 4.0))
    g.output(node.outputs[0])
    g.mat.cycles.emission_sampling = "FRONT"


@deck_material(RING_GLOW, viewport=(0.7, 0.85, 1.0))
def _energy_ring(g) -> None:
    """Inner faces of the containment rings: each ring at its own intensity
    (by height), so the column reads as pulsing upward."""
    co = g.coord("object", per_instance=False)
    _, _, height = g.separate(co)
    step = g.math("FRACT", g.mul(height, 0.27))
    level = g.remap(g.math("POWER", step, 2.2), 0.0, 1.0, 1.5, 14.0)
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], g.mix_color(step, (0.42, 0.62, 1.0), (0.85, 0.93, 1.0)))
    g.set(node.inputs["Strength"], level)
    g.output(node.outputs[0])
    g.mat.cycles.emission_sampling = "FRONT"


@deck_material(BEACON, viewport=(0.9, 0.04, 0.02))
def _beacon_red(g) -> None:
    """Warning beacon dome: a deep signal red that stays red, not pink, at
    the hall's exposure (the library's red lamps bloom toward white)."""
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], (1.0, 0.03, 0.015))
    g.set(node.inputs["Strength"], 1.2)
    g.output(node.outputs[0])
    g.mat.cycles.emission_sampling = "NONE"


# ---------------------------------------------------------------- helpers


def _light(
    name: str, kind: str, location, power: float, color, *, radius: float = 0.1,
    target=None, cone_deg: float = 60.0, blend: float = 0.6,
) -> bpy.types.Object:  # fmt: skip
    """A Cycles point or spot light in the deck's Lights collection, a spot
    aimed at the Blender point ``target``."""
    data = bpy.data.lights.new(name, kind)
    data.energy = power
    data.color = color
    data.shadow_soft_size = radius
    if kind == "SPOT":
        data.spot_size = math.radians(cone_deg)
        data.spot_blend = blend
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(location)
    if target is not None:
        direction = Vector(target) - Vector(location)
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    obj.visible_camera = False
    scene.collection("Lights").objects.link(obj)
    return obj


def _ghost_builders(prefix: str, B: C.Builders) -> None:
    with kit.into(scene.collection("Ceiling")), kit.ghost(-1.0):
        B.finish(prefix, room=ROOM)


# ---------------------------------------------------------------- energy column


def energy_column() -> None:
    """Beam, sheath, containment rings and rails from the core's aperture to
    the injector in the ceiling plenum (ghosts), and its key lights."""
    beam, glow, metal = Geo(), Geo(), Geo()
    y0 = 1.25
    beam.sector(0.0, BEAM_R, y0, COLUMN_TOP - 1.0, BEAM, segments=40)
    for k in range(16):  # field filaments
        px, py, _ = shaft_point(SHEATH_R, k * 22.5 + 11.25)
        glow.box((px - 0.025, py - 0.025, 2.6), (px + 0.025, py + 0.025, c.HALL_H - 1.2), SHEATH)
    # Focusing collar seated on the core head's grate.
    metal.sector(SHEATH_R + 0.05, 2.2, 1.95, 2.25, GUNMETAL, segments=48)
    metal.sector(SHEATH_R + 0.05, 1.85, 2.25, 2.7, GUNMETAL, segments=48, inner=RING_GLOW)
    metal.sector(1.85, 1.89, 2.36, 2.56, RING_GLOW, segments=48)
    # Containment rings: gunmetal outside, glowing inside.
    y = 3.4
    while y < c.HALL_H - 1.2:
        metal.sector(RING_R[0], RING_R[1], y, y + 0.26, GUNMETAL, segments=48, inner=RING_GLOW)
        metal.sector(RING_R[1], RING_R[1] + 0.03, y + 0.09, y + 0.17, RING_GLOW, segments=48)
        y += 0.8 if y < 4.5 else 1.0
    # Four rails on the diagonals, collar to injector, with clamp blocks.
    for i in range(4):
        a = 45.0 + 90.0 * i
        px, py, _ = shaft_point(RAIL_R, a)
        metal.box((px - 0.09, py - 0.09, 2.25), (px + 0.09, py + 0.09, c.HALL_H - 1.0),
                  GUNMETAL)  # fmt: skip
        qx, qy, _ = shaft_point(RAIL_R + 0.12, a)
        for yc in (2.9, 5.5, 8.1):
            metal.box((qx - 0.12, qy - 0.12, yc), (qx + 0.12, qy + 0.12, yc + 0.35), STEEL)
    # Injector: a ribbed drum hung from the plenum cap, a glowing throat below.
    top = COLUMN_TOP
    metal.sector(0.0, 2.6, c.HALL_H - 1.2, c.HALL_H - 0.7, GUNMETAL, segments=48, inner=RING_GLOW)
    metal.sector(0.0, 2.3, c.HALL_H - 0.7, top, DARK, segments=48)
    metal.sector(2.3, 2.42, c.HALL_H - 0.4, top - 0.4, GUNMETAL, segments=48)
    for k in range(16):
        a = k * 22.5
        metal.sector(2.3, 2.55, c.HALL_H - 0.7, top, GUNMETAL, a0=a - 1.4, a1=a + 1.4, segments=2)
    glow.sector(1.0, 1.9, c.HALL_H - 1.22, c.HALL_H - 1.2, RING_GLOW, segments=48)
    for i in range(4):  # stays from the drum to the plenum wall
        a = 90.0 * i
        p0 = shaft_point(2.4, a, c.HALL_H + 1.4)
        p1 = shaft_point(c.SHAFT_R + 0.8, a, c.HALL_H + 2.6)
        metal.tube(p0, p1, 0.16, GUNMETAL, 10)
    with kit.ghost(-1.0):
        for geo, name in ((beam, "Beam"), (glow, "Glow"), (metal, "Frame")):
            obj = build_into("Ceiling", geo, f"SM_Eng_Arena_Column{name}", bevel_width=0.0)
            if obj is not None:
                kit.tag(obj, room=ROOM)
                if geo is not metal:
                    obj.visible_shadow = False
    cold = (0.62, 0.78, 1.0)
    for k, (h, power) in enumerate(((3.4, 7000.0), (6.6, 6000.0), (9.8, 5000.0))):
        _light(f"LT_Arena_Column_{k}", "POINT", c.b(SX, SZ, h), power, cold, radius=0.6)


# ---------------------------------------------------------------- cover


def _tank_pair(name: str, x: float, z: float, yaw: float) -> None:
    B = C.Builders().at(C.place_matrix(x, z, yaw))
    hu, hv = TANK_HALF
    C.box(B.struct, -hu, hu, -hv, hv, 0.0, 0.08, GUNMETAL)  # steel skid
    for k in (-0.9, 0.0, 0.9):
        C.box(B.struct, k - 0.06, k + 0.06, -hv - 0.02, hv + 0.02, 0.0, 0.09, STEEL)
    for i, u in enumerate((-0.68, 0.68)):
        F.coolant_tank(B, u, 0.0, r=0.52, h=TANK_H, seed=(name, i))
    # Cross-feed between the tanks with a valve and a red-capped beacon mast.
    B.pipes.tube((-0.68, 0.0, 2.25), (0.68, 0.0, 2.25), 0.08, PIPE, 12)
    F.valve_wheel(B, 0.0, 0.18, 2.25, red=True)
    B.struct.tube((0.0, 0.0, 2.25), (0.0, 0.0, TANK_H + 0.35), 0.035, GUNMETAL, 8)
    B.struct.tube((0.0, 0.0, TANK_H + 0.35), (0.0, 0.0, TANK_H + 0.42), 0.09, GUNMETAL, 14)
    B.lamps.tube((0.0, 0.0, TANK_H + 0.42), (0.0, 0.0, TANK_H + 0.56), 0.07, BEACON, 14)
    C.box(B.struct, -0.3, 0.3, hv - 0.06, hv, 0.9, 1.5, DARK)  # local control box
    C.box(B.lamps, -0.22, 0.22, hv, hv + 0.004, 1.2, 1.42, "M_Screen")
    C.box(B.lamps, 0.12, 0.2, hv, hv + 0.006, 1.02, 1.08, BEACON_AMBER)
    with kit.into(scene.collection("Props")):
        B.finish(f"SM_Eng_Arena_{name}", room=ROOM, nav="block")
    hx, hz = (hu, hv) if abs(math.sin(math.radians(yaw))) < 0.5 else (hv, hu)
    c.ucx3(f"arena_{name}", x - hx, x + hx, z - hz, z + hz, 0.0, TANK_H)


def _barrier(name: str, x: float, z: float, yaw: float) -> None:
    """Blast barrier: a heavy sloped steel block on feet, hazard chevrons on
    both faces, a bolted cap and a dim amber lamp on the ends."""
    B = C.Builders().at(C.place_matrix(x, z, yaw))
    hu, hv = BARRIER_HALF
    h = BARRIER_H
    for s in (-1, 1):  # feet
        C.box(B.struct, s * hu - 0.18 * s - 0.16, s * hu - 0.18 * s + 0.16, -hv - 0.08, hv + 0.08,
              0.0, 0.1, GUNMETAL)  # fmt: skip
    B.struct.prism_x([(-hv, 0.1), (hv, 0.1), (hv - 0.08, h - 0.08), (-hv + 0.08, h - 0.08)],
                     -hu, hu, DARK)  # fmt: skip
    C.box(B.struct, -hu - 0.02, hu + 0.02, -hv + 0.04, hv - 0.04, h - 0.08, h, GUNMETAL)
    for su in (-1, 1):
        for k in range(5):
            u = su * (0.2 + k * 0.22)
            C.box(B.flat, u - 0.02, u + 0.02, -hv + 0.06, hv - 0.06, h, h + 0.012, STEEL)
    for sv in (-1, 1):  # hazard bands near the top of each face
        v0 = sv * (hv - 0.06)
        a, b = sorted((v0, v0 + sv * 0.012))
        F.hazard_band(B, -hu + 0.1, hu - 0.1, a, b, h - 0.42, h - 0.16)
    for u0, u1 in ((hu, hu + 0.006), (-hu - 0.006, -hu)):  # amber end lamps
        C.box(B.lamps, u0, u1, -0.08, 0.08, h - 0.3, h - 0.18, BEACON_AMBER)
    with kit.into(scene.collection("Props")):
        B.finish(f"SM_Eng_Arena_{name}", room=ROOM, nav="block")
    hx, hz = (hu, hv) if abs(math.sin(math.radians(yaw))) < 0.5 else (hv, hu)
    c.ucx3(f"arena_{name}", x - hx, x + hx, z - hz, z + hz, 0.0, h)


def cover() -> None:
    for name, x, z, yaw in TANK_PAIRS:
        _tank_pair(name, x, z, yaw)
    for name, x, z, yaw in BARRIERS:
        _barrier(name, x, z, yaw)


# ---------------------------------------------------------------- edges


def _polar_frame(angle_deg: float) -> Matrix:
    """(u, v, h) -> Blender with u radial from the shaft axis at ``angle_deg``
    (Blender polar: 0 = east, 90 = north) and v to its left."""
    return Matrix.Translation((SX, -SZ, 0.0)) @ Matrix.Rotation(math.radians(angle_deg), 4, "Z")


def edges() -> None:
    """Catwalk rails, the rim rail round the drop, hazard bands and beacon
    posts at the catwalk heads."""
    B = C.Builders()
    half = c.CATWALK_W / 2 - 0.04
    for a in c.CATWALK_ANGLES:
        B.at(_polar_frame(a))
        for v in (-half, half):
            F.guard_rail(B, c.RING_R[1] + 0.45, c.SHAFT_R - 0.2, v, 0.02, height=1.05)
        F.hazard_band(B, c.SHAFT_R - 0.05, c.SHAFT_R + 0.3, -half, half, 0.0, 0.004)
        F.hazard_band(B, c.RING_R[1] - 0.05, c.RING_R[1] + 0.25, -half, half, 0.0, 0.004)
        for v in (-1.0, 1.0):  # beacon posts either side of the catwalk head
            u = c.SHAFT_R + 0.25
            B.struct.tube((u, v, 0.12), (u, v, 1.35), 0.045, GUNMETAL, 10)
            B.struct.tube((u, v, 1.35), (u, v, 1.42), 0.085, GUNMETAL, 14)
            B.lamps.tube((u, v, 1.42), (u, v, 1.55), 0.065, BEACON, 14)
    # Rim rail between the catwalks, on the kerb's top.
    r = c.SHAFT_R + 0.06  # on the kerb's inner lip: a body at the edge barely touches it
    gap = math.degrees(math.asin(1.0 / r))
    angles = sorted(c.CATWALK_ANGLES)
    B.at(Matrix.Translation((SX, -SZ, 0.0)))
    for i, a in enumerate(angles):
        b = angles[(i + 1) % len(angles)] + (360.0 if i == len(angles) - 1 else 0.0)
        a0, a1 = a + gap, b - gap
        n = max(2, round(math.radians(a1 - a0) * r / 1.4))
        pts = [a0 + (a1 - a0) * k / n for k in range(n + 1)]
        top, knee = [], []
        for k, ang in enumerate(pts):
            x, y = r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))
            B.struct.box((x - 0.03, y - 0.03, 0.12), (x + 0.03, y + 0.03, 1.17), GUNMETAL)
            top.append((x, y, 1.17))
            knee.append((x, y, 0.66))
            if k < n:
                nx = r * math.cos(math.radians(pts[k + 1]))
                ny = r * math.sin(math.radians(pts[k + 1]))
                # Hazard kick plate segment between this post and the next.
                d = Vector((nx - x, ny - y, 0.0))
                side = Vector((-d.y, d.x, 0.0)).normalized() * 0.008
                corners = [Vector((x, y, 0.12)) + side, Vector((nx, ny, 0.12)) + side,
                           Vector((nx, ny, 0.12)) - side, Vector((x, y, 0.12)) - side]  # fmt: skip
                B.flat.prism_z([(p.x, p.y) for p in corners], 0.12, 0.26, HAZARD)
        B.struct.polyline_tube(top, 0.026, STEEL, 8)
        B.struct.polyline_tube(knee, 0.018, GUNMETAL, 6)
    with kit.into(scene.collection("Props")):
        B.finish("SM_Eng_Arena_Rails", room=ROOM, nav="none")


# ---------------------------------------------------------------- walls and overhead


def east_wall() -> None:
    """The east wall in the hall cladding, with fittings (ghosts)."""
    x_face = c.EAST_HULL_X[0]
    t0, t1 = c.FAR_WALL_Z + 0.4, c.GALLERY_NORTH_Z[0] - 0.3
    B = C.Builders().at(C.run_matrix("z", x_face, -1))
    seed = ("eng-arena", "east")
    ribs = C.rib_stations(t0, t1, 4.8, origin=SZ + 2.4)
    lit = {i for i in range(len(ribs) + 1) if i % 2 == 0}
    bays = C.hall_wall(B, seed, t0, t1, top=c.HALL_H, ribs=ribs, lit_bays=lit,
                       lit_upper={i for i in lit if i % 4 == 0}, red_ribs={1, 4})  # fmt: skip
    for bi, (a, b) in enumerate(bays):
        cu = (a + b) / 2
        off = 0.8 if bi in lit else 0.0
        if bi % 2:
            F.heat_vent(B, cu, 0.4, w=1.2, h=0.7)
            C.status_panel(B, cu, 1.55, seed=(seed, bi))
        else:
            C.junction_box(B, cu + off, 1.3, seed=(seed, bi))
            C.conduit_drop(B, cu + off, 1.8, 2.73, n=2)
        C.box(B.struct, cu - 0.6, cu + 0.6, 0.0, 0.2, 6.2, 6.5, GUNMETAL)  # beacon shelf
        B.lamps.tube((cu, 0.12, 6.5), (cu, 0.12, 6.68), 0.08, BEACON, 14)
    _ghost_builders("SM_Eng_Arena_EastWall", B)


def south_wall() -> None:
    """The hall face of the gallery wall: tall light columns between the
    three blast doors, the rail and conduits above their heads (ghosts)."""
    z_face = c.GALLERY_NORTH_Z[0]
    t0, t1 = c.PARTITION_X[1] + 0.3, c.EAST_HULL_X[0] - 0.3
    B = C.Builders().at(C.run_matrix("x", z_face, -1))
    seed = ("eng-arena", "south")
    doors = [(x - 1.8, x + 1.8) for x in c.GALLERY_OPENINGS]
    ribs = [r for r in C.rib_stations(t0, t1, 4.8, origin=SX + 2.4)
            if not any(a - 0.5 < r < b + 0.5 for a, b in doors)]  # fmt: skip
    bands = C.Bands(lower=(0.33, 4.62), rail=(4.62, 4.77), conduit=(4.77, 5.25))
    edges_ = [t0, *ribs, t1]
    spans = list(zip(edges_[:-1], edges_[1:], strict=True))
    def clear(a: float, b: float) -> bool:
        return b - a > 2.4 and not any(da - 0.6 < (a + b) / 2 < db + 0.6 for da, db in doors)

    lit = {i for i, (a, b) in enumerate(spans) if clear(a, b)}
    bays = C.hall_wall(B, seed, t0, t1, top=c.HALL_H, ribs=ribs, bands=bands, lit_bays=lit,
                       lit_upper=set(), red_ribs={0, 3, 6},
                       openings=[C.Opening(a, b, 4.62) for a, b in doors])  # fmt: skip
    for bi, (a, b) in enumerate(bays):
        cu = (a + b) / 2
        if b - a < 1.6 or any(da - 0.7 < cu < db + 0.7 for da, db in doors):
            continue
        off = 0.85 if bi in lit else 0.0
        F.heat_vent(B, cu - off, 0.4, w=0.9, h=0.6)
        C.status_panel(B, cu + off, 1.5, seed=(seed, bi))
    _ghost_builders("SM_Eng_Arena_SouthWall", B)


FLOODS = (  # (plan x, z, height, aim x, aim z): fixtures high on the walls
    (81.7, 9.0, 9.2, 70.0, 12.5),
    (81.7, 35.0, 9.2, 70.0, 31.5),
    (33.3, 9.0, 9.2, 41.0, 13.0),
    (33.3, 35.0, 9.2, 41.0, 31.0),
    (46.8, 37.8, 9.4, 46.8, 30.5),
    (61.2, 37.8, 9.4, 61.2, 30.5),
    (46.8, 2.6, 10.6, 46.8, 9.5),
    (61.2, 2.6, 10.6, 61.2, 9.5),
)
BEACONS = (  # (plan x, z, height): red warning beacons on the walls
    (33.3, 16.0, 5.4), (33.3, 28.0, 5.4), (42.0, 37.8, 5.6), (66.0, 37.8, 5.6),
)  # fmt: skip


def lights_and_fixtures() -> None:
    """Flood heads and beacons on the walls (ghosts) and their Cycles lights."""
    geo = Geo()
    lamps = Geo()
    for i, (x, z, h, ax, az) in enumerate(FLOODS):
        p = Vector(c.b(x, z, h))
        aim = Vector(c.b(ax, az, 0.0))
        d = (aim - p).normalized()
        head = p + d * 0.35
        geo.tube(p, head, 0.24, GUNMETAL, 16)
        lamps.tube(head, head + d * 0.02, 0.2, m("lamp_flood"), 16)
        wall = Vector((p.x, p.y, p.z)) - Vector((d.x, d.y, 0.0)).normalized() * 0.3
        geo.tube(wall, p, 0.06, GUNMETAL, 8)
        _light(f"LT_Arena_Flood_{i}", "SPOT", head + d * 0.05, 2200.0, (0.86, 0.92, 1.0),
               radius=0.12, target=aim, cone_deg=46.0, blend=0.55)  # fmt: skip
    for i, (x, z, h) in enumerate(BEACONS):
        p = Vector(c.b(x, z, h))
        geo.tube(p - Vector((0, 0, 0.12)), p, 0.1, GUNMETAL, 14)
        lamps.tube(p, p + Vector((0, 0, 0.16)), 0.075, BEACON, 14)
        _light(f"LT_Arena_Beacon_{i}", "POINT", p + Vector((0, 0, 0.1)), 40.0,
               (1.0, 0.08, 0.04), radius=0.06)  # fmt: skip
    # The tank pairs' and catwalk heads' beacons throw a little red too.
    for name, x, z, _ in TANK_PAIRS:
        _light(f"LT_Arena_{name}_beacon", "POINT", c.b(x, z, TANK_H + 0.6), 18.0,
               (1.0, 0.08, 0.04), radius=0.05)  # fmt: skip
    with kit.ghost(-1.0):
        for g, name in ((geo, "Fixtures"), (lamps, "FixtureLamps")):
            obj = build_into("Ceiling", g, f"SM_Eng_Arena_{name}", bevel_width=0.0)
            if obj is not None:
                kit.tag(obj, room=ROOM)
                if g is lamps:
                    obj.visible_shadow = False


def overhead() -> None:
    """Two insulated coolant mains across the hall at 10.6 m on a pipe bridge
    over the plenum opening, hung from the ceiling elsewhere (ghosts)."""
    geo = Geo()
    x0, x1 = c.PARTITION_X[1] + 0.2, c.EAST_HULL_X[0] - 0.2
    h = 10.6
    opening = c.SHAFT_R + 1.0
    for z in (14.6, 29.4):
        for dz, r in ((-0.35, 0.36), (0.45, 0.24)):
            geo.tube(c.b(x0, z + dz, h), c.b(x1, z + dz, h), r, PIPE_INS if r > 0.3 else PIPE, 20)
        x = x0 + 1.0
        while x < x1:
            geo.tube(c.b(x - 0.1, z - 0.35, h), c.b(x + 0.1, z - 0.35, h), 0.42, GUNMETAL, 20)
            x += 4.8
        # Bridge girders under the mains across the opening, hangers elsewhere.
        dz = abs(z - SZ)
        half = math.sqrt(max(opening**2 - dz * dz, 0.0)) + 1.0
        geo.box3(SX - half, SX + half, z - 0.7, z + 0.85, h - 0.62, h - 0.4, GUNMETAL)
        for xb in (SX - half, SX + half):
            geo.box3(xb - 0.12, xb + 0.12, z - 0.7, z + 0.85, h - 0.62, c.HALL_H, GUNMETAL)
        x = x0 + 2.4
        while x < x1:
            if abs(x - SX) > half:
                for zz in (z - 0.35, z + 0.45):
                    geo.box3(x - 0.03, x + 0.03, zz - 0.03, zz + 0.03, h, c.HALL_H, STEEL)
            x += 2.4
    with kit.ghost(-1.0):
        obj = build_into("Ceiling", geo, "SM_Eng_Arena_Mains", bevel_width=0.0)
        if obj is not None:
            kit.tag(obj, room=ROOM)


def build() -> None:
    energy_column()
    cover()
    edges()
    east_wall()
    south_wall()
    lights_and_fixtures()
    overhead()
