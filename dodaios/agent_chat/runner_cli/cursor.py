"""Cursor agent planning and stream translator."""

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
    CliPlan,
    CliUnavailable,
    _argv_prompt,
    _cli_tool_summary,
    _identity_message,
)


def cursor_argv_prefix() -> list[str]:
    from dodaios.workspace.cursor_cli import resolve_cursor_binary

    binary = resolve_cursor_binary()
    if not binary:
        raise CliUnavailable("Cursor CLI (agent) is not installed or not on PATH.")
    return [binary]


def plan_cursor(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    """Cursor CLI print mode: one prompt in, stream-json events out.

    ``-p`` / ``--print`` is the non-interactive path (scripts, CI, this chat).
    ``--force`` is what actually applies edits — without it print mode only
    proposes. Ask and Plan are ``--mode`` flags and do not take ``--force``,
    because those stances are supposed to leave the tree alone.
    """
    del cwd, effort  # cwd is the spawn cwd; Cursor has no effort flag.
    mode = normalize_permission("cursor-cli", permission_mode)
    prompt = _identity_message("cursor-cli", prompt, identity, resume)
    argv = [
        *_rc.cursor_argv_prefix(),
        "-p",
        "--output-format",
        "stream-json",
    ]
    if model:
        argv += ["--model", model]
    if mode == "plan":
        argv += ["--mode", "plan"]
    elif mode == "ask":
        argv += ["--mode", "ask"]
    else:
        argv += ["--force"]
    if resume:
        argv += ["--resume", resume]
    argv.append(_argv_prompt(argv, prompt))
    env = _rc._registry_env("cursor", _rc._account_env("cursor"))
    return CliPlan(argv, env, None, "cursor", resume)


# ---------------------------------------------------------- cursor translation


@dataclass(slots=True)
class _CursorState:
    """Cursor CLI ``--output-format stream-json`` print-mode stream."""

    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    emitted_text: bool = False
    result_text: str = ""
    tool_calls: set[str] = field(default_factory=set)
    started_at: dict[str, float] = field(default_factory=dict)


def _cursor_message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and str(block.get("type") or "") == "text":
            text = str(block.get("text") or "")
            if text:
                parts.append(text)
    return "".join(parts)


def _cursor_tool_payload(tool_call: Any) -> tuple[str, dict[str, Any], Any]:
    """Name, args, and the inner payload of one Cursor ``tool_call`` object."""
    if not isinstance(tool_call, dict):
        return "tool", {}, {}
    for key, payload in tool_call.items():
        if not isinstance(payload, dict):
            continue
        if key.endswith("ToolCall"):
            name = key[: -len("ToolCall")] or "tool"
            args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
            return name, args, payload
        if key == "function":
            raw_args = payload.get("arguments")
            args: dict[str, Any]
            if isinstance(raw_args, dict):
                args = raw_args
            elif isinstance(raw_args, str):
                try:
                    parsed = json.loads(raw_args)
                except ValueError:
                    parsed = {"arguments": raw_args}
                args = parsed if isinstance(parsed, dict) else {"arguments": parsed}
            else:
                args = {}
            return str(payload.get("name") or "tool"), args, payload
    return "tool", {}, {}


def _cursor_tool_output(payload: dict[str, Any]) -> tuple[str, bool]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return "", False
    if "success" in result:
        success = result.get("success")
        if isinstance(success, dict):
            for key in ("content", "path"):
                val = success.get(key)
                if isinstance(val, str) and val.strip():
                    return val, False
            return json.dumps(success, ensure_ascii=False), False
        return str(success or "done"), False
    if "error" in result or "failure" in result:
        err = result.get("error") or result.get("failure")
        return str(err or "failed"), True
    return json.dumps(result, ensure_ascii=False), False


def translate_cursor_line(obj: dict[str, Any], st: _CursorState) -> list[dict[str, Any]]:
    """One Cursor print-mode stream-json object -> agent-chat events.

    Shape (Cursor docs, ``--output-format stream-json``): ``system`` init,
    ``assistant`` messages (complete between tool calls), ``tool_call``
    started/completed, terminal ``result``. Session id rides on every line.
    """
    out: list[dict[str, Any]] = []
    kind = str(obj.get("type") or "")
    sid = obj.get("session_id")
    if sid and not st.vendor_session:
        st.vendor_session = str(sid)

    if kind in {"system", "user"}:
        return out

    if kind == "assistant":
        # Partial-output duplicates: a pre-tool flush carries ``model_call_id``
        # and a final flush has no ``timestamp_ms``. Complete messages (the
        # default without ``--stream-partial-output``) have neither extra
        # field and are the ones we keep.
        if "model_call_id" in obj:
            return out
        if "timestamp_ms" in obj:
            return out
        text = _cursor_message_text(obj.get("message"))
        if not text.strip():
            return out
        st.emitted_text = True
        st.result_text = text
        st.status, st.error = "done", None
        mid = str(sid or uuid.uuid4().hex)
        out.append(
            make_event(
                "assistant_text",
                {"turn_id": st.turn_id, "message_id": mid, "text": text},
            )
        )
        return out

    if kind == "tool_call":
        call_id = str(obj.get("call_id") or uuid.uuid4().hex)
        name, args, payload = _cursor_tool_payload(obj.get("tool_call"))
        subtype = str(obj.get("subtype") or "")
        if subtype == "started" or (subtype != "completed" and call_id not in st.tool_calls):
            if call_id not in st.tool_calls:
                st.tool_calls.add(call_id)
                st.started_at[call_id] = time.perf_counter()
                out.append(
                    make_event(
                        "tool_call",
                        {
                            "turn_id": st.turn_id,
                            "call_id": call_id,
                            "name": name,
                            "input": args,
                            "summary": _cli_tool_summary(name, args)
                            or str(args.get("path") or "")[:200],
                        },
                    )
                )
        if subtype == "completed":
            output, is_error = _cursor_tool_output(payload if isinstance(payload, dict) else {})
            started = st.started_at.get(call_id)
            duration_ms = int((time.perf_counter() - started) * 1000) if started else None
            out.append(
                make_event(
                    "tool_result",
                    {
                        "turn_id": st.turn_id,
                        "call_id": call_id,
                        "output": output or ("failed" if is_error else "done"),
                        "is_error": is_error,
                        "duration_ms": duration_ms,
                    },
                )
            )
        return out

    if kind == "result":
        if sid:
            st.vendor_session = str(sid)
        is_error = bool(obj.get("is_error")) or str(obj.get("subtype") or "") != "success"
        result = str(obj.get("result") or "")
        if result.strip():
            st.result_text = result
            if not st.emitted_text:
                st.emitted_text = True
                out.append(
                    make_event(
                        "assistant_text",
                        {
                            "turn_id": st.turn_id,
                            "message_id": str(sid or uuid.uuid4().hex),
                            "text": result,
                        },
                    )
                )
        if is_error:
            st.status = "error"
            st.error = result or "Cursor CLI reported an error"
        else:
            st.status, st.error = "done", None
        return out

    return out
