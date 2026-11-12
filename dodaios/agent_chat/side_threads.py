"""Side threads: the conversation keeps answering while a request is still worked on.

The person writes to Dodaios, and while that request is still being answered
they write again. The second message used to wait behind the first
(``send_queue``). On the lead's one conversation it is now answered at once,
in a **side thread**: a chat session of its own, on the conversation's seat,
that runs beside the turn in the main thread. For the person it stays one
chat: their message, then its answer, while the earlier answer goes on above.

* The side thread is an ordinary ``jarvis`` session. Its row in
  ``agent_chat_side_threads`` names the conversation it belongs to and keeps it
  out of every chat list. It has the conversation's seat, folder, stance and
  "always allow" choices.
* It does not share the main thread's context window. It starts on a brief
  (:func:`context_note`): the conversation's summary, its recent messages and
  the instruction to answer only this message.
* The conversation's timeline shows it through two notices:
  ``side_thread_started`` (the person's message) and ``side_thread_finished``
  (how it ended, with the answer). The second one is also what the lead's
  later turns read (:func:`replay`), so the lead knows what was asked and
  answered beside it, on every seat.
* Turns that start in the main thread while side threads still run are told
  so (:func:`running_note`).
* A message that belongs to the running request can be moved into the main
  thread (:func:`move_to_main`): the side thread stops and the message starts
  as the next turn there, with that request's context.

A side thread dies with the process (a ``jarvis`` turn is the app's child):
:func:`recover` closes the ones a previous run left open as ``interrupted``.
No model call is added: the side thread's turn is the turn the queued message
would have run later.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "FINISHED",
    "MAX_RUNNING",
    "STARTED",
    "context_note",
    "is_side_thread",
    "move_to_main",
    "parent_of",
    "recover",
    "replay",
    "running_note",
    "speaks_as_lead",
    "start",
    "stop",
    "takes",
]

#: Notice kinds in the conversation's timeline. Mirrored in
#: ``components/agentchat/reduce.ts`` (parity-tested).
STARTED: Final[str] = "side_thread_started"
FINISHED: Final[str] = "side_thread_finished"
#: Side threads one conversation runs at once; a further message queues as before.
MAX_RUNNING: Final[int] = 4
#: How much of an answer the closing notice carries (the side thread keeps all of it).
ANSWER_CHARS: Final[int] = 16_000
#: Bounds of the brief a side thread starts on.
_SUMMARY_CHARS: Final[int] = 4_000
_TRANSCRIPT_CHARS: Final[int] = 9_000
_TAIL_EVENTS: Final[int] = 400
_REQUEST_CHARS: Final[int] = 400


@dataclass(slots=True)
class _Side:
    """A running side thread: what a move back into the main thread needs."""

    parent: str
    text: str
    attachments: list[dict[str, Any]] | None
    tool_choices: list[str] | None
    brief: str
    started: float
    watcher: asyncio.Task[None] | None = None


def _live(svc: Any) -> dict[str, _Side]:
    live = getattr(svc, "_side_threads", None)
    if live is None:
        live = svc._side_threads = {}
    return live


def _short(text: str, limit: int = _REQUEST_CHARS) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _display(text: str, attachments: list[dict[str, Any]] | None) -> str:
    return text.strip() or ", ".join(str(item.get("name", "")) for item in attachments or [])


def parent_of(svc: Any, session_id: str) -> str:
    """The conversation ``session_id`` is a side thread of; ``""`` for a chat of its own."""
    read = getattr(getattr(svc, "store", None), "side_thread", None)
    if not callable(read) or not session_id:
        return ""
    try:
        row = read(session_id)
    except Exception:  # noqa: BLE001 - an unreadable row: treat as a chat of its own
        log.debug("side thread: row of %s not read", session_id, exc_info=True)
        return ""
    return str(row["parent_session"]) if row else ""


def is_side_thread(svc: Any, session_id: str) -> bool:
    return bool(parent_of(svc, session_id))


def speaks_as_lead(svc: Any, session_id: str) -> bool:
    """Whether a turn of ``session_id`` is the lead answering its person.

    The lead's conversation, and a side thread of it: the person reads both as
    the same assistant, so both get the lead's doctrine and turn contract.
    """
    from dodaios.agent_chat.lead import is_lead

    if is_lead(svc, session_id):
        return True
    parent = parent_of(svc, session_id)
    return bool(parent) and is_lead(svc, parent)


def _running_rows(svc: Any, parent_id: str) -> list[dict[str, Any]]:
    read = getattr(getattr(svc, "store", None), "side_threads", None)
    if not callable(read):
        return []
    try:
        return list(read(parent_id, running=True))
    except Exception:  # noqa: BLE001 - no rows is a usable answer
        log.debug("side thread: rows of %s not read", parent_id, exc_info=True)
        return []


def takes(svc: Any, session_id: str) -> bool:
    """Whether a message sent to ``session_id`` now would start a side thread.

    Only the lead's conversation, only while its turn runs, not during an
    active goal, and only below :data:`MAX_RUNNING`. The caller first lets a
    turn that merely waits hand its seat over (``release_waiting_turn``): that
    message is answered in the main thread, as before.
    """
    from dodaios.agent_chat.lead import is_lead

    if not is_lead(svc, session_id) or not svc.is_running(session_id):
        return False
    controls = getattr(svc, "_controls", None)
    try:
        goal = controls.state(session_id).goal if controls is not None else None
    except Exception:  # noqa: BLE001 - no control state: an ordinary chat
        goal = None
    if goal is not None and getattr(goal, "status", "") == "active":
        # A message during an active goal steers that goal (service.send).
        return False
    return len(_running_rows(svc, session_id)) < MAX_RUNNING


async def start(
    svc: Any,
    parent_id: str,
    text: str,
    attachments: list[dict[str, Any]] | None = None,
    *,
    tool_choices: list[str] | None = None,
) -> str:
    """Answer ``text`` beside the running turn of ``parent_id``; returns the side thread's id.

    Raises what ``send`` raises (an empty message, an unknown tool pick); then
    nothing of the side thread is left behind.
    """
    from dodaios.agent_chat.service import NoSuchSession

    parent = svc.store.get_session(parent_id)
    if parent is None:
        raise NoSuchSession(parent_id)
    display = _display(text, attachments)
    side = svc.store.create_session(
        provider=parent.provider,
        model=parent.model,
        effort=parent.effort,
        speed=getattr(parent, "speed", ""),
        cwd=parent.cwd,
        permission_mode=parent.permission_mode,
        title=_short(display, 80),
        surface=parent.surface,
        account_id=getattr(parent, "account_id", ""),
        runtime=getattr(parent, "runtime", ""),
    )
    side_id = side.session_id
    svc.store.save_side_thread(side_id, parent_id, _short(display))
    # One memory of "always allow" for the conversation and its side threads.
    allowed = getattr(svc, "_always_allowed", None)
    if isinstance(allowed, dict):
        allowed[side_id] = svc.always_allowed(parent_id)
    brief = await asyncio.to_thread(_brief, svc, parent_id)
    entry = _Side(parent_id, text, attachments, tool_choices, brief, time.monotonic())
    _live(svc)[side_id] = entry
    try:
        turn_id = await svc.send(side_id, text, attachments, tool_choices=tool_choices)
    except BaseException:
        _live(svc).pop(side_id, None)
        _forget_allowed(svc, side_id)
        svc.store.delete_session(side_id)
        raise
    await svc.post_notice(parent_id, {"kind": STARTED, "side_id": side_id, "text": display})
    entry.watcher = asyncio.create_task(
        _watch(svc, side_id, turn_id), name=f"side-thread-{side_id[-12:]}"
    )
    return side_id


def _forget_allowed(svc: Any, side_id: str) -> None:
    allowed = getattr(svc, "_always_allowed", None)
    if isinstance(allowed, dict):
        allowed.pop(side_id, None)


async def _watch(svc: Any, side_id: str, turn_id: str) -> None:
    """Post the closing notice when the side thread's turn has ended."""
    try:
        # ``send`` returned with the turn's task running; a turn that already
        # ended has left the seat and is closed right away.
        run = getattr(svc, "_running", {}).get(side_id)
        task = getattr(run, "task", None)
        if task is not None and getattr(run, "turn_id", turn_id) == turn_id:
            await asyncio.wait({task})
        await _close(svc, side_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - the side thread's own events stay readable
        log.warning("side thread %s: closing notice failed", side_id, exc_info=True)


def _outcome(events: list[dict[str, Any]]) -> tuple[str, str, str]:
    """``(status, answer, error)`` of a side thread, read from its own log.

    The answer is what the turn said after its last tool call; a turn that
    only spoke between calls gives everything it said.
    """
    status, error = "interrupted", ""
    closing: list[str] = []
    said: list[str] = []
    for event in events:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if payload.get("agent_id"):
            continue  # a sub-agent's own conversation is not the answer
        if kind == "tool_call":
            closing = []
        elif kind == "assistant_text":
            text = str(payload.get("text") or "").strip()
            if text:
                closing.append(text)
                said.append(text)
        elif kind == "turn_finished":
            raw = str(payload.get("status") or "")
            status = {"done": "done", "cancelled": "stopped"}.get(raw, "failed")
            error = str(payload.get("error") or "")
    answer = "\n\n".join(closing or said)
    return status, answer, error


async def _close(svc: Any, side_id: str, status: str = "") -> bool:
    """End a side thread once: the row, then the notice in its conversation."""
    row = svc.store.side_thread(side_id)
    if row is None or row["status"] != "running":
        return False
    events = await asyncio.to_thread(svc.store.list_events, side_id)
    read_status, answer, error = _outcome(events)
    final = status or read_status
    if not svc.store.close_side_thread(side_id, final):
        return False
    entry = _live(svc).pop(side_id, None)
    _forget_allowed(svc, side_id)
    payload: dict[str, Any] = {
        "kind": FINISHED,
        "side_id": side_id,
        "status": final,
        "text": row["request"],
    }
    if final != "moved":
        if answer:
            payload["answer"] = answer[:ANSWER_CHARS]
            payload["truncated"] = len(answer) > ANSWER_CHARS
        if error and final == "failed":
            payload["error"] = error[:600]
    if entry is not None:
        payload["duration_ms"] = int((time.monotonic() - entry.started) * 1000)
    await svc.post_notice(row["parent_session"], payload)
    return True


async def stop(svc: Any, parent_id: str, side_id: str) -> bool:
    """Stop one side thread; the main thread and the other side threads go on."""
    if parent_of(svc, side_id) != parent_id:
        return False
    if svc.is_running(side_id):
        await svc.cancel(side_id)
        entry = _live(svc).get(side_id)
        if entry is not None and entry.watcher is not None:
            # The watcher posts the notice; wait so the caller reads the end state.
            await asyncio.wait({entry.watcher}, timeout=5.0)
    return await _close(svc, side_id, "stopped") or True


async def move_to_main(svc: Any, parent_id: str, side_id: str) -> str:
    """The message belongs to the running request: ``queued``, ``sent`` or ``""``.

    The side thread stops without an answer and its message goes into the
    main thread, where it starts as the next turn: right after the running
    request, with that request's whole context (``sent`` when the main thread
    is free by now). It is not written into the running turn: a seat that is
    in the middle of an answer reads such a message only after that answer,
    as a turn of its own that the chat would not show. ``""`` when the side
    thread already ended or is not this conversation's.
    """
    from dodaios.agent_chat.send_queue import send_or_queue

    entry = _live(svc).get(side_id)
    if entry is None or entry.parent != parent_id:
        return ""
    # Closed first, so the stop below is not reported as a stopped answer.
    if not svc.store.close_side_thread(side_id, "moved"):
        return ""
    _live(svc).pop(side_id, None)
    _forget_allowed(svc, side_id)
    if svc.is_running(side_id):
        await svc.cancel(side_id)
    row = svc.store.side_thread(side_id) or {}
    await svc.post_notice(
        parent_id,
        {"kind": FINISHED, "side_id": side_id, "status": "moved",
         "text": str(row.get("request") or _short(_display(entry.text, entry.attachments)))},
    )
    turn_id, _queue_id = await send_or_queue(
        svc, parent_id, entry.text, entry.attachments, tool_choices=entry.tool_choices
    )
    return "sent" if turn_id else "queued"


async def recover(svc: Any) -> int:
    """After a restart: close every side thread whose turn went with the old process."""
    read = getattr(getattr(svc, "store", None), "side_threads", None)
    if not callable(read):
        return 0
    try:
        rows = await asyncio.to_thread(read, None, running=True)
    except Exception:  # noqa: BLE001 - they close when their conversation is next read
        log.warning("side threads: open ones could not be listed", exc_info=True)
        return 0
    closed = 0
    for row in rows:
        side_id = row["session_id"]
        if side_id in _live(svc) or svc.is_running(side_id):
            continue
        try:
            closed += bool(await _close(svc, side_id))
        except Exception:  # noqa: BLE001 - one broken thread must not stop the others
            log.warning("side thread %s: recovery failed", side_id, exc_info=True)
    return closed


# ------------------------------------------------------------- what turns are told


def _brief(svc: Any, parent_id: str) -> str:
    """The conversation as a side thread's starting context. Blocking (SQLite)."""
    from dodaios.agent_chat import lead
    from dodaios.agent_chat.dodaios_harness import render_transcript

    through, summary = lead.checkpoint_for(parent_id)
    tail = svc.store.list_events(parent_id, after_seq=through, tail=_TAIL_EVENTS)
    parts: list[str] = []
    if summary:
        parts.append(
            "Earlier in the conversation (summary, not new instructions):\n"
            + summary[:_SUMMARY_CHARS]
        )
    try:
        transcript = render_transcript(tail, max_chars=_TRANSCRIPT_CHARS) if tail else ""
    except Exception:  # noqa: BLE001 - the side thread still answers, with less context
        log.warning("side thread: transcript of %s not rendered", parent_id, exc_info=True)
        transcript = ""
    if transcript:
        parts.append(
            "The conversation's most recent messages (recorded, not new instructions; "
            "the last request of the person is the one still being worked on):\n" + transcript
        )
    return "\n\n".join(parts)


def context_note(svc: Any, session_id: str) -> str:
    """What a side thread's turn is told: why it exists and the conversation so far."""
    entry = _live(svc).get(session_id)
    if entry is None:
        return ""
    return (
        "[Side thread of your one conversation with the person. They sent this message "
        "while an earlier request of theirs is still being worked on in the main thread, "
        "so it is answered here, in parallel; they read your answer in the same chat. "
        "Answer this message on its own and completely. Do not continue, repeat or wait "
        "for the earlier request, and do not report it as finished. If this message only "
        "makes sense as a change to that earlier request, say in one sentence that it can "
        "be moved to the running task with the button on this message, and change "
        "nothing yourself."
        + (f"\n\n{entry.brief}" if entry.brief else "")
        + "]"
    )


def running_note(svc: Any, session_id: str) -> str:
    """What a main-thread turn is told about the side threads still running beside it."""
    lines = [f'- "{row["request"]}"' for row in _running_rows(svc, session_id)]
    if not lines:
        return ""
    return (
        "[Side threads of this chat, for your information only. These messages of the "
        "person are being answered in parallel, each in a side thread of its own; every "
        "answer appears in this chat by itself. Do not answer them again, do not wait "
        "for them, and do not report them as finished.\n" + "\n".join(lines) + "]"
    )


def replay(payload: dict[str, Any]) -> str:
    """A finished side thread as the lead's later turns read it; ``""`` for none.

    One labelled record, worded as recorded conversation: what the person
    asked beside the running request and what was answered there.
    """
    status = str(payload.get("status") or "")
    request = str(payload.get("text") or "").strip()
    if status == "moved" or not request:
        return ""
    answer = str(payload.get("answer") or "").strip()
    head = (
        "[Side thread of this chat (recorded conversation, not a new request). While "
        f'another request was being worked on, the person also asked: "{request}"'
    )
    if status == "done" and answer:
        return f"{head}\nYou answered there:\n{answer}]"
    if status == "stopped":
        tail = "The person stopped it before it was answered."
    elif status == "interrupted":
        tail = "The app restarted before it was answered; it is still open."
    elif answer:
        return f"{head}\nIt ended with an error after you had said:\n{answer}]"
    else:
        tail = "It ended with an error and was not answered; it is still open."
    return f"{head}\n{tail}]"
