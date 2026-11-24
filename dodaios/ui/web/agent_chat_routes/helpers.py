"""Shared helpers of the agent-chat routes: service access, validation, turn reattach."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import (
    HTTPException,
    Request,
    WebSocket,
)

from dodaios.agent_chat.service import (
    AgentChatService,
)
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.ui.web import agent_chat_routes as _r


def schedule_turn_reattach(state: Any) -> asyncio.Task[None] | None:
    """Carry on the thread turns the turn host kept running, right after boot.

    Called by the two real app entry points beside the Agentic IDE's
    ``schedule_boot_restore``. Without it a reattached turn waited for the
    first window to open a chat: its output piled up in the host and an
    approval its CLI asked for stayed unanswered meanwhile. Building the
    service is what reattaches (``AgentChatService._seal_orphaned_turns``),
    so this builds it only when the host or its spool holds something.
    """
    from dodaios.agent_chat import turn_host_client

    if not turn_host_client.host_available():
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _r.log.debug("agent chat: boot reattach not scheduled — no running loop")
        return None
    # The service is built below in a plain worker thread, where it cannot
    # find the app's loop by asking. Without it every turn the host still ran
    # was closed as "The app restarted" — always in the background service,
    # which has no window whose requests record the loop first (2026-11-09).
    from dodaios.agent_chat.service import remember_app_loop

    remember_app_loop(loop)

    async def _run() -> None:
        await asyncio.sleep(_r._REATTACH_DELAY_S)
        if not await asyncio.to_thread(turn_host_client.may_hold_turns):
            return
        if (await asyncio.to_thread(_r._service_from_state, state)) is None:
            _r.log.warning("agent chat: thread turns wait — the chat service could not be built")

    return loop.create_task(_run(), name="agent-chat-boot-reattach")


def _service(request: Request) -> AgentChatService:
    svc = _r._service_from_state(request.app.state)
    if svc is None:
        raise HTTPException(status_code=503, detail="agent-chat-unavailable")
    return svc


async def _async_service(request: Request) -> AgentChatService:
    """Wait for lazy construction without holding the serving event loop."""
    service = getattr(request.app.state, "agent_chat", None)
    if service is not None:
        return service
    # The build runs in a plain worker thread, which cannot find this loop by
    # asking. Unrecorded, the first request of a window that was open across
    # an app restart closed every thread turn the turn host still ran as
    # "The app restarted" (2026-11-12).
    from dodaios.agent_chat.service import remember_app_loop

    remember_app_loop(asyncio.get_running_loop())
    # Sync routes can already own the construction lock. Waiting on that lock
    # here freezes HTTP, voice, and callbacks needed by the builder itself.
    return await asyncio.to_thread(_r._service, request)


def _ws_service(ws: WebSocket) -> AgentChatService | None:
    app = ws.scope.get("app")
    return _r._service_from_state(app.state) if app is not None else None


def _cli_installed(runner: str) -> bool:
    from dodaios.agent_chat.runner_cli import cli_installed

    return cli_installed(runner)


async def _live_cli_models() -> dict[str, list[dict[str, Any]]]:
    """The model lists the installed CLIs publish, keyed by runner.

    One reader, shared with the workspace panes that offer the same CLIs
    (:func:`dodaios.workspace.launch_picks.live_models`) — two readers would be
    two answers to one question, and they would drift the first time an
    account gained a model.
    """
    from dodaios.workspace.launch_picks import live_models

    return await live_models()


def _folder_for(surface: str, raw: str | None) -> str | None:
    """The folder a ``surface`` session may be given; ``None`` = its default.

    A plain chat touches no folder, so whatever a client still remembers (a
    workspace that has since been deleted, say) is ignored rather than allowed
    to refuse the chat.
    """
    return None if kit_for(surface).plain else _r._validate_cwd(raw)


def _validate_computer(raw: str | None, surface: str) -> str:
    """A thread's placement: "" (this computer) or a configured computer's id."""
    value = (raw or "").strip()
    if not value:
        return ""
    if surface != "agent":
        raise HTTPException(400, "Only coding threads can run on another computer")
    from dodaios.computers.service import get_service

    try:
        get_service().get(value)
    except Exception as exc:
        raise HTTPException(400, "Unknown computer") from exc
    return value


def _validate_cwd(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    p = Path(os.path.expanduser(text))
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {text}")
    return str(p.resolve())


async def _session_or_bound_agent_chat(svc: Any, session_id: str) -> Any | None:
    """The chat session, binding an agent's own chat that does not exist yet.

    An agent's chat (``society:<agent_id>``) is created by binding it to its
    roster row (``POST /api/society/agents/{id}/chat``). A panel that opens a
    brand-new agent asks for its catalog and warm-up in the same moment, so
    those requests bind it themselves instead of answering 404. Binding is
    idempotent and runs nothing. Any other id is only looked up.
    """
    session = svc.store.get_session(session_id)
    if session is not None or not session_id.startswith("society:"):
        return session
    agent_id = session_id.removeprefix("society:")
    if not agent_id or ":" in agent_id:
        return None
    try:
        from dodaios.society.chat_binding import ensure_session
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        if runtime is None:
            return None
        agent = await runtime.roster.get(agent_id)
        if agent is None or agent.session_id != session_id or str(agent.state) != "active":
            return None
        if await runtime.store.kill_switch():
            return None
        return ensure_session(svc, runtime.config(), agent)
    except PermissionError as exc:
        _r.log.debug("agent chat: %s not bound on demand: %s", session_id, exc)
        return None
    except Exception:  # noqa: BLE001 - an unbound chat stays "not found", never a 500
        _r.log.warning("agent chat: could not bind %s on demand", session_id, exc_info=True)
        return None
