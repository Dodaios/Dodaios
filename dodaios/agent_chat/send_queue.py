"""A created agent's one chat never refuses its person while it works.

A society agent has one endless chat (MASTERPLAN §2.10). Work from Jarvis,
teammates and routines runs there too, so the person often writes while a
turn is still running. Instead of a "turn already running" refusal, the
message waits here and starts as the next turn once the agent's seat is free.

Coding threads (``agent`` surface) use the same queue for a follow-up typed
while a turn runs and cannot take it mid-turn (a CLI without steering, or a
turn about to end): it survives a page reload and starts as the next turn.
Stop pauses the queue so the halted agent does not start the next job by
itself; :func:`resume` lets it go on. A CLI that takes a message while it
works (Claude Code over stream-json) is steered instead — see :func:`try_steer`.

The queue is bounded per chat in size. Waiting for a credential or approval
never expires an accepted message. Every queued message is a
``message_queued`` notice in the chat; when it starts (or cannot be sent) a
``message_dequeued`` notice with the same ``queue_id`` replaces it, so the
timeline shows a waiting message exactly while it waits.

The queue survives a restart: the message's full payload (text, attachments,
tool picks, timezone, away flag) is saved in the chat database under its
``queue_id``, and :func:`recover_waiting` puts every message whose notice has
no matching dequeue back into the queue, in its original order. A message
older than :data:`STALE_AFTER_S` is never sent silently on a later boot: its
notice is closed with a written note so the person can send it again
(:func:`close_orphans`).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "MAX_QUEUED",
    "QueueFull",
    "STALE_AFTER_S",
    "close_orphans",
    "discard",
    "has_waiting",
    "pause",
    "queue_state",
    "recover_waiting",
    "resume",
    "send_or_queue",
    "try_steer",
]

#: Messages one chat may hold while its agent works.
MAX_QUEUED: Final[int] = 64
#: A waiting message older than this is not sent on its own after a restart.
STALE_AFTER_S: Final[float] = 24 * 3600.0
#: How often a waiting chat checks whether its agent is free (seconds).
_POLL_S: Final[float] = 0.5
#: Shown in the chat for a message that never started; never provider text (AP-34).
_NOT_SENT: Final[str] = "The waiting message could not be sent. Please send it again."


class QueueFull(RuntimeError):
    """The chat already holds :data:`MAX_QUEUED` waiting messages."""


@dataclass(slots=True)
class _Queued:
    queue_id: str
    text: str
    attachments: list[dict[str, Any]] | None
    tool_choices: list[str] | None
    timezone: str | None = None
    #: Written away from the desk (Telegram, Discord, WhatsApp): the drain loop
    #: sets it around the send, so the screen context follows the message and
    #: not whoever queued first.
    away: bool = False


@dataclass(slots=True)
class _ChatQueue:
    items: deque[_Queued] = field(default_factory=deque)
    drain: asyncio.Task[None] | None = None
    starting: bool = False
    #: Stop was pressed: nothing starts until :func:`resume`.
    paused: bool = False


def _display_text(text: str, attachments: list[dict[str, Any]] | None) -> str:
    return text.strip() or ", ".join(str(item.get("name", "")) for item in attachments or [])


def _queues(svc: Any) -> dict[str, _ChatQueue]:
    queues = getattr(svc, "_society_send_queues", None)
    if queues is None:
        queues = {}
        svc._society_send_queues = queues
    return queues


def has_waiting(svc: Any, session_id: str) -> bool:
    """Whether a message of the person is waiting for this chat's seat."""
    pending = getattr(svc, "_society_send_queues", {}).get(session_id)
    return bool(pending is not None and (pending.items or pending.starting))


def _queueable(svc: Any, session_id: str) -> bool:
    """User chats queue; automated routine and teammate threads stay exclusive."""
    from dodaios.society.roster import PAIR_SESSION_MARKER
    from dodaios.society.routine_runner import is_routine_session

    session = svc.store.get_session(session_id)
    if session is None or getattr(session, "surface", "") not in ("jarvis", "society", "agent"):
        return False
    if is_routine_session(session_id) or PAIR_SESSION_MARKER in session_id:
        return False
    return True


async def _notice(svc: Any, session_id: str, payload: dict[str, Any]) -> None:
    post = getattr(svc, "post_notice", None)
    if post is None:
        return
    try:
        await post(session_id, payload)
    except Exception:  # noqa: BLE001 — the queue still runs; the notice is a projection
        log.warning("agent chat: queue notice not posted for %s", session_id, exc_info=True)


