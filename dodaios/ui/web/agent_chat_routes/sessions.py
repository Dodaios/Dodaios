"""Session list, search and creation."""

from __future__ import annotations

import time
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)

from dodaios.agent_chat.permissions import (
    is_permission_mode,
    ladder_key,
    normalize_permission,
    permission_modes,
)
from dodaios.agentic_ide import thread_finder
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    CreateSessionBody,
    SurfaceName,
)

router = APIRouter()


# ------------------------------------------------------------------ sessions


@router.get("/sessions")
def list_sessions(
    request: Request,
    limit: int = Query(200, ge=1, le=1000),
    surface: SurfaceName | None = None,
) -> dict[str, Any]:
    svc = _r._service(request)
    out = []
    teams = _r._team_sessions(request) if surface in (None, "agent") else {}
    for s in svc.store.list_sessions(limit=limit, surface=surface):
        if surface is None and s.surface in _r.HIDDEN_SURFACES:
            continue
        d = s.to_dict()
        d["running"] = _r._reported_running(svc, s.session_id)
        if s.surface == "agent":
            d["pending_approvals"] = svc.pending_approvals(s.session_id)
            # An open question card: the sidebar marks the thread as waiting for the person.
            d["pending_questions"] = svc.pending_questions(s.session_id)
            d["cli_title"] = _r._cli_title(svc, s)
            # What the person gives Dodaios to name this thread (``thread_finder``).
            d["code"] = thread_finder.thread_code(s.session_id)
            # A member of a team thread is listed under its team, not as a thread.
            d["team_id"] = teams.get(s.session_id, "")
        out.append(d)
    _r._title_chats(request, svc, out)
    return {"sessions": out}


