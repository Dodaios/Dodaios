"""Lessons and how-to notes: what the assistant learns from being corrected.

Two kinds of memory come out of the learning review, both stored in the vault
as ``procedural`` memories whose ``source`` says what they are:

- ``lesson``: a rule drawn from a correction ("send reports as PDF, never as
  Word documents"), with the words that triggered it, the user's quote and
  where it was said.
- ``how_to``: a short procedural note from a turn in which a tool failed and
  the assistant worked around it ("opening the share needs the VPN first").

This module is deterministic and cheap (no model): it finds the lessons that
fit a new situation, notices when the owner has to give the same correction a
second time, and keeps the small counters the Memory page shows. The review
decides what is worth keeping; Python decides what is stored and recalled.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, Final

from dodaios.memory.vault.models import Memory
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

LESSON: Final[str] = "lesson"
HOW_TO: Final[str] = "how_to"
NOTES: Final[tuple[str, ...]] = (LESSON, HOW_TO)

STATE_KEY: Final[str] = "lessons_state"
TIDY_KEY: Final[str] = "tidy_last"

#: Longest trigger context kept with a lesson.
MAX_TRIGGER_CHARS: Final[int] = 200
#: Overlap (share of the smaller word set) from which a lesson fits a message.
RECALL_THRESHOLD: Final[float] = 0.4
#: Overlap from which a correction repeats a stored lesson.
REPEAT_THRESHOLD: Final[float] = 0.5

_TOKEN = re.compile(r"[^\W_]{3,}", re.UNICODE)
#: Words that carry no topic: grammar, and the vocabulary of corrections itself.
_STOP: Final[frozenset[str]] = frozenset(
    (
        "the and you your what when where who how why can could would should will are "
        "was were have has had this that these those with from for about into not dont "
        "never always again please user users meant mean wrong told said say tell stop "
        "just also some any more much very like want need make sure instead rather "
        "der die das und ich du wir ihr sie ist sind war was wer wie wo wann warum "  # i18n-allow
        "ein eine einen dem den des mit von für über auf noch auch bitte mal mir "  # i18n-allow
        "mich dir dich nicht nie immer wieder nochmal gesagt sondern falsch meinte "  # i18n-allow
        "que los las una por para como con del pero siempre nunca otra vez "  # i18n-allow
    ).split()
)

_lock = threading.Lock()


def words(text: str) -> frozenset[str]:
    """Topic words of ``text``: lower case, no stop words, plural and inflection folded."""
    found: set[str] = set()
    for raw in _TOKEN.findall((text or "").casefold()):
        if raw in _STOP:
            continue
        word = raw[:-1] if len(raw) > 4 and raw.endswith("s") else raw
        found.add(word[:6])
    return frozenset(found)


def similarity(query: str, document: str) -> float:
    """Share of the smaller topic-word set that both texts have; 0 below two shared words.

    One shared word only counts when one of the texts has two topic words or
    fewer (a short rule like "no emojis" still matches "stop the emojis").
    """
    left, right = words(query), words(document)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    smallest = min(len(left), len(right))
    if shared < 2 and not (shared == 1 and smallest <= 2):
        return 0.0
    return shared / smallest


# ── state ────────────────────────────────────────────────────────────────


def load_state(vault: MemoryVault) -> dict[str, Any]:
    try:
        data = json.loads(vault.get_meta(STATE_KEY) or "{}")
    except ValueError:
        log.warning("lessons: unreadable state in the vault, starting afresh")
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("needs_stronger", [])
    data.setdefault("auto_pinned", [])
    data.setdefault("total_repeats", 0)
    return data


def _save(vault: MemoryVault, data: dict[str, Any]) -> None:
    vault.set_meta(STATE_KEY, json.dumps(data, sort_keys=True))


def _chain(vault: MemoryVault, memory: Memory) -> set[str]:
    """Ids of every version of ``memory`` (the counters follow the supersede chain)."""
    try:
        return {m.id for m in vault.history(memory.id)} | {memory.id}
    except Exception:  # noqa: BLE001 - a broken chain must not stop a lookup
        log.warning("lessons: could not read a memory history", exc_info=True)
        return {memory.id}


def note_of(memory: Memory) -> str:
    """``lesson``, ``how_to`` or ``""``."""
    value = str(memory.source.get("note") or "")
    return value if value in NOTES else ""


def note_auto_pin(vault: MemoryVault, memory_id: str) -> None:
    """Remember that the learning loop (not the owner) pinned this memory."""
    with _lock:
        data = load_state(vault)
        if memory_id not in data["auto_pinned"]:
            data["auto_pinned"].append(memory_id)
            _save(vault, data)


def owner_pinned(vault: MemoryVault, memory: Memory, data: dict[str, Any] | None = None) -> bool:
    """True when the owner pinned it: the consolidation never touches such a memory."""
    if not memory.pinned:
        return False
    state = data if data is not None else load_state(vault)
    return not (_chain(vault, memory) & set(state["auto_pinned"]))


# ── recall ───────────────────────────────────────────────────────────────


def _document(memory: Memory) -> str:
    return f"{memory.text} {memory.source.get('trigger') or ''}"


def current_notes(vault: MemoryVault, note: str | None = None) -> list[Memory]:
    """Current lessons and how-to notes (only ``note`` when given)."""
    return [
        m
        for m in vault.list(kind="procedural")
        if (note is None and note_of(m)) or (note is not None and note_of(m) == note)
    ]


def recall(vault: MemoryVault, user_text: str, *, limit: int = 3) -> list[tuple[Memory, float]]:
    """Lessons and how-to notes that fit what the user just said, best first."""
    scored = [
        (m, similarity(user_text, _document(m)))
        for m in current_notes(vault)
        if not m.sensitivity == "sensitive"
    ]
    fitting = [(m, s) for m, s in scored if s >= RECALL_THRESHOLD]
    fitting.sort(key=lambda pair: (pair[1], pair[0].recorded_at), reverse=True)
    return fitting[:limit]


# ── repeat errors ────────────────────────────────────────────────────────


def find_repeat(vault: MemoryVault, correction: str) -> Memory | None:
    """The stored lesson this correction says again, if any."""
    best: tuple[float, Memory] | None = None
    for lesson in current_notes(vault, LESSON):
        score = similarity(correction, _document(lesson))
        if score >= REPEAT_THRESHOLD and (best is None or score > best[0]):
            best = (score, lesson)
    return best[1] if best else None


def note_repeat(vault: MemoryVault, correction: str) -> Memory | None:
    """Count a correction that repeats a stored lesson; returns that lesson.

    The lesson is marked as needing stronger wording (the next consolidation
    pass rewrites it) and is pinned so it rides in every conversation.
    """
    lesson = find_repeat(vault, correction)
    if lesson is None:
        return None
    with _lock:
        data = load_state(vault)
        data["total_repeats"] = int(data["total_repeats"]) + 1
        if lesson.id not in data["needs_stronger"]:
            data["needs_stronger"].append(lesson.id)
        if not lesson.pinned:
            vault.pin(lesson.id, True)
            data["auto_pinned"].append(lesson.id)
        _save(vault, data)
    log.info("learning: the owner repeated a correction (%d in total)", data["total_repeats"])
    return lesson


def needing_stronger(vault: MemoryVault) -> list[Memory]:
    """Current lessons the owner had to correct again."""
    data = load_state(vault)
    marked = set(data["needs_stronger"])
    return [m for m in current_notes(vault, LESSON) if _chain(vault, m) & marked]


def clear_stronger(vault: MemoryVault, memory: Memory, replaced_by: str) -> None:
    """After a rewrite: the new version no longer needs it; its counters carry over."""
    with _lock:
        data = load_state(vault)
        data["needs_stronger"] = [i for i in data["needs_stronger"] if i != memory.id]
        if _chain(vault, memory) & set(data["auto_pinned"]):
            data["auto_pinned"].append(replaced_by)
        _save(vault, data)


# ── metrics ──────────────────────────────────────────────────────────────


def record_tidy(vault: MemoryVault, summary: dict[str, int]) -> None:
    """Keep the result of the last consolidation pass for the Memory page."""
    vault.set_meta(TIDY_KEY, json.dumps({"at": vault.now(), **summary}, sort_keys=True))


def metrics(vault: MemoryVault) -> dict[str, Any]:
    """What the Memory page shows about learning from corrections."""
    data = load_state(vault)
    try:
        tidy = json.loads(vault.get_meta(TIDY_KEY) or "{}")
    except ValueError:
        log.warning("lessons: unreadable tidy-up record in the vault")
        tidy = {}
    notes = current_notes(vault)
    return {
        "lessons": sum(1 for m in notes if note_of(m) == LESSON),
        "how_to": sum(1 for m in notes if note_of(m) == HOW_TO),
        "repeat_errors": int(data["total_repeats"]),
        "needs_stronger": len(needing_stronger(vault)),
        "last_tidy": tidy if isinstance(tidy, dict) else {},
    }
