"""WP12: deck collision imports: authored primitives through Interchange, bounds, ceilings."""

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


def test_shells_leave_pawn_collision_to_the_deck_bounds():
    """Shells are joined render meshes; their floors and walls are the hidden bounds proxies."""
    decks = ROOT / "unreal/Verse/Art/Import/Decks"
    shells = sorted(decks.glob("*/*_Shell.import.json"))
    assert shells
    for path in shells:
        collision = json.loads(path.read_text(encoding="utf-8"))["collision"]
        assert collision["source"] == "none", path.name
    bounds = sorted(decks.glob("*/*_Bounds*.import.json"))
    assert len(bounds) >= len(shells)
    for path in bounds:
        record = json.loads(path.read_text(encoding="utf-8"))
        collision = record["collision"]
        assert collision["profile"] == "Verse_ProxyOnly", path.name
        assert collision["source"] == "authored", path.name
        assert 1 <= collision["primitives"] <= 16, path.name
        assert import_meshes.wants_collision_import(collision["source"], "interchange")
    zones_with_bounds = {p.name.split("_Bounds")[0] for p in bounds}
    assert zones_with_bounds == {p.name.split("_Shell")[0] for p in shells}


def test_bounds_placements_are_hidden_blocking_proxies():
    placements = sorted((ROOT / "unreal/Verse/Art/Placements").glob("*/*.placement.json"))
    found = 0
    for path in placements:
        for entry in json.loads(path.read_text(encoding="utf-8"))["placements"]:
            if "_bounds_" in entry["id"]:
                found += 1
                assert entry["collision"] == "Verse_ProxyOnly", entry["id"]
                assert entry["nav"] == "block", entry["id"]
                assert "_Bounds" in entry["piece"], entry["id"]
    assert found >= 21


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
