"""The lead thread: brief, proactive settings, life admin, standing tasks, triggers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)

from dodaios.agentic_ide import thread_finder
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    LeadBriefBody,
    LeadCheckinBody,
    LeadLifeAdminBody,
    LeadProactiveBody,
    LeadStandingBody,
    LeadStandingPatchBody,
    LeadTriggerEventBody,
)

router = APIRouter()


@router.get("/lead", summary="The lead's one endless conversation (created on first use)")
async def get_lead_session(request: Request) -> dict[str, Any]:
    from dodaios.agent_chat.lead import lead_session

    svc = _r._service(request)
    session = await asyncio.to_thread(lead_session, svc)
    if session is None:
        raise HTTPException(status_code=409, detail="No chat provider is set up yet")
    d = session.to_dict()
    d["running"] = svc.is_running(session.session_id)
    d["lead"] = True
    return d


@router.get(
    "/lead/threads",
    summary="The Agentic IDE threads the assistant wrote a task into, newest first",
)
def list_lead_threads(request: Request, limit: int = Query(12, ge=1, le=50)) -> dict[str, Any]:
    from dodaios.agent_chat.catalog import provider_row
    from dodaios.society.coding_threads import _label_of
    from dodaios.society.roster import LEAD_AGENT_ID

    svc = _r._service(request)
    out = []
    for session, briefed_ms in svc.store.sessions_briefed_by(LEAD_AGENT_ID, limit=limit):
        row = provider_row(session.provider)
        out.append(
            {
                "session_id": session.session_id,
                "title": session.title,
                "cli_title": _r._cli_title(svc, session),
                "provider": session.provider,
                # The coding CLI's registry id, so the sidebar draws its logo.
                "agent": row.agent if row is not None and row.agent else "",
                "agent_label": _label_of(session.provider),
                "cwd": session.cwd,
                "briefed_ms": briefed_ms,
                "updated_ms": session.updated_ms,
                "running": _r._reported_running(svc, session.session_id),
                "waiting": bool(
                    svc.pending_approvals(session.session_id)
                    or svc.pending_questions(session.session_id)
                ),
            }
        )
    return {"threads": out}


@router.get(
    "/thread-links/{ref}",
    summary="The coding thread a chat link or a thread code names: its title and coding agent",
    openapi_extra={"x-jarvis-readonly": True},
)
def get_thread_link(ref: str, request: Request) -> dict[str, Any]:
    """What a ``thread:<id>`` link in a chat answer draws: title, coding agent, code.

    ``ref`` is a thread's session id or its code. ``found`` is false when no
    thread (or more than one) answers to it; the chat then draws plain text.
    """
    from dodaios.agent_chat.catalog import provider_row
    from dodaios.society.coding_threads import _label_of

    svc = _r._service(request)
    key = thread_finder.code_key(ref)
    session = svc.store.get_session(key) if key else None
    if session is None:
        matches = thread_finder.sessions_for_code(svc.store, ref)
        session = matches[0] if len(matches) == 1 else None
    if session is None or session.surface != thread_finder.THREAD_SURFACE:
        return {"found": False, "ref": ref}
    row = provider_row(session.provider)
    return {
        "found": True,
        "session_id": session.session_id,
        "code": thread_finder.thread_code(session.session_id),
        "title": thread_finder.shown_title(svc.store, session),
        "agent": row.agent if row is not None and row.agent else "",
        "agent_label": _label_of(session.provider),
        "provider": session.provider,
        "cwd": session.cwd,
        "running": _r._reported_running(svc, session.session_id),
    }


@router.get("/lead/files", summary="The files the assistant handed over in its conversation")
def list_lead_files(request: Request, limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    from dodaios.agent_chat.lead import lead_session_id
    from dodaios.agent_chat.lead_files import SCAN_MESSAGES, handed_over

    svc = _r._service(request)
    session_id = lead_session_id(svc)
    if not session_id:
        return {"files": []}
    messages = svc.store.assistant_texts(session_id, limit=SCAN_MESSAGES)
    return {"files": handed_over(messages, limit=limit)}


@router.get("/lead/channels", summary="Where the person reaches the assistant outside the app")
async def get_lead_channels(request: Request) -> dict[str, Any]:
    from dodaios.agent_chat.reach import channels_view

    manager = getattr(request.app.state, "channel_manager", None)
    # The Slack grant is read from the keyring, which can block.
    return await asyncio.to_thread(channels_view, manager)


@router.get("/lead/brief", summary="The morning brief's state (off until turned on)")
async def get_lead_brief() -> dict[str, Any]:
    from dodaios.agent_chat.proactive import brief_state

    return await brief_state()


@router.put("/lead/brief", summary="Turn the morning brief on or off, or move it")
async def put_lead_brief(body: LeadBriefBody) -> dict[str, Any]:
    from dodaios.agent_chat.proactive import set_brief

    try:
        return await set_brief(enabled=body.enabled, local_time=body.time, timezone=body.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/lead/proactive", summary="Proactivity settings and the 'needs you' check's state")
async def get_lead_proactive() -> dict[str, Any]:
    from dodaios.agent_chat.proactive_checks import checks_state

    return await checks_state()


@router.put("/lead/proactive", summary="Set the proactivity level, topics and rhythm")
async def put_lead_proactive(body: LeadProactiveBody) -> dict[str, Any]:
    from dodaios.agent_chat.proactive_checks import apply_settings
    from dodaios.agent_chat.proactive_settings import ProactiveSettings

    settings = ProactiveSettings.from_dict(body.model_dump())
    try:
        return await apply_settings(settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/lead/proactive/checkin", status_code=201, summary="A one-shot check-in in N minutes")
async def post_lead_checkin(body: LeadCheckinBody) -> dict[str, Any]:
    from dodaios.agent_chat.checkins import CheckinRequest, schedule_checkin

    try:
        return await schedule_checkin(CheckinRequest(minutes=body.minutes, doing=body.doing))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/lead/life-admin", summary="Life admin: settings and the open items (off by default)")
async def get_lead_life_admin() -> dict[str, Any]:
    from dodaios.life_admin.service import state

    return await state()


@router.put("/lead/life-admin", summary="Turn life admin on or off, set the digest and kinds")
async def put_lead_life_admin(body: LeadLifeAdminBody) -> dict[str, Any]:
    from dodaios.life_admin.service import apply_settings
    from dodaios.life_admin.settings import LifeAdminSettings

    try:
        return await apply_settings(LifeAdminSettings.from_dict(body.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/lead/life-admin/items/{item_id}/prepare", summary="Prepare a draft; sends nothing")
async def prepare_lead_life_admin_item(item_id: str) -> dict[str, Any]:
    from dodaios.life_admin.service import prepare_item

    item = await prepare_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such open item")
    return item


@router.post("/lead/life-admin/items/{item_id}/dismiss", summary="Never show this item again")
async def dismiss_lead_life_admin_item(item_id: str) -> dict[str, Any]:
    from dodaios.life_admin.service import dismiss_item

    if not await dismiss_item(item_id):
        raise HTTPException(status_code=404, detail="No such item")
    return {"id": item_id, "status": "dismissed"}


@router.post("/lead/life-admin/items/{item_id}/done", summary="Mark this item done")
async def finish_lead_life_admin_item(item_id: str) -> dict[str, Any]:
    from dodaios.life_admin.service import finish_item

    if not await finish_item(item_id):
        raise HTTPException(status_code=404, detail="No such item")
    return {"id": item_id, "status": "done"}


def _standing_refused(exc: Any) -> HTTPException:
    return HTTPException(
        status_code=_r._STANDING_STATUS.get(str(exc.code), 400), detail=str(exc.message)
    )


async def _lead_session_id(request: Request) -> str:
    """The lead conversation's id, or ``""`` before there is one: where a click came from."""
    from dodaios.agent_chat.lead import lead_session

    svc = getattr(request.app.state, "agent_chat", None)
    if svc is None:
        return ""
    try:
        session = await asyncio.to_thread(lead_session, svc, create=False)
    except Exception:  # noqa: BLE001 - the click still counts without its conversation
        _r.log.debug("standing tasks: lead conversation not resolved", exc_info=True)
        return ""
    return str(session.session_id) if session is not None else ""


