"""Whether the done-when points of a brief hold, read from what the run left behind.

An agent's "done" is a claim, and measured on real runs such claims are wrong
often enough that the lead must not pass them on unread. When a thread ends
the turn it took for an order, each done-when point of that order is held
against evidence the agent did not write for the occasion:

* the commands it ran in this turn and whether they succeeded (the thread's
  own record of tool calls);
* the files that exist in its folder;
* where the commits of this turn are now (on the default branch or not), and
  the state of the pull request it opened.

Each point comes back ``confirmed`` (evidence for it), ``contradicted``
(evidence against it) or ``open`` (nothing found either way). ``open`` is the
honest answer for what only eyes can check, such as how something looks: the
check says so and names what the agent pointed at.

Read-only: nothing is run in the repository except ``git`` and ``gh`` reads,
no model is asked. What cannot be read (a CLI that records no tool calls)
leaves its points open.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from dodaios.briefs import done

__all__ = [
    "CONFIRMED",
    "CONTRADICTED",
    "OPEN",
    "Ran",
    "Result",
    "commands_run",
    "judge",
    "summary",
    "with_done_when",
]

log = logging.getLogger(__name__)

CONFIRMED: Final[str] = "confirmed"
CONTRADICTED: Final[str] = "contradicted"
OPEN: Final[str] = "open"

_GIT_TIMEOUT_S: Final[float] = 6.0
_GH_TIMEOUT_S: Final[float] = 10.0
_SHELL_TOOLS: Final[frozenset[str]] = frozenset(
    {"bash", "runcommand", "run_command", "shell", "exec", "execute", "terminal", "run_shell"}
)
_PR_URL = re.compile(r"https://github\.com/([\w.\-]+/[\w.\-]+)/pull/(\d+)")
_PICTURE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)|(\S+\.(?:png|jpe?g|gif|webp|mp4|mov))\b")
_EXIT = re.compile(r"\[exit (\d+)\]\s*$")
#: How much of a command's output is kept as evidence.
_TAIL_CHARS: Final[int] = 600
#: How many lines of a command's output are read for what it says about itself.
_SAID_LINES: Final[int] = 4_000

# What a command line only carries is not what it runs: the body of a here
# document (a file being written, a commit message) and quoted text. Both can
# name a check without running it.
_HEREDOC = re.compile(
    r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1([^\n]*)\n(?:.*?\n)?[ \t]*\2[ \t]*(?=\n|$)", re.S
)
_SHELL_READS_INPUT = re.compile(r"(?:^|[\s;&|(])(?:ba|z|da)?sh(?:\s+-\w+)*\s*$")
_SHELL_RUNS_ARGUMENT = re.compile(r"(?:^|[\s;&|(])(?:ba|z|da)?sh(?:\s+-\w+)*\s+-\w*c\s+$")
# A line of several commands ends with the last one's exit status, so the
# line succeeding says nothing sure about one command in the middle of it.
_JOIN = re.compile(r"(\|\||&&|;|\||\n)")
_REDIRECT = re.compile(r"^(?:\d*[<>]|&>)")
_ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
_PYTHON = re.compile(r"python(?:\d+(?:\.\d+)?)?|py")
_DURATION = re.compile(r"\d+(?:\.\d+)?[smhd]?")
#: Words in front of a command that start it without being it.
_LAUNCHERS: Final[frozenset[str]] = frozenset(
    {"uv", "uvx", "poetry", "pipenv", "hatch", "pdm", "rye", "npx", "pnpx", "bunx", "exec",
     "env", "time", "sudo", "command", "nice", "arch", "timeout", "gtimeout", "nohup",
     "bash", "sh", "zsh", "dash"}
)
_RUNNERS: Final[frozenset[str]] = frozenset({"uv", "poetry", "pipenv", "hatch", "pdm", "rye"})
_SCRIPT_RUNNERS: Final[frozenset[str]] = frozenset({"npm", "pnpm", "yarn", "bun"})
_TEST_PROGRAMS: Final[frozenset[str]] = frozenset(
    {"pytest", "py.test", "unittest", "vitest", "jest", "mocha", "tox", "nox", "ctest",
     "rspec", "phpunit"}
)
_TEST_PAIRS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("npm", "test"), ("pnpm", "test"), ("yarn", "test"), ("bun", "test"), ("cargo", "test"),
     ("go", "test"), ("make", "test"), ("make", "check"), ("deno", "test"),
     ("dotnet", "test"), ("gradle", "test"), ("gradlew", "test"), ("mvn", "test")}
)
#: Tools that change a file, by the last part of their name.
_EDIT_TOOLS: Final[frozenset[str]] = frozenset(
    {"edit", "write", "multiedit", "notebookedit", "apply_patch", "str_replace_editor",
     "str_replace_based_edit_tool", "create_file", "write_file", "edit_file",
     "replace_in_file", "replace", "patch"}
)
#: Files whose change does not make a test run stale.
_PROSE = re.compile(r"(?i)\.(?:md|mdx|txt|rst|adoc)$")
_WRITES_INTO = re.compile(r"(?<![0-9&>])>>?\s*([^\s&|;<>()]+)")
_SCRATCH = re.compile(r"^(?:/dev/|/tmp/|/private/tmp/|/var/folders/|&)")
_EDITS_IN_PLACE = re.compile(r"\b(?:sed|perl)\b[^|;&\n]*\s-\w*i\w*\b")
_FILE_CHANGERS: Final[frozenset[str]] = frozenset({"apply_patch", "patch", "tee"})
_TREE_CHANGERS: Final[frozenset[str]] = frozenset(
    {"apply", "checkout", "restore", "reset", "revert", "merge", "rebase", "pull", "stash",
     "cherry-pick", "switch"}
)
_TEST_SCRIPT = re.compile(r"(?:agent_land|agent_done_gate|run_tests\w*)\.py$")
# What a test runner or a check prints about itself. A count of zero failures
# is no failure, and a word in the middle of a file that was printed is none
# either, so the failure words count at the start of a line only.
_SAYS_PASSED = re.compile(
    r"(?i:\b\d+ passed\b|\ball (?:tests |checks )?pass(?:ed)?\b|\bexit=0\b"
    r"|\btest result: ok\b|\bno issues found\b)|^\s*PASS\b|^ok\s+\S+\s+[\d.]+s\b"
)
_SAYS_FAILED = re.compile(
    r"(?i:\b[1-9]\d* (?:failed|errors?)\b|\bexit=[1-9]\d*\b|\btest result: failed\b)"
    r"|^\s*(?:-+ )?(?:FAILED|FAIL)\b|\bBUILD FAILED\b"
)


@dataclass(frozen=True, slots=True)
class Ran:
    """A command line the agent ran in the turn, and how it ended."""

    command: str
    ok: bool
    tail: str = ""
    #: The line as it was typed, line breaks kept (a here document needs them).
    typed: str = ""
    #: The last thing the output says about passing or failing, and which it was.
    said: str = ""
    said_failed: bool = False
    #: How many changes to the folder's files followed this line in the turn.
    changed_after: int = 0


@dataclass(frozen=True, slots=True)
class _Step:
    """One command of a command line, with what joins it to its neighbours."""

    text: str
    core: tuple[str, ...]
    before: str = ""
    after: str = ""


@dataclass(frozen=True, slots=True)
class Result:
    """One done-when point and what the evidence says about it."""

    text: str
    verdict: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return {"point": self.text, "verdict": self.verdict, "evidence": self.evidence}


def commands_run(events: Sequence[dict[str, Any]], *, since_ms: int = 0) -> list[Ran]:
    """The shell commands of a turn with their results, in the order they ran.

    A call and its result pair by ``call_id``. A call without a result (the
    turn was cut off) is left out: nothing is known about how it ended. Each
    line also knows how many file changes followed it (an edit tool, a later
    line that writes a file), since a check that passed before the last change
    says nothing about the state the work ended in.
    """
    calls: dict[str, tuple[str, int]] = {}
    found: list[tuple[int, Ran]] = []
    changes: list[int] = []
    for place, event in enumerate(events):
        if int(event.get("ts_ms") or 0) < since_ms:
            continue
        payload = event.get("payload") or {}
        if event.get("kind") == "tool_call":
            name = str(payload.get("name") or "").rsplit("__", 1)[-1].lower()
            arguments = payload.get("input")
            arguments = arguments if isinstance(arguments, dict) else {}
            if name in _EDIT_TOOLS:
                target = next(
                    (str(arguments[key]) for key in ("file_path", "path", "notebook_path",
                                                     "target_file") if arguments.get(key)),
                    "",
                )
                if not _PROSE.search(target):
                    changes.append(place)
                continue
            command = arguments.get("command")
            if isinstance(command, list):
                command = " ".join(str(part) for part in command)
            if isinstance(command, str) and command.strip() and (
                name in _SHELL_TOOLS or "command" in name or "shell" in name or "bash" in name
            ):
                calls[str(payload.get("call_id") or "")] = (command, place)
        elif event.get("kind") == "tool_result":
            command, at = calls.pop(str(payload.get("call_id") or ""), ("", 0))
            if not command:
                continue
            output = str(payload.get("output") or "")
            code = _EXIT.search(output)
            failed = bool(payload.get("is_error")) or (code is not None and code.group(1) != "0")
            said, said_failed = _said(output)
            run = Ran(
                command=" ".join(command.split()),
                ok=not failed,
                tail=" ".join(output.split())[-_TAIL_CHARS:],
                typed=command,
                said=said,
                said_failed=said_failed,
            )
            found.append((at, run))
            if _changes_files(run):
                changes.append(at)
    found.sort(key=lambda item: item[0])
    return [
        replace(run, changed_after=sum(1 for change in changes if change > at))
        for at, run in found
    ]


def _changes_files(run: Ran) -> bool:
    """Whether a command line writes into the folder's files (not into scratch or prose)."""
    code = _code_of(run.typed or run.command)
    for target in _WRITES_INTO.findall(code):
        if not _SCRATCH.match(target) and not _PROSE.search(target):
            return True
    if _EDITS_IN_PLACE.search(code):
        return True
    for step in _steps(run):
        if not step.core:
            continue
        if step.core[0] in _FILE_CHANGERS:
            return True
        if step.core[0] == "git" and len(step.core) > 1 and step.core[1] in _TREE_CHANGERS:
            return True
    return False


