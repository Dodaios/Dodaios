"""REST routes for the self-change list ("What I changed in myself", Trust page).

Endpoints (all under ``/api/self-change``)::

    GET  ""                   Every recorded self-change, newest first, plus the counts
    GET  /{id}                One change with its diff, history and regression results
    POST /{id}/approve        The owner lets a waiting change go live
    POST /{id}/reject         The owner refuses a waiting change
    POST /{id}/keep           Keep a change that is on trial
    POST /{id}/rollback       Restore the exact text from before the change
    POST /rollback-since      ``{"since_ms": n}`` reverts every change still in effect since n

There is no route that records a change, writes a regression result or edits the
audit: the agent proposes through the skill and self-build paths, the owner
decides here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dodaios.self_change import SelfChangeError, SelfChangeRegistry
from dodaios.self_change import current as current_registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/self-change", tags=["self-change"])


class SinceBody(BaseModel):
    since_ms: int


def _registry(request: Request) -> SelfChangeRegistry:
    registry = getattr(request.app.state, "self_change", None) or current_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="the self-change registry is not running")
    return registry


async def _run(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except SelfChangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
async def list_changes(request: Request) -> dict[str, Any]:
    registry = _registry(request)
    return {
        "changes": await asyncio.to_thread(registry.list),
        "summary": await asyncio.to_thread(registry.summary),
    }


@router.post("/rollback-since")
async def rollback_since(body: SinceBody, request: Request) -> dict[str, Any]:
    done = await _run(_registry(request).rollback_since, body.since_ms)
    return {"ok": True, "reverted": [c.public() for c in done]}


@router.get("/{change_id}")
async def get_change(change_id: str, request: Request) -> dict[str, Any]:
    return await _run(_registry(request).detail, change_id)


@router.post("/{change_id}/approve")
async def approve(change_id: str, request: Request) -> dict[str, Any]:
    return {"ok": True, "change": (await _run(_registry(request).approve, change_id)).public()}


@router.post("/{change_id}/reject")
async def reject(change_id: str, request: Request) -> dict[str, Any]:
    return {"ok": True, "change": (await _run(_registry(request).reject, change_id)).public()}


@router.post("/{change_id}/keep")
async def keep(change_id: str, request: Request) -> dict[str, Any]:
    return {"ok": True, "change": (await _run(_registry(request).promote, change_id)).public()}


@router.post("/{change_id}/rollback")
async def rollback(change_id: str, request: Request) -> dict[str, Any]:
    done = await _run(_registry(request).rollback, change_id)
    return {"ok": True, "reverted": [c.public() for c in done]}