@router.get("/lead/standing", summary="Standing tasks: what the assistant looks after, and limits")
async def get_lead_standing(ended: bool = False) -> dict[str, Any]:
    from dodaios.standing_tasks import service
    from dodaios.standing_tasks.models import StandingError

    try:
        view = dict(await service.overview())
        if ended:
            tasks = await service.list_tasks(include_ended=True)
            view["tasks"] = [task.to_dict() for task in tasks]
    except StandingError as exc:
        raise _r._standing_refused(exc) from exc
    return view


@router.post("/lead/standing", status_code=201, summary="The owner hands over a standing task")
async def post_lead_standing(body: LeadStandingBody) -> dict[str, Any]:
    from dodaios.standing_tasks import service
    from dodaios.standing_tasks.models import StandingError

    # Written in the panel, not said in a chat: no ``origin_session``, so the service
    # gives it what a task set up outside a chat gets.
    try:
        task = await service.take_on(**body.model_dump(exclude_none=True), origin="owner")
    except StandingError as exc:
        raise _r._standing_refused(exc) from exc
    return {"task": task.to_dict()}


@router.get("/lead/standing/{standing_id}", summary="One standing task and its last runs")
async def get_lead_standing_task(
    standing_id: str, runs: int = Query(20, ge=1, le=100)
) -> dict[str, Any]:
    from dodaios.standing_tasks import service
    from dodaios.standing_tasks.models import StandingError

    try:
        task = await service.get_task(standing_id)
        if task is None:
            raise HTTPException(status_code=404, detail="No such standing task")
        log_rows = await service.runs_of(standing_id, limit=runs)
    except StandingError as exc:
        raise _r._standing_refused(exc) from exc
    return {"task": task.to_dict(), "runs": [run.to_dict() for run in log_rows]}


