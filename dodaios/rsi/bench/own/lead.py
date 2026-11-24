"""first_move tasks from the person's own lead turns: only where the record gives a truth.

A recorded lead turn (``lead_turns.db``) says what the lead was given and what
it did first. Whether that first move was right, the record does not say; what
the person did next sometimes does (``dodaios.evals.agent_score.signals``):

* **corrected, then accepted.** The person's next message corrected the turn
  or asked the same again (``follow_up_kind``: ``correction`` or ``repeat``,
  within :data:`REPEAT_WINDOW_MS`), the turn after it went through (it ended
  ``done`` and nothing corrected, repeated or undid it), and its first move
  differs from the corrected one. Then the later first move is the truth for
  the earlier turn's input: a task that can show a gain (``Role.GAIN``). When
  both first moves agree, the correction was about something else, and the
  pair says nothing about the first move.
* **accepted.** A turn that went through and was not corrected, repeated or
  undone: its first move is what the person let stand. A task that guards
  against regressions (``Role.GUARD``): a change that replays it differently
  breaks something that worked, but beating it proves nothing.

Left out: a turn that carried a running task on (no request of the person's),
one that answered nothing, one whose first move only loaded a tool and the
record does not say which, one the chat record has no request for, and one
still too new to know whether it is corrected.

Turns linked by corrections and repeats are one piece of work and share a
group, so the corrected turn and the turn that got it right always land in the
same split.

A task holds no words of the person's: it names its row in ``lead_turns.db``
and the tools of the right move. The replay reads the row when it runs; a row
that is gone (the chat was deleted, the row aged out) retires its task.

No model is called.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.rsi.bench.first_move import LOADING_TOOLS, NO_TOOL, Expect, tool_name
from dodaios.rsi.bench.model import Domain, Role, Source, Task, task_id
from dodaios.rsi.bench.store import BenchStore

__all__ = ["REPEAT_WINDOW_MS", "Mined", "mine", "take_in"]

log = logging.getLogger(__name__)

#: A follow-up counts as one about the turn within this long (the score's own window).
REPEAT_WINDOW_MS: Final[int] = 30 * 60 * 1000
_CORRECTED: Final = frozenset({"correction", "repeat"})


@dataclass(slots=True)
class Mined:
    tasks: list[Task] = field(default_factory=list)
    #: Why turns were left out, counted.
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def _move(row: Any) -> str | None:
    """The tool a recorded first move called (``"none"`` for text only); ``None``: unknown."""
    if row.first_kind == "text":
        return NO_TOOL
    if row.first_kind != "tool":
        return None
    name = str(row.first_tool or "")
    if name in LOADING_TOOLS:
        # An older record kept the schema load. Its query names the tool only as
        # "select:<one tool>"; anything else does not say which tool came next.
        query = str((row.first_args or {}).get("query") or "")
        picked = query.removeprefix("select:") if query.startswith("select:") else ""
        if not picked or "," in picked:
            return None
        name = picked
    return tool_name(name) or None


def _check(tool: str, role: Role, *, was: str = "") -> dict[str, Any]:
    expect = Expect(tools=(tool,))
    out: dict[str, Any] = {
        "expect": expect.to_json(),
        "opening": expect.expects_tool,
        "role": role.value,
    }
    if was:
        out["was"] = was
    return out


def _task(row: Any, group: str, check: dict[str, Any], role: Role) -> Task:
    return Task(
        id=task_id(Domain.FIRST_MOVE, Source.MINED, f"{row.session_id}:{row.turn_id}:{role}"),
        domain=Domain.FIRST_MOVE,
        source=Source.MINED,
        group=group,
        payload={"turn": {"seq": int(row.seq), "session": row.session_id, "turn": row.turn_id}},
        check=check,
        created_ms=int(row.ts_ms),
    )


def mine(rows: Sequence[Any], chat: Sequence[Any], *, now_ms: int) -> Mined:
    """Tasks from recorded lead turns (``rows``) and the chat's turns (``chat``).

    ``chat`` is the lead's turns as the score of daily use reads them
    (``agent_score.turns.Turn``: ``turn_id``, ``text``, ``ts_ms``, ``status``),
    oldest first; it says what the person asked and what came after.
    """
    from dodaios.evals.agent_score.signals import follow_up_kind

    out = Mined()
    recorded = {(r.session_id, r.turn_id): r for r in rows}
    by_session: dict[str, list[Any]] = {}
    for turn in chat:
        by_session.setdefault(turn.session_id, []).append(turn)
    for session, turns in by_session.items():
        turns.sort(key=lambda t: t.ts_ms)
        kinds: list[str] = []
        for here, after in zip(turns, turns[1:], strict=False):
            soon = after.ts_ms - here.ts_ms <= REPEAT_WINDOW_MS
            kinds.append(follow_up_kind(here.text, after.text) if soon else "")
        kinds.append("")
        group = ""
        for index, turn in enumerate(turns):
            linked = index > 0 and kinds[index - 1] in _CORRECTED
            if not linked:
                group = f"lead:{session}:{turn.turn_id}"
            row = recorded.get((session, turn.turn_id))
            if row is None:
                continue  # not a recorded lead turn (from before the record, a slash command)
            if row.continuation:
                out.skip("carried a running task on")
                continue
            move = _move(row)
            if move is None:
                out.skip("the record does not say which tool it called")
                continue
            last = index == len(turns) - 1
            if last and now_ms - turn.ts_ms <= REPEAT_WINDOW_MS:
                out.skip("too new to know whether it was corrected")
                continue
            follow = kinds[index]
            if follow in _CORRECTED:
                later = _accepted_after(turns, kinds, index, recorded, now_ms=now_ms)
                if later is None:
                    out.skip("corrected, and nothing after it went through")
                    continue
                truth = _move(later)
                if truth is None or truth == move:
                    out.skip("corrected, but the first move stayed the same")
                    continue
                check = _check(truth, Role.GAIN, was=move)
                out.tasks.append(_task(row, group, check, Role.GAIN))
            elif follow == "undo" or turn.status != "done":
                out.skip("undone, or it did not finish")
            else:
                out.tasks.append(_task(row, group, _check(move, Role.GUARD), Role.GUARD))
    return out


def _accepted_after(
    turns: Sequence[Any],
    kinds: Sequence[str],
    index: int,
    recorded: dict[tuple[str, str], Any],
    *,
    now_ms: int,
) -> Any | None:
    """The recorded turn that went through after the corrections that follow ``index``."""
    at = index + 1
    while at < len(turns):
        turn = turns[at]
        if kinds[at] in _CORRECTED:
            at += 1
            continue  # corrected again: the next one is the candidate
        if kinds[at] == "undo" or turn.status != "done":
            return None
        if at == len(turns) - 1 and now_ms - turn.ts_ms <= REPEAT_WINDOW_MS:
            return None  # too new to know whether it went through
        return recorded.get((turn.session_id, turn.turn_id))
    return None


def take_in(
    bench: BenchStore,
    rows: Sequence[Any],
    chat: Sequence[Any],
    *,
    now_ms: int,
    alive: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Store new tasks and retire those whose recorded turn is gone. Returns the counts."""
    if bench.readonly:
        return {}
    found = mine(rows, chat, now_ms=now_ms)
    new = bench.put_tasks(found.tasks)
    seqs = {int(r.seq) for r in rows} if alive is None else set(alive)
    gone = [
        t.id
        for t in bench.tasks(Domain.FIRST_MOVE, source=Source.MINED)
        if int((t.payload.get("turn") or {}).get("seq") or 0) not in seqs
    ]
    if gone:
        bench.retire(gone)
    corrected = sum(1 for t in found.tasks if t.check.get("role") == Role.GAIN.value)
    return {
        "lead_turns": new,
        "lead_corrected": corrected,
        "lead_retired": len(gone),
        "lead_skipped": dict(found.skipped),
    }


def read(turns: Any, chat_db: Path) -> tuple[list[Any], list[Any]]:
    """The recorded lead turns (a ``LeadTurnStore``) and the lead's chat turns. Read-only."""
    from dodaios.evals.agent_score.turns import read_lead_turns

    rows = list(turns.moves())
    if not rows:
        return [], []
    since = min(int(r.ts_ms) for r in rows) - REPEAT_WINDOW_MS
    return rows, read_lead_turns(Path(chat_db), since_ms=max(0, since))
