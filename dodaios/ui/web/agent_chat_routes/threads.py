"""One session: fork, read, patch, delete, post a message, side questions."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)

from dodaios.agent_chat.catalog import offers
from dodaios.agent_chat.effort import normalize_effort
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.permissions import (
    PLAN_MODES,
    is_permission_mode,
    ladder_key,
    normalize_permission,
    permission_modes,
    society_mode_supported,
)
from dodaios.agent_chat.service import (
    NoSuchSession,
    SessionBusy,
)
from dodaios.agent_chat.speed import normalize_speed
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    ForkSessionBody,
    FromTerminalBody,
    MessageBody,
    PatchSessionBody,
)

router = APIRouter()


@router.post("/sessions/from-terminal", status_code=201)
async def thread_from_terminal(body: FromTerminalBody, request: Request) -> dict[str, Any]:
    """A thread that continues the conversation a grid pane is having."""
    from dodaios.agent_chat.catalog import PROVIDER_ROWS
    from dodaios.agent_chat.thread_sessions import clean_vendor_session
    from dodaios.agentic_ide.session import get_registry

    svc = await _r._async_service(request)
    registry = get_registry()
    found = registry._locate(body.name, body.workspace_id)  # noqa: SLF001 — the grid's own lookup
    if found is None:
        raise HTTPException(404, "terminal not found")
    workspace, term = found
    row = next(
        (r for r in PROVIDER_ROWS if r.agent == term.agent and r.runner.endswith("-cli")), None
    )
    handle = term.resume
    if row is None or handle is None:
        raise HTTPException(409, "This terminal has no conversation a thread can continue yet.")
    try:
        vendor = clean_vendor_session(row.runner, handle.id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session = svc.create_session(
        provider=row.id,
        model=term.model or "",
        effort=term.effort or None,
        cwd=_r._validate_cwd(term.cwd(workspace.folder)),
        permission_mode=normalize_permission(
            ladder_key("agent", row.runner), term.permission_mode or ""
        ),
        account_id=term.account or "",
        surface="agent",
    )
    session = svc.store.update_session(session.session_id, vendor_session=vendor) or session
    d = session.to_dict()
    d["running"] = False
    return d


@router.post("/sessions/{session_id}/fork", status_code=201)
async def fork_session(session_id: str, body: ForkSessionBody, request: Request) -> dict[str, Any]:
    """Copy a thread into a new one, optionally in a fresh git worktree."""
    from dodaios.agent_chat.thread_sessions import fork_session as make_fork
    from dodaios.agentic_ide import fork as worktree_fork

    svc = await _r._async_service(request)
    source = svc.store.get_session(session_id)
    if source is None:
        raise HTTPException(404, "session not found")
    if source.surface != "agent":
        raise HTTPException(400, "Only coding threads can be forked.")
    if svc.is_running(session_id):
        raise HTTPException(409, "Wait for the thread to finish its turn before forking it.")
    runner = _r.resolve_runner(
        source.provider, surface=source.surface, account_id=source.account_id
    )
    cwd = source.cwd
    if body.worktree:
        name = body.name.strip() or await asyncio.to_thread(
            worktree_fork.suggest_name, cwd, source.title or "thread"
        )
        try:
            created = await asyncio.to_thread(worktree_fork.create_worktree, cwd, name)
        except worktree_fork.ForkError as exc:
            raise HTTPException(409, str(exc)) from exc
        cwd = str(created.folder)
    copy = await asyncio.to_thread(
        make_fork,
        svc,
        source,
        runner=runner,
        cwd=cwd,
        title=body.title.strip() or source.title,
    )
    d = copy.to_dict()
    d["running"] = False
    return d


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    request: Request,
    tail: int | None = Query(
        None, ge=1, le=500, description="Only the newest N events (e.g. a live preview)."
    ),
) -> dict[str, Any]:
    svc = _r._service(request)
    session = svc.store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.surface in ("jarvis", "society"):
        from dodaios.agent_chat.send_queue import close_orphans

        await close_orphans(svc, session_id)
    d = session.to_dict()
    d["running"] = svc.is_running(session_id)
    events = await asyncio.to_thread(svc.store.list_events, session_id, tail=tail)
    return {"session": d, "events": events}


@router.get(
    "/sessions/{session_id}/subagents",
    summary="The sub-agents a coding agent spawned, read from the CLI's own session files",
    openapi_extra={"x-jarvis-readonly": True},
)
async def list_subagents(session_id: str, request: Request) -> dict[str, Any]:
    """A thread's sub-agents whose steps the CLI does not stream (Codex).

    Claude Code streams its sub-agents into the thread itself; Codex files each
    one as a rollout of its own. ``agents`` is empty for every other CLI.
    """
    from dodaios.agent_chat.subagent_transcripts import codex_homes, codex_subagents

    svc = await _r._async_service(request)
    session = svc.store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    runner = _r.resolve_runner(session.provider, surface=session.surface, runtime=session.runtime)
    if runner != "codex-cli" or not session.vendor_session:
        return {"agents": []}
    parent, since, account = session.vendor_session, session.created_ms, session.account_id
    # Reading rollouts is file work: off the event loop.
    agents = await asyncio.to_thread(
        lambda: codex_subagents(parent, since_ms=since, homes=codex_homes(account or None))
    )
    return {"agents": [agent.to_dict() for agent in agents]}


@router.get(
    "/sessions/{session_id}/context",
    summary="How full the thread's context window is, and what fills it",
    openapi_extra={"x-jarvis-readonly": True},
)
async def get_context_window(
    session_id: str,
    request: Request,
    detail: bool = Query(False, description="Also ask the CLI what fills the window."),
) -> dict[str, Any]:
    """A Claude Code thread's context window, for the ring under its composer.

    ``reading`` is the last answer's count from the CLI's own session file
    (the live count arrives with the thread's events); ``breakdown`` is
    Claude Code's ``/context`` report, run on an unsaved fork of the session
    when ``detail`` is set. Every other CLI answers ``supported: false``.
    """
    from dodaios.agent_chat import context_window
    from dodaios.agent_chat.thread_sessions import split_fork

    svc = await _r._async_service(request)
    session = svc.store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    runner = _r.resolve_runner(session.provider, surface=session.surface, runtime=session.runtime)
    if runner != "claude-cli" or session.computer_id:
        return {"supported": False, "reading": None, "breakdown": None}
    resume_id, fork_source = split_fork(session.vendor_session)
    vendor = resume_id or fork_source or ""
    found = await asyncio.to_thread(context_window.find_session_file, vendor, session.account_id)
    recorded = await asyncio.to_thread(context_window.read_recorded, found[0]) if found else None
    breakdown = None
    if found and (detail or (recorded is not None and not recorded.get("window"))):
        breakdown = await context_window.probe_breakdown(
            vendor_session=session.vendor_session or "",
            cwd=session.cwd,
            model=(recorded or {}).get("model") or session.model,
            account_id=session.account_id,
        )
        if recorded is not None and not recorded.get("window"):
            recorded["window"] = context_window.known_window(recorded["model"]) or (
                breakdown.window if breakdown else None
            )
    return {
        "supported": True,
        "reading": recorded,
        "breakdown": breakdown.to_dict() if breakdown and detail else None,
    }


async def _leave_provider(svc: Any, session_id: str) -> None:
    """Clear the way for a provider change, or refuse it while a turn runs.

    That turn would write its own CLI's conversation id onto the new provider.
    """
    from dodaios.agent_chat.lead import SEAT_BUSY

    await svc._await_finishing(session_id)  # noqa: SLF001 — same package boundary
    if not svc.is_running(session_id):
        await svc.controls._clear_saved_native(session_id)
    if svc.is_running(session_id):  # one that ran, or arrived while that waited
        raise HTTPException(status_code=409, detail=SEAT_BUSY)


@router.patch("/sessions/{session_id}")
async def patch_session(
    session_id: str, body: PatchSessionBody, request: Request
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    existing = svc.store.get_session(session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="session not found")
    if existing.surface == "society" and ":routine:" in session_id:
        raise HTTPException(status_code=403, detail="Routine chat is owned by its schedule")
    if existing.surface == "society" and svc.is_running(session_id):
        raise HTTPException(status_code=409, detail="Agent chat is working")
    fields: dict[str, Any] = {}
    provider_moves = False
    if body.title is not None:
        fields["title"] = body.title.strip()[:120]
    if body.provider is not None:
        picked = body.provider.strip().lower()
        if not offers(existing.surface, picked):
            raise HTTPException(
                status_code=400,
                detail=f"provider {picked!r} is not offered on the {existing.surface!r} chat",
            )
        fields["provider"] = picked
        provider_moves = picked != existing.provider
        if provider_moves:
            fields["account_id"] = ""
            # A provider change resets the vendor conversation: the new CLI
            # cannot resume the old one's id.
            fields["vendor_session"] = ""
    if body.model is not None:
        fields["model"] = body.model.strip()
    if body.effort is not None:
        provider = fields.get("provider") or svc.store.get_session(session_id).provider  # type: ignore[union-attr]
        fields["effort"] = normalize_effort(provider, body.effort)
    if body.speed is not None:
        fields["speed"] = normalize_speed(body.speed)
    current = svc.store.get_session(session_id)
    assert current is not None
    if body.cwd is not None and not kit_for(current.surface).plain:
        fields["cwd"] = _r._validate_cwd(body.cwd) or svc.default_cwd(current.surface)
        if fields["cwd"] != current.cwd:
            # A CLI keeps its conversations per folder: the old id cannot be
            # resumed from the new one.
            fields["vendor_session"] = ""
    if body.computer_id is not None:
        new_computer = _r._validate_computer(body.computer_id, current.surface)
        if new_computer != current.computer_id:
            if svc.is_running(session_id):
                raise HTTPException(409, "Stop the running turn before moving the thread")
            fields["computer_id"] = new_computer
            # The CLI's conversation lives on the old computer.
            fields["vendor_session"] = ""
    runner = _r.resolve_runner(
        fields.get("provider") or current.provider,
        surface=current.surface,
        runtime=str(getattr(current, "runtime", "") or ""),
    )
    ladder = ladder_key(current.surface, runner)
    if body.permission_mode is not None:
        if not is_permission_mode(ladder, body.permission_mode):
            raise HTTPException(
                status_code=400,
                detail=(
                    "permission_mode must be one of "
                    + ", ".join(m.id for m in permission_modes(ladder))
                ),
            )
        if current.surface == "society" and not society_mode_supported(
            runner, body.permission_mode
        ):
            raise HTTPException(
                status_code=422,
                detail=f"{runner} cannot provide an actionable approval for {body.permission_mode}",
            )
        fields["permission_mode"] = body.permission_mode
    elif "provider" in fields:
        # A provider change folds the old mode onto the new runner's ladder
        # (a no-op on the Jarvis surface, whose ladder is the same for all),
        # read in the old ladder's words: Claude Code's "auto" is not
        # OpenCode's "auto" (full access).
        before = ladder_key(
            current.surface,
            _r.resolve_runner(
                current.provider,
                surface=current.surface,
                runtime=str(getattr(current, "runtime", "") or ""),
            ),
        )
        fields["permission_mode"] = normalize_permission(
            ladder, current.permission_mode, source=before
        )
        if current.build_mode and not body.build_mode:
            fields["build_mode"] = normalize_permission(ladder, current.build_mode, source=before)
    if body.build_mode and fields.get("permission_mode", current.permission_mode) in PLAN_MODES:
        # The pill while Plan is on: where an approved plan goes on.
        build = normalize_permission(ladder, body.build_mode)
        if build not in PLAN_MODES:
            fields["build_mode"] = build
    if any(key in fields for key in ("provider", "model", "permission_mode", "account_id")):
        if fields.get("permission_mode") == "plan" and current.permission_mode not in (
            "plan",
            "read-only",
        ):
            control = svc.controls.state(session_id)
            control.previous_permission = current.permission_mode
            svc.controls.store.save(control)
        control = svc.controls.state(session_id)
        if (
            control.goal
            and control.goal.status == "active"
            or fields.get("permission_mode") == "plan"
        ):
            await svc.controls.pause(session_id, "Model or permission settings changed")
    if provider_moves:
        # After the pause above, which stops a goal's turn.
        await _leave_provider(svc, session_id)
    if current.surface == "society" and svc.is_running(session_id):
        raise HTTPException(status_code=409, detail="Agent chat is working")
    session = svc.store.update_session(session_id, **fields)
    assert session is not None
    if session.surface == "jarvis" and {"provider", "model", "effort"}.intersection(fields):
        from dodaios.agent_chat.store import ChatSelection

        svc.store.save_chat_selection(
            ChatSelection(session.provider, session.model, session.effort, session.account_id)
        )
    if current.surface == "society" and body.permission_mode is not None:
        svc.store.set_permission_override(session_id, session.permission_mode)
    if current.surface == "society":
        binder = getattr(svc, "bind_society_session", None)
        if binder is not None:
            session = await binder(session_id)
            if body.permission_mode is not None:
                # Persist the effective choice, not a requested escalation that
                # the roster narrowed during binding.
                svc.store.set_permission_override(session_id, session.permission_mode)
    changed = {key: getattr(session, key) for key in fields if key != "vendor_session"}
    if "permission_mode" in changed:
        # Entering Plan records the mode to return to, leaving it drops that.
        changed["build_mode"] = session.build_mode
    if changed:
        await svc._emit(session_id, make_event("session_updated", changed))  # noqa: SLF001 — same package boundary
    d = session.to_dict()
    d["running"] = svc.is_running(session_id)
    return d


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    from dodaios.agent_chat.lead import is_lead

    if is_lead(svc, session_id):
        raise HTTPException(
            status_code=409, detail="The main Dodaios conversation cannot be deleted"
        )
    await svc.controls.pause(session_id, "Session deleted")
    # No request of a deleted chat may come back as a turn.
    svc.parked_work.stop(session_id)
    await svc.controls._clear_saved_native(session_id)
    await svc.discard_credential_requests(session_id)
    if not svc.store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    svc.controls.store.delete(session_id)
    return {"ok": True, "session_id": session_id}


# ------------------------------------------------------------------ turns


@router.post("/sessions/{session_id}/messages", status_code=202)
async def post_message(session_id: str, body: MessageBody, request: Request) -> dict[str, Any]:
    from dodaios.tasks.calendar import calendar_zone
    from dodaios.tasks.context import client_timezone

    if body.timezone is not None:
        try:
            calendar_zone(body.timezone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    from dodaios.agent_chat.send_queue import QueueFull, send_or_queue, try_steer

    svc = await _r._async_service(request)
    token = client_timezone.set(body.timezone)
    try:
        # A ritual's phrase typed into the assistant's conversation starts the
        # sequence the person wrote beforehand; its card is the answer, no turn.
        from dodaios.rituals import said as ritual_said

        ritual_id = await ritual_said.typed(
            svc, session_id, body.text, has_attachments=bool(body.attachments)
        )
        if ritual_id:
            return {"turn_id": "", "session_id": session_id, "ritual": ritual_id}
        # "/btw <question>" in a Claude Code thread: answered beside the work
        # from a copy of the conversation; the running turn is not touched.
        aside_id = await _r._ask_aside(svc, session_id, body.text, has_files=bool(body.attachments))
        if aside_id:
            return {"turn_id": "", "session_id": session_id, "aside": aside_id}
        # A coding thread whose running CLI takes a message mid-turn is steered:
        # the text goes into the turn like typing into a terminal.
        # The person may ask for the other way: wait for the agent to finish.
        if body.delivery != "after" and await try_steer(
            svc,
            session_id,
            body.text,
            body.attachments,
            tool_choices=body.tool_choices,
            overtake=body.delivery == "now",
        ):
            return {"turn_id": "", "session_id": session_id, "steered": True}
        from dodaios.agent_chat import side_threads

        # The lead's conversation answers a message beside a turn that is
        # still working, in a side thread. A turn that only waits hands its
        # seat over instead, and the message is answered in the main thread.
        if (
            body.delivery != "after"
            and side_threads.takes(svc, session_id)
            and not await svc.release_waiting_turn(session_id)
            and svc.is_running(session_id)
        ):
            side_id = await side_threads.start(
                svc, session_id, body.text, body.attachments, tool_choices=body.tool_choices
            )
            return {"turn_id": "", "session_id": session_id, "side_thread": side_id}
        # A created agent's chat queues a message behind its running turn
        # instead of refusing it; every other chat answers 409 as before.
        turn_id, queue_id = await send_or_queue(
            svc, session_id, body.text, body.attachments, tool_choices=body.tool_choices
        )
    except NoSuchSession as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except QueueFull as exc:
        raise HTTPException(status_code=409, detail="too many messages are waiting") from exc
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="a turn is already running") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        client_timezone.reset(token)
    if queue_id:
        return {"turn_id": "", "session_id": session_id, "queued": True, "queue_id": queue_id}
    if not turn_id:
        # "/clear" in a coding thread: the conversation started over, no turn runs.
        return {"turn_id": "", "session_id": session_id, "cleared": True}
    return {"turn_id": turn_id, "session_id": session_id}


async def _ask_aside(svc: Any, session_id: str, text: str, *, has_files: bool) -> str:
    """Start a ``/btw`` side question; ``""`` when the message is not one."""
    from dodaios.agent_chat import aside
    from dodaios.agent_chat.service import session_runner

    question = aside.parse(text)
    if question is None:
        return ""
    session = svc.store.get_session(session_id)
    if session is None:
        raise NoSuchSession(session_id)
    if not aside.takes(session, session_runner(session)):
        return ""
    if has_files:
        raise ValueError("A side question takes text only; send the files as a normal message.")
    return await aside.ask(svc, session_id, question, runner=session_runner(session))


@router.delete(
    "/sessions/{session_id}/asides/{aside_id}",
    summary="Close a side question's card (and stop it if it is still being answered)",
)
async def dismiss_aside(session_id: str, aside_id: str, request: Request) -> dict[str, Any]:
    from dodaios.agent_chat import aside

    svc = await _r._async_service(request)
    if svc.store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    await aside.dismiss(svc, session_id, aside_id)
    return {"dismissed": True, "session_id": session_id, "aside_id": aside_id}