@router.patch("/lead/standing/{standing_id}", summary="Change a standing task's wording or pace")
async def patch_lead_standing(standing_id: str, body: LeadStandingPatchBody) -> dict[str, Any]:
    from dodaios.standing_tasks import service
    from dodaios.standing_tasks.models import StandingError

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    try:
        task = await service.update(standing_id, **changes)
    except StandingError as exc:
        raise _r._standing_refused(exc) from exc
    return {"task": task.to_dict()}


@router.post(
    "/lead/standing/{standing_id}/{action}",
    summary="Accept, decline, pause, resume, end or run a standing task now",
)
async def act_on_lead_standing(standing_id: str, action: str, request: Request) -> dict[str, Any]:
    from dodaios.core.protocols import started_by_user
    from dodaios.standing_tasks import service
    from dodaios.standing_tasks.models import StandingError

    name = _r._STANDING_ACTIONS.get(action)
    if name is None:
        raise HTTPException(status_code=404, detail="Unknown action")
    try:
        if action == "accept":
            # The proposal is a card in the lead conversation: a click on it is a yes
            # said there, so an ``act`` task never gets more than that chat allows.
            task = await service.accept(
                standing_id, origin_session=await _r._lead_session_id(request)
            )
        elif action == "run":
            # The owner's own click: it runs on the task's seat as chosen, the way
            # "Run now" on a routine does. A run the assistant starts does not.
            with started_by_user():
                task = await service.run_now(standing_id)
        else:
            task = await getattr(service, name)(standing_id)
    except StandingError as exc:
        raise _r._standing_refused(exc) from exc
    return {"task": task.to_dict()}


def _trigger_service() -> Any:
    from dodaios.lead_triggers.wiring import get_service

    service = get_service()
    if service is None:
        raise HTTPException(status_code=503, detail="The agent society is not running")
    return service


