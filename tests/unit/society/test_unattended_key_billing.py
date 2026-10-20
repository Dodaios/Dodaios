"""Unattended Society work never bills a per-token key once a subscription is connected.

The background billing rule (``dodaios.brain.background_policy``): with a
subscription connected, work nobody started by hand runs on subscriptions and
local models only, or waits. Society routines and the post-turn memory work
(review, skill learning) used to bypass it: a routine or an agent pinned to an
API-key seat billed that key while nobody was at the machine. These tests pin
the closed hole and the cases that keep working as before: a "Run now" click,
subscription and local seats, and an install that never connected a
subscription (a single-key download).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.brain import background_policy
from dodaios.brain.background_policy import BackgroundDeferred
from dodaios.control.cancel import CancelToken
from dodaios.core.bus import EventBus
from dodaios.core.protocols import started_by_user
from dodaios.society import routine_runner, seat_brain
from dodaios.society.review import _ask, review_turn
from dodaios.society.runtime import SocietyRuntime
from dodaios.tasks.runner import TaskRunner
from dodaios.tasks.schema import AgentAction, TaskSpec, TriggerEvery
from dodaios.tasks.store import TaskStore
from tests.fakes.fake_seat_registry import RecordingRegistry


def _connect_a_subscription() -> None:
    """A subscription login was seen: the install is in subscription mode."""
    background_policy.note_connected("claude-cli")


# ── routines ─────────────────────────────────────────────────────────────────


class _SessionStarted(Exception):
    """The run got past every billing gate and opened its routine chat."""


def _routine_runtime() -> SimpleNamespace:
    agent = SimpleNamespace(
        agent_id="scout", state="active", session_id="society:scout", runtime="jarvis",
        provider="gemini", account_id="", name="Scout",
    )

    async def kill_switch() -> bool:
        return False

    async def get(_agent_id: str) -> Any:
        return agent

    def create_session(**_kwargs: Any) -> Any:
        raise _SessionStarted

    service = SimpleNamespace(store=SimpleNamespace(create_session=create_session))
    return SimpleNamespace(
        store=SimpleNamespace(kill_switch=kill_switch),
        roster=SimpleNamespace(get=get),
        chat_service=lambda: service,
        config=lambda: None,
    )


@pytest.fixture
def routine_seat(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    """The routine runs on a pinned seat; ``billed`` says whether it is a key."""
    state = {"billed": True}

    async def seat_for_run(runtime: Any, agent: Any, task_id: str) -> tuple[str, str, str, str]:
        return "gemini", "gemini-chosen", "", ""

    monkeypatch.setattr(routine_runner, "_seat_for_run", seat_for_run)
    monkeypatch.setattr(routine_runner, "_workspace", lambda cfg, agent: "workspace")
    monkeypatch.setattr(
        routine_runner, "_billed_via_api", lambda provider, account_id="": state["billed"]
    )
    return state


async def _run(runtime: SimpleNamespace) -> None:
    await routine_runner.run_owned_routine(
        runtime, "t1", ("society", "agent:scout"), "Check the inbox."
    )


async def test_a_scheduled_run_on_a_key_seat_is_skipped_once_a_subscription_is_connected(
    routine_seat: dict[str, bool],
) -> None:
    _connect_a_subscription()
    with pytest.raises(BackgroundDeferred) as caught:
        await _run(_routine_runtime())  # no session is opened: nothing was billed
    message = str(caught.value)
    assert "gemini" in message and "Run now" in message


async def test_run_now_on_a_key_seat_is_the_persons_own_start(
    routine_seat: dict[str, bool],
) -> None:
    _connect_a_subscription()
    with started_by_user(), pytest.raises(_SessionStarted):
        await _run(_routine_runtime())


async def test_a_key_seat_still_runs_on_an_install_without_a_subscription(
    routine_seat: dict[str, bool],
) -> None:
    with pytest.raises(_SessionStarted):
        await _run(_routine_runtime())


async def test_a_subscription_or_local_seat_runs_unattended(
    routine_seat: dict[str, bool],
) -> None:
    _connect_a_subscription()
    routine_seat["billed"] = False
    with pytest.raises(_SessionStarted):
        await _run(_routine_runtime())


@pytest.fixture
async def task_store(tmp_path: Path):
    store = TaskStore(tmp_path / "runner.db")
    await store.init()
    try:
        yield store
    finally:
        await store.close()


async def test_the_task_runner_records_a_routine_deferral_as_a_skip(
    task_store: TaskStore,
) -> None:
    """The deferral is not wrapped into a "seat failed" error: no seat was asked."""

    async def owned_runner(task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any) -> str:
        raise BackgroundDeferred("A subscription is connected, so this run did not bill a key.")

    delivered: list[tuple[tuple[str, ...], str, str]] = []

    async def sink(tags: tuple[str, ...], text: str, status: str, **_: Any) -> None:
        delivered.append((tags, text, status))

    runner = TaskRunner(task_store, EventBus(), owned_agent_runner=owned_runner, result_sink=sink)
    task_id = await task_store.insert(
        TaskSpec(
            title="[agent:Scout] Inbox sweep",
            trigger=TriggerEvery(interval_seconds=86400),
            action=AgentAction(prompt="Sort the inbox."),
            tags=("society", "agent:scout"),
        )
    )
    await asyncio.wait_for(runner.run(task_id, CancelToken()), timeout=2.0)

    row = await task_store.get(task_id)
    assert row is not None and row["state"] == "scheduled"
    assert "did not bill a key" in (row["last_error"] or "")
    assert "not rerouted" not in (row["last_error"] or "")
    events = [step["payload"] for step in row["steps"]]
    assert any(e.get("event") == "skipped" and e.get("reason") == "waiting_capacity"
               for e in events)
    assert not any(e.get("event") == "owner_seat_failed" for e in events)
    assert delivered and "did not bill a key" in delivered[0][1]
    assert delivered[0][2] == "skipped"


# ── post-turn review and skill learning ──────────────────────────────────────


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> RecordingRegistry:
    from dodaios.brain import resolver
    from dodaios.core import config, runtime_refs

    reg = RecordingRegistry(["gemini", "openai", "codex", "claude-cli", "ollama"])
    monkeypatch.setattr(resolver, "_get_registry", lambda: reg)
    monkeypatch.setattr(config, "get_jarvis_agent_secret", lambda provider: f"agent-key-{provider}")
    monkeypatch.setattr(runtime_refs, "get_brain_manager", lambda: None)
    return reg


def _agent(provider: str, model: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider, model=model, effort="", agent_id="scout", account_id=""
    )


def _review_runtime() -> SimpleNamespace:
    return SimpleNamespace(config=lambda: None, skills_for=lambda agent_id: None)


async def test_a_review_does_not_bill_the_agents_key_once_a_subscription_is_connected(
    registry: RecordingRegistry,
) -> None:
    _connect_a_subscription()
    assert await _ask(_review_runtime(), _agent("gemini", "gemini-chosen"), "Evidence") is None
    assert registry.built == []  # nothing was built, so nothing could bill


async def test_skill_learning_refuses_a_key_seat_the_same_way(
    registry: RecordingRegistry,
) -> None:
    _connect_a_subscription()
    with pytest.raises(seat_brain.SeatDeferred):
        await seat_brain.agent_brain(
            None, _agent("gemini", "gemini-chosen"), caller="society-skill"
        )
    assert registry.built == []


async def test_a_review_on_a_key_seat_still_runs_without_a_subscription(
    registry: RecordingRegistry,
) -> None:
    assert await _ask(_review_runtime(), _agent("gemini", "gemini-chosen"), "Evidence") == {
        "memories": [], "skill": None,
    }
    assert registry.built_names() == ["gemini"]


@pytest.mark.parametrize(("provider", "built"), [("openai-codex", "codex"), ("ollama", "ollama")])
async def test_subscription_and_local_seats_keep_reviewing(
    registry: RecordingRegistry, provider: str, built: str
) -> None:
    _connect_a_subscription()
    await _ask(_review_runtime(), _agent(provider, "chosen"), "Evidence")
    assert registry.built_names() == [built]


def test_the_seat_billing_check_follows_the_runner_not_the_name() -> None:
    assert seat_brain.bills_per_token(seat_brain.Seat("gemini", runner="brain"))
    # A per-token provider card reached through its CLI runs on the subscription.
    assert not seat_brain.bills_per_token(seat_brain.Seat("openai-codex", runner="codex-cli"))
    # A keyless local runtime behind a brain plugin bills nothing.
    assert not seat_brain.bills_per_token(seat_brain.Seat("ollama", runner="brain"))


@pytest.fixture
async def society(tmp_path: Path):
    cfg = SimpleNamespace(wiki=SimpleNamespace(vault_root=str(tmp_path / "vault")))
    runtime = SocietyRuntime(tmp_path, cfg=lambda: cfg, seed_starter_team=False)
    await runtime.ensure_started()
    await runtime.roster.create(name="Scout", description="Draft only.")
    try:
        yield runtime
    finally:
        await runtime.close()


async def test_a_deferred_review_stays_pending_with_a_reason_the_ui_can_show(
    society: SocietyRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def deferred(config: Any, agent: Any, *, caller: str) -> Any:
        raise seat_brain.SeatDeferred("a subscription is connected; the key is not billed")

    monkeypatch.setattr(seat_brain, "agent_brain", deferred)
    pending = {
        "session": "society:scout",
        "turn_id": "turn-1",
        "direct_user": True,
        "events": [
            {"kind": "user_message", "payload": {"text": "Check the dates."}},
            {"kind": "assistant_text", "payload": {"text": "Done."}},
            {"kind": "turn_finished", "payload": {"status": "done"}},
        ],
    }
    assert not await review_turn(society, pending)
    record = json.loads(await society.store.get_meta("review:last:scout"))
    assert record["state"] == "pending"
    assert record["reason"] == "a subscription is connected; the key is not billed"
    assert record["reason_code"] == "api_key_seat"


async def test_a_review_dropped_after_its_retries_says_so_and_why(
    society: SocietyRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounded queue gives up; the agent's status shows the drop and its reason."""
    from dodaios.society import review_queue

    calls: list[str] = []

    async def deferred(config: Any, agent: Any, *, caller: str) -> Any:
        calls.append(caller)
        raise seat_brain.SeatDeferred("the key is not billed", provider="gemini")

    monkeypatch.setattr(seat_brain, "agent_brain", deferred)
    monkeypatch.setattr(review_queue.random, "uniform", lambda *args: 0)
    society.conversations.queue_review(
        "society:scout",
        "turn-1",
        [
            {"kind": "user_message", "payload": {"text": "Check the dates."}},
            {"kind": "assistant_text", "payload": {"text": "Done."}},
            {"kind": "turn_finished", "payload": {"status": "done"}},
        ],
        direct_user=True,
    )
    await society.recover_reviews()
    for _ in range(20):
        retry = getattr(society, "_memory_review_retry", None)
        if retry is None or retry.done():
            break
        await asyncio.wait_for(retry, 5)

    assert len(calls) == review_queue.MAX_ATTEMPTS  # bounded: no retry storm
    record = json.loads(await society.store.get_meta("review:last:scout"))
    assert record["state"] == "dropped"
    assert record["attempts"] == review_queue.MAX_ATTEMPTS
    assert record["reason_code"] == "api_key_seat"
    assert record["provider"] == "gemini"
    assert society.conversations.review_counts("scout")["dropped"] == 1
    assert society.conversations.pending_reviews() == []


async def test_a_seat_that_did_not_answer_is_named_as_the_reason(
    society: SocietyRuntime,
) -> None:
    async def silent(runtime: Any, agent: Any, prompt: str) -> None:
        from dodaios.society import review

        review._wait_reason.set({"reason_code": "seat_failed", "provider": "openai"})

    society.turn_reviewer = silent  # type: ignore[attr-defined]
    pending = {
        "session": "society:scout",
        "turn_id": "turn-2",
        "direct_user": True,
        "events": [
            {"kind": "user_message", "payload": {"text": "Sort the inbox."}},
            {"kind": "turn_finished", "payload": {"status": "done"}},
        ],
    }
    assert not await review_turn(society, pending)
    record = json.loads(await society.store.get_meta("review:last:scout"))
    assert record == {
        "turn_id": "turn-2",
        "updated_ms": record["updated_ms"],
        "state": "pending",
        "reason_code": "seat_failed",
        "provider": "openai",
    }
