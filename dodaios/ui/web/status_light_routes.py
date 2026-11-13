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
        cards = [item.to_dict() for item in await (await _attention(request)).items()]
    except Exception:  # noqa: BLE001
        log.warning("status light: attention unavailable", exc_info=True)
        return []
    names = _agent_names() if cards else {}
    return [
        {**card, "agent_name": names.get(str(card.get("agent_id") or ""), "")} for card in cards
    ]


def _agent_names() -> dict[str, str]:
    """Every agent's name as the person knows it, so a card can say who asks."""
    from dodaios.society.runtime import current_runtime

    try:
        runtime = current_runtime()
        if runtime is None:
            return {}
        from dodaios.society.display_name import display_name

        return {a.agent_id: display_name(a) for a in runtime.roster.snapshot()}
    except Exception:  # noqa: BLE001 - a card without a name still shows
        log.warning("status light: agent names unavailable", exc_info=True)
        return {}


def _name_coding_agents(light: dict[str, Any]) -> dict[str, Any]:
    """Put each coding CLI's product name beside its id ("claude" -> "Claude Code")."""
    from dodaios.workspace.agents import get_agent

    for row in (*light["needs_you"], *light["running"]):
        if row.get("kind") != "pane" or not row.get("agent"):
            continue
        try:
            spec = get_agent(str(row["agent"]))
        except Exception:  # noqa: BLE001 - the id stands in for the name
            spec = None
        row["agent_label"] = spec.display_name if spec is not None else str(row["agent"])
    return light


def _name_seats(light: dict[str, Any]) -> dict[str, Any]:
    """Put a troubled provider's readable name beside its id."""
    from dodaios.ui.web.provider_spec import get_spec

    for seat in light["trouble"]:
        try:
            spec = get_spec(str(seat.get("provider") or ""))
        except Exception:  # noqa: BLE001 - the id stands in for the name
            spec = None
        if spec is not None:
            seat["label"] = spec.label
    return light


def _findings() -> list[dict[str, Any]]:
    """The running watchdog's open findings; none while it is not running."""
    from dodaios.orchestrator.watchdog import supervisor

    try:
        running = supervisor.current()
        found = list(running.store.open_findings(25)) if running is not None else []
    except Exception:  # noqa: BLE001
        log.warning("status light: watchdog findings unavailable", exc_info=True)
        return []
    return [_with_provider_label(f) for f in found]


def _with_provider_label(finding: dict[str, Any]) -> dict[str, Any]:
    """Put the provider's readable name beside its id, so a row never shows a raw id."""
    from dodaios.ui.web.provider_spec import get_spec

    evidence = finding.get("evidence")
    if not isinstance(evidence, dict) or not evidence.get("provider"):
        return finding
    spec = get_spec(str(evidence["provider"]))
    if spec is None:
        return finding
    return {**finding, "evidence": {**evidence, "provider_label": spec.label}}


async def _prepared() -> list[dict[str, Any]]:
    """Drafts and fixes made in advance that wait for the person (a count, never a push)."""
    from dodaios.lead_triggers import wiring

    service = wiring.get_service()
    if service is None or service.preparer is None:
        return []
    try:
        return [i.to_dict() for i in await service.preparer.waiting()]
    except Exception:  # noqa: BLE001 - the light stands on its other sources
        log.warning("status light: prepared items unavailable", exc_info=True)
        return []


def _browsers() -> list[dict[str, Any]]:
    """The agents' live browsers that run a task or wait for the person to take over."""
    from dodaios.society.runtime import current_runtime

    try:
        runtime = current_runtime()
        sessions = list(runtime.browser.live.sessions.values()) if runtime is not None else []
        from dodaios.society.display_name import display_name

        names = {a.agent_id: display_name(a) for a in runtime.roster.snapshot()} if sessions else {}
        rows = []
        for session in sessions:
            request = session.takeover.request
            running = session.run_lock.locked()
            if request is None and not running:
                continue
            rows.append(
                {
                    "agent_id": session.agent_id,
                    "running": running,
                    "request_id": (request or {}).get("id", ""),
                    "reason": (request or {}).get("reason", ""),
                    "title": names.get(session.agent_id, ""),
                }
            )
        return rows
    except Exception:  # noqa: BLE001 - the light stands on its other sources
        log.warning("status light: browsers unavailable", exc_info=True)
        return []


async def compute(request: Request) -> dict[str, Any]:
    from dodaios.brain.seat_health import get_seat_health
    from dodaios.core.status_light import build_status_light
    from dodaios.orchestrator import jobs

    board, cards, prepared = await asyncio.gather(_board(), _attention_cards(request), _prepared())
    try:
        open_jobs = jobs.get_ledger().recent(limit=50, open_only=True)
    except Exception:  # noqa: BLE001
        log.warning("status light: jobs unavailable", exc_info=True)
        open_jobs = []
    try:
        seats = get_seat_health().troubled()
    except Exception:  # noqa: BLE001
        log.warning("status light: seat health unavailable", exc_info=True)
        seats = []
    light = build_status_light(
        board=board,
        jobs=open_jobs,
        attention=cards,
        seats=seats,
        findings=_findings(),
        prepared=prepared,
        browsers=_browsers(),
    )
    return _name_seats(_name_coding_agents(light))


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
