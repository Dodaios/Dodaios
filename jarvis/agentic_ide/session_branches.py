"""Find the branch a pane's work belongs to, from its session's own record.

A pane's branch is, in this order (:func:`pane_branch`):

1. the branch its session created or last changed a checkout of, whichever
   is newer, and
2. the branch checked out in the folder the pane runs in.

The CLI transcript is used only as evidence of where a session worked. GitHub
remains the sole source of remote branch, PR and check status. Unrecognised
commands fail closed, which leaves the pane with its folder's branch.

A creation call counts once it is confirmed, by either witness:

* the tool result quotes Git's own "new branch" line, or
* the repository's reflog records that branch as created while the call ran.

The second witness is what makes this work for every coding CLI: a result that
was piped through a filter, cut short, or written by a shell that reports no
exit code still leaves the repository's own record of the creation.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loguru import logger

from jarvis.agentic_ide import agent_transcript, git_overview


@dataclass(frozen=True)
class PaneBranchRecord:
    pane: str
    history_id: str
    folder: str
    agent: str = ""
    session_id: str = ""
    home: Path | None = None
    # Set by Jarvis only when it creates a fork's new branch/worktree.
    created_branch: str = ""
    started_at: float = 0


@dataclass(frozen=True)
class CreatedBranch:
    branch: str
    folder: str
    created_at: float = 0
    silent_success: bool = False
    # When the creating call started; with created_at it bounds the moment the
    # repository must have recorded the branch.
    called_at: float = 0
    # False while only the command names the branch and its result does not.
    confirmed: bool = True


_STRING = r"""(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')"""
_EXEC = re.compile(r"\b(?:tools\.)?exec_command\s*\(\s*\{(?:" + _STRING + r"""|[^}"'])*\}""")
_FIELD = re.compile(r"""(?<!\w)["']?(cmd|workdir)["']?\s*:\s*(""" + _STRING + r")")
_CREATED = re.compile(r"(?:new branch|[Cc]reated branch)\s+['\"]([^'\"]+)['\"]")


def _commands(arguments: dict[str, Any]) -> Iterable[tuple[str, str]]:
    command = arguments.get("cmd") or arguments.get("command") or arguments.get("CommandLine")
    if isinstance(command, str):
        yield command, str(arguments.get("workdir") or arguments.get("cwd") or "")
        return
    # Codex code-mode records the executed tool calls inside a JS orchestration
    # string. Parse only literal exec_command arguments; never execute JS or
    # interpret agent prose, file contents, templates or dynamic expressions.
    source = arguments.get("input")
    if not isinstance(source, str):
        return
    for match in _EXEC.finditer(source):
        fields: dict[str, str] = {}
        for key, literal in _FIELD.findall(match[0]):
            try:
                value = ast.literal_eval(literal)
            except (SyntaxError, ValueError):
                logger.debug("Session branch: unsupported command argument literal")
                continue
            if isinstance(value, str):
                fields[key] = value
        if re.search(r"""\bworkdir["']?\s*:""", match[0]) and "workdir" not in fields:
            # A dynamic workdir can name a different repository. Its absence
            # from the literal fields is not permission to assume this pane.
            continue
        if fields.get("cmd"):
            yield fields["cmd"], fields.get("workdir", "")


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'" else value


_DRIVE_PATH = re.compile(r"/([A-Za-z])(/.*)?")


def _enter(cwd: Path, target: str) -> Path:
    """The directory a shell lands in after ``cd target`` from ``cwd``."""
    if target == "~" or target[:2] in {"~/", "~\\"}:
        return (Path.home() / target[2:]).resolve()
    drive = _DRIVE_PATH.fullmatch(target) if os.name == "nt" else None
    if drive:
        # Git Bash on Windows spells a drive root as /c/.
        return Path(f"{drive[1].upper()}:{drive[2] or '/'}").resolve()
    return (cwd / target).resolve()


def _git_calls(command: str, folder: str) -> list[tuple[Path, list[str], int]]:
    """Every literal ``git`` call: its folder, its arguments, the chain's length."""
    lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        words = [_unquote(word) for word in lexer]
    except ValueError:
        logger.debug("Session branch: incomplete quoted command")
        return []
    segments: list[list[str]] = [[]]
    for word in words:
        if word and all(character in ";&|\n" for character in word):
            segments.append([])
        else:
            segments[-1].append(word)
    cwd = Path(folder)
    calls = []
    for args in segments:
        if not args:
            continue
        if args[0].lower() in {"cd", "set-location", "pushd"} and len(args) == 2:
            cwd = _enter(cwd, args[1])
            continue
        if args[0] not in {"git", "git.exe"}:
            continue
        args = args[1:]
        root = cwd
        while len(args) >= 2 and args[0] in {"-C", "-c"}:
            if args[0] == "-C":
                root = _enter(root, args[1])
            args = args[2:]
        calls.append((root, args, len(segments)))
    return calls


#: Git commands that change a checkout or publish from it. Reading a folder
#: (``git log``, ``git diff``) is not working in it.
_GIT_WRITES = frozenset(
    {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "commit",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "switch",
    }
)


def written_by_command(command: str, folder: str) -> list[str]:
    """The folders whose checkout this command line changed through Git."""
    return [
        str(root)
        for root, args, _ in _git_calls(command, folder)
        if args and args[0] in _GIT_WRITES
    ]


def created_by_command(command: str, folder: str) -> list[CreatedBranch]:
    """Understand literal Git creation commands; checking out a branch is not creation."""
    found = []
    for root, args, chained in _git_calls(command, folder):
        branch = ""
        silent = False
        if args[:2] == ["worktree", "add"] and "-b" in args:
            index = args.index("-b")
            if index + 1 < len(args):
                branch = args[index + 1]
        elif len(args) >= 3 and args[0] in {"switch", "checkout"}:
            flag = "-c" if args[0] == "switch" else "-b"
            for option in (flag, "--create" if flag == "-c" else "-b"):
                if option in args and args.index(option) + 1 < len(args):
                    branch = args[args.index(option) + 1]
        elif len(args) >= 2 and args[0] == "branch" and not args[1].startswith("-"):
            branch = args[1]
            silent = chained == 1 and len(args) in {2, 3}
        if branch and not branch.startswith("-"):
            found.append(CreatedBranch(branch=branch, folder=str(root), silent_success=silent))
    return found


#: Shell tools across the coding CLIs, lower-cased and without a namespace.
_SHELL_TOOLS = frozenset(
    {
        "exec",
        "exec_command",
        "bash",
        "powershell",
        "shell",
        "run_shell_command",
        "run_command",
        "run_terminal_cmd",
    }
)


def created_branches(
    events: Iterable[dict[str, Any]],
    folder: str,
    *,
    not_before: float = 0,
    unconfirmed: bool = False,
) -> list[CreatedBranch]:
    """Branches this session's shell calls created, oldest first.

    With ``unconfirmed`` a successful creation call whose result does not name
    the branch is returned too, marked ``confirmed=False``: the caller has to
    find the creation in the repository before it counts.
    """
    calls: dict[str, tuple[float, list[CreatedBranch]]] = {}
    found: list[CreatedBranch] = []
    for event in events:
        # A native conversation fork copies earlier tool records. Those belong
        # to the parent session, not to the newly spawned pane.
        if not_before and (event.get("ts_ms") or 0) < not_before * 1000:
            continue
        payload = event.get("payload") or {}
        identity = str(payload.get("call_id") or "")
        if event.get("kind") == "tool_call":
            tool = str(payload.get("name") or "").rsplit(".", 1)[-1].lower()
            if tool not in _SHELL_TOOLS:
                continue
            arguments = payload.get("input") or {}
            if not isinstance(arguments, dict):
                continue
            candidates = []
            for command, cwd in _commands(arguments):
                candidates.extend(
                    created_by_command(
                        command, str((Path(folder) / cwd).resolve()) if cwd else folder
                    )
                )
            calls[identity] = ((event.get("ts_ms") or 0) / 1000, candidates)
        elif event.get("kind") == "tool_result" and not payload.get("is_error"):
            output = str(payload.get("output") or "")
            names = set(_CREATED.findall(output))
            # A bare `git branch name` is silent on success. Require an actual
            # zero exit code for that case, not merely the absence of is_error.
            succeeded = bool(
                re.search(r'(?:"exit_code"\s*:\s*0\b|Process exited with code 0\b)', output)
            )
            called_at, candidates = calls.pop(identity, (0, []))
            ended_at = (event.get("ts_ms") or 0) / 1000
            for candidate in candidates:
                confirmed = candidate.branch in names or (
                    candidate.silent_success and succeeded and not names and "fatal:" not in output
                )
                if confirmed or unconfirmed:
                    found.append(
                        CreatedBranch(
                            candidate.branch,
                            candidate.folder,
                            ended_at,
                            called_at=called_at,
                            confirmed=confirmed,
                        )
                    )
    return found


#: Tools that write one file, lower-cased and without a namespace. An unknown
#: tool is ignored: the session's Git writes still place it.
_FILE_TOOLS = frozenset(
    {
        "write",
        "edit",
        "multiedit",
        "notebookedit",
        "write_file",
        "replace",
        "writefile",
        "strreplacefile",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    }
)
_PATH_KEYS = ("file_path", "filePath", "notebook_path", "path", "TargetFile")


def worked_folders(
    events: Iterable[dict[str, Any]], folder: str, *, not_before: float = 0
) -> list[tuple[str, float]]:
    """Folders this session changed, oldest first: by a Git write or a file tool.

    Only a call whose result came back without an error counts, and reading a
    folder never does.
    """
    calls: dict[str, list[str]] = {}
    found: list[tuple[str, float]] = []
    for event in events:
        if not_before and (event.get("ts_ms") or 0) < not_before * 1000:
            continue
        payload = event.get("payload") or {}
        identity = str(payload.get("call_id") or "")
        if event.get("kind") == "tool_call":
            tool = str(payload.get("name") or "").rsplit(".", 1)[-1].lower()
            arguments = payload.get("input") or {}
            if not isinstance(arguments, dict):
                continue
            folders: list[str] = []
            if tool in _SHELL_TOOLS:
                for command, cwd in _commands(arguments):
                    folders.extend(
                        written_by_command(
                            command, str((Path(folder) / cwd).resolve()) if cwd else folder
                        )
                    )
            elif tool in _FILE_TOOLS:
                target = next(
                    (arguments[key] for key in _PATH_KEYS if isinstance(arguments.get(key), str)),
                    "",
                )
                if target:
                    folders.append(str(_enter(Path(folder), target).parent))
            if folders:
                calls[identity] = folders
        elif event.get("kind") == "tool_result" and not payload.get("is_error"):
            at = (event.get("ts_ms") or 0) / 1000
            found.extend((written, at) for written in calls.pop(identity, []))
    return found


_Evidence = tuple[float, list[CreatedBranch], list[tuple[str, float]]]
_cache: dict[tuple[str, str, str, float], _Evidence] = {}
_cache_lock = threading.Lock()


def _common(folder: str) -> str:
    path = Path(folder)
    value = git_overview._out(["rev-parse", "--git-common-dir"], path) if path.is_dir() else None
    return os.path.normcase(str((path / value.strip()).resolve())) if value else ""


_REFLOG_ENTRY = re.compile(r"@\{(\d+)\}\t(.*)")
# Transcript and reflog clocks are the same machine's; the reflog keeps whole
# seconds, the transcript stamps a call a moment after the model emitted it.
_CLOCK_SLACK = 2


_creations: dict[tuple[str, str, float, float], bool] = {}


def _recorded_creation(folder: str, branch: str, called_at: float, ended_at: float) -> bool:
    """Did this repository record ``branch`` as created while the call ran?

    The window lies in the past and a reflog entry never changes, so an answer
    Git actually gave stays valid; a read that failed is asked again.
    """
    if not called_at or not ended_at or ended_at < called_at:
        return False
    key = (os.path.normcase(folder), branch, called_at, ended_at)
    with _cache_lock:
        known = _creations.get(key)
    if known is not None:
        return known
    log = git_overview._out(
        ["log", "-g", "--date=unix", "--format=%gd%x09%gs", f"refs/heads/{branch}", "--"],
        Path(folder),
    )
    if log is None:
        return False
    recorded = False
    for line in log.splitlines():
        entry = _REFLOG_ENTRY.search(line)
        if entry is None or not entry[2].startswith("branch: Created from"):
            continue
        if called_at - _CLOCK_SLACK <= int(entry[1]) <= ended_at + _CLOCK_SLACK:
            recorded = True
            break
    with _cache_lock:
        if len(_creations) >= 512:
            _creations.clear()
        _creations[key] = recorded
    return recorded


def _evidence(record: PaneBranchRecord) -> tuple[list[CreatedBranch], list[tuple[str, float]]]:
    """What this session's own record says it created and where it wrote."""
    if not record.session_id or not agent_transcript.can_read(record.agent):
        return [], []
    key = (record.history_id, record.session_id, record.folder, record.started_at)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None and now - cached[0] < 15:
        return cached[1], cached[2]
    events = agent_transcript.read_events(record.agent, record.session_id, home=record.home) or []
    candidates = created_branches(
        events, record.folder, not_before=record.started_at, unconfirmed=True
    )
    worked = worked_folders(events, record.folder, not_before=record.started_at)
    with _cache_lock:
        _cache[key] = (now, candidates, worked)
        for expired in [key for key, entry in _cache.items() if now - entry[0] > 300]:
            del _cache[expired]
    return candidates, worked


def owned_branch(record: PaneBranchRecord) -> CreatedBranch | None:
    """The newest branch this pane demonstrably created."""
    if record.created_branch:
        return CreatedBranch(record.created_branch, record.folder)
    candidates, _ = _evidence(record)
    if not candidates:
        return None
    root = _common(record.folder)
    if not root:
        return None
    for candidate in reversed(candidates):
        if candidate.confirmed and _common(candidate.folder) == root:
            return candidate
        # The result did not name the branch, or the command reached this
        # repository by a path this module cannot follow (a shell variable).
        # The pane's own repository then has to show the creation inside the
        # call.
        if _recorded_creation(
            record.folder, candidate.branch, candidate.called_at, candidate.created_at
        ):
            return replace(candidate, folder=record.folder, confirmed=True)
    return None


@dataclass(frozen=True)
class _Repository:
    read_at: float
    # (folder, branch) of every checkout with a branch out, longest folder first.
    checkouts: list[tuple[str, str]]
    default_branch: str


_repositories: dict[str, _Repository] = {}


def _key(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder))


