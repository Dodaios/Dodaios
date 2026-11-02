"""Regenerate the WP01 content from code (work-packages.md WP01.1 and WP01.9).

Runs inside the headless editor's pythonscript commandlet, under the machine lock:

    python scripts/unreal/with_lock.py --label wp01-content -- \
        "<UE>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" unreal/Verse/Verse.uproject \
        -run=pythonscript -script=<this file> -nullrhi -unattended -nosplash -NoSound

Creates (overwrites):
* /Game/Verse/Movement/DA_MovementTuning, imported from Data/movement/movement_tuning.json;
* /Game/Verse/Test/WP01/LV_Test_Movement, the fixture map: the AVerseMovementCourse actor (all
  geometry lives in its C++ table), four player starts, a sun, sky light and atmosphere, and the
  movement test game mode as the world's game mode override.
Prints "VERSE_WP01 OK" when everything verifies.
"""

import os

import unreal

MAP = "/Game/Verse/Test/WP01/LV_Test_Movement"
TUNING_DIR = "/Game/Verse/Movement"
TUNING = "DA_MovementTuning"
FAILURES = []


def say(msg):
    unreal.log(f"VERSE_WP01 {msg}")


def fail(msg):
    FAILURES.append(msg)
    unreal.log_error(f"VERSE_WP01 FAIL {msg}")


def make_tuning():
    path = f"{TUNING_DIR}/{TUNING}"
    project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    json_path = os.path.join(project, "Data", "movement", "movement_tuning.json")
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        asset = unreal.EditorAssetLibrary.load_asset(path)
    else:
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.VerseMovementTuning)
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        asset = tools.create_asset(TUNING, TUNING_DIR, unreal.VerseMovementTuning, factory)
    ok, error = asset.import_json_file(json_path)
    if not ok:
        fail(f"tuning import: {error}")
        return
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    say(f"saved {path} from {json_path}")


def make_map():
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if unreal.EditorAssetLibrary.does_asset_exist(MAP):
        unreal.EditorAssetLibrary.delete_asset(MAP)
    if not levels.new_level(MAP, False):
        fail("new_level failed")
        return
    course_class = unreal.load_class(None, "/Script/VerseMovement.VerseMovementCourse")
    mode_class = unreal.load_class(None, "/Script/VerseMovement.VerseMovementTestGameMode")
    actors.spawn_actor_from_class(course_class, unreal.Vector(0, 0, 0))
    # Player starts at the head of the ledge lanes (capsule centre above the floor).
    for index, y in enumerate((800.0, 1600.0, 2400.0, 3200.0)):
        start = actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0.0, y, 100.0))
        start.set_actor_label(f"PlayerStart_{index}")
    sun = actors.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(0.0, -50.0, 35.0)
    )
    sun.light_component.set_editor_property("intensity", 6.0)
    sun.light_component.set_editor_property("atmosphere_sun_light", True)
    actors.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    sky = actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 500))
    sky.light_component.set_editor_property("real_time_capture", True)
    actors.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
    world = unreal.EditorLevelLibrary.get_editor_world()
    world.get_world_settings().set_editor_property("default_game_mode", mode_class)
    if not levels.save_current_level():
        fail("save_current_level failed")
        return
    say(f"saved {MAP}")


def verify():
    asset = unreal.EditorAssetLibrary.load_asset(f"{TUNING_DIR}/{TUNING}")
    if not asset:
        fail("DA_MovementTuning missing")
    elif abs(asset.get_editor_property("values").get_editor_property("walk_speed") - 4.5) > 1e-4:
        fail("DA_MovementTuning walk speed is not the json value")
    if not unreal.EditorAssetLibrary.does_asset_exist(MAP):
        fail("LV_Test_Movement missing")


make_tuning()
make_map()
verify()
say("OK" if not FAILURES else f"FAILED {len(FAILURES)}")
