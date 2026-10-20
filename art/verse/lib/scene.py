"""Deck scene setup and placement helpers (runs inside Blender).

A deck builder (`art/verse/decks/<id>/build.py`) calls `new_deck()` first, then
places kit pieces into the collections it creates and adds sockets, rooms and
occluder proxies with the helpers below. `lib.cook.cook_deck()` turns the scene
into runtime content.

Axes: Blender X = three X (screen right), Blender Y = -(three Z) (away from the
camera), Blender Z = three Y (up). Builders work in Blender axes; manifests are
written in three.js axes by the cook.

Lookdev scenes that are not decks use `configure_render()` and
`plate_camera()` to render exactly like a cook.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass

import bpy
from mathutils import Euler, Vector

from lib import naming

PITCH_DEG = 60.0
YAW_DEG = 0.0
FRAME_MARGIN_M = 0.5
CAMERA_DISTANCE_M = 250.0
PIXEL_ALIGN = 16

# AgX with the base look: the realtime actors are tone-mapped with three.js
# AgXToneMapping, which implements this same curve, so characters and plate
# match. Contrast comes from the lighting design, not from a look.
VIEW_TRANSFORM = "AgX"
LOOK = "None"


@dataclass(frozen=True)
class QualityPreset:
    px_per_m: int
    samples: int
    adaptive_threshold: float
    env_samples: int
    probe_samples: int


QUALITY = {
    # 192 px/m (5 mm plate pixels): the runtime's close third-person camera
    # shows the plate at up to ~200 CSS px per metre, so L0 stays 1:1 there.
    "final": QualityPreset(
        px_per_m=192, samples=192, adaptive_threshold=0.02, env_samples=256, probe_samples=128
    ),
    "preview": QualityPreset(
        px_per_m=48, samples=96, adaptive_threshold=0.03, env_samples=64, probe_samples=32
    ),
}


@dataclass(frozen=True)
class Bounds:
    """Deck extent in Blender metres: ground rectangle plus the height range seen."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    z_min: float = 0.0
    z_max: float = 5.0


@dataclass(frozen=True)
class Frame:
    """The fixed orthographic plate camera for one density."""

    centre: tuple[float, float, float]  # Blender axes, on the floor plane z = 0
    width_m: float
    height_m: float
    width_px: int
    height_px: int
    px_per_m: int


def camera_basis() -> tuple[Vector, Vector, Vector]:
    """Right, up and view direction of the plate camera in Blender axes."""
    pitch = math.radians(PITCH_DEG)
    right = Vector((1.0, 0.0, 0.0))
    up = Vector((0.0, math.sin(pitch), math.cos(pitch)))
    view = Vector((0.0, math.cos(pitch), -math.sin(pitch)))
    return right, up, view


def frame_for(bounds: Bounds, px_per_m: int, margin: float = FRAME_MARGIN_M) -> Frame:
    """Smallest pixel-aligned frame that shows `bounds` plus `margin` on every side."""
    pitch = math.radians(PITCH_DEG)
    u_min, u_max = bounds.x_min - margin, bounds.x_max + margin
    v_min = math.sin(pitch) * bounds.y_min + math.cos(pitch) * bounds.z_min - margin
    v_max = math.sin(pitch) * bounds.y_max + math.cos(pitch) * bounds.z_max + margin
    width_px = _align((u_max - u_min) * px_per_m)
    height_px = _align((v_max - v_min) * px_per_m)
    u_c, v_c = (u_min + u_max) / 2, (v_min + v_max) / 2
    centre = (u_c, v_c / math.sin(pitch), 0.0)
    return Frame(
        centre=centre,
        width_m=width_px / px_per_m,
        height_m=height_px / px_per_m,
        width_px=width_px,
        height_px=height_px,
        px_per_m=px_per_m,
    )


def _align(pixels: float) -> int:
    return int(math.ceil(pixels / PIXEL_ALIGN) * PIXEL_ALIGN)


