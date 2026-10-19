"""REST routes for team threads: one task, several coding agents as peers.

Endpoints (all under ``/api/team-threads``)::

    GET    ""                 Every team thread, newest first
    GET    /seats             The coding agents and providers that can sit in a team
    POST   ""                 Start a team thread on a task (as peers, or planner and builder)
    GET    /{team_id}         The shared thread: members, entries, bounds, caught issues
    POST   /{team_id}/message Step in; every member reads it with its next turn
    POST   /{team_id}/pause   Stop the running turns; the thread can continue later
    POST   /{team_id}/resume  Continue a paused or waiting thread
    POST   /{team_id}/accept  Settle a disagreement: take the plan or the work as it is
    POST   /{team_id}/stop    End the thread
    DELETE /{team_id}         Delete the thread and its members' sessions

The engine (``dodaios.agent_chat.team``) is built on first use, never on boot.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from dodaios.agent_chat.team import Limits, SeatPick, TeamError, TeamThreads, TeamThreadStore
from dodaios.agent_chat.team.engine import MAX_MEMBERS, MIN_MEMBERS
from dodaios.agent_chat.team.store import MODES, ROLES

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/team-threads", tags=["team-threads"])

_BUILD_LOCK = threading.Lock()

#: Which seats a new team is offered first, by brand family. An order of
#: preference only: any seat that is ready can sit in a team (AP-21).
_PREFERRED_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("claude",),
    ("openai",),
    ("antigravity", "gemini", "google-cloud"),
)
_DEFAULT_TEAM_SIZE = 3


class SeatBody(BaseModel):
    provider: str
    model: str = ""
    effort: str = ""
    #: The member's role in the planner-and-builder mode; "" = by position.
    role: str = ""

    @field_validator("role")
    @classmethod
    def _known_role(cls, value: str) -> str:
        value = value.strip().lower()
        if value and value not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        return value


class LimitsBody(BaseModel):
    max_minutes: int | None = Field(default=None, ge=5, le=1440)
    max_turns: int | None = Field(default=None, ge=6, le=400)
    plan_rounds: int | None = Field(default=None, ge=1, le=10)
    review_rounds: int | None = Field(default=None, ge=1, le=10)
    turn_minutes: int | None = Field(default=None, ge=2, le=180)
    max_cost_usd: float | None = Field(default=None, ge=0)


class StartBody(BaseModel):
    task: str = Field(min_length=1, max_length=40_000)
    cwd: str
    #: Empty = the default team of the seats that are ready.
    seats: list[SeatBody] = Field(default_factory=list, max_length=MAX_MEMBERS)
    limits: LimitsBody | None = None
    title: str = Field(default="", max_length=200)
    #: "peers" (the default) or "planner_builder".
    mode: str = "peers"

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        return value


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=40_000)


# ------------------------------------------------------------------ engine


def _engine_from_state(state: Any) -> TeamThreads | None:
    """The coordinator, built on first use on top of the agent-chat service."""
    engine = getattr(state, "team_threads", None)
    if engine is not None:
        return engine
    from dodaios.agent_chat.team.port import ChatTurns

    from .agent_chat_routes import _service_from_state

    service = _service_from_state(state)
    if service is None:
        return None
    with _BUILD_LOCK:
        engine = getattr(state, "team_threads", None)
        if engine is not None:
            return engine
        cfg = getattr(state, "config", None)
        data_dir = Path(getattr(getattr(cfg, "memory", None), "data_dir", None) or "data")

        def language(task: str) -> str:
            from dodaios.core.turn_language import resolve_output_language

            return resolve_output_language(
                getattr(getattr(cfg, "brain", None), "reply_language", "auto"), "", task
            )

        engine = TeamThreads(
            TeamThreadStore(data_dir / "team_threads.db"), ChatTurns(service), language=language
        )
        state.team_threads = engine
        return engine


async def _engine(request: Request) -> TeamThreads:
    engine = getattr(request.app.state, "team_threads", None)
    if engine is None:
        # Building opens a database and may build the chat service: off the loop.
        engine = await asyncio.to_thread(_engine_from_state, request.app.state)
    if engine is None:
        raise HTTPException(status_code=503, detail="team-threads-unavailable")
    return engine


def _engine_if_used(state: Any) -> TeamThreads | None:
    """The coordinator, unless this install never started a team thread.

    The thread list asks on every refresh; that must not build anything or
    create a database for someone who never used the feature.
    """
    engine = getattr(state, "team_threads", None)
    if engine is None:
        cfg = getattr(state, "config", None)
        data_dir = Path(getattr(getattr(cfg, "memory", None), "data_dir", None) or "data")
        if not (data_dir / "team_threads.db").is_file():
            return None
        engine = _engine_from_state(state)
    return engine


def team_sessions(state: Any) -> dict[str, str]:
    """``session_id -> team_id`` for the thread list; empty before first use."""
    engine = _engine_if_used(state)
    return engine.session_teams() if engine is not None else {}


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Team thread not found")
    return HTTPException(status_code=409, detail=str(exc))


# ------------------------------------------------------------------ seats


async def _seats() -> list[dict[str, Any]]:
    """Every seat of the thread layout with whether it can run here right now."""
    from .agent_chat_routes import _live_cli_models

    try:
        live = await _live_cli_models()
    except Exception:  # noqa: BLE001 - without the lists a seat runs its CLI's own default
        log.warning("team threads: the coding CLIs' model lists are unavailable", exc_info=True)
        live = {}
    return await asyncio.to_thread(_seat_rows, live)


def _seat_rows(live: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    from dodaios.core.config import get_secret
    from dodaios.ui.web.provider_spec import get_spec

    from .agent_chat_routes import _catalog_rows

    seats = []
    for row in _catalog_rows("agent", live):
        installed = row.get("cli_installed")
        if installed is None:
            # An API seat: ready with a saved key, or without one on local hardware.
            spec = get_spec(row["id"])
            keys = spec.secret_keys if spec is not None else ()
            ready = bool(row.get("keyless")) or any(get_secret(key) for key in keys)
        else:
            ready = bool(installed)
        options = _model_options(row)
        seats.append(
            {
                "provider": row["id"],
                "label": row["label"],
                "family": row["family"],
                "runner": row["runner"],
                "agent": row.get("agent", ""),
                "model": row.get("default_model", ""),
                "fallback": _seat_fallback(row, live),
                "models": [option["id"] for option in options],
                "model_options": options,
                "efforts": _efforts(row.get("effort_levels")),
                "ready": ready,
                "local": bool(row.get("keyless")),
            }
        )
    return seats


def _efforts(levels: Any) -> list[str]:
    """Effort levels a member can be given; "" (the seat's own) is always there too."""
    return [str(level) for level in levels or [] if str(level or "").strip()]


def _model_options(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The models a member on this seat can run, as every model picker lists them.

    Models hidden on the API Keys page stay out, as in the composer.
    """
    hidden = set(row.get("hidden_models") or [])
    options = []
    for model in row.get("curated_models") or []:
        model_id = str(model.get("id") or "")
        if not model_id or model_id in hidden:
            continue
        options.append(
            {
                "id": model_id,
                "label": str(model.get("label") or model_id),
                "efforts": _efforts(model.get("efforts")),
            }
        )
    return options


def short_model_label(seat_label: str, model_label: str) -> str:
    """The model's name without the words the seat's name already says.

    "Anthropic Claude" with "Claude Opus 5.5" reads "Opus 5.5". A model name
    that would then start with a bare number ("Grok 4.7" on "Grok Build")
    keeps its words.
    """
    seat_words = {word.lower() for word in seat_label.split()}
    words = model_label.split()
    rest = list(words)
    while rest and rest[0].lower() in seat_words:
        rest.pop(0)
    if not rest or rest == words or rest[0][:1].isdigit():
        return model_label.strip()
    return " ".join(rest)


def _seat_fallback(row: dict[str, Any], live: dict[str, list[dict[str, Any]]]) -> str:
    """A model to fall back on when the seat's own default is refused.

    A seat starts on its runner's default. A CLI's configured default can name
    a model the signed-in account may not use; the first model the CLI lists
    for this account is tried once then. ``""`` where the CLI lists none.
    """
    listed = live.get(str(row.get("runner") or "")) or []
    return str(listed[0].get("id") or "") if listed else ""


def _efforts_for(row: dict[str, Any], model: str) -> list[str]:
    """The effort levels the picked model (or else the seat) offers; [] = any."""
    for option in row.get("model_options") or []:
        if option["id"] == model and option.get("efforts"):
            return list(option["efforts"])
    return list(row.get("efforts") or [])


def default_team(seats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Up to three ready seats from different families; a coding CLI before an API row.

    With fewer families ready, the team fills up with what there is: a second
    row of one family, then the same seat twice. One ready seat is still a
    team of two; none is an empty list.
    """
    ready = [s for s in seats if s["ready"] and not s["local"]] or [s for s in seats if s["ready"]]
    ready.sort(key=lambda s: 0 if s["agent"] else 1)
    team: list[dict[str, Any]] = []
    used_families: set[str] = set()

    def group(family: str) -> str:
        for families in _PREFERRED_FAMILIES:
            if family in families:
                return families[0]
        return family

    for families in _PREFERRED_FAMILIES:
        seat = next((s for s in ready if s["family"] in families), None)
        if seat is not None:
            team.append(seat)
            used_families.add(group(seat["family"]))
    for seat in ready:
        if len(team) >= _DEFAULT_TEAM_SIZE:
            break
        if group(seat["family"]) not in used_families:
            team.append(seat)
            used_families.add(group(seat["family"]))
    for seat in ready:
        if len(team) >= MIN_MEMBERS:
            break
        if seat not in team:
            team.append(seat)
    if len(team) == 1:
        team.append(team[0])
    return team[:_DEFAULT_TEAM_SIZE]


@router.get("/seats", openapi_extra={"x-jarvis-readonly": True})
async def get_seats() -> dict[str, Any]:
    """The seats a team can be made of, and the team a new thread starts with."""
    seats = await _seats()
    return {
        "seats": seats,
        "default": [{"provider": s["provider"], "model": s["model"]} for s in default_team(seats)],
        "min_members": MIN_MEMBERS,
        "max_members": MAX_MEMBERS,
        # The default turn bound by team size, so the start form can say it.
        "max_turns": {
            str(size): Limits.for_team(size).max_turns
            for size in range(MIN_MEMBERS, MAX_MEMBERS + 1)
        },
    }


# ------------------------------------------------------------------ threads


@router.get("", openapi_extra={"x-jarvis-readonly": True})
async def list_team_threads(request: Request) -> dict[str, Any]:
    """List every team thread, newest first."""
    engine = await asyncio.to_thread(_engine_if_used, request.app.state)
    return {"threads": await asyncio.to_thread(engine.threads) if engine is not None else []}


@router.post("", status_code=201, openapi_extra={"x-jarvis-dangerous": True})
async def start_team_thread(body: StartBody, request: Request) -> dict[str, Any]:
    """Give a team of coding agents one task to plan, build and review together.

    ``mode`` "planner_builder" gives each member a role (``seats[].role``, or by
    position: plans, builds, reviews): one member owns a living plan, one builds
    it step by step, the others review the plan and every step.
    """
    engine = await _engine(request)
    rows = await _seats()
    by_id = {row["provider"]: row for row in rows}
    wanted = [seat.model_dump() for seat in body.seats] or [
        {"provider": s["provider"], "model": s["model"], "effort": "", "role": ""}
        for s in default_team(rows)
    ]
    if body.seats and len(wanted) < MIN_MEMBERS:
        raise HTTPException(
            status_code=422,
            detail=f"A team thread has {MIN_MEMBERS} to {MAX_MEMBERS} members.",
        )
    if len(wanted) < MIN_MEMBERS:
        raise HTTPException(
            status_code=409,
            detail="No coding agent or provider is ready. Connect one first.",
        )
    picks = []
    for seat in wanted:
        row = by_id.get(seat["provider"].strip().lower())
        if row is None:
            raise HTTPException(status_code=400, detail=f"Unknown seat: {seat['provider']}")
        if not row["ready"]:
            # Said now, not as a member that leaves after the others have worked.
            raise HTTPException(
                status_code=409, detail=f"{row['label']} is not connected on this machine."
            )
        model = (seat.get("model") or "").strip()
        effort = (seat.get("effort") or "").strip()
        offered = _efforts_for(row, model)
        if effort and offered and effort not in offered:
            raise HTTPException(
                status_code=422,
                detail=f"{row['label']} runs with effort {', '.join(offered)}, not {effort}.",
            )
        labels = {option["id"]: option["label"] for option in row.get("model_options") or []}
        picks.append(
            SeatPick(
                provider=row["provider"],
                model=model or row["model"],
                # Only where the person left the model to the seat.
                fallback_model="" if model else row.get("fallback", ""),
                effort=effort,
                name=row["label"],
                # Two members on one seat read apart by the model the person picked.
                model_label=short_model_label(row["label"], labels.get(model, model))
                if model
                else "",
                family=row["family"],
            )
        )
    limits = body.limits.model_dump(exclude_none=True) if body.limits else None
    from .agent_chat_routes import _validate_cwd

    cwd = await asyncio.to_thread(_validate_cwd, body.cwd)
    if cwd is None:
        raise HTTPException(status_code=400, detail="A team thread needs a project folder.")
    try:
        return await engine.start(
            task=body.task,
            cwd=cwd,
            seats=picks,
            limits=limits,
            title=body.title,
            mode=body.mode,
            roles=[str(seat.get("role") or "") for seat in wanted],
        )
    except TeamError as exc:
        raise _refused(exc) from exc


@router.get("/{team_id}", openapi_extra={"x-jarvis-readonly": True})
async def get_team_thread(
    team_id: str, request: Request, after: int = Query(0, ge=0)
) -> dict[str, Any]:
    """Read the shared thread; ``after`` returns only the entries past that number."""
    engine = await _engine(request)
    try:
        return await asyncio.to_thread(engine.snapshot, team_id, after=after)
    except KeyError as exc:
        raise _refused(exc) from exc


@router.post("/{team_id}/message", openapi_extra={"x-jarvis-dangerous": True})
async def message_team_thread(team_id: str, body: MessageBody, request: Request) -> dict[str, Any]:
    """Step into a team thread; every member reads the message with its next turn."""
    engine = await _engine(request)
    try:
        return await engine.message(team_id, body.text)
    except (TeamError, KeyError) as exc:
        raise _refused(exc) from exc


async def _command(request: Request, team_id: str, name: str) -> dict[str, Any]:
    engine = await _engine(request)
    try:
        return await getattr(engine, name)(team_id)
    except (TeamError, KeyError) as exc:
        raise _refused(exc) from exc


@router.post("/{team_id}/pause", openapi_extra={"x-jarvis-dangerous": True})
async def pause_team_thread(team_id: str, request: Request) -> dict[str, Any]:
    """Stop the team's running turns; the thread can continue later."""
    return await _command(request, team_id, "pause")


@router.post("/{team_id}/resume", openapi_extra={"x-jarvis-dangerous": True})
async def resume_team_thread(team_id: str, request: Request) -> dict[str, Any]:
    """Continue a paused or waiting team thread; a reached bound grows by half."""
    return await _command(request, team_id, "resume")


@router.post("/{team_id}/accept", openapi_extra={"x-jarvis-dangerous": True})
async def accept_team_thread(team_id: str, request: Request) -> dict[str, Any]:
    """Settle a disagreement by taking the plan, or the work, as it is."""
    return await _command(request, team_id, "accept")


@router.post("/{team_id}/stop", openapi_extra={"x-jarvis-dangerous": True})
async def stop_team_thread(team_id: str, request: Request) -> dict[str, Any]:
    """End a team thread and stop its running turns."""
    return await _command(request, team_id, "stop")


@router.delete("/{team_id}", openapi_extra={"x-jarvis-dangerous": True})
async def delete_team_thread(team_id: str, request: Request) -> dict[str, bool]:
    """Delete a team thread and the sessions of its members."""
    engine = await _engine(request)
    try:
        await engine.delete(team_id)
    except (TeamError, KeyError) as exc:
        raise _refused(exc) from exc
    return {"deleted": True}
