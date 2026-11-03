"""Runs inside the headless editor (pythonscript commandlet): import the Verse sounds (WP19).

Reads unreal/Verse/Data/audio/{cues,mix,occlusion}.json and the build manifest in
art/verse/.cache/audio/, imports every WAV as /Game/Verse/Audio/<Group>/SW_<cue>_<nn>,
writes DA_AudioCues (UVerseAudioCueSet) and deletes sound waves no cue lists any more.
Started by art/verse/audio/import_audio.py, never by hand. Prints "VERSE_AUDIO OK" on success.
"""

import json
import os
from pathlib import Path

import unreal

REPO = Path(os.environ["VERSE_AUDIO_REPO"])
DATA = REPO / "unreal" / "Verse" / "Data" / "audio"
CACHE = REPO / "art" / "verse" / ".cache" / "audio"
ROOT = "/Game/Verse/Audio"
CUESET = f"{ROOT}/DA_AudioCues"
VERIFY = os.environ.get("VERSE_AUDIO_MODE") == "verify"


def log(msg):
    unreal.log(f"VERSE_AUDIO {msg}")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def import_waves(manifest):
    tasks = []
    for s in manifest["sounds"]:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(CACHE / s["file"]))
        task.set_editor_property("destination_path", f"{ROOT}/{s['group']}")
        task.set_editor_property("destination_name", s["asset"])
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", False)
        tasks.append(task)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    waves = {}
    for s in manifest["sounds"]:
        path = f"{ROOT}/{s['group']}/{s['asset']}"
        wave = unreal.EditorAssetLibrary.load_asset(path)
        if not isinstance(wave, unreal.SoundWave):
            raise RuntimeError(f"import failed: {path}")
        wave.set_editor_property("looping", bool(s["loop"]))
        unreal.EditorAssetLibrary.save_loaded_asset(wave, only_if_is_dirty=False)
        waves[(s["cue"], s["variant"])] = wave
    return waves


def bus(name):
    return getattr(unreal.VerseAudioBus, name.upper())


def make_mix(mix, occ):
    m = unreal.VerseAudioMixSettings()
    order = ["Weapons", "Impacts", "Foley", "Destruction", "Gadgets", "Ambience", "UI"]
    d, lim = mix["distance"], mix["limiter"]
    values = {
        "master_gain_db": mix["master_gain_db"],
        "bus_gain_db": [float(mix["bus_gain_db"][b]) for b in order],
        "max_voices": int(mix["max_voices"]),
        "dormant_unmute_fade_s": mix["dormant_unmute_fade_s"],
        "reference_m": d["reference_m"],
        "rolloff": d["rolloff"],
        "fade_start_fraction": d["fade_start_fraction"],
        "floor_db": d["floor_db"],
        "shot_near_full_m": mix["shot_layers"]["near_full_m"],
        "shot_far_full_m": mix["shot_layers"]["far_full_m"],
        "flyby_radius_m": mix["flyby"]["radius_m"],
        "bolt_speed_mps": mix["flyby"]["bolt_speed_mps"],
        "settle_delay_min_s": mix["debris_settle_delay_s"][0],
        "settle_delay_max_s": mix["debris_settle_delay_s"][1],
        "occlusion_refresh_s": mix["occlusion_refresh_s"],
        "occlusion_max_loss_db": occ["max_loss_db"],
        "open_lowpass_hz": occ["open_lowpass_hz"],
        "occlusion_loss_db": [float(r["transmission_db"]) for r in occ["materials"]],
        "occlusion_lowpass_hz": [float(r["lowpass_hz"]) for r in occ["materials"]],
        "limiter_threshold_db": lim["threshold_db"],
        "limiter_lookahead_ms": lim["lookahead_ms"],
        "limiter_attack_ms": lim["attack_ms"],
        "limiter_release_ms": lim["release_ms"],
    }
    for k, v in values.items():
        m.set_editor_property(k, v)
    return m


