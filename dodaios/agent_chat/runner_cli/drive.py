"""Process driver: spawn, stream loop, reaping, timing limits and wire shapes."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.approval_bridge import approval_ref
from dodaios.agent_chat.effort import (
    effort_for_model,
    effort_note,
    normalize_effort,
)
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.model_fallback import (
    LimitSignal,
)
from dodaios.agent_chat.permissions import (
    PLAN_MODES,
    ladder_key,
    mode_after_plan,
)
from dodaios.agent_chat.questions import (
    CANCELLED,
    DEFAULTED,
    DELEGATOR,
    DELEGATOR_NOTE,
    UNATTENDED,
    as_line,
    parse_questions,
    recommended_answer,
)
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.runner_cli import agy as _rc_agy
from dodaios.agent_chat.runner_cli import claude as _rc_claude
from dodaios.agent_chat.runner_cli import codex as _rc_codex
from dodaios.agent_chat.runner_cli import plans as _rc_plans
from dodaios.agent_chat.runner_cli.agy import (
    _agy_effective_effort,
    _agy_model_ladder,
    _AgyState,
    translate_agy_line,
)
from dodaios.agent_chat.runner_cli.base import (
    _CLAUDE_CODE_RUNNERS,
    _REMOTE_PLANNING,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _carry_thread_conversation,
    _resolved_cwd,
    apply_child_env_drops,
    cli_catalog_scope,
    log,
    run_tag,
)
from dodaios.agent_chat.runner_cli.claude import (
    allow_bypass_after_plan,
    claude_bypass_chosen,
    claude_question_rows,
    claude_reported_commands,
    claude_rules_cover,
    claude_session_rules,
    claude_stream_input,
    dodaios_read_free,
    opens_with_command,
)
from dodaios.agent_chat.runner_cli.claude_stream import (
    _claude_outstanding,
    _claude_request_summary,
    _ClaudeState,
    grok_idle_wait,
    translate_claude_line,
)
from dodaios.agent_chat.runner_cli.codex import (
    _CodexState,
    _deliver_codex_images,
    isolate_task_tools,
    translate_codex_line,
)
from dodaios.agent_chat.runner_cli.cursor import _CursorState, translate_cursor_line
from dodaios.agent_chat.runner_cli.kimi import _KimiState, translate_kimi_line
from dodaios.agent_chat.runner_cli.opencode import _OpenCodeState, translate_opencode_line
from dodaios.agent_chat.runner_cli.plans import _PLANNERS, _release_plan
from dodaios.agent_chat.speed import apply_speed
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

_READLINE_LIMIT: Final[int] = 16 * 1024 * 1024

#: A coding-agent turn has no wall-clock limit: a session may run for days.
#: Stop ends it; a stalled ACP runtime ends through its own watchdog.
_TURN_TIMEOUT_S: Final[float | None] = None

#: Once a CLI gave its final answer (its ``result`` line) and runs nothing in
#: the background, the turn waits this long for the process to exit by
#: itself, then ends without it: the answer is in. A CLI that still has open
#: background tasks is waited for as long as they run — no clock (#1112).
_RESULT_EXIT_GRACE_S: Final[float] = 1.0

#: Claude Code wakes its agent within a moment of a background task ending.
#: When every task ended after an answer and nothing came for this long, its
#: stdin is closed, so a CLI with nothing left to do ends by itself.
_WAKE_GRACE_S: Final[float] = 30.0

#: A CLI that answered may go on shutting down (SessionEnd/Stop hooks, a
#: memory pass, flushing its session file) after its turn ended. Behind the
#: finished turn it is read on, and killed only once it printed nothing for
#: this long: it is not killed while it still works.
_REAP_GRACE_S: Final[float] = 120.0

#: The same silence limit once the session's next turn waits for it.
_REAP_HURRY_S: Final[float] = 15.0

#: After the process exited, its pipes get this long to drain. A grandchild
#: that inherited them (Windows: ``py.exe`` gone, ``python.exe`` alive) would
#: otherwise hold the turn open until it ends — hours, in one case.
_PIPE_DRAIN_S: Final[float] = 1.5

#: How long a killed CLI gets to be gone before the turn moves on regardless.
_KILL_WAIT_S: Final[float] = 2.0

#: A Grok turn idle without its result for this long waits on background
#: work, even when no tool result named it (``grok_idle_wait``).
_GROK_IDLE_HINT_S: Final[float] = 10.0

_EXIT_POLL_S: Final[float] = 0.05


# ---------------------------------------------------------- plain-text shape


@dataclass(slots=True)
class _TextState:
    """A CLI that prints its answer and nothing else — every line is the answer."""

    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    emitted_text: bool = False
    result_text: str = ""


def _translate_nothing(obj: dict[str, Any], st: Any) -> list[dict[str, Any]]:
    return []


#: shape -> (a fresh state for a turn, the line translator). The pump below
#: knows nothing about any CLI: it decodes a line, hands it here, and emits
#: what comes back. A new wire shape is one row.
_SHAPES: Final[dict[str, tuple[Callable[[str, str | None], Any], Callable[..., Any]]]] = {
    "claude": (lambda tid, vs: _ClaudeState(turn_id=tid, vendor_session=vs), translate_claude_line),
    "codex": (lambda tid, vs: _CodexState(turn_id=tid, vendor_session=vs), translate_codex_line),
    "agy": (lambda tid, vs: _AgyState(turn_id=tid, vendor_session=vs), translate_agy_line),
    "opencode": (
        lambda tid, vs: _OpenCodeState(turn_id=tid, vendor_session=vs),
        translate_opencode_line,
    ),
    "kimi": (lambda tid, vs: _KimiState(turn_id=tid, vendor_session=vs), translate_kimi_line),
    "cursor": (
        lambda tid, vs: _CursorState(turn_id=tid, vendor_session=vs),
        translate_cursor_line,
    ),
    "text": (lambda tid, vs: _TextState(turn_id=tid, vendor_session=vs), _translate_nothing),
}


# ------------------------------------------------------------ the turn


@dataclass(slots=True)
class _Outcome:
    status: str
    error: str | None
    usage: dict[str, int]
    cost_usd: float | None
    vendor_session: str | None
    #: The stream's limit signal of the run (``model_fallback``), if any.
    limit: LimitSignal | None = None
    #: ``error`` is a tool's output or the CLI's stderr, not the CLI's own
    #: words: a 429 a tool hit is not the model's limit.
    tool_error: bool = False


#: How a Codex turn that left a tool failure unresolved says so.
_UNRESOLVED_TOOLS: Final[str] = "Unresolved tool failure: "


async def _run_cli_once(
    handle: TurnHandle,
    user_text: str,
    runner: str,
    resume: str | None,
    *,
    identity: dodaios_harness.Identity | None = None,
    bridge: Any | None = None,
) -> _Outcome:
    session = handle.session
    # The previous turn's CLI may still be shutting down after its answer.
    if not await _await_lingering(session.session_id, getattr(handle, "cancel", None)):
        return _Outcome("cancelled", None, {}, None, None)
    cwd = _resolved_cwd(session.cwd or Path.home())
    effort = normalize_effort(session.provider, session.effort)
    # The picked model's own levels when the catalog knows them (``None`` =
    # the provider ladder applies); see ``effort_for_model``.
    model_ladder: list[str] | tuple[str, ...] | None = None
    # ``None`` = an external agent runtime, planned asynchronously (runner_acp).
    planner = _PLANNERS.get(runner)
    vendor_session: str | None = None
    from dodaios.society.remote import placement_for_session

    # A society agent placed on another computer runs its CLI there over SSH.
    placement = await placement_for_session(session)
    remote_token = _REMOTE_PLANNING.set(placement is not None)
    from dodaios.agent_chat import plain_chat

    # A plain chat's instructions open every conversation the CLI starts,
    # the one a lost resume falls back to included.
    planned_prompt = plain_chat.cli_prompt(handle, user_text, resume)
    # Set once planning succeeded; an external runtime's plan holds a turn slot.
    plan: CliPlan | None = None
    is_thread = getattr(session, "surface", "agent") != "society"
    if placement is not None and not is_thread and not getattr(handle, "tools_disabled", False):
        # Also refresh resumed conversations which remember the old missing bridge.
        planned_prompt = (
            "<jarvis_remote_context>\n"
            "You run on the connected computer. Dodaios MCP tools are connected for this turn "
            "under your own identity and permissions, including persistent routines, memory "
            "and the visible Dodaios browser on the main computer. Inspect the real tools; "
            "earlier messages saying they were unavailable are outdated. Native file tools "
            "and society_shell run on the connected computer; Dodaios file tools access "
            "your workspace on the main computer.\n</jarvis_remote_context>\n\n" + user_text
        )

    try:
        with cli_catalog_scope(
            cwd=cwd,
            ignore_user_config=identity is not None or bool(getattr(handle, "gateway_only", False)),
        ):
            if runner == "codex-cli" and placement is None:
                models = await asyncio.to_thread(
                    _rc_codex.read_codex_models, required_model=session.model
                )
                if session.model and (
                    models is None or not any(row["id"] == session.model for row in models)
                ):
                    # Pass it through: Codex itself reports an invalid model,
                    # as it does in a terminal.
                    log.warning(
                        "agent chat %s: model %r is not in the Codex catalog; passing it on",
                        handle.turn_id,
                        session.model,
                    )
                for row in models or []:
                    if row["id"] == session.model:
                        model_ladder = list(row.get("efforts", []))
                        break
            if runner == "claude-cli":
                from dodaios.agent_chat.catalog import claude_model_efforts

                # Claude Code folds a level the model lacks on its own (Opus
                # 4.6 runs ``--effort xhigh`` as high); fold it here first so
                # the flag, the note below and the composer name one level.
                model_ladder = claude_model_efforts(session.model)
            if runner == "agy-cli" and placement is None:
                # A chat can start before the model picker has loaded its catalog.
                # Resolve the installed CLI's effort ladder off the event loop so
                # newly available models keep the required model/effort pairing.
                await asyncio.to_thread(_rc_agy.read_agy_models, required_model=session.model)
            plan: CliPlan
            if planner is None:
                from dodaios.agent_chat.runner_acp import plan_runtime_turn

                plan = await plan_runtime_turn(
                    handle,
                    runner,
                    prompt=planned_prompt,
                    cwd=cwd,
                    resume=resume,
                    identity=identity,
                )
            else:
                if runner == "agy-cli":
                    model_ladder = _agy_model_ladder(session.model)
                if runner == "custom-cli":
                    # No effort knob: the command line is the user's own.
                    effort = ""
                elif identity is None and not (session.effort or "").strip():
                    # A coding thread nobody gave an effort runs on the CLI's
                    # own default, like a grid pane: no flag, no note.
                    effort = ""
                else:
                    effort = effort_for_model(session.provider, session.effort, model_ladder)
                    told_effort = (
                        _agy_effective_effort(session.model, effort)
                        if runner == "agy-cli"
                        else effort
                    )
                    if not opens_with_command(planned_prompt):
                        # A slash command runs only as the message's first word:
                        # with the note in front, Claude Code read "/context"
                        # as text and answered that it cannot run it.
                        planned_prompt = (
                            effort_note(session.provider, told_effort, model_ladder)
                            + planned_prompt
                        )
                if runner in _CLAUDE_CODE_RUNNERS:
                    await asyncio.to_thread(_rc_claude.warm_claude_capabilities)
                custom_kwargs: dict[str, Any] = (
                    {"provider": session.provider, "session_id": session.session_id}
                    if runner == "custom-cli"
                    else {}
                )
                plan = planner(
                    **custom_kwargs,
                    prompt=planned_prompt,
                    cwd=cwd,
                    model=session.model,
                    effort=effort,
                    permission_mode=plain_chat.permission_mode(
                        handle, runner, session.permission_mode
                    ),
                    resume=resume,
                    identity=identity,
                )
                # The speed pick (Claude Code's fast mode, a Codex service
                # tier) is one flag on top of any plan; see ``speed.py``.
                apply_speed(plan.argv, runner, getattr(session, "speed", ""))
                # A thread that plans may go on in "Bypass permissions".
                allow_bypass_after_plan(plan.argv, runner, session)
                if runner in _CLAUDE_CODE_RUNNERS:
                    from dodaios.agent_chat.thread_visuals import tell_claude_code

                    # A coding thread draws pictures; its agent is told so.
                    tell_claude_code(plan.argv, session)
                    from dodaios.briefs import standing

                    # A thread an agent opened takes work orders: the rules for them.
                    standing.tell_claude_code(plan.argv, handle)
                await asyncio.to_thread(_carry_thread_conversation, runner, resume, plan.env)
            apply_child_env_drops(session.session_id, plan.env)
            if getattr(handle, "tools_disabled", False):
                from dodaios.agent_chat.native_control import disable_cli_tools

                # A plain chat is a conversation: its next turn resumes this one.
                disable_cli_tools(
                    plan, runner, keep_session=bool(getattr(handle, "plain_system", ""))
                )
            images = tuple(getattr(handle, "images", ()) or ())
            if images:
                # Pictures go to the model itself, not only their description
                # (``plain_chat`` says why); a coding thread's CLI takes them too.
                await asyncio.to_thread(
                    plain_chat.attach_images, plan, runner, [Path(p) for p in images]
                )
            if getattr(handle, "gateway_only", False):
                isolate_task_tools(plan.argv, runner)
    except CliUnavailable as exc:
        _release_plan(plan)
        return _Outcome("error", str(exc), {}, None, None)
    finally:
        _REMOTE_PLANNING.reset(remote_token)

    vendor_session = plan.vendor_session
    if (
        getattr(handle, "goal_turn", False)
        and vendor_session
        and handle.control_service is not None
    ):
        handle.control_service.store.update_session(
            session.session_id, vendor_session=vendor_session
        )
    log.info("agent chat %s: %s argv=%s", handle.turn_id, runner, plan.argv[:6])
    started_at = time.time()
    tree = None
    #: Where a remote thread's folder went for this turn (``remote.Placement``).
    moved: Any = None
    if (
        placement is None
        and plan.proc is None
        and (
            getattr(handle, "goal_turn", False)
            or (session.surface == "society" and session.permission_mode == "plan")
            or plan.acp is not None
        )
    ):
        from dodaios.core.process_tree import make_process_tree

        tree = make_process_tree("chat-controlled-cli")
    proc: Any
    if plan.proc is not None:
        proc = plan.proc
    elif placement is not None:
        from dodaios.agent_chat.remote_cli import RemoteCliUnavailable, spawn

        prompt_files: dict[str, str] = {}
        thread_folder = ""
        if is_thread:
            from dodaios.agent_chat import remote_thread_sync
            from dodaios.agentic_ide import remote as ide_remote

            # The thread's folder goes up first, mapped the way grid panes map it.
            try:
                moved = await remote_thread_sync.send_folder(handle, placement[0], cwd)
            except ide_remote.MoveError as exc:
                return _Outcome("error", str(exc), {}, None, None)
            thread_folder = moved.remote_folder
            await remote_thread_sync.emit_step(handle, "start", cli=CLI_BINARIES[runner][0])
        if identity is not None and identity.path is not None:
            try:
                prompt_files[str(identity.path)] = await asyncio.to_thread(
                    Path(identity.path).read_text, encoding="utf-8"
                )
            except OSError:
                log.warning("agent chat: identity file unreadable for a remote turn")
        try:
            proc = await spawn(
                placement[0],
                agent_id=placement[1],
                runner=runner,
                binary=CLI_BINARIES[runner][0],
                argv=plan.argv,
                local_cwd=str(cwd),
                env=plan.env,
                system_prompt_files=prompt_files,
                session_id=session.session_id,
                tools_enabled=not is_thread and not getattr(handle, "tools_disabled", False),
                remote_cwd_override=thread_folder,
            )
        except RemoteCliUnavailable as exc:
            return _Outcome("error", str(exc), {}, None, None)
    else:
        hosted = None
        if tree is None and plan.acp is None and _survives_restart(handle, identity):
            from dodaios.agent_chat import turn_host_client

            hosted = await turn_host_client.spawn(
                plan.argv,
                cwd=str(cwd),
                env=plan.env,
                # The host writes the handshake and the prompt itself, so a
                # restart between spawn and feed cannot leave the CLI waiting.
                stdin=(
                    (plan.control_init or "") + plan.stdin_text
                    if plan.stdin_text is not None
                    else None
                ),
                keep_stdin=plan.keep_stdin,
                meta=_hosted_meta(handle, runner, plan, cwd, started_at),
                # Claude Code keeps reading stdin after its result line. This
                # process closes it once the turn is over; the host does when
                # no app has read the turn for a while, so the CLI still ends.
                close_stdin_on="result" if plan.keep_stdin and plan.shape == "claude" else "",
            )
        if hosted is not None:
            proc = hosted
        else:
            proc = await _spawn_child(plan, cwd, tree, runner)
            if isinstance(proc, _Outcome):
                return proc
    outcome = await _drive_cli(
        handle,
        proc,
        plan,
        runner,
        cwd=cwd,
        started_at=started_at,
        placement=placement,
        tree=tree,
        bridge=bridge,
    )
    if moved is not None:
        from dodaios.agent_chat import remote_thread_sync

        # However the turn ended, what it wrote over there comes back here.
        await remote_thread_sync.return_work(handle, placement[0], cwd, moved)
    return outcome


def _survives_restart(handle: TurnHandle, identity: Any) -> bool:
    """Whether this turn's CLI runs in the turn host and outlives an app restart.

    Threads in the Agentic IDE (surface ``agent``) only: their CLI is a plain
    coding agent whose whole turn is its own process. A turn running AS
    Jarvis (``identity``), a goal or a tool-less helper turn depends on state
    that lives in this process (MCP tool context, approval bridge, goal
    control) and would lose it across a restart, so it stays a child here.
    """
    session = handle.session
    return (
        getattr(session, "surface", "") == "agent"
        and identity is None
        and not getattr(handle, "goal_turn", False)
        and not getattr(handle, "tools_disabled", False)
        and not getattr(handle, "gateway_only", False)
    )


def _hosted_meta(
    handle: TurnHandle, runner: str, plan: CliPlan, cwd: Path, started_at: float
) -> dict[str, Any]:
    """What a hosted turn needs to be carried on after an app restart."""
    return {
        "session_id": handle.session.session_id,
        "turn_id": handle.turn_id,
        "runner": runner,
        "shape": plan.shape,
        "keep_stdin": plan.keep_stdin,
        "control": plan.control_init is not None,
        "vendor_session": plan.vendor_session,
        "discover": plan.discover is not None,
        "codex_home": plan.env.get("CODEX_HOME", ""),
        "cwd": str(cwd),
        "started_at": started_at,
    }


async def _spawn_child(
    plan: CliPlan, cwd: Path, tree: Any, runner: str
) -> asyncio.subprocess.Process | _Outcome:
    """Start the CLI as this process's own child (no turn host)."""
    if plan.acp is not None and plan.env is not None and os.name != "nt":
        # Every descendant inherits this mark, so the turn's tracker finds a
        # detached one even when no snapshot saw it (POSIX; Windows: the job).
        from uuid import uuid4

        from dodaios.core.process_tree import TURN_MARKER_ENV

        plan.env[TURN_MARKER_ENV] = uuid4().hex
    try:
        if runner == "codex-cli" and os.name == "nt":
            from dodaios.core.path_augment import ensure_cli_paths

            ensure_cli_paths()
            plan.env["PATH"] = os.environ.get("PATH", "")
        proc = await asyncio.create_subprocess_exec(
            *plan.argv,
            cwd=str(cwd),
            env=plan.env,
            stdin=asyncio.subprocess.PIPE
            if plan.stdin_text is not None or plan.acp is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=NO_WINDOW_CREATIONFLAGS,
            start_new_session=tree is not None and os.name != "nt",
            limit=_READLINE_LIMIT,
        )
        if tree is not None:
            tree.assign(proc.pid)
    except (OSError, ValueError) as exc:
        if tree is not None:
            tree.close()
        _release_plan(plan)
        return _Outcome("error", f"Could not start {runner}: {exc}", {}, None, None)
    return proc


