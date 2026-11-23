"""REST routes for the Self-improvement page (docs/self-improvement.md).

Endpoints (all under ``/api/self-improvement``)::

    GET  ""                      What was measured, what is in effect, what the nights did
    POST /pause                  ``{"paused": true}`` is the person's stop; ``false`` lifts it
    POST /changes/{id}/undo      Take one learned change back (the exact earlier value)

The person has exactly these two controls: stop, and undo. There is no route
that lets a change in, records a measurement or edits a result: that is the
kernel's alone.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dodaios.rsi import overview
from dodaios.rsi.night import NightService
from dodaios.self_change import OWNER, SelfChangeError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/self-improvement", tags=["self-improvement"])


class PauseBody(BaseModel):
    paused: bool


def _service(request: Request) -> NightService:
    service = getattr(request.app.state, "self_improvement", None)
    if service is None:
        raise HTTPException(status_code=503, detail="self-improvement is not running")
    return service


@router.get("")
async def get_overview(request: Request) -> dict[str, Any]:
    service = _service(request)
    return await asyncio.to_thread(overview.build, service.night)


@router.post("/pause")
async def pause(body: PauseBody, request: Request) -> dict[str, Any]:
    service = _service(request)
    await asyncio.to_thread(service.night.pause, body.paused)
    return {"ok": True, "paused": body.paused}


@router.post("/changes/{change_id}/undo")
async def undo(change_id: str, request: Request) -> dict[str, Any]:
    service = _service(request)
    registry = service.night.registry
    try:
        done = await asyncio.to_thread(registry.rollback, change_id, OWNER)
    except SelfChangeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "reverted": [change.id for change in done]}
