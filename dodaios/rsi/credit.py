"""A learned note's track in the person's own requests: where it was shown, how those went.

A how-to note the assistant wrote for itself (:mod:`dodaios.rsi.adopt`) rides
in later prompts when it fits a message. Nothing measures yet whether it helps.
What the record can say is plain: in how many of the person's requests since
the note came into effect the lead had it in front of it, how many of those
went through, and how the other requests of the same period went.

This is observation, not a measurement of cause. A note comes up when a
request is about its subject, so the requests it was shown in are not like
the others, and the difference between the two shares says nothing about the
note. Nothing decides on it (the gate decides), and nothing reads it but the
page.

**Shown.** Every lead turn's system prompt and message are on record
(:mod:`dodaios.rsi.lead_turns`), exactly as the CLI got them. The memory blocks
in them (the always-on block and the recall for the message,
``dodaios.memory.vault.runtime``) carry no memory ids: a memory is one line,
``- <text>``, and a recalled one may have `` (since <date>)`` after it. The
vault keeps a memory's text on one line with single spaces, and a note never
changes its words under the same id (a rewrite is a new memory and a new
registry entry). So a turn showed a note when one of its lines is exactly the
note's line. Nothing looser counts: a note that reached the model reworded or
cut short is not counted as shown.

**How it went.** The chat record (``agent_chat.db``, read as the score of daily
use reads it, :mod:`dodaios.evals.agent_score`) says what came after a request.
It *went through* when it ended done, no undo call followed, and the person's
next message (within 30 minutes) did not correct it, ask the same again or ask
to undo it (``follow_up_kind``); the first_move tasks use the same rule
(``bench/own/lead.py``). Not counted: a request still too new to know, a turn
that carried a running task on (no request of the person's), and a recorded
turn the chat record holds no request for.

**The minimum.** A share, and the count of requests that went through, is
given only on :data:`MIN_REQUESTS` requests or more; below that, only how
often the note was shown. 30 is the number of tasks below which the gate
decides nothing (``gate.rules.MIN_PAIRS``), so the page never gives a figure
on fewer requests than the kernel would act on. It is also where a share stops
being mostly chance: near the usual 85 %, the 95 % range of a share on 30
requests is still about 13 points either way, and on 10 requests it is 22.

No model is called and nothing leaves the machine. What leaves this module is
counts, never words. It reads at most every ten minutes (the page's route runs
it in a thread, off the event loop), and a recorded turn's text is read once
per set of notes: a row is never changed after it is written.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = ["MIN_REQUESTS", "TTL_S", "Note", "count", "outcomes", "shown_in", "track"]

log = logging.getLogger(__name__)

#: Fewest requests a share is given on (see the module's docstring).
MIN_REQUESTS: Final = 30
#: The track reads both records: at most once in this long.
TTL_S: Final = 600.0
#: What a recalled memory's line carries after its text.
_SINCE: Final = " (since "
_NONE: Final[frozenset[str]] = frozenset()


@dataclass(frozen=True, slots=True)
class Note:
    """One learned note, as the page lists it."""

    #: The registry entry that stands for it.
    change_id: str
    #: Its words, read from the memory right now.
    text: str
    #: When it came into effect (epoch ms).
    since_ms: int


def _line(text: str) -> str:
    """The note's line as the memory blocks render it."""
    return "- " + " ".join(text.split())


def _lines(system: str, message: str) -> set[str]:
    """Every list line of what the lead got; a recalled memory's line also without its date."""
    found: set[str] = set()
    for blob in (system, message):
        for line in blob.split("\n"):
            if not line.startswith("- "):
                continue
            found.add(line)
            cut = line.rfind(_SINCE)
            if cut > 0 and line.endswith(")"):
                found.add(line[:cut])
    return found


def shown_in(text: str, system: str, message: str) -> bool:
    """True when one line of what the lead got is this note's line."""
    return _line(text) in _lines(system, message)


def outcomes(chat: Iterable[Any], *, now_ms: int) -> dict[tuple[str, str], bool]:
    """How each of the person's requests went: ``True`` went through, ``False`` did not.

    ``chat`` is the lead's turns as ``agent_score.turns.read_lead_turns`` gives
    them (each knows the person's next message). A request still too new to
    know is left out.
    """
    from dodaios.evals.agent_score.signals import REPEAT_WINDOW_MS, follow_up_kind

    out: dict[tuple[str, str], bool] = {}
    for turn in chat:
        if not turn.turn_id:
            continue
        if turn.next_ts_ms <= 0:
            if now_ms - turn.ts_ms <= REPEAT_WINDOW_MS:
                continue  # the person may still answer it
            follow = ""
        elif turn.next_ts_ms - turn.ts_ms <= REPEAT_WINDOW_MS:
            follow = follow_up_kind(turn.text, turn.next_text)
        else:
            follow = ""
        went = turn.status == "done" and not follow and not turn.undo_calls
        out[(turn.session_id, turn.turn_id)] = went
    return out


