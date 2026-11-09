"""The process-wide memory vault and the helpers prompt builders and tools call.

``prompt_block()`` is what every engine (chat, realtime voice, GPT-Live)
puts into its instructions; ``remember_explicitly()`` is what a "remember
that ..." request writes. Both are cheap: the block is cached and only
rebuilt after a write.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from dodaios.memory.vault.models import WriteResult
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

VAULT_FILENAME = "vault.db"

_HEADER = (
    "## What you know about the user (long-term memory)\n"
    "Use it when it helps; never recite it. Search it with memory-search for "
    "anything not listed here."
)

_active: MemoryVault | None = None
_lock = threading.Lock()
_cache: dict[bool, tuple[int, str]] = {}
_generation = 0
_budgets = {"full": 2400, "compact": 1200}


def vault_path(config: Any) -> Path:
    """``memory.vault.path`` if set, else ``<memory.data_dir>/memory/vault.db``."""
    memory = getattr(config, "memory", None)
    vault_cfg = getattr(memory, "vault", None)
    explicit = str(getattr(vault_cfg, "path", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    from dodaios.core.config import DATA_DIR

    data_dir = str(getattr(memory, "data_dir", "") or "").strip()
    base = Path(data_dir) if data_dir and data_dir not in ("./data", "data") else DATA_DIR
    return base / "memory" / VAULT_FILENAME


def open_from_config(config: Any) -> MemoryVault | None:
    """Open the vault and make it the active one; ``None`` when switched off."""
    vault_cfg = getattr(getattr(config, "memory", None), "vault", None)
    if vault_cfg is not None and not getattr(vault_cfg, "enabled", True):
        set_active(None)
        return None
    if _active is not None:
        return _active
    if vault_cfg is not None:
        _budgets["full"] = int(getattr(vault_cfg, "profile_max_chars", 2400))
        _budgets["compact"] = max(400, _budgets["full"] // 2)
    vault = MemoryVault(vault_path(config))
    set_active(vault)
    return vault


def set_active(vault: MemoryVault | None) -> None:
    global _active
    with _lock:
        old, _active = _active, vault
        changed()
    if old is not None and old is not vault:
        try:
            old.close()
        except Exception:  # noqa: BLE001 — closing an old handle never fails a swap
            log.debug("memory vault: could not close the old handle", exc_info=True)


def active() -> MemoryVault | None:
    return _active


def changed() -> None:
    """Drop the cached prompt block; called after every write."""
    global _generation
    _generation += 1
    _cache.clear()


def budget_chars(*, compact: bool = False) -> int:
    """Characters the always-on block may use (voice gets the compact budget)."""
    return _budgets["compact" if compact else "full"]


def prompt_block(*, compact: bool = False) -> str:
    """The always-on memory block, ``""`` while no vault runs or it is empty."""
    vault = _active
    if vault is None:
        return ""
    cached = _cache.get(compact)
    if cached is not None and cached[0] == _generation:
        return cached[1]
    try:
        body = vault.profile_block(max_chars=_budgets["compact" if compact else "full"])
    except Exception:  # noqa: BLE001 — a vault fault never breaks a prompt build
        log.warning("memory vault: could not build the prompt block", exc_info=True)
        return ""
    block = f"{_HEADER}\n{body}" if body else ""
    _cache[compact] = (_generation, block)
    return block


# Words that hint at a kind, in the shipped input languages.
_WORDS = {
    "procedural": (
        "always never don't stop immer nie niemals siempre nunca"  # i18n-allow
    ),
    "preference": (
        "like love hate prefer favorite favourite "
        "mag liebe hasse lieber bevorzuge prefiero gusta"  # i18n-allow
    ),
    "relationship": (
        "wife husband partner girlfriend boyfriend mother father mom dad sister brother "
        "son daughter friend colleague boss "
        "frau mann freundin freund mutter vater schwester bruder sohn tochter "  # i18n-allow
        "kollege kollegin chef chefin"  # i18n-allow
    ),
    "project": (
        "project deadline goal plan launch projekt ziel abgabe frist"  # i18n-allow
    ),
}

#: Words that say nothing about what a message is about (shipped input languages).
_STOPWORDS = frozenset(
    (
        "the and you your what when where who how why can could would should will "
        "are was were have has had this that these those with from for about into "
        "please tell know remember just also some any more much very "
        "der die das und ich du wir ihr sie ist sind war was wer wie wo wann warum "  # i18n-allow
        "ein eine einen dem den des mit von für über auf noch auch bitte mal mir "  # i18n-allow
        "mich dir dich mein meine kannst kann weißt hast habe nicht oder aber "  # i18n-allow
        "que los las una por para como con del pero"  # i18n-allow
    ).split()
)

#: Budget and size of the per-message recall.
TURN_MAX_CHARS = 900
TURN_LIMIT = 6
#: A hit must score at least this share of the best hit to be shown.
TURN_RELATIVE_FLOOR = 0.35

_TURN_HEADER = (
    "## Possibly relevant memories (looked up for this message)\n"
    "From the user's long-term memory; use them only if they fit the question."
)


def turn_block(user_text: str, *, compact: bool = False) -> str:
    """Memories that match this message and are not already always in mind.

    Cheap and local: one FTS query on the vault, no model call. ``""`` when
    nothing fits, no vault runs or the message has no content words.
    """
    vault = _active
    if vault is None or not user_text.strip():
        return ""
    words = [
        w for w in re.findall(r"\w+", user_text.casefold()) if len(w) > 2 and w not in _STOPWORDS
    ]
    if not words:
        return ""
    try:
        budget = _budgets["compact" if compact else "full"]
        in_mind = {
            m.id for _, memories in vault.profile_selection(max_chars=budget) for m in memories
        }
        hits = [
            h
            for h in vault.search(" ".join(words), limit=TURN_LIMIT * 2)
            if h.memory.id not in in_mind
        ]
    except Exception:  # noqa: BLE001 — recall must never break a turn
        log.warning("memory vault: per-message recall failed", exc_info=True)
        return ""
    if not hits:
        return ""
    floor = hits[0].score * TURN_RELATIVE_FLOOR
    lines: list[str] = []
    used = 0
    chosen = []
    for hit in hits:
        if hit.score < floor or len(lines) >= TURN_LIMIT:
            break
        memory = hit.memory
        line = f"- {memory.text}"
        if memory.valid_from and memory.origin != "imported":
            line += f" (since {memory.valid_from[:10]})"
        if used + len(line) > TURN_MAX_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
        chosen.append(memory.id)
    if not lines:
        return ""
    try:
        vault.mark_used(chosen)
    except Exception:  # noqa: BLE001 — a usage counter is not worth failing a turn over
        log.debug("memory vault: could not count recall use", exc_info=True)
    return _TURN_HEADER + "\n" + "\n".join(lines)


_KIND_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(r"\b(" + "|".join(map(re.escape, words.split())) + r")\b", re.I))
    for kind, words in _WORDS.items()
)


def guess_kind(text: str) -> str:
    """A kind for an explicit request, without a model call."""
    for kind, pattern in _KIND_HINTS:
        if pattern.search(text):
            return kind
    return "profile"


def remember_explicitly(
    content: str, *, evidence: str = "", source: str = "remember tool", kind: str | None = None
) -> WriteResult:
    """Save an explicit "remember that ..." in the user's own words.

    Raises ``LookupError`` while no vault runs.
    """
    vault = _active
    if vault is None:
        raise LookupError("the memory vault is not running")
    result = vault.remember(
        content,
        kind or guess_kind(content),
        origin="user",
        source={"via": source, "evidence": evidence[:500]},
    )
    if result.action == "added":
        changed()
    return result


_NAME_PATTERNS = (
    re.compile(r"\buser'?s name is ([A-Z][\w'-]{1,40})"),
    re.compile(r"^(?:my )?name(?: is|:)\s*([A-Z][\w'-]{1,40})", re.I),
)


def learned_user_name() -> str | None:
    """The user's first name as a current profile memory states it, else ``None``."""
    vault = _active
    if vault is None:
        return None
    try:
        memories = vault.list(kind="profile")
    except Exception:  # noqa: BLE001 — no learned name is the honest answer
        log.debug("memory vault: profile unreadable for the name", exc_info=True)
        return None
    for memory in memories:
        for pattern in _NAME_PATTERNS:
            match = pattern.search(memory.text)
            if match:
                return match.group(1)
    return None