async def _trigger_view() -> dict[str, Any]:
    from dodaios.lead_triggers.wiring import producers_view

    view = await _r._trigger_service().view()
    view["producers"] = await producers_view()
    return view


@router.get("/lead/triggers", summary="Event trigger rules, drop counts and the decision log")
async def get_lead_triggers() -> dict[str, Any]:
    return await _r._trigger_view()


@router.put("/lead/triggers", summary="Set the accept mode, source rules and policies")
async def put_lead_triggers(body: dict[str, Any]) -> dict[str, Any]:
    from dodaios.lead_triggers import TriggerSettings

    service = _r._trigger_service()
    await service.save_settings(TriggerSettings.from_dict(body))
    return await _r._trigger_view()


@router.post("/lead/triggers/policies/{policy_id}/promote", summary="Let one policy act")
async def promote_lead_trigger_policy(policy_id: str) -> dict[str, Any]:
    service = _r._trigger_service()
    if await service.promote(policy_id) is None:
        raise HTTPException(status_code=404, detail="Unknown policy")
    return await service.view()


@router.get("/lead/prepared", summary="Drafts and fixes prepared in advance, waiting for the owner")
async def get_lead_prepared(thread_key: str = "") -> dict[str, Any]:
    preparer = _r._trigger_service().preparer
    if preparer is None:
        return {"items": [], "stats": None, "settings": None}
    items = await preparer.waiting(thread_key)
    return {
        "items": [i.to_dict() for i in items],
        "stats": preparer.items.stats(),
        "settings": (await preparer.settings()).to_dict(),
    }


@router.put("/lead/prepared/settings", summary="Switch the kinds of preparation on or off")
async def put_lead_prepared_settings(body: dict[str, Any]) -> dict[str, Any]:
    from dodaios.lead_triggers.prepare import PrepareSettings

    preparer = _r._trigger_service().preparer
    if preparer is None:
        raise HTTPException(status_code=503, detail="Preparation is not available")
    return (await preparer.save_settings(PrepareSettings.from_dict(body))).to_dict()


@router.post("/lead/prepared/{item_id}/{outcome}", summary="Mark a prepared item used or not")
async def resolve_lead_prepared(item_id: str, outcome: str) -> dict[str, Any]:
    if outcome not in ("used", "discard"):
        raise HTTPException(status_code=404, detail="Unknown outcome")
    preparer = _r._trigger_service().preparer
    if preparer is None:
        raise HTTPException(status_code=503, detail="Preparation is not available")
    done = (
        preparer.items.mark_used(item_id)
        if outcome == "used"
        else preparer.items.mark_discarded(item_id)
    )
    if not done:
        raise HTTPException(status_code=404, detail="No such waiting item")
    return {"ok": True}


@router.post(
    "/lead/triggers/events",
    status_code=202,
    summary="Feed one event (mail, calendar, code host) into the trigger intake",
    openapi_extra={"x-jarvis-dangerous": True},
)
async def post_lead_trigger_event(body: LeadTriggerEventBody) -> dict[str, str]:
    from dodaios.lead_triggers.event import SOURCES
    from dodaios.lead_triggers.wiring import submit_payload

    if body.source not in SOURCES:
        raise HTTPException(status_code=422, detail=f"source must be one of {', '.join(SOURCES)}")
    return {"verdict": await submit_payload(body.source, body.payload)}


@router.post("/lead/fresh-start", summary="Start the lead's model fresh; the thread stays")
async def lead_fresh_start(request: Request) -> dict[str, Any]:
    from dodaios.agent_chat.lead import fresh_start, lead_session

    svc = _r._service(request)
    through = await asyncio.to_thread(fresh_start, svc)
    if through is None:
        raise HTTPException(status_code=409, detail="The conversation is not ready yet")
    session = lead_session(svc, create=False)
    if session is not None:
        await svc.post_notice(session.session_id, {"kind": "context_reset", "status": "done"})
    return {"ok": True, "through_seq": through}
