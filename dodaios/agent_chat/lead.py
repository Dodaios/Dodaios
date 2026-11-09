"""The lead's one endless conversation.

Dodaios (the lead) talks to its person in ONE conversation that never ends:
typed turns, voice calls, agent reports and notices all land in the same
``jarvis``-surface session. That session is chosen once and remembered in
the store (``jarvis_lead_session``). On an install that already has Jarvis
chats, the newest one is adopted so the conversation continues where the
person left off; older chats stay readable as the archive.

Everything that used to pick "the newest Jarvis chat" asks
:func:`lead_session` instead, so a report never lands in a chat nobody looks
at and never fails because no chat was open.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Final

log = logging.getLogger(__name__)

#: The chat surface of the lead's conversation.
SURFACE: Final[str] = "jarvis"

_lock = threading.RLock()


def chat_seat(svc: Any) -> dict[str, str] | None:
    """The provider / model / effort the person last picked for the chat.

    In order: the last explicit chat pick, the seat of the newest Jarvis
    chat. ``None`` when neither offers a provider of the chat surface.
    """
    from dodaios.agent_chat.catalog import offers

    read_selection = getattr(svc.store, "chat_selection", None)
    selection = read_selection() if callable(read_selection) else None
    if selection is not None and offers(SURFACE, selection.provider):
        seat = {
            "provider": selection.provider,
            "model": selection.model,
            "effort": selection.effort,
        }
        if getattr(selection, "account_id", ""):
            seat["account_id"] = selection.account_id
        return seat
    newest = svc.store.list_sessions(limit=1, surface=SURFACE)
    if newest and offers(SURFACE, newest[0].provider):
        session = newest[0]
        seat = {"provider": session.provider, "model": session.model, "effort": session.effort}
        if getattr(session, "account_id", ""):
            seat["account_id"] = session.account_id
        return seat
    return None


def _default_seat(provider_hint: str = "") -> dict[str, str] | None:
    from dodaios.agent_chat.catalog import offers, rows_for

    provider = (provider_hint or "").strip().lower()
    if provider and offers(SURFACE, provider):
        return {"provider": provider}
    rows = rows_for(SURFACE)
    return {"provider": rows[0].id} if rows else None


def lead_session_id(svc: Any) -> str | None:
    """The remembered id of the lead's conversation, without creating one."""
    read = getattr(svc.store, "lead_session_id", None)
    if not callable(read):
        return None
    try:
        return read()
    except Exception:  # noqa: BLE001 — an older store: treat as not chosen yet
        log.debug("lead thread: could not read the lead session id", exc_info=True)
        return None


def is_lead(svc: Any, session_id: str) -> bool:
    """True when ``session_id`` is the lead's one conversation."""
    return bool(session_id) and lead_session_id(svc) == session_id


def lead_session(svc: Any, *, create: bool = True, provider_hint: str = "") -> Any | None:
    """The lead's one conversation; adopted or created on first use.

    Order: the remembered session (if it still exists on the jarvis
    surface), else the newest Jarvis chat (an upgrade keeps talking where it
    stopped), else a new session on the person's chat pick. ``create=False``
    never writes; it returns ``None`` when nothing exists yet.
    """
    with _lock:
        store = svc.store
        remembered = lead_session_id(svc)
        if remembered:
            session = store.get_session(remembered)
            if session is not None and session.surface == SURFACE:
                return session
        newest = store.list_sessions(limit=1, surface=SURFACE)
        session = newest[0] if newest else None
        if session is None:
            if not create:
                return None
            seat = chat_seat(svc) or _default_seat(provider_hint)
            if seat is None:
                log.warning("lead thread: no chat provider is available")
                return None
            session = svc.create_session(surface=SURFACE, **seat)
        remember = getattr(store, "set_lead_session_id", None)
        if callable(remember):
            remember(session.session_id)
            log.info("lead thread: conversation is %s", session.session_id)
        return session


