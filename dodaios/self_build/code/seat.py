"""Which coding CLI may run loop work right now, on the person's subscription only.

The maintainer's rule: once a subscription is connected, background work never
bills a per-token key (``dodaios.brain.background_policy``). A coding run is
the most expensive background work there is, so the rule is strict here:

* only a CLI whose plan login is confirmed signed in right now;
* never while that CLI's own API-key variable reaches it, since the CLI would
  bill that key instead of the plan. Codex is run with those variables removed
  from its own child environment when its login is a ChatGPT plan (see
  :func:`codex_plan_login`); the app's environment is never changed. Claude
  Code with a key in the environment is skipped;
* never inside a cooldown after the plan reported its usage limit, after a
  dead login, or while a usage window is nearly spent.

Anything else is an unknown and the answer is "wait".
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from loguru import logger

#: Thread runner -> (the brain provider whose login probe answers for its plan,
#: the account platform, the environment variables that make the CLI bill a key).
SEATS: Final[dict[str, tuple[str, str, tuple[str, ...]]]] = {
    "claude-cli": ("claude-cli", "claude", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")),
    "codex-cli": ("codex", "codex", ("OPENAI_API_KEY", "CODEX_API_KEY")),
}
#: Runners that may run with their key variables removed from the child
#: environment, because without them the CLI bills the plan login it holds.
#: Checked against Codex CLI 0.160: with a ChatGPT login in ``auth.json``,
#: ``codex exec`` ignores ``OPENAI_API_KEY`` but bills ``CODEX_API_KEY``.
STRIPPABLE: Final[frozenset[str]] = frozenset({"codex-cli"})
#: A usage window this full leaves the plan to the person.
FULL_PERCENT: Final[float] = 80.0
_FORCED_LOGIN: Final[re.Pattern[str]] = re.compile(
    r"""^\s*forced_login_method\s*=\s*["']([^"']*)["']""", re.MULTILINE
)


@dataclass(frozen=True, slots=True)
class Seat:
    #: The agent-chat provider id the thread opens with.
    provider: str
    runner: str
    label: str
    #: Environment variables the coding CLI's child process must not see.
    drop_env: tuple[str, ...] = ()


def _codex_home() -> Path:
    """The ``CODEX_HOME`` a thread's Codex runs with: the active account's, else the default."""
    env: dict[str, str] = dict(os.environ)
    try:
        from dodaios import agent_accounts

        account = agent_accounts.active_account("codex")
        env = agent_accounts.spawn_env("codex", account.id, base=os.environ)
    except Exception:  # noqa: BLE001 - no account layer: the CLI's own default applies
        logger.opt(exception=True).debug("self-build code: codex account unreadable")
    return Path(env.get("CODEX_HOME") or Path.home() / ".codex")


def _forced_login(config_toml: str) -> str:
    """``forced_login_method`` at the top level of a Codex ``config.toml`` ("" when unset)."""
    top = re.split(r"(?m)^\s*\[", config_toml, maxsplit=1)[0]
    match = _FORCED_LOGIN.search(top)
    return match.group(1).strip().lower() if match else ""


def codex_plan_login(home: Path | None = None) -> bool:
    """Does this Codex home hold a ChatGPT plan login the CLI will use without a key?

    Strict on purpose, since a yes lets a run start while a key is in the app's
    environment: ``auth.json`` carries ChatGPT tokens, no stored API key and
    no other ``auth_mode``, and ``config.toml`` does not force the API login.
    """
    home = home or _codex_home()
    try:
        auth = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no readable login: not a plan login
        return False
    if not isinstance(auth, dict):
        return False
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict) or not any(
        isinstance(tokens.get(k), str) and tokens.get(k)
        for k in ("access_token", "refresh_token", "id_token")
    ):
        return False
    if auth.get("OPENAI_API_KEY") or auth.get("openai_api_key"):
        return False
    mode = str(auth.get("auth_mode") or "chatgpt").lower()
    if not mode.startswith("chatgpt"):
        return False
    try:
        config = (home / "config.toml").read_text(encoding="utf-8")
    except OSError:  # no config: nothing forces the API login
        config = ""
    return _forced_login(config) not in ("api", "apikey")


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
        drop: tuple[str, ...] = ()
        if runner in STRIPPABLE and codex_plan_login():
            drop = key_vars  # always: a key set later must not reach the run either
        elif any(os.environ.get(name) for name in key_vars):
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
        return Seat(provider=row.id, runner=runner, label=row.label, drop_env=drop), ""
    return None, "; ".join(reasons) or "no subscription coding CLI"


async def installed_clis() -> dict[str, bool]:
    try:
        from dodaios.workspace.agents import detect_agents

        return {info.name: bool(info.installed) for info in await detect_agents()}
    except Exception:  # noqa: BLE001 - unknown means "not installed" here: wait
        logger.opt(exception=True).debug("self-build code: CLI detection failed")
        return {}
