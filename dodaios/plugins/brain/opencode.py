"""OpenCode Brain — answer through the user's own OpenCode install, no Dodaios key.

This provider drives the official ``opencode`` CLI in headless mode
(``opencode run --format json``). OpenCode brings its own model access: the
providers the person signed in to with ``opencode auth login``, the keys in its
own environment, and the free ``opencode/*`` models it ships with. Dodaios
stores no credential for it.

It is a sibling of :class:`dodaios.plugins.brain.claude_cli.ClaudeCliBrain` and
:class:`dodaios.plugins.brain.antigravity.AntigravityBrain`: a CLI turn is
seconds, not milliseconds, so it is not a voice brain. It serves callers that
already wait seconds for a result whose text IS the product (the Agentic IDE
prompt composer, background writers).

Safety: every turn runs OpenCode's read-only ``plan`` agent in an empty
temporary directory, so the model cannot edit files or run commands even when a
prompt asks it to.

Two shapes, chosen by the caller through ``structured_prompts``:

* **Conversational** (default) — a light "answer in one to three sentences"
  wrapper with the recent turns. The heavy router system prompt is dropped.
* **Structured** — the caller's contract and payload go to stdin verbatim.
  OpenCode has no system-prompt flag, so the contract is prepended
  (``native_system_prompt = False``) and the subscription resolver prefers a
  sibling with a real system channel when one is signed in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS
from dodaios.core.protocols import BrainDelta, BrainRequest

from .cli_prompt_context import (
    extract_reply_language_directive,
    render_cli_standing_instructions,
    render_structured_prompt,
)

log = logging.getLogger(__name__)

# Hard cap for one turn. Callers with their own budget pass ``cli_timeout_s``.
_CLI_TIMEOUT_S: float = 120.0

# The caller's no-progress watchdog resets on any delta, so the wait loop yields
# an empty delta this often while the CLI works.
_TICK_S: float = 3.0

# OpenCode's built-in read-only agent: it can read and plan, never edit or run.
_READ_ONLY_AGENT = "plan"

_CLI_SYSTEM = (
    "You are the user's concise and friendly voice assistant. Answer the user's "
    "message directly in one to three short sentences. Reply in plain text only "
    "— do not run any commands, do not read or edit files, do not use tools."
)

# Recent turns that ride along on the conversational path.
_CONVO_TURNS = 6

# Optional flags, each used only when this install's ``opencode run --help``
# lists it, so an older CLI still answers instead of exiting on an unknown flag.
# ``--pure`` skips external plugins: they are start-up cost on a text-only turn,
# and a user plugin must not hook a brain call.
_OPTIONAL_FLAGS: tuple[str, ...] = ("--pure",)

_supported_flags: frozenset[str] | None = None
_probe_lock = threading.Lock()
_HELP_PROBE_TIMEOUT_S = 20.0
_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")


def _argv_prefix() -> list[str]:
    """The command that launches OpenCode, or raise ``RuntimeError``.

    Reuses the agent-chat resolver, which augments PATH for a GUI-launched
    process and looks behind the Windows npm shim.
    """
    from dodaios.agent_chat.runner_cli import CliUnavailable, opencode_argv_prefix

    try:
        return opencode_argv_prefix()
    except CliUnavailable as exc:
        raise RuntimeError(
            "OpenCode is not installed. Install it from https://opencode.ai "
            "(npm i -g opencode-ai), then pick a model with 'opencode auth login' "
            "or use one of its free models."
        ) from exc


def _probe_flags(prefix: list[str]) -> frozenset[str]:
    """Long options ``opencode run`` understands (probed once per process)."""
    global _supported_flags
    with _probe_lock:
        if _supported_flags is not None:
            return _supported_flags
        flags: frozenset[str] = frozenset()
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [*prefix, "run", "--help"],
                capture_output=True,
                timeout=_HELP_PROBE_TIMEOUT_S,
                stdin=subprocess.DEVNULL,
                creationflags=NO_WINDOW_CREATIONFLAGS,
            )
            text = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
            flags = frozenset(_FLAG_RE.findall(text))
        except (OSError, subprocess.SubprocessError) as exc:
            log.info("OpenCodeBrain: help probe failed (%s); optional flags off", exc)
        _supported_flags = flags
        return flags


# Preferred free model when none is configured. Background work must never bill
# a key on its own, and OpenCode's own default may be a keyed provider it found
# in the environment, so an unset model resolves to a free ``opencode/*`` one.
_PREFERRED_FREE_MODEL = "opencode/big-pickle"


def pick_free_model(model_ids: list[str]) -> str | None:
    """The free OpenCode model to use when none is configured, or None."""
    free = [
        mid
        for mid in model_ids
        if mid.startswith("opencode/") and (mid.endswith("-free") or mid == _PREFERRED_FREE_MODEL)
    ]
    if _PREFERRED_FREE_MODEL in free:
        return _PREFERRED_FREE_MODEL
    return free[0] if free else None


def _installed_free_model() -> str | None:
    """Blocking: ask the installed CLI for its models and pick a free one."""
    try:
        from dodaios.agent_chat.runner_cli import read_opencode_models

        ids = [str(row.get("id") or "") for row in read_opencode_models()]
    except Exception as exc:  # noqa: BLE001 - no list means no free pick
        log.info("OpenCodeBrain: model list unavailable (%s)", type(exc).__name__)
        return None
    return pick_free_model(ids)


def _build_argv(prefix: list[str], model: str | None, supported: frozenset[str]) -> list[str]:
    """Headless, read-only, JSON-event run; the prompt travels on stdin."""
    argv = [*prefix, "run", "--format", "json", "--agent", _READ_ONLY_AGENT]
    argv.extend(flag for flag in _OPTIONAL_FLAGS if flag in supported)
    if model:
        argv.extend(["--model", model])
    return argv


def _build_cli_prompt(req: BrainRequest) -> str:
    """Flatten the last few conversational turns into one prompt."""
    lines: list[str] = [_CLI_SYSTEM, ""]
    convo = [
        m
        for m in req.messages
        if getattr(m, "role", None) in ("user", "assistant")
        and isinstance(getattr(m, "content", None), str)
    ][-_CONVO_TURNS:]
    for m in convo:
        speaker = "User" if m.role == "user" else "Assistant"
        lines.append(f"{speaker}: {m.content}")
    prefs = render_cli_standing_instructions(req.system)
    if prefs:
        lines.extend(["", prefs])
    # The reply-language directive rides last so the answer follows the turn's
    # resolved language.
    lang_directive = extract_reply_language_directive(req.system)
    if lang_directive:
        lines.extend(["", lang_directive])
    lines.append("Assistant:")
    return "\n".join(lines)


def parse_events(stdout: str) -> tuple[str, str | None]:
    """Answer text and error message from ``opencode run --format json`` output.

    The output is one JSON event per line. ``text`` events carry the answer in
    ``part.text``; an ``error`` event carries ``error.data.message`` or
    ``error.name``. Lines that are not JSON are ignored.
    """
    texts: list[str] = []
    error: str | None = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "text":
            part = event.get("part")
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
        elif kind == "error":
            err = event.get("error")
            message = None
            if isinstance(err, dict):
                data = err.get("data")
                if isinstance(data, dict) and isinstance(data.get("message"), str):
                    message = data["message"]
                elif isinstance(err.get("name"), str):
                    message = err["name"]
            error = message or "OpenCode reported an error."
    return "\n\n".join(texts), error


class OpenCodeBrain:
    name: str = "opencode"
    context_window: int = 200_000
    supports_tools: bool = True  # ignored on the CLI path (mirrors the siblings)
    supports_vision: bool = False
    # OpenCode has no system-prompt flag; a structured contract is prepended.
    native_system_prompt: bool = False

    def __init__(
        self,
        model: str | None = None,
        structured_prompts: bool = False,
        cli_timeout_s: float | None = None,
    ) -> None:
        # Empty means "a free OpenCode model" (see ``pick_free_model``).
        self._model = (model or "").strip() or None
        self._structured_prompts = bool(structured_prompts)
        try:
            budget = float(cli_timeout_s) if cli_timeout_s is not None else 0.0
        except (TypeError, ValueError):
            budget = 0.0
        self._cli_timeout_s = budget if budget > 0 else _CLI_TIMEOUT_S

    @staticmethod
    def subscription_connected() -> bool:
        """Whether OpenCode can answer now: the CLI is installed.

        OpenCode owns its model access (its own logins, its own keys, its free
        models), so an installed CLI is ready. Never raises.
        """
        try:
            from dodaios.agent_chat.runner_cli import cli_installed

            return cli_installed("opencode-cli")
        except Exception:  # noqa: BLE001 - a probe degrades, never raises
            return False

    def can_call_tools(self) -> bool:
        """The CLI path takes a flattened prompt and drops Dodaios tools."""
        return False

    def _render_prompt(self, req: BrainRequest) -> str:
        if self._structured_prompts:
            return render_structured_prompt(req)
        return _build_cli_prompt(req)

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        prefix = _argv_prefix()
        supported = await asyncio.to_thread(_probe_flags, prefix)
        model = self._model or await asyncio.to_thread(_installed_free_model)
        if not model:
            raise RuntimeError(
                "OpenCode has no model set and no free model available. Pick a "
                "model for OpenCode in Settings."
            )
        argv = _build_argv(prefix, model, supported)
        prompt = self._render_prompt(req)
        async for delta in self._run(argv, prompt):
            yield delta

    async def _run(self, argv: list[str], prompt: str) -> AsyncIterator[BrainDelta]:
        workdir = tempfile.mkdtemp(prefix="dodaios-opencode-brain-")
        creationflags = NO_WINDOW_CREATIONFLAGS if sys.platform == "win32" else 0
        log.info("OpenCodeBrain: spawning (prompt=%d chars)", len(prompt))
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=workdir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            with suppress(OSError):
                shutil.rmtree(workdir, ignore_errors=True)
            log.warning("OpenCodeBrain: spawn failed: %s", exc)
            raise RuntimeError(f"OpenCode could not be launched: {exc}") from exc

        comm_task = asyncio.create_task(proc.communicate(input=prompt.encode("utf-8")))
        deadline = t0 + self._cli_timeout_s
        stdout_bytes = b""
        stderr_bytes = b""

        async def _kill() -> None:
            if not comm_task.done():
                comm_task.cancel()
            pid = getattr(proc, "pid", None)
            if sys.platform == "win32" and isinstance(pid, int) and pid > 0:
                # The Windows launcher may sit in front of node; kill the tree.
                with suppress(Exception):
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/PID",
                        str(pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        creationflags=creationflags,
                    )
                    await asyncio.wait_for(killer.wait(), timeout=3.0)
            with suppress(Exception):
                proc.kill()
            with suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            with suppress(asyncio.CancelledError, Exception):
                await comm_task

        try:
            while True:
                slice_timeout = min(_TICK_S, deadline - time.monotonic())
                if slice_timeout <= 0:
                    raise TimeoutError
                done, _ = await asyncio.wait({comm_task}, timeout=slice_timeout)
                if done:
                    stdout_bytes, stderr_bytes = comm_task.result()
                    break
                yield BrainDelta(content="")
        except asyncio.CancelledError:
            await _kill()
            log.info("OpenCodeBrain: cancelled (killed)")
            raise
        except TimeoutError as exc:
            await _kill()
            log.warning("OpenCodeBrain: no answer within %.0fs (killed)", self._cli_timeout_s)
            raise RuntimeError(
                f"OpenCode did not answer within {self._cli_timeout_s:.0f}s."
            ) from exc
        finally:
            with suppress(OSError):
                shutil.rmtree(workdir, ignore_errors=True)

        answer, error = parse_events(stdout_bytes.decode("utf-8", errors="replace"))
        elapsed = time.monotonic() - t0
        if error:
            log.warning(
                "OpenCodeBrain: CLI reported an error after %.1fs: %s", elapsed, error[:200]
            )
            raise RuntimeError(f"OpenCode failed: {error}")
        if not answer:
            detail = stderr_bytes.decode("utf-8", errors="replace").strip()[:300]
            log.warning(
                "OpenCodeBrain: empty answer after %.1fs rc=%s detail=%s",
                elapsed,
                proc.returncode,
                detail[:200],
            )
            raise RuntimeError("OpenCode returned no answer" + (f": {detail}" if detail else "."))

        log.info("OpenCodeBrain turn ok: %d chars in %.1fs", len(answer), elapsed)
        yield BrainDelta(content=answer)
        yield BrainDelta(finish_reason="stop")

    def estimate_cost(self, req: BrainRequest) -> float:
        # OpenCode bills through its own logins and keys, not through Dodaios.
        return 0.0


def _reset_for_tests() -> None:
    global _supported_flags
    _supported_flags = None
