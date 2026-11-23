"""What a person asked a coding agent for, and which pull requests the session opened.

Every coding CLI keeps a record of its sessions on the person's machine. This
module reads those records for two facts only: what the person said, and when
the session opened a pull request. It reads nothing else out of them, changes
nothing, and makes no network call.

One shape for every CLI (:class:`PastSession`); a CLI is added by registering a
reader in :data:`_READERS`. Each reader follows the layout it was measured
against, and says so:

* **claude**, ``<home>/projects/<folder>/<session>.jsonl``, measured on
  2026-11-23 against 431 records. A ``user`` row with text is the person
  unless it is ``isMeta`` (the harness writing in their name) or
  ``isSidechain`` (a sub-agent). A message typed while a turn ran is an
  ``attachment`` row holding a ``queued_command`` of human origin. An opened
  pull request is ``toolUseResult.gitOperation.pr`` with ``action: created``;
  records from before the CLI wrote that field carry only the address that
  ``gh pr create`` printed.
* **codex**, ``<home>/sessions/**/*.jsonl``, measured on 2026-11-23 against 24
  records. ``session_meta`` names the session and its folder, a
  ``response_item`` message of role ``user`` is the person, and an opened pull
  request is the address in the output of a call that ran ``gh pr create``.

A sub-agent's own record is not read: what a sub-agent was told is a brief
somebody composed, not the person's words.
"""

from __future__ import annotations

import json
import mmap
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

__all__ = ["Opened", "PastSession", "Said", "person_text", "read_sessions"]

#: A block a CLI wrote into a user turn on the person's behalf (a reminder, a
#: command echo, a notification). The shape is the signal, not a list of tag
#: names: a person typing at a prompt does not write in tags. The same rule the
#: conversation view uses (``dodaios/agentic_ide/agent_transcript.py``), kept
#: here so the kernel reads its evidence through nothing it does not own.
_MACHINE_BLOCK: Final = re.compile(
    r"<([a-zA-Z][\w:-]*)\b[^>]*>.*?</\1\s*>|<[a-zA-Z][\w:-]*\b[^>]*/?>",
    re.DOTALL,
)
#: What a person typed after a slash command: their words, inside a tag.
_COMMAND_ARGS: Final = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_COMMAND_REQUEST_WORDS: Final = 3
#: What a CLI writes in the person's name when they stop a turn.
_INTERRUPTED: Final = "[Request interrupted by user"

_PULL_URL: Final = re.compile(r"https?://([\w.-]+)/([\w.-]+/[\w.-]+)/pull/(\d+)")
_OPENS_PULL: Final = "gh pr create"
#: A file without this cannot have opened a pull request, so it is not parsed.
_PULL_MARK: Final = b"/pull/"


@dataclass(frozen=True, slots=True)
class Said:
    """One thing the person said in a session."""

    ts_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class Opened:
    """A pull request a session opened."""

    ts_ms: int
    #: ``host/owner/name``, lower case: the id :mod:`dodaios.rsi.repo_identity` gives.
    repo: str
    number: int


@dataclass(frozen=True, slots=True)
class PastSession:
    """What one recorded session says about the person's requests and its pull requests."""

    agent: str
    session_id: str
    cwd: str
    said: tuple[Said, ...]
    opened: tuple[Opened, ...]


def person_text(text: str) -> str:
    """What a person said in a user record, or ``""`` when nobody did."""
    raw = str(text or "")
    if raw.lstrip().startswith(_INTERRUPTED):
        return ""
    spoken = _MACHINE_BLOCK.sub(" ", raw).strip()
    if spoken:
        return spoken
    match = _COMMAND_ARGS.search(raw)
    if match is None:
        return ""
    request = " ".join(match.group(1).split())
    return request if len(request.split()) >= _COMMAND_REQUEST_WORDS else ""


def _ts_ms(value: Any) -> int:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value if value > 1e11 else value * 1000)
    if not isinstance(value, str) or not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:  # an unreadable stamp: the row keeps the time of the one before it
        return 0


