"""Lead conversation compaction that runs after a turn, not inside the next one.

The lead's one conversation grows without end. When its history nears the
model's window, older events are summarized into a checkpoint
(``society.conversation.prepare_history``). Done inside the person's turn, the
summary calls run before any answer streams, on the person's chosen model.

This module moves the work to the quiet time after ``turn_finished``: when the
events past the checkpoint exceed a share of the history budget, one background
task summarizes them and saves the checkpoint, and the next turn reads it.

Seat choice follows the background billing rule (``brain.background_policy``):
a keyless local session seat compacts on itself; a key-billed session compacts
in the background only on a connected subscription; with neither, nothing runs
here and the next user-started turn compacts as before. Compaction never
truncates what the model may read: the history budget is unchanged, only the
moment the summary is written moves.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

log = logging.getLogger(__name__)

#: Share of the history budget at which the background pass starts summarizing.
#: The turn path still compacts at 100 %, so a turn rarely meets a full history.
BACKGROUND_COMPACT_AT: Final[float] = 0.75

_running: dict[str, asyncio.Task[None]] = {}


def schedule_after_turn(svc: Any, session: Any) -> None:
    """Start the background compaction for a finished lead turn (never raises)."""
    try:
        if getattr(session, "surface", "") != "jarvis":
            return
        sid = session.session_id
        existing = _running.get(sid)
        if existing is not None and not existing.done():
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run(svc, sid), name=f"lead-compaction-{sid[:8]}")
        _running[sid] = task
        task.add_done_callback(lambda t, _sid=sid: _forget(_sid, t))
    except RuntimeError:
        return  # no running loop: nothing to schedule on


def _forget(session_id: str, task: asyncio.Task[None]) -> None:
    if _running.get(session_id) is task:
        _running.pop(session_id, None)


def _pick_seat(session: Any, brain: Any, config: Any) -> Any | None:
    """The provider that may write the summary in the background, or None."""
    from dodaios.brain import background_policy

    if background_policy.keyless_local(session.provider):
        return brain._get_brain(
            session.provider, session.model or None, scope=f"lead-compaction:{session.session_id}"
        )
    from dodaios.brain.resolver import resolve_subscription_brain

    if not background_policy.subscription_mode([session.provider]):
        return None  # key only: the next user-started turn compacts, as before
    return resolve_subscription_brain(config)


async def _run(svc: Any, session_id: str) -> None:
    from dodaios.agent_chat.lead import is_lead
    from dodaios.agent_chat.runner_brain import brain_manager
    from dodaios.agent_chat.service import session_runner
    from dodaios.society.conversation import prepare_history
    from dodaios.society.runtime import current_runtime

    try:
        session = svc.store.get_session(session_id)
        runtime = current_runtime()
        brain = brain_manager()
        if (
            session is None
            or runtime is None
            or brain is None
            or not is_lead(svc, session_id)
            or session_runner(session) != "brain"
        ):
            return
        through, _summary = await asyncio.to_thread(runtime.conversations.checkpoint, session_id)
        events = await asyncio.to_thread(svc.store.list_events, session_id, after_seq=through)
        own = brain._get_brain(
            session.provider, session.model or None, scope=f"society-compaction:{session_id}"
        )
        window = int(getattr(own, "context_window", 0) or 0) or None
        seat = await asyncio.to_thread(_pick_seat, session, brain, runtime.config())
        if seat is None:
            return
        await prepare_history(
            runtime,
            session,
            events,
            "",
            seat,
            prompt_chars=16000,
            window=window,
            compact_at=BACKGROUND_COMPACT_AT,
            compact_only=True,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the next turn compacts (or falls back) as before
        log.info("lead compaction: background pass skipped for %s: %s", session_id, exc)
