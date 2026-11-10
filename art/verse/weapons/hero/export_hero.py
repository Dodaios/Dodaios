"""Bake and export the hero Graveline for the first-person view (bpy, Cycles).

    python scripts/verse/blender.py run art/verse/weapons/hero/export_hero.py [-- size]

1. Builds the model (`graveline.build`), applies every modifier and joins the
   parts into one mesh with a vertex group per bone.
2. Unwraps the opaque parts into one atlas and bakes the procedural materials
   into `T_Weapon_GravelineHero_BC/_ORM/_NDX` (ORM: R ambient occlusion,
   G roughness, B metallic; normal with green flipped for Unreal).
3. Merges the opaque slots into `M_Weapon_GravelineHero`; glass and reticle
   keep `M_Weapon_Optic` and `M_Weapon_Reticle`.
4. Writes `SK_Weapon_GravelineHero.fbx` with the WP14 bones and this mesh's
   sockets, and the import records next to the WP14 Graveline's.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from lib import unreal_export as ux

from weapons import export as wexport
from weapons import specs
from weapons.hero import graveline, kit

REPO = Path(__file__).resolve().parents[4]
ASSET = "SK_Weapon_GravelineHero"
SKELETON = "SKEL_Weapon_GravelineHero"
FOLDER = "/Game/Verse/Weapons/GravelineHero"
SKIN = "M_Weapon_GravelineHero"
TEXTURE_OUT = REPO / "art/verse/.cache/weapons/hero"
FBX_OUT = REPO / "art/verse/.cache/unreal/weapons"
RECORDS = REPO / "unreal/Verse/Art/Import/Weapons/GravelineHero"
KEEP_SLOTS = ("M_Weapon_Optic", "M_Weapon_Reticle")
MI_ROOT = "/Game/Verse/Materials/Instances/Weapons"

SPEC = specs.WeaponSpec(
    weapon_id="graveline",
    display_name="GravelineHero",
    role="assault rifle, first-person hero mesh",
    asset=ASSET,
    kind="skeletal",
    bones=specs.GRAVELINE.bones,
    sockets=tuple(specs.Socket(n, "Root", loc) for n, loc in graveline.SOCKETS.items()),
    triangle_cap=specs.MAX_FIRST_PERSON_TRIANGLES * 2,
)


def _select_only(objs, active=None):
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[0]


def join_parts() -> bpy.types.Object:
    col = bpy.data.collections[kit.COLLECTION]
    parts = [o for o in col.objects if o.type == "MESH" and not o.get("cutter")]
    cutters = [o for o in col.objects if o.get("cutter")]
    deps = bpy.context.evaluated_depsgraph_get()
    baked = []
    for obj in parts:
        mesh = bpy.data.meshes.new_from_object(
            obj.evaluated_get(deps), preserve_all_data_layers=True, depsgraph=deps
        )
        new = bpy.data.objects.new(obj.name + "_J", mesh)
        new.matrix_world = obj.matrix_world.copy()
        col.objects.link(new)
        group = new.vertex_groups.new(name=obj.get("bone", "Root"))
        group.add(range(len(mesh.vertices)), 1.0, "REPLACE")
        baked.append(new)
    for obj in parts + cutters:
        bpy.data.objects.remove(obj)
    _select_only(baked)
    body = baked[0]
    ctx = {"active_object": body, "selected_objects": baked, "selected_editable_objects": baked}
    with bpy.context.temp_override(**ctx):
        bpy.ops.object.join()
    body.name = ASSET
    body.data.name = ASSET
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return body


def unwrap(body) -> None:
    """Planar charts per connected face set of one dominant axis, shelf-packed into 0..1.

    Smart projection needs a window, so the export does its own: every chart keeps its
    true scale (uniform texel density), which a weapon seen up close needs.
    """
    from mathutils import Vector

    bm = bmesh.new()
    bm.from_mesh(body.data)
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.verify()
    axes = [
        Vector(a) for a in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
    ]

    def axis_of(face):
        return max(range(6), key=lambda i: face.normal.dot(axes[i]))

    label = {f.index: axis_of(f) for f in bm.faces}
    seen = set()
    charts = []
    for f in bm.faces:
        if f.index in seen:
            continue
        ax = label[f.index]
        stack, chart = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            chart.append(cur)
            for e in cur.edges:
                for nb in e.link_faces:
                    if nb.index not in seen and label[nb.index] == ax:
                        seen.add(nb.index)
                        stack.append(nb)
        charts.append((ax, chart))

    def project(ax, co):
        i = ax // 2
        if i == 0:
            return (co.y, co.z)
        if i == 1:
            return (co.x, co.z)
        return (co.x, co.y)

    boxes = []
    for ax, chart in charts:
        pts = [project(ax, l.vert.co) for f in chart for l in f.loops]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes.append((ax, chart, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    pad = 0.0012  # metres between charts
    area = sum((w + pad) * (h + pad) for *_, w, h in boxes)
    side = area**0.5 * 1.08
    boxes.sort(key=lambda b: -b[5])
    x = y = shelf = 0.0
    placed = []
    for ax, chart, x0, y0, w, h in boxes:
        if x + w > side:
            x, y, shelf = 0.0, y + shelf + pad, 0.0
        placed.append((ax, chart, x0, y0, x, y))
        x += w + pad
        shelf = max(shelf, h)
    extent = max(side, y + shelf)
    for ax, chart, x0, y0, ox, oy in placed:
        for f in chart:
            for l in f.loops:
                px, py = project(ax, l.vert.co)
                l[uv].uv = ((px - x0 + ox) / extent, (py - y0 + oy) / extent)
    bm.to_mesh(body.data)
    bm.free()
    print(f"[hero] unwrap: {len(charts)} charts, atlas side {extent * 100:.1f} cm")


def _baked_materials(body):
    return [m for m in body.data.materials if m and m.name not in KEEP_SLOTS]


def _target(body, image):
    for mat in _baked_materials(body):
        nodes = mat.node_tree.nodes
        node = nodes.get("BakeTarget") or nodes.new("ShaderNodeTexImage")
        node.name = "BakeTarget"
        node.image = image
        nodes.active = node


def _bake(body, kind, image, **kw):
    _target(body, image)
    _select_only([body])
    bpy.ops.object.bake(type=kind, margin=8, use_clear=True, **kw)


def _image(name, size, colour):
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=not colour)
    img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    return img


def _pixels(img):
    return np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)


def _metallic_to_emission(body, on: bool):
    """Route each material's metallic input to the output as emission, or restore it."""
    for mat in _baked_materials(body):
        nt = mat.node_tree
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        if on:
            em = nt.nodes.new("ShaderNodeEmission")
            em.name = "MetalProbe"
            src = bsdf.inputs["Metallic"]
            if src.is_linked:
                nt.links.new(src.links[0].from_socket, em.inputs["Color"])
            else:
                v = src.default_value
                em.inputs["Color"].default_value = (v, v, v, 1.0)
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        else:
            nt.nodes.remove(nt.nodes["MetalProbe"])
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def bake(body, size: int) -> dict:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 32
    scene.render.bake.use_selected_to_active = False
    TEXTURE_OUT.mkdir(parents=True, exist_ok=True)

    bc = _image("BC", size, True)
    _bake(body, "DIFFUSE", bc, pass_filter={"COLOR"})
    rough = _image("Rough", size, False)
    _bake(body, "ROUGHNESS", rough)
    ao = _image("AO", size, False)
    _bake(body, "AO", ao)
    _metallic_to_emission(body, True)
    metal = _image("Metal", size, False)
    _bake(body, "EMIT", metal)
    _metallic_to_emission(body, False)
    normal = _image("Normal", size, False)
    _bake(body, "NORMAL", normal, normal_space="TANGENT")

    out = {}

    def save(name, array, colour):
        img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
        img.colorspace_settings.name = "sRGB" if colour else "Non-Color"
        img.pixels[:] = array.reshape(-1)
        path = TEXTURE_OUT / f"{name}.png"
        img.filepath_raw = str(path)
        img.file_format = "PNG"
        img.save()
        out[name] = str(path)

    stem = "T_Weapon_GravelineHero"
    save(f"{stem}_BC", _pixels(bc), True)
    orm = np.ones((size, size, 4), dtype=np.float32)
    orm[..., 0] = _pixels(ao)[..., 0]
    orm[..., 1] = _pixels(rough)[..., 0]
    orm[..., 2] = _pixels(metal)[..., 0]
    save(f"{stem}_ORM", orm, False)
    nrm = _pixels(normal).copy()
    nrm[..., 1] = 1.0 - nrm[..., 1]  # OpenGL -> DirectX green
    save(f"{stem}_NDX", nrm, False)
    return out


