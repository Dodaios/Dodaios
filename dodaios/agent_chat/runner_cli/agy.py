"""Antigravity planning, model catalog and stream translator."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat import runner_cli as _rc
from dodaios.agent_chat.cli_catalog import catalog_key
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.permissions import (
    normalize_permission,
)
from dodaios.agent_chat.runner_cli.base import (
    _PREPARED_MODELS,
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _catalog_cwd,
    _identity_message,
    _remember_models,
    _resolved_cwd,
    log,
)
from dodaios.agent_chat.runner_cli.claude_stream import _content_text
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

#: agy's print mode stops itself after 5 min unless told otherwise.
_AGY_PRINT_TIMEOUT: Final[str] = f"{365 * 24 * 3600}s"


def agy_argv_prefix() -> list[str]:
    try:
        from dodaios.google_cli.resolver import resolve_google_cli

        cli = resolve_google_cli()
    except Exception:  # noqa: BLE001 — fall back to PATH below
        cli = None
    if cli is not None and cli.kind == "agy":
        return list(cli.argv_prefix)
    binary = _rc._which(*CLI_BINARIES["agy-cli"])
    if not binary:
        raise CliUnavailable("Antigravity CLI (agy) is not installed or not on PATH.")
    return [binary]


#: agy's own model ids as of 1.1.19, for a box where ``agy models`` cannot be
#: read (the live list is account-dependent and wins whenever it answers).
AGY_FALLBACK_MODELS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("gemini-4-hydrogen", "Gemini 4 Hydrogen", ("low", "medium", "high")),
    ("gemini-4-hydrogen-xhigh", "Gemini 4 Hydrogen (XHigh)", ()),
    ("gemini-3.8-flash", "Gemini 3.8 Flash", ("low", "medium", "high")),
    ("gemini-3.7-flash", "Gemini 3.7 Flash", ("low", "medium", "high")),
    ("gemini-3.6-flash", "Gemini 3.6 Flash", ("low", "medium", "high")),
    ("gemini-3.5-flash", "Gemini 3.5 Flash", ("low", "medium", "high")),
    ("gemini-3.1-pro", "Gemini 3.1 Pro", ("low", "high")),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)", ()),
    ("claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)", ()),
    ("gpt-oss-120b", "GPT-OSS 120B", ("medium",)),
)


_AGY_EFFORT_SUFFIXES: Final[tuple[str, ...]] = ("low", "medium", "high")


def agy_model_catalog(raw_models: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Fold agy's suffixed ids into base models with an effort ladder each.

    ``agy models`` lists ``gemini-3.5-flash-low`` / ``-medium`` / ``-high``
    as three ids; the composer shows ONE model with a three-step effort
    pick, so this folds ``<base>-<effort>`` onto ``<base>`` and records the
    efforts seen. Ids without a suffix (the Claude models, ``gpt-oss-120b``)
    keep an empty ladder = no effort pick. ``None`` (no list readable) gives
    the fallback table.
    """
    if not raw_models:
        return [
            {"id": mid, "label": label, "efforts": list(efforts)}
            for mid, label, efforts in AGY_FALLBACK_MODELS
        ]
    order: list[str] = []
    efforts: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for m in raw_models:
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        label = str(m.get("label") or mid)
        base, suffix = mid, ""
        for sfx in _AGY_EFFORT_SUFFIXES:
            if mid.endswith("-" + sfx):
                base, suffix = mid[: -(len(sfx) + 1)], sfx
                break
        if base not in efforts:
            efforts[base] = []
            order.append(base)
            labels[base] = _strip_effort_label(label) if suffix else label
        if suffix and suffix not in efforts[base]:
            efforts[base].append(suffix)
    return [
        {
            "id": base,
            "label": labels[base],
            "efforts": sorted(efforts[base], key=_AGY_EFFORT_SUFFIXES.index),
        }
        for base in order
    ]


