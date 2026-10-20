"""Plan a society turn on an external agent runtime (Hermes, OpenClaw).

The CLI runner (``runner_cli``) owns the process for every CLI seat — spawn,
containment, cancellation, rollover, resume-lost retries, approvals — and
these runtimes are just one more seat to it. This module answers the part
that differs: which agent the chat belongs to, which model route and Jarvis
tools that agent gets, and which process to start (from the runtime's
driver in ``dodaios.agent_runtimes``). The turn itself is driven over ACP by
``dodaios.agent_runtimes.acp.AcpTurn``, handed to the runner on the plan.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from dodaios.agent_runtimes import RUNNER_RUNTIMES, driver, gateway
from dodaios.agent_runtimes.acp import AcpTurn
from dodaios.agent_runtimes.base import RuntimeTurn, RuntimeUnavailable
from dodaios.agent_runtimes.model_map import RouteUnavailable, prepare_route

log = logging.getLogger(__name__)

#: Native tools must honor the same capability selection as the MCP surface.
_NATIVE_GROUPS: dict[str, str] = {"core:shell": "shell", "core:browser": "web"}


def supports_runner(runner: str) -> bool:
    return runner in RUNNER_RUNTIMES


def _agent_id(session_id: str) -> str:
    parts = session_id.split(":", 2)
    return parts[1] if len(parts) > 1 and parts[0] == "society" else ""


async def _agent(agent_id: str) -> Any:
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    if runtime is None or not agent_id:
        return None
    return await runtime.roster.get(agent_id)


def _config() -> Any:
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    cfg = runtime.config() if runtime is not None else None
    if cfg is not None:
        return cfg
    from dodaios.core.config import load_config

    return load_config()


#: ``supported_parameters`` a catalog lists for a model that reasons.
_REASONING_PARAMETERS: frozenset[str] = frozenset(
    {"reasoning", "include_reasoning", "reasoning_effort"}
)


def model_capabilities(provider: str, model: str) -> tuple[bool | None, bool | None]:
    """``(reasons, reads_images)`` as the model catalog DECLARES them.

    ``None`` = the catalog says nothing (no cached entry, or a provider whose
    feed carries no such field): the runtime keeps its own default. Never a
    provider- or model-name rule (AP-21). Blocking (catalog cache file).
    """
    from dodaios.brain.model_catalog import ModelCatalog

    try:
        info = ModelCatalog().cached_model(provider, model)
    except Exception as exc:  # noqa: BLE001 — an unreadable cache means "unknown"
        log.debug("agent runtimes: catalog entry of %s/%s unreadable: %s", provider, model, exc)
        return None, None
    if info is None:
        return None, None
    params = info.supported_parameters
    inputs = info.input_modalities
    reasons = bool(_REASONING_PARAMETERS & set(params)) if params is not None else None
    vision = ("image" in inputs) if inputs is not None else None
    return reasons, vision


def _denied_native(agent: Any, plan_mode: bool) -> frozenset[str]:
    grants = set(agent.grants or [])
    denies = set(agent.denies or [])
    denied = {
        group
        for cap, group in _NATIVE_GROUPS.items()
        if cap in denies or (str(agent.grant_mode) == "allowlist" and cap not in grants)
    }
    if plan_mode:
        denied.add("shell")
    return frozenset(denied)


async def _ready(handle: Any, runtime_name: str, runtime: Any) -> None:
    """Install or update the runtime first when it cannot run this turn.

    Nobody sets Hermes or OpenClaw up by hand: the first turn on a fresh
    machine (or after a failed update) waits for the official installer and
    says so in the chat. A runtime that still is not ready ends the turn
    with the reason.
    """
    from dodaios.agent_chat.events import make_event
    from dodaios.agent_chat.runner_cli import CliUnavailable
    from dodaios.agent_runtimes import manager

    current = manager.job(runtime_name)
    setting_up = current is not None and current.state == "running"
    status = await asyncio.to_thread(runtime.detect, fast=True)
    if not setting_up and manager.needed(runtime, status) is None:
        return
    await handle.emit(
        make_event(
            "notice",
            {
                "kind": "runtime_setup",
                "runtime": runtime_name,
                "turn_id": handle.turn_id,
                "text": f"Setting up {runtime.label} for this agent. The first time takes "
                "a few minutes; the message is sent as soon as it is ready.",
            },
        )
    )
    status = await manager.wait_ready(runtime_name)
    if not status.ready:
        reason = manager.failure_reason(runtime_name) or status.problem
        raise CliUnavailable(f"{runtime.label} could not be set up. {reason}".strip())


async def _runtime_turn(
    session: Any,
    agent: Any,
    *,
    cwd: Path,
    resume: str | None,
    tools: bool,
    warm: bool,
) -> RuntimeTurn:
    """The runtime's view of one turn; raises ``RouteUnavailable``."""
    from dodaios.agent_chat import dodaios_harness
    from dodaios.agent_chat.effort import normalize_effort

    route = await prepare_route(
        _config(), session.provider, session.model,
        agent_id=agent.agent_id,
        account_id=getattr(session, "account_id", "") or "",
        session_id=session.session_id,
    )
    plan_mode = session.permission_mode in ("plan", "read-only")
    reasoning, vision = await asyncio.to_thread(model_capabilities, route.provider, route.model)
    return RuntimeTurn(
        agent_id=agent.agent_id,
        agent_name=agent.name,
        session_id=session.session_id,
        workspace=cwd,
        route=route,
        resume=resume,
        auto_approve=session.permission_mode == "bypass",
        mcp_url=dodaios_harness.endpoint() if tools else None,
        control_key=dodaios_harness.control_key() if tools else None,
        denied_native=_denied_native(agent, plan_mode),
        effort=normalize_effort(session.provider, getattr(session, "effort", "") or ""),
        reasoning=reasoning,
        vision=vision,
        warm=warm,
    )


