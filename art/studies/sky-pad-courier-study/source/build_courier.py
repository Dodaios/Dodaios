"""Author the sky-pad courier: a slender chrome starship for the Dodaios Verse.

Run headless, it builds the ship from lofted sections, saves the editable
source next to this script and leaves three collections for the study
exporter (one per level of detail):

    blender --background --factory-startup --python build_courier.py

Shape language: a long, flat lens of a hull with a crisp blade edge all
round and needle points at both ends; a raised bridge with a dark visor; two
slim engine pods on swept wings, each with a pointed intake cone, ringed
bodies, a nozzle bell with a glowing core and a long tail spike; a keel fin,
a dorsal fin and mast, gold on every edge that matters and navigation lights.

Units are metres, Blender's +Y is the nose (glTF -Z after export), +Z up.
Every lofted part gets ordered UVs (u round the section, v along the ship),
so the runtime's panel map lays its plates along the hull. The hull's origin
is its middle; the gear reaches GEAR_DROP below the belly. Named nodes the
runtime drives: Gear_Nose, Gear_Left, Gear_Right (raised by GEAR_TRAVEL) and
the EngineGlow material.
"""

from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy

HERE = Path(__file__).resolve().parent
LENGTH = 30.0
HALF_WIDTH = 4.0
TOP = 1.15
BOTTOM = 0.7
GEAR_DROP = 2.3
GEAR_TRAVEL = 1.9
POD_X = 5.9
POD_Z = -0.15
POD_R = 0.64
# The pods run from just ahead of the middle to past the tail.
POD_FRONT = 1.5
EXHAUST_Y = -13.4
SPIKE_TIP = -20.5


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, colour, metallic, roughness, emission=None, strength=0.0):
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


def mesh_from_rings(name, rings, closed, cap_start=False, cap_end=False):
    """A surface through rings of points (all the same length), with ordered UVs."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    verts = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    span = n if closed else n - 1
    for i in range(len(rings) - 1):
        for k in range(span):
            k1 = (k + 1) % n
            face = bm.faces.new((verts[i][k], verts[i][k1], verts[i + 1][k1], verts[i + 1][k]))
            corners = ((k, i), (k + 1, i), (k + 1, i + 1), (k, i + 1))
            for loop, (a, b) in zip(face.loops, corners, strict=True):
                loop[uv_layer].uv = (a / span, b / (len(rings) - 1))
    for flag, ring, first in ((cap_start, verts[0], True), (cap_end, verts[-1], False)):
        if flag:
            face = bm.faces.new(list(reversed(ring)) if first else ring)
            for loop in face.loops:
                loop[uv_layer].uv = (0.5, 0.5)
            bmesh.ops.triangulate(bm, faces=[face])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def lens_ring(cx, y, cz, half_w, top, bottom, count=28):
    """A lens section: a domed top and a flatter belly meeting in a blade edge at both sides."""
    ring = []
    for k in range(count):
        # The top from the right edge to the left one, then the belly back.
        u = 1 - 2 * k / count
        ring.append((cx + half_w * u, y, cz + top * (1 - u * u) ** 0.62))
    for k in range(count):
        u = -1 + 2 * k / count
        ring.append((cx + half_w * u, y, cz - bottom * (1 - u * u) ** 0.8))
    return ring


def hull_shape(t: float) -> tuple[float, float, float]:
    """Half width, top and belly height at t (0 tail tip, 1 nose tip)."""
    u = t**0.92
    body = math.sin(math.pi * u)
    return HALF_WIDTH * body**0.72, TOP * body**1.05, BOTTOM * body**1.15


def hull_y(t: float) -> float:
    return -LENGTH / 2 + t * LENGTH


def hull_point(t: float, u: float, upper: bool, lift: float = 0.0):
    """A point on the hull at t along and u across it (-1 left .. 1 right edge), raised by lift."""
    w, top, bottom = hull_shape(t)
    z = top * (1 - u * u) ** 0.62 + lift if upper else -bottom * (1 - u * u) ** 0.8 - lift
    return (w * u, hull_y(t), z)


def build_hull():
    """The hull as two shells meeting at the blade edge: the chrome back and the charcoal belly."""
    halves = []
    n, count = 140, 28
    for upper in (True, False):
        rings = []
        for i in range(1, n):
            t = i / n
            # Upper: right edge to left edge; belly: left edge to right edge.
            us = [1 - 2 * k / count for k in range(count + 1)]
            rings.append([hull_point(t, u if upper else -u, upper) for u in us])
        obj = mesh_from_rings("Hull" if upper else "Belly", rings, closed=False)
        # The blade edge stays crisp, the domes stay smooth.
        obj.data.set_sharp_from_angle(angle=math.radians(38))
        halves.append(obj)
    return halves


def ribbon(name, points, sides, half=0.035):
    """A thin strip through `points`, `sides` giving each point's sideways unit vector."""
    rings = [
        [
            (p[0] - s[0] * half, p[1] - s[1] * half, p[2] - s[2] * half),
            (p[0] + s[0] * half, p[1] + s[1] * half, p[2] + s[2] * half),
        ]
        for p, s in zip(points, sides, strict=True)
    ]
    return mesh_from_rings(name, rings, closed=False)


