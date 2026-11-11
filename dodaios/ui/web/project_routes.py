"""REST routes for long-horizon projects (the lead's ``project`` tool, over the same engine).

Endpoints (all under ``/api/projects``)::

    GET  ""                              Open projects (``?all=true`` adds finished ones)
    GET  /{id}                           One project, refreshed from the jobs ledger
    POST /{id}/confirm/{subgoal_id}      The owner confirms a sub-goal that asks for it
    POST /{id}/resume                    Back to active, with a fresh review and stall window
    POST /{id}/close                     ``{"outcome": "complete" | "abandon", "reason": ""}``
    GET  /metrics                        Multi-session completion rate and median duration
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dodaios.projects.engine import ProjectError, get_engine
from dodaios.projects.metrics import project_metrics

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CloseBody(BaseModel):
    outcome: Literal["complete", "abandon"] = "complete"
    reason: str = ""


def _fail(exc: ProjectError) -> HTTPException:
    return HTTPException(404 if "No such" in str(exc) else 409, str(exc))


@router.get("")
def list_projects(all: bool = False) -> dict[str, Any]:  # noqa: A002 - query name
    return {"projects": get_engine().summaries(open_only=not all)}


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    return project_metrics(get_engine().store)


@router.get("/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    try:
        return await get_engine().status(project_id)
    except ProjectError as exc:
        raise _fail(exc) from exc


@router.post("/{project_id}/confirm/{subgoal_id}")
async def confirm(project_id: str, subgoal_id: str) -> dict[str, Any]:
    engine = get_engine()
    try:
        return engine.view(await engine.confirm(project_id, subgoal_id))
    except ProjectError as exc:
        raise _fail(exc) from exc


@router.post("/{project_id}/resume")
async def resume(project_id: str) -> dict[str, Any]:
    engine = get_engine()
    try:
        return engine.view(await engine.set_status(project_id, "active"))
    except ProjectError as exc:
        raise _fail(exc) from exc


@router.post("/{project_id}/close")
async def close(project_id: str, body: CloseBody) -> dict[str, Any]:
    try:
        result = await get_engine().close(project_id, body.outcome, reason=body.reason)
    except ProjectError as exc:
        raise _fail(exc) from exc
    return result.to_dict()
