"""The ship's copy of the level-system ids matches the Python rulebook (AP-4).

``levelCatalog.ts`` names the ids, ``starship/levels/ranks.ts`` draws the
ladder and ``starship/space/destinations.ts`` paints the destinations; the
server owns the numbers. An id added on one side without the other would
render nothing, show a raw key or open a destination at the wrong level, so
the lists must be equal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dodaios.progression.rules import (
    DESTINATION_IDS,
    LOOK_UNLOCKS,
    RANKS,
    REWARDS,
    RULES,
    SLOTS,
    SUBJECT_KINDS,
    WORLD_ACTIONS,
)
from dodaios.progression.service import VERSE_DECKS

_FRONTEND = Path(__file__).resolve().parents[3] / "dodaios/ui/web/frontend/src"
_CATALOG = _FRONTEND / "components/society/progression/levelCatalog.ts"
_STARSHIP = _FRONTEND / "components/society/starship"
_SHIP_LOCALES = _FRONTEND / "i18n/locales/ship"
_LANGS = ("en", "de", "es", "pt", "zh")


def _ts_list(name: str) -> list[str]:
    text = _CATALOG.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", text, re.S)
    assert match, f"{name} not found in levelCatalog.ts"
    return re.findall(r'"([a-z_]+)"', match.group(1))


def _ts_union(name: str) -> set[str]:
    text = _CATALOG.read_text(encoding="utf-8")
    match = re.search(rf"export type {name} =(.*?);", text, re.S)
    assert match, f"{name} not found in levelCatalog.ts"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def test_kinds_slots_rewards_ranks_and_sources_match():
    assert _ts_list("SUBJECT_KINDS") == list(SUBJECT_KINDS)
    assert _ts_list("SLOTS") == list(SLOTS)
    assert _ts_list("REWARD_IDS") == [r.reward_id for r in REWARDS]
    assert _ts_list("RANK_IDS") == [rank for _, rank, _ in RANKS]
    assert _ts_list("XP_SOURCES") == [r.source for r in RULES]
    assert _ts_union("WorldAction") == set(WORLD_ACTIONS)


def test_the_ship_draws_the_same_ladder():
    text = (_STARSHIP / "levels/ranks.ts").read_text(encoding="utf-8")
    ladder = [
        (int(level), rank, tier)
        for rank, level, tier in re.findall(
            r'\{ id: "([a-z_]+)", level: (\d+), tier: "([a-z]+)"', text
        )
    ]
    assert ladder == list(RANKS)


def test_destinations_open_at_the_rulebooks_levels():
    text = (_STARSHIP / "space/destinations.ts").read_text(encoding="utf-8")
    found = re.findall(r'id: "([a-z_]+)", level: (\d+)', text)
    painted = [(dest, int(level)) for dest, level in found]
    expected = [("home", 1)] + [
        (r.reward_id.removeprefix("destination_"), r.person)
        for r in REWARDS if r.slot == "destination"
    ]
    assert painted == expected
    assert tuple(dest for dest, _ in painted) == DESTINATION_IDS


def test_the_decks_the_server_pays_are_the_ships_decks():
    text = (_STARSHIP / "plan/types.ts").read_text(encoding="utf-8")
    match = re.search(r"export const DECKS: readonly DeckId\[\] = \[(.*?)\];", text, re.S)
    assert match, "DECKS not found in starship/plan/types.ts"
    assert set(re.findall(r'"([a-z_]+)"', match.group(1))) == set(VERSE_DECKS)


def test_every_id_has_words_in_every_language():
    ranks = {rank for _, rank, _ in RANKS}
    sources = {r.source for r in RULES}
    for lang in _LANGS:
        chunk = json.loads((_SHIP_LOCALES / f"levels.{lang}.json").read_text(encoding="utf-8"))
        levels = chunk["ship"]["levels"]
        assert set(levels["reward"]) == {r.reward_id for r in REWARDS}, lang
        assert set(levels["source"]) == sources, lang
        assert set(levels["rule"]) == sources, lang
        assert set(levels["slot"]) == set(SLOTS), lang
        assert set(levels["tier"]) == {tier for _, _, tier in RANKS}, lang
        core = json.loads((_SHIP_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        assert ranks <= set(core["ship"]["rank"]), lang


def test_every_agent_look_is_a_real_accessory():
    catalog = json.loads(
        (_FRONTEND / "components/society/companion/accessories.json").read_text(encoding="utf-8")
    )
    assert set(LOOK_UNLOCKS) == {item["id"] for item in catalog["items"]}
