"""The hangar arena's art (arena.md 9.2): arena MI recipes and the `bind` step. Pure Python."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ART = REPO_ROOT / "art" / "verse"
PIPELINE = REPO_ROOT / "unreal" / "Verse" / "Content" / "Python"
SCRIPTS = REPO_ROOT / "scripts" / "unreal"
ARENA_MIS = REPO_ROOT / "unreal" / "Verse" / "Art" / "Materials" / "Arena"
SOURCE = REPO_ROOT / "unreal" / "Verse" / "Source" / "Verse" / "Private"
DRESSING = SOURCE / "VerseArenaDressing.cpp"

for _path in (ART, PIPELINE, SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import import_art  # noqa: E402
from verse_pipeline import bind  # noqa: E402
from weapons.editor import masters  # noqa: E402


def _arena_recipes() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ARENA_MIS.glob("*.mi.json"))]


def test_arena_recipes_only_set_parameters_of_their_master():
    table: dict[str, set[str]] = {}
    for row in masters.parameter_table():
        table.setdefault(row["master"], set()).add(row["name"])
    recipes = _arena_recipes()
    assert len(recipes) >= 15
    for recipe in recipes:
        assert recipe["schema"] == "verse.mi/1"
        assert recipe["owner"] == "WP11"
        master = recipe["parent"].rsplit(".", 1)[1]
        for group in ("scalars", "vectors", "textures", "switches"):
            unknown = set(recipe[group]) - table[master]
            assert not unknown, f"{recipe['name']}: {sorted(unknown)} not on {master}"


def test_every_look_the_dressing_names_has_a_recipe():
    """Each `TEXT("Arena_...")` look in the dressing code is an arena MI recipe."""
    names = {p.name[: -len(".mi.json")] for p in ARENA_MIS.glob("*.mi.json")}
    looks = set(re.findall(r'TEXT\("(Arena_[A-Za-z]+)"\)', DRESSING.read_text(encoding="utf-8")))
    assert looks, "the dressing names no arena looks"
    missing = sorted(look for look in looks if f"MI_{look}" not in names)
    assert not missing


def test_wanted_slots_maps_slot_names_to_their_mi():
    record = {
        "mesh": {
            "material_slots": [
                {"slot": "M_Crate_Paint", "mi": "/Game/A/MI_Crate_Paint.MI_Crate_Paint"},
                {"slot": "M_Empty", "mi": ""},
            ]
        }
    }
    assert bind.wanted_slots(record) == {"M_Crate_Paint": "/Game/A/MI_Crate_Paint.MI_Crate_Paint"}
    assert bind.wanted_slots({}) == {}


def test_bind_forwards_only_and_no_save():
    parser_args = ["bind", "--only", "SM_A,SM_B", "--no-save"]
    seen: dict = {}

    def fake_run(argv):
        seen["argv"] = argv
        return 0, {"ok": True}, Path("report.json")

    original = import_art.run_pipeline
    import_art.run_pipeline = fake_run
    try:
        assert import_art.main(parser_args) == 0
    finally:
        import_art.run_pipeline = original
    assert seen["argv"] == ["bind", "--only", "SM_A,SM_B", "--no-save"]
