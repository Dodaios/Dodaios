"""Planner table: maps each CLI family to its plan builder, with identity refresh."""

from __future__ import annotations

from typing import Any, Final

from dodaios.agent_chat.runner_cli.agy import plan_agy
from dodaios.agent_chat.runner_cli.base import CliPlan
from dodaios.agent_chat.runner_cli.claude import plan_claude, plan_glm
from dodaios.agent_chat.runner_cli.codex import plan_codex
from dodaios.agent_chat.runner_cli.cursor import plan_cursor
from dodaios.agent_chat.runner_cli.custom import plan_custom_cli, plan_dsh
from dodaios.agent_chat.runner_cli.grok import plan_grok
from dodaios.agent_chat.runner_cli.kimi import plan_kimi
from dodaios.agent_chat.runner_cli.opencode import plan_opencode

_PLANNERS: Final[dict[str, Any]] = {
    "claude-cli": plan_claude,
    "grok-cli": plan_grok,
    "agy-cli": plan_agy,
    "codex-cli": plan_codex,
    "opencode-cli": plan_opencode,
    "kimi-cli": plan_kimi,
    "glm-cli": plan_glm,
    "dsh-cli": plan_dsh,
    "cursor-cli": plan_cursor,
    "custom-cli": plan_custom_cli,
}


#: Every runner this module drives — the catalog route's "is this a CLI
#: seat" question, answered from the planners rather than a second list.
CLI_RUNNERS: Final[frozenset[str]] = frozenset(_PLANNERS)


#: How long an ACP runtime may keep running after it answered the prompt.
_ACP_EXIT_GRACE_S: Final[float] = 10.0


#: An ACP runtime gets this long after ``session/cancel`` to end its turn
#: itself (an OpenClaw run lives in its Gateway, so killing the bridge alone
#: would leave it working and billing) before the process is killed.
_ACP_CANCEL_GRACE_S: Final[float] = 5.0


#: Stall watchdog for ACP turns (AP-19), checked every tick:
#: * the runtime must open its session within the handshake limit — generous,
#:   since a runtime may finish its own setup first (Hermes after an update);
#: * afterwards, the model must say something within the idle limit. The
#:   counter resets on every frame, and pauses while a tool runs, the person
#:   has an approval card open, or Jarvis' gateway is still serving the
#:   runtime's model call (a local model reading a long prompt or thinking
#:   sends nothing for minutes; the gateway's own read timeout bounds it).
_ACP_HANDSHAKE_TIMEOUT_S: Final[float] = 420.0

_ACP_IDLE_TIMEOUT_S: Final[float] = 300.0

_ACP_WATCH_TICK_S: Final[float] = 2.0


def _release_plan(plan: CliPlan | None) -> None:
    """Run a plan's ``after_turn`` once (an external runtime's turn slot)."""
    if plan is None or plan.after_turn is None:
        return
    release, plan.after_turn = plan.after_turn, None
    release()


def supports_cli_runner(runner: str) -> bool:
    from dodaios.agent_chat.runner_acp import supports_runner

    return runner in _PLANNERS or supports_runner(runner)
