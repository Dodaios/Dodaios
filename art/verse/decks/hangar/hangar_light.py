"""Hangar lighting: every light is a fixture you can point at.

* High-bay banks under the ceiling (camera-invisible): area lights light the
  deck in soft pools; the diffuser panels only show in floor reflections.
* Flood lamps on the hero wall piers throw long pools onto the deck.
* The blast door's glow band and the pier strips are mesh emitters.
* The launch well's field glows faintly blue from below.
* The front band rooms have their own 4.7 m ceilings and fittings.

``POWER`` scales are the one place to rebalance the plate.
"""

from __future__ import annotations

import math

import hangar_arch as A
import hangar_layout as L
from lib import materials, scene
from mathutils import Vector

B = L.B

POWER = {
    "bank": 900.0,  # W per high-bay fill (broad area light along each fitting)
    "bank_focus": 3.0,  # multiplier for banks over the pad, walkway and aisles
    "flood": 26000.0,  # W per pier flood (spot)
    "field": 0.0,  # W, blue upward light inside the well
    "room": 460.0,  # W per front-band ceiling fitting
    "desk_key": 500.0,  # W spot over the arrivals desk
    "shuttle_spot": 9000.0,  # W ceiling spots that rim the shuttle
    "pool": 11000.0,  # W per high-bay spot over a work area
    "door_wash": 9000.0,  # W per ceiling washer on the blast door
}


@materials.material("M_Hangar_BankPanel", viewport=(1.0, 1.0, 1.0))
def _bank_panel(g) -> None:
    """Linear high-bay fitting seen only in reflections: two tubes behind a lens,
    dark end caps; the spot light under it does the lighting."""
    path = g.new("ShaderNodeLightPath")
    visible = g.math("MAXIMUM", path.outputs["Is Glossy Ray"], path.outputs["Is Camera Ray"])
    pos = g.coord("world", per_instance=False)
    cell = g.vmath("SNAP", pos, (14.4, 14.4, 100.0))
    rnd = g.white(cell)
    age = g.remap(rnd, 0.0, 1.0, 0.75, 1.0)
    co = g.coord("object", per_instance=False)
    x, y, _ = g.separate(co)
    lx = g.math(
        "SUBTRACT",
        g.math("FRACT", g.add(g.math("DIVIDE", g.math("SUBTRACT", x, 7.2), 14.4), 0.5)),
        0.5,
    )
    lx = g.mul(lx, 14.4)
    tubes = g.remap(
        g.math("ABSOLUTE", g.math("SUBTRACT", g.math("ABSOLUTE", lx), 0.075)),
        0.03,
        0.06,
        1.0,
        0.35,
        smooth=True,
    )
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], g.blackbody(6300.0))
    g.set(node.inputs["Strength"], g.mul(g.mul(visible, g.mul(age, tubes)), 11.0))
    g.output(node.outputs[0])
    materials._set_emission_sampling(g.mat, "NONE")


def _aim(obj, target) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _spot(name, location, target, power, size_deg, blend=0.5, kelvin=5800.0, radius=0.3):
    import bpy

    data = bpy.data.lights.new(name, "SPOT")
    data.energy = power
    data.spot_size = math.radians(size_deg)
    data.spot_blend = blend
    data.shadow_soft_size = radius
    data.use_temperature = True
    data.temperature = kelvin
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(location)
    _aim(obj, target)
    scene.collection("Lights").objects.link(obj)
    obj.visible_camera = False
    obj.visible_glossy = False
    return obj