def _save(svc: Any, session_id: str, item: _Queued) -> None:
    """Keep the payload so a restart can re-enqueue the message."""
    save = getattr(getattr(svc, "store", None), "save_queued_message", None)
    if save is None:
        return
    try:
        save(
            item.queue_id,
            session_id,
            {
                "text": item.text,
                "attachments": item.attachments,
                "tool_choices": item.tool_choices,
                "timezone": item.timezone,
                "away": item.away,
            },
        )
    except Exception:  # noqa: BLE001 - the message still queues; only its durability is lost
        log.warning("agent chat: queued message %s not saved", item.queue_id, exc_info=True)


def _forget(svc: Any, queue_id: str) -> None:
    forget = getattr(getattr(svc, "store", None), "delete_queued_message", None)
    if forget is None:
        return
    try:
        forget(queue_id)
    except Exception:  # noqa: BLE001 - a stale row is harmless: its notice is closed
        log.warning("agent chat: queued message %s not forgotten", queue_id, exc_info=True)


async def try_steer(
    svc: Any,
    session_id: str,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    *,
    tool_choices: list[str] | None = None,
) -> bool:
    """Hand a message to the running turn's CLI; False when it must queue or start instead.

    Only a coding thread whose running turn can take a message does this, and
    only a plain-text one: files and tool picks travel with a new turn. Messages
    already waiting keep their place, so a steer never overtakes them.
    """
    session = svc.store.get_session(session_id)
    if session is None or getattr(session, "surface", "") != "agent":
        return False
    if attachments or tool_choices or not text.strip():
        return False
    if has_waiting(svc, session_id) or not svc.is_running(session_id):
        return False
    steer = getattr(svc, "steer", None)
    return bool(steer is not None and await steer(session_id, text))


def pause(svc: Any, session_id: str) -> None:
    """Stop was pressed: waiting messages stay until the person releases them."""
    pending = getattr(svc, "_society_send_queues", {}).get(session_id)
    if pending is not None and pending.items:
        pending.paused = True


def resume(svc: Any, session_id: str) -> None:
    pending = getattr(svc, "_society_send_queues", {}).get(session_id)
    if pending is not None:
        pending.paused = False


def queue_state(svc: Any, session_id: str) -> dict[str, Any]:
    """What waits for this chat: ``{"paused", "items": [{queue_id, text}]}``."""
    pending = getattr(svc, "_society_send_queues", {}).get(session_id)
    if pending is None:
        return {"paused": False, "items": []}
    return {
        "paused": pending.paused,
        "items": [
            {"queue_id": item.queue_id, "text": _display_text(item.text, item.attachments)}
            for item in pending.items
        ],
    }


async def discard(svc: Any, session_id: str, queue_id: str) -> bool:
    """Take one waiting message back; False when it already started or is gone."""
    pending = getattr(svc, "_society_send_queues", {}).get(session_id)
    if pending is None:
        return False
    for item in list(pending.items):
        if item.queue_id == queue_id:
            pending.items.remove(item)
            _forget(svc, queue_id)
            await _notice(
                svc,
                session_id,
                {"kind": "message_dequeued", "queue_id": queue_id, "status": "removed"},
            )
            return True
    return False


