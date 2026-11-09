"""The Unreal copies of the progression rulebook match the server (WP21.6, WP21.7).

The Unreal service record draws the rank ladder from its own table and the
duel reporter spells the ``end_reason`` values itself; both must equal
``dodaios/progression/rules.py`` or a rank would read wrong and a result
would be refused.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dodaios.progression.rules import DUEL_END_REASONS, DUEL_OUTCOMES, RANKS

_SOURCE = Path(__file__).resolve().parents[3] / "unreal/Verse/Source"
_MODEL = _SOURCE / "VerseUI/Private/ServiceRecord/VerseServiceRecordModel.cpp"
_CODEC = _SOURCE / "VerseBridge/Private/Duel/VerseDuelResultCodec.cpp"


_RANKS_TS = (
    Path(__file__).resolve().parents[3]
    / "dodaios/ui/web/frontend/src/components/society/verse/ranks/ranks.ts"
)


def _unreal_ladder() -> list[tuple[str, int, str, str]]:
    text = _MODEL.read_text(encoding="utf-8")
    block = re.search(r"VERSE_RANK_LADDER_BEGIN(.*?)VERSE_RANK_LADDER_END", text, re.S)
    assert block, "ladder markers missing"
    rows = re.findall(
        r'\{TEXT\("([a-z_]+)"\), (\d+), TEXT\("([a-z]+)"\), TEXT\("([01]{3}\|[01]{3})"\)\}',
        block.group(1),
    )
    return [(rank, int(level), tier, plate) for rank, level, tier, plate in rows]


def test_the_unreal_service_record_draws_the_servers_ladder():
    """Parity R-01: ids, levels and tiers equal rules.py RANKS."""
    ladder = _unreal_ladder()
    assert [(level, rank, tier) for rank, level, tier, _ in ladder] == list(RANKS)


def test_the_unreal_rank_plates_equal_the_web_plates():
    """Parity R-01 and R-03: the plate patterns are the web record's, and no two ranks share one."""
    web = re.findall(
        r'\{ id: "([a-z_]+)", level: (\d+), tier: "([a-z]+)", plate: "([01]{3}\|[01]{3})" \}',
        _RANKS_TS.read_text(encoding="utf-8"),
    )
    assert [(rank, int(level), tier, plate) for rank, level, tier, plate in web] == _unreal_ladder()
    plates = [plate for *_, plate in _unreal_ladder()]
    assert len(set(plates)) == len(plates) == 15
    for plate in plates:  # left-right symmetric
        top, bottom = plate.split("|")
        assert top == top[::-1] and bottom == bottom[::-1]


def test_the_unreal_reporter_spells_every_end_reason_and_outcome():
    text = _CODEC.read_text(encoding="utf-8")
    block = re.search(r"EndReasonNames\[\] = \{(.*?)\};", text, re.S)
    assert block, "EndReasonNames not found"
    assert re.findall(r'TEXT\("([a-z_]+)"\)', block.group(1)) == list(DUEL_END_REASONS)
    for outcome in DUEL_OUTCOMES:
        assert f'TEXT("{outcome}")' in text


@pytest.mark.parametrize(
    "path",
    sorted((_SOURCE / "VerseBridge/Private/Duel").rglob("*.*")),
    ids=lambda p: p.name,
)
def test_the_reporter_never_includes_combat(path: Path):
    """combat-state.md 11.2: VerseBridge reads FVerseSetSummary from Core, never VerseCombat."""
    text = path.read_text(encoding="utf-8")
    includes = re.findall(r'#include\s+"([^"]+)"', text)
    combat = [
        i
        for i in includes
        if i.startswith("VerseCombat")
        or (
            (_SOURCE / "VerseCombat/Public" / i).exists()
            and not (_SOURCE / "VerseCore/Public" / i).exists()
        )
    ]
    assert combat == []
