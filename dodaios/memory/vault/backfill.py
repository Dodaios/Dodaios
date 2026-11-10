"""One learning pass over the chats that existed before the one endless conversation.

The old front-page chats (``agent_chat.db``, surface ``jarvis``) and the older
text store (``chats.db``) hold months of things the user said. With one
endless conversation they move to a read-only archive; their facts should not
be lost with them. This pass reads only the user's own sentences, keeps the
ones the learning filter marks as personal, and reconciles them into the
vault in small batches with the same reviewer the learning loop uses (so it
never bills a paid key). It runs once per vault, in the background, resumes
where it stopped, and stops for good after ``MAX_CALLS`` model calls.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dodaios.memory.vault import reconcile
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

META_KEY = "chat_backfill"
#: Most model calls the whole pass may make.
MAX_CALLS = 30
#: User sentences per call.
BATCH = 8
#: How far back the archive is read.
SINCE_DAYS = 180

Reviewer = Callable[[str], Awaitable[Any]]


def _read(db: Path, sql: str, args: tuple[Any, ...]) -> list[sqlite3.Row]:
    if not db.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:  # a locked or broken archive is skipped, not fatal
        log.info("memory backfill: cannot open %s", db)
        return []
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.Error:  # an older schema without these columns has nothing to give
        log.info("memory backfill: %s has no readable chat rows", db)
        return []
    finally:
        conn.close()


def collect_user_turns(data_dir: Path, *, since_days: int = SINCE_DAYS) -> list[str]:
    """The user's own sentences from the old chats, oldest first, personal ones only."""
    from dodaios.memory.learning.signals import has_signal

    cutoff_ms = int((time.time() - since_days * 86400) * 1000)
    rows: list[tuple[int, str]] = []
    for row in _read(
        data_dir / "agent_chat.db",
        "SELECT e.ts_ms AS ts, e.payload AS payload FROM agent_chat_events e "
        "JOIN agent_chat_sessions s ON s.session_id = e.session_id "
        "WHERE s.surface = 'jarvis' AND e.kind = 'user_message' AND e.ts_ms >= ?",
        (cutoff_ms,),
    ):
        try:
            text = str((json.loads(row["payload"]) or {}).get("text") or "")
        except (TypeError, ValueError):  # a malformed event is skipped
            continue
        rows.append((int(row["ts"]), text))
    for row in _read(
        data_dir / "chats.db",
        "SELECT timestamp_ns AS ts, text FROM chat_messages "
        "WHERE role = 'user' AND timestamp_ns >= ?",
        (cutoff_ms * 1_000_000,),
    ):
        rows.append((int(row["ts"]) // 1_000_000, str(row["text"] or "")))
    seen: set[str] = set()
    turns: list[str] = []
    for _, text in sorted(rows):
        text = " ".join(text.split())
        key = text.casefold()
        if len(text) < 12 or key in seen or not has_signal(text):
            continue
        seen.add(key)
        turns.append(text[:1500])
    return turns


def _state(vault: MemoryVault) -> dict[str, Any]:
    raw = vault.get_meta(META_KEY)
    try:
        return dict(json.loads(raw)) if raw else {}
    except ValueError:  # an unreadable state starts the pass afresh
        return {}


async def run_once(vault: MemoryVault, reviewer: Reviewer, data_dir: Path) -> dict[str, Any]:
    """Continue (or start) the pass; returns its state. Safe to call on every boot."""
    import asyncio

    from dodaios.memory.vault import runtime as vault_runtime

    state = _state(vault)
    if state.get("done"):
        return state
    turns = await asyncio.to_thread(collect_user_turns, data_dir)
    offset = int(state.get("offset", 0))
    calls = int(state.get("calls", 0))
    written = int(state.get("written", 0))
    while offset < len(turns) and calls < MAX_CALLS:
        if vault_runtime.learning_paused():
            break
        said = [{"user": text} for text in turns[offset : offset + BATCH]]
        shown = await asyncio.to_thread(reconcile.nearest, vault, said)
        try:
            raw = await reviewer(reconcile.build_prompt(said, shown))
        except Exception:  # noqa: BLE001 — a provider fault ends this run; the next boot resumes
            log.warning("memory backfill: reviewer failed", exc_info=True)
            raw = None
        if raw is None:
            break
        # Only an answered call spends the budget. A reviewer that was down for
        # thirty boots used to end the pass as "done" with nothing read.
        calls += 1
        ops, _ = reconcile.validate(raw, user_texts=[r["user"] for r in said], shown=shown)
        written += await asyncio.to_thread(
            reconcile.apply, vault, ops, source={"via": "chat-backfill"}
        )
        offset += len(said)
        vault.set_meta(META_KEY, json.dumps({"offset": offset, "calls": calls, "written": written}))
    state = {
        "offset": offset,
        "calls": calls,
        "written": written,
        "done": offset >= len(turns) or calls >= MAX_CALLS,
        "turns": len(turns),
    }
    vault.set_meta(META_KEY, json.dumps(state))
    if written:
        vault_runtime.changed()
    log.info("memory backfill: %s", state)
    return state
