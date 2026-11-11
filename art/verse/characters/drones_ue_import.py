"""Import the drones into the Unreal project (editor Python).

Runs inside `UnrealEditor-Cmd -ExecutePythonScript=<this file>` started by
`art/verse/characters/import_characters.py --drones`. Environment as `fps/ue_import.py`:
`VERSE_CHAR_RESULT` (the `drones_unreal.py` result), `VERSE_CHAR_REPORT`, `VERSE_CHAR_QUIT`.

Each drone mesh creates its own skeleton on import (moved to `SKEL_Drone_<Kind>` beside the
mesh), then its clips import onto it. Textures and MIs import through
`scripts/unreal/import_art.py assets` and `materials`, slots through `bind`.
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

import unreal

REPO = Path(__file__).resolve().parents[3]
ASSETS = unreal.EditorAssetLibrary
SHA_TAG = "VerseExportSha256"
FOLDER = "/Game/Verse/Characters/Drones"
CLIP_FOLDER = "/Game/Verse/Animations/Drones"
REPORT: dict = {"imported": [], "skipped": [], "errors": [], "notes": []}


def error(msg: str) -> None:
    REPORT["errors"].append(msg)
    unreal.log_error(f"VERSE_DRONES FAIL {msg}")


def stored_sha(path: str) -> str:
    if not ASSETS.does_asset_exist(path):
        return ""
    return str(ASSETS.get_metadata_tag(ASSETS.load_asset(path), SHA_TAG) or "")


def tag_and_save(asset, sha: str) -> None:
    ASSETS.set_metadata_tag(asset, SHA_TAG, sha)
    ASSETS.save_loaded_asset(asset, only_if_is_dirty=False)


def _common(data) -> None:
    data.set_editor_property("convert_scene", True)
    data.set_editor_property("force_front_x_axis", False)
    data.set_editor_property("convert_scene_unit", False)
    data.set_editor_property("import_uniform_scale", 1.0)


def _task(fbx: Path, folder: str, name: str, options):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(fbx))
    task.set_editor_property("destination_path", folder)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("replace_existing_settings", True)
    task.set_editor_property("save", False)
    task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return list(task.get_editor_property("imported_object_paths") or [])


def mesh_options(skeleton):
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("automated_import_should_detect_type", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    if skeleton is not None:
        ui.set_editor_property("skeleton", skeleton)
    data = ui.get_editor_property("skeletal_mesh_import_data")
    _common(data)
    data.set_editor_property("import_meshes_in_bone_hierarchy", True)
    data.set_editor_property("use_t0_as_ref_pose", False)
    data.set_editor_property(
        "normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    )
    return ui


def anim_options(skeleton, fps: int):
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", False)
    ui.set_editor_property("import_as_skeletal", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", True)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("automated_import_should_detect_type", False)
    ui.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_ANIMATION)
    ui.set_editor_property("skeleton", skeleton)
    data = ui.get_editor_property("anim_sequence_import_data")
    _common(data)
    data.set_editor_property(
        "animation_length", unreal.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME
    )
    data.set_editor_property("import_bone_tracks", True)
    data.set_editor_property("use_default_sample_rate", False)
    data.set_editor_property("custom_sample_rate", int(fps))
    data.set_editor_property("remove_redundant_keys", False)
    data.set_editor_property("import_custom_attribute", False)
    return ui


def fix_redirectors(folder: str) -> None:
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    redirectors = [
        d.get_asset()
        for d in registry.get_assets_by_path(folder, recursive=True)
        if str(d.asset_class_path.asset_name) == "ObjectRedirector"
    ]
    if redirectors:
        unreal.AssetToolsHelpers.get_asset_tools().fixup_referencers(redirectors)
    for d in registry.get_assets_by_path(folder, recursive=True):
        if str(d.asset_class_path.asset_name) == "ObjectRedirector":
            ASSETS.delete_asset(str(d.package_name))


def import_drone(entry: dict) -> None:
    name = entry["name"]
    mesh_path = f"{FOLDER}/{name}"
    skel_path = f"{FOLDER}/SKEL_{name[len('SK_'):]}"
    if stored_sha(mesh_path) == entry["sha256"] and ASSETS.does_asset_exist(skel_path):
        REPORT["skipped"].append(name)
    else:
        # A fresh skeleton every time the mesh changes: the drones' rigs are tiny and own.
        for path in (mesh_path, skel_path):
            if ASSETS.does_asset_exist(path):
                ASSETS.delete_asset(path)
        imported = _task(REPO / entry["file"], FOLDER, name, mesh_options(None))
        mesh = ASSETS.load_asset(mesh_path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            error(f"{name}: import gave {imported}")
            return
        made = mesh.get_editor_property("skeleton")
        old = made.get_path_name().split(".")[0]
        if old != skel_path:
            if not ASSETS.rename_asset(old, skel_path):
                error(f"rename {old} -> {skel_path}")
                return
            fix_redirectors(FOLDER)
        skeleton = ASSETS.load_asset(skel_path)
        tag_and_save(skeleton, entry["sha256"])
        mesh = ASSETS.load_asset(mesh_path)
        tag_and_save(mesh, entry["sha256"])
        REPORT["imported"].append(name)
    skeleton = ASSETS.load_asset(skel_path)
    for clip in entry["clips"]:
        path = f"{CLIP_FOLDER}/{clip['name']}"
        if stored_sha(path) == clip["sha256"] and name in REPORT["skipped"]:
            REPORT["skipped"].append(clip["name"])
            continue
        if ASSETS.does_asset_exist(path):
            ASSETS.delete_asset(path)
        imported = _task(
            REPO / clip["file"], CLIP_FOLDER, clip["name"], anim_options(skeleton, clip["fps"])
        )
        seq = ASSETS.load_asset(path)
        if not isinstance(seq, unreal.AnimSequence):
            error(f"{clip['name']}: import gave {imported}")
            continue
        seq.set_editor_property("enable_root_motion", False)
        tag_and_save(seq, clip["sha256"])
        REPORT["imported"].append(clip["name"])


def main() -> None:
    try:
        unreal.SystemLibrary.execute_console_command(
            None, "Interchange.FeatureFlags.Import.FBX 0"
        )
        result = json.loads(Path(os.environ["VERSE_CHAR_RESULT"]).read_text(encoding="utf-8"))
        for entry in result["drones"]:
            import_drone(entry)
    except Exception:  # noqa: BLE001 - the host must see every failure
        error(traceback.format_exc())
    REPORT["ok"] = not REPORT["errors"]
    report = os.environ.get("VERSE_CHAR_REPORT")
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(REPORT, indent=2) + "\n", encoding="utf-8")
    unreal.log(f"VERSE_DRONES {'OK' if REPORT['ok'] else 'FAIL'}")
    if os.environ.get("VERSE_CHAR_QUIT") == "1":
        unreal.SystemLibrary.quit_editor()


main()
