"""Model preload, session warm-up and turn cancel."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)

from dodaios.agent_chat import send_queue
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    PreloadBody,
)

router = APIRouter()


def _preload_local_model(session: Any) -> bool:
    """Start loading this chat's local model (Ollama) in the background."""
    return _r._preload_provider_model(
        str(getattr(session, "provider", "") or ""), str(getattr(session, "model", "") or "")
    )


def _preload_provider_model(provider: str, model: str) -> bool:
    """Start loading a local model in the background; ``True`` when one loads.

    A local model that is not in memory costs a load of seconds on the first
    message; started while the person types or dictates, the load is done
    by the time they send. Only a brain with a ``preload`` method does
    anything (a capability, not a provider name); every other one is a no-op.
    """
    from dodaios.agent_chat.runner_brain import _default_model, brain_manager

    manager = brain_manager()
    getter = getattr(manager, "_get_brain", None)
    if manager is None or not provider or not callable(getter):
        return False
    key = f"local-preload:{provider}"
    if key in _r._WARMING:
        return True
    model = model.strip() or _default_model(manager, provider)
    try:
        brain = getter(provider, model)
    except Exception:  # noqa: BLE001 — an unknown provider has nothing to load
        return False
    preload = getattr(brain, "preload", None)
    if not callable(preload):
        return False
    task = asyncio.create_task(preload(), name=f"local-model-preload-{provider}")
    _r._WARMING[key] = task
    task.add_done_callback(lambda _done: _r._WARMING.pop(key, None))
    return True


@router.post(
    "/preload",
    summary="Load a local model before the next message is sent",
    description=(
        "Loads the picked local model (Ollama) into memory in the background while "
        "the person types or dictates, so the first answer does not wait for the "
        "load. Sends no prompt. A no-op for hosted providers and coding agents."
    ),
)
async def preload_model(body: PreloadBody) -> dict[str, Any]:
    return {"loading": _r._preload_provider_model(body.provider, body.model)}


@router.post(
    "/sessions/{session_id}/warm",
    summary="Get a Hermes or OpenClaw agent ready before the next message",
    description=(
        "Starts the agent's runtime process and opens its conversation in the "
        "background, so the message that follows answers without a start-up wait. "
        "Makes no model call. A no-op for every other chat."
    ),
)
async def warm_session(session_id: str, request: Request) -> dict[str, Any]:
    svc = await _r._async_service(request)
    session = await _r._session_or_bound_agent_chat(svc, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.surface != "society" or not session.runtime:
        return {"warming": _r._preload_local_model(session), "session_id": session_id}
    running = _r._WARMING.get(session_id)
    if running is None and not svc.is_running(session_id):
        from dodaios.agent_chat.runner_acp import warm_session as warm

        task = asyncio.create_task(
            warm(session, svc.store), name=f"agent-runtime-warm-{session_id}"
        )
        _r._WARMING[session_id] = task

        def done(finished: asyncio.Task[bool]) -> None:
            _r._WARMING.pop(session_id, None)
            if not finished.cancelled() and finished.exception() is not None:
                _r.log.warning(
                    "agent chat %s: runtime warm-up failed: %s", session_id, finished.exception()
                )

        task.add_done_callback(done)
        running = task
    return {"warming": running is not None, "session_id": session_id}


@router.post(
    "/sessions/{session_id}/cancel",
    summary="Stop the turn this chat session is running",
    # Cancelling throws away work in flight: the runner is interrupted mid-turn
    # and whatever it had not yet written is lost. The CLI safety gate and the
    # Command Registry must treat it as destructive and ask before firing.
    openapi_extra={"x-jarvis-dangerous": True},
)
async def cancel_turn(session_id: str, request: Request) -> dict[str, Any]:
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    session = svc.store.get_session(session_id)
    cancelled = svc.is_running(session_id)
    sides = 0
    if session.surface == "jarvis":
        from dodaios.agent_chat import side_threads

        # One Stop for the conversation: the answers being written beside the
        # main thread stop with it (the chat shows no control of their own).
        sides = await side_threads.stop_all(svc, session_id)
    if not cancelled and not sides and svc.parked_work.stop(session_id):
        # Nothing is answering, so the stop means the requests still waiting
        # for their agents: their results no longer continue here. The agents'
        # own work is not touched. During a turn, stop ends that turn only.
        cancelled = True
    # Who ended a turn is otherwise invisible: name the control that asked.
    headers = request.headers
    _r.log.info(
        "agent chat %s: stop requested over HTTP (via=%s, running=%s, fetch-site=%s)",
        session_id,
        (headers.get("x-jarvis-stop-via") or "unnamed")[:40],
        cancelled,
        (headers.get("sec-fetch-site") or "none")[:20],
    )
    if session.surface in ("jarvis", "society"):
        await svc.controls.pause(session_id, "Stopped by the user")
    else:
        # Stop halts the agent: messages waiting behind it do not start by themselves.
        send_queue.pause(svc, session_id)
        cancelled = await svc.cancel(session_id)
    # The runner can already be gone while the transcript still shows Working.
    # Closing that turn is what makes the stop button leave the chat.
    if not svc.is_running(session_id):
        cancelled = await svc.seal_stopped_turn(session_id) or cancelled
    return {"cancelled": cancelled or bool(sides), "session_id": session_id}
