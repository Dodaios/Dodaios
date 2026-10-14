"""Author the sky-pad courier: a slender chrome starship for the Dodaios Verse.

Run headless, it builds the ship from lofted sections, saves the editable
source next to this script and leaves three collections for the study
exporter (one per level of detail):

    blender --background --factory-startup --python build_courier.py

Units are metres, Blender's +Y is the nose (glTF -Z after export), +Z up.
The hull's origin is its middle; the landing gear reaches GEAR_DROP below the
hull's belly, so a landed ship stands with its origin LANDED_HEIGHT above the
pad. Named nodes the runtime drives: Gear_Nose, Gear_Left, Gear_Right (raised
by moving them up GEAR_TRAVEL) and the EngineGlow material (its emission is
the throttle).
"""

from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy

HERE = Path(__file__).resolve().parent
LENGTH = 30.0
HULL_HALF_WIDTH = 4.2
HULL_HALF_HEIGHT = 1.35
GEAR_DROP = 2.3
GEAR_TRAVEL = 1.9
NACELLE_X = 6.6
NACELLE_RADIUS = 1.1
# Where each pod's body ends in its exhaust ring and the spike behind it begins.
EXHAUST_Y = -12.6


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def material(
    name: str,
    colour: tuple[float, float, float],
    metallic: float,
    roughness: float,
    emission: tuple[float, float, float] | None = None,
    strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*colour, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


def smoothstep(e0: float, e1: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def loft(
    name: str,
    sections: list[tuple[float, float, float, float, float]],
    radial: int,
    power: float,
    cap_ends: bool = True,
) -> bpy.types.Object:
    """A closed body through superellipse sections.

    Each section is (y, half width, half height, z offset, x offset).
    """
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rings = []
    for y, a, b, cz, cx in sections:
        ring = []
        for k in range(radial):
            th = 2 * math.pi * k / radial
            c, s = math.cos(th), math.sin(th)
            x = cx + a * math.copysign(abs(c) ** (2 / power), c)
            z = cz + b * math.copysign(abs(s) ** (2 / power), s)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:], strict=False):
        for k in range(radial):
            k1 = (k + 1) % radial
            bm.faces.new((r0[k], r0[k1], r1[k1], r1[k]))
    if cap_ends:
        for ring, flip in ((rings[0], True), (rings[-1], False)):
            face = bm.faces.new(ring if not flip else list(reversed(ring)))
            bmesh.ops.triangulate(bm, faces=[face])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def hull_profile(t: float) -> tuple[float, float, float]:
    """Half width, half height and centre lift of the hull at t (0 tail tip, 1 nose tip)."""
    u = t**0.8
    body = math.sin(math.pi * u)
    return HULL_HALF_WIDTH * body**0.85, HULL_HALF_HEIGHT * body**1.0, 0.18 * body


def build_hull() -> bpy.types.Object:
    sections = []
    n = 120
    for i in range(n + 1):
        t = i / n
        a, b, c = hull_profile(t)
        y = -LENGTH / 2 + t * LENGTH
        sections.append((y, max(a, 0.004), max(b, 0.003), c, 0.0))
    return loft("Hull", sections, 72, 2.5)


def hull_top(y: float) -> float:
    t = (y + LENGTH / 2) / LENGTH
    _, b, c = hull_profile(t)
    return c + b


def build_canopy() -> bpy.types.Object:
    sections = []
    y0, y1 = 3.2, 9.6
    n = 48
    for i in range(n + 1):
        s = i / n
        y = y0 + s * (y1 - y0)
        shape = math.sin(math.pi * s**0.75) ** 0.6
        a, b = 1.25 * shape, 0.85 * shape
        sections.append((y, max(a, 0.003), max(b, 0.003), hull_top(y) - 0.35, 0.0))
    return loft("Canopy", sections, 48, 2.2)


def build_belt(name: str, lift: float, thickness: float, push: float) -> bpy.types.Object:
    """A thin band round the hull at a height share `lift` of its half height."""
    sections = []
    n = 120
    for i in range(2, n - 1):
        t = i / n
        a, b, c = hull_profile(t)
        y = -LENGTH / 2 + t * LENGTH
        sections.append((y, a + push, thickness, c + lift * b, 0.0))
    return loft(name, sections, 24, 2.0)


def build_nacelle(side: int) -> bpy.types.Object:
    """An engine pod on its outrigger.

    A rounded intake, a long body and a spike behind the exhaust ring.
    """
    sections = []
    y_tail, y_front = -LENGTH / 2 - 2.2, -0.8
    n = 90
    for i in range(n + 1):
        s = i / n
        y = y_tail + s * (y_front - y_tail)
        spike = 0.12 + 0.88 * smoothstep(0.0, 0.28, s)
        nose = math.sqrt(max(0.0, 1 - smoothstep(0.86, 1.0, s) ** 2 * 0.75))
        r = NACELLE_RADIUS * spike * nose
        sections.append((y, max(r, 0.01), max(r * 0.92, 0.01), -0.25, side * NACELLE_X))
    return loft(f"Nacelle_{'Left' if side < 0 else 'Right'}", sections, 40, 2.0)


