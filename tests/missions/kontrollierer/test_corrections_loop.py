"""A correction given while a mission runs reaches its next attempt."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.missions.kontrollierer import orchestrator
from dodaios.missions.manager import MissionManager
from dodaios.missions.state_machine import MissionState
from tests.missions.kontrollierer.test_loop import (
    FakeCriticRunner,
    FakeWorker,
    _make_approve_verdict,
    _make_kontrollierer,
    _make_revise_verdict,
    manager,  # noqa: F401 - the shared MissionManager fixture
)

_CORRECTION = "Use a dark colour scheme instead of the light one."
_MARK = "USER CORRECTIONS"


class _AmendingWorker(FakeWorker):
    """A worker during whose chosen attempt the user corrects the mission."""

    def __init__(self, *, amend_during: int) -> None:
        super().__init__()
        self._amend_during = amend_during
        self.kontrollierer = None
        self.mission_id = ""

    async def spawn(self, prompt, **kwargs):
        attempt = len(self.spawn_calls)
        async for event in super().spawn(prompt, **kwargs):
            yield event
        if attempt == self._amend_during:
            self.kontrollierer.amend_mission(self.mission_id, _CORRECTION)


async def _run(manager, tmp_path, critic, worker, *, amend_first: bool = False):  # noqa: F811
    k = _make_kontrollierer(
        manager=manager, tmp_path=tmp_path, critic=critic, worker_factory_fn=lambda step: worker
    )
    mid = await manager.dispatch(prompt="build the settings page")
    if isinstance(worker, _AmendingWorker):
        worker.kontrollierer, worker.mission_id = k, mid
    if amend_first:
        k.amend_mission(mid, _CORRECTION)
    return k, mid, await k.run_mission(mid)


@pytest.mark.asyncio
async def test_a_correction_during_an_attempt_is_followed_by_one_more(
    manager: MissionManager, tmp_path: Path  # noqa: F811
) -> None:
    critic = FakeCriticRunner(_make_approve_verdict(), _make_approve_verdict())
    worker = _AmendingWorker(amend_during=0)
    k, mid, end = await _run(manager, tmp_path, critic, worker)
    assert end == MissionState.APPROVED
    first, second = (call["prompt"] for call in worker.spawn_calls)
    assert _MARK not in first
    # The step's own task stays; the correction is added in front of it.
    assert _MARK in second and _CORRECTION in second and second.endswith("do task")
    # The second result is judged against the task as the user corrected it.
    assert _CORRECTION not in critic.calls[0]["mission_prompt"]
    assert _CORRECTION in critic.calls[1]["mission_prompt"]
    assert k.mission_corrections(mid)["unapplied_corrections"] == []


@pytest.mark.asyncio
async def test_a_correction_given_before_the_first_attempt_needs_no_extra_one(
    manager: MissionManager, tmp_path: Path  # noqa: F811
) -> None:
    critic = FakeCriticRunner(_make_approve_verdict())
    worker = FakeWorker()
    k, mid, end = await _run(manager, tmp_path, critic, worker, amend_first=True)
    assert end == MissionState.APPROVED and len(worker.spawn_calls) == 1
    assert _CORRECTION in worker.spawn_calls[0]["prompt"]
    assert _CORRECTION in critic.calls[0]["mission_prompt"]
    assert [item["text"] for item in k.mission_corrections(mid)["corrections"]] == [_CORRECTION]


@pytest.mark.asyncio
async def test_without_corrections_nothing_is_added_to_the_task(
    manager: MissionManager, tmp_path: Path  # noqa: F811
) -> None:
    critic = FakeCriticRunner(_make_approve_verdict())
    worker = FakeWorker()
    k, mid, end = await _run(manager, tmp_path, critic, worker)
    assert end == MissionState.APPROVED and len(worker.spawn_calls) == 1
    assert _MARK not in worker.spawn_calls[0]["prompt"]
    assert critic.calls[0]["mission_prompt"] == "build the settings page"
    assert k.mission_corrections(mid) == {}


@pytest.mark.asyncio
async def test_a_correction_during_the_last_attempt_is_reported_as_not_applied(
    manager: MissionManager, tmp_path: Path  # noqa: F811
) -> None:
    critic = FakeCriticRunner(
        _make_revise_verdict("first"), _make_revise_verdict("second"), _make_approve_verdict()
    )
    worker = _AmendingWorker(amend_during=orchestrator.MAX_CRITIC_LOOPS - 1)
    k, mid, end = await _run(manager, tmp_path, critic, worker)
    assert end == MissionState.APPROVED
    assert len(worker.spawn_calls) == orchestrator.MAX_CRITIC_LOOPS  # no attempt beyond the cap
    late = k.mission_corrections(mid)["unapplied_corrections"]
    assert [item["text"] for item in late] == [_CORRECTION]


@pytest.mark.asyncio
async def test_no_extra_attempt_is_started_without_time_to_finish_it(
    manager: MissionManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    monkeypatch.setattr(orchestrator, "_TASK_TIME_BUDGET_S", 0.0)
    critic = FakeCriticRunner(_make_approve_verdict(), _make_approve_verdict())
    worker = _AmendingWorker(amend_during=0)
    k, mid, end = await _run(manager, tmp_path, critic, worker)
    assert end == MissionState.APPROVED and len(worker.spawn_calls) == 1
    assert len(k.mission_corrections(mid)["unapplied_corrections"]) == 1


def test_an_empty_or_oversized_correction_is_refused(tmp_path: Path) -> None:
    from dodaios.missions.corrections import MAX_CORRECTION_CHARS, CorrectionInbox

    inbox = CorrectionInbox(tmp_path / "mission")
    for bad in ("", "   ", "x" * (MAX_CORRECTION_CHARS + 1)):
        with pytest.raises(ValueError):
            inbox.add(bad)
    assert inbox.read() == []


def test_corrections_survive_a_restart_and_a_torn_last_line(tmp_path: Path) -> None:
    from dodaios.missions.corrections import CorrectionInbox, render

    inbox = CorrectionInbox(tmp_path / "mission")
    inbox.add("First  correction\nover two lines")
    inbox.add("Second correction")
    with inbox.path.open("a", encoding="utf-8") as handle:
        handle.write('{"text": "torn')  # the app died while writing this one
    reread = CorrectionInbox(tmp_path / "mission").read()
    assert [(item.number, item.text) for item in reread] == [
        (1, "First correction over two lines"),
        (2, "Second correction"),
    ]
    block = render(reread)
    assert block.index("1. First") < block.index("2. Second")
    assert "a later correction wins over an earlier one" in block
    assert render([]) == ""


def test_a_correction_added_after_a_torn_line_is_kept_and_returned(tmp_path: Path) -> None:
    from dodaios.missions.corrections import CorrectionInbox

    inbox = CorrectionInbox(tmp_path / "mission")
    inbox.add("First correction")
    with inbox.path.open("a", encoding="utf-8") as handle:
        handle.write('{"text": "torn')  # the app died while writing this one
    added = inbox.add("Second correction")
    assert (added.number, added.text) == (2, "Second correction")
    assert [item.text for item in inbox.read()] == ["First correction", "Second correction"]


def test_steps_noting_late_corrections_at_once_lose_none(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from dodaios.missions.corrections import CorrectionInbox

    inbox = CorrectionInbox(tmp_path / "mission")
    corrections = [inbox.add(f"Correction {index}") for index in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(
            pool.map(lambda item: inbox.note_unapplied(f"step-{item.number}", [item]), corrections)
        )
    assert [item.number for item in inbox.unapplied()] == list(range(1, 13))


def test_an_unreadable_record_of_late_corrections_is_reported_not_fatal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from dodaios.missions.corrections import CorrectionInbox

    inbox = CorrectionInbox(tmp_path / "mission")
    inbox.add("Only correction")
    inbox.path.with_name("corrections-unapplied.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert inbox.unapplied() == []
    assert "Unreadable record of late corrections" in caplog.text


@pytest.mark.asyncio
async def test_the_extra_attempt_is_recorded_as_the_users_wish_not_the_reviewers(
    manager: MissionManager, tmp_path: Path  # noqa: F811
) -> None:
    from dodaios.missions.events import WorkerCorrectionRequired

    critic = FakeCriticRunner(_make_approve_verdict(), _make_approve_verdict())
    worker = _AmendingWorker(amend_during=0)
    _k, mid, _end = await _run(manager, tmp_path, critic, worker)
    asked = [
        envelope for envelope in await manager.store.events_for_mission(mid)
        if isinstance(envelope.payload, WorkerCorrectionRequired)
    ]
    assert [(e.source_actor, e.payload.correction_instruction) for e in asked] == [
        ("ui", _CORRECTION)
    ]