def _pull(text: str) -> tuple[str, int] | None:
    match = _PULL_URL.search(text or "")
    if match is None:
        return None
    return f"{match.group(1)}/{match.group(2)}".lower(), int(match.group(3))


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):  # not JSON-shaped: its plain text is searched instead
        return str(value)


def _mentions_pull(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                return False
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as view:
                return view.find(_PULL_MARK) != -1
    except (OSError, ValueError):  # cannot be opened or mapped: nothing to read from it
        return False


def _rows(path: Path, worth: Callable[[bytes], bool]) -> Iterator[dict[str, Any]]:
    """The rows of a record that ``worth`` lets through, parsed; a broken line is skipped.

    ``worth`` looks at the raw line, so a record of megabytes costs a parse only
    for the few rows that can matter. It matches the compact JSON the CLIs write.
    A record written with spaces after its colons is one the filter has not
    seen; then every row is parsed, because a filter that must recognise a
    layout to let anything through ends up reading nothing.
    """
    try:
        handle = path.open("rb")
    except OSError:  # a record that vanished or is locked: the next run reads it
        return
    with handle:
        filtered: bool | None = None
        for line in handle:
            if filtered is None:
                if not line.strip():
                    continue
                filtered = b'":"' in line or b'":{' in line
            if filtered and not worth(line):
                continue
            try:
                row = json.loads(line)
            except ValueError:  # a line cut off mid-write: the other rows still count
                continue
            if isinstance(row, dict):
                yield row


class _Notes:
    """What a reader collects from one record, in the order it was written."""

    def __init__(self) -> None:
        self.said: list[Said] = []
        self.opened: dict[tuple[str, int], Opened] = {}
        self.creating: set[str] = set()
        self.last_ms = 0

    def at(self, value: Any) -> int:
        self.last_ms = _ts_ms(value) or self.last_ms
        return self.last_ms

    def say(self, text: str, ts_ms: int) -> None:
        spoken = person_text(text)
        if spoken:
            self.said.append(Said(ts_ms, spoken))

    def open(self, text: str, ts_ms: int) -> None:
        found = _pull(text)
        if found is not None and found not in self.opened:
            self.opened[found] = Opened(ts_ms, found[0], found[1])

    def session(self, agent: str, session_id: str, cwd: str) -> PastSession | None:
        if not self.opened:
            return None
        return PastSession(
            agent=agent,
            session_id=session_id,
            cwd=cwd,
            said=tuple(self.said),
            opened=tuple(sorted(self.opened.values(), key=lambda item: item.ts_ms)),
        )


# --------------------------------------------------------------------------- #
# claude
# --------------------------------------------------------------------------- #


def _claude_worth(line: bytes) -> bool:
    if b'"type":"user"' in line:
        # A tool's output arrives in a user row and can be a whole file. It is never the
        # person, and it matters only when it reports a pull request.
        if b'"tool_result"' in line:
            return b"gitOperation" in line or _PULL_MARK in line
        return True
    if b'"type":"assistant"' in line:
        return b"gh pr create" in line
    return b'"type":"attachment"' in line and b"queued_command" in line


def _claude_blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def _read_claude(path: Path) -> PastSession | None:
    notes = _Notes()
    cwd = ""
    for row in _rows(path, _claude_worth):
        if row.get("isSidechain"):
            continue
        if not cwd and isinstance(row.get("cwd"), str):
            cwd = row["cwd"]
        ts = notes.at(row.get("timestamp"))
        kind = row.get("type")
        if kind == "attachment":
            queued = row.get("attachment")
            origin = queued.get("origin") if isinstance(queued, dict) else None
            if (
                isinstance(queued, dict)
                and queued.get("type") == "queued_command"
                and isinstance(origin, dict)
                and origin.get("kind") == "human"
                and queued.get("commandMode", "prompt") == "prompt"
            ):
                notes.say(str(queued.get("prompt") or ""), ts)
            continue
        if kind == "assistant":
            for block in _claude_blocks(row):
                if block.get("type") == "tool_use" and _OPENS_PULL in _as_text(block.get("input")):
                    notes.creating.add(str(block.get("id") or ""))
            continue
        if kind != "user":
            continue
        result = row.get("toolUseResult")
        operation = result.get("gitOperation") if isinstance(result, dict) else None
        pull = operation.get("pr") if isinstance(operation, dict) else None
        if isinstance(pull, dict) and pull.get("action") == "created":
            notes.open(str(pull.get("url") or ""), ts)
        spoken: list[str] = []
        for block in _claude_blocks(row):
            if block.get("type") == "tool_result":
                if str(block.get("tool_use_id") or "") in notes.creating:
                    notes.open(_as_text(block.get("content")), ts)
            elif block.get("type") == "text" and not row.get("isMeta"):
                spoken.append(str(block.get("text") or ""))
        if spoken:
            notes.say("\n\n".join(spoken), ts)
    return notes.session("claude", path.stem, cwd)


def _claude_files(home: Path | None) -> Iterator[Path]:
    if home is None:
        raw = os.environ.get("CLAUDE_CONFIG_DIR")
        home = Path(raw).expanduser() if raw else Path.home() / ".claude"
    projects = home / "projects"
    if projects.is_dir():
        # One level deep: a sub-agent's record sits in a folder below its session.
        yield from sorted(projects.glob("*/*.jsonl"))


# --------------------------------------------------------------------------- #
# codex
# --------------------------------------------------------------------------- #


def _codex_worth(line: bytes) -> bool:
    if b'"type":"session_meta"' in line:
        return True
    if b'"type":"response_item"' not in line:
        return False
    return b'"role":"user"' in line or _PULL_MARK in line or b"gh pr create" in line


def _codex_texts(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and str(block.get("type") or "").endswith("text")
    )


def _read_codex(path: Path) -> PastSession | None:
    notes = _Notes()
    session_id, cwd = path.stem, ""
    for row in _rows(path, _codex_worth):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        ts = notes.at(row.get("timestamp"))
        kind = row.get("type")
        if kind == "session_meta":
            # Only an explicit marker makes a record a sub-agent's; anything else is read.
            source = payload.get("source")
            if payload.get("thread_source") == "subagent" or (
                isinstance(source, dict) and "subagent" in source
            ):
                return None
            session_id = str(payload.get("id") or session_id)
            cwd = str(payload.get("cwd") or cwd)
            continue
        if kind != "response_item":
            continue
        item = str(payload.get("type") or "")
        call_id = str(payload.get("call_id") or payload.get("id") or "")
        if item == "message":
            if payload.get("role") == "user":
                notes.say(_codex_texts(payload.get("content")), ts)
        elif item in ("function_call", "local_shell_call", "custom_tool_call"):
            arguments = payload.get("arguments", payload.get("input", payload.get("action")))
            if _OPENS_PULL in _as_text(arguments):
                notes.creating.add(call_id)
        elif item in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            if call_id in notes.creating:
                notes.open(_as_text(payload.get("output")), ts)
    return notes.session("codex", session_id, cwd)


def _codex_files(home: Path | None) -> Iterator[Path]:
    if home is None:
        raw = os.environ.get("CODEX_HOME")
        home = Path(raw).expanduser() if raw else Path.home() / ".codex"
    sessions = home / "sessions"
    if sessions.is_dir():
        yield from sorted(sessions.rglob("*.jsonl"))


_READERS: Final[
    dict[str, tuple[Callable[[Path | None], Iterator[Path]], Callable[[Path], PastSession | None]]]
] = {
    "claude": (_claude_files, _read_claude),
    "codex": (_codex_files, _read_codex),
}


def read_sessions(homes: dict[str, Path] | None = None) -> Iterator[PastSession]:
    """Every recorded session that opened a pull request, of every CLI that has a reader.

    ``homes`` names a CLI's config folder where it is not the default one
    (``{"claude": Path(...)}``). A CLI that is not installed contributes nothing.
    """
    for agent, (files, read) in _READERS.items():
        for path in files((homes or {}).get(agent)):
            if not _mentions_pull(path):
                continue
            session = read(path)
            if session is not None:
                yield session
