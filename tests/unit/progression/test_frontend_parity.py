"""The Verse's copy of the level-system ids matches the Python rulebook.

``progression/levelCatalog.ts`` names the ids and the reward levels,
``verse/ranks/ranks.ts`` draws the ladder and ``verse/decks.ts`` lists the
decks; the server owns the numbers. An id added on one side without the other
would render nothing, show a raw key or be refused by the server, so the lists
must be equal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from dodaios.progression.rules import (
    LOOK_UNLOCKS,
    RANK_TIERS,
    RANKS,
    REWARDS,
    RULES,
    SLOTS,
    SUBJECT_KINDS,
    VERSE_DECKS,
    WORLD_ACTIONS,
)

_FRONTEND = Path(__file__).resolve().parents[3] / "dodaios/ui/web/frontend/src"
_SOCIETY = _FRONTEND / "components/society"
_CATALOG = _SOCIETY / "progression/levelCatalog.ts"
_LOCALES = _FRONTEND / "i18n/locales/ship"
_LANGS = ("en", "de", "es", "pt", "zh")


def _catalog() -> str:
    return _CATALOG.read_text(encoding="utf-8")


def _ts_list(name: str, text: str | None = None) -> list[str]:
    source = text if text is not None else _catalog()
    match = re.search(rf"export const {name} = \[(.*?)\] as const;", source, re.S)
    assert match, f"{name} not found"
    return re.findall(r'"([a-z_]+)"', match.group(1))


def _ts_union(name: str) -> set[str]:
    match = re.search(rf"export type {name} =(.*?);", _catalog(), re.S)
    assert match, f"{name} not found in levelCatalog.ts"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def test_kinds_slots_rewards_and_sources_match():
    assert _ts_list("SUBJECT_KINDS") == list(SUBJECT_KINDS)
    assert _ts_list("SLOTS") == list(SLOTS)
    assert _ts_list("REWARD_IDS") == [r.reward_id for r in REWARDS]
    assert _ts_list("XP_SOURCES") == [r.source for r in RULES]
    assert _ts_union("WorldAction") == set(WORLD_ACTIONS)


def test_the_clients_reward_levels_are_the_rulebooks():
    rows = re.findall(
        r"^\s+([a-z_]+): \{ person: (\d+|null), agent: (\d+|null), pet: (\d+|null) \},$",
        _catalog(),
        re.M,
    )

    def level(value: str) -> int | None:
        return None if value == "null" else int(value)

    client = [(rid, level(p), level(a), level(q)) for rid, p, a, q in rows]
    assert client == [(r.reward_id, r.person, r.agent, r.pet) for r in REWARDS]


def test_the_verse_draws_the_same_ladder():
    text = (_SOCIETY / "verse/ranks/ranks.ts").read_text(encoding="utf-8")
    ladder = [
        (int(level), rank, tier)
        for rank, level, tier in re.findall(
            r'\{ id: "([a-z_]+)", level: (\d+), tier: "([a-z]+)"', text
        )
    ]
    assert ladder == list(RANKS)
    assert _ts_list("RANK_TIERS", text) == list(RANK_TIERS)
    assert _ts_list("RANK_IDS", text) == [rank for _, rank, _ in RANKS]


def test_the_decks_the_server_pays_are_the_ships_decks():
    text = (_SOCIETY / "verse/decks.ts").read_text(encoding="utf-8")
    assert _ts_list("DECK_IDS", text) == list(VERSE_DECKS)


def test_every_id_has_words_in_every_language():
    sources = {r.source for r in RULES}
    for lang in _LANGS:
        chunk = json.loads((_LOCALES / f"ranks.{lang}.json").read_text(encoding="utf-8"))
        words = chunk["verse"]["ranks"]
        assert set(words["rank"]) == {rank for _, rank, _ in RANKS}, lang
        assert set(words["tier"]) == set(RANK_TIERS), lang
        assert set(words["uniform"]) == {
            r.reward_id.removeprefix("uniform_") for r in REWARDS if r.slot == "uniform"
        }, lang
        assert set(words["ribbon"]) == {r.reward_id for r in REWARDS if r.slot == "ribbon"}, lang
        assert set(words["source"]) == sources | {"retired"}, lang
        assert set(words["rule"]) == sources, lang


def test_every_agent_look_is_a_real_accessory():
    catalog = json.loads(
        (_SOCIETY / "companion/accessories.json").read_text(encoding="utf-8")
    )
    assert set(LOOK_UNLOCKS) == {item["id"] for item in catalog["items"]}
