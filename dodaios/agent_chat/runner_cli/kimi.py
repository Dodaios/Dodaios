"""Kimi planning and stream translator."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat import runner_cli as _rc
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.permissions import (
    normalize_permission,
)
from dodaios.agent_chat.runner_cli.base import (
    _PLAN_PREAMBLE,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _argv_prompt,
    _behind_shim,
    _cli_tool_summary,
    _identity_message,
    log,
)
from dodaios.agent_chat.runner_cli.claude_stream import _content_text


def kimi_argv_prefix() -> list[str]:
    binary = _rc._which(*CLI_BINARIES["kimi-cli"])
    if not binary:
        raise CliUnavailable("Kimi Code (kimi) is not installed or not on PATH.")
    return _behind_shim(binary, "kimi")


def _kimi_session_after(cwd: Path, started_at: float) -> str | None:
    """The session Kimi's print run in ``cwd`` created after ``started_at``.

    Kimi's stream names no session; its store does. The same search a pane
    runs for its own conversation — the newest session under this folder's
    bucket, created after the start, with content — through
    ``agent_sessions.discover``, so the two never disagree about where Kimi
    keeps a conversation.
    """
    try:
        from dodaios.agentic_ide import agent_sessions

        handle = agent_sessions.discover("kimi", str(cwd), started_at)
    except Exception as exc:  # noqa: BLE001 — a lost id costs one resume, not the turn
        log.debug("agent chat: kimi session discovery failed: %s", exc)
        return None
    return handle.id if handle is not None else None


def plan_kimi(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    mode = normalize_permission("kimi-cli", permission_mode)
    prompt = _identity_message("kimi-cli", prompt, identity, resume)
    argv = [*_rc.kimi_argv_prefix(), "--output-format", "stream-json"]
    if model:
        argv += ["--model", model]
    # Print mode is autonomous by Kimi's own design (a headless run has nobody
    # to ask), and Kimi Code refuses ``--auto``, ``--yolo`` and ``--plan`` next
    # to ``--prompt`` ("Cannot combine --prompt with --auto", 0.29). Plan is
    # therefore an instruction, not a sandbox — the ladder's sentence says so.
    if resume:
        # Long form on purpose: the two Kimi generations disagree on the short
        # flag (``agent_sessions``).
        argv += ["--session", resume]
    text = _PLAN_PREAMBLE + prompt if mode == "plan" else prompt
    argv += ["--prompt", _argv_prompt(argv, text)]
    env = _rc._registry_env("kimi", _rc._account_env("kimi"))
    return CliPlan(
        argv, env, None, "kimi", resume, discover=None if resume else _kimi_session_after
    )


# ---------------------------------------------------------- kimi translation


@dataclass(slots=True)
class _KimiState:
    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    emitted_text: bool = False
    result_text: str = ""
    #: assistant lines seen — each is one message on the timeline
    messages: int = 0
    started_at: dict[str, float] = field(default_factory=dict)


def _kimi_arguments(raw: Any) -> dict[str, Any]:
    """The call's arguments as a dict — Kimi writes them as a JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"arguments": raw}
        return parsed if isinstance(parsed, dict) else {"arguments": parsed}
    return {}


def translate_kimi_line(obj: dict[str, Any], st: _KimiState) -> list[dict[str, Any]]:
    """One ``kimi --output-format stream-json`` object -> agent-chat events.

    Shape (kimi-code 0.29.2, ``PromptJsonWriter``): chat messages by
    ``role``. ``assistant`` carries ``content`` (the step's whole text) and
    ``tool_calls`` — OpenAI's function-call shape, ``function.arguments`` a
    JSON string; ``tool`` carries ``tool_call_id`` and ``content``; ``meta``
    lines (``turn.step.retrying``) and a goal's ``goal.summary`` are noise.
    """
    out: list[dict[str, Any]] = []
    role = str(obj.get("role") or "")

    if role == "assistant":
        st.messages += 1
        mid = f"kimi-{st.messages}"
        raw_content = obj.get("content")
        content = _content_text(raw_content) if isinstance(raw_content, list) else raw_content
        if isinstance(content, str) and content.strip():
            st.emitted_text = True
            st.result_text = content
            out.append(
                make_event(
                    "assistant_text",
                    {"turn_id": st.turn_id, "message_id": mid, "text": content},
                )
            )
        calls = obj.get("tool_calls") if isinstance(obj.get("tool_calls"), list) else []
        for call in calls:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(fn.get("name") or "tool")
            args = _kimi_arguments(fn.get("arguments"))
            call_id = str(call.get("id") or uuid.uuid4().hex)
            st.started_at[call_id] = time.perf_counter()
            out.append(
                make_event(
                    "tool_call",
                    {
                        "turn_id": st.turn_id,
                        "call_id": call_id,
                        "name": name,
                        "input": args,
                        "summary": _cli_tool_summary(name, args),
                    },
                )
            )
        return out

    if role == "tool":
        call_id = str(obj.get("tool_call_id") or "")
        content = obj.get("content")
        output = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        started = st.started_at.get(call_id)
        out.append(
            make_event(
                "tool_result",
                {
                    "turn_id": st.turn_id,
                    "call_id": call_id,
                    "output": output,
                    # Kimi's record does not say; a failure reads in the text.
                    "is_error": False,
                    "duration_ms": int((time.perf_counter() - started) * 1000) if started else None,
                },
            )
        )
        return out

    return out
