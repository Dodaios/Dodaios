"""Create and verify the G0.8 deck maps and the G0.9 test skeleton (editor Python).

Runs inside the headless editor's ``pythonscript`` commandlet, started by
``scripts/unreal/g0_content.py``. Environment:

* ``VERSE_G0_MODE``: ``build`` (create what is missing, then verify) or ``verify``.
* ``VERSE_G0_FBX``: the FBX the Blender step exported (build mode only).

Idempotent: an existing map, data layer or mesh is kept, never re-saved, so a
rerun does not churn LFS objects. Delete an asset first to rebuild it. Every
result line starts with ``VERSE_G0``; the last one is ``VERSE_G0 OK`` or
``VERSE_G0 FAIL``.
"""

from __future__ import annotations

import os
import traceback

import unreal

DECKS = {
    "Bridge": ("Base",),
    "Ops": ("Base",),
    "Engineering": ("Base",),
    "Hangar": ("Base", "Day", "Arena"),
}
# Day-to-day state on load: the hangar is a normal deck; the arena switch
# (VerseDecks, FVerseArenaSwitchEvent) activates DL_Hangar_Arena on demand.
INITIAL_STATE = {"Base": "ACTIVATED", "Day": "ACTIVATED", "Arena": "UNLOADED"}

TEST_DIR = "/Game/Verse/Test/G0"
MESH = "SK_Test_Human"
SKELETON = "SKEL_Test_Human"
PHYSICS = "PHYS_Test_Human"

# Hit zones of art-pipeline 12.1 (architecture 3.3): (bone, capsule end bone or
# None to continue along the parent direction, radius in cm). Hips is the root body.
HIT_BODIES = (
    ("Hips", "Spine_01", 13.0),
    ("Spine_01", "Spine_03", 14.0),  # lower torso
    ("Spine_03", "Neck", 16.0),  # upper torso
    ("Neck", "Head", 6.0),
    ("Head", None, 11.0),
    ("UpperArm_L", "LowerArm_L", 6.0),
    ("UpperArm_R", "LowerArm_R", 6.0),
    ("LowerArm_L", "Hand_L", 5.0),
    ("LowerArm_R", "Hand_R", 5.0),
    ("Thigh_L", "Calf_L", 8.0),
    ("Thigh_R", "Calf_R", 8.0),
    ("Calf_L", "Foot_L", 6.0),
    ("Calf_R", "Foot_R", 6.0),
)

ASSETS = unreal.EditorAssetLibrary
FAILURES: list[str] = []


def say(msg: str) -> None:
    unreal.log(f"VERSE_G0 {msg}")


def fail(msg: str) -> None:
    FAILURES.append(msg)
    unreal.log_error(f"VERSE_G0 FAIL {msg}")


def map_path(deck: str) -> str:
    return f"/Game/Verse/Decks/{deck}/LV_{deck}"


def layer_path(deck: str, layer: str) -> str:
    return f"/Game/Verse/Decks/{deck}/DataLayers/DL_{deck}_{layer}"


# ---------------------------------------------------------------- G0.8 levels


def ensure_layer_asset(deck: str, layer: str) -> unreal.DataLayerAsset:
    path = layer_path(deck, layer)
    if ASSETS.does_asset_exist(path):
        return ASSETS.load_asset(path)
    folder, name = path.rsplit("/", 1)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = tools.create_asset(name, folder, unreal.DataLayerAsset, unreal.DataLayerFactory())
    asset.set_editor_property("data_layer_type", unreal.DataLayerType.RUNTIME)
    ASSETS.save_loaded_asset(asset, only_if_is_dirty=False)
    say(f"created {path}")
    return asset


def ensure_level(deck: str) -> None:
    path = map_path(deck)
    assets = [ensure_layer_asset(deck, layer) for layer in DECKS[deck]]
    if ASSETS.does_asset_exist(path):
        say(f"kept {path}")
        return
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not levels.new_level(path, is_partitioned_world=True):
        fail(f"new_level {path}")
        return
    layers = unreal.get_editor_subsystem(unreal.DataLayerEditorSubsystem)
    for layer, asset in zip(DECKS[deck], assets, strict=True):
        params = unreal.DataLayerCreationParameters()
        params.set_editor_property("data_layer_asset", asset)
        instance = layers.create_data_layer_instance(params)
        if instance is None:
            fail(f"data layer instance DL_{deck}_{layer}")
            continue
        state = getattr(unreal.DataLayerRuntimeState, INITIAL_STATE[layer])
        layers.set_data_layer_initial_runtime_state(instance, state)
    if not levels.save_current_level():
        fail(f"save {path}")
        return
    say(f"created {path}")


def verify_level(deck: str) -> None:
    path = map_path(deck)
    if not ASSETS.does_asset_exist(path):
        fail(f"missing {path}")
        return
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not levels.load_level(path):
        fail(f"load {path}")
        return
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    settings = world.get_world_settings()
    if settings.get_editor_property("world_partition") is None:
        fail(f"{path} is not World Partition")
    layers = unreal.get_editor_subsystem(unreal.DataLayerEditorSubsystem)
    found = {}
    for instance in layers.get_all_data_layers():
        asset = instance.get_editor_property("data_layer_asset") \
            if hasattr(instance, "data_layer_asset") else instance.get_asset()
        if asset is not None:
            found[asset.get_name()] = instance
    for layer in DECKS[deck]:
        name = f"DL_{deck}_{layer}"
        instance = found.get(name)
        if instance is None:
            fail(f"{path} lacks data layer {name}")
            continue
        if not instance.is_runtime():
            fail(f"{name} is not a runtime layer")
        state = instance.get_initial_runtime_state()
        want = getattr(unreal.DataLayerRuntimeState, INITIAL_STATE[layer])
        if state != want:
            fail(f"{name} initial state {state}, want {want}")
    say(f"verified {path} layers={sorted(found)}")


