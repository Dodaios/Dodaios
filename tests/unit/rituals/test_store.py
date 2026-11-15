"""The ritual store: what was written survives, and a day is claimed exactly once."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.rituals.models import Ritual, RitualStep
from dodaios.rituals.store import RitualStore

DAY = "2026-03-02"


def _ritual(ritual_id: str = "rit_12345678", **changes) -> Ritual:
    fields = {
        "id": ritual_id,
        "name": "Good morning",
        "phrases": ("Good morning", "Morning"),
        "enabled": True,
        "window_from": "05:00",
        "window_to": "11:00",
        "weekdays": (0, 1, 2, 3, 4),
        "once_per_day": True,
        "prepare_from": "04:50",
        "steps": (
            RitualStep("s_aaaaaa", "now", "Play my favourite music."),
            RitualStep("s_bbbbbb", "ahead", "The AI news since yesterday."),
        ),
        "task_id": "",
        "origin": "owner",
        "created_ms": 10,
        "updated_ms": 20,
    }
    fields.update(changes)
    return Ritual(**fields)


@pytest.fixture
def store():
    opened = RitualStore(":memory:")
    try:
        yield opened
    finally:
        opened.close()


def test_a_ritual_comes_back_as_it_was_written(store: RitualStore) -> None:
    ritual = _ritual()
    store.save(ritual)
    assert store.get(ritual.id) == ritual
    assert store.get("rit_missing") is None
    assert ritual.steps_at("now") == (ritual.steps[0],)
    assert ritual.steps_at("ahead") == (ritual.steps[1],)


def test_saving_again_replaces_the_row_and_keeps_the_order(store: RitualStore) -> None:
    store.save(_ritual("rit_1", name="First", created_ms=1))
    store.save(_ritual("rit_2", name="Second", created_ms=2))
    store.save(_ritual("rit_1", name="First, renamed", created_ms=99, enabled=False))
    listed = store.list()
    assert [ritual.name for ritual in listed] == ["First, renamed", "Second"]
    # The first write's creation time stays.
    assert listed[0].created_ms == 1 and listed[0].enabled is False


def test_a_file_store_survives_being_reopened(tmp_path: Path) -> None:
    path = tmp_path / "data" / "rituals.db"
    first = RitualStore(path)
    first.save(_ritual())
    first.claim_fire("rit_12345678", DAY, 5, "voice")
    first.close()
    second = RitualStore(path)
    try:
        assert second.get("rit_12345678") == _ritual()
        assert second.day("rit_12345678", DAY).fired_via == "voice"
    finally:
        second.close()


def test_the_phrase_starts_a_day_exactly_once(store: RitualStore) -> None:
    assert store.day("rit_1", DAY) is None
    assert store.claim_fire("rit_1", DAY, 100, "voice") is True
    assert store.claim_fire("rit_1", DAY, 200, "chat") is False
    row = store.day("rit_1", DAY)
    assert (row.phrase_ms, row.fired_ms, row.fired_via) == (100, 100, "voice")
    # Another day, and another ritual, are their own claims.
    assert store.claim_fire("rit_1", "2026-03-03", 300, "chat") is True
    assert store.claim_fire("rit_2", DAY, 400, "chat") is True


def test_a_click_is_the_newest_start_and_leaves_the_phrase_as_it_was(store: RitualStore) -> None:
    # A click before the phrase: the phrase still has its one start of the day.
    store.record_fire("rit_0", DAY, 50, "button")
    assert store.day("rit_0", DAY).phrase_ms is None
    assert store.claim_fire("rit_0", DAY, 60, "voice") is True

    store.claim_fire("rit_1", DAY, 100, "voice")
    store.patch_day("rit_1", DAY, results=["Music is playing."], delivered_ms=150)
    store.record_fire("rit_1", DAY, 900, "button")
    row = store.day("rit_1", DAY)
    assert (row.fired_ms, row.fired_via) == (900, "button")
    # What the earlier start did and delivered belongs to that start.
    assert row.results == () and row.delivered_ms is None
    # The click did not hand the phrase a second start.
    assert row.phrase_ms == 100
    assert store.claim_fire("rit_1", DAY, 950, "voice") is False


def test_what_was_gathered_is_kept_on_the_day_and_outlives_a_start(store: RitualStore) -> None:
    row = store.patch_day(
        "rit_1", DAY, prep_state="ready", prepared_ms=50, steps_hash="h",
        spoken="Three things today.", written="## Today\n- one",
    )
    assert (row.prep_state, row.prepared_ms, row.spoken) == ("ready", 50, "Three things today.")
    assert row.fired_ms is None
    assert store.claim_fire("rit_1", DAY, 100, "voice") is True
    kept = store.day("rit_1", DAY)
    assert kept.written == "## Today\n- one" and kept.prep_state == "ready"
    assert kept.to_dict() == {
        "day": DAY, "prep_state": "ready", "prep_error": "", "prepared_ms": 50,
        "fired_ms": 100, "fired_via": "voice", "results": [], "delivered_ms": None,
        "phrase_ms": 100,
    }
    assert kept.to_dict(with_text=True)["written"] == "## Today\n- one"
    with pytest.raises(ValueError, match="not a day field"):
        store.patch_day("rit_1", DAY, colour="blue")


def test_removing_a_ritual_takes_its_days_along(store: RitualStore) -> None:
    store.save(_ritual("rit_1"))
    store.claim_fire("rit_1", DAY, 100, "voice")
    assert store.delete("rit_1") is True
    assert store.delete("rit_1") is False
    assert store.get("rit_1") is None and store.day("rit_1", DAY) is None


def test_old_days_are_dropped(store: RitualStore) -> None:
    store.claim_fire("rit_1", "2026-01-31", 1, "voice")
    store.claim_fire("rit_1", "2026-02-01", 2, "voice")
    store.claim_fire("rit_2", "2026-03-02", 3, "voice")
    assert store.prune("2026-02-01") == 1
    assert store.day("rit_1", "2026-01-31") is None
    assert [row.ritual_id for row in store.days("2026-03-02")] == ["rit_2"]