def _said(output: str) -> tuple[str, bool]:
    """The last line of an output that says passed or failed: ``(its words, failed)``."""
    words, failed = "", False
    for line in output.splitlines()[-_SAID_LINES:]:
        against = _SAYS_FAILED.search(line)
        if against:
            words, failed = against.group(0).strip(), True
            continue
        for_it = _SAYS_PASSED.search(line)
        if for_it:
            words, failed = for_it.group(0).strip(), False
    return words, failed


def _code_of(typed: str) -> str:
    """A command line without the text it only carries.

    Here-document bodies and quoted strings are dropped, except where a shell
    reads them as commands (``bash <<EOF``, ``sh -c '...'``).
    """

    def body(match: re.Match[str]) -> str:
        opening_line = typed[: match.start()].rsplit("\n", 1)[-1]
        if _SHELL_READS_INPUT.search(opening_line):
            return match.group(0)
        return match.group(3)

    text = _HEREDOC.sub(body, typed)
    out: list[str] = []
    quote, keep, at = "", False, 0
    while at < len(text):
        char = text[at]
        if char == "\\" and quote != "'" and at + 1 < len(text):
            following = text[at + 1]
            if not quote:
                out.append(" " if following == "\n" else char + following)
            elif keep:
                out.append(following)
            at += 2
            continue
        if quote:
            if char == quote:
                quote = ""
            elif keep:
                out.append(char)
        elif char in "'\"":
            quote = char
            keep = bool(_SHELL_RUNS_ARGUMENT.search("".join(out[-48:])))
        else:
            out.append(char)
        at += 1
    return "".join(out)