# ----------------------------------------------------------- G0.9 test human


def import_test_human(fbx: str) -> None:
    mesh_path = f"{TEST_DIR}/{MESH}"
    if ASSETS.does_asset_exist(mesh_path):
        say(f"kept {mesh_path}")
        return
    if not fbx or not os.path.isfile(fbx):
        fail(f"FBX not found: {fbx}")
        return
    # The Interchange importer syncs the Content Browser (Slate) after import,
    # which asserts in a commandlet; the classic FBX factory does not.
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")
    options = unreal.FbxImportUI()
    options.set_editor_property("import_as_skeletal", True)
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_materials", False)
    options.set_editor_property("import_textures", False)
    options.set_editor_property("import_animations", False)
    options.set_editor_property("create_physics_asset", False)
    options.set_editor_property("mesh_type_to_import", unreal.FBXImportType.FBXIT_SKELETAL_MESH)
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", fbx)
    task.set_editor_property("destination_path", TEST_DIR)
    task.set_editor_property("destination_name", MESH)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = [p for p in task.get_editor_property("imported_object_paths")]
    say(f"imported {imported}")
    mesh = ASSETS.load_asset(mesh_path)
    if not isinstance(mesh, unreal.SkeletalMesh):
        fail(f"import produced no skeletal mesh at {mesh_path}: {imported}")
        return
    rename_skeleton(mesh)
    build_physics(mesh)
    for path in ASSETS.list_assets(TEST_DIR, recursive=True, include_folder=False):
        ASSETS.save_asset(path, only_if_is_dirty=False)


def rename_skeleton(mesh: unreal.SkeletalMesh) -> None:
    skeleton = mesh.get_editor_property("skeleton")
    old = skeleton.get_path_name().split(".")[0]
    new = f"{TEST_DIR}/{SKELETON}"
    if old == new:
        return
    if not ASSETS.rename_asset(old, new):
        fail(f"rename {old} -> {new}")
        return
    fix_redirectors()


def fix_redirectors() -> None:
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    redirectors = []
    for data in registry.get_assets_by_path(TEST_DIR, recursive=True):
        if str(data.asset_class_path.asset_name) == "ObjectRedirector":
            redirectors.append(data.get_asset())
    if redirectors:
        unreal.AssetToolsHelpers.get_asset_tools().fixup_referencers(redirectors)
    for data in registry.get_assets_by_path(TEST_DIR, recursive=True):
        if str(data.asset_class_path.asset_name) == "ObjectRedirector":
            ASSETS.delete_asset(str(data.package_name))


def build_physics(mesh: unreal.SkeletalMesh) -> None:
    """Create PHYS_Test_Human and give it exactly the HIT_BODIES capsules.

    The engine generator only creates the asset; its automatic bodies weld the
    thin placeholder boxes away, so UVerseContentTools replaces them.
    """
    path = f"{TEST_DIR}/{PHYSICS}"
    meshes = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    meshes.create_physics_asset(mesh)
    physics = mesh.get_editor_property("physics_asset")
    if physics is None:
        fail(f"physics asset for {MESH}")
        return
    old = physics.get_path_name().split(".")[0]
    if old != path:
        if not ASSETS.rename_asset(old, path):
            fail(f"rename {old} -> {path}")
            return
        fix_redirectors()
        physics = ASSETS.load_asset(path)
    ok = unreal.VerseContentTools.rebuild_hit_bodies(
        physics, mesh,
        [unreal.Name(b) for b, _, _ in HIT_BODIES],
        [unreal.Name(e or "None") for _, e, _ in HIT_BODIES],
        [r for _, _, r in HIT_BODIES],
    )
    if not ok:
        fail(f"hit bodies for {path}")
        return
    say(f"created {path} with {len(HIT_BODIES)} hit bodies")


def verify_test_human() -> None:
    mesh_path = f"{TEST_DIR}/{MESH}"
    if not ASSETS.does_asset_exist(mesh_path):
        fail(f"missing {mesh_path}")
        return
    mesh = ASSETS.load_asset(mesh_path)
    # Centimetres in Unreal (art-pipeline 12.1): the placeholder stands about 1.8 m tall.
    height = mesh.get_bounds().box_extent.z * 2.0
    if not 170.0 <= height <= 190.0:
        fail(f"{MESH} is {height:.2f} units tall, want about 181 cm")
    skeleton = mesh.get_editor_property("skeleton")
    if skeleton is None or skeleton.get_name() != SKELETON:
        fail(f"skeleton is {skeleton.get_name() if skeleton else None}, want {SKELETON}")
    physics = mesh.get_editor_property("physics_asset")
    if physics is None or physics.get_name() != PHYSICS:
        fail(f"physics asset is {physics.get_name() if physics else None}, want {PHYSICS}")
    say(f"verified {mesh_path}")


# ---------------------------------------------------------------------- main


def main() -> None:
    mode = os.environ.get("VERSE_G0_MODE", "verify")
    try:
        if mode == "build":
            for deck in DECKS:
                ensure_level(deck)
            import_test_human(os.environ.get("VERSE_G0_FBX", ""))
        for deck in DECKS:
            verify_level(deck)
        verify_test_human()
    except Exception:  # noqa: BLE001 - report and fail the run, never hang the editor
        fail(traceback.format_exc())
    say("FAIL" if FAILURES else "OK")


main()
