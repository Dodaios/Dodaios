"""The owner stop record: scopes, persistence across a restart, who may lift it."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.safety.stop_hold import (
    StopHolds,
    blocking_for_job,
    refs_from_context,
    set_stop_holds,
    stop_holds,
)


def test_a_hold_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "holds.json"
    StopHolds(path).hold("routine", "t1", reason="not now", source="telegram")
    after_restart = StopHolds(path)  # a new process reads the same file
    hold = after_restart.blocking(routine="t1")
    assert hold is not None
    assert (hold.kind, hold.reason, hold.source) == ("routine", "not now", "telegram")


@pytest.mark.parametrize(
    ("kind", "ref", "query"),
    [
        ("job", "j1", {"job": "j1"}),
        ("routine", "t1", {"routine": "t1"}),
        ("trigger", "tr1", {"trigger": "tr1"}),
        ("agent", "ada", {"agent": "ada"}),
        ("session", "s1", {"session": "s1"}),
    ],
)
def test_each_scope_blocks_only_its_own_work(tmp_path: Path, kind: str, ref: str, query) -> None:
    holds = StopHolds(tmp_path / "h.json")
    holds.hold(kind, ref, reason="r")
    assert holds.blocking(**query) is not None
    assert holds.blocking() is None
    assert holds.blocking(job="other", routine="other", agent="other") is None


def test_everything_blocks_all_work_and_wins(tmp_path: Path) -> None:
    holds = StopHolds(tmp_path / "h.json")
    holds.hold("routine", "t1", reason="one")
    holds.hold("everything", reason="all")
    found = holds.blocking(routine="t1")
    assert found is not None and found.kind == "everything"
    assert holds.blocking(job="anything") is not None


def test_only_release_lifts_a_hold(tmp_path: Path) -> None:
    holds = StopHolds(tmp_path / "h.json")
    holds.hold("agent", "ada", reason="r")
    assert holds.hold("agent", "ada").reason == "r", "a refresh keeps the first reason"
    assert holds.release("agent", "ada") is not None
    assert holds.blocking(agent="ada") is None
    assert holds.release("agent", "ada") is None


def test_an_unreadable_record_does_not_lift_a_stop(tmp_path: Path) -> None:
    path = tmp_path / "h.json"
    holds = StopHolds(path)
    holds.hold("everything", reason="r")
    path.write_text("{ not json", encoding="utf-8")
    assert holds.blocking(job="x") is not None


def test_scope_needs_a_reference(tmp_path: Path) -> None:
    holds = StopHolds(tmp_path / "h.json")
    with pytest.raises(ValueError):
        holds.hold("routine", "")
    with pytest.raises(ValueError):
        holds.hold("planet", "x")


def test_refs_come_from_the_calling_layer() -> None:
    refs = refs_from_context({"task_id": "t1", "agent_id": "ada", "x": "y"})
    assert refs == {"routine": "t1", "agent": "ada"}


def test_a_repair_path_can_ask_before_touching_a_job() -> None:
    job = SimpleNamespace(id="j1", owner_session="s1", target="ada")
    assert blocking_for_job(job) is None
    stop_holds().hold("job", "j1", reason="owner stopped it")
    assert blocking_for_job(job) is not None
    stop_holds().release("job", "j1")
    stop_holds().hold("session", "s1", reason="r")
    assert blocking_for_job(job) is not None


def test_the_process_store_can_be_swapped(tmp_path: Path) -> None:
    own = StopHolds(tmp_path / "own.json")
    set_stop_holds(own)
    assert stop_holds() is own
