"""An identity turn (the lead's chat or a society seat) stays inside the Dodaios gateway.

The vendor CLI's own web, shell, sub-agent and connector tools run outside the
trust layer (risk tiers, origin ledger, outbound check, audit log). The planned
argv for an identity turn takes them away where the CLI has a flag for it; a
coding thread (no identity) is a plain CLI session and is left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agent_chat import dodaios_harness, runner_cli
from dodaios.core import runtime_refs


@pytest.fixture(autouse=True)
def _app(monkeypatch):
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "codex_argv_prefix", lambda: ["codex"])
    monkeypatch.setattr(runner_cli, "grok_argv_prefix", lambda: ["grok"])
    monkeypatch.setattr(runner_cli, "read_codex_models", lambda **_: None)
    monkeypatch.setattr(runner_cli, "_registry_env", lambda agent, base: dict(base))
    monkeypatch.setattr(runner_cli.dodaios_harness, "control_key", lambda: "k")
    runtime_refs.set_api_base_url("http://127.0.0.1:47821")
    yield
    runtime_refs._reset_for_tests()


def _identity(tmp_path: Path, session_id: str) -> dodaios_harness.Identity:
    path = tmp_path / "id.md"
    path.write_text("IDENTITY", encoding="utf-8")
    return dodaios_harness.Identity(session_id=session_id, text="x", compact="x", path=path)


def _plan(planner, tmp_path: Path, identity):
    return planner(
        prompt="hi",
        cwd=tmp_path,
        model="",
        effort="",
        permission_mode="default",
        resume=None,
        identity=identity,
    )


def _disallowed(argv: list[str]) -> set[str]:
    return set(argv[argv.index("--disallowedTools") + 1].split(","))


@pytest.mark.parametrize("planner_name", ["plan_claude", "plan_glm"])
def test_the_lead_on_claude_code_loads_only_the_dodaios_server_and_its_hands_are_gated(
    tmp_path, planner_name
):
    argv = _plan(getattr(runner_cli, planner_name), tmp_path, _identity(tmp_path, "lead-1")).argv
    # The person's own MCP servers and their account's cloud connectors are not loaded.
    assert "--strict-mcp-config" in argv and "--mcp-config" in argv
    removed = _disallowed(argv)
    # Web results get their origin from the Dodaios web tools.
    assert {"WebSearch", "WebFetch"} <= removed
    # Shell goes through run_shell, which tiers every command.
    assert {"Bash", "PowerShell"} <= removed
    # The lead delegates through the Dodaios tools, never the vendor's sub-agent tool.
    assert {"Task", "Agent"} <= removed
    # The file tools stay: they act in the chat's working folder.
    assert not removed & {"Read", "Write", "Edit", "Glob", "Grep"}


def test_a_society_seat_loses_connectors_web_and_sub_agents_but_keeps_its_workspace_shell(
    tmp_path,
):
    argv = _plan(runner_cli.plan_claude, tmp_path, _identity(tmp_path, "society:scout")).argv
    assert "--strict-mcp-config" in argv
    removed = _disallowed(argv)
    assert {"WebSearch", "WebFetch", "Task", "Agent"} <= removed
    assert not removed & {"Bash", "PowerShell"}


def test_a_coding_thread_is_a_plain_cli_session(tmp_path):
    argv = _plan(runner_cli.plan_claude, tmp_path, None).argv
    assert "--strict-mcp-config" not in argv and "--disallowedTools" not in argv


def test_nothing_is_taken_away_when_the_app_cannot_offer_its_own_tools(tmp_path, monkeypatch):
    # Without the Dodaios server the vendor's tools are all the chat has.
    monkeypatch.setattr(runner_cli.dodaios_harness, "control_key", lambda: None)
    argv = _plan(runner_cli.plan_claude, tmp_path, _identity(tmp_path, "lead-1")).argv
    assert "--strict-mcp-config" not in argv and "--disallowedTools" not in argv


def test_a_task_turn_does_not_get_the_strict_flag_twice(tmp_path):
    argv = _plan(runner_cli.plan_claude, tmp_path, _identity(tmp_path, "lead-1")).argv
    runner_cli.isolate_task_tools(argv, "claude-cli")
    assert argv.count("--strict-mcp-config") == 1
    assert argv[argv.index("--tools") + 1] == ""


@pytest.mark.parametrize("session_id", ["lead-1", "society:scout"])
def test_grok_identity_turns_have_no_vendor_web_tools(tmp_path, session_id):
    argv = _plan(runner_cli.plan_grok, tmp_path, _identity(tmp_path, session_id)).argv
    assert "--disable-web-search" in argv


def test_a_grok_coding_thread_keeps_its_web_tools(tmp_path):
    assert "--disable-web-search" not in _plan(runner_cli.plan_grok, tmp_path, None).argv


@pytest.mark.parametrize("session_id", ["lead-1", "society:scout"])
def test_codex_identity_turns_ignore_user_config_and_have_no_vendor_web_or_connectors(
    tmp_path, session_id
):
    argv = _plan(runner_cli.plan_codex, tmp_path, _identity(tmp_path, session_id)).argv
    assert "--ignore-user-config" in argv
    disabled = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--disable"}
    assert {"apps", "plugins", "browser_use", "web_search_request"} <= disabled
    assert 'web_search="disabled"' in argv


def test_a_codex_coding_thread_is_left_alone(tmp_path):
    argv = _plan(runner_cli.plan_codex, tmp_path, None).argv
    assert "--ignore-user-config" not in argv and 'web_search="disabled"' not in argv


@pytest.mark.parametrize(
    ("planner", "runner"),
    [
        ("plan_agy", "agy-cli"),
        ("plan_opencode", "opencode-cli"),
        ("plan_kimi", "kimi-cli"),
        ("plan_cursor", "cursor-cli"),
        ("plan_dsh", "dsh-cli"),
    ],
)
def test_the_seats_without_a_flag_for_it_plan_no_unknown_options(
    tmp_path, monkeypatch, planner, runner
):
    """Gaps are documented, not papered over with flags the CLI may not know."""
    for prefix in ("agy", "opencode", "kimi", "cursor", "dsh"):
        monkeypatch.setattr(runner_cli, f"{prefix}_argv_prefix", lambda p=prefix: [p])
    monkeypatch.setattr(
        runner_cli.dodaios_harness, "install_agy_jarvis_plugin", lambda *a, **k: None
    )
    monkeypatch.setattr(runner_cli, "_agy_catalog_cached", lambda: None)
    with_identity = _plan(getattr(runner_cli, planner), tmp_path, _identity(tmp_path, "lead-1"))
    without = _plan(getattr(runner_cli, planner), tmp_path, None)
    assert runner_cli.identity_turn_flags(runner, _identity(tmp_path, "lead-1")) == []
    assert [a for a in with_identity.argv if a.startswith("--") and a not in without.argv] == []