def write_cue_set(cues_doc, mix, occ, waves):
    asset = (
        unreal.EditorAssetLibrary.load_asset(CUESET)
        if unreal.EditorAssetLibrary.does_asset_exist(CUESET)
        else None
    )
    if asset is None:
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.VerseAudioCueSet)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "DA_AudioCues", ROOT, unreal.VerseAudioCueSet, factory
        )
    cues = []
    for c in cues_doc["cues"]:
        cue = unreal.VerseAudioCue()
        cue.set_editor_property("cue_id", c["id"])
        cue.set_editor_property(
            "variants", [waves[(c["id"], v)] for v in range(int(c["variants"]))]
        )
        cue.set_editor_property("bus", bus(c["bus"]))
        cue.set_editor_property("spatial", c["space"] == "3d")
        cue.set_editor_property("noise_tag", c["noise"] or "None")
        cue.set_editor_property("range_m", float(c["range_m"]))
        cue.set_editor_property("volume", unreal.Vector2D(*[float(x) for x in c["volume"]]))
        cue.set_editor_property("pitch", unreal.Vector2D(*[float(x) for x in c["pitch"]]))
        cue.set_editor_property("priority", float(c["priority"]))
        cue.set_editor_property("max_voices", int(c["max_voices"]))
        cue.set_editor_property("loop", bool(c["loop"]))
        cue.set_editor_property("licence", c["licence"])
        cues.append(cue)
    asset.set_editor_property("cues", cues)
    asset.set_editor_property("mix", make_mix(mix, occ))
    asset.set_editor_property("weapon_profiles", list(cues_doc["weapon_profiles"].keys()))
    asset.set_editor_property("default_weapon_profile", cues_doc["default_weapon_profile"])
    unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    return asset


def delete_orphans(manifest):
    keep = {f"{ROOT}/{s['group']}/{s['asset']}" for s in manifest["sounds"]}
    removed = 0
    for path in unreal.EditorAssetLibrary.list_assets(ROOT, recursive=True, include_folder=False):
        package = path.split(".")[0]
        name = package.rsplit("/", 1)[-1]
        if name.startswith("SW_") and package not in keep:
            unreal.EditorAssetLibrary.delete_asset(package)
            removed += 1
    return removed


def verify(cues_doc):
    asset = unreal.EditorAssetLibrary.load_asset(CUESET)
    if asset is None:
        raise RuntimeError("DA_AudioCues missing")
    have = {str(c.get_editor_property("cue_id")): c for c in asset.get_editor_property("cues")}
    for c in cues_doc["cues"]:
        cue = have.get(c["id"])
        if cue is None or len(cue.get_editor_property("variants")) != int(c["variants"]):
            raise RuntimeError(f"cue {c['id']} missing or wrong variant count")
        if any(v is None for v in cue.get_editor_property("variants")):
            raise RuntimeError(f"cue {c['id']} has an empty variant")
    log(f"verified {len(have)} cues")


def load_decoders():
    """Register the audio decoders a commandlet never loads on its own.

    A commandlet creates no audio device, so the BINKA decoder (the default
    compression) is not registered and every imported or loaded sound wave
    fails an ensure in the engine, which turns the run's exit code red.
    """
    for module in ("BinkAudioDecoder",):
        unreal.SystemLibrary.execute_console_command(None, f"Module Load {module}")


def main():
    load_decoders()
    cues_doc = load_json(DATA / "cues.json")
    if VERIFY:
        verify(cues_doc)
        log("OK")
        return
    manifest = load_json(CACHE / "manifest.json")
    waves = import_waves(manifest)
    log(f"imported {len(waves)} sound waves")
    write_cue_set(cues_doc, load_json(DATA / "mix.json"), load_json(DATA / "occlusion.json"), waves)
    log(f"removed {delete_orphans(manifest)} orphan sound waves")
    verify(cues_doc)
    log("OK")


try:
    main()
except Exception as error:  # noqa: BLE001 - the host script reads the log for the verdict
    unreal.log_error(f"VERSE_AUDIO FAILED {error}")
    raise
