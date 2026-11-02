"""Import the WP13 characters into the Unreal project (editor Python).

Runs inside `UnrealEditor-Cmd -ExecutePythonScript=<this file>` started by
`art/verse/characters/import_characters.py`. Environment:

* `VERSE_CHAR_RESULT`: the `rig_fps.py` result JSON (FBX files, clip markers, curves).
* `VERSE_CHAR_REPORT`: where the JSON report goes.
* `VERSE_CHAR_ONLY`: comma list of asset names to (re)import; empty = all.
* `VERSE_CHAR_QUIT=1`: quit the editor at the end.

Steps: the skeleton source mesh (creates `SKEL_Verse_Human`, moved to
`Characters/Rig/`), the other meshes on that skeleton, `PHYS_Verse_Human`
with the hit-zone capsules of `skeleton.HIT_BODIES`, `IKRig_Verse_Human`
with its retarget chains, then every clip: root motion, sync markers
(finisher phases, knife hit), float curves (`OffHandIK`) and the
`Warp_Finisher` motion-warping window. An asset whose stored export hash
equals the FBX's is skipped, so a rerun does not churn LFS objects.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

import unreal

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # art/verse

from characters.fps import catalogue as K  # noqa: E402
from characters.fps import skeleton as S  # noqa: E402

REPO = HERE.parents[3]
ASSETS = unreal.EditorAssetLibrary
SHA_TAG = "VerseExportSha256"
REPORT: dict = {"imported": [], "skipped": [], "errors": [], "notes": []}


def note(msg: str) -> None:
    REPORT["notes"].append(msg)
    unreal.log(f"VERSE_WP13 {msg}")


def error(msg: str) -> None:
    REPORT["errors"].append(msg)
    unreal.log_error(f"VERSE_WP13 FAIL {msg}")


def object_path(path: str) -> str:
    return path.split(".")[0]


def stored_sha(path: str) -> str:
    if not ASSETS.does_asset_exist(path):
        return ""
    asset = ASSETS.load_asset(path)
    return str(ASSETS.get_metadata_tag(asset, SHA_TAG) or "")


def tag_and_save(asset, sha: str) -> None:
    ASSETS.set_metadata_tag(asset, SHA_TAG, sha)
    ASSETS.save_loaded_asset(asset, only_if_is_dirty=False)


def _legacy_fbx() -> None:
    unreal.SystemLibrary.execute_console_command(None, "Interchange.FeatureFlags.Import.FBX 0")


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
    data.set_editor_property("delete_existing_morph_target_curves", True)
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


# ---------------------------------------------------------------------- meshes


def skeleton_path() -> str:
    return f"{S.RIG_FOLDER}/{S.SKELETON}"


def import_meshes(result: dict, only: set[str]) -> None:
    _legacy_fbx()
    meshes = {m["name"]: m for m in result["meshes"]}
    order = [K.SKELETON_SOURCE] + [m.name for m in K.MESHES if m.name != K.SKELETON_SOURCE]
    for name in order:
        entry = meshes.get(name)
        spec = next(m for m in K.MESHES if m.name == name)
        if entry is None:
            continue
        path = object_path(spec.asset_path)
        if only and name not in only:
            continue
        if stored_sha(path) == entry["sha256"] and ASSETS.does_asset_exist(skeleton_path()):
            REPORT["skipped"].append(name)
            continue
        skeleton = (
            ASSETS.load_asset(skeleton_path()) if ASSETS.does_asset_exist(skeleton_path()) else None
        )
        if skeleton is None and name != K.SKELETON_SOURCE:
            error(f"{name}: {S.SKELETON} missing; import {K.SKELETON_SOURCE} first")
            continue
        folder = path.rsplit("/", 1)[0]
        imported = _task(REPO / entry["file"], folder, name, mesh_options(skeleton))
        mesh = ASSETS.load_asset(path)
        if not isinstance(mesh, unreal.SkeletalMesh):
            error(f"{name}: import gave {imported}")
            continue
        if skeleton is None:
            made = mesh.get_editor_property("skeleton")
            old = object_path(made.get_path_name())
            if old != skeleton_path():
                if not ASSETS.rename_asset(old, skeleton_path()):
                    error(f"rename {old} -> {skeleton_path()}")
                    continue
                fix_redirectors(folder)
                fix_redirectors(S.RIG_FOLDER)
            skeleton = ASSETS.load_asset(skeleton_path())
            tag_and_save(skeleton, entry["sha256"])
        set_lods(mesh)
        tag_and_save(mesh, entry["sha256"])
        REPORT["imported"].append(name)


def set_lods(mesh) -> None:
    try:
        subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
        ok = subsystem.regenerate_lod(mesh, new_lod_count=4, regenerate_even_if_imported=True)
        note(f"{mesh.get_name()}: LODs regenerated={ok}")
    except Exception as exc:  # noqa: BLE001 - LOD generation is best effort, reported
        note(f"{mesh.get_name()}: LOD generation unavailable ({exc})")


# --------------------------------------------------------------------- physics


def build_physics() -> None:
    source = ASSETS.load_asset(
        object_path(next(m for m in K.MESHES if m.name == K.SKELETON_SOURCE).asset_path)
    )
    if source is None:
        error("physics: skeleton source mesh missing")
        return
    path = f"{S.RIG_FOLDER}/{S.PHYSICS}"
    if not ASSETS.does_asset_exist(path):
        meshes = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
        meshes.create_physics_asset(source)
        physics = source.get_editor_property("physics_asset")
        if physics is None:
            error("physics asset not created")
            return
        old = object_path(physics.get_path_name())
        if old != path:
            if not ASSETS.rename_asset(old, path):
                error(f"rename {old} -> {path}")
                return
            fix_redirectors(source.get_path_name().rsplit("/", 1)[0])
            fix_redirectors(S.RIG_FOLDER)
    physics = ASSETS.load_asset(path)
    ok = unreal.VerseContentTools.rebuild_hit_bodies(
        physics,
        source,
        [unreal.Name(b) for b, _, _, _ in S.HIT_BODIES],
        [unreal.Name(e or "None") for _, e, _, _ in S.HIT_BODIES],
        [r for _, _, r, _ in S.HIT_BODIES],
    )
    if not ok:
        error("hit bodies not rebuilt")
        return
    ASSETS.save_loaded_asset(physics, only_if_is_dirty=False)
    for spec in K.MESHES:
        mesh = ASSETS.load_asset(object_path(spec.asset_path))
        if mesh is None:
            continue
        # Always saved: the source mesh already points at the renamed asset in
        # memory, but its package on disk still names the pre-rename object.
        mesh.set_editor_property("physics_asset", physics)
        ASSETS.save_loaded_asset(mesh, only_if_is_dirty=False)
    note(f"{S.PHYSICS}: {len(S.HIT_BODIES)} hit bodies")


def build_ik_rig() -> None:
    path = f"{S.RIG_FOLDER}/{S.IK_RIG}"
    source = ASSETS.load_asset(
        object_path(next(m for m in K.MESHES if m.name == K.SKELETON_SOURCE).asset_path)
    )
    try:
        if ASSETS.does_asset_exist(path):
            rig = ASSETS.load_asset(path)
        else:
            tools = unreal.AssetToolsHelpers.get_asset_tools()
            rig = tools.create_asset(
                S.IK_RIG, S.RIG_FOLDER, unreal.IKRigDefinition, unreal.IKRigDefinitionFactory()
            )
        controller = unreal.IKRigController.get_controller(rig)
        controller.set_skeletal_mesh(source)
        controller.set_retarget_root("Hips")
        existing = {str(c.chain_name) for c in controller.get_retarget_chains()}
        for chain, start, end, goal in S.IK_CHAINS:
            if chain in existing:
                continue
            goal_name = ""
            if goal:
                goal_name = f"{chain}_Goal"
                controller.add_new_goal(goal_name, goal)
            controller.add_retarget_chain(chain, start, end, goal_name)
        ASSETS.save_loaded_asset(rig, only_if_is_dirty=False)
        note(f"{S.IK_RIG}: {len(S.IK_CHAINS)} chains")
    except Exception as exc:  # noqa: BLE001 - reported; the IK rig is for retargeting only
        error(f"IK rig: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------- clips


def import_clips(result: dict, only: set[str]) -> None:
    _legacy_fbx()
    skeleton = ASSETS.load_asset(skeleton_path())
    if skeleton is None:
        error("clips: no skeleton")
        return
    lib = unreal.AnimationLibrary
    for entry in result["clips"]:
        clip = K.BY_NAME[entry["name"]]
        if only and clip.name not in only:
            continue
        path = object_path(clip.asset_path)
        if stored_sha(path) == entry["sha256"]:
            REPORT["skipped"].append(clip.name)
            continue
        folder = path.rsplit("/", 1)[0]
        imported = _task(REPO / entry["file"], folder, clip.name, anim_options(skeleton, clip.fps))
        seq = ASSETS.load_asset(path)
        if not isinstance(seq, unreal.AnimSequence):
            error(f"{clip.name}: import gave {imported}")
            continue
        try:
            seq.set_editor_property("enable_root_motion", bool(clip.root_motion))
            seq.set_editor_property("root_motion_root_lock", unreal.RootMotionRootLock.REF_POSE)
            if clip.markers:
                track = "Markers"
                if track not in [str(n) for n in lib.get_animation_notify_track_names(seq)]:
                    lib.add_animation_notify_track(seq, track)
                lib.remove_all_animation_sync_markers(seq)
                for marker, time in clip.markers:
                    lib.add_animation_sync_marker(seq, marker, float(time), track)
            for curve, keys in entry.get("curves", {}).items():
                if lib.does_curve_exist(seq, curve, unreal.RawCurveTrackTypes.RCT_FLOAT):
                    lib.remove_curve(seq, curve, False)
                lib.add_curve(seq, curve, unreal.RawCurveTrackTypes.RCT_FLOAT, False)
                lib.add_float_curve_keys(
                    seq, curve, [float(t) for t, _ in keys], [float(v) for _, v in keys]
                )
            if clip.name == "A_Finisher_Attacker":
                add_warp_window(seq)
        except Exception as exc:  # noqa: BLE001 - report every clip
            error(f"{clip.name}: {type(exc).__name__}: {exc}")
        tag_and_save(seq, entry["sha256"])
        REPORT["imported"].append(clip.name)


def add_warp_window(seq) -> None:
    lib = unreal.AnimationLibrary
    track = "Warp"
    try:
        if track not in [str(n) for n in lib.get_animation_notify_track_names(seq)]:
            lib.add_animation_notify_track(seq, track)
        start, end = K.WARP_WINDOW
        state = lib.add_animation_notify_state_event(
            seq, track, start, end - start, unreal.AnimNotifyState_MotionWarping
        )
        modifier = unreal.new_object(unreal.RootMotionModifier_SkewWarp, outer=state)
        modifier.set_editor_property("warp_target_name", K.WARP_TARGET)
        state.set_editor_property("root_motion_modifier", modifier)
        note(f"A_Finisher_Attacker: {K.WARP_TARGET} window {start}-{end} s")
    except Exception as exc:  # noqa: BLE001
        error(f"warp window: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------- verify


def verify() -> None:
    skeleton = ASSETS.load_asset(skeleton_path())
    if skeleton is None:
        error("verify: no skeleton")
        return
    meshes = [ASSETS.load_asset(object_path(m.asset_path)) for m in K.MESHES]
    names = []
    if meshes and meshes[0] is not None:
        names = (
            [str(n) for n in unreal.SkeletalMeshEditorSubsystem().get_bone_names(meshes[0])]
            if hasattr(unreal.SkeletalMeshEditorSubsystem, "get_bone_names")
            else []
        )
    REPORT["bone_check"] = (
        S.check_names(names) if names else ["bone names not readable from Python"]
    )
    REPORT["meshes"] = [m.get_name() for m in meshes if m is not None]
    REPORT["clips"] = sum(1 for c in K.CLIPS if ASSETS.does_asset_exist(object_path(c.asset_path)))


def main() -> None:
    only = {s for s in os.environ.get("VERSE_CHAR_ONLY", "").split(",") if s}
    try:
        result = json.loads(Path(os.environ["VERSE_CHAR_RESULT"]).read_text(encoding="utf-8"))
        import_meshes(result, only)
        build_physics()
        build_ik_rig()
        import_clips(result, only)
        verify()
    except Exception:  # noqa: BLE001 - the host must see every failure
        error(traceback.format_exc())
    REPORT["ok"] = not REPORT["errors"]
    report = os.environ.get("VERSE_CHAR_REPORT")
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(REPORT, indent=2) + "\n", encoding="utf-8")
    unreal.log(f"VERSE_WP13 {'OK' if REPORT['ok'] else 'FAIL'}")
    if os.environ.get("VERSE_CHAR_QUIT") == "1":
        unreal.SystemLibrary.quit_editor()


main()
