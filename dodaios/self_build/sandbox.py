"""Run a drafted skill's steps on a past request, read-only, before it may go live.

The routing replay (:func:`.judge.skill`) proves that a skill would catch the
person's requests; it says nothing about whether its steps work. This module
runs the steps: the drafted skill's body and one of the person's past requests
go to a model on a signed-in subscription or a keyless local seat, with the
tools the skill names (and the tools the assistant used for those requests)
offered through the app's own tool executor in read-only mode:

* Every call goes through ``ToolExecutor`` with ``chat_read_only`` set (the
  Plan-mode gate, ``core/tool_read_only.py``): a tool runs only when its
  trusted metadata says it reads (``read_only`` / ``read_only_for_args``).
  Anything else, a send, a write, a purchase, a post, is refused before it
  runs and recorded as *held back*: the step was reached, its side effect was
  not produced. Approvals are denied, never asked.
* The run's working folder is a fresh temporary directory, removed afterwards.
* On a subscription seat the turn runs through the vendor CLI with only the
  Dodaios gateway's tools (native tools isolated, ``gateway_only``), in the
  CLI's read-only permission mode, scoped to the named tools, exactly like an
  unattended scheduled task. On a local seat the model drives the tool loop in
  process.
* Nothing is delivered anywhere; the answer only goes to the judge.

What comes back is a :class:`Run`: the answer, every tool step (ran, failed or
held back) and whether the run itself finished. :func:`.judge.skill_execution`
compares it with what the person accepted then. Callers count each run against
the loop's daily build-call budget and wrap it in ``cost.attributed``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from . import brain

log = logging.getLogger(__name__)

#: Rounds of the in-process tool loop for one replay (a skill is a few steps).
MAX_ROUNDS: Final[int] = 6
#: A replay that takes longer than this failed.
TIMEOUT_S: Final[float] = 240.0
#: CLI runners that enforce a task's tool scope (``agent_chat/tasks.py``).
_SCOPED_RUNNERS: Final[frozenset[str]] = frozenset({"codex-cli", "claude-cli"})
#: The executor's refusal of a non-read tool in read-only mode.
HELD_MARKER: Final[str] = "permits reads only"

SYSTEM: Final[str] = (
    "You are testing a skill your user's assistant may adopt. Follow the skill's steps for the "
    "user's request below, as you would for real, using the tools offered. This is a dry run: "
    "tools that read work normally; any tool that would send, write, change, buy or post is "
    "held back and returns a refusal. When that happens, do not retry it or look for another "
    "way; note in one line what the step would have done and continue. End with the answer you "
    "would give the user, in the user's language."
)


@dataclass(frozen=True, slots=True)
class Step:
    """One tool call of a replay."""

    name: str
    ok: bool
    #: Refused because it would have had a side effect: reached, not run.
    held: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class Run:
    """One replay of a skill on one past request."""

    request: str
    answer: str
    steps: tuple[Step, ...] = ()
    #: Why the run itself did not finish (exception, timeout, a failed turn).
    error: str = ""
    seat: str = ""


def prompt_for(skill_name: str, skill_body: str, request: str) -> str:
    return (
        f"# Skill: {skill_name}\n\n{skill_body.strip()}\n\n"
        f"# The user's request\n\n{request.strip()}"
    )


def _canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def registered_name(called: str, allowed: tuple[str, ...]) -> str:
    """The registered tool a model's call names (CLIs prefix MCP tools, e.g. ``mcp__x__``)."""
    if called in allowed:
        return called
    bare = called.rsplit("__", 1)[-1] if called.startswith("mcp__") else called
    wanted = _canon(bare)
    for name in allowed:
        if _canon(name) == wanted:
            return name
    return called


