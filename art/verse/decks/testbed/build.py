"""Testbed deck: a lit graybox room that exercises every pipeline contract.

24 m x 14 m interior (Blender x -12..12, y -7..7), two rooms split by a cut-away
east-west wall with a door gap, a full-height north hull wall with a light
strip, full-height walls along Z, a console station (screen, seat, stand), a
holo table, a raised platform with steps, a pit with steps, a pillar, a lift,
and ceiling lights that are invisible to the camera but mirror in the floor.

Plain bpy primitives only; the kit replaces them on the real decks.
Run: python scripts/verse/cook.py deck testbed --quality preview
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import bpy
from lib import scene
from mathutils import Euler, Vector

DECK_ID = "testbed"
WALL_H = 4.5
CUT_H = 1.1
WALL_T = 0.3
CEILING_Z = WALL_H
BEVEL_M = 0.012


# ---------------------------------------------------------------- materials


def _principled(
    name: str,
    base: Sequence[float],
    roughness: float,
    metallic: float = 0.0,
    roughness_noise: float = 0.08,
    seams_m: float | None = None,
) -> bpy.types.Material:
    """Graybox material with roughness variation and optional 1.2 m panel seams."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = (*base, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 7.0
    noise.inputs["Detail"].default_value = 6.0
    coords = nodes.new("ShaderNodeNewGeometry")
    links.new(coords.outputs["Position"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = roughness - roughness_noise
    ramp.inputs["To Max"].default_value = roughness + roughness_noise
    links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    rough_out = ramp.outputs["Result"]
    if seams_m:
        seam = _seam_mask(nodes, links, coords, seams_m)
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "FLOAT"
        mix.inputs["B"].default_value = 0.55
        links.new(seam, mix.inputs["Factor"])
        links.new(rough_out, mix.inputs["A"])
        rough_out = mix.outputs["Result"]
        dark = nodes.new("ShaderNodeMix")
        dark.data_type = "RGBA"
        dark.inputs["A"].default_value = (*base, 1.0)
        dark.inputs["B"].default_value = (*(c * 0.35 for c in base), 1.0)
        links.new(seam, dark.inputs["Factor"])
        links.new(dark.outputs["Result"], shader.inputs["Base Color"])
    links.new(rough_out, shader.inputs["Roughness"])
    return material


def _seam_mask(nodes, links, coords, period: float):
    """1 on thin lines every `period` metres along world X and Y, else 0."""
    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords.outputs["Position"], separate.inputs["Vector"])
    masks = []
    for axis in ("X", "Y"):
        wrap = nodes.new("ShaderNodeMath")
        wrap.operation = "PINGPONG"
        wrap.inputs[1].default_value = period / 2
        links.new(separate.outputs[axis], wrap.inputs[0])
        line = nodes.new("ShaderNodeMath")
        line.operation = "LESS_THAN"
        line.inputs[1].default_value = 0.006
        links.new(wrap.outputs[0], line.inputs[0])
        masks.append(line.outputs[0])
    both = nodes.new("ShaderNodeMath")
    both.operation = "MAXIMUM"
    links.new(masks[0], both.inputs[0])
    links.new(masks[1], both.inputs[1])
    return both.outputs[0]


def _emission(name: str, colour: Sequence[float], strength: float) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1.0)
    shader.inputs["Emission Color"].default_value = (*colour, 1.0)
    shader.inputs["Emission Strength"].default_value = strength
    shader.inputs["Roughness"].default_value = 0.3
    return material


def _materials() -> dict[str, bpy.types.Material]:
    return {
        "floor": _principled(
            "M_floor_black", (0.012, 0.012, 0.013), 0.06, roughness_noise=0.025, seams_m=1.2
        ),
        "wall": _principled("M_wall_panel", (0.42, 0.43, 0.44), 0.45, seams_m=1.2),
        "metal": _principled(
            "M_gunmetal", (0.18, 0.19, 0.2), 0.3, metallic=1.0, roughness_noise=0.04
        ),
        "cap": _principled("M_section_cap", (0.035, 0.036, 0.04), 0.55, metallic=0.6),
        "hull": _principled("M_hull_dark", (0.03, 0.03, 0.032), 0.6, metallic=0.8),
        "ceiling": _principled("M_ceiling", (0.3, 0.3, 0.31), 0.6),
        "glass": _principled("M_screen_glass", (0.005, 0.006, 0.008), 0.05, roughness_noise=0.01),
        "strip": _emission("M_light_strip", (0.85, 0.92, 1.0), 12.0),
        "red": _emission("M_indicator_red", (1.0, 0.05, 0.03), 25.0),
        "green": _emission("M_indicator_green", (0.1, 1.0, 0.25), 18.0),
    }