def _core(text: str) -> tuple[str, ...]:
    """What a command is, without what merely starts or tunes it.

    Environment assignments, launchers (``uv run``, ``python -m``, ``npx``),
    flags and redirections go; the program or script and its plain arguments
    stay, so ``.venv/bin/python -m pytest -q tests`` is ``("pytest", "tests")``.
    """
    core: list[str] = []
    previous = ""
    for word in text.lstrip("({ ").split():
        if _REDIRECT.match(word):
            continue
        if word.startswith("-"):
            continue
        base = word.rstrip(")}").rsplit("/", 1)[-1]
        if not core:
            if _ASSIGNMENT.match(word):
                continue
            if _PYTHON.fullmatch(base) or base in _LAUNCHERS:
                previous = base
                continue
            if base in ("run", "exec", "x") and previous in _RUNNERS:
                continue
            if previous in ("timeout", "gtimeout") and _DURATION.fullmatch(word):
                continue
        elif word == "run" and len(core) == 1 and core[0] in _SCRIPT_RUNNERS:
            continue
        plain = word.rstrip(")}").rstrip("/")
        core.append(plain[2:] if plain.startswith("./") else plain)
    if core:
        core[0] = core[0].rsplit("/", 1)[-1]
    return tuple(core)


def _steps(run: Ran) -> list[_Step]:
    """The commands of a line in order, each with what joins it to the next."""
    pieces = _JOIN.split(_code_of(run.typed or run.command))
    steps: list[_Step] = []
    before = ""
    for at in range(0, len(pieces), 2):
        text = " ".join(pieces[at].split())
        after = pieces[at + 1] if at + 1 < len(pieces) else ""
        if not text:
            # An empty piece (a blank line, ``;;``) joins nothing new.
            before = before or after
            continue
        steps.append(_Step(text=text, core=_core(text), before=before, after=after))
        before = after
    if steps:
        steps[-1] = _Step(steps[-1].text, steps[-1].core, steps[-1].before, "")
    return steps


