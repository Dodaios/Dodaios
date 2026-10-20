"""REST routes for the self-building ledger ("Built for you").

Endpoints (all under ``/api/self-build``)::

    GET    ""               Every build, newest change first, plus the loop's status
    GET    /digest          What happened in the last ``hours`` (the daily card)
    POST   /pause           The kill switch: ``{"paused": true}`` stops observing and building
    GET    /{build_id}      One build with its history and what it cost
    POST   /{build_id}/accept  Build a proposed build
    POST   /{build_id}/keep    Keep a build on trial (or restore an archived one)
    POST   /{build_id}/undo    Remove what the build created, or reject the proposal
    GET    /provenance      Which agents, skills and routines a build created (the badge)
    GET    /settings        ``[self_build]`` with each number's range
    PUT    /settings        Change ``[self_build]``; written to jarvis.toml, applied at once

The ledger is opened at boot (``dodaios.self_build.service.start``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from dodaios.self_build import (
    Kind,
    NoBuilder,
    SelfBuild,
    State,
    TransitionError,
    UndoUnavailable,
)
from dodaios.self_build import current as current_service
from dodaios.self_build.cost import spent

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/self-build", tags=["self-build"])


class PauseBody(BaseModel):
    paused: bool


class NoteBody(BaseModel):
    note: str = ""


def _service(request: Request) -> SelfBuild:
    service = getattr(request.app.state, "self_build", None) or current_service()
    if service is None:
        raise HTTPException(status_code=503, detail="self-build ledger is not running")
    return service


def _parse(values: list[str] | None, enum: Any) -> list[Any] | None:
    if not values:
        return None
    try:
        return [enum(v) for v in values]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_builds(
    request: Request,
    state: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    service = _service(request)
    states = _parse(state, State)
    kinds = _parse(kind, Kind)
    rows = await asyncio.to_thread(service.ledger.list, states=states, kinds=kinds, limit=limit)
    status = await asyncio.to_thread(service.status)
    return {"builds": [r.to_json() for r in rows], "status": status}


@router.get("/digest")
async def digest(request: Request, hours: int = Query(default=24, ge=1, le=24 * 30)) -> Any:
    from dodaios.self_build.ledger import now_ms

    service = _service(request)
    return await asyncio.to_thread(service.digest, now_ms() - hours * 3_600_000)


@router.post("/pause")
async def pause(request: Request, body: PauseBody) -> dict[str, Any]:
    service = _service(request)
    await asyncio.to_thread(service.set_paused, body.paused)
    return await asyncio.to_thread(service.status)


@router.get("/provenance")
async def provenance(request: Request, type: str = "") -> dict[str, Any]:  # noqa: A002 — the query name
    """``{"items": {"<type>:<id>": {build_id, state, title, ...}}}`` for the
    "built by Dodaios" badge. Empty (not 503) while the ledger is not running,
    so a list that asks for badges never fails because of them."""
    service = getattr(request.app.state, "self_build", None) or current_service()
    if service is None:
        return {"items": {}}
    return {"items": await asyncio.to_thread(service.provenance, type or None)}


# ------------------------------------------------------------------ settings

_LEVELS = ("off", "suggest", "trial", "full")


class SettingsBody(BaseModel):
    enabled: bool | None = None
    silent_days: int | None = None
    memory: Literal["off", "suggest", "trial", "full"] | None = None
    skill: Literal["off", "suggest", "trial", "full"] | None = None
    routine: Literal["off", "suggest", "trial", "full"] | None = None
    agent: Literal["off", "suggest", "trial", "full"] | None = None
    code: Literal["off", "suggest", "trial", "full"] | None = None
    trial_days: int | None = None
    trial_uses: int | None = None
    max_builds_per_day: int | None = None
    max_agents_per_week: int | None = None
    max_open_trials: int | None = None
    max_code_runs_per_day: int | None = None
    max_rejections: int | None = None
    #: Repositories (``owner/name``) whose loop pull requests merge after green CI.
    code_land_repos: list[str] | None = None


#: ``owner/name`` as GitHub spells it.
_REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def _clean_repos(values: list[str]) -> list[str]:
    """Trim, drop empties and duplicates (case-insensitive), refuse anything not ``owner/name``."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        repo = str(raw).strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
        if not repo:
            continue
        if not _REPO.match(repo):
            raise HTTPException(status_code=400, detail=f"Not a repository (owner/name): {raw!r}")
        if repo.lower() not in seen:
            seen.add(repo.lower())
            out.append(repo)
    if len(out) > 50:
        raise HTTPException(status_code=400, detail="At most 50 repositories.")
    return out