# -- dates, pause ------------------------------------------------------------


def dated_notes(*, days: int = 30) -> list[tuple[Any, str]]:
    """``(date, text)`` for current memories falling due soon, for "coming up" grounding."""
    from datetime import date as _date

    vault = _active
    if vault is None:
        return []
    try:
        memories = vault.upcoming(days=days)
    except Exception:  # noqa: BLE001 — dates are grounding, never a turn breaker
        log.debug("memory vault: upcoming read failed", exc_info=True)
        return []
    notes = []
    for memory in memories:
        try:
            notes.append((_date.fromisoformat((memory.due_at or "")[:10]), memory.text))
        except ValueError:  # an unreadable date is left out of the list
            continue
    return notes


def upcoming(*, days: int = 14) -> list[Any]:
    """Current memories due within ``days`` (overdue first); ``[]`` without a vault."""
    vault = _active
    return [] if vault is None else vault.upcoming(days=days)


def learning_paused() -> bool:
    """True while the user has paused background learning."""
    vault = _active
    if vault is None:
        return False
    try:
        return vault.learning_paused_until() is not None
    except Exception:  # noqa: BLE001 — an unreadable flag must not stop learning silently
        log.warning("memory vault: pause flag unreadable", exc_info=True)
        return False


#: Kinds the user's agents may read: how the user wants things done, nothing private.
AGENT_KINDS = ("preference", "procedural")
AGENT_BLOCK_MAX_CHARS = 1200