def to_three(point: Sequence[float], digits: int = 4) -> list[float]:
    """Blender (x, y, z) -> three.js (x, y, z) = (x, z, -y), rounded (0.1 mm default)."""
    x, y, z = point
    return [round(x, digits) + 0.0, round(z, digits) + 0.0, round(-y, digits) + 0.0]


# ---------------------------------------------------------------- scene setup


def new_deck(
    deck_id: str,
    bounds: Bounds,
    *,
    name: str,
    floor: int = 0,
    exposure: float = 0.0,
) -> bpy.types.Scene:
    """Reset the file to an empty, fully configured deck scene and return it."""
    level = naming.level_name(deck_id)
    _clear_file()
    scene = bpy.context.scene
    scene.name = level
    scene["verse"] = {
        "deck_id": deck_id,
        "name": name,
        "floor": floor,
        "bounds": asdict(bounds),
    }
    configure_render(scene, "final", exposure)
    root = bpy.data.collections.new(level)
    scene.collection.children.link(root)
    for child in naming.DECK_COLLECTIONS:
        collection = bpy.data.collections.new(child)
        root.children.link(collection)
        collection.hide_render = child in ("Occluders", "Sockets", "NavOnly")
    plate_camera(scene, bounds, QUALITY["final"].px_per_m, root)
    return scene


def configure_render(scene: bpy.types.Scene, quality: str = "final", exposure: float = 0.0) -> None:
    """Units, Cycles, colour management and the black interior world of a cook."""
    _configure_units(scene)
    _configure_cycles(scene, QUALITY[quality])
    _configure_colour(scene, exposure)
    _configure_world(scene)


def plate_camera(
    scene: bpy.types.Scene,
    bounds: Bounds,
    px_per_m: int | None = None,
    collection: bpy.types.Collection | None = None,
) -> bpy.types.Object:
    """The scene's plate camera (created if missing), framed on `bounds`
    (default density: the final preset's)."""
    camera = scene.objects.get("CAM_plate")
    if camera is None:
        camera = _add_plate_camera(scene, collection or scene.collection)
    scene.camera = camera
    apply_frame(scene, camera, frame_for(bounds, px_per_m or QUALITY["final"].px_per_m))
    return camera


def _clear_file() -> None:
    for collection in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.collections,
        bpy.data.materials,
        bpy.data.node_groups,
        bpy.data.images,
        bpy.data.worlds,
    ):
        for block in list(collection):
            collection.remove(block)
    bpy.data.orphans_purge(do_recursive=True)


def _configure_units(scene: bpy.types.Scene) -> None:
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"


def _configure_cycles(scene: bpy.types.Scene, preset: QualityPreset) -> None:
    scene.render.engine = "CYCLES"
    cycles = scene.cycles
    backend = os.environ.get("VERSE_CYCLES_BACKEND", "CPU")
    cycles.device = "CPU" if backend == "CPU" else "GPU"
    cycles.samples = preset.samples
    cycles.use_adaptive_sampling = True
    cycles.adaptive_threshold = preset.adaptive_threshold
    cycles.adaptive_min_samples = 32
    cycles.use_denoising = True
    cycles.denoiser = "OPTIX" if backend == "OPTIX" else "OPENIMAGEDENOISE"
    cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    cycles.seed = 0
    cycles.use_animated_seed = False
    # Light paths: enough glossy depth for the mirrored black decks.
    cycles.max_bounces = 12
    cycles.diffuse_bounces = 4
    cycles.glossy_bounces = 6
    cycles.transmission_bounces = 8
    cycles.volume_bounces = 1
    cycles.transparent_max_bounces = 16
    cycles.caustics_reflective = False
    cycles.caustics_refractive = False
    cycles.blur_glossy = 1.0
    cycles.sample_clamp_direct = 0.0
    cycles.sample_clamp_indirect = 8.0
    cycles.use_auto_tile = True
    cycles.tile_size = 2048
    scene.render.film_transparent = False
    scene.render.dither_intensity = 1.0