@dataclass
class _Recorder:
    """Wraps the app's executor: read-only, approvals denied, every call recorded."""

    executor: Any
    steps: list[Step] = field(default_factory=list)

    async def execute(self, tool: Any, args: dict[str, Any], **kwargs: Any) -> Any:
        from dodaios.core.protocols import ToolResult
        from dodaios.core.tool_read_only import allows_read

        name = str(getattr(tool, "name", "") or "")
        if not allows_read(tool, args):
            # Belt and braces: never handed to the executor at all.
            self.steps.append(Step(name, ok=False, held=True))
            return ToolResult(False, None, f"Held back in a dry run: this skill run {HELD_MARKER}")
        snapshot = dict(kwargs.pop("config_snapshot", None) or {})
        snapshot.update(
            {"chat_read_only": True, "unattended": True, "approval_surface": "unattended"}
        )
        result = await self.executor.execute(tool, args, config_snapshot=snapshot, **kwargs)
        error = str(getattr(result, "error", "") or "")
        held = HELD_MARKER in error
        self.steps.append(
            Step(name, ok=bool(getattr(result, "success", False)), held=held, error=error[:200])
        )
        return result


def _live_tools() -> tuple[dict[str, Any], Any]:
    """The assistant's registered tools and its executor, or empty without a brain."""
    from dodaios.agent_chat.runner_brain import brain_manager

    manager = brain_manager()
    if manager is None:
        return {}, None
    return dict(getattr(manager, "_tools", {}) or {}), getattr(manager, "_tool_executor", None)


async def run(
    config: Any,
    *,
    skill_name: str,
    skill_body: str,
    request: str,
    tools: tuple[str, ...],
) -> Run:
    """Replay the skill on ``request`` on the first seat that can drive tools.

    Raises :class:`brain.BackgroundDeferred` when no subscription or local seat
    can run it (nothing was billed); the build then waits.
    """
    live, executor = _live_tools()
    if executor is None:
        raise brain.BackgroundDeferred("the assistant's tools are not loaded yet")
    offered = {name: live[name] for name in tools if name in live}
    seats = await asyncio.to_thread(brain.seats, config)
    workdir = Path(tempfile.mkdtemp(prefix="dodaios-skill-proof-"))
    try:
        for seat in seats:
            if seat.billing.startswith("subscription"):
                from dodaios.core.task_agent import subscription_seat_off_loop

                pair = await subscription_seat_off_loop(seat.provider)
                if pair is None or pair[1] not in _SCOPED_RUNNERS:
                    continue
                return await asyncio.wait_for(
                    _run_cli(seat, pair, skill_name, skill_body, request, offered, workdir),
                    timeout=TIMEOUT_S,
                )
            local = await asyncio.to_thread(brain._instantiate, seat)
            if local is None or not _calls_tools(local):
                continue
            return await asyncio.wait_for(
                _run_local(seat, local, skill_name, skill_body, request, offered, executor),
                timeout=TIMEOUT_S,
            )
    except TimeoutError:  # not silent: the timeout is the failed proof the judge reports
        return Run(request, "", error=f"no answer within {TIMEOUT_S:.0f} s")
    finally:
        await asyncio.to_thread(shutil.rmtree, workdir, True)
    raise brain.BackgroundDeferred("no subscription or local seat can run a skill's steps")


