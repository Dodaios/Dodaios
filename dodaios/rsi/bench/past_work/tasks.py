"""Benchmark tasks from coding work the person already had done.

A recorded session says what the person asked for and which pull request the
session opened (:mod:`.sessions`). The repository says what was merged for
that pull request (:mod:`.history`). Joined, they are a task with a known
answer, and nobody had to write one:

* a **brief** task: given the person's request and the repository as it was,
  does a brief name the files the merged change touched, its tests, and what
  the person had to say afterwards?
* a **coding** task: given the same request and state, do the tests that were
  merged with the work pass? Only when the change brought tests and code.

Both tasks of one pull request share a group, so they are one piece of work.

**Which words asked for which pull request.** Guessing here would grade the
assistant against the wrong answer, so the rule is strict and a pull request
it cannot place is left out and counted:

* the first pull request of a session: the request is the first thing the
  person said that is long enough to be one; what they said after it, before
  the pull request was opened, is what they had to add. A session in which the
  person said more than :data:`MAX_SAID_BEFORE_FIRST` things before the first
  pull request is a conversation, not one request, and is left out;
* a later pull request of the same session: only when the person said exactly
  one thing since the previous one. With more, which of them asked for it is a
  guess.

Nothing a tool, a web page or the agent wrote is ever taken as the request. A
request with credential-shaped text is left out. No model is called.

**A request the assistant composed.** When the assistant hands work to a
coding agent, the session opens with a brief, which is nobody's words. A brief
cannot be the input of a brief task, so such a piece gives only the coding
task, marked ``composed``. :func:`logged_briefs` knows the briefs the app sent
(``briefs.db``); a brief from before that log existed cannot be told apart.

**A request that points at a file.** ``@folder/shot.png`` in a request names a
file the agent was shown. The paths are listed as ``attached``, so a run can
tell a request it can serve whole from one whose picture is gone.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from dodaios.rsi.bench.model import Domain, Source, Task, task_id
from dodaios.rsi.bench.past_work.history import MergedChange
from dodaios.rsi.bench.past_work.sessions import PastSession

__all__ = [
    "MAX_SAID_BEFORE_FIRST",
    "MIN_REQUEST_WORDS",
    "LeftOut",
    "Mined",
    "Piece",
    "logged_briefs",
    "mine",
    "pieces",
]

#: Fewer words than this steer or confirm ("yes, go on"); they do not ask for work.
MIN_REQUEST_WORDS: Final = 5
#: More things said than this before the first pull request: a conversation, not one request.
MAX_SAID_BEFORE_FIRST: Final = 4
_MAX_REQUEST_CHARS: Final = 8000
_MAX_LATER: Final = 8
_MAX_LATER_CHARS: Final = 2000
#: A file the person pointed the agent at: ``@`` and a path with an extension.
_ATTACHED: Final = re.compile(r"(?:^|(?<=\s))@([^\s@]+\.[A-Za-z0-9]{1,5})(?=$|[\s,;:)])")
#: How much of a logged brief has to appear in a session's opening words.
_BRIEF_HEAD_CHARS: Final = 240


class LeftOut(StrEnum):
    """Why an opened pull request became no task."""

    NO_REQUEST = "no_request"  # opened without the person asking for anything in words
    CONVERSATION = "conversation"  # too much was said before it to call one thing the request
    AMBIGUOUS = "ambiguous"  # several things said since the previous pull request
    NOT_MERGED = "not_merged"  # not on the default branch of a repository that was given
    REVERTED = "reverted"  # merged and taken back
    CREDENTIAL = "credential"  # the person's words hold credential-shaped text
    DUPLICATE = "duplicate"  # another session already accounts for this pull request


@dataclass(frozen=True, slots=True)
class Piece:
    """One request and the pull request a session opened for it."""

    agent: str
    session_id: str
    repo: str
    number: int
    opened_ms: int
    request: str
    #: What the person said after the request and before the pull request was opened.
    told_later: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Mined:
    """The tasks, and an account of every opened pull request that became none."""

    tasks: tuple[Task, ...] = ()
    #: Sessions that opened at least one pull request.
    sessions: int = 0
    #: Pull requests those sessions opened.
    opened: int = 0
    left_out: Mapping[str, int] = field(default_factory=dict)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_request(text: str) -> bool:
    return len(text.split()) >= MIN_REQUEST_WORDS


def pieces(session: PastSession) -> tuple[list[Piece], Counter[LeftOut]]:
    """The requests of one session that can be placed, and why the others cannot."""
    found: list[Piece] = []
    left: Counter[LeftOut] = Counter()
    said = sorted(session.said, key=lambda item: item.ts_ms)
    cursor = 0
    for index, pull in enumerate(sorted(session.opened, key=lambda item: item.ts_ms)):
        before: list[str] = []
        while cursor < len(said) and said[cursor].ts_ms <= pull.ts_ms:
            before.append(said[cursor].text)
            cursor += 1
        request, later = "", ()
        if index == 0:
            start = next((i for i, text in enumerate(before) if _is_request(text)), None)
            if start is None:
                left[LeftOut.NO_REQUEST] += 1
                continue
            if len(before) > MAX_SAID_BEFORE_FIRST:
                left[LeftOut.CONVERSATION] += 1
                continue
            request, later = before[start], tuple(before[start + 1 :])
        elif not before or (len(before) == 1 and not _is_request(before[0])):
            left[LeftOut.NO_REQUEST] += 1
            continue
        elif len(before) > 1:
            left[LeftOut.AMBIGUOUS] += 1
            continue
        else:
            request = before[0]
        found.append(
            Piece(
                agent=session.agent,
                session_id=session.session_id,
                repo=pull.repo,
                number=pull.number,
                opened_ms=pull.ts_ms,
                request=_clip(request, _MAX_REQUEST_CHARS),
                told_later=tuple(_clip(text, _MAX_LATER_CHARS) for text in later[:_MAX_LATER]),
            )
        )
    return found, left


def _has_secret(piece: Piece) -> bool:
    from dodaios.memory.learning.guard import contains_secret

    return contains_secret("\n".join((piece.request, *piece.told_later)))


def _tasks(piece: Piece, change: MergedChange, *, composed: bool) -> list[Task]:
    key = f"{change.repo}#{change.number}"
    where: dict[str, object] = {
        "repo": change.repo,
        "base": change.parent,
        "request": piece.request,
    }
    attached = sorted(set(_ATTACHED.findall(piece.request)))
    if attached:
        where["attached"] = attached
    made: list[Task] = []
    if not composed:
        made.append(
            Task(
                id=task_id(Domain.BRIEF, Source.MINED, key),
                domain=Domain.BRIEF,
                source=Source.MINED,
                group=key,
                payload=where,
                check={
                    "commit": change.commit,
                    "files": list(change.files),
                    "tests": list(change.tests),
                    "told_later": list(piece.told_later),
                },
                created_ms=change.merged_ms,
            )
        )
    if change.tests and change.sources:
        # The agent that did the work was told these things too.
        given = {**where, "told_later": list(piece.told_later)}
        if composed:
            given["composed"] = True
        made.append(
            Task(
                id=task_id(Domain.CODING, Source.MINED, key),
                domain=Domain.CODING,
                source=Source.MINED,
                group=key,
                payload=given,
                check={"commit": change.commit, "tests": list(change.tests)},
                created_ms=change.merged_ms,
            )
        )
    return made


def _flat(text: str) -> str:
    return " ".join(text.split())


def logged_briefs() -> Callable[[str], bool] | None:
    """Whether a text opens with a brief the app sent; ``None`` when there is no log."""
    from dodaios.briefs import log as brief_log
    from dodaios.core import config as core_config

    path = core_config.DATA_DIR / brief_log.DB_NAME
    if not path.is_file():
        return None
    store = brief_log.BriefLog(path)
    try:
        rows = store.rows(limit=brief_log.MAX_BRIEFS)
    finally:
        store.close()
    heads = {
        head
        for row in rows
        if (head := _flat(str(row.get("brief_text") or ""))[:_BRIEF_HEAD_CHARS])
    }
    if not heads:
        return None
    return lambda text: any(head in _flat(text) for head in heads)


def mine(
    sessions: Iterable[PastSession],
    changes: Mapping[str, Mapping[int, MergedChange]],
    *,
    composed: Callable[[str], bool] | None = None,
) -> Mined:
    """Tasks from ``sessions``, for the repositories whose merged changes are given.

    ``changes`` maps a repository id to its merged pull requests
    (:func:`.history.merged_changes`). A pull request of another repository, or
    one that is not merged there, is left out as ``not_merged``. ``composed``
    says whether a request is a brief the assistant wrote (:func:`logged_briefs`).
    """
    left: Counter[LeftOut] = Counter()
    placed: dict[tuple[str, int], Piece] = {}
    seen = opened = 0
    for session in sessions:
        seen += 1
        opened += len(session.opened)
        found, missed = pieces(session)
        left.update(missed)
        for piece in found:
            key = (piece.repo, piece.number)
            earlier = placed.get(key)
            if earlier is not None:
                left[LeftOut.DUPLICATE] += 1
                if earlier.opened_ms <= piece.opened_ms:
                    continue
            placed[key] = piece
    tasks: list[Task] = []
    for (repo, number), piece in sorted(placed.items()):
        change = changes.get(repo, {}).get(number)
        if change is None:
            left[LeftOut.NOT_MERGED] += 1
        elif change.reverted:
            left[LeftOut.REVERTED] += 1
        elif _has_secret(piece):
            left[LeftOut.CREDENTIAL] += 1
        else:
            written = composed is not None and composed(piece.request)
            tasks.extend(_tasks(piece, change, composed=written))
    return Mined(
        tasks=tuple(tasks),
        sessions=seen,
        opened=opened,
        left_out={reason.value: count for reason, count in sorted(left.items())},
    )
