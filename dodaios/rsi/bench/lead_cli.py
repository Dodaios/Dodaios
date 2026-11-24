"""Replay one lead turn on Claude Code and stop it at the first move.

The CLI is started as the lead's own turn starts it, with the inputs a replay
changes and the safeguards a replay needs:

* the recorded (or rebuilt) system prompt as ``--append-system-prompt-file``
  and the message on stdin, the lead's model and effort;
* the lead's identity flags (``runner_cli.identity_turn_flags``): only the
  app's tool server, the vendor's web, sub-agent and shell tools removed;
* the app's tool server replaced by :mod:`replay_tools`, which lists the same
  tools and runs none of them;
* the CLI's own file-changing tools removed as well (:data:`REPLAY_DENIED`) and
  the permission mode fixed to ``dontAsk``: the person's settings may put every
  chat in ``bypassPermissions`` and allow ``Edit`` and ``Write``, and a replayed
  first move must never change a file before the CLI is stopped. A replay that
  answers calls runs in ``default`` instead, so that exactly those calls can be
  allowed on the control protocol, and also goes without the CLI's own reading
  tools (:data:`READS_TODAY`): they would read the person's clone as it is
  today, the merged change included; the app's own folder tools stay and are
  answered from the repository as it was;
* every other permission prompt answered "deny" on the control protocol, one
  empty folder as the working folder of every replay, no session written to
  disk (the CLI still names one empty project folder after that working
  folder, once);
* the replay's tool server started from the same code as the replay itself
  (``PYTHONPATH``), not from whatever copy of the app is installed.

The stream is read with the parser the live chat uses
(``runner_cli.translate_claude_line``), and the first move is taken the way the
turn record takes it (``lead_turns.TurnRecorder``): text before the first tool
call is the opening, a schema load (``ToolSearch``) is not a move, a sub-agent's
events are not the lead's. At the first tool call, or the end of a turn that
answered in text, the CLI and everything it started are stopped.

**A served call.** A brief replay passes ``serve``: for a call a replay may
answer (``replay_tools.served``: the brief kit request and the read-only folder
tools, which send nothing) it returns the text the app's tool would have
returned, or ``None`` when it does not answer this one. An answered call is not
the move: its answer goes to the replay's tool server, its permission prompt is
allowed, and the turn goes on. The first call that is not answered is the move.
At most :data:`MAX_SERVED` calls are answered in one replay.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Final

from . import replay_tools
from .first_move import LOADING_TOOLS, Move, tool_name
from .lead_replay import LeadInput, Platform

__all__ = ["MAX_SERVED", "RUNNERS", "ClaudeReplay", "Serve"]

log = logging.getLogger(__name__)

#: The lead CLIs a replay can run. GLM's plan is Claude Code too, but bills its own
#: key; it waits until its billing can be told apart from a per-token key.
RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli"})
#: A replay that has not made its first move by then is a failed run.
TIMEOUT_S: Final[float] = 180.0
_TEXT_KEEP: Final = 400
#: Calls one replay answers at most (look-ups and the brief kit together).
MAX_SERVED: Final[int] = 4
#: The CLI's own tools that read the disk as it is now: not offered in a replay that
#: answers calls, which reads the repository as it was (the app's folder tools).
READS_TODAY: Final[tuple[str, ...]] = ("Read", "Grep", "Glob", "LS")

#: What a served call returns, by tool (as the app lists it) and arguments: its
#: text, or its text and whether it is an error; ``None``: this call is the move.
Serve = Callable[[str, Mapping[str, Any]], "str | tuple[str, bool] | None"]


def _stop(proc: subprocess.Popen[bytes]) -> None:
    """Stop the CLI and what it started (its tool server, a shim's node process)."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # A ``.cmd`` shim's child outlives the shim: the whole tree goes.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603 - fixed argv, our own child's pid
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S607
                capture_output=True,
                timeout=15,
                check=False,
            )
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=10)


