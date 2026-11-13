"""Keeping a node current: one tagged lead routine per node, checked against it.

The renderers are not under test: a stand-in kind is registered for the two
types these tests use.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import proactive_checks
from dodaios.nodes import kinds, refresh, shell
from dodaios.nodes.kinds import NodeKind
from dodaios.nodes.model import Node
from dodaios.nodes.store import (
    DEFAULT_EVERY_MINUTES,
    MIN_EVERY_MINUTES,
    NodeStore,
)
from dodaios.nodes.types import NodeError
from dodaios.tasks.schema import TaskSpec

SPEC: dict[str, Any] = {"rows": [["Shoes", "In transit"], ["Books", "Delivered"]]}


def _kind(name: str) -> NodeKind:
    return NodeKind(
        type=name,
        normalize=lambda spec: {"rows": [list(row) for row in spec.get("rows", [])]},
        render=lambda node: shell.document(
            node, body=f"<main>{shell.esc(len(node.spec['rows']))} rows</main>"
        ),
        preview=lambda spec: {"rows": len(spec["rows"])},
        starter=lambda title, language: {"rows": []},
        guide="rows: a list of lists",
    )


@pytest.fixture(autouse=True)
def fake_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kinds, "_KINDS", {name: _kind(name) for name in ("sheets", "data")})


def _store(tmp_path: Path) -> NodeStore:
    return NodeStore(root=tmp_path)


def _parcels(store: NodeStore) -> Node:
    return store.create(type="sheets", title="My parcels", spec=SPEC, now=1_700_000_000)


class _TaskStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def insert(self, spec: TaskSpec) -> str:
        task_id = f"task-{len(self.rows) + 1}"
        self.rows.append(
            {"id": task_id, "state": "scheduled", "spec_json": spec.model_dump_json(), "spec": spec}
        )
        return task_id

    async def list(self, state_filter=None, *, limit: int = 100) -> list[dict]:
        return list(self.rows)

    async def get(self, task_id: str) -> dict | None:
        return next((r for r in self.rows if r["id"] == task_id), None)

    async def get_spec(self, task_id: str) -> TaskSpec | None:
        row = await self.get(task_id)
        return row["spec"] if row else None

    async def delete(self, task_id: str) -> bool:
        self.rows = [r for r in self.rows if r["id"] != task_id]
        return True


class _Scheduler:
    def __init__(self, store: _TaskStore) -> None:
        self.store = store

    async def schedule(self, spec: TaskSpec) -> str:
        return await self.store.insert(spec)

    async def cancel_task(self, task_id: str, reason: str = "") -> bool:
        row = await self.store.get(task_id)
        if row:
            row["state"] = "cancelled"
        return True


class _Roster:
    def __init__(self, *, lead: bool = True) -> None:
        self._lead = lead

    async def get(self, agent_id: str):
        if not self._lead:
            return None
        return SimpleNamespace(
            agent_id=agent_id,
            name="Dodaios",
            title="",
            description="",
            focus=(),
            provider="claude-cli",
            model="m",
            effort="low",
            account_id="",
        )


def _society(
    monkeypatch: pytest.MonkeyPatch, tasks: _TaskStore | None, *, lead: bool = True
) -> None:
    """Put a society runtime with these task services in place (``None``: down)."""
    runtime = None
    if tasks is not None:
        scheduler = _Scheduler(tasks)
        runtime = SimpleNamespace(
            roster=_Roster(lead=lead), task_services=lambda: (tasks, scheduler)
        )
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: runtime)


def _alive(tasks: _TaskStore) -> list[dict]:
    return [row for row in tasks.rows if row["state"] != "cancelled"]


async def test_refresh_is_one_tagged_quiet_lead_routine_that_can_restart_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = _parcels(store)

    live = await refresh.start_refresh(
        store, node.id, track="Parcels on  their way,\nfrom shipping mails.", every_minutes=60
    )
    assert live.refreshing and live.task_id == "task-1"
    assert live.track == "Parcels on their way, from shipping mails."
    spec = tasks.rows[0]["spec"]
    assert refresh.tag_for(node.id) == f"node:{node.id}" and refresh.tag_for(node.id) in spec.tags
    assert "agent:jarvis" in spec.tags
    assert spec.trigger.interval_seconds == 60 * 60
    # A refresh shows on the page itself: its runs post no card into the chat.
    assert proactive_checks.quiet_routine(spec.tags)
    prompt = spec.action.prompt
    assert node.id in prompt and "My parcels" in prompt and live.track in prompt
    assert 'operation "get"' in prompt and 'operation "update"' in prompt
    assert "do not send" in prompt.lower() and "never create a second node" in prompt.lower()
    assert await refresh.refresh_live(live)

    # Starting again replaces the routine instead of adding a second one, and
    # keeps what the node tracks when no new instruction comes with it.
    again = await refresh.start_refresh(store, node.id, every_minutes=120)
    alive = _alive(tasks)
    assert len(alive) == 1 and again.task_id == alive[0]["id"]
    assert again.track == live.track and again.every_minutes == 120
    assert alive[0]["spec"].trigger.interval_seconds == 120 * 60

    stopped = await refresh.stop_refresh(store, node.id)
    assert not stopped.refreshing and stopped.task_id == ""
    assert _alive(tasks) == []
    # The node keeps its content and what it tracked, so it can be resumed.
    assert stopped.spec == node.spec and stopped.track == live.track
    assert not await refresh.refresh_live(stopped)


async def test_cadence_defaults_and_stays_inside_its_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = _parcels(store)
    plain = await refresh.start_refresh(store, node.id, track="parcels")
    assert plain.every_minutes == DEFAULT_EVERY_MINUTES
    hasty = await refresh.start_refresh(store, node.id, every_minutes=1)
    assert hasty.every_minutes == MIN_EVERY_MINUTES
    assert _alive(tasks)[0]["spec"].trigger.interval_seconds == MIN_EVERY_MINUTES * 60


async def test_a_routine_paused_or_deleted_elsewhere_reads_as_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = await refresh.start_refresh(store, _parcels(store).id, track="parcels")
    assert (await refresh.node_state(node))["refreshing"] is True

    tasks.rows[0]["state"] = "paused"
    assert not await refresh.refresh_live(node)
    state = await refresh.node_state(node)
    assert state["refreshing"] is False and "spec" not in state
    assert (await refresh.node_state(node, with_spec=True))["spec"] == SPEC

    tasks.rows.clear()
    assert not await refresh.refresh_live(node)


async def test_only_this_nodes_own_live_lead_routine_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    first = await refresh.start_refresh(store, _parcels(store).id, track="parcels")
    other = store.create(type="data", title="Numbers", spec=SPEC)
    other = await refresh.start_refresh(store, other.id, track="numbers")
    assert len(_alive(tasks)) == 2

    # Stopping one node leaves the other node's routine alone.
    await refresh.stop_refresh(store, first.id)
    (left,) = _alive(tasks)
    assert refresh.tag_for(other.id) in left["spec"].tags
    assert await refresh.refresh_live(other)
    # A finished routine is not a live refresh.
    left["state"] = "completed"
    assert not await refresh.refresh_live(other)


async def test_start_refuses_an_unknown_node_and_one_that_tracks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = _parcels(store)
    with pytest.raises(NodeError, match="No node with id"):
        await refresh.start_refresh(store, "0123456789ab", track="x")
    with pytest.raises(NodeError, match="'track' must say"):
        await refresh.start_refresh(store, node.id)
    with pytest.raises(NodeError, match="'track' must say"):
        await refresh.start_refresh(store, node.id, track="   ")
    with pytest.raises(NodeError, match="No node with id"):
        await refresh.stop_refresh(store, "0123456789ab")
    assert tasks.rows == [] and not store.get(node.id).refreshing


async def test_start_fails_and_stop_works_while_the_society_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _society(monkeypatch, None)
    store = _store(tmp_path)
    node = _parcels(store)
    with pytest.raises(RuntimeError, match="not running"):
        await refresh.start_refresh(store, node.id, track="parcels", every_minutes=30)
    # What the person asked for is recorded, so a later start can resume it.
    recorded = store.get(node.id)
    assert (recorded.track, recorded.every_minutes, recorded.refreshing) == ("parcels", 30, False)
    assert not await refresh.refresh_live(recorded)

    # A node that was live when the society went down still says so, and stops.
    marked = store.set_upkeep(node.id, refreshing=True, task_id="task-1")
    assert await refresh.refresh_live(marked)
    stopped = await refresh.stop_refresh(store, node.id)
    assert not stopped.refreshing and stopped.task_id == ""


async def test_a_society_without_a_scheduler_or_a_lead_cannot_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    node = _parcels(store)
    monkeypatch.setattr(
        "dodaios.society.runtime.current_runtime",
        lambda: SimpleNamespace(roster=_Roster(), task_services=lambda: (None, None)),
    )
    with pytest.raises(RuntimeError, match="scheduler is unavailable"):
        await refresh.start_refresh(store, node.id, track="parcels")

    tasks = _TaskStore()
    _society(monkeypatch, tasks, lead=False)
    with pytest.raises(RuntimeError, match="agent record is missing"):
        await refresh.start_refresh(store, node.id, track="parcels")
    assert tasks.rows == [] and not store.get(node.id).refreshing


def test_the_refresh_prompt_is_read_only_and_names_the_way_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    node = store.set_upkeep(_parcels(store).id, track="Parcels from shipping mails in Gmail.")
    prompt = refresh.refresh_prompt(node)
    assert f"node id {node.id}, type sheets" in prompt
    assert "It tracks: Parcels from shipping mails in Gmail." in prompt
    assert '"changes" for a few values' in prompt and 'complete "spec"' in prompt
    assert 'a short "note" saying why' in prompt
    assert "If nothing changed, do not update." in prompt
    assert "Read only" in prompt and "one short sentence" in prompt
