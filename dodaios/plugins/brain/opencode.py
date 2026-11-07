"""OpenCode Brain — answer through a local ``opencode acp`` session, no API key.

This provider drives the **official OpenCode binary** over the Agent Client
Protocol, exactly the exchange OpenMausBot's ``opencode acp`` driver makes:
``initialize`` -> ``session/new`` -> ``session/set_config_option`` for the
picked model (and effort, when the session offers it) -> ``session/prompt``,
with every ``session/update`` streamed back as a :class:`BrainDelta`.

Nothing here talks to a vendor HTTP endpoint and nothing reads a credential:
OpenCode resolves its own providers, logins and free models. The brain runs the
binary in a throwaway folder with every permission request denied, so a
conversational turn cannot read or write the user's files.

Two shapes, one provider, chosen by ``structured_prompts``:

* **Conversational** (default) — a light "answer in a sentence or three" wrapper
  with the recent turns, mirroring the Codex/Antigravity siblings.
* **Structured** — the caller's contract is prepended verbatim
  (``render_structured_prompt``); there is no system-prompt channel in ACP.

Like the other subscription-CLI brains, startup is a full coding-agent process,
so this is deliberately not the install's default spoken brain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from dodaios.agent_runtimes.acp import AcpTurn
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS
from dodaios.core.protocols import BrainDelta, BrainRequest

from .cli_prompt_context import (
    extract_reply_language_directive,
    render_cli_standing_instructions,
    render_structured_prompt,
)

log = logging.getLogger(__name__)

#: Empty means "whatever model OpenCode itself is configured to use".
DEFAULT_MODEL = ""

#: One brain turn may wait this long before the process is killed. Cold starts
#: of the coding-agent server are seconds, but a wedged session must not hold
#: the caller's coroutine forever.
_CLI_TIMEOUT_S: float = 120.0

#: How long one queue wait may block before an empty progress tick is yielded
#: (keeps the caller's own no-progress deadline alive through the handshake).
_TICK_S: float = 1.0

_BINARIES: tuple[str, ...] = ("opencode", "opencode.cmd", "opencode.exe")

_CONVO_TURNS = 6

_CLI_SYSTEM = (
    "You are the user's concise and friendly voice assistant. Answer the user's "
    "message directly in one to three short sentences. Reply in plain text only "
    "— do not run any commands, do not read or edit files, do not use tools."
)

#: ``opencode models`` answers from a shared background service; the probe is
#: cached so a provider card or the subscription resolver cannot spawn it on
#: every request.
_PROBE_TTL_S: float = 600.0
_PROBE_TIMEOUT_S: float = 15.0
_probe_lock = threading.Lock()
_probe_cache: tuple[float, bool] | None = None


def _resolve_binary() -> str | None:
    """The absolute OpenCode binary, or ``None`` when it is not installed."""
    for name in _BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    # The binary rewrites itself in place otherwise, which can swap it under a
    # running turn.
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _build_cli_prompt(req: BrainRequest) -> str:
    """Flatten the recent turns into one conversational prompt.

    The heavy router system prompt is dropped on purpose: it is large,
    tool-heavy, and misleading for a read-only agent call. Standing user
    instructions and the turn's reply-language directive still travel with the
    prompt, the latter last because it is authoritative.
    """
    lines: list[str] = [_CLI_SYSTEM, ""]
    convo = [
        message
        for message in req.messages
        if getattr(message, "role", None) in ("user", "assistant")
        and isinstance(getattr(message, "content", None), str)
    ][-_CONVO_TURNS:]
    for message in convo:
        speaker = "User" if message.role == "user" else "Assistant"
        lines.append(f"{speaker}: {message.content}")
    prefs = render_cli_standing_instructions(req.system)
    if prefs:
        lines.extend(["", prefs])
    directive = extract_reply_language_directive(req.system)
    if directive:
        lines.extend(["", directive])
    lines.append("Assistant:")
    return "\n".join(lines)


def _effort_value(req: BrainRequest) -> str:
    """The caller's effort hint, or "" to leave OpenCode on its own default.

    ACP effort values are opaque (they differ per model), so no level is
    invented here; an id/value the session does not offer is skipped by
    ``AcpTurn`` and the turn still runs. "none" means "do not ask for extra
    reasoning", which the agent default already is.
    """
    requested = str(getattr(req, "reasoning_effort", "") or "").strip().lower()
    if not requested or requested == "none":
        return ""
    return requested


def _config_for(model: str, req: BrainRequest) -> dict[str, str]:
    """ACP config options for one turn.

    OpenCode names its effort select ``effort`` (category ``thought_level``);
    ``variant`` is the chat seat's older spelling. Both are emitted and the
    session's own ``configOptions`` decide which one is actually applied —
    OpenCode 2.2.5 offers only ``model`` and ``mode`` and skips the rest.
    """
    config: dict[str, str] = {}
    picked = (model or "").strip()
    if picked:
        # OpenCode ids are ``provider/model``. A bare alias cannot be applied
        # and is left to the agent's default rather than sent as a bad value.
        if "/" in picked:
            config["model"] = picked
        else:
            log.debug("opencode: ignoring non-slug model pick %r", picked)
    effort = _effort_value(req)
    if effort:
        config["effort"] = effort
        config["variant"] = effort
    return config


def _usage_payload(usage: dict[str, int]) -> dict[str, int]:
    """ACP usage keys -> the BrainDelta usage vocabulary."""
    out: dict[str, int] = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cached_input_tokens", "cache_hit_tokens"),
    ):
        value = usage.get(source)
        if isinstance(value, int | float):
            out[target] = int(value)
    return out


class _QueueIO:
    """ACP host that streams turn events through an asyncio queue.

    The brain consumes deltas while the pump reads stdout; a direct async
    generator would deadlock the two. Permission requests are always denied by
    the turn (``auto_deny=True``), so ``ask`` is only a protocol placeholder.
    """

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self.events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def write(self, frame: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def emit(self, event: dict[str, Any]) -> None:
        await self.events.put(event)

    async def ask(self, _call_id: str, _name: str, _args: dict[str, Any], _summary: str) -> str:
        return "deny"


async def _stop(
    proc: asyncio.subprocess.Process,
    pump: asyncio.Task[None] | None,
    stderr_task: asyncio.Task[None] | None,
    creationflags: int,
) -> None:
    """Stop the ACP server and its children, then reap both pump tasks."""
    if pump is not None and not pump.done():
        pump.cancel()
    with suppress(Exception):
        proc.stdin.close()
    pid = getattr(proc, "pid", None)
    if sys.platform == "win32" and isinstance(pid, int) and pid > 0:
        # The npm shim and the server are separate processes; killing only the
        # shim leaves the server holding the pipes open.
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
    for task in (pump, stderr_task):
        if task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(task, timeout=3.0)


class OpenCodeBrain:
    name: str = "opencode"
    context_window: int = 200_000
    #: ACP is a coding-agent protocol, but this brain gives the agent no tools
    #: of ours and denies its own; tools belong to the Agentic IDE seats.
    supports_tools: bool = False
    supports_vision: bool = False
    #: ACP has no system-prompt channel, so a structured contract is prepended
    #: to the prompt. The subscription resolver orders providers with a real
    #: system channel ahead of this one.
    native_system_prompt: bool = False

    def __init__(
        self,
        model: str | None = None,
        structured_prompts: bool = False,
        cli_timeout_s: float | None = None,
    ) -> None:
        self._model = model or DEFAULT_MODEL
        self._structured_prompts = bool(structured_prompts)
        try:
            budget = float(cli_timeout_s) if cli_timeout_s is not None else 0.0
        except (TypeError, ValueError):
            budget = 0.0
        self._cli_timeout_s = budget if budget > 0 else _CLI_TIMEOUT_S

    @staticmethod
    def subscription_connected() -> bool:
        """Whether this install can run OpenCode right now.

        OpenCode needs no Dodaios API key: the binary finds its own logins,
        and unauthenticated installs still reach the free models. So the probe
        is "the binary exists and advertises at least one model". Cached for
        ten minutes because ``opencode models`` starts a background service.
        Never raises — a failed probe means "not usable", never a broken card.
        """
        global _probe_cache
        now = time.monotonic()
        with _probe_lock:
            if _probe_cache is not None and now - _probe_cache[0] < _PROBE_TTL_S:
                return _probe_cache[1]
        binary = _resolve_binary()
        usable = False
        if binary is not None:
            try:
                result = subprocess.run(
                    [binary, "models"],
                    capture_output=True,
                    timeout=_PROBE_TIMEOUT_S,
                    env=_child_env(),
                    stdin=subprocess.DEVNULL,
                    creationflags=NO_WINDOW_CREATIONFLAGS if sys.platform == "win32" else 0,
                    check=False,
                )
                usable = result.returncode == 0 and bool(result.stdout.strip())
            except Exception as exc:  # noqa: BLE001 - a probe degrades, never raises
                log.debug("opencode: model probe failed: %s", exc)
        with _probe_lock:
            _probe_cache = (now, usable)
        return usable

    def can_call_tools(self) -> bool:
        """Runtime tool capability: this brain delegates every tool turn.

        ``AcpTurn`` would happily surface the agent's own calls, but the brain
        is read-only by contract and the caller must use an API/tool provider
        instead of letting the CLI silently work in an empty temp folder.
        """
        return False

    def _render_prompt(self, req: BrainRequest) -> str:
        if self._structured_prompts:
            return render_structured_prompt(req)
        return _build_cli_prompt(req)

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        binary = _resolve_binary()
        if binary is None:
            raise RuntimeError(
                "OpenCode (opencode) is not installed or not on PATH — install it "
                "from https://opencode.ai and sign in, or use an API-key brain."
            )

        prompt = self._render_prompt(req)
        # A throwaway working directory: this brain answers questions and has no
        # business seeing, or being trusted in, the user's repository.
        workdir = tempfile.mkdtemp(prefix="jarvis-opencode-brain-")
        turn = AcpTurn(
            turn_id="opencode-brain",
            cwd=workdir,
            prompt_text=prompt,
            auto_deny=True,
            config=_config_for(self._model, req),
        )
        creationflags = NO_WINDOW_CREATIONFLAGS if sys.platform == "win32" else 0

        log.info(
            "opencode: spawning acp turn (model=%s, structured=%s, prompt=%d chars)",
            self._model or "<agent default>",
            self._structured_prompts,
            len(prompt),
        )

        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "acp",
                cwd=workdir,
                env=_child_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
                limit=4 * 1024 * 1024,
            )
        except (FileNotFoundError, OSError) as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            log.warning("opencode: spawn failed: %s", exc)
            raise RuntimeError(f"OpenCode could not be launched: {exc}") from exc

        assert proc.stdin is not None  # noqa: S101 - PIPE is always present
        assert proc.stdout is not None  # noqa: S101
        assert proc.stderr is not None  # noqa: S101

        io = _QueueIO(proc)
        stderr_chunks: list[str] = []
        pump_error: list[BaseException] = []

        async def _pump() -> None:
            try:
                while True:
                    try:
                        raw = await proc.stdout.readline()
                    except ValueError as exc:
                        # One line past the stream limit: a broken frame of the
                        # turn itself, not a reason to keep reading.
                        pump_error.append(exc)
                        return
                    if not raw:
                        return
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    await turn.on_message(obj, io)
                    if turn.saw_result:
                        return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reported with the turn's own error
                pump_error.append(exc)
            finally:
                await io.events.put(None)

        async def _drain_stderr() -> None:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                stderr_chunks.append(line.decode("utf-8", errors="replace"))

        pump_task = asyncio.create_task(_pump())
        stderr_task = asyncio.create_task(_drain_stderr())
        answer_parts: list[str] = []
        usage: dict[str, int] = {}

        try:
            try:
                proc.stdin.write(turn.opening_frame().encode("utf-8"))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise RuntimeError("OpenCode closed its input during the handshake.") from exc

            deadline = t0 + self._cli_timeout_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    event = await asyncio.wait_for(
                        io.events.get(), timeout=min(_TICK_S, remaining)
                    )
                except TimeoutError:
                    if pump_task.done():
                        break
                    yield BrainDelta(content="")
                    continue
                if event is None:
                    break
                kind = event.get("kind")
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                if kind == "text_delta":
                    text = str(payload.get("text") or "")
                    if text:
                        answer_parts.append(text)
                        yield BrainDelta(content=text)
                elif kind == "usage_delta":
                    raw_usage = payload.get("usage")
                    if isinstance(raw_usage, dict):
                        usage.update(
                            {
                                str(key): int(value)
                                for key, value in raw_usage.items()
                                if isinstance(value, int | float)
                            }
                        )

            if pump_error:
                raise RuntimeError(f"OpenCode ACP stream failed: {pump_error[0]}") from pump_error[0]
            if turn.status != "done":
                detail = "".join(stderr_chunks).strip()[:300]
                reason = turn.error or f"OpenCode ended the turn ({turn.stop_reason or 'no answer'})"
                raise RuntimeError(reason + (f": {detail}" if detail else ""))

            answer = "".join(answer_parts)
            if not answer.strip():
                answer = turn.result_text
            if not answer.strip():
                detail = "".join(stderr_chunks).strip()[:300]
                raise RuntimeError(
                    "OpenCode returned no answer" + (f": {detail}" if detail else ".")
                )
            if not answer_parts:
                yield BrainDelta(content=answer)

            mapped = _usage_payload(usage or turn.usage)
            if mapped:
                yield BrainDelta(usage=mapped)

            log.info(
                "opencode turn ok: %d chars in %.1fs (model=%s)",
                len(answer),
                time.monotonic() - t0,
                turn.agent_name or "OpenCode",
            )
            yield BrainDelta(finish_reason="stop")
        except asyncio.CancelledError:
            with suppress(Exception):
                await turn.cancel(io)
            log.info("opencode: cancelled (stopping acp server)")
            raise
        except TimeoutError as exc:
            raise RuntimeError(
                f"OpenCode did not answer within {self._cli_timeout_s:.0f}s."
            ) from exc
        finally:
            await _stop(proc, pump_task, stderr_task, creationflags)
            shutil.rmtree(workdir, ignore_errors=True)

    def estimate_cost(self, req: BrainRequest) -> float:
        """Zero: OpenCode spends the user's own plan or its free models.

        A per-token estimate would make cost-aware callers avoid the one path
        that adds no bill of its own.
        """
        return 0.0


__all__ = ["OpenCodeBrain"]