def build_seams():
    """Panel seams on the chrome back: two lines along it, rings across it fore and aft."""
    strips = []
    for u in (-0.42, 0.42):
        pts = [hull_point(i / 100, u, True, 0.012) for i in range(14, 92)]
        strips.append(ribbon(f"SeamLong_{u}", pts, [(1, 0, 0)] * len(pts)))
    for t in (0.22, 0.31, 0.4, 0.49, 0.88):
        pts = [hull_point(t, -0.94 + 1.88 * k / 40, True, 0.012) for k in range(41)]
        strips.append(ribbon(f"SeamCross_{t}", pts, [(0, 1, 0)] * len(pts)))
    return join(strips, "Seams")


def build_vents():
    """Dark vent plates on the belly, in pairs either side of the keel."""
    plates = []
    for t0, t1 in ((0.3, 0.4), (0.44, 0.52), (0.6, 0.66)):
        for side in (-1, 1):
            rings = []
            for i in range(6):
                t = t0 + (t1 - t0) * i / 5
                rings.append(
                    [hull_point(t, side * (0.18 + 0.32 * k / 4), False, 0.01) for k in range(5)]
                )
            plates.append(mesh_from_rings(f"Vent_{t0}_{side}", rings, closed=False))
    return join(plates, "Vents")


def hull_top_at(y: float) -> float:
    return hull_shape((y + LENGTH / 2) / LENGTH)[1]


def build_bridge():
    """The raised bridge on the forward back, and the dark visor wrapped round its front."""
    rings, visor = [], []
    y0, y1 = 1.5, 11.0
    n = 50
    for i in range(1, n):
        s = i / n
        y = y0 + s * (y1 - y0)
        shape = math.sin(math.pi * s**0.8) ** 0.7
        base = hull_top_at(y) - 0.25
        rings.append(
            lens_ring(
                0, y, base, 1.85 * shape + 0.01, 0.78 * shape + 0.005, 0.2 * shape + 0.003, 18
            )
        )
        if 0.5 < s < 0.96:
            # The visor: the bridge's front shell, a hair larger.
            visor.append(
                lens_ring(0, y, base, 1.87 * shape + 0.01, 0.795 * shape + 0.006, 0.0, 18)[:18]
            )
    bridge = mesh_from_rings("Bridge", rings, closed=True, cap_start=True, cap_end=True)
    glass = mesh_from_rings("Visor", visor, closed=False)
    return bridge, glass


def build_visor_frames():
    """Chrome mullions across the visor: one down its middle, one either side."""
    strips = []
    y0, y1 = 1.5, 11.0
    for u in (-0.55, 0.0, 0.55):
        pts = []
        for i in range(26, 48):
            s = i / 50
            y = y0 + s * (y1 - y0)
            shape = math.sin(math.pi * s**0.8) ** 0.7
            base = hull_top_at(y) - 0.25
            hw, top = 1.87 * shape + 0.01, 0.795 * shape + 0.006
            pts.append((hw * u, y, base + top * (1 - u * u) ** 0.62 + 0.01))
        strips.append(ribbon(f"Mullion_{u}", pts, [(1, 0, 0)] * len(pts), 0.03))
    return join(strips, "VisorFrames")


