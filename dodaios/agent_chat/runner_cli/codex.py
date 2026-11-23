"""Codex planning, model catalog, stream translator and image delivery."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.cli_catalog import CatalogCache, catalog_key, discover_codex_models
from dodaios.agent_chat.effort import (
    snap_to_ladder,
)
from dodaios.agent_chat.events import make_event, plan_steps, plan_update_events
from dodaios.agent_chat.model_fallback import (
    LimitSignal,
    limit_from_codex_error,
)
from dodaios.agent_chat.permissions import (
    normalize_permission,
)
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.runner_cli import base as _rc_base
from dodaios.agent_chat.runner_cli.base import (
    _PLAN_PREAMBLE,
    _PREPARED_MODELS,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _catalog_cwd,
    _remember_models,
    _with_identity,
    log,
)
from dodaios.agent_chat.runner_cli.claude_stream import subagent_status


def codex_argv_prefix() -> list[str]:
    try:
        from dodaios.missions.workers.codex_direct_worker import _resolve_codex_argv_prefix

        prefix = _resolve_codex_argv_prefix()
    except Exception:  # noqa: BLE001 — the worker helper is a convenience, not a contract
        prefix = []
    if prefix:
        return list(prefix)
    binary = _rc_base._which(*CLI_BINARIES["codex-cli"])
    if not binary:
        raise CliUnavailable("Codex CLI (codex) is not installed or not on PATH.")
    return [binary]


_CODEX_CATALOG = CatalogCache()


def read_codex_models(*, required_model: str = "") -> list[dict[str, Any]] | None:
    """Ask the installed CLI, never trust another client's models_cache.json.

    Config-isolation flags belong to ``codex exec`` and are not accepted by
    ``codex app-server``. Discovery only reads model/list; it starts no turn.
    """
    env = _rc_base._account_env("codex")
    argv = codex_argv_prefix()
    cwd = _catalog_cwd()
    rows = _CODEX_CATALOG.read(
        catalog_key(argv, env, cwd),
        lambda: discover_codex_models(argv, env, cwd),
        required_model=required_model,
    )
    _remember_models("codex-cli", rows)
    return rows


def plan_codex(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    mode = normalize_permission("codex-cli", permission_mode)
    # Codex reads the prompt from stdin, which has no length limit: the
    # identity rides in front of it on a fresh conversation. (Its
    # ``model_instructions_file`` REPLACES the CLI's own instructions rather
    # than adding to them, so it is not used here.)
    prompt = _with_identity(prompt, identity, resume)
    base = codex_argv_prefix()
    if resume:
        argv = [*base, "exec", "resume", resume, "--json"]
    else:
        argv = [*base, "exec", "--json", "--cd", str(cwd)]
    argv += ["--skip-git-repo-check"]
    # Jarvis' own tools over streamable-HTTP MCP, mounted for this run only —
    # the person's ~/.codex/config.toml is never touched.
    argv += dodaios_harness.codex_config_args(identity.session_id if identity else None)
    if identity is not None:
        # A Jarvis seat must use the browser and connections visible in Jarvis.
        # Inheriting the coding CLI's plugins gives it a second, unrelated
        # browser whose actions never appear in the agent's live viewer.
        argv += ["--ignore-user-config", "--ignore-rules"]
        for feature in ("browser_use", "plugins", "computer_use", "apps", "web_search_request"):
            argv += ["--disable", feature]
        # The vendor's own web search is off too: results come from the Dodaios web tools.
        argv += ["-c", 'web_search="disabled"']
    # The TUI's presets, spelled out for ``exec`` (codex 0.149): Read only /
    # Auto (workspace-write) / Full access (``--yolo``), plus "approve for
    # me" — Codex's own reviewer model decides what would have asked you,
    # the one ask-stance a headless run has. ``exec`` never prompts on
    # stdin; the sandbox decides what may happen. Plan is the read-only
    # sandbox plus an instruction to plan instead of act. The sandbox goes
    # through ``-c sandbox_mode`` because ``exec resume`` has no ``-s``.
    society_seat = identity is not None and identity.session_id.startswith("society:")
    if society_seat:
        # The headless CLI cannot relay native approval prompts into Jarvis.
        # Give it only the app-owned MCP hands; all actions then pass through
        # the session grant, ToolExecutor and the visible chat approval card.
        argv += ["-c", 'sandbox_mode="read-only"', "-c", 'approval_policy="never"']
        for feature in (
            "shell_tool",
            "apps",
            "hooks",
            "multi_agent",
            "browser_use",
            "computer_use",
            "plugins",
            "web_search_request",
        ):
            argv += ["--disable", feature]
    elif mode == "full-access":
        argv += ["--dangerously-bypass-approvals-and-sandbox"]
    elif mode == "approve-for-me":
        argv += [
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            'approvals_reviewer="auto_review"',
            "-c",
            'approval_policy="on-request"',
        ]
    else:
        sandbox = "workspace-write" if mode == "auto" else "read-only"
        argv += ["-c", f'sandbox_mode="{sandbox}"']
    if model:
        # The account's catalog says which levels THIS model takes (5.5 stops
        # at xhigh, terra goes to ultra); an unsupported level is snapped
        # rather than sent for the server to reject.
        prepared = _PREPARED_MODELS.get()
        models = (
            prepared.get("codex-cli")
            if prepared is not None and "codex-cli" in prepared
            else read_codex_models()
        )
        for row in models or []:
            if row.get("id") == model and "efforts" in row:
                effort = snap_to_ladder(effort, list(row["efforts"]))
                break
    if effort:
        argv += ["-c", f"model_reasoning_effort={effort}"]
    # Without a summary setting no ``reasoning`` items appear at all.
    argv += ["-c", "model_reasoning_summary=auto"]
    if model:
        argv += ["--model", model]
    argv += ["-"]  # prompt on stdin
    text = _PLAN_PREAMBLE + prompt if mode == "plan" else prompt
    return CliPlan(
        argv, dodaios_harness.apply_env(_rc_base._account_env("codex")), text, "codex", resume
    )


@dataclass(slots=True)
class _CodexState:
    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    emitted_text: bool = False
    #: item id -> (call_id, name) for items that became tool calls
    items: dict[str, tuple[str, str]] = field(default_factory=dict)
    started_at: dict[str, float] = field(default_factory=dict)
    #: The last top-level ``error`` notification (retryable until turn.failed).
    last_error: str | None = None
    failed_tools: set[str] = field(default_factory=set)
    #: What the stream said about a usage / rate limit (``model_fallback``).
    limit: LimitSignal = field(default_factory=LimitSignal)
    #: A sub-agent's thread id -> the ``spawn_agent`` call that started it.
    agents: dict[str, str] = field(default_factory=dict)
    #: Sub-agents whose end was already told, so a later ``close_agent`` that
    #: reports them shut down does not turn a finished agent into a stopped one.
    agents_ended: set[str] = field(default_factory=set)
    #: The agent's to-do list as it was last told, and how often it was told.
    plan: list[dict[str, str]] = field(default_factory=list)
    plan_calls: int = 0
    #: This run's tag (:func:`run_tag`). Codex numbers its items from
    #: ``item_0`` in every process, so a turn it ran twice (after a limit, a
    #: recovery) reused the first run's ids, and the chat kept the first
    #: run's to-do list, messages and tool rows instead of the second's.
    run: str = ""
    #: The output of the last tool call that failed: never the turn's own
    #: words about a limit (``_Outcome.tool_error``).
    last_tool_error: str | None = None


def _codex_item_id(st: _CodexState, item: dict[str, Any]) -> str:
    raw = str(item.get("id") or uuid.uuid4().hex)
    return f"{raw}-{st.run}" if st.run else raw


#: Codex's word for a sub-agent that is still working.
_CODEX_AGENT_LIVE: Final = frozenset({"pending_init", "running"})


def _codex_collab_events(item: dict[str, Any], phase: str, st: _CodexState) -> list[dict[str, Any]]:
    """Codex's multi-agent calls (``collab_tool_call``) as sub-agent cards.

    ``spawn_agent`` becomes the card's call; the agent's thread id is
    remembered, so every later call that reports ``agents_states`` (``wait``,
    ``send_input``, ``close_agent``) updates that card. ``codex exec`` does not
    stream a sub-agent's own steps — the card carries its task and its answer.
    """
    out: list[dict[str, Any]] = []
    item_id = _codex_item_id(st, item)
    tool = str(item.get("tool") or "agent")
    prompt = str(item.get("prompt") or "")
    receivers = [str(t) for t in item.get("receiver_thread_ids") or [] if t]
    states = item.get("agents_states") if isinstance(item.get("agents_states"), dict) else {}
    if item_id not in st.items:
        st.items[item_id] = (item_id, tool)
        st.started_at[item_id] = time.perf_counter()
        summary = prompt.strip().splitlines()[0][:200] if prompt.strip() else ""
        args: dict[str, Any] = {"prompt": prompt} if prompt else {}
        if tool != "spawn_agent" and receivers:
            args["agents"] = receivers
        out.append(
            make_event(
                "tool_call",
                {
                    "turn_id": st.turn_id,
                    "call_id": item_id,
                    "name": tool,
                    "input": args,
                    "summary": summary,
                },
            )
        )
    if tool == "spawn_agent":
        for thread_id in receivers:
            if thread_id in st.agents:
                continue
            st.agents[thread_id] = item_id
            out.append(
                make_event(
                    "subagent_started",
                    {
                        "turn_id": st.turn_id,
                        "agent_id": item_id,
                        "thread_id": thread_id,
                        "description": prompt.strip().splitlines()[0][:120] if prompt else "",
                        "agent_type": "",
                        "prompt": prompt,
                        "background": True,
                    },
                )
            )
    for thread_id, raw in states.items():
        agent_id = st.agents.get(str(thread_id))
        state = raw if isinstance(raw, dict) else {}
        status = str(state.get("status") or "")
        if not agent_id or not status or status in _CODEX_AGENT_LIVE:
            continue
        if status in {"shutdown", "not_found"} and agent_id in st.agents_ended:
            continue
        st.agents_ended.add(agent_id)
        out.append(
            make_event(
                "subagent_finished",
                {
                    "turn_id": st.turn_id,
                    "agent_id": agent_id,
                    "status": subagent_status(status),
                    "summary": str(state.get("message") or ""),
                },
            )
        )
    if phase == "completed":
        started = st.started_at.get(item_id)
        failed = str(item.get("status") or "") == "failed"
        out.append(
            make_event(
                "tool_result",
                {
                    "turn_id": st.turn_id,
                    "call_id": item_id,
                    "output": ", ".join(receivers) if tool == "spawn_agent" else "done",
                    "is_error": failed,
                    "duration_ms": int((time.perf_counter() - started) * 1000) if started else None,
                },
            )
        )
    return out


def translate_codex_line(obj: dict[str, Any], st: _CodexState) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    kind = str(obj.get("type") or "")
    if kind == "thread.started":
        tid = obj.get("thread_id")
        if tid:
            st.vendor_session = str(tid)
        return out
    if kind == "turn.completed":
        usage = obj.get("usage") or {}
        if isinstance(usage, dict):
            for k in (
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "reasoning_output_tokens",
            ):
                if isinstance(usage.get(k), int | float):
                    st.usage[k] = int(usage[k])
        # A completed turn wins over a retryable error seen on the way.
        st.status = "done"
        st.error = None
        return out
    if kind == "turn.failed":
        st.status = "error"
        err = obj.get("error")
        limit_from_codex_error(st.limit, err)
        st.error = (
            str(err.get("message") or err)
            if isinstance(err, dict)
            else str(err or st.last_error or "turn failed")
        )
        return out
    if kind == "error":
        # A server notification — may be retried by the CLI; remembered, and
        # only terminal when no turn.completed follows (exit code decides).
        st.last_error = str(obj.get("message") or "error")
        limit_from_codex_error(st.limit, obj)
        return out
    if not kind.startswith("item."):
        return out

    item = obj.get("item") or {}
    item_id = _codex_item_id(st, item)
    itype = str(item.get("type") or "")
    phase = kind.split(".", 1)[1]  # started | updated | completed

    if itype == "agent_message":
        text = str(item.get("text") or "")
        if phase == "completed" and text.strip():
            st.emitted_text = True
            out.append(
                make_event(
                    "assistant_text",
                    {"turn_id": st.turn_id, "message_id": item_id, "text": text},
                )
            )
        return out
    if itype == "reasoning":
        text = str(item.get("text") or "")
        if phase == "started":
            out.append(
                make_event(
                    "reasoning_started",
                    {"turn_id": st.turn_id, "message_id": item_id},
                )
            )
            return out
        if phase == "completed" and text.strip():
            out.append(
                make_event(
                    "reasoning",
                    {
                        "turn_id": st.turn_id,
                        "message_id": item_id,
                        "text": text,
                        "duration_ms": None,
                    },
                )
            )
        return out
    if itype == "collab_tool_call":
        return _codex_collab_events(item, phase, st)
    if itype == "todo_list":
        # Codex's plan (its ``update_plan`` tool) is ONE item: started with the
        # first list, updated on every change, completed with the turn. Each
        # change is told as a list call of its own; the closing repeat is not.
        steps = plan_steps(item.get("items"))
        if not steps or steps == st.plan:
            return out
        st.plan = steps
        st.plan_calls += 1
        run = f"{st.run}-" if st.run else ""
        return plan_update_events(st.turn_id, f"plan-{st.turn_id}-{run}{st.plan_calls}", steps)
    if itype in {"command_execution", "file_change", "mcp_tool_call", "web_search"}:
        if itype == "command_execution":
            name, args = "RunCommand", {"command": str(item.get("command") or "")}
            summary = args["command"].splitlines()[0][:200] if args["command"] else ""
        elif itype == "file_change":
            changes = item.get("changes") or []
            paths = [str(c.get("path") or "") for c in changes if isinstance(c, dict)]
            name, args = "Edit", {"changes": changes}
            summary = ", ".join(p for p in paths if p)[:200]
        elif itype == "mcp_tool_call":
            name = str(item.get("tool") or item.get("server") or "mcp")
            args = item.get("arguments") or {}
            summary = str(item.get("server") or "")
        else:
            name, args = "WebSearch", {"query": str(item.get("query") or "")}
            summary = args["query"]
        if item_id not in st.items:
            st.items[item_id] = (item_id, name)
            st.started_at[item_id] = time.perf_counter()
            out.append(
                make_event(
                    "tool_call",
                    {
                        "turn_id": st.turn_id,
                        "call_id": item_id,
                        "name": name,
                        "input": args if isinstance(args, dict) else {"input": args},
                        "summary": summary,
                    },
                )
            )
        if phase == "completed":
            if itype == "command_execution":
                output = str(item.get("aggregated_output") or "")
                code = item.get("exit_code")
                if code is not None:
                    output = (output.rstrip() + f"\n[exit {code}]").strip()
                item_status = str(item.get("status") or "")
                is_error = bool(code) or item_status in {"failed", "declined"}
                if item_status == "declined":
                    output = (output.rstrip() + "\n[declined by the sandbox / policy]").strip()
            elif itype == "file_change":
                output = "\n".join(
                    f"{c.get('kind', 'edit')}: {c.get('path', '')}"
                    for c in (item.get("changes") or [])
                    if isinstance(c, dict)
                )
                is_error = str(item.get("status") or "") == "failed"
            elif itype == "mcp_tool_call":
                result = item.get("result")
                output = json.dumps(result or item.get("error") or {}, ensure_ascii=False)
                is_error = (
                    bool(item.get("error"))
                    or str(item.get("status") or "") == "failed"
                    or (isinstance(result, dict) and bool(result.get("isError")))
                )
                if is_error:
                    st.failed_tools.add(name)
                    st.last_error = st.last_tool_error = f"{name} failed: {output[:300]}"
                else:
                    st.failed_tools.discard(name)
            else:
                output = "done"
                is_error = False
            started = st.started_at.get(item_id)
            out.append(
                make_event(
                    "tool_result",
                    {
                        "turn_id": st.turn_id,
                        "call_id": item_id,
                        "output": output,
                        "is_error": is_error,
                        "duration_ms": int((time.perf_counter() - started) * 1000)
                        if started
                        else None,
                    },
                )
            )
        return out
    if itype == "error":
        # NOT a failed turn: Codex files warnings here (skills budget, hook
        # clamps, model reroutes) in every run. Remembered for the error text
        # should the turn fail without a message of its own.
        st.last_error = str(item.get("message") or "error")
    return out


#: Codex features a task turn must not reach: only the Dodaios gateway's tools.
_CODEX_TASK_DISABLED: Final[tuple[str, ...]] = (
    "shell_tool",
    "apps",
    "hooks",
    "multi_agent",
    "browser_use",
    "web_search_request",
    "goals",
    "memories",
    "plugins",
    "computer_use",
    "image_generation",
    "multi_agent_v2",
)


def isolate_task_tools(argv: list[str], runner: str) -> None:
    """Leave a task turn only the Dodaios gateway's tools (``gateway_only``), in place.

    An identity turn already carries some of codex's flags, and codex refuses
    a flag given twice, so each goes in once.
    """
    if runner == "claude-cli":
        argv += ["--tools", ""]
        if "--strict-mcp-config" not in argv:
            argv.append("--strict-mcp-config")
        return
    if runner != "codex-cli":
        raise CliUnavailable("The selected runner cannot isolate task tools.")
    for flag in ("--ignore-user-config", "--ignore-rules"):
        if flag not in argv:
            argv.append(flag)
    disabled = {argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--disable"}
    for feature in _CODEX_TASK_DISABLED:
        if feature not in disabled:
            argv += ["--disable", feature]


async def _deliver_codex_images(
    handle: TurnHandle, env: dict[str, str], thread_id: str, since: float
) -> bool:
    """Recover native visual results omitted by the CLI's text event stream."""
    from dodaios.agent_chat.generated_images import collect_generated_images
    from dodaios.core.paths import repo_root
    from dodaios.missions.isolation.worktree import resolve_outputs_root

    raw_home = env.get("CODEX_HOME", "")
    home = Path(raw_home) if raw_home else Path.home() / ".codex"
    try:
        images = await asyncio.to_thread(
            collect_generated_images,
            codex_home=home,
            thread_id=thread_id,
            since=since,
            outputs_root=resolve_outputs_root(repo_root()),
        )
    except (OSError, ValueError):
        log.warning("agent chat: generated image delivery failed", exc_info=True)
        await handle.emit(
            make_event(
                "error",
                {
                    "turn_id": handle.turn_id,
                    "message": "A generated image could not be added to the chat artifacts.",
                },
            )
        )
        return False
    for image in images:
        await handle.emit(
            make_event(
                "assistant_text",
                {
                    "turn_id": handle.turn_id,
                    "message_id": image.message_id,
                    "text": image.markdown,
                },
            )
        )
    return True
