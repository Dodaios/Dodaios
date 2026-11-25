"""The runner of the brief domain: replay a lead turn up to the brief it writes, and score it.

A brief task is a request the person once typed into a coding CLI, and the
change that was merged for it (``past_work``). The replay asks: what brief
does the lead write today when that request reaches it?

**What the lead does first.** Replayed on the lead's own input, a coding
request never makes the lead write the brief at once: it reads first. Most
often it asks for the brief kit (``delegate`` with ``options.prepare``; the
brief line says "look first"), which in the app only reads the repository and
sends nothing; sometimes it searches the repository with its own folder tools
(``Grep``, ``Read``, ``Glob``, ``Ls``). So a replay answers exactly these calls
that only read, as the app would, from the repository as it was when the work
started (``base``; read from git's objects, nothing checked out or written:
:mod:`dodaios.rsi.bench.at_commit`, :mod:`dodaios.rsi.bench.brief_world`): the kit once, built
for the lead's own wording, and up to ``lead_cli.MAX_SERVED`` calls in all.
The first call that is not answered is the move. When it hands the work over
(``delegate``), its text is the brief, scored by
:func:`dodaios.rsi.bench.brief.score`.

**What the lead is given.** The input of one recorded lead turn, pinned for
weeks (:class:`Template`): its system prompt, and its message with the
person's words replaced by the request and one fixed line
(:data:`REPOSITORY_LINE`). The person typed the request into a coding agent's
session in that repository, so the line says what that choice said: a coding
agent is to do it, in that repository. Without it the lead reads "fix this" as
addressed to itself and investigates the code the way an agent would (a real
replay read six files and was still reading). The standing lines are switched
as the run's overlay says (:func:`dodaios.rsi.lines.apply`). Both arms of a
comparison get the same template and the same fixed line.

**How a run ends.**

* a hand-off (``delegate`` that is not the kit request): the brief is scored;
* a text answer, or a question on the card: no brief, score 0;
* any other call (a tool that does more than read the repository, a path
  outside it, the kit asked for again, more look-ups than a replay answers):
  void, with what it was;
* a task whose repository or commit is not on this machine, or whose request
  showed a picture, is void with the reason, before anything is spent.

**Cost.** The lead's message and the brief, in tokens (characters / 4): the
line under test rides in every message, and the brief is what the agent then
reads. A run that ends without a brief costs as much as the dearest brief the
domain expects (:data:`NO_BRIEF_TOKENS`): failing to hand the work over must
never look cheaper than handing it over.

**What it spends.** One replay is one CLI run: one call against the round's
budget, and one more for every answered call (each answer makes the CLI ask the
model again). The budget is the one the first_move domain uses
(:mod:`dodaios.rsi.budget`). It is asked before anything is read from the
repository, so once the round has to stop (the person is back, the backend let
go, the calls are spent) a task costs no git process either: it is void as
held by the budget, and the comparison carries on in the next round.

What a replay cannot see: a look-up that is not a folder tool (the shell, the
person's memory, the web), the brief check that may send a brief back once
(the first brief is scored), the conversation before the turn, and everything
after the hand-off.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from dodaios.rsi import lines
from dodaios.rsi.budget import Budget

from . import brief, replay_tools
from .at_commit import CommitFiles
from .first_move import Move
from .lead_replay import LeadInput, Platform, same_model
from .model import Measured, Task

__all__ = [
    "NO_BRIEF_TOKENS",
    "REPOSITORY_LINE",
    "WORLD",
    "BriefWorld",
    "Template",
    "lead_input",
    "run",
    "template_of",
]

#: The name a brief world has among a night's worlds.
WORLD: Final = "brief"
#: The fixed line put after a mined request. The person typed the request into a
#: coding agent's session in the repository: the lead is told both.
REPOSITORY_LINE: Final[str] = (
    "\n\n(Have a coding agent do this, in the repository {repo}, local folder {folder}.)"
)
#: What a run that ends without a brief costs, besides the message: a long brief.
NO_BRIEF_TOKENS: Final[int] = 2_000
#: The question card: asking the person instead of handing the work over is no brief.
_ASKS: Final[frozenset[str]] = frozenset({"society_ask_user"})
_PICTURES: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic"}
)
_CATCH_UP: Final = re.compile(r"\A\s*<since_your_last_turn>.*?</since_your_last_turn>\s*", re.S)
_EFFORT_NOTE: Final = re.compile(r"<jarvis_turn_settings>.*?</jarvis_turn_settings>\n\n", re.S)


def _harness(name: str) -> str:
    from dodaios.agent_chat import dodaios_harness

    return str(getattr(dodaios_harness, name))


@dataclass(frozen=True, slots=True)
class Template:
    """The lead's input of one recorded turn, with the person's words taken out."""

    system: str
    #: What stands in front of the person's words (the effort note).
    head: str
    #: The standing lines after them and the reply-language line, as recorded.
    tail: str

    @property
    def digest(self) -> str:
        blob = "\x00".join((self.system, self.head, self.tail))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def template_of(system: str, message: str) -> Template | str:
    """The template a recorded lead turn gives, or why it gives none."""
    if not system.strip():
        return "the recorded turn has no system prompt"
    effort = _harness("EFFORT_LINE")
    at = message.find(effort)
    if at < 0:
        return "the recorded message carries no standing lines"
    secret = _harness("SECRET_FIELD_LINE")
    said_end = at - len(secret) if message[:at].endswith(secret) else at
    before = _CATCH_UP.sub("", message[:said_end], count=1)
    note = _EFFORT_NOTE.search(before)
    head = note.group(0) if note is not None and note.start() == 0 else ""
    return Template(system=system, head=head, tail=message[at:])


def lead_input(template: Template, said: str) -> LeadInput | str:
    """What the lead is given for ``said`` today, under the active overlay; or why nothing."""
    from dodaios.agent_chat.secret_requests import SECRET_NOUN

    secret = _harness("SECRET_FIELD_LINE") if SECRET_NOUN.search(said) else ""
    message = lines.apply(template.head + said + secret + template.tail, lines.switches())
    if message is None:
        return "the lead's input has no place for a line this arm changes"
    return LeadInput(template.system, message)


#: A repository at a commit, read in place (repository id, commit), or why there is none.
CommitOf = Callable[[str, str], "CommitFiles | str"]
#: The text the app's kit request answers with: the task, the repository at its
#: commit, and the arguments of the lead's call.
KitAnswer = Callable[[Task, CommitFiles, Mapping[str, Any]], str]
#: What a read-only folder tool answers in the repository at a commit: the text and
#: whether it is an error, or ``None`` when the call reaches outside the repository.
LookAnswer = Callable[[CommitFiles, str, Mapping[str, Any]], "tuple[str, bool] | None"]
#: Replays one turn, answering the calls ``serve`` answers (``lead_cli.ClaudeReplay``).
BriefDriver = Callable[..., Move]


@dataclass(slots=True)
class BriefWorld:
    """What a night needs to run brief tasks."""

    platform: Platform
    driver: BriefDriver
    #: The night's budget, the same object the first_move world asks.
    budget: Budget
    template: Template
    #: Repository id -> the person's clone of it on this machine.
    clones: Mapping[str, Path]
    commit: CommitOf
    kit: KitAnswer
    look: LookAnswer


def _pictures(payload: Mapping[str, Any]) -> list[str]:
    found = payload.get("attached") or ()
    return [str(p) for p in found if PurePosixPath(str(p)).suffix.lower() in _PICTURES]


def _brief_text(args: Mapping[str, Any]) -> str:
    """The brief an agent receives from a hand-off: the task and its two optional parts."""
    from dodaios.brain.delegate_tool import _brief  # noqa: PLC2701 - the hand-off's own join

    return _brief(
        str(args.get("task") or ""),
        str(args.get("context") or ""),
        str(args.get("completion_criteria") or ""),
    )


class _Reads:
    """The calls one replay answers, each paid for before it is answered."""

    def __init__(self, task: Task, world: BriefWorld, files: CommitFiles) -> None:
        self._task, self._world, self._files = task, world, files
        self.kits = 0
        self.looks = 0
        #: A look-up reached outside the repository (it was not answered).
        self.outside = ""
        #: Why the budget refused an answer ("" while none was refused).
        self.cut = ""

    def __call__(self, tool: str, args: Mapping[str, Any]) -> str | tuple[str, bool] | None:
        kit = replay_tools.asks_kit(tool, args)
        if kit and self.kits:
            return None  # the kit asked for again: the move
        found: str | tuple[str, bool] | None
        if kit:
            found = None
        elif tool in replay_tools.LOOKUPS:
            found = self._world.look(self._files, tool, args)
            if found is None:
                self.outside = tool
                return None  # outside the repository: the move
        else:
            return None
        why = self._world.budget.take()  # the answer makes the CLI ask the model again
        if why:
            self.cut = why
            return None
        if kit:
            self.kits += 1
            return self._world.kit(self._task, self._files, args)
        self.looks += 1
        return found

    def how(self) -> str:
        looked = f"{self.looks} look-up{'s' if self.looks != 1 else ''}"
        if self.kits:
            return f"after the kit and {looked}" if self.looks else "after the kit"
        return f"without the kit, after {looked}" if self.looks else "without the kit"


@dataclass(frozen=True, slots=True)
class _Ready:
    """What a replay of one task starts from."""

    lead: LeadInput
    #: The repository at the task's commit, read in place.
    files: CommitFiles


def _ready(task: Task, world: BriefWorld) -> _Ready | Measured:
    """What the replay needs, or the void result that says why it cannot run. Spends nothing.

    The budget is asked before the repository is: a round that has to stop
    starts no git process for a task it will not replay.
    """
    payload = task.payload
    repo = str(payload.get("repo") or "")
    base = str(payload.get("base") or "")
    request = str(payload.get("request") or "")
    if not (repo and base and request):
        why = "the task names no repository, commit or request"
        return Measured(0.0, 0, why, void=why)
    shown = _pictures(payload)
    if shown:
        why = f"the request showed a picture ({shown[0]}); a replay cannot show it"
        return Measured(0.0, 0, why, void="the request showed a picture")
    clone = world.clones.get(repo)
    if clone is None:
        why = f"the repository {repo} is not on this machine"
        return Measured(0.0, 0, why, void=why)
    found = lead_input(world.template, request + REPOSITORY_LINE.format(repo=repo, folder=clone))
    if isinstance(found, str):
        return Measured(0.0, 0, found, void=found)
    held = world.budget.held()
    if held:
        return Measured(0.0, 0, held, void=f"budget: {held}")
    files = world.commit(repo, base)
    if isinstance(files, str):
        return Measured(0.0, 0, files, void=files)
    return _Ready(found, files)


def _not_a_brief(move: Move, reads: _Reads) -> tuple[str, str] | None:
    """Why the move is no hand-off the replay can score: ``(detail, void)``; ``None`` for one."""
    if replay_tools.asks_kit(str(move.tool), move.args):
        why = "it asked for the brief kit a second time"
        return why, why
    if move.tool in replay_tools.LOOKUPS:
        if reads.outside:
            why = f"it read outside the repository ({move.tool})"
        else:
            why = f"it looked further than a replay answers ({move.tool} after {reads.looks})"
        return why, why.partition(" (")[0]
    if move.tool != "delegate":
        why = f"it used {move.tool} before the hand-off; a replay answers only what reads the code"
        return why, "used a tool a replay cannot answer"
    return None


def _scored(task: Task, world: BriefWorld, ready: _Ready, move: Move, reads: _Reads) -> Measured:
    """The result of one replay from the move it ended on."""
    seat = f"{world.platform.cli}:{move.model or world.platform.model}"
    calls = 1 + reads.kits + reads.looks
    message = round(len(ready.lead.message) / 4)
    failed = message + NO_BRIEF_TOKENS
    if reads.cut:
        return Measured(0.0, 0, reads.cut, seat=seat, void=f"budget: {reads.cut}", calls=calls)
    if not same_model(world.platform.model, move.model):
        why = f"the model changed: asked {world.platform.model}, answered {move.model}"
        return Measured(0.0, 0, why, seat=seat, void="the model changed", calls=calls)
    if move.error:
        return Measured(0.0, 0, move.error[:200], seat=seat, void="could not run", calls=calls)
    if move.tool is None or move.tool in _ASKS:
        what = "answered in text" if move.tool is None else "asked the person first"
        return Measured(0.0, failed, f"no brief: it {what}", seat=seat, calls=calls)
    other = _not_a_brief(move, reads)
    if other is not None:
        return Measured(0.0, 0, other[0], seat=seat, void=other[1], calls=calls)
    text = _brief_text(move.args)
    if not text.strip():
        return Measured(0.0, failed, "no brief: the hand-off was empty", seat=seat, calls=calls)
    scored = brief.score(task, text)
    detail = f"{reads.how()}; {scored.detail}"[:200]
    return Measured(scored.score, message + scored.tokens, detail, seat=seat, calls=calls)


def run(task: Task, world: BriefWorld) -> Measured:
    """Replay one task under the active overlay and score the brief the lead writes."""
    ready = _ready(task, world)
    if isinstance(ready, Measured):
        return ready
    try:
        refused = world.budget.take()
        if refused:
            return Measured(0.0, 0, refused, void=f"budget: {refused}")
        reads = _Reads(task, world, ready.files)
        move = world.driver(ready.lead, world.platform, reads)
        return _scored(task, world, ready, move, reads)
    finally:
        ready.files.close()
