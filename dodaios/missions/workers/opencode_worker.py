"""OpenCodeWorker — drive ``opencode acp`` as a Phase-6 worker subprocess.

The brain's heavy-task path (``spawn_worker``) had a worker per connected
provider: Claude, Codex, Antigravity, Grok Build, Gemini, the API models. This
one runs the work on **OpenCode**, over the same Agent Client Protocol pipeline
the chat seat uses (and OpenMausBot drives): ``initialize`` -> ``session/new``
(or ``session/load`` for a resumed step) -> ``session/set_config_option`` for
the picked model -> ``session/prompt``, with every ``session/update`` turned
into worker text by ``AcpTurn``.

Cmd layout::

    opencode acp            # ACP server on stdio, one JSON object per line

Spawn discipline is GeminiWorker's: routed through
``create_worker_subprocess`` (no shell, Win32 creationflags, POSIX
``start_new_session``), ``env`` from ``build_worker_env`` plus the mission's
broker overlay, ``cwd=worktree`` so the CLI's own file tools land inside the
mission's git worktree where ``_capture_diff`` picks them up.

Events: the worker speaks the orchestrator's language — one synthetic
``ClaudeSystemInit`` then one ``ClaudeResult`` — while ``stream.jsonl`` keeps
the raw ACP frames, so the Critic's evidence and the node graph read the same
``normalize_worker_stream`` they always did.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any, ClassVar, Literal

from dodaios.agent_runtimes.acp import AcpTurn, McpServer

from .capabilities import WorkerCapabilityInventory
from .process_utils import create_worker_subprocess
from .stream_consumer import ClaudeResult, ClaudeSystemInit

logger = logging.getLogger(__name__)

_OPENCODE_BINARIES: tuple[str, ...] = ("opencode", "opencode.cmd", "opencode.exe")
_WORKER_TIMEOUT_S: float = 1200.0

def _opencode_model(requested: str) -> str:
    """Only a ``provider/model`` slug is an OpenCode id.

    The decomposer writes Claude aliases (``"sonnet"``) into a step's
    ``model``; OpenCode would refuse one, so anything that is not a
    ``provider/model`` slug leaves the agent's own model alone.
    """
    value = (requested or "").strip()
    return value if "/" in value else ""


def _resolve_opencode_argv_prefix() -> list[str]:
    for name in _OPENCODE_BINARIES:
        found = shutil.which(name)
        if found:
            return [found]
    return ["opencode"]


def _build_opencode_cmd() -> list[str]:
    """The worker's argv: OpenCode's ACP server, stdout carrying the protocol."""
    return [*_resolve_opencode_argv_prefix(), "acp"]


def _broker_servers(binding: Any | None) -> list[McpServer]:
    """The mission's tool broker as ACP ``mcpServers`` entries."""
    if binding is None:
        return []
    try:
        configured = binding.mcp_server_config()
    except Exception:  # noqa: BLE001 — no tools beats a dead turn
        logger.debug("OpenCodeWorker: broker config unreadable", exc_info=True)
        return []
    servers: list[McpServer] = []
    for name, entry in (configured or {}).items():
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command") or "")
        if not command:
            continue
        servers.append(
            McpServer(
                name=str(name),
                command=command,
                args=[str(part) for part in entry.get("args") or []],
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
            )
        )
    return servers