def _calls_tools(instance: Any) -> bool:
    probe = getattr(instance, "can_call_tools", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001 - an unanswerable probe means no tools
            log.debug("self_build: tool-calling probe of %s failed", instance, exc_info=True)
            return False
    return bool(getattr(instance, "supports_tools", False))


async def _run_local(
    seat: Any,
    instance: Any,
    skill_name: str,
    skill_body: str,
    request: str,
    offered: dict[str, Any],
    executor: Any,
) -> Run:
    from dodaios.brain.iteration_budget import IterationBudget
    from dodaios.brain.tool_use_loop import ToolUseLoop
    from dodaios.core.protocols import BrainMessage

    recorder = _Recorder(executor)
    loop = ToolUseLoop(
        instance,
        offered,
        recorder,  # type: ignore[arg-type]
        system_prompt=SYSTEM,
        budget=IterationBudget(max_turns=MAX_ROUNDS),
        max_tokens=2_000,
        tool_context={"delivery": "written", "unattended": True, "chat_read_only": True},
    )
    prompt = prompt_for(skill_name, skill_body, request)
    try:
        agg = await loop.run([BrainMessage(role="user", content=prompt)], user_utterance=request)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a run that breaks is the failed proof
        return Run(request, "", tuple(recorder.steps), f"{type(exc).__name__}", seat.provider)
    return Run(request, agg.text or "", tuple(recorder.steps), "", seat.provider)


async def _run_cli(
    seat: Any,
    pair: tuple[str, str],
    skill_name: str,
    skill_body: str,
    request: str,
    offered: dict[str, Any],
    workdir: Path,
) -> Run:
    """An unattended, read-only CLI turn scoped to the offered tools (cf. ``agent_chat/tasks``)."""
    from dodaios.agent_chat.runner_api import TurnHandle
    from dodaios.agent_chat.runner_cli import run_cli_turn
    from dodaios.agent_chat.store import AgentChatSession
    from dodaios.core.protocols import ChatTurn, current_chat_turn
    from dodaios.core.task_agent import TaskToolScope, register_scope, release_scope
    from dodaios.core.tool_read_only import set_chat_read_only

    provider, runner = pair
    sid = "skill-proof-" + uuid4().hex
    trace = uuid4()
    allowed = tuple(offered)
    texts: list[str] = []
    calls: dict[str, str] = {}
    steps: list[Step] = []
    failure: list[str] = []

    async def emit(event: dict[str, Any]) -> None:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if kind == "assistant_text":
            texts.append(str(payload.get("text") or ""))
        elif kind == "tool_call":
            calls[str(payload.get("call_id") or "")] = registered_name(
                str(payload.get("name") or ""), allowed
            )
        elif kind == "tool_result":
            name = calls.pop(str(payload.get("call_id") or ""), "")
            output = str(payload.get("output") or payload.get("error") or "")
            error = bool(payload.get("is_error"))
            held = error and (HELD_MARKER in output or name not in allowed)
            steps.append(Step(name, ok=not error, held=held, error=output[:200] if error else ""))
        elif kind == "turn_finished" and payload.get("status") != "done":
            failure.append(str(payload.get("error") or payload.get("status") or "failed"))

    async def deny(*_args: Any) -> str:
        return "deny"

    session = AgentChatSession(
        sid,
        "Skill proof",
        provider,
        seat.model or "",
        "",
        str(workdir),
        "read-only",
        None,
        0,
        0,
        0,
        "",
        surface="jarvis",
    )
    handle = TurnHandle(
        session=session,
        turn_id=str(trace),
        emit=emit,
        request_approval=deny,
        cancel=asyncio.Event(),
        trace_id=trace,
        surface="jarvis",
        gateway_only=True,
    )
    prompt = SYSTEM + "\n\n" + prompt_for(skill_name, skill_body, request)
    register_scope(sid, TaskToolScope(frozenset(allowed), trace, request))
    set_chat_read_only(sid, True)
    origin = current_chat_turn.set(ChatTurn(sid, str(trace), request, False, str(trace)))
    try:
        await run_cli_turn(handle, prompt, runner, identity=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a run that breaks is the failed proof
        failure.append(type(exc).__name__)
    finally:
        current_chat_turn.reset(origin)
        set_chat_read_only(sid, False)
        release_scope(sid)
    return Run(
        request,
        "\n".join(t for t in texts if t).strip(),
        tuple(steps),
        failure[-1] if failure else "",
        seat.provider,
    )


__all__ = ["HELD_MARKER", "MAX_ROUNDS", "SYSTEM", "Run", "Step", "prompt_for", "run"]
