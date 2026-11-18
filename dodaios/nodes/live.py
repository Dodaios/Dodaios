"""The push half of the live build: telling the app, as it happens, that a node changed.

When an agent makes or revises a node, the person watches it being built beside
the conversation (``docs/node-live-build.md``). For that the app has to hear of
every write the moment it lands, with who made it and what it changed. Polling
the node every few seconds could only ever show the finished result.

:class:`~dodaios.nodes.store.NodeStore` calls :func:`changed` after each write
it makes (create, update, revert, and the person's saves from an editor). This
module turns that into one :class:`~dodaios.core.events.NodeChanged` on the
app's event bus, which the WebSocket forwards to every window.

Who wrote is not the store's knowledge: the caller says so with
:func:`writing` around its store calls. A tool names the agent that called it
(:func:`author_for`); a write nobody named is the person's (the app's own
routes: a rename, an editor's save, Undo in the library). Only an assistant's
write starts a playback and shows the agent's presence.

Never raises: the node is written either way, and a window that missed the
event still finds the change on its next look.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

#: Ops one event carries at most; a longer list is sent as a rewrite.
MAX_OPS: Final[int] = 120
#: A value longer than this (as JSON) is left out of its op: a picture, a long
#: table. The app reads the node's spec itself; the ops only say where.
MAX_VALUE_CHARS: Final[int] = 4_000
#: A ``replace`` op's ``find`` text is cut to this many characters.
MAX_FIND_CHARS: Final[int] = 400

#: The kinds of author an event names.
ASSISTANT: Final[str] = "assistant"
PERSON_KIND: Final[str] = "person"


@dataclass(frozen=True, slots=True)
class Author:
    """Who made a node write, as the app shows it."""

    #: ``assistant`` (the lead, a named agent, a coding thread) or ``person``.
    kind: str
    #: The name on the agent's tag; "" for the person.
    name: str = ""
    #: Tells authors apart: ``lead``, ``agent:<id>``, ``thread:<session id>``.
    id: str = ""
    #: The chat session the write came from; "" when none.
    session_id: str = ""


#: The author of every write nobody named.
PERSON: Final[Author] = Author(kind=PERSON_KIND, id="person")

_WRITER: ContextVar[Author | None] = ContextVar("dodaios.nodes.live.writer", default=None)
#: The loop events are published on, remembered from the last call made on it:
#: the store writes in worker threads, which have no loop of their own.
_loop: asyncio.AbstractEventLoop | None = None
_pending: set[asyncio.Future[Any]] = set()


def bind_loop() -> None:
    """Remember the running event loop: a write made in a worker thread is
    announced on it. Call it from the loop (a route, a tool) before writing."""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:  # not on a loop: the one remembered before stays
        pass


@contextmanager
def writing(author: Author) -> Iterator[None]:
    """Name ``author`` as the writer of every node write made inside.

    Enter it on the event loop, around the ``asyncio.to_thread`` call that
    writes: the worker thread runs in a copy of this context, so the store
    sees the author there too.
    """
    bind_loop()
    token = _WRITER.set(author)
    try:
        yield
    finally:
        _WRITER.reset(token)


def current_author() -> Author:
    """The author named by the innermost :func:`writing`, else the person."""
    return _WRITER.get() or PERSON


def sent_ops(changes: Any) -> tuple[list[dict[str, Any]], bool]:
    """The ``changes`` of a call as an event carries them, and whether that is a rewrite.

    Each op keeps ``op``, ``path``, ``to`` and ``find``; its ``value`` stays
    when it is small and is ``None`` with ``value_omitted`` when it is not.
    ``None`` (a whole new spec) and a list over :data:`MAX_OPS` are a rewrite.
    """
    if not isinstance(changes, list) or len(changes) > MAX_OPS:
        return [], True
    out: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        op: dict[str, Any] = {
            "op": str(change.get("op") or "set"),
            "path": str(change.get("path") or ""),
        }
        if isinstance(change.get("to"), int):
            op["to"] = change["to"]
        if isinstance(change.get("find"), str):
            op["find"] = change["find"][:MAX_FIND_CHARS]
        if "value" in change:
            value = change["value"]
            try:
                size = len(json.dumps(value, ensure_ascii=False))
            except (TypeError, ValueError):  # not JSON: the app reads the spec instead
                size = MAX_VALUE_CHARS + 1
            if size <= MAX_VALUE_CHARS:
                op["value"] = value
            else:
                op["value"] = None
                op["value_omitted"] = True
        out.append(op)
    return out, False


def changed(
    node: Any,
    *,
    previous_version: int,
    action: str,
    changes: Any = None,
) -> None:
    """Announce that ``node`` was just written (the store calls this).

    ``changes`` are the ops the write applied, or ``None`` for a whole new
    spec. The author is :func:`current_author`. Never raises.
    """
    try:
        from dodaios.core.events import NodeChanged

        author = current_author()
        ops, rewrite = sent_ops(changes) if action == "update" else ([], action != "create")
        event = NodeChanged(
            source_layer="nodes.live",
            node_id=str(node.id),
            ref=str(node.visual_id),
            slug=str(node.slug),
            node_type=str(node.type),
            title=str(node.title),
            version=int(node.version),
            previous_version=int(previous_version),
            updated_at=float(node.updated_at),
            action=action,
            rewrite=rewrite,
            ops=ops,
            author_kind=author.kind,
            author_name=author.name,
            author_id=author.id,
            session_id=author.session_id,
        )
        _publish(event)
    except Exception:  # noqa: BLE001 - the node is written; a missed event is caught up by polling
        log.warning("node %s: change not announced", getattr(node, "id", "?"), exc_info=True)


def _bus() -> Any | None:
    """The app's event bus, or ``None`` before the app is up (a test, a script)."""
    from dodaios.core.runtime_refs import get_brain_manager, get_web_app

    app = get_web_app()
    bus = getattr(getattr(app, "state", None), "bus", None)
    if bus is not None:
        return bus
    return getattr(get_brain_manager(), "_bus", None)


