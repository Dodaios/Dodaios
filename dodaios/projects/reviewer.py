"""The periodic project review: reads evidence, writes at most one short line, never speaks.

A review needs no model for progress (it reads the jobs ledger), so it costs nothing
and never bills a key. The one model call a review can make is the criteria check when
every sub-goal is done, and that runs only on a seat background work may use
(``dodaios.brain.background_policy``). The line lands in the lead's one conversation as
a written notice, deferred during the owner's quiet hours and never repeated.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Final

from .engine import ProjectEngine, get_engine

log = logging.getLogger(__name__)

#: How often the loop looks for due reviews. Each project sets its own rhythm (daily by default).
TICK_S: Final[float] = 15 * 60
NOTICE_KIND: Final[str] = "project"

Post = Callable[[dict[str, Any]], Awaitable[bool]]
Quiet = Callable[[], Awaitable[bool]]


async def review_due(
    engine: ProjectEngine, post: Post, quiet: Quiet, *, only: list[str] | None = None
) -> list[str]:
    """Review every due project; return the lines delivered (for tests and logs)."""
    delivered: list[str] = []
    for project_id in only if only is not None else engine.due():
        try:
            result = await engine.review(project_id, background=True)
        except Exception:  # noqa: BLE001 - one broken project never stops the others
            log.warning("projects: review of %s failed", project_id, exc_info=True)
            continue
        if result.line is None:
            continue
        try:
            if await quiet():
                continue  # said later: the report fingerprint is not marked
            sent = await post(
                {
                    "kind": NOTICE_KIND,
                    "status": "done",
                    "text": result.line,
                    "project_id": project_id,
                }
            )
        except Exception:  # noqa: BLE001 - an undelivered line stays pending for the next tick
            log.info("projects: notice not delivered", exc_info=True)
            continue
        if sent:
            await engine.mark_reported(project_id, result.report_fp)
            delivered.append(result.line)
    return delivered


async def _post_to_lead(runtime: Any, payload: dict[str, Any]) -> bool:
    from dodaios.agent_chat.lead import lead_session

    service = runtime.chat_service()
    if service is None:
        return False
    session = lead_session(service, create=False)
    if session is None:
        return False
    await service.post_notice(session.session_id, payload)
    return True


async def _quiet_hours(runtime: Any) -> bool:
    """Outside the waking hours the owner set for proactive messages (none set: never quiet)."""
    from dodaios.agent_chat.proactive_settings import load_settings

    settings = await load_settings(getattr(runtime, "store", None))
    if not settings.enabled:
        return False
    try:
        from zoneinfo import ZoneInfo

        now = (
            datetime.now(ZoneInfo(settings.timezone))
            if settings.timezone
            else datetime.now().astimezone()
        )
    except Exception:  # noqa: BLE001 - an unknown zone reads as local time
        now = datetime.now().astimezone()
    return not settings.from_hour <= now.hour <= settings.to_hour


async def run_loop(runtime: Any, engine: ProjectEngine | None = None) -> None:
    """Review due projects every :data:`TICK_S` until cancelled (society runtime lifetime)."""
    engine = engine or get_engine()

    async def post(payload: dict[str, Any]) -> bool:
        return await _post_to_lead(runtime, payload)

    async def quiet() -> bool:
        return await _quiet_hours(runtime)

    while True:
        try:
            await asyncio.sleep(TICK_S)
            await review_due(engine, post, quiet)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop outlives any one failed tick
            log.warning("projects: review tick failed", exc_info=True)
