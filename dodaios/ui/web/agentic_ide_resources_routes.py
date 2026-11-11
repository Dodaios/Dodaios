"""REST routes for the Agentic IDE's resource view.

Endpoints (under ``/api/agentic-ide/resources``)::

    GET  /       The machine right now: processor, memory and graphics load,
                 split into agents (with their tools and linked apps), this
                 app and everything else, plus the last minutes as series
    POST /end    End tools an agent started (handles from the last GET only)

The GET measures on request and nothing runs between requests, so a closed
panel costs nothing. Both handlers are plain ``def``: the read takes tens of
milliseconds and belongs in the threadpool, never on the event loop.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from dodaios.agentic_ide.resource_sampler import ResourceSampler, SampleContext
from dodaios.agentic_ide.resource_usage import AgentSignature, KnownRoot
from dodaios.ui.web.surface_security import is_loopback_request

router = APIRouter(prefix="/api/agentic-ide/resources", tags=["agentic-ide-resources"])

#: Command names too common to recognise a coding CLI by. A pane of such a CLI
#: is still named, because the app knows which process it started for it.
_GENERIC_BINARIES = frozenset({"agent", "ai", "code", "run"})

_sampler: ResourceSampler | None = None
_sampler_lock = threading.Lock()


def get_sampler() -> ResourceSampler:
    """The process-wide sampler, created on first use."""
    global _sampler
    with _sampler_lock:
        if _sampler is None:
            from dodaios.hardware.gpu_usage import GpuReader

            _sampler = ResourceSampler(gpu=GpuReader())
        return _sampler


def reset_for_tests(sampler: ResourceSampler | None = None) -> None:
    global _sampler
    with _sampler_lock:
        _sampler = sampler


def signatures() -> list[AgentSignature]:
    """How each coding CLI of the catalog shows up in a process list."""
    from dodaios.workspace.agents import coding_agents

    found: list[AgentSignature] = []
    taken: set[str] = set()
    for agent in coding_agents():
        first = (agent.launch_command or "").split()[:1]
        names = [agent.binary, *agent.binary_aliases, *first]
        binaries = tuple(
            dict.fromkeys(
                name.lower()
                for name in names
                if name and len(name) >= 3 and name.lower() not in _GENERIC_BINARIES | taken
            )
        )
        if binaries:
            taken.update(binaries)
            found.append(AgentSignature(agent.name, agent.display_name, binaries))
    return found


def _agent_label(agent: str) -> str:
    from dodaios.workspace.agents import get_agent

    entry = get_agent(agent)
    return entry.display_name if entry is not None else agent


def _pane_roots() -> tuple[list[KnownRoot], int]:
    from dodaios.agentic_ide.session import get_registry

    registry = get_registry()
    roots = [
        KnownRoot(
            pid=row["pid"],
            id=f"pane:{row['history_id']}",
            kind="pane",
            agent=row["agent"],
            agent_label=row["display_name"],
            label=row["name"],
            detail=row["title"],
            workspace=row["workspace_name"],
        )
        for row in registry.pane_processes()
    ]
    return roots, int(registry.runtime_status().get("host_pid") or 0)


def _thread_roots(app_state: Any) -> tuple[list[KnownRoot], int]:
    from dodaios.agent_chat import turn_host_client

    host_pid, processes = turn_host_client.live_processes()
    service = getattr(app_state, "agent_chat", None) if app_state is not None else None
    roots: list[KnownRoot] = []
    seen: set[str] = set()
    for pid, meta in processes:
        session_id = str(meta.get("session_id") or "")
        runner = str(meta.get("runner") or "")
        title = ""
        if service is not None and session_id:
            row = service.store.get_session(session_id)
            title = row.title if row is not None else ""
        root_id = f"thread:{session_id or pid}"
        if root_id in seen:
            root_id = f"{root_id}:{pid}"
        seen.add(root_id)
        cwd = str(meta.get("cwd") or "")
        roots.append(
            KnownRoot(
                pid=pid,
                id=root_id,
                kind="thread",
                agent=runner,
                agent_label=_agent_label(runner) if runner else "",
                label=title,
                workspace=Path(cwd).name if cwd else "",
            )
        )
    return roots, host_pid


def build_context(app_state: Any = None) -> SampleContext:
    """What the app knows about its own panes and threads, for one sample.

    Each source is asked on its own: a registry that cannot answer leaves its
    agents to be recognised by name, it does not empty the view.
    """
    roots: list[KnownRoot] = []
    hosts: list[int] = []
    for source in (_pane_roots, lambda: _thread_roots(app_state)):
        try:
            found, host_pid = source()
        except Exception as exc:  # noqa: BLE001 - the view must still draw
            logger.warning("Resource view: a source of agents is unreadable: {}", exc)
            continue
        roots.extend(found)
        if host_pid:
            hosts.append(host_pid)
    try:
        known = signatures()
    except Exception as exc:  # noqa: BLE001 - same reason
        logger.warning("Resource view: the agent catalog is unreadable: {}", exc)
        known = []
    return SampleContext(known_roots=roots, signatures=known, host_pids=hosts)


@router.get("", summary="Processor, memory and graphics load by agent")
def resources(request: Request) -> dict[str, Any]:
    app = getattr(request, "app", None)
    return get_sampler().sample(build_context(getattr(app, "state", None)))


class EndRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=64)


@router.post("/end", summary="End tools an agent started")
def end(body: EndRequest, request: Request) -> dict[str, int]:
    if not is_loopback_request(request.scope):
        raise HTTPException(status_code=403, detail="Only available on this computer.")
    return {"ended": get_sampler().end_tools(body.ids)}