def _repository(folder: str, root: str) -> _Repository:
    """The repository's checkouts and default branch; one read serves every pane."""
    now = time.monotonic()
    with _cache_lock:
        known = _repositories.get(root)
    if known is not None and now - known.read_at < 15:
        return known
    path = Path(folder)
    checkouts: list[tuple[str, str]] = []
    worktree = ""
    for line in (git_overview._out(["worktree", "list", "--porcelain"], path) or "").splitlines():
        if line.startswith("worktree "):
            worktree = _key(line[len("worktree ") :])
        elif line.startswith("branch refs/heads/") and worktree:
            checkouts.append((worktree, line[len("branch refs/heads/") :]))
    checkouts.sort(key=lambda entry: len(entry[0]), reverse=True)
    head = git_overview._out(
        ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path
    )
    repository = _Repository(now, checkouts, (head or "").strip().removeprefix("origin/"))
    with _cache_lock:
        _repositories[root] = repository
    return repository


def _worked_branch(record: PaneBranchRecord) -> tuple[str, float] | None:
    """The feature branch out in the checkout this session last changed.

    The default branch does not count: a command run in the main checkout must
    not hide the feature branch the session has been building.
    """
    _, worked = _evidence(record)
    if not worked:
        return None
    root = _common(record.folder)
    if not root:
        return None
    repository = _repository(record.folder, root)
    default = {repository.default_branch} if repository.default_branch else {"main", "master"}
    for folder, at in reversed(worked):
        touched = _key(folder)
        for checkout, branch in repository.checkouts:
            if touched == checkout or touched.startswith(checkout + os.sep):
                if branch not in default:
                    return branch, at
                break
    return None


@dataclass(frozen=True)
class PaneBranch:
    branch: str
    folder: str
    # Set only for a branch the pane created: a pull request older than this
    # belongs to an earlier branch of the same name.
    created_at: float = 0


def pane_branch(record: PaneBranchRecord) -> PaneBranch | None:
    """The branch a pane's work belongs to.

    In this order: the branch its session created or last changed a checkout
    of, whichever is newer, and failing both the branch checked out where the
    pane runs. A detached HEAD has none.
    """
    created = owned_branch(record)
    if record.created_branch and created is not None:
        return PaneBranch(created.branch, created.folder)
    worked = _worked_branch(record)
    if created is not None and (
        worked is None or worked[0] == created.branch or created.created_at >= worked[1]
    ):
        return PaneBranch(created.branch, created.folder, created.created_at)
    if worked is not None:
        return PaneBranch(worked[0], record.folder)
    path = Path(record.folder)
    head = (
        git_overview._out(["symbolic-ref", "--quiet", "--short", "HEAD"], path)
        if path.is_dir()
        else None
    )
    return PaneBranch(head.strip(), record.folder) if head and head.strip() else None
