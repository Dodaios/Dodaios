"""The compact index of repositories the lead reads with a message.

The lead works across many repositories in one conversation. This renders what
it needs to keep them apart in a few lines: which ones have agents working,
which wait for the person, and where a pull request is red. One line per
repository *in play*, the rest as a count:

    [Repos, rev 41: 4 of 23 in play. Detail: workspace-orchestrate status project=<name>; ...]
    notes: 3 busy, 1 waits for you; PR 2, 1 failing; main dirty
    shop-web: 2 wait for you; PR 1 passing
    More in play: sdk-python (PR failing), data-jobs (named)
    Quiet: 19 repos.

Two properties matter more than completeness:

* **It stays the same while nothing changes.** No commit ids, ages or branch
  names: they would change the bytes on every look and with them the prompt
  cache of the conversation it rides in. ``rev`` moves only when the content
  does.
* **It never exceeds its budget.** A repository that waits for the person is
  never dropped, only shortened; everything else gives way in the order of how
  much it matters.

Pure: this module reads nothing. :mod:`repo_cards` gathers the states.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

__all__ = ["BUDGET_CHARS", "RepoState", "body_digest", "in_play", "render", "tier"]

#: The hard ceiling of the rendered index.
BUDGET_CHARS: Final[int] = 1_200
_DETAIL: Final[str] = "Detail: workspace-orchestrate status project=<name>; pull-requests-list."
#: Kept free for the line that names the repositories without a line of their own.
_OVERFLOW_ROOM: Final[int] = 160


@dataclass(frozen=True, slots=True)
class RepoState:
    """What the index says about one repository."""

    name: str
    #: Coding threads working right now.
    busy: int = 0
    #: Coding threads that wait for the person (a question, a plan, an approval).
    waits: int = 0
    #: The person's open pull requests in this repository, and how their checks stand.
    prs: int = 0
    prs_failing: int = 0
    prs_running: int = 0
    #: A pull request in conflict, or a checkout with unresolved conflicts.
    conflict: bool = False
    #: The main checkout has uncommitted changes.
    dirty: bool = False
    #: An agent's done gate gave up on a branch here.
    gate_stuck: bool = False
    #: The current message names this repository.
    named: bool = False
    #: Among the repositories this conversation handed work to most recently.
    recent: bool = False


def tier(state: RepoState) -> int:
    """How much a repository matters right now: 1 most, 0 not in play."""
    if state.waits or state.gate_stuck:
        return 1
    if state.busy:
        return 2
    if state.named:
        return 3
    if state.recent:
        return 4
    if state.prs_failing or state.conflict:
        return 5
    return 0


def in_play(states: Iterable[RepoState]) -> list[RepoState]:
    """The repositories worth a line, most important first, by name within a tier."""
    chosen = [state for state in states if tier(state)]
    return sorted(chosen, key=lambda s: (tier(s), s.name.lower(), s.name))


def _runs(state: RepoState) -> str:
    parts: list[str] = []
    if state.busy:
        parts.append(f"{state.busy} busy")
    if state.waits:
        parts.append(f"{state.waits} {'waits' if state.waits == 1 else 'wait'} for you")
    return ", ".join(parts) or "idle"


def _pulls(state: RepoState) -> str:
    if not state.prs:
        return ""
    if state.prs_failing:
        return f"PR {state.prs}, {state.prs_failing} failing"
    if state.prs_running:
        return f"PR {state.prs} running"
    return f"PR {state.prs} passing"


def _flags(state: RepoState) -> str:
    flags = [
        text
        for wanted, text in (
            (state.conflict, "conflict"),
            (state.dirty, "main dirty"),
            (state.gate_stuck, "gate stuck"),
        )
        if wanted
    ]
    return ", ".join(flags)


def _line(state: RepoState) -> str:
    parts = [part for part in (_runs(state), _pulls(state), _flags(state)) if part]
    return f"{state.name}: " + "; ".join(parts)


def _short(state: RepoState) -> str:
    """A repository that waits for the person, in as few characters as it takes."""
    if state.waits:
        return f"{state.name}: {state.waits} wait"
    return f"{state.name}: gate stuck"


def _why(state: RepoState) -> str:
    """One word on why a repository without a line of its own is in play."""
    if state.busy:
        return "busy"
    if state.named:
        return "named"
    if state.prs_failing:
        return "PR failing"
    if state.conflict:
        return "conflict"
    return "recent"


def _overflow(rest: Sequence[RepoState], room: int) -> str:
    """``More in play: a (busy), b (named), +3`` within ``room`` characters."""
    if not rest or room <= 0:
        return ""
    head = "More in play: "
    shown: list[str] = []
    for index, state in enumerate(rest):
        entry = f"{state.name} ({_why(state)})"
        left = len(rest) - index - 1
        tail = f", +{left}" if left else ""
        candidate = head + ", ".join([*shown, entry]) + tail
        if len(candidate) > room:
            break
        shown.append(entry)
    hidden = len(rest) - len(shown)
    if not shown:
        text = f"More in play: +{hidden}"
        return text if len(text) <= room else ""
    return head + ", ".join(shown) + (f", +{hidden}" if hidden else "")


def _body(states: Sequence[RepoState], *, total: int, header_room: int, budget: int) -> list[str]:
    chosen = in_play(states)
    quiet = max(0, total - len(chosen))
    quiet_line = f"Quiet: {quiet} repo{'' if quiet == 1 else 's'}." if quiet else ""
    # Reserved before any line is placed: the header, the quiet line, room for
    # an overflow line that still names a few repositories, and the newlines.
    reserve = header_room + len(quiet_line) + _OVERFLOW_ROOM + 3
    room = budget - reserve
    lines: list[str] = []
    rest: list[RepoState] = []
    for state in chosen:
        full = _line(state)
        if len(full) + 1 <= room:
            lines.append(full)
            room -= len(full) + 1
        elif tier(state) == 1:
            # Never dropped: the person is waited for there.
            short = _short(state)
            lines.append(short)
            room -= len(short) + 1
        else:
            rest.append(state)
    used = header_room + len(quiet_line) + sum(len(line) + 1 for line in lines) + 2
    more = _overflow(rest, budget - used)
    return [*lines, *([more] if more else []), *([quiet_line] if quiet_line else [])]


def body_digest(states: Sequence[RepoState], *, total: int, budget: int = BUDGET_CHARS) -> str:
    """A digest of what the index would say, without its ``rev``.

    The keeper of the index compares digests and raises ``rev`` only when one
    differs, so the rendered text is byte-identical while nothing changed.
    """
    lines = _body(states, total=total, header_room=_header_room(total), budget=budget)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _header(rev: int, shown: int, total: int) -> str:
    return f"[Repos, rev {rev}: {shown} of {total} in play. {_DETAIL}]"


def _header_room(total: int) -> int:
    # The widest header this install can produce: every count at its widest.
    return len(_header(999_999, total, total))


def render(
    states: Sequence[RepoState], *, total: int, rev: int, budget: int = BUDGET_CHARS
) -> str:
    """The index text, or ``""`` when no repository is in play.

    ``total`` counts every repository the install knows, in play or not.
    """
    chosen = in_play(states)
    if not chosen:
        return ""
    total = max(total, len(chosen))
    lines = _body(states, total=total, header_room=_header_room(total), budget=budget)
    text = "\n".join([_header(rev, len(chosen), total), *lines])
    # The reserve above makes this hold; cutting is the last line of defence
    # against a budget smaller than a header.
    return text if len(text) <= budget else text[:budget]