@router.get(
    "/sessions/search",
    summary="Find chats whose title or messages contain a text",
    openapi_extra={"x-jarvis-readonly": True},
)
def search_sessions(
    request: Request,
    q: str = Query("", max_length=200),
    surface: SurfaceName = "agent",
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """The thread search: the matching chats, newest first, each with the
    latest matching message as a snippet."""
    if surface in _r.HIDDEN_SURFACES:
        return {"hits": []}
    return {"hits": _r._service(request).store.search_sessions(q, surface=surface, limit=limit)}


def _team_sessions(request: Request) -> dict[str, str]:
    """Which sessions belong to a team thread (``session_id -> team_id``)."""
    from dodaios.ui.web.team_thread_routes import team_sessions

    try:
        return team_sessions(request.app.state)
    except Exception:  # noqa: BLE001 - the thread list must not fail with the team store
        _r.log.warning("team threads unavailable; listing their members as threads", exc_info=True)
        return {}


def _cli_title(svc: Any, session: Any) -> str:
    """The name the coding CLI gave a thread's conversation itself, or ""."""
    return thread_finder.cli_title_of(svc.store, session)


def _title_chats(request: Request, svc: Any, rows: list[dict[str, Any]]) -> None:
    """Give the Jarvis chats and the IDE's threads a topic title, not their first words.

    The ``jarvis`` surface — the front page's own history — and the ``agent``
    surface — the IDE's threads — are retitled. A thread whose coding CLI named
    the conversation itself keeps that name (``cli_title``); Claude Code in
    print mode never writes one, so most threads are named here — right after
    their first message, the way the CLI names a terminal pane. A title the
    user typed is recognised by the titler and kept.
    """
    from dodaios.agent_chat.events import shown_text
    from dodaios.agent_chat.store import _title_from
    from dodaios.sessions import chat_titles

    now = int(time.time() * 1000)
    requests: list[chat_titles.TitleRequest] = []
    for row in rows:
        surface = row.get("surface")
        if not (surface == "jarvis" or (surface == "agent" and not row.get("cli_title"))):
            continue
        sid = str(row["session_id"])
        seed = str(row.get("title") or "")
        # What the person sent -> the title a build before 2026-11-12 stored for
        # it, which it took from the composed prompt. Filled by ``load``.
        from_prompt: dict[str, str] = {}

        def load(
            sid: str = sid, from_prompt: dict[str, str] = from_prompt
        ) -> list[tuple[str, str]]:
            texts: list[tuple[str, str]] = []
            for event in svc.store.list_events(sid):
                payload = event.get("payload") or {}
                text = str(payload.get("text") or "")
                if event["kind"] == "user_message":
                    # The person's own words, as the store titles the chat: the
                    # prompt of a message with files also holds the note and the
                    # file blocks written for the model.
                    said = shown_text(payload)
                    from_prompt.setdefault(said, _title_from(text))
                    texts.append(("user", said))
                elif event["kind"] == "agent_message":
                    texts.append(("agent", text))
                elif event["kind"] == "assistant_text":
                    texts.append(("assistant", text))
            return texts

        def auto_title(
            text: str, seed: str = seed, from_prompt: dict[str, str] = from_prompt
        ) -> str:
            """The title this first message gave the chat; any other title was typed."""
            return seed if seed and from_prompt.get(text) == seed else _title_from(text)

        updated = int(row.get("updated_ms") or 0)
        requests.append(
            chat_titles.TitleRequest(
                kind=chat_titles.KIND_TYPED,
                conv_id=sid,
                version=str(int(row.get("message_count") or 0)),
                message_count=int(row.get("message_count") or 0),
                updated_ms=updated,
                settled=not row.get("running")
                and now - updated >= chat_titles.TYPED_SETTLE_S * 1000,
                seed=seed,
                loader=load,
                auto_title=auto_title,
                # A thread is named a moment after its first message, as its CLI
                # names a terminal pane — not only once the agent has gone quiet.
                name_early=surface == "agent",
            )
        )
    if not requests:
        return
    try:
        titles = chat_titles.titler_for_state(request.app.state).titles_for(requests)
    except Exception:  # noqa: BLE001 - the stored title is a fine answer; logged
        _r.log.warning("Dodaios chat titles unavailable, keeping the stored ones", exc_info=True)
        return
    for row in rows:
        key = (chat_titles.KIND_TYPED, str(row["session_id"]))
        # A Jarvis chat with no topic shows as what it is ("Voice chat · 09:42");
        # a thread keeps its first message rather than an empty row.
        if key in titles and (titles[key] or row.get("surface") == "jarvis"):
            row["title"] = titles[key]


@router.post(
    "/sessions",
    status_code=201,
    summary="Create a chat session",
    # Still an app action, but the search says what a model should use for a
    # coding agent: the raw route knows neither the task nor who asked, and
    # took four failed calls to fill by hand (live 2026-11-12).
    openapi_extra={
        "x-jarvis-instead": (
            "For a new coding agent (a thread in the Agentic IDE, surface agent) call the "
            "workspace-orchestrate tool with action create instead: it takes cli, model, "
            "effort and folder as the person said them, hands over the task and returns "
            "the result to this conversation."
        )
    },
)
def create_session(body: CreateSessionBody, request: Request) -> dict[str, Any]:
    svc = _r._service(request)
    if body.account_id:
        from dodaios import agent_accounts
        from dodaios.agent_chat.catalog import provider_row

        account = agent_accounts.resolve(body.account_id)
        row = provider_row(body.provider)
        if account is None or row is None or account.platform != row.agent:
            raise HTTPException(400, "This subscription account does not belong to the provider")
    ladder = ladder_key(body.surface, _r.resolve_runner(body.provider, surface=body.surface))
    if body.permission_mode and not is_permission_mode(ladder, body.permission_mode):
        raise HTTPException(
            status_code=400,
            detail=(
                "permission_mode must be one of "
                + ", ".join(m.id for m in permission_modes(ladder))
            ),
        )
    if body.surface == "jarvis":
        # Dodaios keeps ONE endless conversation: "new chat" returns it with
        # the picked model on its seat instead of opening a second chat.
        from dodaios.agent_chat.lead import SeatBusy, adopt_seat

        try:
            lead = adopt_seat(
                svc,
                {
                    "provider": body.provider,
                    "model": body.model or None,
                    "effort": body.effort,
                    "account_id": body.account_id,
                },
            )
        except SeatBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if lead is not None:
            from dodaios.agent_chat.store import ChatSelection

            svc.store.save_chat_selection(
                ChatSelection(lead.provider, lead.model, lead.effort, lead.account_id)
            )
            d = lead.to_dict()
            d["running"] = svc.is_running(lead.session_id)
            d["lead"] = True
            return d
    cwd = _r._folder_for(body.surface, body.cwd)
    computer_id = _r._validate_computer(body.computer_id, body.surface)
    try:
        from dodaios.agent_chat.thread_sessions import clean_vendor_session

        vendor = clean_vendor_session(
            _r.resolve_runner(body.provider, surface=body.surface, account_id=body.account_id),
            body.vendor_session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        session = svc.create_session(
            computer_id=computer_id,
            provider=body.provider,
            model=body.model,
            effort=body.effort,
            speed=body.speed,
            cwd=cwd,
            permission_mode=normalize_permission(ladder, body.permission_mode),
            build_mode=body.build_mode,
            title=body.title,
            surface=body.surface,
            account_id=body.account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if vendor:
        session = svc.store.update_session(session.session_id, vendor_session=vendor) or session
    if session.surface == "jarvis":
        from dodaios.agent_chat.store import ChatSelection

        svc.store.save_chat_selection(
            ChatSelection(session.provider, session.model, session.effort, session.account_id)
        )
    d = session.to_dict()
    d["running"] = False
    return d