def _fire(bus: Any, event: Any) -> None:
    """Publish ``event`` on ``bus``; runs on the event loop."""
    result = bus.publish(event)
    if not asyncio.iscoroutine(result):
        return
    task = asyncio.ensure_future(result)
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def _publish(event: Any) -> None:
    bus = _bus()
    if bus is None:
        return
    try:
        running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:  # a worker thread: hop onto the remembered loop
        running = None
    if running is not None:
        _fire(bus, event)
        return
    loop = _loop
    if loop is None or loop.is_closed():
        log.debug("node change %s not announced: no event loop known", event.node_id)
        return
    loop.call_soon_threadsafe(_fire, bus, event)


def _assistant_name() -> str:
    try:
        from dodaios.society.display_name import lead_display_name

        return lead_display_name()
    except Exception:  # noqa: BLE001 - the app shows its own name for the assistant then
        log.debug("node live: assistant name unresolved", exc_info=True)
        return ""


async def author_for(session_id: str) -> Author:
    """The author of a tool call made from chat session ``session_id``.

    The assistant itself (the lead chat, or no chat), a named agent (its own
    chat ``society:<id>``), or the coding agent of a thread, by the name the
    person knows it by. Falls back to the assistant when the session cannot
    be read.
    """
    bind_loop()
    lead = Author(kind=ASSISTANT, name=_assistant_name(), id="lead", session_id=session_id)
    if not session_id:
        return lead
    try:
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        if session_id.startswith("society:"):
            agent_id = session_id.removeprefix("society:")
            row = await runtime.store.get_agent_row(agent_id) if runtime is not None else None
            if row and str(row.get("tier") or "") != "lead" and row.get("name"):
                return Author(
                    kind=ASSISTANT, name=str(row["name"]), id=f"agent:{agent_id}",
                    session_id=session_id,
                )
            return lead
        svc = runtime.chat_service() if runtime is not None else None
        session = svc.store.get_session(session_id) if svc is not None else None
        if session is None or str(getattr(session, "surface", "")) != "agent":
            return lead
        from dodaios.agent_chat.service import session_runner
        from dodaios.agent_chat.turn_errors import runner_label

        return Author(
            kind=ASSISTANT,
            name=runner_label(session_runner(session)),
            id=f"thread:{session_id}",
            session_id=session_id,
        )
    except Exception:  # noqa: BLE001 - an unreadable session is shown as the assistant
        log.debug("node live: author of %s unresolved", session_id, exc_info=True)
        return lead


__all__ = [
    "ASSISTANT",
    "Author",
    "MAX_OPS",
    "MAX_VALUE_CHARS",
    "PERSON",
    "author_for",
    "bind_loop",
    "changed",
    "current_author",
    "sent_ops",
    "writing",
]