class _Stdio:
    """Writes frames to the worker's stdin; nothing is streamed per event.

    The mission gets one text answer, so the update events are collected by
    ``AcpTurn`` itself and only the final text is reported.
    """

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc

    async def write(self, frame: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def emit(self, _event: dict[str, Any]) -> None:
        return None

    async def ask(self, _call_id: str, _name: str, _args: dict[str, Any], _summary: str) -> str:
        # An unattended worker inside its own worktree: the same answer
        # ``--yolo`` gives the other CLIs.
        return "allow"


class OpenCodeWorker:
    """Phase-6 worker that runs a step on OpenCode over ACP.

    ``cli`` stays ``"claude"`` so the existing worker telemetry needs no
    schema migration; ``ClaudeSystemInit.name`` and the model string carry
    ``opencode`` so a debugging session never has to guess.
    """

    cli: Literal["claude"] = "claude"
    #: Provider family this worker bills (``missions.capacity.worker_family``).
    family: ClassVar[str] = "opencode"

    def __init__(self, *, capability_inventory: WorkerCapabilityInventory | None = None) -> None:
        self.last_pid: int | None = None
        self.last_session_id: str | None = None
        self.capability_inventory = capability_inventory or WorkerCapabilityInventory.build()

    async def spawn(
        self,
        prompt: str,
        *,
        worktree: Path,
        env: dict[str, str],
        job: Any,
        worker_id: str,
        log_dir: Path,
        model: str = "",
        allowed_tools: str = "",  # accepted for parity, unused (the CLI decides)
        permission_mode: str = "yolo",
        max_turns: int = 20,  # accepted for parity, unused (one ACP prompt)
        resume_session_id: str | None = None,
        extra_args: tuple[str, ...] = (),
        timeout_s: float = _WORKER_TIMEOUT_S,
        _broker_binding: Any | None = None,
        **_unused: Any,
    ) -> AsyncIterator[Any]:
        """Run one step: spawn ``opencode acp``, prompt it, report the answer."""
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = log_dir / "stream.jsonl"
        stderr_log = log_dir / "stderr.log"

        session_id = resume_session_id or str(uuid.uuid4())
        self.last_session_id = session_id
        effective_model = _opencode_model(model)

        yield ClaudeSystemInit(
            session_id=session_id,
            model=f"opencode/{effective_model or 'default'}",
            tools=[],
            cwd=str(worktree),
            external_capabilities=self.capability_inventory.report_for(
                "opencode-cli", binding=_broker_binding
            ),
        )

        child_env = dict(env)
        if _broker_binding is not None:
            with suppress(Exception):
                child_env = _broker_binding.apply_environment(child_env)
        child_env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")

        turn = AcpTurn(
            turn_id=worker_id,
            cwd=str(worktree),
            prompt_text=prompt,
            resume=resume_session_id,
            auto_allow=permission_mode == "yolo",
            mcp_servers=_broker_servers(_broker_binding),
            config={"model": effective_model},
        )

        logger.info(
            "OpenCodeWorker[%s] spawn: cwd=%s model=%s yolo=%s",
            worker_id,
            worktree,
            effective_model or "(agent default)",
            permission_mode == "yolo",
        )

        t0 = time.perf_counter()
        deadline = t0 + timeout_s
        proc = await create_worker_subprocess(
            [*_build_opencode_cmd(), *extra_args],
            cwd=str(worktree),
            env=child_env,
            # The ACP protocol is the conversation: the worker writes on stdin.
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.last_pid = proc.pid
        try:
            job.assign(proc.pid)
        except Exception:  # noqa: BLE001 — the tree is still killable without it
            logger.warning(
                "OpenCodeWorker[%s]: job.assign(pid=%d) failed", worker_id, proc.pid, exc_info=True
            )

        frames: list[str] = []
        stderr_chunks: list[str] = []
        io = _Stdio(proc)

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                stderr_chunks.append(line.decode("utf-8", errors="replace"))

        stderr_task = asyncio.create_task(_drain_stderr())
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(turn.opening_frame().encode("utf-8"))
            await proc.stdin.drain()
            while not turn.saw_result:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
                except TimeoutError:  # deadline passed; end the turn with frames so far
                    break
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                frames.append(line)
                try:
                    obj = json.loads(line)
                except ValueError:  # a malformed line is not an ACP frame; skip it
                    continue
                await turn.on_message(obj, io)
        finally:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
            with suppress(Exception):
                await asyncio.wait_for(stderr_task, timeout=5.0)

        with suppress(OSError):
            stdout_log.write_text("\n".join(frames) + ("\n" if frames else ""), encoding="utf-8")
        with suppress(OSError):
            stderr_log.write_text("".join(stderr_chunks), encoding="utf-8")

        wall_ms = int((time.perf_counter() - t0) * 1000)
        is_error = turn.status != "done" or not turn.emitted_text
        result_text = turn.result_text
        if is_error:
            reason = turn.error or f"OpenCode ended the turn ({turn.stop_reason or 'no answer'})"
            tail = "".join(stderr_chunks)[-300:]
            result_text = (result_text or "") + f"\n{reason}" + (f"\n[stderr-tail]\n{tail}" if tail else "")

        yield ClaudeResult(
            subtype="success" if not is_error else "error_during_execution",
            is_error=is_error,
            cost_usd=None,
            num_turns=None,
            session_id=turn.acp_session or session_id,
            duration_ms=wall_ms,
            result=result_text[:4000],
        )
