"""Import static and skeletal meshes from FBX with the `fbx-ue/1` options (art-pipeline 6).

The import options are part of `fbx-ue/1`: they and the Blender export
settings (`art/verse/lib/unreal_export.py`) are proven together by
`verse_pipeline.calib`. Imports never create materials or textures (those
come from MI recipes and texture records) and never generate lightmap UVs.
"""

from __future__ import annotations

import os
from pathlib import Path

from .records import split_object_path

#: Which FBX importer runs: the engine default (Interchange) or the legacy
#: FbxFactory. Part of `fbx-ue/1`; calibrated by verse_pipeline.calib.
IMPORTER_ENV = "VERSE_FBX_IMPORTER"
DEFAULT_IMPORTER = "interchange"
_CVAR = "Interchange.FeatureFlags.Import.FBX"


def _unreal():
    import unreal

    return unreal


def use_importer(name: str | None = None) -> str:
    """Select the FBX importer for this process and return its name."""
    unreal = _unreal()
    name = (name or os.environ.get(IMPORTER_ENV) or DEFAULT_IMPORTER).lower()
    if name not in ("interchange", "legacy"):
        raise ValueError(f"{IMPORTER_ENV} must be interchange or legacy, got {name!r}")
    value = "1" if name == "interchange" else "0"
    unreal.SystemLibrary.execute_console_command(None, f"{_CVAR} {value}")
    return name


def _base_options(skeletal: bool):
    unreal = _unreal()
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("create_physics_asset", False)
    ui.set_editor_property("automated_import_should_detect_type", False)
    ui.set_editor_property("import_as_skeletal", skeletal)
    kinds = unreal.FBXImportType
    kind = kinds.FBXIT_SKELETAL_MESH if skeletal else kinds.FBXIT_STATIC_MESH
    ui.set_editor_property("mesh_type_to_import", kind)
    return ui


def _common(data) -> None:
    unreal = _unreal()
    data.set_editor_property("convert_scene", True)
    data.set_editor_property("force_front_x_axis", False)
    data.set_editor_property("convert_scene_unit", False)
    data.set_editor_property("import_uniform_scale", 1.0)
    data.set_editor_property("import_translation", unreal.Vector(0.0, 0.0, 0.0))
    data.set_editor_property("import_rotation", unreal.Rotator(0.0, 0.0, 0.0))


def static_mesh_options(*, nanite: bool, auto_collision: bool):
    unreal = _unreal()
    ui = _base_options(skeletal=False)
    data = ui.get_editor_property("static_mesh_import_data")
    _common(data)
    data.set_editor_property("combine_meshes", True)
    data.set_editor_property("generate_lightmap_u_vs", False)
    data.set_editor_property("auto_generate_collision", auto_collision)
    data.set_editor_property("remove_degenerates", True)
    data.set_editor_property("build_nanite", nanite)
    data.set_editor_property(
        "normal_import_method", unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    )
    return ui


def skeletal_mesh_options(skeleton=None):
    unreal = _unreal()
    ui = _base_options(skeletal=True)
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


def run_import(fbx: Path, object_path: str, options, *, save: bool):
    """Import one FBX into `object_path` and return the loaded asset."""
    unreal = _unreal()
    folder, name = split_object_path(object_path)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(fbx))
    task.set_editor_property("destination_path", folder)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("replace_existing_settings", True)
    task.set_editor_property("save", save)
    task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    asset = unreal.load_asset(object_path)
    if asset is None:
        imported = list(task.get_editor_property("imported_object_paths") or [])
        raise RuntimeError(f"import of {fbx.name} produced no {object_path} (got {imported})")
    return asset


def import_static(record: dict, fbx: Path, *, save: bool = True):
    nanite = bool(record.get("nanite", {}).get("enabled", False))
    collision = record.get("collision", {})
    auto_box = collision.get("source") == "auto_box"
    options = static_mesh_options(nanite=nanite, auto_collision=auto_box)
    return run_import(fbx, record["asset_path"], options, save=save)


def import_skeletal(record: dict, fbx: Path, *, save: bool = True, skeleton=None):
    return run_import(fbx, record["asset_path"], skeletal_mesh_options(skeleton), save=save)
