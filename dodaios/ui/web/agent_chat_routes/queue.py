"""The send queue and side threads."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)

from dodaios.agent_chat import send_queue
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    QueuedEditBody,
)

router = APIRouter()


@router.get("/sessions/{session_id}/queue")
async def get_queue(session_id: str, request: Request) -> dict[str, Any]:
    """Messages waiting for this chat's next turn (server side, survives a reload)."""
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return send_queue.queue_state(svc, session_id)


@router.post("/sessions/{session_id}/queue/resume")
async def resume_queue(session_id: str, request: Request) -> dict[str, Any]:
    """Let waiting messages start again after Stop paused them."""
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    send_queue.resume(svc, session_id)
    return send_queue.queue_state(svc, session_id)


@router.delete("/sessions/{session_id}/queue/{queue_id}")
async def discard_queued(session_id: str, queue_id: str, request: Request) -> dict[str, Any]:
    """Take one waiting message back before it starts."""
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"removed": await send_queue.discard(svc, session_id, queue_id)}


@router.patch("/sessions/{session_id}/queue/{queue_id}")
async def edit_queued(
    session_id: str, queue_id: str, body: QueuedEditBody, request: Request
) -> dict[str, Any]:
    """Change the words of one waiting message before it starts."""
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"edited": await send_queue.edit_waiting(svc, session_id, queue_id, body.text)}


@router.post(
    "/sessions/{session_id}/queue/{queue_id}/send-now",
    summary="Send one waiting message now instead of after the running turn",
    # An agent that cannot take a message mid-turn has that turn stopped so
    # the message starts at once: work in flight is lost, like Stop.
    openapi_extra={"x-jarvis-dangerous": True},
)
async def send_queued_now(session_id: str, queue_id: str, request: Request) -> dict[str, Any]:
    """Steer the message into the running turn, or stop the turn and start it next."""
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    outcome = await send_queue.send_waiting_now(svc, session_id, queue_id)
    return {"steered": outcome == "steered", "next": outcome == "next"}


@router.post(
    "/sessions/{session_id}/side-threads/{side_id}/stop",
    summary="Stop one side thread of this conversation; everything else goes on",
)
async def stop_side_thread(session_id: str, side_id: str, request: Request) -> dict[str, Any]:
    """Stop the answer to a message that was sent while another request was running."""
    from dodaios.agent_chat import side_threads

    svc = await _r._async_service(request)
    if side_threads.parent_of(svc, side_id) != session_id:
        raise HTTPException(status_code=404, detail="side thread not found")
    return {"stopped": await side_threads.stop(svc, session_id, side_id)}


@router.post(
    "/sessions/{session_id}/side-threads/{side_id}/to-main",
    summary="Move a side thread's message into the main thread, behind the running request",
)
async def side_thread_to_main(session_id: str, side_id: str, request: Request) -> dict[str, Any]:
    """The message belongs to the running request, not to a task of its own.

    Its side thread stops without an answer. The message starts as the next
    turn of the main thread, with the running request's context (``queued``,
    or ``sent`` when the main thread is free by now).
    """
    from dodaios.agent_chat import side_threads

    svc = await _r._async_service(request)
    if side_threads.parent_of(svc, side_id) != session_id:
        raise HTTPException(status_code=404, detail="side thread not found")
    try:
        outcome = await side_threads.move_to_main(svc, session_id, side_id)
    except send_queue.QueueFull as exc:
        raise HTTPException(status_code=409, detail="too many messages are waiting") from exc
    if not outcome:
        raise HTTPException(status_code=409, detail="the side thread has already ended")
    return {"outcome": outcome}
