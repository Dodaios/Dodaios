"""Keeping a node current: one tagged lead routine per node.

Any node can be kept current: a sheet of open orders, a dashboard of this
week's numbers, a document that follows a project. The person says what it
tracks (``track``) and how often to look (``every_minutes``); the lead then
runs a routine on that schedule: read the sources the node names, and hand the
changed content back through the ``node`` tool (operation ``update``). The
renderer draws the page again from the new spec, so a refresh changes content
and never the design.

The routine is an ordinary lead routine created through the society routines
API (``society/routines.py``), tagged :data:`TAG_PREFIX` + node id so the node
and its routine find each other. Like every unattended run it never bills a
provider API key (``routine_runner._hold_unattended_run_off_keys``).
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.nodes.model import Node
from dodaios.nodes.store import DEFAULT_EVERY_MINUTES, NodeStore
from dodaios.nodes.types import NodeError

log = logging.getLogger(__name__)

#: Tag on the refresh routine: ``node:<node id>``.
TAG_PREFIX: Final[str] = "node:"
_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "cancelled", "failed", "interrupted"})


def tag_for(node_id: str) -> str:
    return f"{TAG_PREFIX}{node_id}"


def refresh_prompt(node: Node) -> str:
    """The routine's standing instruction for one node (English, model-facing)."""
    return (
        f'Refresh the node "{node.title}" (node id {node.id}, type {node.type}). '
        f"It tracks: {node.track}\n\n"
        "Read the current state from the person's connected apps and sources. Then call the "
        f'node tool with operation "get" and node "{node.id}" to see its content, and once with '
        f'operation "update", node "{node.id}" and what changed: "changes" for a few values, '
        'or the complete "spec" when most of it is new. Keep the structure and the wording of '
        "the parts that did not change. If nothing changed, do not update. If no source could "
        'be read, call it with operation "update", the node and a short "note" saying why, '
        "and nothing else.\n"
        "Read only: do not send, change, book or delete anything outside this node. Never "
        "create a second node. Your reply is one short sentence."
    )


def _services() -> tuple[Any, Any, Any]:
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        raise RuntimeError("The agent society is not running")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise RuntimeError("The task scheduler is unavailable")
    return runtime, task_store, scheduler


async def _lead(runtime: Any) -> Any:
    from dodaios.society.roster import LEAD_AGENT_ID

    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RuntimeError("The assistant's agent record is missing")
    return lead


async def _routine_rows(task_store: Any, node_id: str) -> list[dict[str, Any]]:
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import _tags_of, is_agent_routine

    tag = tag_for(node_id)
    return [
        row
        for row in await task_store.list(limit=1000)
        if is_agent_routine(row, LEAD_AGENT_ID)
        and tag in _tags_of(row)
        and row.get("state") not in _TERMINAL
    ]


async def _delete_routines(runtime: Any, task_store: Any, scheduler: Any, node_id: str) -> int:
    from dodaios.society.routines import manage_routine

    lead = await _lead(runtime)
    removed = 0
    for row in await _routine_rows(task_store, node_id):
        await manage_routine(
            lead, {"task_id": str(row["id"]), "operation": "delete"}, task_store, scheduler
        )
        removed += 1
    return removed


async def start_refresh(
    store: NodeStore,
    node_id: str,
    *,
    track: str | None = None,
    every_minutes: Any = None,
) -> Node:
    """Schedule (or re-schedule) the node's refresh routine and mark it live.

    ``track`` and ``every_minutes`` replace what the node recorded; left out,
    the node's own are used (a resume).

    Raises ``NodeError`` for an unknown node or one that does not say what it
    tracks, ``RuntimeError`` when the society runtime or its scheduler is not
    running.
    """
    from dodaios.society.routines import build_task_spec, create_routine

    node = store.get(node_id)
    if node is None:
        raise NodeError(f"No node with id {node_id!r}.")
    wanted_track = node.track if track is None else " ".join(str(track).split())
    if not wanted_track:
        raise NodeError("'track' must say what the node keeps current and where to read it.")
    cadence = every_minutes if every_minutes is not None else node.every_minutes
    node = store.set_upkeep(
        node.id, track=wanted_track, every_minutes=cadence or DEFAULT_EVERY_MINUTES
    )
    runtime, task_store, scheduler = _services()
    await _delete_routines(runtime, task_store, scheduler, node.id)
    lead = await _lead(runtime)
    spec = build_task_spec(
        lead,
        title=f"Node: {node.title}",
        prompt=refresh_prompt(node),
        schedule={"kind": "every", "interval_seconds": node.every_minutes * 60},
    )
    spec = spec.model_copy(update={"tags": (*spec.tags, tag_for(node.id))})
    task_id = await create_routine(task_store, scheduler, spec)
    log.info("node %s: refresh every %d min (task %s)", node.id, node.every_minutes, task_id)
    return store.set_upkeep(node.id, refreshing=True, task_id=task_id)


async def stop_refresh(store: NodeStore, node_id: str) -> Node:
    """Delete the node's refresh routine; the node keeps its content.

    A node whose society runtime is down is still marked stopped: the person
    asked for it to stop, and a routine that comes back finds no live node.
    """
    node = store.get(node_id)
    if node is None:
        raise NodeError(f"No node with id {node_id!r}.")
    try:
        runtime, task_store, scheduler = _services()
        await _delete_routines(runtime, task_store, scheduler, node_id)
    except RuntimeError:
        log.warning("node %s: routine not reachable while stopping", node_id)
    return store.set_upkeep(node.id, refreshing=False, task_id="")


async def refresh_live(node: Node) -> bool:
    """Whether the node's refresh routine still exists and is not paused.

    The Automations section can delete or pause the routine behind the node's
    back; the node then reads as stopped instead of claiming a refresh.
    """
    if not node.refreshing:
        return False
    try:
        _, task_store, _ = _services()
    except RuntimeError:  # society down: the node's own record is all there is
        return node.refreshing
    rows = await _routine_rows(task_store, node.id)
    return any(row.get("state") != "paused" for row in rows)


async def node_state(node: Node, *, with_spec: bool = False) -> dict[str, Any]:
    """The node as the UI reads it, with its refresh checked against the routine."""
    data = node.to_dict(with_spec=with_spec)
    data["refreshing"] = await refresh_live(node)
    return data


__all__ = [
    "TAG_PREFIX",
    "node_state",
    "refresh_live",
    "refresh_prompt",
    "start_refresh",
    "stop_refresh",
    "tag_for",
]