def _strip_effort_label(label: str) -> str:
    # "Gemini 3.5 Flash (High)" -> "Gemini 3.5 Flash"
    for sfx in ("(Low)", "(Medium)", "(High)"):
        if label.endswith(sfx):
            return label[: -len(sfx)].rstrip()
    return label


def _agy_catalog_is_live() -> bool:
    """The cached catalog is what ``agy models`` answered, not the fallback table."""
    return bool(_rc._AGY_CATALOG.get("live")) and _rc._agy_catalog_cached() is not None


def agy_model_args(
    model: str,
    effort: str,
    catalog: list[dict[str, Any]] | None = None,
    *,
    live: bool = False,
) -> list[str]:
    """The ``--model`` / ``--effort`` pair agy accepts for a base id + effort.

    agy is strict: a base Gemini id REQUIRES ``--effort`` (and only the levels
    that model has — Pro knows low/high), a suffixed id FORBIDS it, and the
    Claude / GPT-OSS ids take none at all. The catalog says which is which;
    without one the fallback table does.
    """
    rows = catalog or agy_model_catalog(None)
    by_id = {r["id"]: r for r in rows}
    if live and catalog and model and model not in by_id:
        # The installed agy listed its models and this one is not among them (a
        # saved choice from the curated list, e.g. ``gemini-3.1-pro``): agy
        # would refuse it, so it runs its own default model instead.
        log.warning("agent chat: agy has no model %r; using its default", model)
        model = ""
    if not model:
        # Default model: agy accepts ``--effort`` alone.
        return ["--effort", effort] if effort in _AGY_EFFORT_SUFFIXES else []
    row = by_id.get(model)
    if (row is None or not row.get("efforts")) and _is_base_gemini_id(model):
        # A newer Gemini base id still requires --effort when discovery failed
        # or returned a bare id without its suffixed variants.
        level = effort if effort in _AGY_EFFORT_SUFFIXES else _AGY_DEFAULT_EFFORT
        return ["--model", model, "--effort", level]
    if row is None:
        # A suffixed or non-Gemini unknown id: pass it through untouched.
        return ["--model", model]
    ladder = list(row.get("efforts") or [])
    if not ladder:
        return ["--model", model]
    if ladder == ["medium"] and model.startswith("gpt-oss"):
        # gpt-oss-120b: the bare id runs; ``-medium`` is the only suffix.
        return ["--model", model]
    level = effort if effort in ladder else _nearest_lower(effort, ladder)
    return ["--model", model, "--effort", level]


#: The level a base Gemini id newer than the catalog runs at when nobody chose
#: one: every Gemini ladder agy publishes has it (Pro knows only low/high).
_AGY_DEFAULT_EFFORT: Final = "high"


def _is_base_gemini_id(model: str) -> bool:
    """``gemini-3.8-flash`` yes; ``gemini-3.8-flash-high`` and ``claude-…`` no."""
    return model.startswith("gemini-") and not model.endswith(
        tuple(f"-{level}" for level in _AGY_EFFORT_SUFFIXES)
    )


def _nearest_lower(effort: str, ladder: list[str]) -> str:
    order = list(_AGY_EFFORT_SUFFIXES)
    if effort not in order:
        return ladder[-1] if "high" in ladder else ladder[0]
    idx = order.index(effort)
    lower = [lvl for lvl in ladder if order.index(lvl) <= idx]
    return lower[-1] if lower else ladder[0]


