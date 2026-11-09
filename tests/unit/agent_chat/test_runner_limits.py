"""Thread-mode runner limits that were lifted to match a grid pane."""

from __future__ import annotations

from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_chat.team.engine import Limits


def test_outstanding_tracks_background_tasks_and_sub_agents() -> None:
    st = rc._ClaudeState(turn_id="t")
    assert not rc._claude_outstanding(st)
    st.open_tasks["a"] = "build"
    assert rc._claude_outstanding(st)
    st.open_tasks.clear()
    child = rc._ClaudeState(turn_id="t")
    child.open_tasks["b"] = "agent"
    st.agents["call"] = child
    assert rc._claude_outstanding(st)


def test_parent_agent_session_markers_are_stripped() -> None:
    env = {"CLAUDECODE": "1", "CLAUDE_EFFORT": "high", "CODEX_SANDBOX": "x", "PATH": "/bin"}
    assert rc._without_parent_session(env) == {"PATH": "/bin"}


def test_team_limits_default_to_no_cap() -> None:
    limits = Limits.of(None)
    assert (limits.max_minutes, limits.max_turns, limits.turn_minutes) == (0, 0, 0)
    assert Limits.of({"max_turns": 7}).max_turns == 7