def build_pylon(side: int) -> bpy.types.Object:
    """A swept outrigger from the hull's flank to the pod: a thin airfoil plate."""
    mesh = bpy.data.meshes.new(f"Pylon_{side}")
    bm = bmesh.new()
    root_front, root_back, tip_front, tip_back = -2.0, -9.5, -4.4, -10.6
    x_root, x_tip = side * 2.6, side * (NACELLE_X - 0.6)
    half = 0.16
    pts = [
        (x_root, root_front, half),
        (x_root, root_back, half),
        (x_tip, tip_back, half * 0.7),
        (x_tip, tip_front, half * 0.7),
        (x_root, root_front, -half),
        (x_root, root_back, -half),
        (x_tip, tip_back, -half * 0.7),
        (x_tip, tip_front, -half * 0.7),
    ]
    v = [bm.verts.new(p) for p in pts]
    for f in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 3, 7, 4), (1, 5, 6, 2), (0, 4, 5, 1), (3, 2, 6, 7)):
        bm.faces.new([v[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(f"Pylon_{'Left' if side < 0 else 'Right'}", mesh)
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.12
    bevel.segments = 3
    return obj


def torus(name: str, major: float, minor: float, location, rotation) -> bpy.types.Object:
    bpy.ops.mesh.primitive_torus_add(
        major_radius=major,
        minor_radius=minor,
        major_segments=48,
        minor_segments=10,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    for c in obj.users_collection:
        c.objects.unlink(obj)
    return obj


def cylinder(
    name: str, radius: float, depth: float, location, vertices: int = 16
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=depth, vertices=vertices, location=location
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    for c in obj.users_collection:
        c.objects.unlink(obj)
    return obj


def gear(name: str, x: float, y: float, mats: dict, collection) -> None:
    """A gear leg under its own empty, so the runtime can retract it by moving the empty up."""
    belly = -HULL_HALF_HEIGHT * 0.78
    root = bpy.data.objects.new(name, None)
    root.location = (x, y, belly)
    collection.objects.link(root)
    strut = cylinder(f"{name}_Strut", 0.16, GEAR_DROP, (0, 0, -GEAR_DROP / 2), 12)
    foot = cylinder(
        f"{name}_Foot",
        0.55,
        0.14,
        (0, 0, -GEAR_DROP + 0.07 - (HULL_HALF_HEIGHT - HULL_HALF_HEIGHT * 0.78)),
        20,
    )
    foot.location.z = -GEAR_DROP + 0.07
    collar = cylinder(f"{name}_Collar", 0.3, 0.35, (0, 0, -0.2), 16)
    strut.data.materials.append(mats["dark"])
    foot.data.materials.append(mats["dark"])
    collar.data.materials.append(mats["gold"])
    for part in (strut, foot, collar):
        collection.objects.link(part)
        part.parent = root


def uv_unwrap(obj: bpy.types.Object) -> None:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.01)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)


def main() -> None:
    reset_scene()
    mats = {
        "chrome": material("Chrome", (0.86, 0.88, 0.91), 1.0, 0.09),
        "gold": material("Gold", (0.83, 0.64, 0.30), 1.0, 0.22),
        "dark": material("Graphite", (0.06, 0.065, 0.08), 0.6, 0.4),
        "glass": material("CanopyGlass", (0.03, 0.05, 0.09), 0.3, 0.05),
        "glow": material("EngineGlow", (0.4, 0.8, 1.0), 0.0, 0.3, (0.45, 0.85, 1.0), 6.0),
        "strip": material("LightStrip", (0.6, 0.9, 1.0), 0.0, 0.4, (0.55, 0.9, 1.0), 3.0),
    }
    lod0 = bpy.data.collections.new("CourierLOD0")
    bpy.context.scene.collection.children.link(lod0)

    def add(obj, mat_key):
        obj.data.materials.clear()
        obj.data.materials.append(mats[mat_key])
        lod0.objects.link(obj)
        return obj

    add(build_hull(), "chrome")
    add(build_canopy(), "glass")
    add(build_belt("TrimBelt", 0.0, 0.07, 0.035), "gold")
    add(build_belt("LightStrip", -0.42, 0.035, 0.0), "strip")
    for side in (-1, 1):
        add(build_nacelle(side), "chrome")
        add(build_pylon(side), "chrome")
        add(
            torus(
                f"Exhaust_{side}",
                NACELLE_RADIUS * 0.92,
                0.2,
                (side * NACELLE_X, EXHAUST_Y, -0.25),
                (math.pi / 2, 0, 0),
            ),
            "glow",
        )
        add(
            torus(
                f"Intake_{side}",
                NACELLE_RADIUS * 0.97,
                0.1,
                (side * NACELLE_X, -3.1, -0.25),
                (math.pi / 2, 0, 0),
            ),
            "gold",
        )
    gear("Gear_Nose", 0.0, 8.0, mats, lod0)
    gear("Gear_Left", -2.6, -6.0, mats, lod0)
    gear("Gear_Right", 2.6, -6.0, mats, lod0)

    for obj in list(lod0.objects):
        if obj.type == "MESH":
            for mod in list(obj.modifiers):
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier=mod.name)
            uv_unwrap(obj)

    # Lower levels of detail: decimated copies. The gear and glow keep their names,
    # so the runtime drives every level.
    for name, ratio in (("CourierLOD1", 0.38), ("CourierLOD2", 0.1)):
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        copies = {}
        for obj in lod0.objects:
            copy = obj.copy()
            if obj.data is not None:
                copy.data = obj.data.copy()
            copy.name = f"{obj.name}"
            coll.objects.link(copy)
            copies[obj] = copy
        for obj, copy in copies.items():
            if obj.parent is not None:
                copy.parent = copies[obj.parent]
            if copy.type == "MESH" and len(copy.data.polygons) > 200:
                dec = copy.modifiers.new("Decimate", "DECIMATE")
                dec.ratio = ratio
                bpy.context.view_layer.objects.active = copy
                bpy.ops.object.modifier_apply(modifier=dec.name)
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "courier.blend"))
    for coll in bpy.data.collections:
        tris = sum(
            sum(len(p.vertices) - 2 for p in o.data.polygons)
            for o in coll.objects
            if o.type == "MESH"
        )
        print(f"{coll.name}: {tris} triangles")


if __name__ == "__main__":
    main()