def merge_slots(body) -> None:
    skin = bpy.data.materials.new(SKIN)
    mats = list(body.data.materials)
    keep = {m.name: m for m in mats if m and m.name in KEEP_SLOTS}
    new_order = [skin, *[keep[n] for n in KEEP_SLOTS if n in keep]]
    index_of = {}
    for i, m in enumerate(mats):
        index_of[i] = new_order.index(keep[m.name]) if m and m.name in keep else 0
    bm = bmesh.new()
    bm.from_mesh(body.data)
    for f in bm.faces:
        f.material_index = index_of.get(f.material_index, 0)
    bm.to_mesh(body.data)
    bm.free()
    body.data.materials.clear()
    for m in new_order:
        body.data.materials.append(m)


def armature(body):
    scene = ux._export_scene()
    for obj in (body,):
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        scene.objects.link(obj)
    arm_data = bpy.data.armatures.new(f"{ASSET}_Data")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    scene.objects.link(arm_obj)
    bpy.context.view_layer.update()
    _select_only([arm_obj])
    bpy.ops.object.mode_set(mode="EDIT")
    for bone in specs.export_bones(SPEC):
        eb = arm_data.edit_bones.new(bone.name)
        eb.head, eb.tail, eb.roll, eb.use_deform = bone.head, bone.tail, 0.0, True
        if bone.parent:
            eb.parent = arm_data.edit_bones[bone.parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    body.parent = arm_obj
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm_obj
    return arm_obj


def records(result: dict) -> None:
    RECORDS.mkdir(parents=True, exist_ok=True)
    source = {
        "args": {"asset": ASSET},
        "builder": "art/verse/weapons/hero/export_hero.py",
        "function": "main",
    }
    slots = [
        {"mi": f"{MI_ROOT}/MI_Weapon_GravelineHero.MI_Weapon_GravelineHero", "slot": SKIN},
        {"mi": f"{MI_ROOT}/MI_Weapon_OpticHero.MI_Weapon_OpticHero", "slot": "M_Weapon_Optic"},
        {
            "mi": f"{MI_ROOT}/MI_Weapon_ReticleHero.MI_Weapon_ReticleHero",
            "slot": "M_Weapon_Reticle",
        },
    ]
    export = {
        "blender": bpy.app.version_string.split(" ")[0],
        "file": f"art/verse/.cache/unreal/weapons/{ASSET}.fbx",
        "format": "fbx",
        "settings_id": "fbx-ue/1",
        "sha256": result["sha256"],
    }
    mesh = {
        "bones": [b.name for b in specs.export_bones(SPEC)],
        "bounds_cm": result["bounds_cm"],
        "material_slots": slots,
        "sockets": sorted(SPEC.socket_names()),
        "triangles": result["triangles"],
        "uv_sets": 1,
        "vertices": result["vertices"],
    }
    common = {"license": {"kind": "own"}, "lightmap": "none", "owner": "WP14"}
    common.update({"schema": "verse.import/1", "source": source})
    sk = {
        "asset_path": f"{FOLDER}/{ASSET}.{ASSET}",
        "collision": {"primitives": 0, "profile": "Verse_NoCollision", "source": "none"},
        "export": export,
        "kind": "skeletal_mesh",
        "lod": {"mode": "single"},
        "mesh": mesh,
        "name": ASSET,
        "nanite": {"enabled": False},
        **common,
    }
    skel = {
        "asset_path": f"{FOLDER}/{SKELETON}.{SKELETON}",
        "export": export,
        "kind": "skeleton",
        "mesh": {**mesh, "material_slots": []},
        "name": SKELETON,
        **common,
    }
    for rec in (sk, skel):
        path = RECORDS / f"{rec['name']}.import.json"
        path.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(size: int) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    graveline.build()
    body = join_parts()
    unwrap(body)
    textures = bake(body, size)
    merge_slots(body)
    triangles = ux.triangle_count(body.data)
    vertices = len(body.data.vertices)
    box = ux.bounds_cm(body.data)
    arm = armature(body)
    digest = wexport._write_skeletal_fbx(SPEC, arm, body, FBX_OUT / f"{ASSET}.fbx")
    result = {"sha256": digest, "triangles": triangles, "vertices": vertices, "bounds_cm": box}
    records(result)
    print(json.dumps({"textures": textures, **result}, indent=1))


if __name__ == "__main__":
    args = sys.argv[1:]
    main(int(args[0]) if args else 4096)
