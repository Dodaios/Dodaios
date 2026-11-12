"""Finding a coding thread again: its short code, its shown title, a search.

The status board lists the threads that work, wait or moved in the last day.
A thread the person started a week ago is not on it, and "look at the agent I
had on the login bug" had no way to reach it. Three things close that gap:

* **The code.** Every thread has one: the first six characters of its session
  id, shown in the IDE as ``#3f9a2c``. The person copies it and gives it to
  Dodaios, and :func:`sessions_for_code` names the thread. Nothing is stored:
  the code is read off the id, so every thread that ever existed has one.
* **The search.** :func:`find` looks through every thread of the IDE, old and
  new, by the words of its title or its messages.
* **The link.** :func:`thread_link` is the markdown a chat answer carries to
  point at a thread. The chat draws it as the thread's title with the coding
  agent's logo, and a click opens the thread in the Agentic IDE.

Everything here reads the chat store, so call it off the event loop.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Final

from loguru import logger

THREAD_SURFACE: Final[str] = "agent"
#: The scheme of a thread link, and of a thread's ``terminal_id``.
THREAD_PREFIX: Final[str] = "thread:"
#: How many characters of the session id the IDE shows as the code.
CODE_CHARS: Final[int] = 6
#: Fewer characters than this name too many threads to be a code.
MIN_CODE_CHARS: Final[int] = 4
MAX_FOUND: Final[int] = 50
DEFAULT_FOUND: Final[int] = 12
#: A search reads at most this many words of the request.
_MAX_WORDS: Final[int] = 6
#: Titles a coding CLI or the titler gave are read for the newest threads only,
#: as the IDE's sidebar does.
_TITLE_SCAN: Final[int] = 200
_CODE_RE: Final[re.Pattern[str]] = re.compile(r"[0-9a-z]+")
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)


def thread_code(session_id: object) -> str:
    """The short code of a thread: the first six characters of its id."""
    return str(session_id or "").strip().casefold()[:CODE_CHARS]


def code_key(raw: object) -> str:
    """What was written or said for a code, reduced to the characters of an id.

    ``#3F9A2C``, ``3f9a 2c``, ``thread:3f9a2c`` and a whole session id all
    read as the start of an id. Anything else is ``""``: not a code.
    """
    text = str(raw or "").strip().casefold().removeprefix(THREAD_PREFIX)
    text = re.sub(r"[\s#\-_.]+", "", text)
    return text if _CODE_RE.fullmatch(text) else ""


def is_short_ref(terminal_id: object) -> bool:
    """Whether ``terminal_id`` names a thread by its code, not by its whole id.

    ``#3f9a2c`` and ``thread:3f9a2c`` are; a pane id and a whole thread id are
    not.
    """
    text = str(terminal_id or "").strip().casefold()
    key = code_key(text)
    if text.startswith("#"):
        return len(key) >= MIN_CODE_CHARS
    return text.startswith(THREAD_PREFIX) and MIN_CODE_CHARS <= len(key) < 32


def sessions_for_code(store: Any, raw: object) -> list[Any]:
    """The threads whose id starts with the code ``raw``, newest first.

    One thread is the usual answer. Two mean the code was cut too short to
    tell them apart; none means no thread carries it (any more).
    """
    key = code_key(raw)
    if len(key) < MIN_CODE_CHARS:
        return []
    return [
        session
        for session in store.list_sessions_matching(key, limit=MAX_FOUND)
        if session.surface == THREAD_SURFACE and store.side_thread(session.session_id) is None
    ]


def _titler(store: Any) -> Any | None:
    """The titler whose book names the IDE's threads, where one is kept."""
    path = str(getattr(store, "_path", "") or "")
    if not path or path == ":memory:":
        return None
    from dodaios.sessions import chat_titles

    return chat_titles.titler_in(Path(path).parent)


def cli_title_of(store: Any, session: Any) -> str:
    """The name the coding CLI gave a thread's conversation itself, or "".

    Claude Code, Codex, Grok Build and Antigravity title their own sessions on
    their own subscription; a thread shows that name the way a terminal pane
    does. A title the person typed wins, so the CLI's is only offered while
    the stored one is still the first message's.
    """
    if not session.vendor_session:
        return ""
    from dodaios.agent_chat.catalog import provider_row

    from . import cli_title

    row = provider_row(session.provider)
    agent = row.agent if row is not None else ""
    if agent not in cli_title.THREAD_AGENTS:
        return ""
    title = cli_title.session_title(agent, session.vendor_session, session.account_id)
    if not title or not store.title_is_automatic(session):
        return ""
    return title


def shown_title(store: Any, session: Any) -> str:
    """The name the IDE's sidebar shows for a thread.

    A title the person typed; else the one its coding CLI gave the
    conversation; else the topic the titler wrote; else its first message.
    Never raises: a title is a label, and the stored one is always there.
    """
    stored = str(session.title or session.preview or "").strip()
    try:
        if stored and not store.title_is_automatic(session):
            return stored
        named = cli_title_of(store, session)
        if not named:
            titler = _titler(store)
            if titler is not None:
                from dodaios.sessions import chat_titles

                named = titler.known(chat_titles.KIND_TYPED, session.session_id)
        return named or stored or "New thread"
    except Exception:  # noqa: BLE001 - the stored title is a fine answer
        logger.opt(exception=True).debug("Thread finder: shown title not read")
        return stored or "New thread"


