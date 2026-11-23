"""Grok Build planning, model catalog and background-task tracking."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.effort import (
    ORDER,
)
from dodaios.agent_chat.permissions import (
    normalize_permission,
)
from dodaios.agent_chat.runner_cli import base as _rc_base
from dodaios.agent_chat.runner_cli.base import (
    CLI_BINARIES,
    CliPlan,
    CliUnavailable,
    _argv_prompt,
    _resolved_cwd,
    _with_identity,
    log,
)
from dodaios.agent_chat.runner_cli.claude import identity_turn_flags
from dodaios.core.response_style import KEEP_GOING_ON_TOOL_FAILURE


def grok_argv_prefix() -> list[str]:
    binary = _rc_base._which(*CLI_BINARIES["grok-cli"])
    if not binary:
        raise CliUnavailable("Grok Build (grok) is not installed or not on PATH.")
    return [binary]


def plan_grok(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    effort: str,
    permission_mode: str,
    resume: str | None,
    identity: dodaios_harness.Identity | None = None,
) -> CliPlan:
    # Grok Build takes the prompt on argv, so the identity rides in front of
    # it — the compact cut, and only on a fresh conversation.
    prompt = _with_identity(prompt, identity, resume, compact=True)
    mode = normalize_permission("grok-cli", permission_mode)
    work = _resolved_cwd(cwd)
    if identity is not None:
        # grok has no --mcp-config; a project `.grok/config.toml` is how
        # print-mode actually sees Jarvis' tools (gmail, calendar, the rest).
        dodaios_harness.install_grok_jarvis_mcp(work, identity.session_id)
    argv = [
        *grok_argv_prefix(),
        "--no-auto-update",
        "--no-alt-screen",
        "--output-format",
        "streaming-messages-json",
        "--include-partial-messages",
        "--cwd",
        str(work),
    ]
    if mode == "plan":
        argv += ["--permission-mode", "plan"]
    else:
        # Print-mode grok cannot answer a permission prompt. default and
        # acceptEdits therefore decline MCP tools (live Morning Briefing,
        # 2026-09-17: jarvis__gmail "Tool not found" / cancelled) and abort
        # the whole turn (live Bot ersteller, 2026-09-17: run_terminal_command
        # "User cancelled"). Jarvis' gateway still gates every call.
        argv += ["--always-approve"]
    argv += ["--rules", KEEP_GOING_ON_TOOL_FAILURE]
    if identity is not None:
        argv += identity_turn_flags("grok-cli", identity)
    if model:
        argv += ["-m", model]
    if effort:
        argv += ["--reasoning-effort", effort]
    if resume:
        argv += ["-r", resume]
        sid = resume
    else:
        sid = str(uuid.uuid4())
        argv += ["--session-id", sid]
    argv += ["-p", _argv_prompt(argv, prompt)]
    env = dodaios_harness.apply_env(_rc_base._account_env("grok-build"))
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return CliPlan(argv, env, None, "claude", sid)


def read_grok_models() -> list[dict[str, Any]] | None:
    """Grok Build's account catalog from ``$GROK_HOME/models_cache.json``.

    The CLI refreshes that file itself. It is the same list the Grok Build
    picker shows for this login (verified against grok 1.0.40: a dict of
    model id to ``{info: {id, name, hidden, reasoning_efforts}}``). ``None``
    when the file is missing or unreadable — the caller keeps
    ``GROK_BUILD_MODELS``.
    """
    env = _rc_base._account_env("grok-build")
    home = Path(env.get("GROK_HOME") or Path.home() / ".grok")
    path = home / "models_cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.debug("agent chat: grok models cache unreadable at %s: %s", path, exc)
        return None
    models = data.get("models") if isinstance(data, dict) else None
    if isinstance(models, dict):
        entries = list(models.values())
    elif isinstance(models, list):
        entries = models
    else:
        return None
    rows: list[dict[str, Any]] = []
    for entry in entries:
        info = entry.get("info") if isinstance(entry, dict) else None
        if not isinstance(info, dict):
            info = entry if isinstance(entry, dict) else None
        if not isinstance(info, dict) or info.get("hidden") is True:
            continue
        slug = str(info.get("id") or info.get("model") or "").strip()
        if not slug:
            continue
        seen: list[str] = []
        for level in info.get("reasoning_efforts") or []:
            if isinstance(level, dict):
                value = str(level.get("value") or level.get("id") or "")
            else:
                value = str(level)
            value = value.strip().lower()
            if value and value not in seen:
                seen.append(value)
        ordered = [level for level in ORDER if level in seen]
        ordered += [level for level in seen if level not in ordered]
        # "" stays the "leave the CLI's own effort alone" choice. The levels
        # after it are the ones this model actually accepts.
        efforts = [""] + ordered if ordered else []
        row: dict[str, Any] = {
            "id": slug,
            "label": str(info.get("name") or slug),
            "efforts": efforts,
        }
        note = str(info.get("description") or "").strip()
        if note:
            row["note"] = note
        rows.append(row)
    return rows or None