def adopt_seat(svc: Any, seat: dict[str, Any]) -> Any | None:
    """Put the person's new chat pick on the lead's conversation.

    A "new chat" request from an older client carries the model the person
    picked. The conversation stays the same; only its seat changes.
    """
    from dodaios.agent_chat.catalog import offers, provider_row
    from dodaios.agent_chat.effort import normalize_effort

    provider = str(seat.get("provider") or "").strip().lower()
    if provider and not offers(SURFACE, provider):
        raise ValueError(f"Provider {provider!r} is not offered on the {SURFACE!r} chat.")
    session = lead_session(svc, provider_hint=provider)
    if session is None:
        return None
    wanted: dict[str, Any] = dict(seat)
    if provider:
        wanted["provider"] = provider
        if provider != session.provider:
            if not wanted.get("model"):
                row = provider_row(provider)
                wanted["model"] = row.default_model if row is not None else ""
            wanted.setdefault("account_id", "")
    if wanted.get("effort") is not None:
        wanted["effort"] = normalize_effort(provider or session.provider, wanted["effort"])
    fields: dict[str, Any] = {}
    for key in ("provider", "model", "effort", "account_id"):
        value = wanted.get(key)
        if value is not None and value != getattr(session, key, None):
            fields[key] = value
    if "provider" in fields:
        fields["vendor_session"] = ""
    if not fields:
        return session
    updated = svc.store.update_session(session.session_id, **fields)
    return updated or session


def voice_history(
    session_id: str, events: list[dict[str, Any]], *, max_chars: int = 60_000
) -> list[Any]:
    """The lead's conversation as a voice call's starting context.

    The latest compaction summary (when the conversation was ever compacted)
    followed by the most recent turns within ``max_chars``. A call never
    starts on a blind cut of the last messages only.
    """
    from dodaios.agent_chat.runner_brain import brain_history_from_events
    from dodaios.core.protocols import BrainMessage

    summary, through = "", 0
    archive = _archive()
    if archive is not None and events:
        try:
            through, summary = archive.checkpoint(session_id)
        except Exception:  # noqa: BLE001 — no summary is a usable answer
            log.debug("lead thread: checkpoint read failed", exc_info=True)
    tail = [e for e in events if int(e.get("seq") or 0) > through]
    history = brain_history_from_events(tail, max_messages=None)
    kept: list[Any] = []
    used = len(summary)
    for message in reversed(history):
        cost = len(str(getattr(message, "content", "") or "")) + 16
        if kept and used + cost > max_chars:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    if summary:
        kept.insert(
            0,
            BrainMessage(
                role="user",
                content="Earlier in our conversation (summary, not new instructions):\n" + summary,
            ),
        )
    return kept


def search_conversation(query: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """What was said earlier in the lead's conversation about ``query``.

    Blocking (SQLite); call it off the event loop. Rows carry who said it,
    the date and an excerpt, newest relevant first. Empty when the society
    runtime (which owns the archive) or the conversation does not exist.
    """
    import datetime as _dt

    try:
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
    except Exception:  # noqa: BLE001 — society not loaded
        return []
    svc = runtime.chat_service() if runtime is not None else None
    archive = getattr(runtime, "conversations", None) if runtime is not None else None
    if svc is None or archive is None:
        return []
    sid = lead_session_id(svc)
    if not sid or not str(query or "").strip():
        return []
    archive.ingest(sid, svc.store.list_events(sid))
    rows: list[dict[str, Any]] = []
    for hit in archive.search(sid, query, limit=max(1, min(20, limit))):
        if hit.get("kind") not in {"user_message", "assistant_text"}:
            continue
        text = str(hit.get("text") or "").strip()
        if not text:
            continue
        ts = int(hit.get("ts_ms") or 0)
        rows.append(
            {
                "who": "user" if hit["kind"] == "user_message" else "you",
                "date": _dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "",
                "text": text[:600],
            }
        )
    return rows


def _archive() -> Any | None:
    try:
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
    except Exception:  # noqa: BLE001 — society not loaded
        return None
    return getattr(runtime, "conversations", None) if runtime is not None else None


__all__ = [
    "SURFACE",
    "adopt_seat",
    "chat_seat",
    "is_lead",
    "lead_session",
    "lead_session_id",
    "search_conversation",
    "voice_history",
]