async def warm_session(session: Any, store: Any | None = None) -> bool:
    """Get an agent's runtime ready before its next message (chat opened, typing).

    Starts the agent's process (OpenClaw: its Gateway too) and opens the
    conversation, so the message that follows only costs the model call.
    No paid model call is made. ``False`` = nothing to warm (not a runtime
    agent, not set up, a turn running, another computer). ``store`` re-reads
    the chat's conversation id once the agent's slot is held.
    """
    from dodaios.agent_chat.runner_cli import _resolved_cwd

    runtime_name = str(getattr(session, "runtime", "") or "")
    agent_id = _agent_id(str(getattr(session, "session_id", "") or ""))
    if runtime_name not in RUNNER_RUNTIMES.values() or not agent_id:
        return False
    from dodaios.society.remote import placement_for_session

    if await placement_for_session(session) is not None:
        return False  # its process runs on the other computer, per turn
    agent = await _agent(agent_id)
    if agent is None:
        return False
    runtime = driver(runtime_name)
    warm = getattr(runtime, "warm", None)
    if warm is None:
        return False
    try:
        turn = await _runtime_turn(
            session, agent,
            cwd=_resolved_cwd(session.cwd or Path.home()),
            resume=session.vendor_session or None,
            tools=True,
            warm=True,
        )
        def latest_resume() -> str | None:
            fresh = store.get_session(session.session_id) if store is not None else None
            row = fresh if fresh is not None else session
            return str(getattr(row, "vendor_session", "") or "") or None

        return bool(await warm(turn, latest_resume))
    except (RouteUnavailable, RuntimeUnavailable) as exc:
        log.info("agent runtimes: %s not warmed: %s", runtime_name, exc)
        return False