async def send_or_queue(
    svc: Any,
    session_id: str,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    *,
    tool_choices: list[str] | None = None,
) -> tuple[str, str]:
    """Send now, or queue behind the running turn: ``(turn_id, queue_id)``.

    Exactly one of the two is non-empty. Raises ``SessionBusy`` for a chat
    that does not queue and :class:`QueueFull` when the queue is full.
    """
    from dodaios.agent_chat.screen_reference import is_away
    from dodaios.agent_chat.service import SessionBusy
    from dodaios.tasks.context import client_timezone

    queues = _queues(svc)
    if not _queueable(svc, session_id):
        return await svc.send(session_id, text, attachments, tool_choices=tool_choices), ""
    pending = queues.setdefault(session_id, _ChatQueue())
    first = False
    released = False
    release = getattr(svc, "release_waiting_turn", None)
    if (
        release is not None
        and svc.is_running(session_id)
        and not pending.items
        and not pending.starting
    ):
        # A turn that only waits for agents hands its seat over; one that is
        # still answering keeps it and this message queues behind it. Admission
        # is reserved first, so a message arriving meanwhile queues behind this
        # one and a finished background result does not take the seat.
        pending.starting = True
        try:
            released = await release(session_id)
        finally:
            pending.starting = False
    if (released or not pending.items) and not pending.starting and not svc.is_running(
        session_id
    ):
        # Reserve admission before setup yields. Later HTTP requests must not
        # overtake this message, even before the service reserves its seat.
        pending.starting = True
        try:
            turn_id = await svc.send(session_id, text, attachments, tool_choices=tool_choices)
        except SessionBusy:  # The expected occupied seat becomes a visible queued message below.
            first = True
        else:
            return turn_id, ""
        finally:
            pending.starting = False
            if not pending.items and not first and queues.get(session_id) is pending:
                queues.pop(session_id, None)
    # Earlier waiting messages go first, so a new one never overtakes them.
    if len(pending.items) >= MAX_QUEUED and not first:
        raise QueueFull(session_id)
    item = _Queued(
        uuid.uuid4().hex, text, attachments, tool_choices, client_timezone.get(), is_away()
    )
    # Recovery reads persisted notices off-thread. A generation fence detects
    # an admission that both starts and finishes while that snapshot is read.
    svc._society_send_generation = getattr(svc, "_society_send_generation", 0) + 1
    if first:
        pending.items.appendleft(item)
    else:
        pending.items.append(item)
    _save(svc, session_id, item)
    await _notice(
        svc,
        session_id,
        {"kind": "message_queued", "queue_id": item.queue_id,
         "text": _display_text(text, attachments)},
    )
    if pending.drain is None or pending.drain.done():
        pending.drain = asyncio.create_task(
            _drain(svc, session_id, pending), name=f"chat-queue-{session_id[-24:]}"
        )
    return "", item.queue_id


async def _drain(svc: Any, session_id: str, pending: _ChatQueue) -> None:
    """Start each waiting message as soon as the agent's seat is free."""
    try:
        await _drain_loop(svc, session_id, pending)
    finally:
        queues = _queues(svc)
        if not pending.items and not pending.starting and queues.get(session_id) is pending:
            queues.pop(session_id, None)


async def _fail(svc: Any, session_id: str, item: _Queued) -> None:
    _forget(svc, item.queue_id)
    await _notice(
        svc,
        session_id,
        {"kind": "message_dequeued", "queue_id": item.queue_id, "status": "failed",
         "text": _display_text(item.text, item.attachments) or _NOT_SENT},
    )


async def _drain_loop(svc: Any, session_id: str, pending: _ChatQueue) -> None:
    from dodaios.agent_chat.screen_reference import away_from_screen
    from dodaios.agent_chat.service import SessionBusy
    from dodaios.tasks.context import client_timezone

    while pending.items:
        # Jitter only spreads polls of several waiting chats; it is not security.
        await asyncio.sleep(_POLL_S + random.uniform(0, _POLL_S / 2))  # noqa: S311
        if pending.starting or pending.paused or svc.is_running(session_id):
            continue
        if not pending.items:  # taken back while waiting
            break
        head = pending.items[0]
        token = client_timezone.set(head.timezone)
        try:
            with away_from_screen(head.away):
                turn_id = await svc.send(
                    session_id, head.text, head.attachments, tool_choices=head.tool_choices
                )
        except SessionBusy:  # the seat is still taken: this message simply waits longer
            continue
        except Exception:  # noqa: BLE001 — reported in the chat, then the next one runs
            # The detail stays in the log; a provider's text never reaches the chat.
            log.warning("agent chat: queued message for %s failed", session_id, exc_info=True)
            pending.items.popleft()
            await _fail(svc, session_id, head)
            continue
        finally:
            client_timezone.reset(token)
        pending.items.popleft()
        _forget(svc, head.queue_id)
        await _notice(
            svc,
            session_id,
            {"kind": "message_dequeued", "queue_id": head.queue_id, "status": "sent",
             "turn_id": str(turn_id or "")},
        )


async def recover_waiting(svc: Any) -> int:
    """After a restart: put every chat's waiting messages back in its queue.

    Runs once when the chat service is built. Returns how many messages were
    queued again. A chat that cannot be read is skipped and recovers when it is
    next opened (:func:`close_orphans`).
    """
    listing = getattr(getattr(svc, "store", None), "sessions_with_waiting_messages", None)
    if listing is None:
        return 0
    try:
        sessions = await asyncio.to_thread(listing)
    except Exception:  # noqa: BLE001 - the chats recover one by one when they are opened
        log.warning("agent chat: waiting messages could not be listed", exc_info=True)
        return 0
    restored = 0
    for session_id in sessions:
        try:
            restored += (await _recover(svc, session_id))[1]
        except Exception:  # noqa: BLE001 - one broken chat must not stop the others
            log.warning("agent chat: recovery of %s failed", session_id, exc_info=True)
    return restored