async def _drive_cli(
    handle: TurnHandle,
    proc: Any,
    plan: CliPlan,
    runner: str,
    *,
    cwd: Path,
    started_at: float,
    placement: Any,
    tree: Any,
    bridge: Any | None,
    timeout_s: float | None = _TURN_TIMEOUT_S,
) -> _Outcome:
    """Read a started CLI to its end: translate, answer, and judge the outcome.

    ``proc`` is a child process, a remote one, or a CLI in the turn host
    (``turn_host_client.HostedCli``). A hosted CLI reattached after an app
    restart replays the lines this turn already handled first
    (``stdout.replaying``): they rebuild the translator's state and emit
    nothing, so the timeline carries on from the first line it has not seen.
    """
    session = handle.session
    chat_ref = approval_ref(session.session_id)
    #: The session rules "Always allow" gave this chat (Claude Code), kept
    #: across turns by the service like a terminal session keeps its own.
    rules_of = getattr(handle.control_service, "cli_session_rules", None)
    always_rules: list[dict[str, Any]] = rules_of(session.session_id) if callable(rules_of) else []
    status = "done"
    error_text: str | None = None
    vendor_session = plan.vendor_session
    hosted = bool(getattr(proc, "hosted", False))
    #: Claude Code's stdin stays open past its result line: an agent that
    #: only waits for its background tasks then still takes a message. A turn
    #: host from an older build closes stdin at that line itself.
    stdin_outlives_result = (
        plan.keep_stdin
        and plan.shape == "claude"
        and bool(getattr(proc, "stdin_after_result", not hosted))
    )
    if plan.acp is not None:
        state: Any = plan.acp
        translate: Any = None
        state.run = run_tag(proc)
    else:
        make_state, translate = _SHAPES[plan.shape]
        state = make_state(handle.turn_id, vendor_session)
        if isinstance(state, _CodexState):
            state.run = run_tag(proc)
        if runner == "grok-cli" and isinstance(state, _ClaudeState):
            state.grok = True
        elif runner == "claude-cli" and isinstance(state, _ClaudeState):
            state.usage_home = plan.env.get("CLAUDE_CONFIG_DIR", "")
    # Lines that are not the CLI's JSON — a banner, a warning, the whole
    # answer of a plain-text CLI — shown as they come, and kept as the answer
    # of last resort when the stream said nothing else.
    plain: list[str] = []
    plain_id = f"plain-{handle.turn_id}"
    stderr_tail: list[str] = []

    def _provider_error() -> str | None:
        signal = plan.provider_failure
        if signal is not None and signal.done() and not signal.cancelled():
            return signal.result()
        return None

    async def _drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            try:
                line = await proc.stderr.readline()
            except ValueError:
                # A diagnostic line past the read limit: dropped, never fatal.
                reads[0] += 1
                continue
            reads[0] += 1
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                stderr_tail.append(text)
                del stderr_tail[:-40]

    async def _say_plain(line: str, *, replay: bool = False) -> None:
        plain.append(line + "\n")
        if replay:
            return
        await handle.emit(
            make_event(
                "text_delta",
                {"turn_id": handle.turn_id, "message_id": plain_id, "text": line + "\n"},
            )
        )

    #: The conversation id the session row already holds.
    kept_conversation = [getattr(session, "vendor_session", None)]

    def _keep_conversation() -> None:
        # The CLI names its conversation in its first lines. The session takes
        # it at once: a first turn cut off before its end (a reboot, a crash)
        # left the thread without it, and the next message then started a new
        # conversation that knew nothing of the work so far (2026-11-12).
        named = getattr(state, "vendor_session", None)
        if not named or named == kept_conversation[0] or handle.on_conversation is None:
            return
        kept_conversation[0] = named
        handle.on_conversation(str(named))

    async def _pump_stdout() -> None:
        nonlocal grace_kill, status, error_text
        assert proc.stdout is not None
        while True:
            # Between lines: the drain after exit may stop reading here, never
            # while a line is still being translated (``_natural_end``).
            busy[0] = False
            try:
                raw = await proc.stdout.readline()
            except ValueError:
                # One line past _READLINE_LIMIT. For an ACP runtime that is a
                # broken frame of the turn itself: end it with a plain reason
                # instead of an unhandled error. Other CLIs: skip the line.
                if plan.acp is None:
                    continue
                status = "error"
                error_text = (
                    f"{runner} sent a message larger than "
                    f"{_READLINE_LIMIT // (1024 * 1024)} MB; the turn was stopped."
                )
                _kill(proc)
                return
            reads[0] += 1
            busy[0] = True
            activity[0] = time.monotonic()
            if hosted and getattr(proc, "handed_over", False):
                return
            if not raw:
                return
            # A line this turn handled before an app restart: rebuild state only.
            replay = hosted and bool(getattr(proc.stdout, "replaying", False))
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if plan.shape == "text":
                await _say_plain(line, replay=replay)
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                if plan.acp is None:
                    await _say_plain(line, replay=replay)
                else:
                    log.debug("agent chat %s: non-ACP stdout line skipped", handle.turn_id)
                continue
            if not isinstance(obj, dict):
                continue
            if replay:
                if obj.get("type") not in ("control_request", "control_response"):
                    translate(obj, state)
                    _keep_conversation()
                    _note_settled()
                continue
            if plan.acp is not None:
                if _provider_error() or handle.cancel.is_set():
                    # Do not present a runtime's synthetic error prose as an
                    # assistant answer, or process tools after the failure.
                    continue
                await plan.acp.on_message(obj, acp_io)
                _keep_conversation()
                if plan.acp.saw_result:
                    if tracker is not None:
                        # Last look at its children while the runtime still
                        # lives: once it exits, detached ones are orphans.
                        tracker.snapshot()
                    # The prompt answered; closing stdin lets the runtime exit.
                    # One that keeps running anyway (a child holding the pipe)
                    # is ended so the chat is not held busy by a finished turn.
                    _close_stdin()
                    if grace_kill is None:
                        grace_kill = asyncio.get_running_loop().call_later(
                            _rc_plans._ACP_EXIT_GRACE_S, _kill, proc
                        )
                    _note_settled()
                continue
            if plan.control_init is not None:
                if obj.get("type") == "control_request":
                    await _answer_control_request(obj)
                    continue
                if obj.get("type") == "control_response":
                    # The CLI's answer to our handshake (its command list):
                    # kept for the thread's "/" picker, never shown on the
                    # timeline and not a line to translate.
                    _remember_cli_commands(obj)
                    continue
            if obj.get("type") == "system" and obj.get("subtype") in ("init", "commands_changed"):
                _remember_cli_commands(obj)
            for ev in translate(obj, state):
                await handle.emit(ev)
            _keep_conversation()
            if (
                plan.keep_stdin
                and not stdin_outlives_result
                and getattr(state, "saw_result", False)
            ):
                # An older turn host closed stdin at the result line already.
                _close_stdin()
            _note_settled()

    def _note_settled() -> None:
        # The answer is in and nothing runs in the background: the turn may
        # end without waiting for the process (``_RESULT_EXIT_GRACE_S``). A
        # task opened again (a woken agent starts one) takes that back.
        if _answer_settled(state):
            if plan.keep_stdin and plan.acp is None:
                # Nothing is left to say to it; closing stdin lets the CLI
                # exit. Until here it stayed open: an agent that waits for
                # its background tasks still takes a message (``_steer``).
                _close_stdin()
            settled.set()
        else:
            settled.clear()

    def _remember_cli_commands(obj: dict[str, Any]) -> None:
        """Hand the commands Claude Code reports to the thread's "/" picker."""
        if runner not in _CLAUDE_CODE_RUNNERS:
            return
        try:
            from dodaios.agent_chat import typeahead

            reported = claude_reported_commands(obj)
            if reported:
                typeahead.remember_cli_commands(runner, session.cwd, reported)
        except Exception as exc:  # noqa: BLE001 - the picker is a convenience
            log.debug("agent chat %s: command list not kept: %s", handle.turn_id, exc)

    def _close_stdin() -> None:
        if proc.stdin is None or proc.stdin.is_closing():
            return
        try:
            proc.stdin.close()
        except OSError as exc:
            log.debug("agent chat %s: stdin close failed: %s", handle.turn_id, exc)

    async def _write_stdin(text: str) -> bool:
        """Write to the CLI's stdin; False when it no longer takes input."""
        if proc.stdin is None or proc.stdin.is_closing():
            return False
        try:
            proc.stdin.write(text.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            log.debug("agent chat %s: stdin write failed: %s", handle.turn_id, exc)
            return False
        return True

    async def _answer_control_request(obj: dict[str, Any]) -> None:
        """A Claude Code ``control_request`` — a permission prompt — answered
        from the chat's approval card. Anything that is not ``can_use_tool``
        is declined (the CLI asks nothing else of a stdio prompt tool today)."""
        request_id = str(obj.get("request_id") or "")
        req = obj.get("request") if isinstance(obj.get("request"), dict) else {}
        subtype = str(req.get("subtype") or "")
        decision = "deny"
        message = "Not supported by this chat."
        tool_name = ""
        if subtype == "can_use_tool":
            tool_name = str(req.get("tool_name") or req.get("display_name") or "tool")
            tool_input = req.get("input") if isinstance(req.get("input"), dict) else {}
            call_id = str(req.get("tool_use_id") or uuid.uuid4().hex)
            if tool_name == "AskUserQuestion":
                await _respond(request_id, await _claude_question(tool_input))
                return
            if tool_name != "ExitPlanMode" and (
                claude_bypass_chosen(runner, session)
                or claude_rules_cover(always_rules, tool_name, tool_input)
                or await dodaios_read_free(session, tool_name, tool_input)
            ):
                # The person picked "Bypass permissions" (the CLI still asks
                # once the model enters plan mode itself, or when it did not
                # take the mode an approved plan returned to), covered by this
                # process's own "Always allow", or a read of Dodaios' own
                # tools that Ask never puts in front of the person.
                await _respond(request_id, {"behavior": "allow", "updatedInput": tool_input})
                return
            summary = str(req.get("description") or "") or _claude_request_summary(
                tool_name, tool_input
            )
            # The card sits on the tool row the assistant line announced; a
            # plan's ExitPlanMode has no row yet, so it gets one here.
            announced: set[str] = getattr(state, "emitted_tool_ids", set())
            if tool_name == "ExitPlanMode" and call_id not in announced:
                announced.add(call_id)
                await handle.emit(
                    make_event(
                        "tool_call",
                        {
                            "turn_id": handle.turn_id,
                            "call_id": call_id,
                            "name": tool_name,
                            "input": tool_input,
                            "summary": "Plan ready — approve to start building",
                        },
                    )
                )
                summary = "Plan ready — approve to start building"
            approval_pending[0] += 1
            try:
                decision = await handle.request_approval(call_id, tool_name, tool_input, summary)
            finally:
                approval_pending[0] -= 1
                activity[0] = time.monotonic()
            message = "The turn was stopped."
            if decision == "deny":
                feedback_of = getattr(handle.control_service, "take_deny_feedback", None)
                said = feedback_of(session.session_id, call_id) if callable(feedback_of) else ""
                message = said or "The person declined this action."
        if decision in {"allow", "allow_always"}:
            body: dict[str, Any] = {"behavior": "allow", "updatedInput": req.get("input") or {}}
            if (
                decision == "allow_always"
                and subtype == "can_use_tool"
                and tool_name != "ExitPlanMode"
            ):
                # Without a rule the CLI asked again at the very next call of
                # this turn: the session's new access mode only reaches the
                # next process. Not for a plan: its suggestions switch the
                # whole session's mode, and where an approved plan goes on
                # is the permission pill's to say (``_leave_plan_mode``).
                body["updatedPermissions"] = claude_session_rules(
                    tool_name, req.get("permission_suggestions")
                )
                always_rules.extend(body["updatedPermissions"])
            if bridge is not None and subtype == "can_use_tool":
                # A Jarvis tool the CLI just asked about will hit the executor's
                # own gate over MCP in a moment; the person has answered once.
                bridge.note_cli_approval(chat_ref, tool_name)
            if tool_name == "ExitPlanMode":
                build = await _leave_plan_mode()
                if build:
                    body["updatedPermissions"] = [
                        {"type": "setMode", "mode": build, "destination": "session"}
                    ]
        else:
            body = {"behavior": "deny", "message": message}
        await _respond(request_id, body)

    async def _respond(request_id: str, body: dict[str, Any]) -> None:
        frame = {
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": body},
        }
        await _write_stdin(json.dumps(frame, ensure_ascii=False) + "\n")

    async def _claude_question(tool_input: dict[str, Any]) -> dict[str, Any]:
        """Claude Code's own ``AskUserQuestion``, answered on the chat's question card.

        A question's ``multiSelect`` becomes a multi-select card question. The
        answers go back the way the CLI reads them: ``updatedInput`` keeps the
        questions and adds ``answers`` keyed by each question's text.
        """
        raw = tool_input.get("questions")
        rows = raw if isinstance(raw, list) else []
        try:
            specs = parse_questions({"questions": claude_question_rows(rows)})
        except ValueError as exc:  # the error text goes back to the model in the deny message
            return {
                "behavior": "deny",
                "message": f"Invalid questions ({exc}). Ask 1-4 questions with 2-4 options each.",
            }
        ask = getattr(handle.control_service, "ask_questions", None)
        if not callable(ask):
            return {
                "behavior": "deny",
                "message": "Nobody can answer here. Decide yourself and state your assumptions.",
            }
        try:
            approval_pending[0] += 1
            try:
                # Like the terminal: the card waits for the person, and every ask
                # of the turn gets one.
                answers = await ask(session.session_id, specs, timeout_s=None, rationed=False)
            finally:
                approval_pending[0] -= 1
                activity[0] = time.monotonic()
        except RuntimeError as exc:
            # The turn has no card to show: the agent's own first options
            # stand, exactly as on an unanswered card.
            log.info("agent chat %s: question not shown (%s)", handle.turn_id, exc)
            answers = [recommended_answer(spec, UNATTENDED) for spec in specs]
        if any(a.source == CANCELLED for a in answers):
            return {"behavior": "deny", "message": "The turn was stopped."}
        # A multi-select answer reads the way the CLI's own picker writes one:
        # the chosen labels joined by commas.
        # A skipped question (empty answer) still gets words the CLI can read.
        # A default the person never picked says so, so the model cannot claim
        # the person chose it.
        picked = {
            str(row.get("question") or ""): (as_line(a.answer) or "No preference; decide yourself.")
            + (
                (
                    " (the person did not answer; your default)"
                    if a.answer
                    else " (the person did not answer)"
                )
                if a.source in DEFAULTED
                else ""
            )
            + (f" ({DELEGATOR_NOTE})" if a.source == DELEGATOR else "")
            for row, a in zip(rows, answers, strict=True)
        }
        return {"behavior": "allow", "updatedInput": {**tool_input, "answers": picked}}

    async def _leave_plan_mode() -> str:
        """The access mode an approved plan goes on in, or "" to leave it to the CLI.

        Coding threads only (``turn_prompts``). A thread the person switched
        to Plan goes back to the mode its permission pill names; one whose
        agent entered plan mode on its own keeps the mode it has
        (``mode_after_plan``). The session and the composer follow, and so
        does this turn: from here on ``session`` is the thread as it is now,
        so the checks below it answer for the new mode, and the Dodaios tools
        are no longer held read-only.
        """
        nonlocal session
        from dodaios.agent_chat.surface_kits import kit_for
        from dodaios.core.tool_read_only import set_chat_read_only

        if not kit_for(session.surface).turn_prompts:
            return ""
        store = getattr(handle.control_service, "store", None)
        read = getattr(store, "get_session", None)
        # The pill may have moved while the plan was written.
        now = (read(session.session_id) if callable(read) else None) or session
        build = mode_after_plan(
            ladder_key(session.surface, runner),
            str(now.permission_mode or ""),
            str(getattr(now, "build_mode", "") or ""),
        )
        if store is not None and build != now.permission_mode:
            now = store.update_session(session.session_id, permission_mode=build) or now
            await handle.emit(make_event("session_updated", {"permission_mode": build}))
        if getattr(now, "permission_mode", "") != build:
            try:
                now = replace(now, permission_mode=build)
            except TypeError:  # not a session record (a test double): the mode alone is lost
                log.debug("agent chat %s: turn keeps its start mode", handle.turn_id)
        session = now
        set_chat_read_only(session.session_id, build in PLAN_MODES)
        return build

    async def _feed_stdin() -> None:
        if proc.stdin is None or hosted:
            # The turn host wrote the handshake and the prompt at spawn.
            return
        try:
            # The control-protocol handshake goes FIRST, on the same stdin, so
            # the CLI knows a client is listening before it needs to ask about
            # the first tool call. Back to back with the prompt on purpose: the
            # CLI reads its input in order, and waiting for the response would
            # add a round-trip to every turn for no gain.
            if plan.control_init is not None:
                proc.stdin.write(plan.control_init.encode("utf-8"))
                await proc.stdin.drain()
            if plan.acp is not None:
                proc.stdin.write(plan.acp.opening_frame().encode("utf-8"))
                await proc.stdin.drain()
                if plan.acp.saw_result:
                    # Settled before a single frame (a warm process that cannot
                    # reopen the conversation): nothing more will come.
                    _close_stdin()
            if plan.stdin_text is not None:
                proc.stdin.write(plan.stdin_text.encode("utf-8"))
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            log.debug("agent chat %s: stdin closed early: %s", handle.turn_id, exc)
        finally:
            # A CLI that talks back on stdin keeps it until its result line.
            if not plan.keep_stdin:
                _close_stdin()

    async def _acp_cancel() -> None:
        """Ask an ACP runtime to end its turn (``session/cancel``), then wait briefly.

        Killing the process alone is not a stop for every runtime: an OpenClaw
        run lives in its Gateway and keeps calling the model and running
        tools after its bridge dies. The caller kills afterwards either way.
        """
        if plan.provider_failure is not None:
            # Revoke inference before waiting for the runtime to acknowledge stop.
            plan.provider_failure.cancel()
        if plan.acp is None or hosted or proc.returncode is not None:
            return
        frame = plan.acp.cancel_frame()
        if frame is None:
            return
        from dodaios.agent_runtimes.acp import frame_line

        await _write_stdin(frame_line(frame))
        deadline = time.monotonic() + _rc_plans._ACP_CANCEL_GRACE_S
        while time.monotonic() < deadline:
            if plan.acp.saw_result or proc.returncode is not None:
                return
            await asyncio.sleep(0.1)

    async def _watch_cancel() -> None:
        await handle.cancel.wait()
        await _acp_cancel()
        _kill(proc)

    async def _watch_provider_failure() -> None:
        nonlocal status, error_text
        if plan.provider_failure is None:
            return
        error_text = await asyncio.wrap_future(plan.provider_failure)
        status = "error"
        await _acp_cancel()
        if tree is not None:
            # Descendants can hold stdout open after the runtime exits. Reap
            # the containment group now, before waiting for either pipe.
            tree.close()
        _kill(proc)

    async def _watch_stall() -> None:
        """End an ACP turn whose runtime stopped making progress (AP-19)."""
        nonlocal status, error_text
        acp = plan.acp
        if acp is None or hosted:
            return
        from dodaios.agent_runtimes import gateway

        started = time.monotonic()
        reason = ""
        while not acp.saw_result and proc.returncode is None:
            await asyncio.sleep(_rc_plans._ACP_WATCH_TICK_S)
            now = time.monotonic()
            if (
                approval_pending[0]
                or acp.tool_running()
                or gateway.model_call_open(plan.provider_failure)
            ):
                activity[0] = now  # a person, a tool or the model sets this pace
                continue
            if not acp.handshaken:
                if now - started > _rc_plans._ACP_HANDSHAKE_TIMEOUT_S:
                    from dodaios.agent_chat.turn_errors import handshake_reason

                    reason = handshake_reason(runner, _rc_plans._ACP_HANDSHAKE_TIMEOUT_S)
                    break
                continue
            if now - activity[0] > _rc_plans._ACP_IDLE_TIMEOUT_S:
                from dodaios.agent_chat.turn_errors import stall_reason

                # The runtime's display name, and a hint when a local model is
                # the likely cause (busy, slow, or queued behind another one).
                reason = stall_reason(
                    runner,
                    _rc_plans._ACP_IDLE_TIMEOUT_S,
                    provider=str(handle.session.provider or ""),
                )
                break
        if not reason or acp.saw_result:
            return
        log.warning("agent chat %s: %s", handle.turn_id, reason)
        status, error_text = "error", reason
        await _acp_cancel()
        _kill(proc)

    class _AcpIO:
        """What an ACP turn needs from this process: stdin, the chat, the card."""

        async def write(self, frame: dict[str, Any]) -> None:
            from dodaios.agent_runtimes.acp import frame_line

            await _write_stdin(frame_line(frame))

        async def emit(self, event: dict[str, Any]) -> None:
            await handle.emit(event)

        async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
            approval_pending[0] += 1
            try:
                decision = await handle.request_approval(call_id, name, args, summary)
            finally:
                approval_pending[0] -= 1
                activity[0] = time.monotonic()
            if decision in {"allow", "allow_always"} and bridge is not None:
                # A Jarvis tool the runtime just asked about reaches the
                # executor's own gate over MCP next; the person answered once.
                bridge.note_cli_approval(chat_ref, name)
            return str(decision)

    acp_io = _AcpIO()
    gate_decider = None
    if plan.acp is not None:
        from dodaios.agent_runtimes import native_gate

        acp_turn = plan.acp

        async def gate_decider(
            call_id: str, tool: str, args: dict[str, Any], title: str, read_only: bool
        ) -> str:
            # A native tool the runtime cannot ask about (OpenClaw's file
            # tools, through Dodaios' gate plugin): this turn's card decides.
            return await acp_turn.native_permission(
                acp_io, call_id, tool, args, title, read_only=read_only
            )

        native_gate.register(handle.session.session_id, gate_decider)
    grace_kill: asyncio.TimerHandle | None = None
    settled = asyncio.Event()

    async def _watch_missing_wake() -> None:
        """Close stdin when the wake after the last background task never comes.

        Stdin stays open while an answered turn waits for its tasks, and
        Claude Code never exits on an open stdin. Normally the agent wakes
        when a task ends and the turn settles on its next answer. If every
        task ended and the CLI then said nothing for ``_WAKE_GRACE_S``, stdin
        is closed: the CLI finishes what it has and ends by itself.
        """
        if not stdin_outlives_result:
            return
        while proc.returncode is None:
            await asyncio.sleep(min(1.0, _WAKE_GRACE_S / 4))
            if (
                getattr(state, "saw_result", False)
                and getattr(state, "idle", False)
                and not _claude_outstanding(state)
                and time.monotonic() - activity[0] >= _WAKE_GRACE_S
            ):
                _close_stdin()
                return

    async def _watch_grok_idle() -> None:
        """Say a Grok turn waits on background work its stream never named."""
        if not getattr(state, "grok", False):
            return
        while True:
            await asyncio.sleep(min(_rc_plans._ACP_WATCH_TICK_S, _GROK_IDLE_HINT_S / 2))
            if time.monotonic() - activity[0] < _GROK_IDLE_HINT_S:
                continue
            for ev in grok_idle_wait(state):
                await handle.emit(ev)

    # Stall watchdog state: the last stdout frame, and an open approval card.
    activity = [time.monotonic()]
    #: Lines read from either pipe: the drain after exit counts them, never a clock.
    reads = [0]
    #: The pump is handling a line it read (translating, emitting).
    busy = [False]
    approval_pending = [0]  # open approval / question cards (a count)
    # POSIX: descendants that leave the process group (setsid) are remembered
    # while the runtime runs and reaped with it (Windows: the job object).
    tracker = None
    if plan.acp is not None and tree is not None and not hosted and placement is None:
        from dodaios.core.process_tree import TURN_MARKER_ENV, DescendantTracker

        tracker = DescendantTracker(proc.pid, marker=(plan.env or {}).get(TURN_MARKER_ENV))
        tracker.start()

    if plan.keep_stdin and plan.shape == "claude" and handle.on_steer is not None:

        async def _steer(text: str, images: tuple[str, ...] = ()) -> bool:
            # Claude Code reads further stream-json user messages for as long
            # as its stdin is open: while it works, and after an answer while
            # it waits for its background tasks. Once the turn is over (or
            # was stopped) there is nobody to read. ``images`` are picture
            # files of the message, sent as its image blocks.
            line = claude_stream_input(text)
            if images:
                from dodaios.agent_chat import plain_chat

                pairs = await asyncio.to_thread(
                    lambda: [pair for pair in map(plain_chat.encoded, images) if pair is not None]
                )
                line = plain_chat.claude_message_with_images(line, pairs)
            if (
                _answer_settled(state)
                or handle.cancel.is_set()
                or proc.returncode is not None
                or proc.stdin is None
                or proc.stdin.is_closing()
            ):
                return False
            if not await _write_stdin(line):
                return False
            # The agent answers this message within the turn: an answer
            # already given is no longer its last word.
            state.answered = False
            _note_settled()
            return True

        handle.on_steer(_steer)

    pump = asyncio.create_task(_pump_stdout())
    drain = asyncio.create_task(_drain_stderr())
    feeder = asyncio.create_task(_feed_stdin())
    watcher = asyncio.create_task(_watch_cancel())
    provider_watcher = asyncio.create_task(_watch_provider_failure())
    stall_watcher = asyncio.create_task(_watch_stall())
    hint_watcher = asyncio.create_task(_watch_grok_idle())
    wake_watcher = asyncio.create_task(_watch_missing_wake())
    natural: asyncio.Task[None] | None = None
    #: The turn ended on its answer, maybe before the process exited.
    ended_on_answer = False
    #: ... and the process was still shutting down: it is reaped in the
    #: background (``_reap_after_answer``), which also releases a hosted one.
    reap_later = False
    try:
        deadline = None if getattr(handle, "goal_turn", False) else timeout_s
        async with asyncio.timeout(deadline):
            natural = asyncio.create_task(
                _natural_end(proc, pump, drain, feeder, lambda: reads[0], lambda: busy[0])
            )
            ended_on_answer = await _until_end_or_answer(natural, settled, state)
    except TimeoutError:
        log.warning(
            "agent chat %s: %s timed out (result=%s, returncode=%s, stdout_done=%s)",
            handle.turn_id,
            runner,
            getattr(state, "saw_result", False),
            proc.returncode,
            pump.done(),
        )
        await _acp_cancel()
        _kill(proc)
        status = "error"
        error_text = f"{runner} did not finish within {int(timeout_s or 0)} s."
    except asyncio.CancelledError:
        if hosted and not handle.cancel.is_set():
            # The app is going away, nobody pressed Stop: the CLI keeps working
            # in the turn host and the next app start carries the turn on.
            proc.detach()
        else:
            await _acp_cancel()
            _kill(proc)
        raise
    finally:
        if handle.on_steer is not None:
            handle.on_steer(None)
        if gate_decider is not None:
            native_gate.unregister(handle.session.session_id, gate_decider)
        watcher.cancel()
        provider_watcher.cancel()
        stall_watcher.cancel()
        hint_watcher.cancel()
        wake_watcher.cancel()
        # Nothing the process prints from here on reaches this turn: lines
        # after its answer can no longer change what was translated.
        for task in (natural, pump, drain, feeder):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(t for t in (natural, watcher, provider_watcher, stall_watcher, hint_watcher) if t),
            wake_watcher,
            pump,
            drain,
            feeder,
            return_exceptions=True,
        )
        if grace_kill is not None:
            grace_kill.cancel()

        def _cleanup() -> None:
            if tracker is not None:
                tracker.close()
            if tree is not None:
                tree.close()
            _release_plan(plan)

        detached = bool(getattr(proc, "detached", False))
        reap_later = (
            ended_on_answer
            and proc.returncode is None
            and not detached
            # Another app process carries a handed-over turn on: never reap it.
            and not getattr(proc, "handed_over", False)
        )
        if reap_later:
            # The answer is in: the turn ends now, the CLI finishes its own
            # shutdown (or is killed after a grace) behind it.
            _linger(
                session.session_id,
                lambda hurry: _reap_after_answer(
                    hurry, proc, handle.turn_id, runner, hosted, _cleanup
                ),
            )
        else:
            if proc.returncode is None and not detached:
                _kill(proc)
                if not await _exited_within(proc, _KILL_WAIT_S):
                    log.warning("Agent CLI did not reap after cancellation")
            _cleanup()
            _close_pipes(proc)

    if hosted and getattr(proc, "handed_over", False):
        from dodaios.agent_chat.turn_host_client import TurnHandedOver

        raise TurnHandedOver(handle.turn_id)
    if hosted and not reap_later:
        # Handled to the end: the host (or its spool file) may drop the lines.
        proc.release()
        if getattr(proc, "host_lost", False) and not handle.cancel.is_set():
            status = "error"
            error_text = "The process that ran this agent stopped unexpectedly."
    #: The stderr tail when it became the error: never read for a limit.
    stderr_said = ""
    if handle.cancel.is_set():
        status = "cancelled"
    elif provider_error := _provider_error():
        status, error_text = "error", provider_error
    elif status == "done":
        if state.status == "error":
            status, error_text = (
                "error",
                state.error or getattr(state, "last_tool_error", None),
            )
        elif proc.returncode not in (0, None) and not (
            # An ACP turn that answered and was then ended by the grace timer.
            plan.acp is not None and plan.acp.saw_result
        ):
            status = "error"
            raw_tail = stderr_said = "\n".join(stderr_tail[-8:]).strip()
            if raw_tail:
                from dodaios.agent_chat.turn_errors import redact

                # The raw tail stays in the log, redacted; the card shows a
                # short reason (``turn_errors.readable_turn_error``).
                log.warning(
                    "agent chat %s: %s exited with code %s; stderr tail:\n%s",
                    handle.turn_id,
                    runner,
                    proc.returncode,
                    redact(raw_tail),
                )
            error_text = (
                state.error
                or getattr(state, "last_error", None)
                or getattr(state, "last_tool_error", None)
                or raw_tail
                or f"{runner} exited with code {proc.returncode}."
            )
        elif plan.shape == "codex" and state.failed_tools:
            status = "error"
            error_text = _UNRESOLVED_TOOLS + ", ".join(sorted(state.failed_tools))
        elif (runner in {"claude-cli", "glm-cli"} or plan.acp is not None) and not state.saw_result:
            status = "error"
            error_text = f"{runner} exited without a terminal result; its output may be incomplete."
    if (
        status == "done"
        and not getattr(state, "emitted_text", False)
        and not str(getattr(state, "result_text", "") or "").strip()
    ):
        # The runtime swallowed a recoverable gateway failure (it may retry)
        # and then ended with no answer: the turn failed, and says why.
        from dodaios.agent_runtimes import gateway

        if swallowed := gateway.last_failure(plan.provider_failure):
            status, error_text = "error", swallowed
        elif plan.failure_probe is not None:
            # The runtime ended a failed run like a finished one (no HTTP
            # error ever reached the gateway): its own log says why.
            try:
                probed = await asyncio.to_thread(plan.failure_probe, started_at)
            except Exception:  # noqa: BLE001 — a probe never decides more than the reason
                log.debug("agent chat %s: failure probe failed", handle.turn_id, exc_info=True)
                probed = ""
            if probed:
                status, error_text = "error", probed

    usage = dict(state.usage)
    cost_usd = getattr(state, "cost_usd", None)
    vendor_session = state.vendor_session or vendor_session
    if (
        vendor_session is None
        and plan.discover is not None
        and status == "done"
        and placement is None  # the CLI's store lives on the remote machine
    ):
        # A CLI that never said which conversation it opened: ask its store.
        vendor_session = await asyncio.to_thread(plan.discover, cwd, started_at)
    result_text = str(getattr(state, "result_text", "") or "")
    plain_tail = "".join(plain)
    if not state.emitted_text and result_text.strip():
        await handle.emit(
            make_event(
                "assistant_text",
                {
                    "turn_id": handle.turn_id,
                    "message_id": f"result-{handle.turn_id}",
                    "text": result_text,
                },
            )
        )
    elif not state.emitted_text and plain_tail.strip():
        await handle.emit(
            make_event(
                "assistant_text",
                {
                    "turn_id": handle.turn_id,
                    "message_id": plain_id,
                    "text": plain_tail.strip(),
                },
            )
        )

    if plan.shape == "codex" and vendor_session:
        delivered = await _deliver_codex_images(handle, plan.env, vendor_session, started_at)
        if not delivered and status == "done":
            status = "error"
            error_text = "A generated image could not be added to the chat artifacts."

    signal = getattr(state, "limit", None)
    not_the_cli = {getattr(state, "last_tool_error", None), stderr_said} - {None, ""}
    return _Outcome(
        status,
        error_text,
        usage,
        cost_usd,
        vendor_session,
        signal if isinstance(signal, LimitSignal) and signal.hit else None,
        tool_error=bool(error_text)
        and (error_text in not_the_cli or error_text.startswith(_UNRESOLVED_TOOLS)),
    )


