"""Owed results for a live call on an install without a speech pipeline.

A finished agent, a watched pane or a late answer is published as an
``AnnouncementRequested``. On the desktop the speech pipeline hands it to the
live call. A headless or browser-only install has no speech pipeline, so the
result had nowhere to go and the call never heard it. This bridge delivers
it there, and stays out of the way wherever a speech pipeline runs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from dodaios.core.events import AnnouncementRequested

log = logging.getLogger(__name__)

#: Kinds that carry an outcome the user is owed. Preambles and progress lines
#: belong to a turn the live model is speaking itself.
_OWED_KINDS: Final[frozenset[str]] = frozenset({"completion", "subagent"})
#: A call refuses a report while a turn is in flight; it is offered again at
#: this pace until the call takes it or ends.
RETRY_S: Final[float] = 2.0
ATTEMPTS: Final[int] = 90

_pending: set[asyncio.Task] = set()


def _owed(event: AnnouncementRequested) -> bool:
    return event.kind in _OWED_KINDS or bool(str(event.report or "").strip())


def _live_call() -> Any | None:
    from dodaios.live.runtime import active

    return next((s for s in active() if getattr(s, "is_active", False)), None)


async def deliver_to_live_call(event: AnnouncementRequested) -> None:
    """Bus subscriber: hand an owed result to the live call when nothing else will."""
    from dodaios.core.runtime_refs import get_speech_pipeline

    if get_speech_pipeline() is not None or not _owed(event) or _live_call() is None:
        return
    task = asyncio.create_task(_hand_over(event), name="live-call-result")
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _hand_over(event: AnnouncementRequested) -> bool:
    from dodaios.brain.output_filter import scrub_for_voice
    from dodaios.live.runtime import on_session_loop

    language = str(event.language or "")
    text = scrub_for_voice(str(event.text or ""), language=language).cleaned
    report = str(event.report or "").strip()
    extra: dict[str, Any] = {"report": report} if report else {}
    for _ in range(ATTEMPTS):
        session = _live_call()
        if session is None:
            return False

        async def offer(target: Any = session) -> bool:
            return bool(await target.deliver_announcement(
                text=text, language=language, spoken_kind=event.kind or "announcement",
                detail=event.detail, **extra,
            ))

        try:
            if await on_session_loop(session, offer):
                return True
        except RuntimeError:  # the call ended or changed meanwhile: look again
            log.debug("live-call result: the call changed before delivery")
        except Exception:  # noqa: BLE001 - a failed handoff must not end the retries
            log.warning("live-call result: delivery failed", exc_info=True)
        await asyncio.sleep(RETRY_S)
    log.warning("live-call result: the call never took %r", text[:80])
    return False


__all__ = ["ATTEMPTS", "RETRY_S", "deliver_to_live_call"]
