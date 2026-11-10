"""Seat health: real call outcomes, parsed reset times, TTL verdicts, streaks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from dodaios.brain import provider_health_ledger as ledger
from dodaios.brain import seat_health as sh
from dodaios.brain.background_policy import BackgroundDeferred

NOW = datetime(2026, 11, 10, 12, 0, 0).timestamp()


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make(path: Path | None = None) -> tuple[sh.SeatHealth, Clock]:
    clock = Clock()
    return sh.SeatHealth(path, clock=clock), clock


# -- reset-time parsing ------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "seconds"),
    [
        ("Rate limited. Try again in 2h 30m.", 9000),
        ("usage limit reached, resets in 45 minutes", 2700),
        ("Please retry after 120 seconds", 120),
        ("retry-after: 90", 90),
        ("You've hit your limit - resets 3pm", 3 * 3600),
        ("limit reached, resets at 15:30", 3.5 * 3600),
        ("resets 9am", 21 * 3600),  # already past today: tomorrow 09:00
    ],
)
def test_reset_time_is_read_from_the_message(message: str, seconds: float) -> None:
    got = sh.parse_reset_time(message, now=NOW)
    assert got is not None
    assert got - NOW == pytest.approx(seconds, abs=1)


@pytest.mark.parametrize("message", ["", "something broke", "resets 3", "try again in 400 days"])
def test_unparseable_or_absurd_reset_is_none(message: str) -> None:
    assert sh.parse_reset_time(message, now=NOW) is None


# -- classification ----------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "cls"),
    [
        ("HTTP 429 insufficient_quota", sh.CLASS_QUOTA),
        ("You've hit your usage limit", sh.CLASS_QUOTA),
        ("429 Too Many Requests", sh.CLASS_RATE),
        ("authentication failed or timed out", sh.CLASS_AUTH),
        ("Not logged in. Run codex login", sh.CLASS_AUTH),
        ("invalid model selection gemini-3.8-flash", sh.CLASS_MODEL),
        ("The selected model is unavailable on this ChatGPT subscription", sh.CLASS_MODEL),
        ("kaboom", sh.CLASS_OTHER),
    ],
)
def test_failures_fold_onto_a_seat_class(message: str, cls: str) -> None:
    assert sh.classify_seat_failure(message) == cls


# -- verdicts ----------------------------------------------------------------
def test_quota_holds_until_the_parsed_reset_then_clears() -> None:
    health, clock = make()
    health.record_failure("codex", "", "usage limit reached, try again in 2h")
    verdict = health.verdict("codex", "")
    assert verdict is not None and verdict.cls == sh.CLASS_QUOTA
    assert verdict.until == pytest.approx(NOW + 7200)
    assert "back around" in health.health_line("codex", "")
    clock.now = NOW + 7201
    assert health.verdict("codex", "") is None


def test_quota_without_a_time_uses_a_bounded_default() -> None:
    health, _ = make()
    health.record_failure("codex", "", "weekly limit reached")
    assert health.verdict("codex", "").until == pytest.approx(NOW + sh.QUOTA_WEEKLY_S)
    health.record_failure("claude", "", "quota exceeded")
    assert health.verdict("claude", "").until == pytest.approx(NOW + sh.QUOTA_DEFAULT_S)


def test_auth_verdict_lasts_six_hours_or_until_the_key_changes() -> None:
    health, clock = make()
    health.record_failure("openai", "", "401 invalid api key", credential="fp-old")
    assert health.verdict("openai", "", credential="fp-old").blocked is True
    assert health.verdict("openai", "", credential="fp-new") is None  # key replaced
    clock.now = NOW + sh.BLOCK_TTL_S - 1
    assert health.verdict("openai", "") is not None
    clock.now = NOW + sh.BLOCK_TTL_S + 1
    assert health.verdict("openai", "") is None


def test_a_model_verdict_only_blocks_that_model() -> None:
    health, _ = make()
    health.record_failure("codex", "", "invalid model selection x-1", model="x-1")
    assert health.verdict("codex", "", model="x-1").cls == sh.CLASS_MODEL
    assert health.verdict("codex", "", model="gpt-5.5") is None
    assert health.verdict("codex", "") is None


def test_seats_are_per_login() -> None:
    health, _ = make()
    health.record_failure("claude", "work", "usage limit reached")
    assert health.verdict("claude", "work") is not None
    assert health.verdict("claude", "home") is None


def test_a_success_clears_the_seat() -> None:
    health, _ = make()
    health.record_failure("codex", "", "usage limit reached")
    health.record_success("codex", "")
    assert health.verdict("codex", "") is None
    assert health.health_line("codex", "") == ""


def test_failure_counts_roll_per_class() -> None:
    health, clock = make()
    health.record_failure("codex", "", "usage limit reached")
    health.record_failure("codex", "", "kaboom")
    assert health.failure_counts("codex") == {sh.CLASS_QUOTA: 1, sh.CLASS_OTHER: 1}
    clock.now = NOW + 25 * 3600
    assert health.failure_counts("codex") == {}


def test_notice_fires_once_per_same_class_streak() -> None:
    health, _ = make()
    flags = [health.record_failure("codex", "", "usage limit reached").notify for _ in range(5)]
    assert flags == [False, False, True, False, False]
    # A different class restarts the streak, and so does a success.
    assert health.record_failure("codex", "", "401 unauthorized").notify is False
    health.record_success("codex", "")
    flags = [health.record_failure("codex", "", "usage limit reached").notify for _ in range(3)]
    assert flags == [False, False, True]


def test_unclassified_failures_never_notify() -> None:
    health, _ = make()
    assert not any(health.record_failure("codex", "", "kaboom").notify for _ in range(6))


def test_verdicts_survive_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "seat_health.json"
    first, clock = make(path)
    first.record_failure("codex", "", "401 unauthorized", credential="fp")
    second = sh.SeatHealth(path, clock=clock)
    assert second.verdict("codex", "").cls == sh.CLASS_AUTH
    second.forget("codex")
    assert sh.SeatHealth(path, clock=clock).verdict("codex", "") is None


def test_an_unreadable_record_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "seat_health.json"
    path.write_text("{not json", encoding="utf-8")
    assert sh.SeatHealth(path).verdict("codex", "") is None


# -- the callers -------------------------------------------------------------
def test_only_a_known_dead_fallback_is_skipped() -> None:
    health = sh.get_seat_health()
    assert sh.fallback_is_known_dead("openai", "gpt") is False
    health.record_failure("openai", "", "401 invalid api key")
    assert sh.fallback_is_known_dead("openai", "gpt") is True
    health.record_success("openai", "")
    assert sh.fallback_is_known_dead("openai", "gpt") is False


def test_background_work_waits_on_a_cooling_seat_and_never_swaps() -> None:
    health = sh.get_seat_health()
    attempts = [("codex", "m1"), ("claude", "m2")]
    assert sh.wait_out_cooling_seats(attempts) == attempts
    health.record_failure("codex", "", "usage limit reached, try again in 2h")
    assert sh.wait_out_cooling_seats(attempts) == [("claude", "m2")]
    health.record_failure("claude", "", "usage limit reached, try again in 1h")
    with pytest.raises(BackgroundDeferred) as raised:
        sh.wait_out_cooling_seats(attempts)
    assert raised.value.code == "seat_cooldown"
    assert raised.value.provider == "claude"  # the earliest reset


def test_the_provider_ledger_feeds_seat_health_from_real_calls_only() -> None:
    ledger.record_failure("codex", ledger.MODALITY_BRAIN, "429 usage limit reached")
    assert sh.get_seat_health().verdict("codex", "") is not None
    # An explicit Test click and voice modalities are not seat evidence.
    ledger.record_failure("grok", ledger.MODALITY_TTS, "401 unauthorized")
    ledger.record_failure(
        "gemini", ledger.MODALITY_BRAIN, "401 unauthorized", source=ledger.SOURCE_TEST
    )
    assert sh.get_seat_health().verdict("grok", "") is None
    assert sh.get_seat_health().verdict("gemini", "") is None
    ledger.record_success("codex", ledger.MODALITY_BRAIN)
    assert sh.get_seat_health().verdict("codex", "") is None


def test_changing_a_key_forgets_the_seat_verdict() -> None:
    ledger.record_failure("openai", ledger.MODALITY_BRAIN, "401 invalid api key")
    assert sh.get_seat_health().verdict("openai", "") is not None
    ledger.forget_providers(["openai"])
    assert sh.get_seat_health().verdict("openai", "") is None
