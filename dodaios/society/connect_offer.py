"""A plugin tool that fails for want of a connection puts the Connect card into the chat.

The card (``connect_tool.py``) used to appear only when the chat's model called
``society_request_connect``. A model that calls ``gmail`` first reads "Gmail is
not connected — connect it in the Plugins view", opens the Plugins page and
writes the steps into its reply; on a CLI seat the tool that would have shown
the card is loaded on demand, so its description never reached the model.

Here the chat does not depend on that choice. Every tool call of a chat passes
the ``ToolExecutor``; a failed call of a marketplace plugin's tool whose error
names the missing connection, and whose connection really is missing, opens
the card in that chat and tells the model what the person now sees. A spoken
call, a routine and every other caller get the tool's own error unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any, Final

from dodaios.agent_chat.credential_requests import (
    PLUGIN,
    CredentialSpec,
    TooManyCredentialRequests,
)
from dodaios.core.protocols import ToolResult

log = logging.getLogger(__name__)

__all__ = ["CARD_STATUS", "names_missing_connection", "offer_connect"]

#: ``output["status"]`` of a failed call whose Connect card is on screen.
CARD_STATUS: Final[str] = "connect_card"

_CHAT_REF: Final[str] = "agent-chat:"
#: How the plugin tools word it: "… is not connected — connect it in the Plugins
#: view." and "… please reconnect … in the Plugins view." (plugins/tool/*_rest.py).
_MISSING: Final[re.Pattern[str]] = re.compile(r"\bnot connected\b|\breconnect\b", re.IGNORECASE)


def names_missing_connection(error: str | None) -> bool:
    """Whether a tool's error says its service has to be connected (again)."""
    return bool(error) and _MISSING.search(str(error)) is not None


def _chat_session(config: Mapping[str, Any]) -> str:
    """The attended chat a call belongs to, or "" when nobody could press Connect."""
    ref = str(config.get("approval_ref") or "")
    if not ref.startswith(_CHAT_REF) or config.get("approval_surface") == "unattended":
        return ""
    from .routine_runner import is_routine_session

    session_id = ref.removeprefix(_CHAT_REF)
    return "" if not session_id or is_routine_session(session_id) else session_id


def _asker(runtime: Any, service: Any, session_id: str) -> str:
    """Whose card it is: a society chat's agent, or the assistant in its own chat.

    A coding thread has no name of its own here; its card says "your agent".
    """
    from .surface import agent_id_of

    agent_id = agent_id_of(session_id)
    if agent_id is not None:
        cached = getattr(runtime, "cached_agent", None)
        agent = cached(agent_id) if callable(cached) else None
        return str(getattr(agent, "name", "") or "")
    try:
        session = service.store.get_session(session_id)
        if getattr(session, "surface", "") == "jarvis":
            return str(service._assistant_name() or "")  # noqa: SLF001 — the chat's own name
    except Exception:  # noqa: BLE001 — a card without a name still connects
        log.debug("society connect: no name for the card in %s", session_id, exc_info=True)
    return ""


async def offer_connect(
    tool_name: str, result: ToolResult, config: Mapping[str, Any] | None
) -> ToolResult:
    """``result``, or the same failure with the Connect card now shown in the chat."""
    if result.success or not names_missing_connection(result.error):
        return result
    session_id = _chat_session(config or {})
    if not session_id:
        return result
    from .connect_tool import connect_save, resolve_target
    from .runtime import current_runtime

    runtime = current_runtime()
    if runtime is None:
        return result
    target = await asyncio.to_thread(resolve_target, PLUGIN, tool_name)
    # Unknown state (None) is not a reason to ask for a sign-in.
    if target is None or target.connected is not False:
        return result
    service = runtime.chat_service()
    if service is None or not callable(getattr(service, "open_credential_request", None)):
        return result
    spec = CredentialSpec.build(target.id, target.label, kind=PLUGIN)
    try:
        request_id = await service.open_credential_request(
            session_id,
            spec,
            connect_save(PLUGIN, target.id),
            asker=_asker(runtime, service, session_id),
            # Asked again in a later turn, the card stands under that turn's message.
            renew=True,
        )
    except (TooManyCredentialRequests, RuntimeError) as exc:
        # The turn used its cards, or it is over: the tool's own error stands.
        log.info("society connect: no card for %s in %s (%s)", target.id, session_id, exc)
        return result
    label = target.label
    return ToolResult(
        success=False,
        output={
            "status": CARD_STATUS,
            "kind": PLUGIN,
            "id": target.id,
            "request_id": request_id,
        },
        error=(
            f"{label} is not connected. A Connect card for {label} is now shown to the "
            "person in this chat; its button starts the sign-in. Tell them in one short "
            f"sentence that you need {label} for this and that they can press Connect on "
            "the card. Do not open or name the Plugins page, do not describe sign-in "
            f"steps and do not look for another way to reach {label}. End your reply "
            "there: once they have connected it, this chat continues the request by "
            f"itself. (request_id {request_id})"
        ),
    )