def build_stabilisers(side: int):
    """Four small swept fins in an X round the root of a pod's tail spike."""
    fins = []
    x0 = side * POD_X
    for j in range(4):
        a = math.pi / 4 + j * math.pi / 2
        ca, sa = math.cos(a), math.sin(a)
        rings = []
        for s_, (yf, yb, r) in enumerate(
            ((EXHAUST_Y - 1.3, EXHAUST_Y - 3.6, 0.34), (EXHAUST_Y - 2.4, EXHAUST_Y - 3.9, 1.05))
        ):
            thick = 0.05 if s_ == 0 else 0.02
            nx, nz = -sa * thick, ca * thick
            rings.append(
                [
                    (x0 + ca * r + nx, yf, POD_Z + sa * r + nz),
                    (x0 + ca * r + nx, yb, POD_Z + sa * r + nz),
                    (x0 + ca * r - nx, yb, POD_Z + sa * r - nz),
                    (x0 + ca * r - nx, yf, POD_Z + sa * r - nz),
                ]
            )
        fins.append(
            mesh_from_rings(f"Fin_{side}_{j}", rings, closed=True, cap_start=True, cap_end=True)
        )
    return join(fins, f"Stabilisers_{side}")


def pod_radius(s: float) -> float:
    """A pod's radius along it, s from its spike's tip (0) to its intake's point (1)."""
    body = 0.08 + 0.92 * smoothstep(0.0, 0.2, s)
    intake = 1 - smoothstep(0.86, 1.0, s) ** 1.6
    return POD_R * body * max(intake, 0.004)


POD_NOSE = POD_FRONT + 2.5


def build_pod(side: int):
    rings = []
    n = 120
    for i in range(1, n):
        s = i / n
        y = SPIKE_TIP + s * (POD_NOSE - SPIKE_TIP)
        r = pod_radius(s)
        rings.append(
            [
                (
                    side * POD_X + r * math.cos(2 * math.pi * k / 24),
                    y,
                    POD_Z + r * 0.94 * math.sin(2 * math.pi * k / 24),
                )
                for k in range(24)
            ]
        )
    name = f"Pod_{'Left' if side < 0 else 'Right'}"
    return mesh_from_rings(name, rings, closed=True, cap_start=True, cap_end=True)


def lathe(name, profile, x, z, segments=32):
    """A body of revolution about the y axis through (x, z): profile is (y, radius)."""
    rings = [
        [
            (
                x + r * math.cos(2 * math.pi * k / segments),
                y,
                z + r * math.sin(2 * math.pi * k / segments),
            )
            for k in range(segments)
        ]
        for y, r in profile
    ]
    return mesh_from_rings(name, rings, closed=True)


def build_nozzle(side: int):
    """The nozzle at the back of a pod's body, flush with its skin, and the glowing core in it."""
    x = side * POD_X
    r = pod_radius((EXHAUST_Y + 0.6 - SPIKE_TIP) / (POD_NOSE - SPIKE_TIP))
    profile = [
        (EXHAUST_Y + 0.6, r + 0.002),
        (EXHAUST_Y, r * 1.04),
        (EXHAUST_Y - 0.35, r * 1.0),
        (EXHAUST_Y - 0.38, r * 0.8),
        (EXHAUST_Y + 0.3, r * 0.62),
    ]
    core_profile = [
        (EXHAUST_Y + 0.28, r * 0.64),
        (EXHAUST_Y - 0.2, r * 0.76),
        (EXHAUST_Y - 0.26, 0.01),
    ]
    return lathe(f"Nozzle_{side}", profile, x, POD_Z), lathe(f"Core_{side}", core_profile, x, POD_Z)


def build_bands(side: int):
    """Gold bands round a pod: behind the intake cone, two on the body, one at the spike's root."""
    out = []
    for i, y in enumerate((POD_FRONT - 0.4, -4.0, -9.5, EXHAUST_Y - 1.4)):
        r = pod_radius((y - SPIKE_TIP) / (POD_NOSE - SPIKE_TIP))
        # Flush with the skin: a band you could run a finger over, not a hoop.
        profile = [
            (y + 0.16, r - 0.004),
            (y + 0.12, r + 0.012),
            (y - 0.12, r + 0.012),
            (y - 0.16, r - 0.004),
        ]
        out.append(lathe(f"Band_{side}_{i}", profile, side * POD_X, POD_Z, 32))
    return out