# ---------------------------------------------------------------- geometry


def _box(
    name: str,
    minimum: Sequence[float],
    maximum: Sequence[float],
    material: bpy.types.Material,
    collection: str = "Architecture",
    cap: bpy.types.Material | None = None,
    nav: str | None = None,
    bevel: float = BEVEL_M,
) -> bpy.types.Object:
    """Bevelled box; `cap` is the section material for the top face of a cut wall."""
    (x0, y0, z0), (x1, y1, z1) = minimum, maximum
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]  # fmt: skip
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(material)
    if cap is not None:
        mesh.materials.append(cap)
        mesh.polygons[1].material_index = 1
    obj = bpy.data.objects.new(name, mesh)
    if bevel > 0:
        modifier = obj.modifiers.new("Bevel", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        modifier.limit_method = "ANGLE"
        modifier.harden_normals = True
    scene.collection(collection).objects.link(obj)
    if nav:
        scene.tag(obj, nav=nav)
    return obj


def _cylinder(
    name: str,
    centre: Sequence[float],
    radius: float,
    z0: float,
    z1: float,
    material: bpy.types.Material,
    collection: str = "Props",
    nav: str | None = None,
) -> bpy.types.Object:
    segments = 48
    ring = [
        (centre[0] + radius * math.cos(a), centre[1] + radius * math.sin(a))
        for a in (2 * math.pi * i / segments for i in range(segments))
    ]
    verts = [(x, y, z0) for x, y in ring] + [(x, y, z1) for x, y in ring]
    faces = [list(range(segments - 1, -1, -1)), list(range(segments, 2 * segments))]
    faces += [
        (i, (i + 1) % segments, segments + (i + 1) % segments, segments + i)
        for i in range(segments)
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.use_smooth = len(polygon.vertices) == 4
    obj = bpy.data.objects.new(name, mesh)
    modifier = obj.modifiers.new("Bevel", "BEVEL")
    modifier.width = BEVEL_M
    modifier.segments = 2
    modifier.limit_method = "ANGLE"
    scene.collection(collection).objects.link(obj)
    if nav:
        scene.tag(obj, nav=nav)
    return obj


def _floor(m: dict) -> None:
    # Hull structure around the room (never walkable), then the deck slabs
    # around the pit hole at x -9..-4, y 3..6.
    _box("SM_Hull_1", (-13, -8, -1.3), (13, 8, -0.06), m["hull"], nav="none", bevel=0)
    slabs = [
        ((-12, -7), (12, 3)),
        ((-12, 6), (12, 7)),
        ((-12, 3), (-9, 6)),
        ((-4, 3), (12, 6)),
    ]
    for index, ((x0, y0), (x1, y1)) in enumerate(slabs, start=1):
        _box(
            f"SM_FloorSlab_{index}",
            (x0, y0, -1.2),
            (x1, y1, 0),
            m["floor"],
            nav="walk",
            bevel=0.004,
        )
    _box("SM_PitFloor_1", (-9, 3, -1.2), (-4, 6, -0.8), m["floor"], nav="walk", bevel=0.004)
    for step in range(3):
        x1 = -4.0 - 0.4 * step
        top = -0.2 * (step + 1)
        _box(f"SM_PitStep_{step + 1}", (x1 - 0.4, 3, -1.2), (x1, 6, top), m["metal"], nav="walk")


def _walls(m: dict) -> None:
    _box("SM_WallNorth_1", (-12.3, 7, 0), (12.3, 7 + WALL_T, WALL_H), m["wall"])
    _box("SM_WallStrip_1", (-11.6, 6.97, 3.15), (11.6, 7.0, 3.23), m["strip"], bevel=0.003)
    _box("SM_WallSkirt_1", (-12, 6.92, 0), (12, 7.0, 0.18), m["metal"], bevel=0.004)
    _box("SM_WallWest_1", (-12.3, -7.3, 0), (-12, 7, WALL_H), m["wall"])
    _box("SM_WallEast_1", (12, -7.3, 0), (12.3, 7, WALL_H), m["wall"])
    # Cut-away east-west walls: walkable space lies behind (north of) them.
    _box("SM_WallSouth_1", (-12.3, -7.3, 0), (12.3, -7, CUT_H), m["wall"], cap=m["cap"])
    _box("SM_WallDivider_1", (-12, 1.85, 0), (3, 2.15, CUT_H), m["wall"], cap=m["cap"])
    _box("SM_WallDivider_2", (4.8, 1.85, 0), (12, 2.15, CUT_H), m["wall"], cap=m["cap"])
    for x in (2.85, 4.65):
        _box(f"SM_DoorFrame_{int(x * 10)}", (x, 1.8, 0), (x + 0.15, 2.2, CUT_H + 0.05), m["metal"])
    _box("SM_Pillar_1", (-1.9, -0.9, 0), (-1.1, -0.1, WALL_H), m["metal"])
    # The cut-away parts stay in the scene, hidden from the plate camera, so
    # floor reflections and the env/probe panoramas still see a closed room.
    # They cast no shadow, so the section cap below them is lit.
    hidden = [
        ((-12.3, -7.3, CUT_H), (12.3, -7, WALL_H)),
        ((-12, 1.85, CUT_H), (3, 2.15, WALL_H)),
        ((3, 1.85, 2.4), (4.8, 2.15, WALL_H)),
        ((4.8, 1.85, CUT_H), (12, 2.15, WALL_H)),
    ]
    for index, (minimum, maximum) in enumerate(hidden, start=1):
        cut = _box(f"SM_WallCutAway_{index}", minimum, maximum, m["wall"], "Ceiling", bevel=0)
        cut.visible_shadow = False


def _ceiling(m: dict) -> None:
    _box(
        "SM_Ceiling_1",
        (-12, -7, CEILING_Z),
        (12, 7, CEILING_Z + 0.2),
        m["ceiling"],
        "Ceiling",
        bevel=0,
    )
    rows = (-5.0, -2.0, 3.5, 5.5)
    for row_index, y in enumerate(rows):
        for column in range(10):
            x = -10.8 + 2.4 * column
            name = f"LT_Ceiling_{row_index}_{column}"
            scene.add_area_light(name, (x, y, CEILING_Z - 0.04), (1.2, 0.35), 55.0, 6200.0)
            frame = _box(
                f"SM_LightFrame_{row_index}_{column}",
                (x - 0.68, y - 0.25, CEILING_Z - 0.03),
                (x + 0.68, y + 0.25, CEILING_Z),
                m["metal"],
                "Ceiling",
                bevel=0.004,
            )
            frame.visible_shadow = False


def _console(m: dict) -> None:
    body = _box("SM_Console_1", (-7, -1.4, 0), (-5, -0.6, 0.85), m["metal"], "Props")
    scene.tag(body, station="console_a", station_kind="agents_list")
    tilt = 30.0
    centre = Vector((-6.0, -1.0, 1.12))
    glass = _box(
        "SM_ConsoleScreen_1",
        (-0.8, -0.03, -0.25),
        (0.8, 0.03, 0.25),
        m["glass"],
        "Props",
        bevel=0.004,
    )
    # Leaning back by `tilt`: the glass faces the camera and slightly up.
    lean = Euler((math.radians(-tilt), 0.0, 0.0))
    glass.location = centre
    glass.rotation_euler = lean
    scene.tag(glass, station="console_a")
    _box("SM_ConsoleNeck_1", (-6.1, -0.95, 0.85), (-5.9, -0.75, 1.0), m["metal"], "Props")
    for index, (x, material) in enumerate(
        ((-6.6, m["red"]), (-6.45, m["green"]), (-5.4, m["green"]))
    ):
        _box(
            f"SM_Indicator_{index}",
            (x, -1.43, 0.7),
            (x + 0.06, -1.4, 0.74),
            material,
            "Props",
            bevel=0,
        )
    # The screen socket lies on the glass's front face; its occluder sits just
    # behind that face so the runtime's live screen is never hidden.
    normal = lean.to_matrix() @ Vector((0.0, -1.0, 0.0))
    occluder = scene.add_ucx_box("console_screen", (-0.8, -0.025, -0.25), (0.8, 0.03, 0.25))
    occluder.location = centre
    occluder.rotation_euler = lean
    scene.add_screen(
        "console_a",
        centre + normal * 0.03,
        1.5,
        0.42,
        yaw_deg=0.0,
        tilt_deg=tilt,
        station="console_a",
    )
    chair_seat = _box("SM_Chair_1", (-6.25, -2.25, 0.42), (-5.75, -1.75, 0.5), m["metal"], "Props")
    _box("SM_ChairBack_1", (-6.25, -2.3, 0.5), (-5.75, -2.22, 1.0), m["metal"], "Props")
    _box("SM_ChairPost_1", (-6.04, -2.04, 0), (-5.96, -1.96, 0.42), m["metal"], "Props")
    scene.tag(chair_seat, station="console_a")
    scene.add_socket("station", "console_a", (-6.0, -1.6, 0.0), 180.0, station_kind="agents_list")
    # Seat sockets sit on the cushion top (hip point).
    scene.add_socket("seat", "console_a", (-6.0, -2.0, 0.5), 180.0, station="console_a")
    scene.add_socket("stand", "console_a", (-4.4, -2.2, 0.0), 160.0, station="console_a")


def _holo_table(m: dict) -> None:
    _cylinder("SM_HoloTable_1", (1.5, -3.5), 1.0, 0.0, 0.88, m["metal"])
    _cylinder("SM_HoloTableTop_1", (1.5, -3.5), 0.85, 0.88, 0.92, m["glass"])
    scene.add_socket("holo", "table", (1.5, -3.5, 0.93), 0.0, radius=0.85)


def _platform(m: dict) -> None:
    _box("SM_Platform_1", (6, -6, -1.2), (11, -1.5, 0.6), m["metal"], "Architecture", nav="walk")
    for step in range(2):
        x0 = 5.2 + 0.4 * step
        top = 0.2 * (step + 1)
        _box(
            f"SM_PlatformStep_{step + 1}",
            (x0, -4.5, -1.2),
            (x0 + 0.4, -3.0, top),
            m["metal"],
            nav="walk",
        )
    scene.add_socket("stand", "platform", (8.5, -3.75, 0.6), 0.0)


def _lift(m: dict) -> None:
    _cylinder("SM_LiftPad_1", (10.2, 4.8), 1.0, -0.2, 0.02, m["metal"], "Architecture", nav="walk")
    for index, (dx, dy) in enumerate(((-1.15, -1.15), (1.15, -1.15), (-1.15, 1.15), (1.15, 1.15))):
        x, y = 10.2 + dx, 4.8 + dy
        _box(
            f"SM_LiftPost_{index}",
            (x - 0.08, y - 0.08, 0),
            (x + 0.08, y + 0.08, 2.6),
            m["metal"],
            "Props",
        )
    scene.add_socket("lift", "main", (10.2, 4.8, 0.02), 0.0, decks="all")


def _sockets() -> None:
    scene.add_socket("door", "divider", (3.9, 2.0, 0.0), 0.0, width=1.8)
    scene.add_socket("spawn", "arrival", (0.0, -5.0, 0.0), 0.0)
    scene.add_socket("waypoint", "hall_west", (-9.0, -4.5, 0.0), 90.0)
    scene.add_socket("waypoint", "annex_east", (7.0, 4.5, 0.0), -90.0)
    scene.add_socket(
        "light", "console_alarm", (-6.6, -1.42, 0.72), 0.0, colour="#ff2a1a", blink_hz=1.0
    )


def _rooms() -> None:
    scene.add_room("hall", "Main Hall", [(-12, -7), (12, -7), (12, 1.85), (-12, 1.85)], main=True)
    scene.add_room("annex", "Annex", [(-12, 2.15), (12, 2.15), (12, 7), (-12, 7)])


def _occluders() -> None:
    boxes = {
        "wall_north": ((-12.3, 7, 0), (12.3, 7.3, WALL_H)),
        "wall_west": ((-12.3, -7.3, 0), (-12, 7, WALL_H)),
        "wall_east": ((12, -7.3, 0), (12.3, 7, WALL_H)),
        "wall_south": ((-12.3, -7.3, 0), (12.3, -7, CUT_H)),
        "divider_west": ((-12, 1.85, 0), (3, 2.15, CUT_H)),
        "divider_east": ((4.8, 1.85, 0), (12, 2.15, CUT_H)),
        "pillar": ((-1.9, -0.9, 0), (-1.1, -0.1, WALL_H)),
        "console": ((-7, -1.4, 0), (-5, -0.6, 0.85)),
        "holo_table": ((0.6, -4.4, 0), (2.4, -2.6, 0.92)),
        "platform": ((6, -6, -1.2), (11, -1.5, 0.6)),
        "platform_steps": ((5.2, -4.5, -1.2), (6, -3.0, 0.4)),
        "pit_rim": ((-9, 2.15, -1.2), (-4, 3, 0)),
        "lift_posts_south": ((9, 3.6, 0), (11.4, 3.7, 2.6)),
    }
    for name, (minimum, maximum) in boxes.items():
        scene.add_ucx_box(name, minimum, maximum)


def build() -> None:
    bounds = scene.Bounds(x_min=-13, y_min=-8, x_max=13, y_max=8, z_min=-0.8, z_max=WALL_H)
    scene.new_deck(DECK_ID, bounds, name="Testbed", floor=0, exposure=0.3)
    materials = _materials()
    _floor(materials)
    _walls(materials)
    _ceiling(materials)
    _console(materials)
    _holo_table(materials)
    _platform(materials)
    _lift(materials)
    _sockets()
    _rooms()
    _occluders()


if __name__ == "__main__":
    build()