def agent_block(*, max_chars: int = AGENT_BLOCK_MAX_CHARS) -> str:
    """The user's preferences and standing instructions for their agents (read-only).

    Agents never see profile facts, people, places or anything sensitive, and
    they cannot write or forget memories (ADR-0044).
    """
    vault = _active
    if vault is None:
        return ""
    try:
        memories = [
            m
            for kind in AGENT_KINDS
            for m in vault.list(kind=kind)
            if m.sensitivity == "normal" and m.scope == "global"
        ]
    except Exception:  # noqa: BLE001 — the agents work on without the user's preferences
        log.debug("memory vault: agent block unavailable", exc_info=True)
        return ""
    memories.sort(key=lambda m: (not m.pinned, m.kind != "procedural", m.recorded_at))
    header = (
        "## How the user wants things done\n"
        "From the user's own memory, read-only; follow it unless the task says otherwise."
    )
    lines: list[str] = []
    used = len(header)
    for memory in memories:
        line = f"- {memory.text}"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return header + "\n" + "\n".join(lines) if lines else ""


def record_checkpoint(session: str, through_seq: int, summary: str) -> bool:
    """Queue a compacted part of the lead conversation for episode memories.

    Cheap and synchronous (one meta write); the background upkeep distills the
    queue. False when no vault runs, learning is paused, or it was queued already.
    """
    vault = _active
    if vault is None or learning_paused():
        return False
    from dodaios.memory.vault.episodes import enqueue

    try:
        return enqueue(vault, session, through_seq, summary)
    except Exception:  # noqa: BLE001 — compaction must never fail over memory
        log.warning("memory vault: could not queue a conversation checkpoint", exc_info=True)
        return False