def build_wing(side: int):
    """A swept wing from the hull's blade edge to the pod: a thin airfoil plate, sharp in front."""
    root_front, root_back = -2.5, -10.5
    tip_front, tip_back = -5.2, -11.8
    rings = []
    for j in range(9):
        s = j / 8
        x = side * (2.4 + s * (POD_X - 0.55 - 2.4))
        yf = root_front + s * (tip_front - root_front)
        yb = root_back + s * (tip_back - root_back)
        z = POD_Z * s + 0.02
        chord = yf - yb
        thick = 0.2 * (1 - 0.4 * s)
        ring = []
        for k in range(12):
            a = k / 11
            # An airfoil: thickest near the front quarter, thin at the trailing edge.
            ring.append((x, yf - a * chord, z + thick * math.sin(math.pi * (1 - a) ** 0.6) * 0.5))
        for k in range(12):
            a = 1 - k / 11
            ring.append((x, yf - a * chord, z - thick * math.sin(math.pi * (1 - a) ** 0.6) * 0.35))
        rings.append(ring)
    name = f"Wing_{'Left' if side < 0 else 'Right'}"
    return mesh_from_rings(name, rings, closed=True, cap_start=True, cap_end=True)


def build_fin(name, base_front, base_back, tip_front, tip_back, z0, height, thick):
    """A thin swept fin standing on (or hanging from) the hull's centre line."""
    rings = []
    for j in range(6):
        s = j / 5
        z = z0 + s * height
        yf = base_front + s * (tip_front - base_front)
        yb = base_back + s * (tip_back - base_back)
        t = thick * (1 - 0.7 * s)
        ring = [(0.0, yf, z)]
        for k in range(1, 10):
            a = k / 10
            ring.append((t * math.sin(math.pi * a**0.7), yf - a * (yf - yb), z))
        ring.append((0.0, yb, z))
        for k in range(9, 0, -1):
            a = k / 10
            ring.append((-t * math.sin(math.pi * a**0.7), yf - a * (yf - yb), z))
        rings.append(ring)
    return mesh_from_rings(name, rings, closed=True, cap_start=True, cap_end=True)


def join(objs, name):
    for o in objs:
        bpy.context.scene.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    out = bpy.context.active_object
    out.name = name
    bpy.context.scene.collection.objects.unlink(out)
    return out


def build_edge_trim():
    """A gold strip along the blade edge, and a light strip on the belly just inside it."""
    trims, lights = [], []
    n = 120
    for i in range(6, n - 5):
        t = i / n
        w, _top, bottom = hull_shape(t)
        y = hull_y(t)
        trims.append(
            [
                (w + 0.03, y, 0.05),
                (w + 0.05, y, 0.0),
                (w + 0.03, y, -0.05),
                (-w - 0.03, y, -0.05),
                (-w - 0.05, y, 0.0),
                (-w - 0.03, y, 0.05),
            ]
        )
        lights.append(
            [
                (w * 0.86, y, -bottom * 0.42),
                (w * 0.84, y, -bottom * 0.46),
                (-w * 0.84, y, -bottom * 0.46),
                (-w * 0.86, y, -bottom * 0.42),
            ]
        )
    right = mesh_from_rings("TrimRight", [r[:3] for r in trims], closed=False)
    left = mesh_from_rings("TrimLeft", [r[3:] for r in trims], closed=False)
    strip_r = mesh_from_rings("StripRight", [r[:2] for r in lights], closed=False)
    strip_l = mesh_from_rings("StripLeft", [r[2:] for r in lights], closed=False)
    return join([right, left], "EdgeTrim"), join([strip_r, strip_l], "LightStrip")


def tip(name, y_from, y_to, x, z, r):
    """A gold needle point: a cone from radius r at y_from to a point at y_to."""
    return lathe(
        name, [(y_from, r), (y_from + (y_to - y_from) * 0.5, r * 0.45), (y_to, 0.002)], x, z, 16
    )


