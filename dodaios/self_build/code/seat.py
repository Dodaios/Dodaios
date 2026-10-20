"""Which coding CLI may run loop work right now, on the person's subscription only.

The maintainer's rule: once a subscription is connected, background work never
bills a per-token key (``dodaios.brain.background_policy``). A coding run is
the most expensive background work there is, so the rule is strict here:

* only a CLI whose plan login is confirmed signed in right now;
* never while that CLI's own API-key variable is in the environment, since
  the CLI would bill that key instead of the plan;
* never inside a cooldown after the plan reported its usage limit, after a
  dead login, or while a usage window is nearly spent.

Anything else is an unknown and the answer is "wait".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger

#: Thread runner -> (the brain provider whose login probe answers for its plan,
#: the account platform, the environment variables that make the CLI bill a key).
SEATS: Final[dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "claude-cli": ("claude-cli", "claude", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")),
    "codex-cli": ("codex", "codex", ("OPENAI_API_KEY", "CODEX_API_KEY")),
}
#: A usage window this full leaves the plan to the person.
FULL_PERCENT: Final[float] = 80.0


@dataclass(frozen=True, slots=True)
class Seat:
    #: The agent-chat provider id the thread opens with.
    provider: str
    runner: str
    label: str


def _cooling(runner: str) -> bool:
    try:
        if runner == "claude-cli":
            from dodaios.claude_auth_state import claude_auth_dead
            from dodaios.claude_quota_state import claude_in_quota_cooldown

            return bool(claude_in_quota_cooldown() or claude_auth_dead())
        if runner == "codex-cli":
            from dodaios.codex_auth_state import codex_needs_reauth
            from dodaios.codex_quota_state import codex_in_quota_cooldown

            return bool(codex_in_quota_cooldown() or codex_needs_reauth())
    except Exception:  # noqa: BLE001 - an unreadable state is a reason to wait
        logger.opt(exception=True).debug("self-build code: cooldown state unreadable")
        return True
    return False


def _window_full(platform: str) -> bool:
    try:
        from dodaios import agent_accounts, agent_usage

        account = agent_accounts.active_account(platform)  # type: ignore[arg-type]
        usage = agent_usage.read_usage(account)
    except Exception:  # noqa: BLE001 - no reading is not a full window
        logger.opt(exception=True).debug("self-build code: usage unreadable for {}", platform)
        return False
    return any(window.percent >= FULL_PERCENT for window in usage.windows)


def _rows() -> list[Any]:
    from dodaios.agent_chat.catalog import rows_for

    return [row for row in rows_for("agent") if row.agent]


def choose(installed: dict[str, bool] | None = None) -> tuple[Seat | None, str]:
    """The seat to run on, or ``(None, why not)``. Blocking: probes CLIs."""
    from dodaios.agent_chat.service import resolve_runner
    from dodaios.brain.background_policy import login_state

    reasons: list[str] = []
    for row in _rows():
        try:
            runner = resolve_runner(row.id, surface="agent")
        except Exception:  # noqa: BLE001 - a row that cannot resolve is not a seat
            logger.opt(exception=True).debug("self-build code: no runner for {}", row.id)
            continue
        seat = SEATS.get(runner)
        if seat is None:
            continue  # billing unknown to this module: never used in the background
        brain, platform, key_vars = seat
        if installed is not None and not installed.get(row.agent, False):
            reasons.append(f"{row.label}: not installed")
            continue
        if any(os.environ.get(name) for name in key_vars):
            reasons.append(f"{row.label}: an API key in the environment would be billed")
            continue
        if login_state(brain) is not True:
            reasons.append(f"{row.label}: plan not signed in")
            continue
        if _cooling(runner):
            reasons.append(f"{row.label}: plan cooling down")
            continue
        if _window_full(platform):
            reasons.append(f"{row.label}: usage window nearly spent")
            continue
        return Seat(provider=row.id, runner=runner, label=row.label), ""
    return None, "; ".join(reasons) or "no subscription coding CLI"


async def installed_clis() -> dict[str, bool]:
    try:
        from dodaios.workspace.agents import detect_agents

        return {info.name: bool(info.installed) for info in await detect_agents()}
    except Exception:  # noqa: BLE001 - unknown means "not installed" here: wait
        logger.opt(exception=True).debug("self-build code: CLI detection failed")
        return {}