def build(flood_mounts) -> None:
    # High-bay fittings: each throws a pool onto the plates; dark deck between.
    for x in A.BANK_XS:
        for z in A.BANK_ZS:
            edge = 0.6 if x < 10.0 or x > 90.0 else 1.0
            _spot(
                f"LT_HighBay_{int(x * 10):04d}_{int(z * 10):03d}",
                B(x, z, A.BANK_H - 0.12),
                B(x, z, 0.0),
                POWER["pool"] * edge,
                78.0,
                blend=1.0,
                kelvin=6200.0,
                radius=0.4,
            )
            fill = scene.add_area_light(
                f"LT_HighBayFill_{int(x * 10):04d}_{int(z * 10):03d}",
                B(x, z, A.BANK_H - 0.05),
                (2.4, 6.0),
                POWER["bank"] * edge,
                kelvin=6300.0,
                spread_deg=180.0,
            )
            fill.visible_camera = False
            fill.visible_glossy = False
    # Pier floods: aimed down and out across the deck.
    for i, (x, z, h) in enumerate(flood_mounts):
        tx = x + (2.0 if x < 50 else -2.0)
        _spot(
            f"LT_Flood_{i + 1:02d}",
            B(x, z + 0.4, h - 0.2),
            B(tx, z + 10.0, 0.0),
            POWER["flood"],
            34.0,
            blend=0.55,
            kelvin=5600.0,
            radius=0.35,
        )
    # Ceiling washers that graze the blast door leaves, so the ribs and stencils read.
    for x in (39.0, 61.0):
        _spot(
            f"LT_DoorWash_{int(x)}",
            B(x, 12.0, A.CEILING_H - 2.0),
            B(x + (50.0 - x) * 0.3, L.WALL_FACE_Z - 0.6, 8.0),
            POWER["door_wash"],
            44.0,
            blend=0.8,
            kelvin=6000.0,
            radius=0.5,
        )
    # Ceiling spots that rim the shuttle against the doors.
    cx, cz = L.SHUTTLE_C
    for sx in (-1, 1):
        _spot(
            f"LT_ShuttleRim_{'W' if sx < 0 else 'E'}",
            B(cx + sx * 14.0, cz - 6.0, 19.0),
            B(cx + sx * 1.5, cz - 1.0, 4.0),
            POWER["shuttle_spot"],
            34.0,
            blend=0.8,
            kelvin=6200.0,
            radius=0.6,
        )
    # The field's faint glow on its surroundings (above the sheet, so the shaft
    # below stays dark).
    x0, x1, z0, z1 = L.WELL
    field = scene.add_area_light(
        "LT_WellField",
        B((x0 + x1) / 2, (z0 + z1) / 2, -0.2),
        (x1 - x0 - 0.6, z1 - z0 - 0.6),
        POWER["field"],
        kelvin=6500.0,
        rotation_deg=(180.0, 0.0, 0.0),
    )
    field.data.use_temperature = False
    field.data.color = (0.35, 0.6, 1.0)
    field.visible_camera = False
    field.visible_glossy = False
    # Grazing wash inside the coaming: shows the shaft's upper frames, which then
    # fall away into the dark.
    wash = scene.add_area_light(
        "LT_WellWash", B((x0 + x1) / 2, z0 + 0.7, -0.9), (x1 - x0 - 1.0, 0.4), 250.0, kelvin=6500.0
    )
    wash.visible_camera = False
    wash.visible_glossy = False
    _front_band()


def _front_band() -> None:
    rooms = {
        "booth": ([6.0, 11.0, 16.0, 21.0], [50.0, 56.0], L.BOOTH_FLOOR + 3.4, 6000.0),
        "crew": ([28.6, 36.0], [50.0, 57.0], 4.6, 5600.0),
        "arrivals": ([44.0, 50.0, 56.0], [49.0, 55.6], 4.6, 5800.0),
        "lobby": ([66.0, 73.0], [53.6, 58.6], 4.6, 6000.0),
        "armoury": ([82.0, 88.0, 94.0], [50.6, 56.6], 4.6, 6200.0),
    }
    for key, (xs, zs, h, kelvin) in rooms.items():
        for x in xs:
            for z in zs:
                light = scene.add_area_light(
                    f"LT_Room_{key}_{int(x)}_{int(z)}",
                    B(x, z, h),
                    (2.4, 0.6),
                    POWER["room"],
                    kelvin=kelvin,
                    spread_deg=120.0,
                )
                light.visible_camera = False
                light.visible_glossy = False
    dx, dz = L.DESK_C
    _spot(
        "LT_DeskKey",
        B(dx, dz + 2.6, 4.6),
        B(dx, dz - 0.4, 1.0),
        POWER["desk_key"],
        48.0,
        blend=0.6,
        kelvin=5600.0,
        radius=0.25,
    )
