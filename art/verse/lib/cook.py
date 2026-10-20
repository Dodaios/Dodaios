"""Deck cook, Blender side: the "lighting build" of a deck.

`cook_deck()` renders and exports everything the runtime needs into a raw
directory; `scripts/verse/package.py` (outside Blender, with Pillow) encodes the
plate tiles and the nav PNG and writes the final `manifest.json`.

Raw outputs (all in `out_dir`):
    plate_<i>.npy   uint8 RGB plate regions (AgX, glow, dithered); cook.json
                    `plate_parts` places them (the packager stitches them)
    nav.npy         uint8 nav grid, 0 = blocked, else floor height code
    occluders.glb   every UCX_ mesh merged, glTF +Y up, no materials
    env.hdr         equirect radiance at the main room (three.js layout)
    cook.json       camera, nav, rooms, sockets, stations, probes, stats
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

from lib import naming, navgrid, plate_post, scene

NAV_SUBSAMPLES = 3
NAV_STEP_M = 0.15  # surfaces up to this high above the floor do not block
NAV_HEADROOM_M = 2.0  # anything solid below this height blocks the cell
EYE_HEIGHT_M = 1.4
ENV_SIZE = (512, 256)  # ~0.3 MB as Radiance HDR; probes carry the diffuse light
PROBE_SIZE = (64, 32)


class CookError(RuntimeError):
    """The deck scene breaks a pipeline contract."""


@dataclass(frozen=True)
class MeshSoup:
    vertices: np.ndarray  # (n, 3) float64, world space
    triangles: np.ndarray  # (m, 3) int32
    triangle_object: np.ndarray  # (m,) int32 index into names
    names: list[str]
    walk: np.ndarray  # (len(names),) bool


def cook_deck(deck_id: str, out_dir: Path, quality: str = "final") -> dict:
    """Render and export deck `deck_id` (the current scene) into `out_dir`."""
    if quality not in scene.QUALITY:
        raise ValueError(f"quality must be one of {sorted(scene.QUALITY)}")
    preset = scene.QUALITY[quality]
    info = scene.deck_info()
    if info["deck_id"] != deck_id:
        raise CookError(f"scene holds deck {info['deck_id']!r}, not {deck_id!r}")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy_scene = bpy.context.scene
    bpy.context.view_layer.update()  # world matrices of freshly built objects
    _prepare_visibility()
    rooms = _rooms()
    sockets = _sockets(rooms)
    stations = _stations(sockets)
    frame = scene.frame_for(info["bounds"], preset.px_per_m)
    _check_sockets_in_frame(sockets, frame)

    timings: dict[str, float] = {}
    print(
        f"[verse] cook {deck_id} ({quality}): {frame.width_px}x{frame.height_px} px, "
        f"{preset.samples} samples, {len(rooms)} rooms, {len(sockets)} sockets",
        flush=True,
    )
    with _stage("plate", timings):
        plate_parts = _render_plate(bpy_scene, frame, preset, out_dir)
    with _stage("nav", timings):
        nav = _cook_nav(info["bounds"], out_dir / "nav.npy")
    with _stage("occluders", timings):
        occluder_triangles = _export_occluders(deck_id, out_dir / "occluders.glb")
    with _stage("lighting", timings):
        env_position = _eye_point(_main_room(rooms))
        _render_panorama(bpy_scene, env_position, ENV_SIZE, preset.env_samples, out_dir / "env.hdr")
        probes = [_cook_probe(bpy_scene, room, preset.probe_samples, out_dir) for room in rooms]

    result = {
        "id": deck_id,
        "name": info["name"],
        "floor": info["floor"],
        "quality": quality,
        "camera": _camera_json(frame, bpy_scene),
        "plate_parts": plate_parts,
        "nav": nav,
        "occluders": {"triangles": occluder_triangles},
        "env": {"w": ENV_SIZE[0], "h": ENV_SIZE[1], "position": scene.to_three(env_position)},
        "probes": probes,
        "rooms": [_room_json(room) for room in rooms],
        "sockets": sockets,
        "stations": stations,
        "stats": {
            "samples": preset.samples,
            "blender": bpy.app.version_string,
            **{key: round(value, 2) for key, value in timings.items()},
        },
    }
    (out_dir / "cook.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


@contextmanager
def _stage(name: str, timings: dict[str, float]) -> Iterator[None]:
    """Time one cook stage into `timings[<name>_s]` and log it."""
    print(f"[verse] stage {name}: start", flush=True)
    started = time.monotonic()
    yield
    timings[f"{name}_s"] = time.monotonic() - started
    print(f"[verse] stage {name}: {timings[f'{name}_s']:.1f} s", flush=True)


# ---------------------------------------------------------------- visibility


def _prepare_visibility() -> None:
    """Ceilings light the deck and mirror in the floor but never face the camera."""
    _set_ceiling_camera_visibility(False)
    for name in ("Occluders", "Sockets", "NavOnly"):
        scene.collection(name).hide_render = True


def _camera_hidden_objects() -> list[bpy.types.Object]:
    """Everything the plate camera must not see but panoramas must: the Ceiling
    collection and kit ghosts (cut-away wall tops, `ceiling_ghost` property),
    which live inside instanced kit master collections."""
    hidden = {obj.name: obj for obj in scene.objects_in("Ceiling")}
    hidden.update({obj.name: obj for obj in bpy.data.objects if obj.get("ceiling_ghost")})
    return list(hidden.values())


def _set_ceiling_camera_visibility(visible: bool) -> None:
    for obj in _camera_hidden_objects():
        obj.visible_camera = visible


# ---------------------------------------------------------------- plate


def _render_plate(
    bpy_scene, frame: scene.Frame, preset: scene.QualityPreset, out_dir: Path
) -> list[dict]:
    """Render the plate region by region with glow; return the region PNGs and rects."""
    scene.apply_frame(bpy_scene, bpy_scene.camera, frame)
    bpy_scene.cycles.samples = preset.samples
    bpy_scene.cycles.adaptive_threshold = preset.adaptive_threshold
    render = bpy_scene.render
    render.use_compositing = False
    render.use_persistent_data = True
    plan = plate_post.regions(frame.width_px, frame.height_px)
    linear_paths = []
    try:
        for index, region in enumerate(plan):
            path = out_dir / f"plate_linear_{index}.exr"
            started = time.monotonic()
            _render_region(bpy_scene, frame, region, path, use_border=len(plan) > 1)
            linear_paths.append(path)
            print(
                f"[verse] plate region {index + 1}/{len(plan)} "
                f"({region.col1 - region.col0}x{region.row1 - region.row0} px): "
                f"{time.monotonic() - started:.1f} s",
                flush=True,
            )
    finally:
        render.use_border = False
        render.use_crop_to_border = False
        render.use_persistent_data = False
    factor = plate_post.GLOW_FACTOR
    small = np.zeros((frame.height_px // factor, frame.width_px // factor, 3), np.float32)
    for region, path in zip(plan, linear_paths, strict=True):
        rows, cols = _inner_slice(region, factor)
        small[rows, cols] = plate_post.downsample(
            plate_post.bright(_load_inner(path, region)), factor
        )
    glow = plate_post.glow(small, frame.px_per_m / factor)
    parts = []
    for index, (region, path) in enumerate(zip(plan, linear_paths, strict=True)):
        linear = _load_inner(path, region)
        linear += plate_post.BLOOM_STRENGTH * plate_post.upsample_window(
            glow, factor, region.inner_row0, region.inner_row1, region.inner_col0, region.inner_col1
        )
        pixels = out_dir / f"plate_{index}.npy"
        np.save(
            pixels, _to_display_8bit(bpy_scene, linear, out_dir / "plate_display.png", seed=index)
        )
        path.unlink()
        parts.append(
            {
                "file": pixels.name,
                "row0": region.inner_row0,
                "row1": region.inner_row1,
                "col0": region.inner_col0,
                "col1": region.inner_col1,
            }
        )
    return parts


def _inner_slice(region: plate_post.Region, factor: int) -> tuple[slice, slice]:
    return (
        slice(region.inner_row0 // factor, region.inner_row1 // factor),
        slice(region.inner_col0 // factor, region.inner_col1 // factor),
    )


def _render_region(
    bpy_scene, frame: scene.Frame, region: plate_post.Region, path: Path, use_border: bool
) -> None:
    """Render one padded region to a half-float scene-linear EXR (denoised, no compositing)."""
    render = bpy_scene.render
    render.use_border = use_border
    render.use_crop_to_border = use_border
    # Blender truncates border * resolution (border is float32): aim a quarter
    # pixel inside each edge so the truncation lands on the intended pixel.
    width, height = frame.width_px, frame.height_px
    render.border_min_x = (region.col0 + 0.25) / width
    render.border_max_x = min(1.0, (region.col1 + 0.25) / width)
    render.border_min_y = (height - region.row1 + 0.25) / height
    render.border_max_y = min(1.0, (height - region.row0 + 0.25) / height)
    settings = render.image_settings
    settings.file_format = "OPEN_EXR"
    settings.color_mode = "RGB"
    settings.color_depth = "16"
    settings.exr_codec = "ZIP"
    render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def _load_inner(path: Path, region: plate_post.Region) -> np.ndarray:
    """The kept (inner) part of a rendered region, scene-linear RGB, row 0 at the top."""
    linear = _load_linear_rgb(path)
    expected = (region.row1 - region.row0, region.col1 - region.col0)
    if linear.shape[:2] != expected:
        raise CookError(f"{path.name}: rendered {linear.shape[:2]}, expected {expected}")
    rows, cols = region.inner_slice()
    return np.ascontiguousarray(linear[rows, cols])


def _to_display_8bit(bpy_scene, linear: np.ndarray, scratch: Path, seed: int) -> np.ndarray:
    """Scene-linear RGB -> the scene's view transform (AgX) -> dithered uint8 RGB.

    Blender applies the view transform when saving a 16-bit PNG; reading it
    back as non-colour data gives display values, which get triangular
    dither before 8-bit quantisation (Image.save_render does not dither).
    """
    height, width = linear.shape[:2]
    image = bpy.data.images.new("PLATE_region", width, height, alpha=False, float_buffer=True)
    try:
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[..., :3] = linear[::-1]
        image.pixels.foreach_set(rgba.ravel())
        settings = bpy_scene.render.image_settings
        settings.file_format = "PNG"
        settings.color_mode = "RGB"
        settings.color_depth = "16"
        settings.compression = 0
        image.save_render(str(scratch), scene=bpy_scene)
    finally:
        bpy.data.images.remove(image)
    display = bpy.data.images.load(str(scratch), check_existing=False)
    try:
        display.colorspace_settings.name = "Non-Color"
        values = np.empty(width * height * 4, dtype=np.float32)
        display.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(display)
        scratch.unlink()
    values = values.reshape(height, width, 4)[::-1, :, :3] * 255.0
    rng = np.random.default_rng(seed)
    values += rng.random(values.shape, dtype=np.float32) - rng.random(
        values.shape, dtype=np.float32
    )
    return np.clip(np.round(values), 0, 255).astype(np.uint8)


def _camera_json(frame: scene.Frame, bpy_scene) -> dict:
    right, up, view = scene.camera_basis()
    centre = Vector(frame.centre)
    return {
        "pitch_deg": scene.PITCH_DEG,
        "yaw_deg": scene.YAW_DEG,
        "px_per_m": frame.px_per_m,
        "centre": scene.to_three(centre),
        "right": scene.to_three(right, 7),
        "up": scene.to_three(up, 7),
        "forward": scene.to_three(view, 7),
        "distance": scene.CAMERA_DISTANCE_M,
        "frame_w_m": frame.width_m,
        "frame_h_m": frame.height_m,
        "plate_w_px": frame.width_px,
        "plate_h_px": frame.height_px,
        "view_transform": scene.VIEW_TRANSFORM,
        "look": scene.LOOK,
        "exposure": round(bpy_scene.view_settings.exposure, 3),
    }


# ---------------------------------------------------------------- geometry


def _deck_roles() -> dict[str, str]:
    """Original object name -> deck collection it belongs to."""
    roles: dict[str, str] = {}
    for name in naming.DECK_COLLECTIONS:
        for obj in scene.objects_in(name):
            roles.setdefault(obj.name, name)
    return roles


def _iter_instances(
    roles_wanted: tuple[str, ...],
) -> Iterator[tuple[str, bpy.types.Object, Matrix, str]]:
    """(display name, evaluated object, world matrix, nav tag) for every mesh instance."""
    roles = _deck_roles()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for instance in depsgraph.object_instances:
        obj = instance.object
        if obj.type != "MESH":
            continue
        owner = (
            instance.parent.original if instance.is_instance and instance.parent else obj.original
        )
        if roles.get(owner.name) not in roles_wanted:
            continue
        nav = obj.original.get("nav") or owner.get("nav") or naming.NAV_BLOCK
        yield owner.name, obj, instance.matrix_world.copy(), str(nav)


def _mesh_arrays(obj: bpy.types.Object, matrix: Matrix) -> tuple[np.ndarray, np.ndarray]:
    mesh = obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", vertices)
        triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", triangles)
    finally:
        obj.to_mesh_clear()
    vertices = vertices.reshape(-1, 3)
    world = np.array(matrix, dtype=np.float64)
    vertices = vertices @ world[:3, :3].T + world[:3, 3]
    return vertices, triangles.reshape(-1, 3)


def _require_finite(name: str, vertices: np.ndarray) -> None:
    """A NaN or infinite vertex poisons nav and occluders silently; stop the cook."""
    bad = int((~np.isfinite(vertices)).any(axis=1).sum())
    if bad:
        raise CookError(f"{name}: {bad} non-finite vertices after modifiers; fix the mesh")


def _mesh_soup(roles_wanted: tuple[str, ...], skip_nav: str | None = None) -> MeshSoup:
    vertex_chunks, triangle_chunks, owner_chunks = [], [], []
    names: list[str] = []
    walk: list[bool] = []
    offset = 0
    for name, obj, matrix, nav in _iter_instances(roles_wanted):
        if nav == skip_nav:
            continue
        vertices, triangles = _mesh_arrays(obj, matrix)
        if not len(triangles):
            continue
        _require_finite(name, vertices)
        vertex_chunks.append(vertices)
        triangle_chunks.append(triangles + offset)
        owner_chunks.append(np.full(len(triangles), len(names), dtype=np.int32))
        names.append(name)
        walk.append(nav == naming.NAV_WALK)
        offset += len(vertices)
    if not names:
        empty = np.zeros((0, 3))
        return MeshSoup(empty, empty.astype(np.int32), np.zeros(0, np.int32), [], np.zeros(0, bool))
    return MeshSoup(
        vertices=np.concatenate(vertex_chunks),
        triangles=np.concatenate(triangle_chunks),
        triangle_object=np.concatenate(owner_chunks),
        names=names,
        walk=np.array(walk, dtype=bool),
    )


# ---------------------------------------------------------------- nav grid


def _cook_nav(bounds: scene.Bounds, path: Path) -> dict:
    """Rasterise walkable floor (navgrid.CELL_M cells) with per-cell floor height."""
    soup = _mesh_soup(("Architecture", "Props"), skip_nav=naming.NAV_NONE)
    if not soup.names or not soup.walk.any():
        raise CookError("no mesh tagged nav='walk' in Architecture/Props")
    walk_bvh, solids = _nav_trees(soup)
    cell = navgrid.CELL_M
    width = math.ceil((bounds.x_max - bounds.x_min) / cell - 1e-9)
    height = math.ceil((bounds.y_max - bounds.y_min) / cell - 1e-9)
    top = float(soup.vertices[:, 2].max()) + 1.0
    bottom = float(soup.vertices[:, 2].min()) - 1.0
    k = NAV_SUBSAMPLES
    offsets = [(i + 0.5) / k for i in range(k)]
    floor = np.full((height * k, width * k), np.nan, dtype=np.float64)
    for row in range(height * k):
        # Row 0 is the far (north, three -Z) edge of the deck.
        y = bounds.y_max - (row // k + offsets[row % k]) * cell
        for col in range(width * k):
            x = bounds.x_min + (col // k + offsets[col % k]) * cell
            floor[row, col] = _column_floor(walk_bvh, solids, x, y, top, bottom)
    heights = navgrid.erode(navgrid.reduce_samples(floor, k))
    if np.isnan(heights).all():
        raise CookError("nav grid has no walkable cell; check the nav='walk' tags and bounds")
    np.save(path, navgrid.encode(heights))
    return {
        "origin_x": round(bounds.x_min, 4),
        "origin_z": round(-bounds.y_max, 4),
        "cell": cell,
        "w": width,
        "h": height,
        "height_zero": navgrid.HEIGHT_ZERO,
        "height_step": navgrid.HEIGHT_STEP_M,
        "max_step": navgrid.MAX_STEP_M,
        "clearance": navgrid.CLEARANCE_M,
        "walkable_cells": int((~np.isnan(heights)).sum()),
    }


@dataclass(frozen=True)
class SolidTree:
    bvh: BVHTree | None
    owner: np.ndarray  # solid triangle index -> object index


def _nav_trees(soup: MeshSoup) -> tuple[BVHTree, SolidTree]:
    """Separate trees for walk surfaces and solids.

    Faces of the two kinds often coincide (a sill standing on the floor); a
    ray returns only one of two coplanar faces, so mixing them would lose the
    floor under every sill.
    """
    vertices = soup.vertices.tolist()
    is_walk = soup.walk[soup.triangle_object]
    walk_bvh = BVHTree.FromPolygons(vertices, soup.triangles[is_walk].tolist(), all_triangles=True)
    solid_triangles = soup.triangles[~is_walk]
    solid_bvh = (
        BVHTree.FromPolygons(vertices, solid_triangles.tolist(), all_triangles=True)
        if len(solid_triangles)
        else None
    )
    return walk_bvh, SolidTree(bvh=solid_bvh, owner=soup.triangle_object[~is_walk])


def _column_floor(
    walk_bvh: BVHTree, solids: SolidTree, x: float, y: float, top: float, bottom: float
) -> float:
    """Height of the walkable floor under (x, y), or NaN when blocked or no floor."""
    floors = [z for z, nz, _ in _column_hits(walk_bvh, x, y, top, bottom) if nz > 0.5]
    if not floors:
        return math.nan
    floor_z = floors[0]
    if solids.bvh is None:
        return floor_z
    band_low, band_high = floor_z + NAV_STEP_M, floor_z + NAV_HEADROOM_M
    hits = _column_hits(solids.bvh, x, y, top, bottom)
    for low, high in _solid_intervals(hits, solids.owner, top):
        if low < band_high and high > band_low:
            return math.nan
    return floor_z


def _column_hits(
    bvh: BVHTree, x: float, y: float, top: float, bottom: float
) -> list[tuple[float, float, int]]:
    """Every surface a vertical ray from `top` crosses: (z, normal z, triangle)."""
    hits = []
    down = Vector((0.0, 0.0, -1.0))
    z = top
    while z > bottom:
        location, normal, index, _ = bvh.ray_cast(Vector((x, y, z)), down, z - bottom)
        if location is None:
            break
        hits.append((location.z, normal.z, index))
        z = location.z - 1e-4
    return hits


def _solid_intervals(hits, owner_of: np.ndarray, top: float) -> Iterator[tuple[float, float]]:
    """Height intervals filled by solids, from entry/exit pairs per object.

    Going down, an up-facing hit enters an object and a down-facing hit leaves
    it. Unpaired hits are treated conservatively (filled to the far end), and
    steep faces hit at grazing angles count as a thin slab.
    """
    entered: dict[int, float] = {}
    for z, nz, triangle in hits:
        owner = int(owner_of[triangle])
        if nz > 0.2:
            entered.setdefault(owner, z)
        elif nz < -0.2:
            yield z, entered.pop(owner, top)
        else:
            yield z - 0.01, z + 0.01
    for z in entered.values():
        yield -math.inf, z


# ---------------------------------------------------------------- occluders


def _export_occluders(deck_id: str, path: Path) -> int:
    """Merge every UCX_ mesh into one object and export it as GLB (+Y up)."""
    vertex_chunks, triangle_chunks, offset = [], [], 0
    for obj in scene.objects_in("Occluders"):
        if obj.type != "MESH":
            continue
        if not naming.is_occluder(obj.name):
            raise CookError(f"object {obj.name!r} in Occluders is not named UCX_*")
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        vertices, triangles = _mesh_arrays(evaluated, obj.matrix_world)
        _require_finite(obj.name, vertices)
        vertex_chunks.append(vertices)
        triangle_chunks.append(triangles + offset)
        offset += len(vertices)
    if not vertex_chunks:
        raise CookError("deck has no UCX_ occluder meshes")
    vertices = np.concatenate(vertex_chunks)
    triangles = np.concatenate(triangle_chunks)
    mesh = bpy.data.meshes.new(f"UCX_{deck_id}")
    mesh.from_pydata(vertices.tolist(), [], triangles.tolist())
    merged = bpy.data.objects.new(f"UCX_{deck_id}", mesh)
    bpy.context.scene.collection.objects.link(merged)
    try:
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        merged.select_set(True)
        bpy.context.view_layer.objects.active = merged
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            export_format="GLB",
            use_selection=True,
            export_yup=True,
            export_apply=True,
            export_materials="NONE",
            export_normals=False,
            export_texcoords=False,
            export_tangents=False,
            export_vertex_color="NONE",
            export_attributes=False,
            export_extras=False,
            export_cameras=False,
            export_lights=False,
        )
    finally:
        bpy.data.objects.remove(merged)
        bpy.data.meshes.remove(mesh)
    return int(len(triangles))


# ---------------------------------------------------------------- rooms


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    polygon: list[tuple[float, float]]  # Blender XY, counter-clockwise
    z: float
    centre: tuple[float, float]
    area: float
    main: bool
    props: dict
    probe_at: tuple[float, float, float] | None


def _rooms() -> list[Room]:
    rooms = []
    for obj in sorted(scene.objects_in("NavOnly"), key=lambda o: o.name):
        room_id = naming.parse_room(obj.name)
        if room_id is None or obj.type != "MESH":
            continue
        polygon = _boundary_loop(obj)
        area = _signed_area(polygon)
        if area < 0:
            polygon.reverse()
            area = -area
        z = sum((obj.matrix_world @ v.co).z for v in obj.data.vertices) / len(obj.data.vertices)
        rooms.append(
            Room(
                id=room_id,
                name=str(obj.get("name", room_id)),
                polygon=polygon,
                z=z,
                centre=_inside_centre(polygon),
                area=area,
                main=bool(obj.get("main", False)),
                props={k: _plain(obj[k]) for k in obj.keys() if k not in _ROOM_RESERVED},
                probe_at=_probe_at(obj),
            )
        )
    if not rooms:
        raise CookError("deck has no ROOM_ polygons in NavOnly")
    ids = [room.id for room in rooms]
    if len(set(ids)) != len(ids):
        raise CookError(f"duplicate room ids: {ids}")
    return rooms


_ROOM_RESERVED = {"name", "main", "probe_at"}


def _probe_at(obj: bpy.types.Object) -> tuple[float, float, float] | None:
    """Optional `probe_at` (x, y, z) in Blender metres overriding the probe point."""
    if "probe_at" not in obj:
        return None
    value = tuple(float(c) for c in _plain(obj["probe_at"]))
    if len(value) != 3:
        raise CookError(f"{obj.name}: probe_at must be (x, y, z)")
    return value


def _boundary_loop(obj: bpy.types.Object) -> list[tuple[float, float]]:
    """Outer boundary of a flat room mesh as one closed XY loop."""
    mesh = obj.data
    counts: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        for key in polygon.edge_keys:
            counts[key] = counts.get(key, 0) + 1
    edges = [key for key, count in counts.items() if count == 1]
    neighbours: dict[int, list[int]] = {}
    for a, b in edges:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    if not edges or any(len(n) != 2 for n in neighbours.values()):
        raise CookError(f"{obj.name}: room mesh must be one simple polygon")
    start = edges[0][0]
    loop, previous, current = [start], None, start
    while True:
        a, b = neighbours[current]
        following = b if a == previous else a
        if following == start:
            break
        loop.append(following)
        previous, current = current, following
    if len(loop) != len(neighbours):
        raise CookError(f"{obj.name}: room mesh has more than one boundary loop")
    world = [obj.matrix_world @ mesh.vertices[i].co for i in loop]
    return [(round(v.x, 4), round(v.y, 4)) for v in world]


def _edges(polygon: list[tuple[float, float]]):
    return zip(polygon, polygon[1:] + polygon[:1], strict=True)


def _signed_area(polygon: list[tuple[float, float]]) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in _edges(polygon))


def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in _edges(polygon):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _inside_centre(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    """Area centroid, or the inside grid point nearest to it for concave rooms."""
    area = _signed_area(polygon)
    cx = cy = 0.0
    for (x0, y0), (x1, y1) in _edges(polygon):
        cross = x0 * y1 - x1 * y0
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    cx, cy = cx / (6 * area), cy / (6 * area)
    if _point_in_polygon(cx, cy, polygon):
        return round(cx, 4), round(cy, 4)
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    candidates = [
        (x, y)
        for x in np.linspace(min(xs), max(xs), 41)
        for y in np.linspace(min(ys), max(ys), 41)
        if _point_in_polygon(x, y, polygon)
    ]
    x, y = min(candidates, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return round(float(x), 4), round(float(y), 4)


def _room_at(x: float, y: float, rooms: list[Room]) -> str | None:
    for room in rooms:
        if _point_in_polygon(x, y, room.polygon):
            return room.id
    return None


def _main_room(rooms: list[Room]) -> Room:
    flagged = [room for room in rooms if room.main]
    return flagged[0] if flagged else max(rooms, key=lambda room: room.area)


def _eye_point(room: Room) -> Vector:
    if room.probe_at is not None:
        return Vector(room.probe_at)
    return Vector((room.centre[0], room.centre[1], room.z + EYE_HEIGHT_M))


def _room_json(room: Room) -> dict:
    return {
        "id": room.id,
        "name": room.name,
        "floor_y": round(room.z, 4),
        "polygon": [[x, round(-y, 4) + 0.0] for x, y in room.polygon],
        "centre": scene.to_three((room.centre[0], room.centre[1], room.z)),
        "area_m2": round(room.area, 2),
        "main": room.main,
        **({"props": room.props} if room.props else {}),
    }


# ---------------------------------------------------------------- sockets


_RESERVED_PROPS = {"size_w", "size_h", "room", "station"}


def _sockets(rooms: list[Room]) -> list[dict]:
    sockets: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for obj in sorted(scene.objects_in("Sockets"), key=lambda o: o.name):
        parsed = naming.parse_socket(obj.name)
        if parsed is None or obj.type != "EMPTY":
            raise CookError(f"{obj.name!r} in Sockets is not an empty named SOCKET_<kind>_<id>")
        if (parsed.kind, parsed.id) in seen:
            raise CookError(f"duplicate socket {obj.name}")
        seen.add((parsed.kind, parsed.id))
        sockets.append(_socket_json(obj, parsed, rooms))
    return sockets


def _socket_json(obj: bpy.types.Object, parsed: naming.SocketName, rooms: list[Room]) -> dict:
    matrix = obj.matrix_world
    rotation = matrix.to_3x3().normalized()
    position = matrix.translation
    forward = rotation @ Vector((0.0, -1.0, 0.0))
    room = obj.get("room") or _room_at(position.x, position.y, rooms)
    entry: dict = {
        "id": parsed.id,
        "kind": parsed.kind,
        "position": scene.to_three(position),
        "yaw_deg": _yaw_deg(forward),
        "room": room,
    }
    if obj.get("station"):
        entry["station"] = str(obj["station"])
    if parsed.kind == "screen":
        entry.update(_screen_json(obj, rotation, position))
    props = {key: _plain(obj[key]) for key in obj.keys() if key not in _RESERVED_PROPS}
    if props:
        entry["props"] = props
    return entry


def _screen_json(obj: bpy.types.Object, rotation: Matrix, position: Vector) -> dict:
    if "size_w" not in obj or "size_h" not in obj:
        raise CookError(f"{obj.name}: screen sockets need size_w and size_h")
    half_w, half_h = float(obj["size_w"]) / 2, float(obj["size_h"]) / 2
    x_axis, y_axis = rotation.col[0], rotation.col[1]
    normal = rotation.col[2]
    corners = [
        position - x_axis * half_w + y_axis * half_h,  # top left
        position + x_axis * half_w + y_axis * half_h,  # top right
        position + x_axis * half_w - y_axis * half_h,  # bottom right
        position - x_axis * half_w - y_axis * half_h,  # bottom left
    ]
    return {
        "size": [round(half_w * 2, 4), round(half_h * 2, 4)],
        "normal": scene.to_three(normal, 6),
        "corners": [scene.to_three(corner) for corner in corners],
        "yaw_deg": _yaw_deg(normal),
    }


def _yaw_deg(direction_blender: Vector) -> float:
    """three.js yaw about +Y of a Blender direction (0 = facing three +Z)."""
    x, _, z = scene.to_three(direction_blender)
    if abs(x) < 1e-6 and abs(z) < 1e-6:
        return 0.0
    return round(math.degrees(math.atan2(x, z)), 2) + 0.0


def _plain(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value


def _station_kind(anchor: dict) -> str:
    kind = anchor.get("props", {}).get("station_kind")
    if not kind:
        raise CookError(f"SOCKET_station_{anchor['id']} needs a station_kind property")
    return str(kind)


def _stations(sockets: list[dict]) -> list[dict]:
    """Stations from SOCKET_station_* anchors; members are sockets whose `station` matches."""
    stations = []
    for anchor in sockets:
        if anchor["kind"] != "station":
            continue
        members: dict[str, list[str]] = {}
        for socket in sockets:
            if socket.get("station") == anchor["id"]:
                members.setdefault(socket["kind"], []).append(socket["id"])
        stations.append(
            {
                "id": anchor["id"],
                "kind": _station_kind(anchor),
                "room": anchor["room"],
                "position": anchor["position"],
                "yaw_deg": anchor["yaw_deg"],
                "sockets": members,
            }
        )
    known = {station["id"] for station in stations}
    for socket in sockets:
        if socket.get("station") and socket["station"] not in known:
            raise CookError(
                f"socket {socket['kind']}_{socket['id']} references unknown station "
                f"{socket['station']!r}"
            )
    return stations


def _check_sockets_in_frame(sockets: list[dict], frame: scene.Frame) -> None:
    right, up, _ = scene.camera_basis()
    centre = Vector(frame.centre)
    for socket in sockets:
        x, y, z = socket["position"]
        offset = Vector((x, -z, y)) - centre
        u, v = offset.dot(right), offset.dot(up)
        if abs(u) > frame.width_m / 2 or abs(v) > frame.height_m / 2:
            raise CookError(f"socket {socket['id']!r} lies outside the plate frame")


# ---------------------------------------------------------------- lighting


def _render_panorama(
    bpy_scene, position: Vector, size: tuple[int, int], samples: int, path: Path
) -> None:
    """Equirect render in the three.js layout: centre column = +X, then toward +Z."""
    plate_camera = bpy_scene.camera
    data = bpy.data.cameras.new("CAM_panorama")
    data.type = "PANO"
    data.panorama_type = "EQUIRECTANGULAR"
    camera = bpy.data.objects.new("CAM_panorama", data)
    bpy_scene.collection.objects.link(camera)
    camera.location = position
    camera.rotation_euler = Euler((math.radians(90.0), 0.0, math.radians(-90.0)))
    render = bpy_scene.render
    saved = (render.resolution_x, render.resolution_y, bpy_scene.cycles.samples)
    try:
        bpy_scene.camera = camera
        render.resolution_x, render.resolution_y = size
        bpy_scene.cycles.samples = samples
        render.use_compositing = False
        _set_ceiling_camera_visibility(True)
        settings = render.image_settings
        if path.suffix == ".hdr":
            settings.file_format = "HDR"
        else:
            settings.file_format = "OPEN_EXR"
            settings.color_depth = "32"
            settings.exr_codec = "ZIP"
        settings.color_mode = "RGB"
        render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        _set_ceiling_camera_visibility(False)
        bpy_scene.camera = plate_camera
        render.resolution_x, render.resolution_y, bpy_scene.cycles.samples = saved
        bpy.data.objects.remove(camera)
        bpy.data.cameras.remove(data)


def _cook_probe(bpy_scene, room: Room, samples: int, out_dir: Path) -> dict:
    position = _eye_point(room)
    path = out_dir / f"probe_{room.id}.exr"
    _render_panorama(bpy_scene, position, PROBE_SIZE, samples, path)
    radiance = _load_linear_rgb(path)
    return {
        "room": room.id,
        "position": scene.to_three(position),
        "sh": [[round(float(c), 5) for c in rgb] for rgb in project_sh9(radiance)],
    }


def _load_linear_rgb(path: Path) -> np.ndarray:
    """(h, w, 3) float32, row 0 at the top."""
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)
    return pixels.reshape(height, width, 4)[::-1, :, :3]


def project_sh9(radiance: np.ndarray) -> np.ndarray:
    """Project an equirect (three.js layout) radiance map to 9 RGB SH coefficients.

    Basis and order match three.js SphericalHarmonics3 (directions in three
    axes), so `LightProbe.sh.fromArray(coefficients.flat)` reproduces it.
    """
    height, width, _ = radiance.shape
    phi = ((np.arange(width) + 0.5) / width - 0.5) * 2 * np.pi
    lat = (0.5 - (np.arange(height) + 0.5) / height) * np.pi
    lat, phi = np.meshgrid(lat, phi, indexing="ij")
    x = np.cos(lat) * np.cos(phi)
    y = np.sin(lat)
    z = np.cos(lat) * np.sin(phi)
    weight = np.cos(lat) * (2 * np.pi / width) * (np.pi / height)
    basis = np.stack(
        [
            np.full_like(x, 0.282095),
            0.488603 * y,
            0.488603 * z,
            0.488603 * x,
            1.092548 * x * y,
            1.092548 * y * z,
            0.315392 * (3 * z * z - 1),
            1.092548 * x * z,
            0.546274 * (x * x - y * y),
        ]
    )
    return np.einsum("khw,hw,hwc->kc", basis, weight, radiance.astype(np.float64))
