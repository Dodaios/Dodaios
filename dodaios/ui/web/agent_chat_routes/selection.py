"""The Dodaios chat model selection, voice chat and slash commands."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)

from dodaios.agent_chat.catalog import offers
from dodaios.agent_chat.control_types import CommandRequest, CommandResult
from dodaios.agent_chat.effort import normalize_effort
from dodaios.agent_chat.service import (
    AgentChatService,
    NoSuchSession,
)
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    ChatSelectionBody,
    VoiceChatBody,
    VoiceChatResponse,
)

router = APIRouter()


@router.put("/selection", summary="Remember the model for new Dodaios chats and agents")
def save_chat_selection(body: ChatSelectionBody, request: Request) -> dict[str, str]:
    from dodaios.agent_chat.store import ChatSelection

    provider = body.provider.strip().lower()
    if not offers("jarvis", provider):
        raise HTTPException(400, "This provider is not offered on the Dodaios chat")
    if body.account_id:
        from dodaios import agent_accounts
        from dodaios.agent_chat.catalog import provider_row

        account = agent_accounts.resolve(body.account_id)
        row = provider_row(provider)
        if account is None or row is None or account.platform != row.agent:
            raise HTTPException(400, "This subscription account does not belong to the provider")
    selection = ChatSelection(
        provider, body.model.strip(), normalize_effort(provider, body.effort), body.account_id
    )
    _r._service(request).store.save_chat_selection(selection)
    return selection.to_dict()


def _reported_running(svc: Any, session_id: str) -> bool:
    """The ``running`` flag the UI shows: idle from the turn's own end on.

    Services without ``reports_running`` (other surfaces, test doubles) fall
    back to ``is_running``.
    """
    reports = getattr(svc, "reports_running", None)
    return bool(reports(session_id) if reports else svc.is_running(session_id))


def _voice_chat_answer(svc: AgentChatService) -> VoiceChatResponse:
    return VoiceChatResponse(
        session_id=svc.voice_chat_id,
        fresh=svc.voice_chat_fresh,
        voice_session_id=svc.voice_session_continued,
    )


def _archived_voice_history(request: Request, voice_session_id: str) -> Any:
    """Reader for an archived voice chat's turns, or ``None`` when it does not exist."""
    from dodaios.ui.web.chats_routes import _normalized_messages, _seed_pairs

    session_store = getattr(request.app.state, "session_store", None)
    chat_store = getattr(request.app.state, "chat_store", None)
    if session_store is None or session_store.get_session(voice_session_id) is None:
        return None

    def history() -> list[Any]:
        messages = _normalized_messages("voice", voice_session_id, chat_store, session_store)
        return _seed_pairs(messages or [])

    return history


@router.get("/voice-chat", summary="The Dodaios chat voice calls continue")
def get_voice_chat(request: Request) -> VoiceChatResponse:
    return _r._voice_chat_answer(_r._service(request))


@router.put("/voice-chat", summary="Continue voice calls in this Dodaios chat")
def put_voice_chat(body: VoiceChatBody, request: Request) -> VoiceChatResponse:
    """Bind the chat the front page shows: calls file into it and start with its history."""
    svc = _r._service(request)
    voice_session = None if body.session_id else (body.voice_session_id or "").strip() or None
    history = None
    if voice_session is not None:
        history = _r._archived_voice_history(request, voice_session)
        if history is None:
            raise HTTPException(status_code=404, detail="no-such-voice-chat")
    try:
        svc.bind_voice_chat(
            body.session_id or None, voice_session=voice_session, voice_history=history
        )
    except NoSuchSession as exc:
        raise HTTPException(status_code=404, detail="no-such-jarvis-chat") from exc
    return _r._voice_chat_answer(svc)


@router.get("/commands", summary="List chat slash commands and their availability")
def list_chat_commands(request: Request, session_id: str | None = None) -> dict[str, Any]:
    try:
        return _r._service(request).controls.catalog(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/sessions/{session_id}/control", summary="Read this chat's mode and goal state")
def get_chat_control(session_id: str, request: Request) -> dict[str, Any]:
    try:
        return _r._service(request).controls.state(session_id).model_dump()
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post(
    "/sessions/{session_id}/commands",
    response_model=CommandResult,
    summary="Run one explicit chat command",
    openapi_extra={"x-jarvis-dangerous": True},
)
async def run_chat_command(
    session_id: str, body: CommandRequest, request: Request
) -> CommandResult:
    try:
        return await (await _r._async_service(request)).controls.execute(session_id, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