async def plan_runtime_turn(
    handle: Any,
    runner: str,
    *,
    prompt: str,
    cwd: Path,
    resume: str | None,
    identity: Any | None,
) -> Any:
    """The ``CliPlan`` for one turn on ``runner``; raises ``CliUnavailable``."""
    from dodaios import __version__
    from dodaios.agent_chat.runner_cli import (
        _REMOTE_PLANNING,
        CliUnavailable,
    )

    session = handle.session
    runtime_name = RUNNER_RUNTIMES[runner]
    agent_id = _agent_id(session.session_id)
    agent = await _agent(agent_id)
    if agent is None:
        raise CliUnavailable(f"{runtime_name.title()} runs society agents only.")
    plan_mode = session.permission_mode in ("plan", "read-only")
    runtime = driver(runtime_name)
    # The route (catalog facts, maybe a network read) and the runtime's
    # readiness check are independent: neither waits for the other.
    turn_task = asyncio.ensure_future(
        _runtime_turn(
            session, agent,
            cwd=cwd,
            resume=resume,
            tools=not getattr(handle, "tools_disabled", False),
            # A turn placed on another computer starts its process there.
            warm=not _REMOTE_PLANNING.get(),
        )
    )
    try:
        await _ready(handle, runtime_name, runtime)
    except BaseException:
        turn_task.cancel()
        raise
    try:
        turn = await turn_task
    except RouteUnavailable as exc:
        raise CliUnavailable(str(exc)) from exc
    route = turn.route
    try:
        launch = await runtime.launch(turn)
    except RuntimeUnavailable as exc:
        raise CliUnavailable(str(exc)) from exc

    def release_launch() -> None:
        lease = launch.proc
        if lease is not None and not lease.finished:
            # Planning ended before the turn ran: the process stays warm.
            lease.finish()
        if launch.release is not None:
            launch.release()

    try:
        failure = gateway.watch_failure(route.api_key or "", effort=session.effort or "")
    except BaseException:
        release_launch()
        raise

    def release() -> None:
        gateway.unwatch_failure(route.api_key or "", failure)
        acp = plan.acp if plan is not None else None
        if launch.invalidate is not None and (
            handle.cancel.is_set()
            or (failure.done() and not failure.cancelled())
            or acp is None
            or not acp.saw_result
            or acp.status != "done"
        ):
            launch.invalidate()
        release_launch()

    plan: Any = None
    try:
        plan = _plan(
            handle, launch, turn, failure, release,
            prompt=prompt, plan_mode=plan_mode, identity=identity, resume=resume,
            client_version=__version__,
        )
        return plan
    except BaseException:
        # Never a warm process left leased (and the slot held) by a plan
        # that was not handed to the runner.
        release()
        raise


def _plan(
    handle: Any,
    launch: Any,
    turn: RuntimeTurn,
    failure: Any,
    release: Any,
    *,
    prompt: str,
    plan_mode: bool,
    identity: Any | None,
    resume: str | None,
    client_version: str,
) -> Any:
    from dodaios.agent_chat.runner_cli import _PLAN_PREAMBLE, CliPlan, _with_identity

    text = _PLAN_PREAMBLE + prompt if plan_mode else prompt
    acp = AcpTurn(
        turn_id=handle.turn_id,
        cwd=str(launch.cwd),
        prompt_text=_with_identity(text, identity, resume),
        resume=launch.acp_resume,
        mcp_servers=launch.mcp_servers,
        auto_allow=turn.auto_approve,
        auto_deny=plan_mode,
        client_version=client_version,
        report_session=launch.vendor_session,
        session_meta=launch.session_meta,
        prompt_meta=launch.prompt_meta,
    )
    if launch.proc is not None:
        # The agent's warm process: initialized, maybe with the session open.
        acp.initialized = launch.proc.initialized
        acp.open_session = launch.proc.open_session
        launch.proc.turn = acp
    return CliPlan(
        argv=launch.argv,
        env=launch.env,
        stdin_text=None,
        shape="acp",
        vendor_session=None,
        keep_stdin=True,
        acp=acp,
        after_turn=release,
        provider_failure=failure,
        proc=launch.proc,
    )
