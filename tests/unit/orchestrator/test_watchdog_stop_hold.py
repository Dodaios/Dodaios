"""The watchdog never repairs or re-queues work the owner stopped, and its repairs
run under the ``watchdog`` origin."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.orchestrator import jobs
from dodaios.orchestrator.watchdog import checks, live
from dodaios.orchestrator.watchdog.checks import Finding
from dodaios.safety.reversibility import unattended_origin
from dodaios.safety.stop_hold import stop_holds


class _Hop:
    def __call__(self, fn: Any, *_a: Any) -> Any:
        raise AssertionError("not used here")


def _actions(service: Any = None) -> live.LiveActions:
    runtime = SimpleNamespace(chat_service=lambda: service)
    return live.LiveActions(runtime, _Hop())  # type: ignore[arg-type]


def _requeue_finding(job_id: str) -> Finding:
    return Finding(
        key=f"{checks.KIND_INTERRUPTED_JOB}:{job_id}",
        kind=checks.KIND_INTERRUPTED_JOB,
        title="t",
        evidence={"job_id": job_id, "kind": "mission"},
        repair=checks.ACT_REQUEUE,
        open_ref=job_id,
    )


@pytest.fixture
def seen(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def requeuer(job: jobs.Job) -> str:
        calls.append((job.id, unattended_origin({})))
        return "new-1"

    monkeypatch.setitem(live._requeuers, "mission", requeuer)
    return calls


def _interrupted(job_id: str = "job_a", session: str = "s1") -> jobs.Job:
    ledger = jobs.get_ledger()
    ledger.create("mission", job_id=job_id, owner_session=session, title="m", state="running")
    return ledger.update(job_id, state="interrupted")


async def test_requeue_runs_under_the_watchdog_origin(seen) -> None:
    _interrupted()
    note = await _actions().requeue("job_a")
    assert note is not None and seen == [("job_a", "watchdog")]


@pytest.mark.parametrize(("kind", "ref"), [("job", "job_a"), ("session", "s1"), ("everything", "")])
async def test_a_stop_hold_blocks_the_requeue(seen, kind: str, ref: str) -> None:
    _interrupted()
    stop_holds().hold(kind, ref, reason="owner stopped it")
    assert await _actions().requeue("job_a") is None
    assert seen == []
    assert jobs.get_ledger().get("job_a").state == "interrupted"


def test_a_held_finding_is_not_repairable(seen) -> None:
    actions = _actions()
    assert actions.can_repair(_requeue_finding("job_a"))
    stop_holds().hold("job", "job_a", reason="r")
    assert not actions.can_repair(_requeue_finding("job_a"))
    assert actions.can_repair(_requeue_finding("job_b"))


async def test_a_nudge_respects_a_session_hold_and_runs_as_watchdog() -> None:
    steered: list[tuple[str, str]] = []

    class Svc:
        async def steer(self, sid: str, text: str) -> bool:
            steered.append((sid, unattended_origin({})))
            return True

    actions = _actions(Svc())
    assert await actions.nudge("s1") is True
    assert steered == [("s1", "watchdog")]
    stop_holds().hold("session", "s1", reason="r")
    assert await actions.nudge("s1") is False
    assert len(steered) == 1