def _config(request: Request) -> Any:
    return getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)


def _settings_payload(section: Any) -> dict[str, Any]:
    from dodaios.core.config import SelfBuildConfig

    values = (section or SelfBuildConfig()).model_dump()
    bounds = {
        name: {"min": _bound(info, "ge"), "max": _bound(info, "le")}
        for name, info in SelfBuildConfig.model_fields.items()
        if info.annotation is int
    }
    keys = SelfBuildConfig.model_fields.keys()
    return {
        "settings": {key: values[key] for key in keys if key in values},
        "levels": list(_LEVELS),
        "bounds": bounds,
    }


def _bound(info: Any, name: str) -> int | None:
    for item in info.metadata:
        value = getattr(item, name, None)
        if value is not None:
            return int(value)
    return None


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    """``[self_build]`` as the Settings page edits it, with each number's range."""
    return _settings_payload(getattr(_config(request), "self_build", None))


@router.put("/settings")
async def put_settings(request: Request, body: SettingsBody) -> dict[str, Any]:
    """Change ``[self_build]``: validated, written to jarvis.toml, applied now.

    The loop reads ``self.cfg`` through a getter, so replacing the in-memory
    section is the whole hot-apply. Excluded from the brain's app actions: only
    the person changes how far the loop may go (docs/self-build.md, rule 3).
    """
    from dodaios.core import config_writer
    from dodaios.core.config import SelfBuildConfig

    changes = body.model_dump(exclude_none=True)
    if "code_land_repos" in changes:
        changes["code_land_repos"] = _clean_repos(changes["code_land_repos"])
    if not changes:
        raise HTTPException(status_code=400, detail="No settings were provided.")
    cfg = _config(request)
    current = getattr(cfg, "self_build", None) or SelfBuildConfig()
    try:
        merged = SelfBuildConfig(**{**current.model_dump(), **changes})
    except Exception as exc:  # noqa: BLE001 — pydantic raises its own type
        raise HTTPException(status_code=400, detail=f"Invalid setting: {exc}") from exc
    await asyncio.to_thread(config_writer.set_self_build_settings, changes)
    if cfg is not None:
        try:
            cfg.self_build = merged
        except Exception as exc:  # noqa: BLE001 — the toml write still counts after a restart
            log.warning("self_build: in-memory settings update skipped: %s", exc)
    return _settings_payload(merged)


@router.get("/{build_id}")
async def get_build(request: Request, build_id: str) -> dict[str, Any]:
    service = _service(request)
    record = await asyncio.to_thread(service.ledger.get, build_id)
    if record is None:
        raise HTTPException(status_code=404, detail="no such build")
    history = await asyncio.to_thread(service.ledger.history, build_id)
    cost = await asyncio.to_thread(spent, record)
    return {"build": record.to_json(), "history": history, "cost": cost}


async def _act(coro: Any) -> dict[str, Any]:
    try:
        record = await coro
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such build") from exc
    except (TransitionError, NoBuilder, UndoUnavailable) as exc:
        raise HTTPException(status_code=409, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"build": record.to_json()}


@router.post("/{build_id}/accept")
async def accept(request: Request, build_id: str) -> dict[str, Any]:
    return await _act(_service(request).accept(build_id))


@router.post("/{build_id}/keep")
async def keep(request: Request, build_id: str) -> dict[str, Any]:
    return await _act(_service(request).keep(build_id))


@router.post("/{build_id}/undo")
async def undo(request: Request, build_id: str, body: NoteBody | None = None) -> dict[str, Any]:
    note = body.note if body is not None else ""
    return await _act(_service(request).undo_build(build_id, note))
