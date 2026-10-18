"""Loss-streak pause: definition, 24 h pause, restart safety, re-check, notification queue."""

import json

import pytest

from jarvis.trading_research.loss_streak import DAY_MS, ClosedTrade, LossStreakGuard

T0 = 1_800_000_000_000


def g(tmp_path):
    return LossStreakGuard(str(tmp_path / "streak.json"))


def losses(guard, n, start=T0, step=60_000):
    started = [guard.record_close(ClosedTrade(f"t{i}", start + i * step, -1.0)) for i in range(n)]
    return started


def test_three_losses_start_a_24h_pause(tmp_path):
    guard = g(tmp_path)
    assert losses(guard, 3) == [False, False, True]
    p = guard.state["pause"]
    assert p["start_ms"] == T0 + 120_000 and p["end_ms"] == T0 + 120_000 + DAY_MS
    assert p["trades"] == ["t0", "t1", "t2"]
    assert guard.allows_open(T0 + 120_001) == (False, "loss-streak pause active")


def test_zero_result_is_not_a_loss_and_resets(tmp_path):
    guard = g(tmp_path)
    losses(guard, 2)
    guard.record_close(ClosedTrade("flat", T0 + 999_999, 0.0))
    guard.record_close(ClosedTrade("l3", T0 + 1_000_000, -0.01))
    assert guard.state["pause"] is None
    assert guard.state["streak"] == ["l3"]


def test_fee_turned_loss_counts(tmp_path):
    guard = g(tmp_path)
    for i in range(3):
        guard.record_close(
            ClosedTrade(f"f{i}", T0 + i, -0.0001)
        )  # gross win smaller than fees -> net loss
    assert guard.state["pause"] is not None


def test_streak_survives_restart_and_replay_is_ignored(tmp_path):
    guard = g(tmp_path)
    losses(guard, 2)
    again = g(tmp_path)  # restart
    assert again.state["streak"] == ["t0", "t1"]
    assert again.record_close(ClosedTrade("t1", T0 + 60_000, -1.0)) is False  # replayed close
    assert again.state["streak"] == ["t0", "t1"]
    assert again.record_close(ClosedTrade("t2", T0 + 180_000, -1.0)) is True


def test_after_pause_a_recheck_is_required(tmp_path):
    guard = g(tmp_path)
    losses(guard, 3)
    end = guard.state["pause"]["end_ms"]
    assert guard.allows_open(end) == (False, "loss-streak pause ended: risk re-check pending")
    with pytest.raises(ValueError):
        guard.confirm_recheck(end - 1, "too early")
    with pytest.raises(ValueError):
        guard.confirm_recheck(end, "  ")
    guard.confirm_recheck(end + 5, "open risk 0 %, limits unchanged")
    assert guard.allows_open(end + 6) == (True, None)
    assert guard.state["pauses"][-1]["recheck_note"] == "open risk 0 %, limits unchanged"
    assert g(tmp_path).allows_open(end + 6) == (True, None)  # persisted


def test_notification_is_queued_not_sent(tmp_path):
    guard = g(tmp_path)
    losses(guard, 3)
    (n,) = guard.pending_notifications()
    assert n["kind"] == "loss_streak_pause" and n["delivered"] is False


def test_rule_has_no_way_to_touch_positions():
    public = {n for n in dir(LossStreakGuard) if not n.startswith("_")}
    assert public == {"record_close", "allows_open", "confirm_recheck", "pending_notifications"}


def test_out_of_order_and_corrupt_state_raise(tmp_path):
    guard = g(tmp_path)
    guard.record_close(ClosedTrade("a", T0 + 10, -1))
    with pytest.raises(ValueError):
        guard.record_close(ClosedTrade("b", T0, -1))
    (tmp_path / "streak.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        g(tmp_path)
