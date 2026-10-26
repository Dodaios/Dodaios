"""What waits on the person across every agent (``/api/agent-chat/attention``).

The list itself lives in :mod:`dodaios.agent_chat.attention`; these routes
read it and take the app's focus report, which the notification gate needs to
stay quiet while the person is already looking at the agent in question.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/agent-chat/attention", tags=["agent-chat"])


async def _attention(request: Request) -> Any:
    from dodaios.agent_chat.attention import attention_of, install

    from .agent_chat_routes import _async_service

    service = await _async_service(request)
    # The server installs it with the app bus when it builds the service; a
    # service built elsewhere still answers, it just cannot notify.
    return attention_of(service) or install(
        service, society=lambda: getattr(request.app.state, "society", None)
    )


@router.get("", summary="Everything an agent is waiting on the person for")
async def list_attention(request: Request) -> dict[str, Any]:
    attention = await _attention(request)
    items = await attention.items()
    return {"items": [item.to_dict() for item in items], "count": len(items)}


class FocusBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: The agent whose chat is on screen; empty when none is.
    agent_id: str = Field(default="", max_length=200)
    session_id: str = Field(default="", max_length=400)
    #: Whether the app window has the keyboard focus.
    app_focused: bool = False
    #: Agents the person muted (no notifications, still counted).
    muted: list[str] = Field(default_factory=list, max_length=500)


@router.post("/focus", summary="Tell the notifier what the person is looking at")
async def report_focus(body: FocusBody, request: Request) -> dict[str, Any]:
    attention = await _attention(request)
    attention.gate.report_focus(
        agent_id=body.agent_id,
        session_id=body.session_id,
        app_focused=body.app_focused,
        muted=body.muted,
    )
    return {"ok": True}
