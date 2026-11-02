"""Weapon import finishing and checks (WP14, art-pipeline 12.2).

After the FBX import, `finish_import`

* assigns each material slot the MI its record names (imports never create
  materials, art-pipeline 6),
* for skeletal weapons renames the importer's `<Mesh>_Skeleton` to
  `SKEL_Weapon_<Name>` (the skeleton record beside the mesh record) and
  renames the sockets Interchange made from the FBX `SOCKET_<Name>` empties
  (it strips the prefix) back to the contract names `SOCKET_<Name>` and
  re-binds them from the carrier bone `SocketBase` to their spec bone,
* gives a gadget whose record says `auto_box` one box of simple collision.

`facts` and `check` are A14.1 on the imported asset.
"""

from __future__ import annotations

import sys

from . import REPO_ROOT

WEAPON_ROOT = "/Game/Verse/Weapons/"
VFX_ROOT = "/Game/Verse/VFX/Weapons/"


def _specs():
    path = str(REPO_ROOT / "art" / "verse")
    if path not in sys.path:
        sys.path.insert(0, path)
    from weapons import specs

    return specs


def is_weapon(record: dict) -> bool:
    return record["asset_path"].startswith(WEAPON_ROOT)


def is_wp14(record: dict) -> bool:
    return record["asset_path"].startswith((WEAPON_ROOT, VFX_ROOT))


def _assign_materials(unreal, record: dict, asset) -> list[str]:
    errors = []
    wanted = {s["slot"]: s["mi"] for s in record.get("mesh", {}).get("material_slots", [])}
    if isinstance(asset, unreal.SkeletalMesh):
        slots = list(asset.get_editor_property("materials"))
        for slot in slots:
            name = str(slot.get_editor_property("material_slot_name"))
            mi = unreal.load_asset(wanted.get(name, "")) if name in wanted else None
            if mi is None:
                errors.append(f"{record['name']}: no MI for slot {name}")
                continue
            slot.set_editor_property("material_interface", mi)
        asset.set_editor_property("materials", slots)
    else:
        for name, path in wanted.items():
            mi = unreal.load_asset(path)
            index = asset.get_material_index(name)
            if mi is None or index < 0:
                errors.append(f"{record['name']}: slot {name} or MI {path} missing")
                continue
            asset.set_material(index, mi)
    return errors


def _rename_skeleton(unreal, mesh, spec) -> list[str]:
    lib = unreal.EditorAssetLibrary
    skeleton = mesh.get_editor_property("skeleton")
    if skeleton is None:
        return [f"{spec.asset}: the import created no skeleton"]
    want = spec.skeleton_path.rsplit(".", 1)[0]
    have = skeleton.get_path_name().rsplit(".", 1)[0]
    if have == want:
        return []
    if lib.does_asset_exist(want):
        mesh.set_editor_property("skeleton", lib.load_asset(want))
        lib.delete_asset(have)
        return []
    if not lib.rename_asset(have, want):
        return [f"{spec.asset}: could not rename {have} to {want}"]
    return []


def _socket_names(mesh) -> set[str]:
    return {
        str(mesh.get_socket_by_index(i).get_editor_property("socket_name"))
        for i in range(mesh.num_sockets())
    }


def _name_sockets(unreal, mesh, spec) -> list[str]:
    subsystem = unreal.SkeletalMeshEditorSubsystem
    existing = _socket_names(mesh)
    for socket in spec.sockets:
        short = socket.name.removeprefix("SOCKET_")
        if socket.name not in existing and short in existing:
            subsystem.rename_socket(mesh, short, socket.name)
    errors = []
    by_name = {
        str(item.get_editor_property("socket_name")): item
        for item in (mesh.get_socket_by_index(i) for i in range(mesh.num_sockets()))
    }
    for socket in spec.sockets:
        item = by_name.get(socket.name)
        if item is None:
            continue
        if str(item.get_editor_property("bone_name")) != socket.bone:
            item.set_socket_parent(mesh, socket.bone)
        if str(item.get_editor_property("bone_name")) != socket.bone:
            errors.append(f"{spec.asset}: {socket.name} not on bone {socket.bone}")
    missing = [s.name for s in spec.sockets if s.name not in _socket_names(mesh)]
    if missing:
        errors.append(f"{spec.asset}: sockets missing after import: {missing}")
    return errors