def _answer_settled(state: Any) -> bool:
    """The CLI gave its final answer, is idle and runs nothing in the background.

    Claude-shaped CLIs (Claude Code, Grok, GLM) keep ``answered``: their
    latest ``result`` with no task ended and no message started since. A
    task that ends after a result wakes Claude Code again, and its next
    answer is part of this turn. ACP runtimes know only their ``result``;
    the other shapes end with their process, as before.
    """
    answered = getattr(state, "answered", None)
    if answered is None:
        answered = getattr(state, "saw_result", False)
    if not answered or not getattr(state, "idle", True):
        return False
    # Background tasks of the CLI itself or of a sub-agent it started.
    return not _claude_outstanding(state)


async def _until_exit(proc: Any) -> None:
    """Until the process itself exited — not until its pipes closed.

    A pipe's EOF can wait on a grandchild that inherited it, for hours.
    """
    while proc.returncode is None:  # noqa: ASYNC110 — no awaitable for exit alone
        await asyncio.sleep(_EXIT_POLL_S)


async def _exited_within(proc: Any, limit_s: float) -> bool:
    try:
        await asyncio.wait_for(_until_exit(proc), limit_s)
    except TimeoutError:
        # Still running after the limit: the caller decides what happens next.
        return False
    return True


def _close_pipes(proc: Any) -> None:
    """Let go of an exited process's pipes a surviving grandchild still holds."""
    transport = getattr(proc, "_transport", None)
    if transport is None or proc.returncode is None:
        return
    with suppress(Exception):
        transport.close()