def thread_link(session_id: str, title: str) -> str:
    """The markdown that points at a thread from a chat answer."""
    label = " ".join(str(title or "").split()) or "Coding agent"
    label = label.replace("[", "(").replace("]", ")")
    return f"[{label}]({THREAD_PREFIX}{session_id})"


def _words(query: str) -> list[str]:
    seen: list[str] = []
    for word in _WORD_RE.findall(str(query or "").casefold()):
        if len(word) >= 2 and word not in seen:
            seen.append(word)
    return seen[:_MAX_WORDS]


def _looks_like_code(text: str) -> bool:
    """One token that reads as a code: ``#3f9a2c``, or id characters with a digit."""
    if not text or len(text.split()) != 1:
        return False
    key = code_key(text)
    if not (MIN_CODE_CHARS <= len(key) <= 32) or not re.fullmatch(r"[0-9a-f]+", key):
        return False
    return text.startswith(("#", THREAD_PREFIX)) or any(ch.isdigit() for ch in key)


def _in(folder: str, roots: list[Path]) -> bool:
    if not roots:
        return True
    cwd = Path(folder)
    return any(cwd == root or root in cwd.parents for root in roots)


def find(
    store: Any,
    *,
    query: str = "",
    code: str = "",
    folders: list[str] | None = None,
    limit: int = DEFAULT_FOUND,
) -> dict[str, Any]:
    """The threads a code or a few words name, newest first.

    Returns ``{"sessions": [(session, hit), ...], "more": int, "by": str}``.
    ``hit`` says why a thread came up: ``snippet`` (the newest matching
    message), ``matches`` and ``words`` (how many of the request's words the
    thread holds). Threads that hold every word come first. With neither a
    code nor words, the newest threads are listed, whatever their age.
    """
    limit = max(1, min(MAX_FOUND, int(limit or DEFAULT_FOUND)))
    roots = [Path(folder) for folder in folders or []]
    # A code typed where the words go is still a code.
    alone = str(query or "").strip()
    as_code = str(code or "").strip() or (alone if _looks_like_code(alone) else "")
    if as_code:
        sessions = [s for s in sessions_for_code(store, as_code) if _in(s.cwd, roots)]
        if sessions or str(code or "").strip():
            return {
                "sessions": [(s, {}) for s in sessions[:limit]],
                "more": max(0, len(sessions) - limit),
                "by": "code",
            }
    words = _words(query)
    if not words:
        sessions = [
            s for s in store.list_sessions(limit=1000, surface=THREAD_SURFACE)
            if _in(s.cwd, roots)
        ]
        return {
            "sessions": [(s, {}) for s in sessions[:limit]],
            "more": max(0, len(sessions) - limit),
            "by": "recent",
        }
    hits: dict[str, dict[str, Any]] = {}

    def note(session_id: str, word: str, **found: Any) -> dict[str, Any]:
        hit = hits.setdefault(
            session_id, {"found": set(), "snippet": "", "matches": 0, "title_match": False}
        )
        hit["found"].add(word)
        if found.get("snippet") and not hit["snippet"]:
            hit["snippet"] = found["snippet"]
        hit["matches"] += int(found.get("matches") or 0)
        hit["title_match"] = hit["title_match"] or bool(found.get("title_match"))
        return hit

    for word in words:
        for row in store.search_sessions(word, surface=THREAD_SURFACE, limit=1000):
            note(
                row["session_id"], word, snippet=row["snippet"], matches=row["matches"],
                title_match=row["title_match"],
            )
    # The name the person reads may be one the CLI or the titler gave: it is
    # in no column the search above reads.
    recent = store.list_sessions(limit=_TITLE_SCAN, surface=THREAD_SURFACE)
    known = {session.session_id: session for session in recent}
    for session in recent:
        title = shown_title(store, session).casefold()
        for word in words:
            if word in title:
                note(session.session_id, word, title_match=True)
    found: list[tuple[Any, dict[str, Any]]] = []
    for session_id, hit in hits.items():
        session = known.get(session_id) or store.get_session(session_id)
        if session is None or not _in(session.cwd, roots):
            continue
        found.append((
            session,
            {
                "words": len(hit["found"]),
                "of": len(words),
                "matches": hit["matches"],
                "title_match": hit["title_match"],
                "snippet": hit["snippet"],
            },
        ))
    found.sort(key=lambda item: (item[1]["words"], int(item[0].updated_ms or 0)), reverse=True)
    return {"sessions": found[:limit], "more": max(0, len(found) - limit), "by": "words"}


def when(ms: int, *, now: float | None = None) -> str:
    """``2026-11-03 14:20 (9 days ago)``: a time a model can read and compare."""
    if not ms:
        return ""
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))
    seconds = max(0.0, (now if now is not None else time.time()) - ms / 1000)
    if seconds < 90:
        ago = "just now"
    elif seconds < 90 * 60:
        ago = f"{round(seconds / 60)} minutes ago"
    elif seconds < 36 * 3600:
        ago = f"{round(seconds / 3600)} hours ago"
    else:
        ago = f"{round(seconds / 86400)} days ago"
    return f"{stamp} ({ago})"


__all__ = [
    "CODE_CHARS",
    "DEFAULT_FOUND",
    "MAX_FOUND",
    "MIN_CODE_CHARS",
    "THREAD_PREFIX",
    "cli_title_of",
    "code_key",
    "find",
    "is_short_ref",
    "sessions_for_code",
    "shown_title",
    "thread_code",
    "thread_link",
    "when",
]
