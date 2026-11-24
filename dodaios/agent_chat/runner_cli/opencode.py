"""OpenCode planning, model catalog and stream translator."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.cli_catalog import catalog_key
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.permissions import (
    normalize_permission,
)
from dodaios.agent_chat.runner_cli import base as _rc_base
from dodaios.agent_chat.runner_cli.base import (
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _argv_prompt,
    _behind_shim,
    _catalog_cwd,
    _cli_tool_summary,
    _identity_message,
    log,
)
from dodaios.agent_chat.runner_cli.claude_stream import _content_text
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS


def opencode_argv_prefix() -> list[str]:
    binary = _rc_base._which(*CLI_BINARIES["opencode-cli"])
    if not binary:
        raise CliUnavailable("OpenCode (opencode) is not installed or not on PATH.")
    return _behind_shim(binary, "opencode")


_OPENCODE_CATALOG: dict[str, Any] = {"at": 0.0, "rows": None}

_OPENCODE_CATALOG_TTL_S: Final[float] = 600.0


def read_opencode_models(timeout_s: float = 20.0) -> list[dict[str, Any]]:
    """``opencode models`` -> the ids this install can run (cached 10 min).

    OpenCode's ids are ``provider/model`` and the list is whatever providers
    the person configured — nothing to curate, only to ask. The label is the
    model half and the note the provider, so ``anthropic/claude-opus-5`` and
    ``cloudflare-ai-gateway/anthropic/claude-opus-5`` read apart in the picker.
    Blocking (a ~2 s subprocess) — call it off the event loop. Any failure
    yields an empty list, and the cache keeps a failure out of the next
    request for the TTL too.
    """
    import subprocess

    env = _rc_base._registry_env("opencode", _rc_base._account_env("opencode"))
    prefix = opencode_argv_prefix()
    cwd = _catalog_cwd()
    key = catalog_key(prefix, env, cwd)
    now = time.monotonic()
    if (
        _OPENCODE_CATALOG.get("key") == key
        and _OPENCODE_CATALOG["rows"] is not None
        and now - _OPENCODE_CATALOG["at"] < _OPENCODE_CATALOG_TTL_S
    ):
        return list(_OPENCODE_CATALOG["rows"])
    rows: list[dict[str, Any]] = []
    try:
        argv = [*prefix, "models"]
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            capture_output=True,
            timeout=timeout_s,
            env=env,
            cwd=str(cwd),
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            mid = line.strip()
            if not mid or "/" not in mid or " " in mid:
                continue
            provider, _, model = mid.partition("/")
            rows.append({"id": mid, "label": model, "note": provider})
    except (CliUnavailable, OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("agent chat: opencode models unavailable: %s", exc)
    _OPENCODE_CATALOG.update(rows=rows, at=now, key=key)
    return list(rows)


def plan_opencode(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    mode = normalize_permission("opencode-cli", permission_mode)
    # The prompt is a positional of ``run`` (no stdin mode), behind ``--`` so
    # a sentence that starts with a dash is a sentence and not a flag; the
    # identity rides in front of it on a fresh conversation.
    prompt = _identity_message("opencode-cli", prompt, identity, resume)
    argv = [*opencode_argv_prefix(), "run", "--format", "json", "--thinking"]
    if mode == "auto":
        argv += ["--auto"]
    elif mode == "plan":
        # OpenCode's own plan agent: read-only by its definition.
        argv += ["--agent", "plan"]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--variant", effort]
    if resume:
        argv += ["--session", resume]
    argv += ["--", _argv_prompt(argv, prompt)]
    env = _rc_base._registry_env("opencode", _rc_base._account_env("opencode"))
    return CliPlan(argv, env, None, "opencode", resume)


# ------------------------------------------------------ opencode translation


@dataclass(slots=True)
class _OpenCodeState:
    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float | None = None
    emitted_text: bool = False
    result_text: str = ""
    #: callIDs already announced as tool rows
    tool_calls: set[str] = field(default_factory=set)
    started_at: dict[str, float] = field(default_factory=dict)


#: ``step_finish.part.tokens`` -> the usage keys the timeline sums. OpenCode
#: follows the OpenAI convention: ``input`` INCLUDES the cache read.
_OPENCODE_TOKEN_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("reasoning", "reasoning_output_tokens"),
)


def _part_duration_ms(part: dict[str, Any]) -> int | None:
    span = part.get("time")
    if not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    if isinstance(start, int | float) and isinstance(end, int | float) and end >= start:
        return int(end - start)
    return None


def translate_opencode_line(obj: dict[str, Any], st: _OpenCodeState) -> list[dict[str, Any]]:
    """One ``opencode run --format json`` object -> agent-chat events.

    Shape (opencode 1.18.23): ``{"type", "timestamp", "sessionID", "part"}``
    where ``type`` is ``step_start`` / ``text`` / ``reasoning`` / ``tool_use``
    / ``step_finish``, and ``part`` is the session record's part of that
    kind — a finished ``text`` part with its ``text``, a ``tool`` part with
    ``tool``, ``callID`` and ``state{status, input, output, title, time}``,
    a ``step-finish`` part with ``tokens{input, output, reasoning,
    cache{read, write}}`` and ``cost``. An ``error`` line carries
    ``error{name, data{message}}`` instead of a part.
    """
    out: list[dict[str, Any]] = []
    kind = str(obj.get("type") or "")
    sid = obj.get("sessionID")
    if sid and not st.vendor_session:
        st.vendor_session = str(sid)
    part = obj.get("part") if isinstance(obj.get("part"), dict) else {}

    if kind == "text":
        text = str(part.get("text") or "")
        mid = str(part.get("id") or part.get("messageID") or uuid.uuid4().hex)
        if text.strip():
            st.emitted_text = True
            st.result_text = text
            # An answer after a retryable error means the retry worked.
            st.status, st.error = "done", None
            out.append(
                make_event(
                    "assistant_text",
                    {"turn_id": st.turn_id, "message_id": mid, "text": text},
                )
            )
        return out

    if kind == "reasoning":
        text = str(part.get("text") or "")
        mid = str(part.get("id") or part.get("messageID") or uuid.uuid4().hex)
        if text.strip():
            out.append(
                make_event(
                    "reasoning",
                    {
                        "turn_id": st.turn_id,
                        "message_id": mid,
                        "text": text,
                        "duration_ms": _part_duration_ms(part),
                    },
                )
            )
        return out

    if kind == "tool_use":
        name = str(part.get("tool") or "tool")
        call_id = str(part.get("callID") or part.get("id") or uuid.uuid4().hex)
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        args = state.get("input") if isinstance(state.get("input"), dict) else {}
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
                        or str(state.get("title") or "")[:200],
                    },
                )
            )
        status = str(state.get("status") or "")
        if status in {"completed", "error"}:
            is_error = status == "error"
            output = _content_text(state.get("output"))
            err = state.get("error")
            if is_error and err:
                output = (output.rstrip() + ("\n" if output else "") + str(err)).strip()
            started = st.started_at.get(call_id)
            duration_ms = _part_duration_ms(state) or (
                int((time.perf_counter() - started) * 1000) if started else None
            )
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

    if kind == "step_finish":
        tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        for theirs, ours in _OPENCODE_TOKEN_KEYS:
            val = tokens.get(theirs)
            if isinstance(val, int | float):
                st.usage[ours] = st.usage.get(ours, 0) + int(val)
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        for theirs, ours in (
            ("read", "cached_input_tokens"),
            ("write", "cache_write_input_tokens"),
        ):
            val = cache.get(theirs)
            if isinstance(val, int | float):
                st.usage[ours] = st.usage.get(ours, 0) + int(val)
        cost = part.get("cost")
        if isinstance(cost, int | float):
            st.cost_usd = (st.cost_usd or 0.0) + float(cost)
        if str(part.get("reason") or "") == "stop":
            st.status, st.error = "done", None
        return out

    if kind == "error":
        err = obj.get("error") if isinstance(obj.get("error"), dict) else {}
        data = err.get("data") if isinstance(err.get("data"), dict) else {}
        message = data.get("message") or err.get("message") or err.get("name") or "error"
        # Terminal unless a later part shows the CLI retried and got through.
        st.status = "error"
        st.error = str(message)
        return out

    return out
