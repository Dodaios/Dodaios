"""The first_move world of an installation's night: what replays the lead's turns tonight.

Built once at the start of a night (:func:`build`) and dropped at its end, so
the night's :class:`~dodaios.rsi.budget.Budget` is one per night. It is built
only when everything a replay needs is there and paid for the right way:

* a recorded lead turn: the newest one names the lead's CLI, model and effort
  and its chat, whose tool list the replay offers;
* the lead runs on Claude Code (``lead_cli.RUNNERS``); other CLIs have no
  replay yet;
* the CLI is signed in to its plan and no API key reaches it (it would bill
  that key per token instead), and the plan is not cooling down after a limit;
* the app's tool list can be read (the replay offers it, ``replay_tools``).

Without any of these there is no world, the first_move tasks wait, and nothing
is spent. The night's report says why (``reason``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.rsi.budget import FIRST_MOVE_CALLS, Budget, Usage

from .lead_cli import RUNNERS, ClaudeReplay
from .lead_replay import FirstMoveWorld, Platform

__all__ = ["Built", "build"]

log = logging.getLogger(__name__)

#: Environment variables that make Claude Code bill a key instead of the plan.
_KEY_VARS: Final[tuple[str, ...]] = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@dataclass(frozen=True, slots=True)
class Built:
    world: FirstMoveWorld | None
    #: Why there is no world ("" when there is one).
    reason: str = ""


def _usage() -> Usage | None:
    """How full the plan's windows are, read at most once a minute; ``None``: unreadable."""
    try:
        from dodaios import agent_accounts, agent_usage

        account = agent_accounts.active_account("claude")
        found = agent_usage.collect([account]).get(account.id)
    except Exception:  # noqa: BLE001 - no reading: the night's cap alone applies
        log.debug("self-improvement: the plan's usage could not be read", exc_info=True)
        return None
    if found is None or found.status != "ok" or not found.windows:
        return None
    return {f"{w.kind}:{w.scope_label or w.raw_label or ''}": w.percent for w in found.windows}


def _cooling() -> bool:
    try:
        from dodaios.claude_auth_state import claude_auth_dead
        from dodaios.claude_quota_state import claude_in_quota_cooldown

        return bool(claude_in_quota_cooldown() or claude_auth_dead())
    except Exception:  # noqa: BLE001 - an unreadable state is a reason to wait
        log.debug("self-improvement: the plan's state could not be read", exc_info=True)
        return True


def _version(prefix: list[str], env: dict[str, str]) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - the CLI's own argv
            [*prefix, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,  # type: ignore[attr-defined]
        )
    except (OSError, subprocess.SubprocessError):  # a version we cannot read is named as such
        return "unknown"
    return (done.stdout or "").strip()[:80] or "unknown"


def _tool_rows(session_id: str, loop: Any) -> list[dict[str, Any]]:
    from dodaios.mcp.dodaios_tools_server import tool_rows

    if loop is None or loop.is_closed():
        return []
    future = asyncio.run_coroutine_threadsafe(tool_rows(session_id), loop)
    return list(future.result(timeout=60))


def build(
    *,
    home: Path,
    turns: Any,
    loop: Any,
    idle: Callable[[], bool],
    cap: int = FIRST_MOVE_CALLS,
) -> Built:
    """The world for tonight, or why there is none. Blocking; call it off the event loop."""
    newest = turns.turns(limit=1)
    if not newest:
        return Built(None, "no lead turn is on record yet")
    lead = newest[0]
    if lead.cli not in RUNNERS:
        return Built(None, f"no replay for the lead's CLI ({lead.cli}) yet")
    if getattr(sys, "frozen", False):
        return Built(None, "this build cannot start the replay's tool server")
    try:
        from dodaios.agent_chat.runner_cli import (
            SILENT_TURN_REMINDER_ENV,
            _account_env,  # noqa: PLC2701 - the lead's own account environment
            claude_argv_prefix,
        )
        from dodaios.brain.background_policy import login_state

        env = _account_env("claude")
        prefix = claude_argv_prefix()
    except Exception as exc:  # noqa: BLE001 - no CLI or no account: no replay tonight
        return Built(None, f"the lead's CLI cannot start: {type(exc).__name__}")
    if any(env.get(name) for name in _KEY_VARS):
        return Built(None, "an API key reaches the lead's CLI; it would be billed per token")
    if login_state("claude-cli") is not True:
        return Built(None, "the lead's CLI is not signed in to its plan")
    if _cooling():
        return Built(None, "the lead's plan is cooling down after a limit")
    try:
        rows = _tool_rows(lead.session_id, loop)
    except Exception:  # noqa: BLE001 - without the tool list a replay would offer other tools
        log.info("self-improvement: the lead's tool list could not be read", exc_info=True)
        rows = []
    if not rows:
        return Built(None, "the lead's tool list could not be read")
    scratch = Path(home) / "rsi" / "replay"
    scratch.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str)
    tools_file = scratch / "tools.json"
    tools_file.write_text(blob, encoding="utf-8")
    env = {**env, SILENT_TURN_REMINDER_ENV: "0"}
    platform = Platform(
        cli=lead.cli,
        model=lead.model,
        effort=lead.effort,
        cli_version=_version(prefix, env),
        tools=hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16],
    )
    driver = ClaudeReplay(
        tools_file=tools_file,
        scratch=scratch,
        env=env,
        argv_prefix=prefix,
        session_id=lead.session_id,
    )
    world = FirstMoveWorld(
        platform=platform,
        driver=driver,
        budget=Budget(cap, usage=_usage, idle=idle),
        offered=frozenset(str(row["name"]) for row in rows),
        recorded=turns.turn,
    )
    return Built(world)