def _unread(proc: Any) -> int:
    """What already arrived on the process's pipes and no reader took yet."""
    total = 0
    for stream in (getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
        buffer = getattr(stream, "_buffer", None)
        if buffer is not None:
            total += len(buffer)
            continue
        queue = getattr(stream, "_queue", None)  # turn_host_client._LineStream
        if queue is not None:
            total += queue.qsize()
    return total


async def _pipes_went_quiet(
    readers: set[asyncio.Task[None]], lines_read: Callable[[], int], window_s: float
) -> bool:
    """Whether a whole wait window passed with no line read and nothing buffered.

    Counted, not clocked: an event loop that stalled past the window still
    finds the lines it had not read yet (the buffer check), so a stall never
    cuts a ``result`` that already arrived.
    """
    seen = lines_read()
    await asyncio.wait(readers, timeout=window_s)
    for _ in range(3):  # let completions that arrived during a stall run
        await asyncio.sleep(0)
    return lines_read() == seen


async def _natural_end(
    proc: Any,
    pump: asyncio.Task[None],
    drain: asyncio.Task[None],
    feeder: asyncio.Task[None],
    lines_read: Callable[[], int],
    handling: Callable[[], bool] = lambda: False,
) -> None:
    """The CLI's own end: it exited and its output was read.

    EOF is not process exit (a CLI may close both pipes and keep running),
    and process exit is not EOF (a grandchild may hold the pipes): wait for
    the exit, then read on while lines still come; stop after a whole
    ``_PIPE_DRAIN_S`` window with no line read, nothing left buffered and no
    line half handled (its ``result`` may be the one being translated).
    """
    await _until_exit(proc)
    while True:
        pending = {t for t in (pump, drain, feeder) if not t.done()}
        if not pending:
            return
        quiet = await _pipes_went_quiet(pending, lines_read, _PIPE_DRAIN_S)
        if quiet and not _unread(proc) and not handling():
            return


async def _until_end_or_answer(
    natural: asyncio.Task[None], settled: asyncio.Event, state: Any
) -> bool:
    """Wait for the CLI's end, or for its answer with nothing left running.

    Returns True when the turn ends on its answer while the process may
    still be shutting down; False when the process ended by itself.
    """
    while True:
        answer = asyncio.ensure_future(settled.wait())
        try:
            done, _ = await asyncio.wait({natural, answer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            answer.cancel()
        if natural in done:
            natural.result()
            return False
        # The answer is in: most CLIs exit within a moment, keeping their
        # real exit code; one that takes longer is not waited for.
        finished, _ = await asyncio.wait({natural}, timeout=_RESULT_EXIT_GRACE_S)
        if finished:
            natural.result()
            return False
        if _answer_settled(state):
            return True

        # The agent woke or a task opened meanwhile: the turn goes on.


#: CLIs that answered and are still shutting down, by chat session. The
#: session's next turn waits for them, so two processes never write one
#: vendor session at once.
_LINGERING: dict[str, set[asyncio.Task[None]]] = {}

#: Set once the session's next turn waits: a lingering CLI then gets the
#: shorter silence limit (``_REAP_HURRY_S``).
_HURRY: dict[str, asyncio.Event] = {}


def _linger(session_id: str, work: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    hurry = _HURRY.setdefault(session_id, asyncio.Event())
    task = asyncio.ensure_future(work(hurry))
    tasks = _LINGERING.setdefault(session_id, set())
    tasks.add(task)

    def _done(t: asyncio.Task[None]) -> None:
        tasks.discard(t)
        if not tasks and _LINGERING.get(session_id) is tasks:
            _LINGERING.pop(session_id, None)
            _HURRY.pop(session_id, None)

    task.add_done_callback(_done)


async def _await_lingering(session_id: str, cancel: asyncio.Event | None = None) -> bool:
    """The previous turn's CLI, if it is still shutting down, ends first.

    False when Stop was pressed meanwhile: the new turn then never starts.
    """
    tasks = list(_LINGERING.get(session_id, ()))
    if not tasks:
        return not (cancel is not None and cancel.is_set())
    hurry = _HURRY.get(session_id)
    if hurry is not None:
        hurry.set()
    waiting = asyncio.ensure_future(
        asyncio.gather(*(asyncio.shield(t) for t in tasks), return_exceptions=True)
    )
    stop = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    try:
        await asyncio.wait(
            {waiting, *([stop] if stop else [])}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        waiting.cancel()
        if stop is not None:
            stop.cancel()
    return not (cancel is not None and cancel.is_set())


async def _reap_after_answer(
    hurry: asyncio.Event,
    proc: Any,
    turn_id: str,
    runner: str,
    hosted: bool,
    cleanup: Callable[[], None],
) -> None:
    """A CLI whose turn already ended on its answer: let it finish, or kill it.

    Its pipes are read on (a full pipe would block it), and it is killed only
    after it printed nothing for ``_REAP_GRACE_S`` (``_REAP_HURRY_S`` once
    the next turn waits): post-answer work such as a SessionEnd hook or a
    session-file flush runs to its end.
    """
    lines = [0]

    async def _read(stream: Any) -> None:
        if stream is None:
            return
        while True:
            try:
                raw = await stream.readline()
            except ValueError:
                # An over-long line is dropped; it still counts as output read.
                lines[0] += 1
                continue
            except Exception:  # noqa: BLE001 — a closed pipe ends the reader
                return
            if not raw:
                return
            lines[0] += 1

    readers = [asyncio.ensure_future(_read(proc.stdout)), asyncio.ensure_future(_read(proc.stderr))]
    exit_task = asyncio.ensure_future(_until_exit(proc))
    try:
        while not exit_task.done():
            if getattr(proc, "handed_over", False) or getattr(proc, "detached", False):
                return  # another app process owns it now
            limit = _REAP_HURRY_S if hurry.is_set() else _REAP_GRACE_S
            seen = lines[0]
            waits: set[asyncio.Future[Any]] = {exit_task}
            hurried = None if hurry.is_set() else asyncio.ensure_future(hurry.wait())
            if hurried is not None:
                waits.add(hurried)
            try:
                await asyncio.wait(waits, timeout=limit, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if hurried is not None:
                    hurried.cancel()
            if exit_task.done() or (hurried is not None and hurried.done()):
                continue
            if lines[0] != seen or _unread(proc):
                continue  # it still works
            if getattr(proc, "handed_over", False) or getattr(proc, "detached", False):
                return
            log.info(
                "agent chat %s: %s printed nothing for %.0f s after its answer; stopping it",
                turn_id,
                runner,
                limit,
            )
            _kill(proc)
            if not await _exited_within(proc, _KILL_WAIT_S):
                log.warning("agent chat %s: %s did not exit after kill", turn_id, runner)
            break
    finally:
        exit_task.cancel()
        for reader in readers:
            reader.cancel()
        await asyncio.gather(exit_task, *readers, return_exceptions=True)
        handed = getattr(proc, "handed_over", False) or getattr(proc, "detached", False)
        try:
            if not handed:
                cleanup()
        finally:
            _close_pipes(proc)
            if hosted and not handed:
                with suppress(Exception):
                    proc.release()


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if isinstance(proc, asyncio.subprocess.Process):
        # A local CLI: its wrapper (node codex.js, claude.cmd) keeps the real
        # agent in a child that a plain kill would leave working after Stop.
        from dodaios.core.process_tree import kill_with_descendants

        kill_with_descendants(proc)
        return
    # A hosted or remote CLI: its own host ends the tree.
    try:
        proc.kill()
    except (ProcessLookupError, OSError) as exc:
        log.debug("agent chat: killing the CLI failed: %s", exc)