def _record(since_ms: int, shown: Sequence[bool], other: Sequence[bool]) -> dict[str, Any]:
    def through(found: Sequence[bool]) -> int | None:
        return sum(found) if len(found) >= MIN_REQUESTS else None

    def share(found: Sequence[bool]) -> float | None:
        return round(sum(found) / len(found), 4) if len(found) >= MIN_REQUESTS else None

    return {
        "since_ms": int(since_ms),
        "shown": len(shown),
        "shown_through": through(shown),
        "shown_share": share(shown),
        "other": len(other),
        "other_through": through(other),
        "other_share": share(other),
        "min_requests": MIN_REQUESTS,
    }


def count(
    notes: Sequence[Note],
    rows: Sequence[Any],
    shown: dict[int, frozenset[str]],
    went: dict[tuple[str, str], bool],
) -> dict[str, dict[str, Any]]:
    """Each note's track from recorded turns, what each showed, and how each went.

    ``rows`` are recorded lead turns (``LeadTurn`` without texts), oldest
    first; ``shown`` maps a row's ``seq`` to the notes it showed. The period
    of a note starts when it came into effect, or with the oldest record if
    that is later (older turns are not on record).
    """
    first = min((int(r.ts_ms) for r in rows), default=0)
    counted = [
        (r, went[(r.session_id, r.turn_id)])
        for r in rows
        if not r.continuation and (r.session_id, r.turn_id) in went
    ]
    out: dict[str, dict[str, Any]] = {}
    for note in notes:
        with_it: list[bool] = []
        without: list[bool] = []
        for row, through in counted:
            if row.ts_ms < note.since_ms:
                continue
            (with_it if note.change_id in shown.get(int(row.seq), _NONE) else without).append(
                through
            )
        out[note.change_id] = _record(max(note.since_ms, first), with_it, without)
    return out


# ------------------------------------------------------------------ the app's records

_lock = threading.Lock()
#: (lead record, chat record) -> (when read, key of the notes, the tracks).
_cache: dict[tuple[str, str], tuple[float, str, dict[str, dict[str, Any]]]] = {}
#: lead record -> (key of the notes' words, seq -> ids of the notes that row showed).
_scanned: dict[str, tuple[str, dict[int, frozenset[str]]]] = {}


def _key(parts: Iterable[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    for part in sorted(parts):
        digest.update(repr(part).encode("utf-8"))
    return digest.hexdigest()


def _shown(
    store: Any, seqs: Sequence[int], notes: Sequence[Note], place: str
) -> dict[int, frozenset[str]]:
    """Which notes each row showed. A row is read once per set of notes' words."""
    words = _key((n.change_id, n.text) for n in notes)
    known, seen = _scanned.get(place, ("", {}))
    if known != words:
        seen = {}
    lines: dict[str, set[str]] = {}
    for note in notes:
        lines.setdefault(_line(note.text), set()).add(note.change_id)
    alive: dict[int, frozenset[str]] = {}
    for seq in seqs:
        if seq in seen:
            alive[seq] = seen[seq]
            continue
        turn = store.turn(seq)
        if turn is None:
            continue  # gone since it was listed (its chat deleted, aged out)
        found = _lines(turn.system, turn.message)
        ids = frozenset(i for line, owners in lines.items() if line in found for i in owners)
        alive[seq] = ids or _NONE
    _scanned[place] = (words, alive)
    return alive


def _read(
    notes: Sequence[Note], lead_db: Path, chat_db: Path, *, now_ms: int
) -> dict[str, dict[str, Any]]:
    from dodaios.evals.agent_score.signals import REPEAT_WINDOW_MS
    from dodaios.evals.agent_score.turns import read_lead_turns
    from dodaios.rsi import lead_turns

    store = lead_turns.store(lead_db)
    rows = store.moves()
    start = min(n.since_ms for n in notes)
    wanted = [r for r in rows if r.ts_ms >= start and not r.continuation]
    went: dict[tuple[str, str], bool] = {}
    if wanted:
        # A row is written just after the person's message: read the chat from a little before.
        since = max(0, min(int(r.ts_ms) for r in wanted) - REPEAT_WINDOW_MS)
        went = outcomes(read_lead_turns(chat_db, since_ms=since), now_ms=now_ms)
    seqs = [int(r.seq) for r in wanted if (r.session_id, r.turn_id) in went]
    shown = _shown(store, seqs, notes, str(lead_db))
    return count(notes, rows, shown, went)


def track(
    notes: Sequence[Note],
    lead_db: Path | None,
    chat_db: Path | None,
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Each note's track, by registry id: counts only. ``{}`` without both records.

    Read at most every :data:`TTL_S` seconds for the same notes; a note that
    comes or goes (taken back, forgotten) is counted again at once.
    """
    if not notes or lead_db is None or chat_db is None:
        return {}
    lead_db, chat_db = Path(lead_db), Path(chat_db)
    if not lead_db.is_file() or not chat_db.is_file():
        return {}
    stamp = time.time() if now is None else now
    place = (str(lead_db), str(chat_db))
    key = _key((n.change_id, n.text, n.since_ms) for n in notes)
    with _lock:
        cached = _cache.get(place)
        if cached is not None and cached[1] == key and stamp - cached[0] < TTL_S:
            return cached[2]
        try:
            found = _read(notes, lead_db, chat_db, now_ms=int(stamp * 1000))
        except Exception:  # noqa: BLE001 — the page lists the notes without their track
            log.info("self-improvement: the notes' track could not be read", exc_info=True)
            found = {}
        _cache[place] = (stamp, key, found)
    return found