def _configure_colour(scene: bpy.types.Scene, exposure: float) -> None:
    settings = scene.view_settings
    settings.view_transform = VIEW_TRANSFORM
    settings.look = LOOK
    settings.exposure = exposure
    settings.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    scene.sequencer_colorspace_settings.name = "sRGB"


def _configure_world(scene: bpy.types.Scene) -> None:
    # The ship is a closed interior: every photon comes from a fixture.
    world = bpy.data.worlds.new("WO_interior")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    background.inputs["Strength"].default_value = 0.0
    scene.world = world


def _add_plate_camera(scene: bpy.types.Scene, root: bpy.types.Collection) -> bpy.types.Object:
    data = bpy.data.cameras.new("CAM_plate")
    data.type = "ORTHO"
    data.sensor_fit = "HORIZONTAL"
    data.clip_start = 1.0
    data.clip_end = CAMERA_DISTANCE_M * 2
    camera = bpy.data.objects.new("CAM_plate", data)
    root.objects.link(camera)
    scene.camera = camera
    return camera


def apply_frame(scene: bpy.types.Scene, camera: bpy.types.Object, frame: Frame) -> None:
    """Point the plate camera at `frame` and set the render size."""
    _, _, view = camera_basis()
    centre = Vector(frame.centre)
    camera.location = centre - view * CAMERA_DISTANCE_M
    camera.rotation_euler = Euler((math.radians(90.0 - PITCH_DEG), 0.0, math.radians(YAW_DEG)))
    camera.data.type = "ORTHO"
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.ortho_scale = frame.width_m
    scene.render.resolution_x = frame.width_px
    scene.render.resolution_y = frame.height_px
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0


def deck_info(scene: bpy.types.Scene | None = None) -> dict:
    """The metadata `new_deck` stored on the scene."""
    scene = scene or bpy.context.scene
    if "verse" not in scene:
        raise RuntimeError("scene was not created with lib.scene.new_deck()")
    info = scene["verse"].to_dict()
    info["bounds"] = Bounds(**info["bounds"])
    return info


def deck_root(scene: bpy.types.Scene | None = None) -> bpy.types.Collection:
    info = deck_info(scene)
    return bpy.data.collections[naming.level_name(info["deck_id"])]


def collection(name: str) -> bpy.types.Collection:
    """One of the deck's child collections (Architecture, Props, ...)."""
    if name not in naming.DECK_COLLECTIONS:
        raise ValueError(f"unknown deck collection {name!r}")
    return deck_root().children[name]


# ---------------------------------------------------------------- placement


def link(obj: bpy.types.Object, collection_name: str) -> bpy.types.Object:
    """Move `obj` into one deck collection (unlinking it from any other)."""
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    collection(collection_name).objects.link(obj)
    return obj


def tag(
    obj: bpy.types.Object,
    *,
    nav: str | None = None,
    room: str | None = None,
    station: str | None = None,
    station_kind: str | None = None,
) -> bpy.types.Object:
    """Set the pipeline custom properties on a placed object."""
    if nav is not None:
        if nav not in naming.NAV_VALUES:
            raise ValueError(f"nav must be one of {naming.NAV_VALUES}")
        obj["nav"] = nav
    for key, value in (("room", room), ("station", station), ("station_kind", station_kind)):
        if value is not None:
            obj[key] = value
    return obj


