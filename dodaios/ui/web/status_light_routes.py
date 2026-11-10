"""The status light (``/api/status-light``): what runs and what needs the person.

One read-only summary for the top bar. It folds the work board (the same read
the lead's ``work_board`` tool does), the open jobs of the ledger, the
attention list and the seat-health verdicts, see :mod:`dodaios.core.status_light`.
It never notifies: the app reads it when the window is visible.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Request

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/status-light", tags=["status-light"])

#: Several windows asking at once share one read.
_CACHE_S = 3.0
_BOARD_TIMEOUT_S = 6.0
_cache: tuple[float, dict[str, Any]] | None = None
_lock = asyncio.Lock()


async def _board() -> dict[str, Any]:
    """The compact work board, or empty before the tools are wired."""
    from dodaios.core.protocols import ExecutionContext
    from dodaios.core.runtime_refs import get_supervisor_tool_gateway

    gateway = get_supervisor_tool_gateway()
    extra = getattr(gateway, "lead_extra_tools", None)
    tool = (extra() if callable(extra) else {}).get("work_board")
    if tool is None:
        return {}
    ctx = ExecutionContext(
        trace_id=uuid.uuid4(), user_utterance="", config={}, memory_read=None, approved_by="auto"
    )
    try:
        result = await asyncio.wait_for(tool.execute({}, ctx), timeout=_BOARD_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - the light stands on its other sources
        log.warning("status light: work board unavailable", exc_info=True)
        return {}
    return result.output if result.success and isinstance(result.output, dict) else {}


async def _attention_cards(request: Request) -> list[dict[str, Any]]:
    from .attention_routes import _attention

    try:
        return [item.to_dict() for item in await (await _attention(request)).items()]
    except Exception:  # noqa: BLE001
        log.warning("status light: attention unavailable", exc_info=True)
        return []


async def compute(request: Request) -> dict[str, Any]:
    from dodaios.brain.seat_health import get_seat_health
    from dodaios.core.status_light import build_status_light
    from dodaios.orchestrator import jobs

    board, cards = await asyncio.gather(_board(), _attention_cards(request))
    try:
        open_jobs = jobs.get_ledger().recent(limit=50, open_only=True)
    except Exception:  # noqa: BLE001
        log.warning("status light: jobs unavailable", exc_info=True)
        open_jobs = []
    try:
        seats = get_seat_health().troubled()
    except Exception:  # noqa: BLE001
        seats = []
    return build_status_light(board=board, jobs=open_jobs, attention=cards, seats=seats)


@router.get("", summary="What runs and what needs the person, for a glance")
async def status_light(request: Request) -> dict[str, Any]:
    global _cache
    async with _lock:
        now = time.monotonic()
        if _cache is not None and now - _cache[0] < _CACHE_S:
            return _cache[1]
        data = await compute(request)
        _cache = (time.monotonic(), data)
        return data