def _auto_box(unreal, record: dict, asset) -> list[str]:
    if record.get("collision", {}).get("source") != "auto_box":
        return []
    subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if subsystem.get_simple_collision_count(asset) == 0:
        subsystem.add_simple_collisions(asset, unreal.ScriptCollisionShapeType.BOX)
    if subsystem.get_simple_collision_count(asset) == 0:
        return [f"{record['name']}: no simple collision after the auto box"]
    return []


def finish_import(record: dict, asset) -> list[str]:
    import unreal

    errors = _assign_materials(unreal, record, asset)
    if record["kind"] == "skeletal_mesh" and is_weapon(record):
        spec = _specs().by_asset(record["name"])
        errors += _rename_skeleton(unreal, asset, spec)
        errors += _name_sockets(unreal, asset, spec)
    elif record["kind"] == "static_mesh":
        errors += _auto_box(unreal, record, asset)
    return errors


def facts(record: dict) -> dict:
    """Bones, sockets and material slots of an imported skeletal weapon."""
    import unreal

    lib = unreal.EditorAssetLibrary
    if not lib.does_asset_exist(record["asset_path"]):
        return {"exists": False}
    mesh = lib.load_asset(record["asset_path"])
    skeleton = mesh.get_editor_property("skeleton")
    pose = unreal.AnimPoseExtensions.get_reference_pose(skeleton)
    bones = [str(b) for b in unreal.AnimPoseExtensions.get_bone_names(pose)]
    slots = mesh.get_editor_property("materials")
    return {
        "exists": True,
        "skeleton": skeleton.get_path_name() if skeleton else None,
        "bones": bones,
        "sockets": sorted(_socket_names(mesh)),
        "slots": [str(m.get_editor_property("material_slot_name")) for m in slots],
        "materials": [
            m.get_editor_property("material_interface").get_path_name()
            if m.get_editor_property("material_interface")
            else None
            for m in slots
        ],
    }


def check(record: dict, got: dict) -> list[str]:
    """A14.1 on one skeletal weapon: bone cap, bones, sockets, skeleton, triangles. Pure."""
    specs = _specs()
    name = record["name"]
    if not got.get("exists"):
        return [f"{name}: asset {record['asset_path']} does not exist"]
    spec = specs.by_asset(name)
    errors = []
    if len(got["bones"]) > specs.MAX_WEAPON_BONES:
        errors.append(f"{name}: {len(got['bones'])} bones, cap {specs.MAX_WEAPON_BONES}")
    for bone in specs.required_bones(spec):
        if bone not in got["bones"]:
            errors.append(f"{name}: missing bone {bone}")
    if got["bones"] and got["bones"][0] != "Root":
        errors.append(f"{name}: first bone is {got['bones'][0]}, not Root")
    for socket in specs.required_sockets(spec):
        if socket not in got["sockets"]:
            errors.append(f"{name}: missing socket {socket}")
    if got.get("skeleton") and got["skeleton"] != spec.skeleton_path:
        errors.append(f"{name}: skeleton {got['skeleton']} != {spec.skeleton_path}")
    if record["mesh"]["triangles"] > spec.triangle_cap:
        errors.append(f"{name}: {record['mesh']['triangles']} triangles, cap {spec.triangle_cap}")
    for slot, material in zip(got.get("slots", []), got.get("materials", []), strict=False):
        if material is None or "/Materials/Instances/Weapons/" not in material:
            errors.append(f"{name}: slot {slot} has no weapon MI ({material})")
    return errors
