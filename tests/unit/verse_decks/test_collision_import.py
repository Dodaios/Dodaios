"""WP12: the deck shells keep their authored floor boxes through the Interchange import."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "unreal" / "Verse" / "Content" / "Python"))

from verse_pipeline import import_meshes  # noqa: E402


def test_auto_box_always_imports_collision():
    assert import_meshes.wants_collision_import("auto_box", "interchange")
    assert import_meshes.wants_collision_import("auto_box", "legacy")


def test_authored_collision_needs_import_on_under_interchange():
    assert import_meshes.wants_collision_import("authored", "interchange")
    assert not import_meshes.wants_collision_import("authored", "legacy")


def test_no_collision_stays_off():
    assert not import_meshes.wants_collision_import(None, "interchange")
    assert not import_meshes.wants_collision_import("none", "interchange")


def test_every_shell_record_is_authored_with_primitives():
    records = sorted((ROOT / "unreal/Verse/Art/Import/Decks").glob("*/*_Shell.import.json"))
    assert records
    for path in records:
        collision = json.loads(path.read_text(encoding="utf-8"))["collision"]
        assert collision["source"] == "authored", path.name
        assert collision["primitives"] >= 1, path.name
        assert import_meshes.wants_collision_import(collision["source"], "interchange")


def test_ceilings_are_separate_and_never_collide():
    """The overview cutaway hides `<zone>_ceiling`; ceilings carry no collision and no nav."""
    placements = sorted((ROOT / "unreal/Verse/Art/Placements").glob("*/*.placement.json"))
    ceilings = []
    for path in placements:
        for entry in json.loads(path.read_text(encoding="utf-8"))["placements"]:
            if entry["id"].endswith("_ceiling"):
                ceilings.append(entry)
                assert entry["piece"].endswith("_Ceiling"), entry["id"]
                assert entry["nav"] == "none", entry["id"]
    decks = {entry["asset"].split("/")[4] for entry in ceilings}
    assert {"Bridge", "Ops", "Engineering"} <= decks
    for path in sorted((ROOT / "unreal/Verse/Art/Import/Decks").glob("*/*_Ceiling.import.json")):
        collision = json.loads(path.read_text(encoding="utf-8"))["collision"]
        assert collision["source"] == "none", path.name