def _lines(stream: IO[bytes], out: queue.Queue[bytes | None]) -> None:
    try:
        for raw in iter(stream.readline, b""):
            out.put(raw)
    except (OSError, ValueError):  # the pipe closed under the reader: the run is over
        log.debug("replay: the CLI's output closed", exc_info=True)
    finally:
        out.put(None)


#: The CLI's own tools that change files. A replay never offers them, whatever the
#: person's settings allow: the first move is taken from the stream, but under
#: ``bypassPermissions`` the CLI would carry such a call out before it is stopped.
REPLAY_DENIED: Final[tuple[str, ...]] = ("Edit", "Write", "MultiEdit", "NotebookEdit")


class ClaudeReplay:
    """A :data:`~dodaios.rsi.bench.lead_replay.Driver` for Claude Code."""

    def __init__(
        self,
        *,
        tools_file: Path,
        scratch: Path,
        env: dict[str, str],
        argv_prefix: Sequence[str] | None = None,
        server: Sequence[str] | None = None,
        timeout_s: float = TIMEOUT_S,
        session_id: str = "",
    ) -> None:
        #: The lead's tool list as :mod:`replay_tools` reads it.
        self.tools_file = Path(tools_file)
        self.scratch = Path(scratch)
        self.env = dict(env)
        self._prefix = list(argv_prefix) if argv_prefix is not None else None
        #: How the replay's tool server is started (a test may start a stand-in).
        self.server = list(server or [sys.executable, "-m", "dodaios.rsi.bench.replay_tools"])
        self.timeout_s = timeout_s
        #: The lead chat the identity flags are built for (never a society seat's).
        self.session_id = session_id or "rsi-replay"

    def _flags(self, identity: Any, *, serving: bool = False) -> list[str]:
        """The lead's identity flags with the replay's own denials and permission mode.

        Every replay goes without the CLI's file-changing tools. A first-move replay
        runs in ``dontAsk``: nothing it asks for happens. A replay that answers calls
        (``serving``) must let exactly those through the control protocol, which
        ``dontAsk`` would refuse without asking, so it runs in ``default``; it also
        goes without the CLI's own reading tools (:data:`READS_TODAY`), and with
        every tool that changes something removed, ``default`` asks the driver for
        everything else.
        """
        from dodaios.agent_chat.runner_cli import identity_turn_flags

        removed = (*REPLAY_DENIED, *(READS_TODAY if serving else ()))
        flags = list(identity_turn_flags("claude-cli", identity))
        if "--disallowedTools" in flags:
            at = flags.index("--disallowedTools") + 1
            denied = [t for t in flags[at].split(",") if t]
            flags[at] = ",".join([*denied, *(t for t in removed if t not in denied)])
        else:
            flags += ["--disallowedTools", ",".join(removed)]
        return [*flags, "--permission-mode", "default" if serving else "dontAsk"]

    def _argv(
        self, platform: Platform, work: Path, system_file: Path, answers: Path | None = None
    ) -> list[str]:
        import dodaios
        from dodaios.agent_chat import dodaios_harness
        from dodaios.agent_chat.runner_cli import claude_argv_prefix
        from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

        prefix = self._prefix if self._prefix is not None else claude_argv_prefix()
        # The server imports the code this replay runs on, not an installed copy.
        code = str(Path(dodaios.__file__).resolve().parent.parent)
        path = os.pathsep.join(p for p in (code, self.env.get("PYTHONPATH", "")) if p)
        config = {
            "mcpServers": {
                MCP_TOOLS_SERVER_NAME: {
                    "type": "stdio",
                    "command": self.server[0],
                    "args": [
                        *self.server[1:],
                        str(self.tools_file),
                        *([str(answers)] if answers is not None else []),
                    ],
                    "env": {"PYTHONPATH": path},
                }
            }
        }
        config_file = work / "mcp.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")
        identity = dodaios_harness.Identity(self.session_id, "", "", path=system_file)
        argv = [
            *prefix,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--input-format",
            "stream-json",
            "--permission-prompt-tool",
            "stdio",
            "--no-session-persistence",
            "--mcp-config",
            str(config_file),
            *self._flags(identity, serving=answers is not None),
            "--append-system-prompt-file",
            str(system_file),
        ]
        if platform.model:
            argv += ["--model", platform.model]
        effort = "xhigh" if platform.effort == "ultracode" else platform.effort
        if effort and platform.cli == "claude-cli":
            argv += ["--effort", effort]
        return [*argv, "--session-id", str(uuid.uuid4())]

    def __call__(self, lead: LeadInput, platform: Platform, serve: Serve | None = None) -> Move:
        # One fixed, empty working folder: the CLI keys what it keeps per project by
        # it, so a new folder per replay would leave a trail of them in its config.
        home = self.scratch / "cwd"
        home.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="replay-", dir=self.scratch))
        try:
            system_file = work / "system.md"
            system_file.write_text(lead.system, encoding="utf-8")
            answers = None
            if serve is not None:
                answers = work / "answers"
                answers.mkdir()
            argv = self._argv(platform, work, system_file, answers)
            return self._run(argv, home, lead.message, _Served(serve, answers))
        except Exception as exc:  # broad-except: a failed replay is a void result, not a crash
            log.info("replay: the CLI could not run", exc_info=True)
            return Move(error=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(
        self, argv: list[str], work: Path, message: str, served: _Served | None = None
    ) -> Move:
        from dodaios.agent_chat.runner_cli import (
            _ClaudeState,  # noqa: PLC2701 - the live chat's own stream state
            claude_control_init,
            claude_stream_input,
            translate_claude_line,
        )

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(  # noqa: S603 - the CLI's own argv, built above
            argv,
            cwd=work,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        out: queue.Queue[bytes | None] = queue.Queue()
        reader = threading.Thread(target=_lines, args=(proc.stdout, out), daemon=True)
        reader.start()
        state = _ClaudeState(turn_id="replay")
        served = served or _Served(None, None)
        found = _FirstMove(served)
        try:
            assert proc.stdin is not None  # noqa: S101 - opened with PIPE above
            proc.stdin.write((claude_control_init() + claude_stream_input(message)).encode())
            proc.stdin.flush()
            deadline = time.monotonic() + self.timeout_s
            while found.move is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return Move(error=f"no first move within {self.timeout_s:.0f} s")
                try:
                    raw = out.get(timeout=left)
                except queue.Empty:  # nothing new yet: look at the deadline again
                    continue
                if raw is None:
                    return found.ended(proc.poll())
                try:
                    obj = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:  # a line that is not JSON (a warning) says nothing of the move
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") == "control_request":
                    _answer(proc, obj, served)
                    continue
                found.line(obj)
                for event in translate_claude_line(obj, state):
                    found.event(event)
            return found.move
        finally:
            _stop(proc)


class _Served:
    """The calls one replay answers: their answers go into the tool server's answers folder."""

    def __init__(self, serve: Serve | None, answers: Path | None) -> None:
        self._serve = serve
        self._answers = answers
        self.keys: set[str] = set()

    def answer(self, name: str, args: Mapping[str, Any]) -> bool:
        """Answer this call if the replay serves it; ``True`` when it is answered (not the move).

        ``name`` is the call's name as the CLI gives it. Only a tool of the app's
        server can be answered: the CLI runs its own tools itself.
        """
        tool = tool_name(name)
        if self._serve is None or self._answers is None or tool == name:
            return False
        key = replay_tools.call_key(tool, args)
        if key in self.keys:
            return True
        if len(self.keys) >= MAX_SERVED or not replay_tools.served(tool, args):
            return False
        found = self._serve(tool, args)
        if found is None:
            return False
        text, error = found if isinstance(found, tuple) else (found, False)
        path = self._answers / f"{key}.json"
        part = path.with_suffix(".part")
        blob = json.dumps({"text": text, "error": bool(error)}, ensure_ascii=False)
        part.write_text(blob, encoding="utf-8")
        os.replace(part, path)
        self.keys.add(key)
        return True


def _answer(proc: subprocess.Popen[bytes], obj: dict[str, Any], served: _Served) -> None:
    """A permission prompt: allowed for a served call only, refused for everything else."""
    found = obj.get("request")
    request: dict[str, Any] = found if isinstance(found, dict) else {}
    raw = request.get("input")
    args = dict(raw) if isinstance(raw, dict) else {}
    name = str(request.get("tool_name") or "")
    if request.get("subtype") == "can_use_tool" and served.answer(name, args):
        decision: dict[str, Any] = {"behavior": "allow", "updatedInput": args}
    else:
        decision = {"behavior": "deny", "message": "Not run: this is a benchmark replay."}
    frame = {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": str(obj.get("request_id") or ""),
            "response": decision,
        },
    }
    with contextlib.suppress(OSError, ValueError):
        assert proc.stdin is not None  # noqa: S101 - opened with PIPE
        proc.stdin.write((json.dumps(frame) + "\n").encode())
        proc.stdin.flush()


class _FirstMove:
    """Reads the first move off the events, as ``lead_turns.TurnRecorder`` does."""

    def __init__(self, served: _Served) -> None:
        self.move: Move | None = None
        self.model = ""
        self._served = served
        self._text: dict[str, str] = {}
        self._order: list[str] = []
        self._error = ""

    @property
    def opening(self) -> str:
        return "".join(self._text[mid] for mid in self._order).strip()

    def line(self, obj: dict[str, Any]) -> None:
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init" and isinstance(obj.get("model"), str):
            self.model = str(obj["model"])
        elif kind == "assistant" and not obj.get("parent_tool_use_id"):
            named = (obj.get("message") or {}).get("model")
            if isinstance(named, str) and named and not named.startswith("<"):
                self.model = named
            if str(obj.get("error") or ""):
                self._error = str(obj.get("error"))
        elif kind == "result" and self.move is None:
            if obj.get("is_error") or str(obj.get("subtype") or "").startswith("error"):
                why = str(obj.get("result") or obj.get("subtype") or "the CLI reported an error")
                self.move = Move(error=why[:300], model=self.model)
            else:
                self.move = Move(text=self.opening[:_TEXT_KEEP], model=self.model)

    def event(self, event: dict[str, Any]) -> None:
        if self.move is not None:
            return
        payload = event.get("payload") or {}
        if payload.get("agent_id"):
            return  # a sub-agent's own conversation, not the lead's move
        kind = event.get("kind")
        if kind == "text_delta":
            mid = str(payload.get("message_id") or "")
            if mid not in self._text:
                self._order.append(mid)
                self._text[mid] = ""
            self._text[mid] += str(payload.get("text") or "")
        elif kind == "assistant_text":
            mid = str(payload.get("message_id") or "")
            if mid not in self._text:
                self._order.append(mid)
            self._text[mid] = str(payload.get("text") or "")
        elif kind == "tool_call":
            name = str(payload.get("name") or "")
            if name in LOADING_TOOLS:
                return  # it only loads a tool's schema; the move is the call after it
            raw = payload.get("input")
            if isinstance(raw, dict) and self._served.answer(name, raw):
                return  # answered like the app's tool would; the move comes after it
            self.move = Move(
                tool=tool_name(name),
                args=dict(raw) if isinstance(raw, dict) else {"input": raw},
                opening=self.opening[:_TEXT_KEEP],
                model=self.model,
            )

    def ended(self, code: int | None) -> Move:
        if self.move is not None:
            return self.move
        why = self._error or f"the CLI ended before a first move (exit {code})"
        return Move(error=why[:300], model=self.model)
