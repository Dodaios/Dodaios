"""Replay one lead turn on Claude Code and stop it at the first move.

The CLI is started as the lead's own turn starts it, with the inputs a replay
changes and the safeguards a replay needs:

* the recorded (or rebuilt) system prompt as ``--append-system-prompt-file``
  and the message on stdin, the lead's model and effort;
* the lead's identity flags (``runner_cli.identity_turn_flags``): only the
  app's tool server, the vendor's web, sub-agent and shell tools removed;
* the app's tool server replaced by :mod:`replay_tools`, which lists the same
  tools and runs none of them;
* every permission prompt answered "deny" on the control protocol, one empty
  folder as the working folder of every replay, no session written to disk (the
  CLI still names one empty project folder after that working folder, once).

The stream is read with the parser the live chat uses
(``runner_cli.translate_claude_line``), and the first move is taken the way the
turn record takes it (``lead_turns.TurnRecorder``): text before the first tool
call is the opening, a schema load (``ToolSearch``) is not a move, a sub-agent's
events are not the lead's. At the first tool call, or the end of a turn that
answered in text, the CLI and everything it started are stopped.
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
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any, Final

from .first_move import LOADING_TOOLS, Move, tool_name
from .lead_replay import LeadInput, Platform

__all__ = ["RUNNERS", "ClaudeReplay"]

log = logging.getLogger(__name__)

#: The lead CLIs a replay can run. GLM's plan is Claude Code too, but bills its own
#: key; it waits until its billing can be told apart from a per-token key.
RUNNERS: Final[frozenset[str]] = frozenset({"claude-cli"})
#: A replay that has not made its first move by then is a failed run.
TIMEOUT_S: Final[float] = 180.0
_TEXT_KEEP: Final = 400


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

    def _argv(self, platform: Platform, work: Path, system_file: Path) -> list[str]:
        from dodaios.agent_chat import dodaios_harness
        from dodaios.agent_chat.runner_cli import claude_argv_prefix, identity_turn_flags
        from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

        prefix = self._prefix if self._prefix is not None else claude_argv_prefix()
        config = {
            "mcpServers": {
                MCP_TOOLS_SERVER_NAME: {
                    "type": "stdio",
                    "command": self.server[0],
                    "args": [*self.server[1:], str(self.tools_file)],
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
            *identity_turn_flags("claude-cli", identity),
            "--append-system-prompt-file",
            str(system_file),
        ]
        if platform.model:
            argv += ["--model", platform.model]
        effort = "xhigh" if platform.effort == "ultracode" else platform.effort
        if effort and platform.cli == "claude-cli":
            argv += ["--effort", effort]
        return [*argv, "--session-id", str(uuid.uuid4())]

    def __call__(self, lead: LeadInput, platform: Platform) -> Move:
        # One fixed, empty working folder: the CLI keys what it keeps per project by
        # it, so a new folder per replay would leave a trail of them in its config.
        home = self.scratch / "cwd"
        home.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="replay-", dir=self.scratch))
        try:
            system_file = work / "system.md"
            system_file.write_text(lead.system, encoding="utf-8")
            argv = self._argv(platform, work, system_file)
            return self._run(argv, home, lead.message)
        except Exception as exc:  # broad-except: a failed replay is a void result, not a crash
            log.info("replay: the CLI could not run", exc_info=True)
            return Move(error=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(self, argv: list[str], work: Path, message: str) -> Move:
        from dodaios.agent_chat.runner_cli import (
            _ClaudeState,  # noqa: PLC2701 - the live chat's own stream state
            claude_control_init,
            claude_stream_input,
            translate_claude_line,
        )

        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]
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
        found = _FirstMove()
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
                    _deny(proc, obj)
                    continue
                found.line(obj)
                for event in translate_claude_line(obj, state):
                    found.event(event)
            return found.move
        finally:
            _stop(proc)


def _deny(proc: subprocess.Popen[bytes], obj: dict[str, Any]) -> None:
    """Every permission prompt of a replay is refused: nothing it asks for may happen."""
    frame = {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": str(obj.get("request_id") or ""),
            "response": {"behavior": "deny", "message": "Not run: this is a benchmark replay."},
        },
    }
    with contextlib.suppress(OSError, ValueError):
        assert proc.stdin is not None  # noqa: S101 - opened with PIPE
        proc.stdin.write((json.dumps(frame) + "\n").encode())
        proc.stdin.flush()


class _FirstMove:
    """Reads the first move off the events, as ``lead_turns.TurnRecorder`` does."""

    def __init__(self) -> None:
        self.move: Move | None = None
        self.model = ""
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
