"""Export the WP14 weapons, gadgets and VFX meshes to FBX under `fbx-ue/1` (bpy).

Called by `scripts/verse/_export_unreal_entry.py weapons`. Skeletal weapons
are exported like `lib/unreal_export.build_rig` (armature node named
`Armature`, so `Root` is the first bone). Their sockets are empties named
`SOCKET_<Name>` parented to the static bone `specs.SOCKET_BASE`: the
Interchange skeletal importer turns them into mesh sockets `<Name>`, which
`verse_pipeline.weapons` renames to the contract's `SOCKET_<Name>`
(art-pipeline 12.2) and re-binds to their spec bone. Static
gadgets and VFX go through `unreal_export.export_static_mesh`.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from lib import unreal_export as ux

from . import build, specs


def _source(asset: str, function: str) -> dict:
    return {
        "builder": "art/verse/weapons/build.py",
        "function": function,
        "module": "weapons.build",
        "args": {"asset": asset},
    }


def export_skeletal(spec: specs.WeaponSpec, out_dir: Path) -> dict:
    builder = build.Builder(spec.asset)
    fn = build.BUILDERS[spec.asset]
    fn(builder)
    mesh, groups = builder.mesh([bone.name for bone in spec.bones])
    unknown = [g for g in groups if g not in {bone.name for bone in spec.bones}]
    if unknown:
        raise ux.ExportError(f"{spec.asset}: parts on unknown bones {unknown}")
    ux.box_project_uv(mesh)
    ux.check_hygiene(mesh, spec.asset)

    scene = ux._export_scene()
    arm_data = bpy.data.armatures.new(f"{spec.asset}_Data")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    scene.objects.link(arm_obj)
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = arm_obj
    with bpy.context.temp_override(active_object=arm_obj, object=arm_obj):
        bpy.ops.object.mode_set(mode="EDIT")
        edit = arm_data.edit_bones
        for bone in specs.export_bones(spec):
            eb = edit.new(bone.name)
            eb.head = bone.head
            eb.tail = bone.tail
            eb.roll = 0.0
            eb.use_deform = True
            if bone.parent:
                eb.parent = edit[bone.parent]
        bpy.ops.object.mode_set(mode="OBJECT")

    body = bpy.data.objects.new(spec.asset, mesh)
    scene.objects.link(body)
    body.parent = arm_obj
    for name in groups:
        body.vertex_groups.new(name=name)
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm_obj

    path = out_dir / f"{spec.asset}.fbx"
    box = ux.bounds_cm(mesh)
    slots = [{"slot": ux.strip_suffix(m.name), "mi": ux._mi_path(m)} for m in mesh.materials]
    triangles = ux.triangle_count(mesh)
    vertices = len(mesh.vertices)
    digest = _write_skeletal_fbx(spec, arm_obj, body, path)
    result = ux.ExportResult(
        name=spec.asset,
        file=path,
        sha256=digest,
        triangles=triangles,
        vertices=vertices,
        bounds_cm=box,
        uv_sets=len(mesh.uv_layers),
        material_slots=slots,
        collision_primitives=0,
        sockets=sorted(spec.socket_names()),
        bones=[bone.name for bone in specs.export_bones(spec)],
    ).as_dict()
    result["source"] = _source(spec.asset, fn.__name__)
    result["kind"] = "skeletal_mesh"
    return result


def _write_skeletal_fbx(spec: specs.WeaponSpec, arm_obj, body, path: Path) -> str:
    """`unreal_export._write_fbx` plus socket empties on bones, placed after the cm scale."""
    import hashlib

    from mathutils import Matrix, Vector

    path.parent.mkdir(parents=True, exist_ok=True)
    view_layer = bpy.context.view_layer
    view_layer.update()
    ux._to_centimetres([arm_obj, body])
    scene = bpy.data.collections[ux.EXPORT_COLLECTION]
    empties = []
    for socket in spec.sockets:
        empty = bpy.data.objects.new(socket.name, None)
        scene.objects.link(empty)
        empty.parent = arm_obj
        empty.parent_type = "BONE"
        empty.parent_bone = specs.SOCKET_BASE  # re-bound to socket.bone on import
        view_layer.update()
        empty.matrix_world = Matrix.Translation(Vector(socket.location) * ux.CM)
        empties.append(empty)
    objects = [arm_obj, body, *empties]
    view_layer.update()
    units = bpy.context.scene.unit_settings
    units.scale_length = 1.0 / ux.CM
    for obj in view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    view_layer.objects.active = arm_obj
    try:
        override = bpy.context.temp_override(active_object=arm_obj, object=arm_obj)
        with override, ux._reproducible_fbx():
            result = bpy.ops.export_scene.fbx(filepath=str(path), **ux.FBX_UE_1)
    finally:
        units.scale_length = 1.0
    if "FINISHED" not in result:
        raise ux.ExportError(f"FBX export failed for {path.name}: {result}")
    ux.check_fbx_names(path, {obj.name for obj in objects})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_static(asset: str, fn, collision, out_dir: Path) -> dict:
    builder = build.Builder(asset)
    fn(builder)
    mesh, _groups = builder.mesh()
    col = bpy.data.collections.new(f"WP14_{asset}")
    obj = bpy.data.objects.new(f"{asset}_Body", mesh)
    col.objects.link(obj)
    for nn, (size, center) in enumerate(collision, start=1):
        box = build.Builder(f"UECOL_Box_{nn:02d}")
        box.box(size, center, chamfer=0.0)
        col_mesh, _ = box.mesh()
        col_mesh.materials.clear()
        col.objects.link(bpy.data.objects.new(f"UECOL_Box_{nn:02d}", col_mesh))
    result = ux.export_static_mesh(asset, col, out_dir).as_dict()
    result["source"] = _source(asset, fn.__name__)
    result["kind"] = "static_mesh"
    return result


def export_all(out_dir: Path, only: list[str] | None = None) -> list[dict]:
    results = []
    wanted = set(only or [])
    for spec in specs.ARSENAL:
        if wanted and spec.asset not in wanted:
            continue
        if spec.kind == "skeletal":
            results.append(export_skeletal(spec, out_dir))
        else:
            fn = build.BUILDERS[spec.asset]
            results.append(
                export_static(spec.asset, fn, build.GADGET_COLLISION[spec.asset], out_dir)
            )
    for vfx in specs.VFX:
        if wanted and vfx.asset not in wanted:
            continue
        results.append(export_static(vfx.asset, build.VFX_BUILDERS[vfx.asset], (), out_dir))
    return results