def sphere(name, location, radius):
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius, segments=12, ring_count=8, location=location
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    for c in obj.users_collection:
        c.objects.unlink(obj)
    return obj


def cylinder(name, radius, depth, location, vertices=16, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=depth, vertices=vertices, location=location, rotation=rotation
    )
    obj = bpy.context.active_object
    obj.name = name
    bpy.ops.object.shade_smooth()
    for c in obj.users_collection:
        c.objects.unlink(obj)
    return obj


def gear(name, x, y, mats, collection):
    """A gear leg under its own empty (strut, piston, link, foot), so the runtime can retract it."""
    root = bpy.data.objects.new(name, None)
    root.location = (x, y, -BOTTOM * 0.9)
    collection.objects.link(root)
    parts = [
        (cylinder(f"{name}_Upper", 0.2, 1.2, (0, 0, -0.6), 14), "graphite"),
        (cylinder(f"{name}_Piston", 0.12, 1.2, (0, 0, -1.55), 14), "chrome"),
        (cylinder(f"{name}_Link", 0.05, 0.9, (0.18, 0, -1.2), 8, (0, 0.35, 0)), "gold"),
        (cylinder(f"{name}_Foot", 0.6, 0.12, (0, 0, -GEAR_DROP + 0.06), 24), "graphite"),
        (cylinder(f"{name}_Pad", 0.48, 0.05, (0, 0, -GEAR_DROP + 0.145), 24), "gold"),
        (cylinder(f"{name}_Collar", 0.3, 0.3, (0, 0, -0.12), 18), "gold"),
    ]
    for part, key in parts:
        part.data.materials.append(mats[key])
        collection.objects.link(part)
        part.parent = root