def plan_agy(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    mode = normalize_permission("agy-cli", permission_mode)
    # agy has no system-prompt flag: the identity rides in front of the prompt
    # on stdin, on a fresh conversation (a resumed one already knows).
    prompt = _identity_message("agy-cli", prompt, identity, resume)
    work = _resolved_cwd(cwd)
    if identity is not None:
        # agy has no --mcp-config; a workspace plugin is how print-mode
        # actually sees Jarvis' tools (gmail, linear, the rest of the gateway).
        dodaios_harness.install_agy_jarvis_plugin(work, identity.session_id)
    argv = [
        *_rc.agy_argv_prefix(),
        "--output-format",
        "stream-json",
        "--add-dir",
        str(work),
        # agy's own print timeout is 5 min; a turn here has no limit.
        "--print-timeout",
        _AGY_PRINT_TIMEOUT,
    ]
    if mode == "plan":
        argv += ["--mode", "plan"]
    else:
        # Print-mode agy 1.1.26: a tool that still wants a confirmation is
        # soft-denied and the process exits. ``accept-edits`` still asks for
        # RunCommand, so without this flag the turn dies after the first
        # shell call (live 2026-09-04, society:test / society:gamil-agent).
        argv += ["--dangerously-skip-permissions"]
        if mode == "accept-edits":
            argv += ["--mode", "accept-edits"]
    argv += agy_model_args(model, effort, _rc._agy_catalog_cached(), live=_agy_catalog_is_live())
    if resume:
        argv += ["--conversation", resume]
    env = dodaios_harness.apply_env(_rc._account_env("antigravity"))
    env.setdefault("AGY_CLI_HIDE_LOGO", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Prompt on stdin: no argv length limit, and no ``-p`` that could swallow
    # the next flag as its value.
    return CliPlan(argv, env, prompt, "agy", resume)


_AGY_CATALOG: dict[str, Any] = {"at": 0.0, "rows": None}

_AGY_CATALOG_TTL_S: Final[float] = 600.0


def _agy_catalog_cached() -> list[dict[str, Any]] | None:
    prepared = _PREPARED_MODELS.get()
    if prepared is not None and "agy-cli" in prepared:
        return prepared["agy-cli"]
    key = catalog_key(_rc.agy_argv_prefix(), _rc._account_env("antigravity"), _catalog_cwd())
    rows = _rc._AGY_CATALOG.get("rows") if _rc._AGY_CATALOG.get("key") == key else None
    return rows if isinstance(rows, list) else None


def agy_probe_cwd() -> Path:
    """An empty, app-owned folder the ``agy models`` probe runs in.

    agy boots every MCP server of its global ``mcp_config.json`` even for
    ``models``, through ``cmd.exe`` on Windows. A server argument like
    ``pkg@>=0.26.0`` reaches cmd unquoted and its ``>`` redirects into an
    empty file named ``0.26.0`` in the probe's folder. Run in an agent's
    workspace (or the home folder) that left a stray file in every fresh
    agent; this scratch folder keeps it out of anything the person reads.
    """
    from dodaios.core.private_tmp import private_temp_folder

    try:
        return private_temp_folder("dodaios-agy-probe")
    except OSError:
        return _catalog_cwd()


def read_agy_models(timeout_s: float = 8.0, *, required_model: str = "") -> list[dict[str, Any]]:
    """``agy --output-format json models`` -> the folded catalog (cached 10 min).

    Blocking (a ~2 s subprocess) — call it off the event loop. Any failure
    yields the fallback table; the cache keeps a failure out of the next
    request for the TTL too.
    """
    import subprocess

    env = _rc._account_env("antigravity")
    argv = _rc.agy_argv_prefix()
    cwd = _catalog_cwd()
    key = catalog_key(argv, env, cwd)
    now = time.monotonic()
    cached = _rc._agy_catalog_cached()
    model_known = not required_model or any(row["id"] == required_model for row in cached or [])
    if cached is not None and model_known and now - _rc._AGY_CATALOG["at"] < _AGY_CATALOG_TTL_S:
        _remember_models("agy-cli", cached)
        return list(cached)
    raw: list[dict[str, Any]] | None = None
    try:
        argv = [*argv, "--output-format", "json", "models"]
        env.setdefault("AGY_CLI_HIDE_LOGO", "1")
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            argv,
            capture_output=True,
            timeout=timeout_s,
            env=env,
            # Never the workspace: see agy_probe_cwd.
            cwd=str(agy_probe_cwd()),
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            obj = json.loads(line)
            data = ((obj.get("command") or {}).get("data") or {}) if isinstance(obj, dict) else {}
            models = data.get("models") if isinstance(data, dict) else None
            if isinstance(models, list):
                raw = [m for m in models if isinstance(m, dict)]
                break
    except (CliUnavailable, OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("agent chat: agy models unavailable: %s", exc)
    rows = agy_model_catalog(raw)
    _rc._AGY_CATALOG.update(rows=rows, at=now, key=key, live=raw is not None)
    _remember_models("agy-cli", rows)
    return list(rows)


# ------------------------------------------------------------ agy translation


@dataclass(slots=True)
class _AgyState:
    turn_id: str
    vendor_session: str | None = None
    status: str = "done"
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    emitted_text: bool = False
    result_text: str = ""
    #: step_index -> wall-clock start, for tool durations
    started_at: dict[int, float] = field(default_factory=dict)
    #: step_index of tool steps already announced
    tool_steps: set[int] = field(default_factory=set)
    #: text per agent_response step (a DONE step repeats its last delta)
    text_acc: dict[int, str] = field(default_factory=dict)


_AGY_TOOL_SUMMARY_KEYS: Final[tuple[str, ...]] = (
    "CommandLine",
    "AbsolutePath",
    "TargetFile",
    "Pattern",
    "SearchDirectory",
    "DirectoryPath",
    "Query",
    "Url",
)


def _agy_summary(params: Any) -> str:
    if not isinstance(params, dict):
        return ""
    for key in _AGY_TOOL_SUMMARY_KEYS:
        val = params.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().splitlines()[0][:200]
    first = next((v for v in params.values() if isinstance(v, str) and v.strip()), "")
    return first.splitlines()[0][:200] if first else ""


def translate_agy_line(obj: dict[str, Any], st: _AgyState) -> list[dict[str, Any]]:
    """One ``agy --output-format stream-json`` object -> agent-chat events.

    Shape (agy 1.1.19): ``{"event": "init" | "step_update" | "result", ...}``.
    A ``step_update`` carries ``step_index``, ``state`` (ACTIVE / DONE /
    ERROR / ...), ``step_type`` (``agent_response`` with ``text_delta``;
    ``tool`` with ``tool_name`` + ``tool_info{name, parameters, output?,
    error?}``) and, on DONE, ``duration_seconds`` + ``usage``. The final
    ``result`` carries ``status`` (SUCCESS / ERROR / CANCELED / ...),
    ``response``, ``error`` and the conversation id.
    """
    out: list[dict[str, Any]] = []
    kind = str(obj.get("event") or "")
    if kind == "init":
        cid = obj.get("conversation_id")
        if cid:
            st.vendor_session = str(cid)
        return out

    if kind == "step_update":
        su = obj.get("step_update") or {}
        if not isinstance(su, dict):
            return out
        cid = su.get("conversation_id")
        if cid and not st.vendor_session:
            st.vendor_session = str(cid)
        try:
            idx = int(su.get("step_index") or 0)
        except (TypeError, ValueError):
            idx = 0
        state = str(su.get("state") or "")
        stype = str(su.get("step_type") or "")

        if stype == "agent_response":
            delta = str(su.get("text_delta") or "")
            if delta:
                acc = st.text_acc.get(idx, "")
                # The DONE step repeats the last delta — do not double it.
                if state == "DONE" and acc.endswith(delta):
                    delta = ""
            if delta:
                st.text_acc[idx] = st.text_acc.get(idx, "") + delta
                st.emitted_text = True
                out.append(
                    make_event(
                        "text_delta",
                        {"turn_id": st.turn_id, "message_id": f"agy-{idx}", "text": delta},
                    )
                )
            if state in {"DONE", "ERROR"} and st.text_acc.get(idx, "").strip():
                out.append(
                    make_event(
                        "assistant_text",
                        {
                            "turn_id": st.turn_id,
                            "message_id": f"agy-{idx}",
                            "text": st.text_acc[idx],
                        },
                    )
                )
            return out

        if stype == "tool":
            info = su.get("tool_info") if isinstance(su.get("tool_info"), dict) else {}
            name = str(su.get("tool_name") or info.get("name") or "tool")
            params = info.get("parameters") if isinstance(info, dict) else None
            call_id = f"agy-step-{idx}"
            if idx not in st.tool_steps:
                st.tool_steps.add(idx)
                st.started_at[idx] = time.perf_counter()
                out.append(
                    make_event(
                        "tool_call",
                        {
                            "turn_id": st.turn_id,
                            "call_id": call_id,
                            "name": name,
                            "input": params if isinstance(params, dict) else {"input": params},
                            "summary": _agy_summary(params),
                        },
                    )
                )
            if state in {"DONE", "ERROR", "CANCELED", "INVALID", "HALTED"}:
                err = info.get("error") if isinstance(info, dict) else None
                err_text = (
                    str(err.get("message") or err) if isinstance(err, dict) else str(err or "")
                )
                output = _content_text(info.get("output")) if isinstance(info, dict) else ""
                is_error = state != "DONE" or bool(err_text)
                if is_error and err_text:
                    output = (output.rstrip() + ("\n" if output else "") + err_text).strip()
                dur = su.get("duration_seconds")
                started = st.started_at.get(idx)
                duration_ms = (
                    int(float(dur) * 1000)
                    if isinstance(dur, int | float)
                    else int((time.perf_counter() - started) * 1000)
                    if started
                    else None
                )
                out.append(
                    make_event(
                        "tool_result",
                        {
                            "turn_id": st.turn_id,
                            "call_id": call_id,
                            "output": output or ("done" if not is_error else "failed"),
                            "is_error": is_error,
                            "duration_ms": duration_ms,
                        },
                    )
                )
            return out
        return out

    if kind == "result":
        res = obj.get("result") if isinstance(obj.get("result"), dict) else obj
        cid = res.get("conversation_id")
        if cid:
            st.vendor_session = str(cid)
        status = str(res.get("status") or "SUCCESS").upper()
        st.result_text = str(res.get("response") or "")
        usage = res.get("usage") or {}
        if isinstance(usage, dict):
            for k in (
                "input_tokens",
                "output_tokens",
                "thinking_tokens",
                "cache_read_tokens",
                "total_tokens",
            ):
                if isinstance(usage.get(k), int | float):
                    st.usage[k] = int(usage[k])
        if status == "SUCCESS":
            st.status = "done"
        elif status in {"CANCELED", "INTERRUPTED"}:
            st.status = "error"
            st.error = str(res.get("error") or f"agy stopped the turn ({status.lower()})")
        else:
            st.status = "error"
            st.error = str(res.get("error") or f"agy reported {status}")
        return out
    return out


def _agy_model_ladder(model: str) -> list[str] | None:
    """agy's effort levels for ``model`` from the cached catalog (``None`` = unknown)."""
    try:
        rows = _rc._agy_catalog_cached()
    except CliUnavailable:  # agy is missing: the planner reports that right after this
        return None
    for row in rows or []:
        if row.get("id") == model and "efforts" in row:
            return list(row["efforts"])
    return None


def _agy_effective_effort(model: str, effort: str) -> str:
    """The ``--effort`` value agy is launched with for ``model`` + ``effort``."""
    try:
        rows = _rc._agy_catalog_cached()
    except CliUnavailable:  # agy is missing: the planner reports that right after this
        rows = None
    args = agy_model_args(model, effort, rows)
    return args[args.index("--effort") + 1] if "--effort" in args else ""