def _git(folder: str, *args: str) -> str:
    try:
        done_process = subprocess.run(  # noqa: S603 - fixed argv, read-only git
            ["git", "-C", folder, *args],  # noqa: S607
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):  # no git here: no git evidence
        return ""
    return done_process.stdout.strip() if done_process.returncode == 0 else ""


def _default_branch(folder: str) -> str:
    head = _git(folder, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for name in ("origin/main", "origin/master"):
        if _git(folder, "rev-parse", "--verify", "--quiet", name):
            return name
    return ""


def _pull_request(report: str, ran: Sequence[Ran]) -> tuple[str, str] | None:
    text = report + "\n" + "\n".join(f"{r.command}\n{r.tail}" for r in ran)
    found = _PR_URL.findall(text)
    return found[-1] if found else None


def _pull_request_state(repo: str, number: str) -> dict[str, Any] | None:
    import json

    try:
        got = subprocess.run(  # noqa: S603 - fixed argv, a read of one pull request
            ["gh", "pr", "view", number, "--repo", repo, "--json", "state,mergedAt"],  # noqa: S607
            capture_output=True, text=True, timeout=_GH_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError):  # no gh or no network: no answer
        return None
    if got.returncode != 0:
        return None
    try:
        data = json.loads(got.stdout or "{}")
    except ValueError:  # an unreadable answer is no answer
        return None
    return data if isinstance(data, dict) else None


def _landed(folder: str, since_ms: int, report: str, ran: Sequence[Ran]) -> tuple[str, str]:
    """``(verdict, evidence)`` for a point that says the work is merged or shipped."""
    pull = _pull_request(report, ran)
    if pull is not None:
        state = _pull_request_state(*pull)
        if state is not None:
            label = f"pull request {pull[0]}#{pull[1]}"
            if str(state.get("state") or "").upper() == "MERGED":
                return CONFIRMED, f"{label} is merged"
            return CONTRADICTED, f"{label} is {str(state.get('state') or 'not merged').lower()}"
    if folder:
        base = _default_branch(folder)
        if base:
            since = f"--since=@{max(0, since_ms // 1000)}"
            commits = _git(folder, "log", since, "--format=%H", "HEAD").split()
            if commits:
                unmerged = _git(folder, "rev-list", "--count", f"{base}..HEAD")
                if unmerged == "0":
                    return CONFIRMED, f"the commits of this run are on {base}"
                # Not a contradiction: a squash merge leaves the branch's own
                # commits off the default branch for good.
                return (
                    OPEN,
                    f"{unmerged or 'some'} commit(s) of the checkout are not on {base} as of "
                    "the last fetch, which a squash merge also leaves behind; no pull "
                    "request was named to read",
                )
    if pull is not None:
        return OPEN, f"it names pull request #{pull[1]}, whose state could not be read"
    return OPEN, "no pull request and no new commit was found for this run"


def _same_check(have: tuple[str, ...], want: tuple[str, ...]) -> bool:
    """Whether a command that ran is the wanted check, other flags allowed."""
    if not have or not want or have[0] != want[0]:
        return False
    rest = iter(have[1:])
    return all(any(word == wanted for word in rest) for wanted in want[1:])


def _is_test(core: tuple[str, ...]) -> bool:
    if not core:
        return False
    first = core[0]
    if first in _TEST_PROGRAMS or _TEST_SCRIPT.search(first):
        return True
    return len(core) > 1 and (first, core[1].split(":", 1)[0]) in _TEST_PAIRS


def _last_step(ran: Sequence[Ran], fits: Any) -> tuple[Ran, list[_Step], int] | None:
    """The last command of the turn that ``fits``: its line, the line's steps, its place."""
    for run in reversed(ran):
        steps = _steps(run)
        for at in range(len(steps) - 1, -1, -1):
            if fits(steps[at].core):
                return run, steps, at
    return None


def _held(run: Ran, steps: Sequence[_Step], at: int) -> tuple[bool | None, str]:
    """Whether the command at ``at`` succeeded, and what says so; ``None`` when nothing does.

    A line's exit status is that of the last command it ran. It speaks for
    the command in question when that is the last one, or when everything
    after it hangs on it with ``&&`` and the line succeeded. Otherwise (piped
    into ``tail``, followed by an ``ls``) what the output says decides, and a
    silent output leaves the point open.
    """
    step = steps[at]
    if at == len(steps) - 1:
        if run.ok:
            return True, "it succeeded"
        if step.before == "&&" and not run.said_failed:
            return None, "the line failed, possibly before it reached this command"
        return False, f"it failed ({run.said or run.tail[-120:]})"
    if run.ok and all(later.after in ("&&", "") for later in steps[at:]):
        return True, "it succeeded"
    if run.said:
        return (not run.said_failed), f"its output says '{run.said}'"
    return None, "it ran inside a longer command line and its own result could not be read"


def _command_result(text: str, found: tuple[Ran, list[_Step], int]) -> Result:
    run, steps, at = found
    held, how = _held(run, steps, at)
    shown = steps[at].text[:140]
    if held is None:
        return Result(text, OPEN, f"ran `{shown}`: {how}")
    if held and run.changed_after:
        return Result(
            text, OPEN,
            f"ran `{shown}`: {how}, but {run.changed_after} file change(s) followed that run "
            "and it was not run again",
        )
    return Result(text, CONFIRMED if held else CONTRADICTED, f"ran `{shown}`: {how}")


def _judge_one(
    point: done.Criterion,
    *,
    ran: Sequence[Ran],
    folder: str,
    since_ms: int,
    report: str,
) -> Result:
    text = point.text
    if point.kind == done.KIND_COMMAND:
        wanted = _core(_code_of(point.target))
        found = _last_step(ran, lambda core: _same_check(core, wanted))
        if found is None:
            return Result(text, OPEN, f"`{point.target}` was not run in this turn")
        return _command_result(text, found)
    if point.kind == done.KIND_FILE:
        try:
            path = Path(point.target).expanduser()
            exists = (path if path.is_absolute() else Path(folder) / path).exists()
        except OSError:  # a path that cannot be asked about is not there
            exists = False
        if exists:
            return Result(text, CONFIRMED, f"{point.target} exists")
        return Result(
            text, CONTRADICTED, f"{point.target} does not exist in {folder or 'the folder'}"
        )
    if point.kind == done.KIND_TEST:
        found = _last_step(ran, _is_test)
        if found is None:
            return Result(text, OPEN, "no test command was run in this turn")
        return _command_result(text, found)
    if point.kind == done.KIND_LANDED:
        verdict, evidence = _landed(folder, since_ms, report, ran)
        return Result(text, verdict, evidence)
    if point.kind == done.KIND_VISIBLE:
        shown = next(
            (a or b for a, b in _PICTURE.findall(report) if (a or b)), ""
        )
        if shown:
            return Result(
                text, OPEN, f"only a look can confirm this; the report points at {shown}"
            )
        return Result(text, OPEN, "only a look can confirm this; the report shows no picture")
    if point.kind == done.KIND_REPORT:
        if report.strip():
            return Result(
                text, CONFIRMED, "a report was delivered; what it says is yours to read"
            )
        return Result(text, CONTRADICTED, "the turn ended without a report")
    return Result(text, OPEN, "nothing in the thread's record or the folder settles this")


def judge(
    criteria: Sequence[done.Criterion],
    *,
    events: Sequence[dict[str, Any]],
    since_ms: int = 0,
    folder: str = "",
    report: str = "",
) -> list[Result]:
    """Hold each done-when point against the turn's record. Blocking (git, gh)."""
    ran = commands_run(events, since_ms=since_ms)
    results: list[Result] = []
    for point in criteria:
        try:
            results.append(
                _judge_one(point, ran=ran, folder=folder, since_ms=since_ms, report=report)
            )
        except Exception:  # noqa: BLE001 - one unreadable point must not hide the others
            log.warning("brief acceptance: a point could not be checked", exc_info=True)
            results.append(Result(point.text, OPEN, "this point could not be checked"))
    return results


def with_done_when(job_id: str, recorded: Any = None) -> Any:
    """A thread job's verdict with the order's done-when points in it.

    ``recorded`` is what the run record says about the job
    (``dodaios.core.delegate_verify.Verification``), or ``None`` when there is
    none. The points come from the check made when the turn ended; without
    any, ``recorded`` is returned as it is. A contradicted point makes the
    verdict ``failed``; ``verified`` needs every point confirmed and nothing
    in the run record against it.
    """
    from dodaios.briefs import log as log_module
    from dodaios.core.delegate_verify import Check, Verification

    store = log_module.get_log()
    row = store.delivery(job_id) if store is not None else None
    try:
        import json

        points = json.loads(str((row or {}).get("acceptance") or "[]"))
    except ValueError:  # an unreadable record is no record
        points = []
    points = [p for p in points if isinstance(p, dict) and p.get("point")]
    if not points:
        return recorded
    verdict_of = {CONFIRMED: True, CONTRADICTED: False}
    checks = [
        Check(
            "done when: " + str(point["point"])[:80],
            verdict_of.get(str(point.get("verdict") or "")),
            str(point.get("evidence") or ""),
        )
        for point in points
    ]
    earlier = list(getattr(recorded, "checks", []) or [])
    against = [c for c in (*earlier, *checks) if c.ok is False]
    if against:
        verdict, text = "failed", "The claim does not hold: " + against[0].detail
    elif all(c.ok for c in checks) and getattr(recorded, "verdict", "") != "failed":
        verdict = "verified"
        text = (
            f"All {len(checks)} done-when point(s) of the order are confirmed by the "
            "thread's record and the repository."
        )
    else:
        open_points = sum(1 for c in checks if c.ok is None)
        verdict = "unverified"
        text = f"{open_points} of {len(checks)} done-when point(s) could not be confirmed."
    return Verification(job_id, "coding", verdict, text, [*earlier, *checks])


def summary(results: Sequence[Result], *, continues: bool = False) -> str:
    """The check as the lead reads it, ``""`` when the order named no done-when point.

    ``continues`` says the turn that ended named no points of its own and went
    on with an earlier order of the thread (an answered question, a follow-up):
    the points are that order's, and the evidence counts from its start.
    """
    if not results:
        return ""
    count = {v: sum(1 for r in results if r.verdict == v) for v in (CONFIRMED, CONTRADICTED, OPEN)}
    head = (
        "Done-when check by Dodaios, from the thread's record and the repository (not from "
        f"the agent's report): {count[CONFIRMED]} of {len(results)} confirmed"
        + (f", {count[CONTRADICTED]} contradicted" if count[CONTRADICTED] else "")
        + (f", {count[OPEN]} open" if count[OPEN] else "")
        + "."
        + (
            " The points are those of the order this turn continues; the evidence counts "
            "from that order's start."
            if continues else ""
        )
    )
    lines = [f"- {r.verdict}: {r.text} ({r.evidence})" for r in results]
    tail = ""
    if count[CONTRADICTED] or count[OPEN]:
        tail = (
            "\nBefore you tell the person it is done: send what is contradicted back to the "
            "same agent, and check what is open yourself or say that it is unchecked."
        )
    return head + "\n" + "\n".join(lines) + tail