def main() -> None:
    reset_scene()
    mats = {
        "chrome": material("Chrome", (0.86, 0.88, 0.91), 1.0, 0.09),
        "gold": material("Gold", (0.83, 0.64, 0.30), 1.0, 0.22),
        "graphite": material("Graphite", (0.06, 0.065, 0.08), 0.6, 0.4),
        "belly": material("Belly", (0.16, 0.17, 0.19), 0.85, 0.3),
        "vent": material("Vent", (0.02, 0.022, 0.03), 0.5, 0.6),
        "glass": material("CanopyGlass", (0.02, 0.035, 0.07), 0.4, 0.04),
        "glow": material("EngineGlow", (0.4, 0.8, 1.0), 0.0, 0.3, (0.45, 0.85, 1.0), 6.0),
        "strip": material("LightStrip", (0.6, 0.9, 1.0), 0.0, 0.4, (0.55, 0.9, 1.0), 3.0),
        "red": material("NavRed", (1, 0.1, 0.1), 0.0, 0.4, (1, 0.1, 0.08), 8.0),
        "green": material("NavGreen", (0.1, 1, 0.3), 0.0, 0.4, (0.1, 1, 0.3), 8.0),
        "white": material("NavWhite", (1, 1, 1), 0.0, 0.4, (1, 1, 1), 8.0),
    }
    lod0 = bpy.data.collections.new("CourierLOD0")
    bpy.context.scene.collection.children.link(lod0)

    def add(obj, key):
        obj.data.materials.clear()
        obj.data.materials.append(mats[key])
        lod0.objects.link(obj)
        return obj

    back, belly = build_hull()
    add(back, "chrome")
    add(belly, "belly")
    add(build_seams(), "graphite")
    add(build_vents(), "vent")
    add(build_visor_frames(), "chrome")
    bridge, visor = build_bridge()
    add(bridge, "chrome")
    add(visor, "glass")
    trim, strip = build_edge_trim()
    add(trim, "gold")
    add(strip, "strip")
    # Gold needle points at the nose and the tail.
    add(tip("NoseTip", hull_y(0.965), hull_y(1.0) + 0.6, 0, 0, hull_shape(0.965)[1] * 0.7), "gold")
    add(tip("TailTip", hull_y(0.035), hull_y(0.0) - 0.6, 0, 0, hull_shape(0.035)[1] * 0.7), "gold")
    # A keel fin under the stern, a low dorsal fin and a sensor mast on the back.
    add(build_fin("Keel", -6.0, -12.0, -9.5, -13.6, -BOTTOM * 0.5, -1.5, 0.16), "chrome")
    add(build_fin("Dorsal", -5.0, -10.5, -8.6, -11.4, TOP * 0.6, 1.0, 0.12), "chrome")
    # Two gold pinstripes from the bridge to the nose: the house's colour on the ship's face.
    for u in (-0.07, 0.07):
        pts = [hull_point(t / 200, u, True, 0.013) for t in range(176, 192)]
        add(ribbon(f"Pinstripe_{u}", pts, [(1, 0, 0)] * len(pts), 0.025), "gold")
    for side in (-1, 1):
        add(build_pod(side), "chrome")
        add(build_wing(side), "chrome")
        bell, core = build_nozzle(side)
        add(bell, "graphite")
        add(core, "glow")
        for band in build_bands(side):
            add(band, "gold")
        add(build_stabilisers(side), "chrome")
        # A gold leading edge on the wing.
        lead = [
            (
                side * (2.4 + s * (POD_X - 0.55 - 2.4)),
                -2.5 + s * (-5.2 + 2.5) + 0.04,
                POD_Z * s + 0.05,
            )
            for s in [k / 16 for k in range(17)]
        ]
        add(ribbon(f"WingEdge_{side}", lead, [(0, 0, 1)] * len(lead), 0.03), "gold")
        add(
            tip(f"SpikeTip_{side}", SPIKE_TIP + 1.6, SPIKE_TIP - 0.3, side * POD_X, POD_Z, 0.12),
            "gold",
        )
        add(
            tip(f"IntakeTip_{side}", POD_FRONT + 1.6, POD_NOSE + 0.4, side * POD_X, POD_Z, 0.14),
            "gold",
        )
        # Navigation lights on the pods' outer flanks: red to port (left), green to starboard.
        nav = sphere(f"Nav_{side}", (side * (POD_X + POD_R * 0.9), -6.0, POD_Z), 0.09)
        add(nav, "red" if side < 0 else "green")
    add(sphere("TailLight", (0, hull_y(0.06), 0.15), 0.08), "white")
    gear("Gear_Nose", 0.0, 7.5, mats, lod0)
    gear("Gear_Left", -2.5, -5.0, mats, lod0)
    gear("Gear_Right", 2.5, -5.0, mats, lod0)

    # One mesh per material for everything that does not move: a dozen draw calls instead of sixty.
    movable = {o for o in lod0.objects if o.parent is not None or o.type != "MESH"}
    by_material: dict[str, list] = {}
    for obj in lod0.objects:
        if obj not in movable:
            by_material.setdefault(obj.data.materials[0].name, []).append(obj)
    for name, objs in by_material.items():
        if len(objs) > 1:
            for o in objs:
                lod0.objects.unlink(o)
            merged = join(objs, f"Body_{name}")
            lod0.objects.link(merged)

    # Lower levels of detail: decimated copies. The gear and the glow keep their names,
    # so the runtime drives every level.
    for name, ratio in (("CourierLOD1", 0.4), ("CourierLOD2", 0.12)):
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
        copies = {}
        for obj in lod0.objects:
            copy = obj.copy()
            if obj.data is not None:
                copy.data = obj.data.copy()
            coll.objects.link(copy)
            copies[obj] = copy
        for obj, copy in copies.items():
            if obj.parent is not None:
                copy.parent = copies[obj.parent]
            if copy.type == "MESH" and len(copy.data.polygons) > 300:
                dec = copy.modifiers.new("Decimate", "DECIMATE")
                dec.ratio = ratio
                bpy.context.view_layer.objects.active = copy
                bpy.ops.object.modifier_apply(modifier=dec.name)
    bpy.ops.wm.save_as_mainfile(filepath=str(HERE / "courier.blend"))
    for coll in bpy.data.collections:
        meshes = [o for o in coll.objects if o.type == "MESH"]
        tris = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes)
        print(f"{coll.name}: {tris} triangles")


if __name__ == "__main__":
    main()