def add_socket(
    kind: str,
    socket_id: str,
    location: Sequence[float],
    yaw_deg: float = 0.0,
    **props: object,
) -> bpy.types.Object:
    """Add `SOCKET_<kind>_<id>`; yaw 0 faces the camera (three +Z), 90 faces screen right.

    The socket faces its local -Y and the character's root takes its yaw.
    Seats: position on the cushion top (hip point). Bunks: mattress top
    centre, local -Y (the yaw) pointing from head to feet.
    """
    empty = bpy.data.objects.new(naming.socket_name(kind, socket_id), None)
    empty.empty_display_type = "ARROWS"
    empty.empty_display_size = 0.4
    empty.location = Vector(location)
    # The character faces local -Y; a Blender rotation about +Z equals the
    # three.js yaw about +Y.
    empty.rotation_euler = Euler((0.0, 0.0, math.radians(yaw_deg)))
    for key, value in props.items():
        empty[key] = value
    collection("Sockets").objects.link(empty)
    return empty


def add_screen(
    socket_id: str,
    centre: Sequence[float],
    width: float,
    height: float,
    yaw_deg: float = 0.0,
    tilt_deg: float = 0.0,
    **props: object,
) -> bpy.types.Object:
    """Add a screen socket: the empty's local XY plane is the screen, +Z its normal.

    yaw 0 = the screen faces the camera; tilt leans the top away from the viewer.
    """
    empty = add_socket("screen", socket_id, centre, 0.0, size_w=width, size_h=height, **props)
    empty.rotation_euler = Euler((math.radians(90.0 - tilt_deg), 0.0, math.radians(yaw_deg)))
    return empty


def add_room(
    room_id: str, name: str, polygon: Sequence[Sequence[float]], z: float = 0.0, **props: object
) -> bpy.types.Object:
    """Add `ROOM_<id>`, a flat polygon (Blender XY, counter-clockwise) at floor height z."""
    verts = [(x, y, z) for x, y in polygon]
    mesh = bpy.data.meshes.new(naming.room_name(room_id))
    mesh.from_pydata(verts, [], [list(range(len(verts)))])
    obj = bpy.data.objects.new(naming.room_name(room_id), mesh)
    obj["name"] = name
    for key, value in props.items():
        obj[key] = value
    obj.display_type = "WIRE"
    collection("NavOnly").objects.link(obj)
    return obj


def add_ucx_box(
    occluder_id: str, minimum: Sequence[float], maximum: Sequence[float]
) -> bpy.types.Object:
    """Add an axis-aligned occluder proxy `UCX_<id>` spanning minimum..maximum."""
    (x0, y0, z0), (x1, y1, z1) = minimum, maximum
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]  # fmt: skip
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new(f"{naming.OCCLUDER}{occluder_id}")
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(f"{naming.OCCLUDER}{occluder_id}", mesh)
    obj.display_type = "WIRE"
    collection("Occluders").objects.link(obj)
    return obj


def add_ucx_from_bounds(
    obj: bpy.types.Object, occluder_id: str | None = None, pad: float = 0.0
) -> bpy.types.Object:
    """Occluder proxy from the world-space bounding box of `obj`."""
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = [min(c[i] for c in corners) - pad for i in range(3)]
    maximum = [max(c[i] for c in corners) + pad for i in range(3)]
    return add_ucx_box(occluder_id or obj.name.removeprefix(naming.STATIC_MESH), minimum, maximum)


def add_area_light(
    name: str,
    location: Sequence[float],
    size: tuple[float, float],
    power_w: float,
    kelvin: float = 6000.0,
    rotation_deg: Sequence[float] = (0.0, 0.0, 0.0),
    spread_deg: float = 180.0,
) -> bpy.types.Object:
    """Rectangular area light (pointing down by default) in the Lights collection."""
    data = bpy.data.lights.new(name, "AREA")
    data.shape = "RECTANGLE"
    data.size, data.size_y = size
    data.energy = power_w
    data.use_temperature = True
    data.temperature = kelvin
    data.spread = math.radians(spread_deg)
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(location)
    obj.rotation_euler = Euler([math.radians(a) for a in rotation_deg])
    collection("Lights").objects.link(obj)
    return obj


def objects_in(collection_name: str) -> Iterable[bpy.types.Object]:
    return collection(collection_name).all_objects