async def close_orphans(svc: Any, session_id: str) -> int:
    """Recover a chat's waiting messages after a restart; close what cannot be.

    A message with a saved payload that is not stale goes back in the queue.
    The others (older than :data:`STALE_AFTER_S`, or saved by an older build
    without a payload) get a closing notice. Returns how many were closed.
    Messages still queued in this process are left alone.
    """
    return (await _recover(svc, session_id))[0]


async def _recover(svc: Any, session_id: str) -> tuple[int, int]:
    """``(closed, restored)`` for one chat; one recovery at a time."""
    lock = getattr(svc, "_society_queue_recovery_lock", None)
    if lock is None:
        lock = svc._society_queue_recovery_lock = asyncio.Lock()
    async with lock:
        return await _close_orphans_locked(svc, session_id)


async def _close_orphans_locked(svc: Any, session_id: str) -> tuple[int, int]:
    """One recovery at a time prevents duplicate receipts from GET/WS reopens."""
    live: set[str] = set()
    for _attempt in range(2):
        generation = getattr(svc, "_society_send_generation", 0)
        pending = _queues(svc).get(session_id)
        if pending is not None:
            live.update(item.queue_id for item in pending.items)
        try:
            events = await asyncio.to_thread(svc.store.queue_notice_events, session_id)
        except Exception:  # noqa: BLE001 — a chat that cannot be read keeps its notices
            log.warning("agent chat: waiting notices of %s not checked", session_id, exc_info=True)
            return 0, 0
        if generation == getattr(svc, "_society_send_generation", 0):
            break
    else:
        # A busy process can postpone recovery until the next open/reconnect;
        # it must never overwrite a live message's successful sent receipt.
        return 0, 0
    waiting: dict[str, str] = {}
    for event in events:
        payload = event.get("payload") or {}
        if event.get("kind") != "notice":
            continue
        queue_id = str(payload.get("queue_id") or "")
        if payload.get("kind") == "message_queued" and queue_id:
            waiting[queue_id] = str(payload.get("text") or _NOT_SENT)
        elif payload.get("kind") == "message_dequeued":
            waiting.pop(queue_id, None)
    closed = 0
    restored = 0
    now_s = time.time()
    saved_of = getattr(svc.store, "queued_message", None)
    for queue_id, text in waiting.items():
        # An admission may have arrived while the history read yielded. Keep
        # both snapshots so a live message that just started also stays safe.
        current = _queues(svc).get(session_id)
        if current is not None:
            live.update(item.queue_id for item in current.items)
        if queue_id in live:
            continue
        saved = None
        if saved_of is not None:
            try:
                saved = await asyncio.to_thread(saved_of, queue_id)
            except Exception:  # noqa: BLE001 - unreadable payload: the message is closed below
                log.warning("agent chat: saved message %s unreadable", queue_id, exc_info=True)
        stale = saved is not None and now_s - saved["queued_ms"] / 1000 > STALE_AFTER_S
        if saved is not None and not stale:
            _requeue(svc, session_id, queue_id, saved)
            live.add(queue_id)
            restored += 1
            continue
        _forget(svc, queue_id)
        payload: dict[str, Any] = {
            "kind": "message_dequeued", "queue_id": queue_id, "status": "failed", "text": text,
        }
        if stale:
            # Written, never silent: the person decides whether it still applies.
            payload["reason"] = "stale_after_restart"
        await _notice(svc, session_id, payload)
        closed += 1
    return closed, restored


def _requeue(svc: Any, session_id: str, queue_id: str, saved: dict[str, Any]) -> None:
    """Put a message saved before a restart back at the end of its chat's queue."""
    attachments = saved.get("attachments")
    tool_choices = saved.get("tool_choices")
    item = _Queued(
        queue_id,
        str(saved.get("text") or ""),
        attachments if isinstance(attachments, list) else None,
        tool_choices if isinstance(tool_choices, list) else None,
        saved.get("timezone") if isinstance(saved.get("timezone"), str) else None,
        bool(saved.get("away")),
    )
    pending = _queues(svc).setdefault(session_id, _ChatQueue())
    svc._society_send_generation = getattr(svc, "_society_send_generation", 0) + 1
    pending.items.append(item)
    if pending.drain is None or pending.drain.done():
        pending.drain = asyncio.create_task(
            _drain(svc, session_id, pending), name=f"chat-queue-{session_id[-24:]}"
        )
