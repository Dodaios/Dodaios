"""Issue #1871: chat agents, plugins, Gemini and Chrome on Windows."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import proactive_voice, runner_cli
from dodaios.agent_chat.runner_cli import agy_model_args, agy_model_catalog
from dodaios.credential_broker import vault_guard
from dodaios.society.retirement import Retirement, retire_named_agents

# --------------------------------------------------- 1: npm shim and cmd.exe


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe re-parses the line only on Windows")
def test_hook_settings_survive_an_npm_cmd_shim(tmp_path: Path) -> None:
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo off\r\necho ARGS: %*\r\n", encoding="utf-8")
    settings = json.dumps(vault_guard.hook_settings())
    assert "|" in settings  # the matcher: the character cmd.exe turns into a pipe

    inline = subprocess.run([str(shim), "--settings", settings], capture_output=True, text=True)
    assert "not recognized" in inline.stderr or "Read" in inline.stderr or inline.returncode != 0

    value = runner_cli._json_flag_value([str(shim)], settings)
    assert Path(value).read_text(encoding="utf-8") == settings
    fixed = subprocess.run([str(shim), "--settings", value], capture_output=True, text=True)
    assert fixed.returncode == 0, fixed.stderr
    assert fixed.stderr.strip() == ""
    assert "ARGS: --settings" in fixed.stdout


def test_json_flag_stays_inline_for_a_real_program() -> None:
    assert runner_cli._json_flag_value(["claude.exe"], '{"a": 1}') == '{"a": 1}'
    assert runner_cli._json_flag_value(["node", "cli.js"], '{"a": 1}') == '{"a": 1}'


def test_claude_prefix_prefers_the_native_program_behind_the_shim(tmp_path: Path) -> None:
    from dodaios import claude_auth

    package = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    package.mkdir(parents=True)
    native = package / "claude.exe"
    native.write_text("", encoding="utf-8")
    shim = tmp_path / "claude.cmd"
    shim.write_text("@echo off", encoding="utf-8")
    assert claude_auth.claude_cli_argv_prefix(str(shim)) == [str(native)]


# --------------------------------------------- 3: vault_guard in a frozen build


def test_hook_command_in_a_frozen_build_calls_the_executable_itself(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Dodaios\DodaiosApp.exe")
    command = vault_guard.hook_command()
    assert command == r'"C:\Dodaios\DodaiosApp.exe" --vault-guard-hook'
    assert ".py" not in command


def test_hook_command_from_source_runs_the_script(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = vault_guard.hook_command("python3")
    assert command.startswith('"python3" "') and command.endswith('vault_guard.py"')
    assert Path(command.split('"')[3]).is_file()


def test_the_hook_entry_blocks_a_vault_read_and_lets_a_normal_read_pass(monkeypatch) -> None:
    def run(payload: dict) -> int:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        return vault_guard.main()

    assert run({"tool_name": "Read", "tool_input": {"file_path": "x/data/credentials.json"}}) == 2
    assert run({"tool_name": "Read", "tool_input": {"file_path": "notes.txt"}}) == 0


def test_main_dispatches_the_hook_flag_before_booting_the_app() -> None:
    source = (Path(__file__).parents[2] / "dodaios" / "__main__.py").read_text(encoding="utf-8")
    assert vault_guard.FROZEN_FLAG in source
    assert source.index(vault_guard.FROZEN_FLAG) < source.index("def main")


# ------------------------------------- 2: bundled plugin servers in a frozen exe


def test_frozen_dash_m_runs_only_the_packages_own_modules() -> None:
    from dodaios.core import frozen_module

    assert frozen_module._own_module("dodaios.plugins.tool.connected_server") == (
        "dodaios.plugins.tool.connected_server"
    )
    assert frozen_module._own_module("jarvis.plugins.tool.connected_server") == (
        "dodaios.plugins.tool.connected_server"
    )
    assert frozen_module._own_module("os") is None
    assert frozen_module._own_module("http.server") is None
    assert frozen_module.run_package_module("http.server", []) == 2


def test_frozen_dash_m_runs_the_module_as_main(monkeypatch) -> None:
    from dodaios.core import frozen_module

    seen: dict = {}
    monkeypatch.setattr(
        frozen_module.runpy,
        "run_module",
        lambda name, **kw: seen.update(name=name, argv=list(sys.argv), **kw),
    )
    assert frozen_module.run_package_module("jarvis.x.y", ["youtube_studio"]) == 0
    assert seen["name"] == "dodaios.x.y"
    assert seen["argv"][1:] == ["youtube_studio"]
    assert seen["run_name"] == "__main__"


# ------------------------------------------------ 5: ChromeSession.takeover


async def test_chrome_session_has_a_takeover_the_status_light_reads(tmp_path: Path) -> None:
    from dodaios.society.browser.chrome import ChromeConnections
    from dodaios.society.browser.extension_session import ChromeSession
    from dodaios.ui.web import status_light_routes

    session = ChromeSession("agent", "profile", ChromeConnections(), ["example.com"], tmp_path)
    assert session.takeover.request is None

    runtime = SimpleNamespace(
        browser=SimpleNamespace(live=SimpleNamespace(sessions={"agent": session})),
        roster=SimpleNamespace(snapshot=lambda: []),
    )
    import dodaios.society.runtime as society_runtime

    society_runtime_current = society_runtime.current_runtime
    society_runtime.current_runtime = lambda: runtime
    try:
        assert status_light_routes._browsers() == []  # idle: no row, and no exception
        session.takeover.request_takeover("captcha")
        rows = status_light_routes._browsers()
    finally:
        society_runtime.current_runtime = society_runtime_current
        session._unsubscribe()
    assert [r["reason"] for r in rows] == ["captcha"]


# ------------------------------------------ 4: archived agents are announced


def _runtime(agents: list, routines_by_agent: dict[str, int]):
    archived: list[str] = []

    async def archive(agent_id: str) -> None:
        archived.append(agent_id)

    return SimpleNamespace(
        lead_id="lead",
        roster=SimpleNamespace(snapshot=lambda: agents, archive=archive),
        task_services=lambda: (object(), None),
        archived=archived,
        routines=routines_by_agent,
    )


async def test_retirement_reports_names_and_switched_off_routines(monkeypatch) -> None:
    from dodaios.society import routines
    from dodaios.society.events import AgentState

    agents = [
        SimpleNamespace(agent_id="lead", name="Dodaios", state=AgentState.ACTIVE),
        SimpleNamespace(agent_id="a1", name="Directeur", state=AgentState.ACTIVE),
        SimpleNamespace(agent_id="a2", name="Accountmanager", state=AgentState.ACTIVE),
        SimpleNamespace(agent_id="a3", name="Old", state=AgentState.ARCHIVED),
    ]
    runtime = _runtime(agents, {"a1": 3, "a2": 1})

    async def fake_retire(_store, _scheduler, agent_id: str) -> int:
        return runtime.routines.get(agent_id, 0)

    monkeypatch.setattr(routines, "retire_agent_routines", fake_retire)
    result = await retire_named_agents(runtime)
    assert isinstance(result, Retirement) and result
    assert result.names == ["Directeur", "Accountmanager"]
    assert result.routines == 4
    assert runtime.archived == ["a1", "a2"]


async def test_nothing_to_retire_stays_silent() -> None:
    from dodaios.society.events import AgentState

    runtime = _runtime([SimpleNamespace(agent_id="lead", name="D", state=AgentState.ACTIVE)], {})
    assert not await retire_named_agents(runtime)


def test_the_retirement_notice_is_voiced_with_a_written_fallback() -> None:
    assert "agents_retired" in proactive_voice.VOICED_KINDS
    payload = {"agents": ["Directeur", "Accountmanager"], "routines": 4}
    facts = proactive_voice.facts_of("agents_retired", [payload], None)
    assert "Directeur, Accountmanager" in facts and "4 routine" in facts
    for lang in ("en", "de", "es", "pt"):
        text = proactive_voice.fallback_text("agents_retired", [payload], lang, None)
        assert "Directeur, Accountmanager" in text and "4" in text
    none_running = {**payload, "routines": 0}
    quiet = proactive_voice.fallback_text("agents_retired", [none_running], "de", None)
    assert "Directeur" in quiet and "Routine" not in quiet


async def test_the_runtime_posts_the_notice_once_the_lead_chat_is_up(monkeypatch) -> None:
    from dodaios.agent_chat import lead
    from dodaios.society import runtime as society_runtime

    calls: list[tuple] = []

    async def fake_post(names, routines):
        calls.append((names, routines))
        return len(calls) >= 3  # the chat comes up on the third try

    monkeypatch.setattr(lead, "post_agents_retired", fake_post)
    monkeypatch.setattr(society_runtime, "_RETIREMENT_NOTICE_WAIT_S", 0)
    holder = SimpleNamespace()
    await society_runtime.SocietyRuntime._announce_retirement(
        holder, Retirement(names=["A"], routines=2)
    )
    assert calls == [(["A"], 2)] * 3


# ---------------------------------------------------- 6: Gemini / Antigravity


def test_agy_drops_a_model_its_own_list_does_not_have() -> None:
    live = agy_model_catalog(
        [{"id": "gemini-3.8-flash-high"}, {"id": "gemini-3.8-flash-low"}, {"id": "gpt-oss-120b"}]
    )
    assert agy_model_args("gemini-3.1-pro", "high", live, live=True) == ["--effort", "high"]
    assert agy_model_args("gemini-3.8-flash", "high", live, live=True) == [
        "--model",
        "gemini-3.8-flash",
        "--effort",
        "high",
    ]


def test_agy_keeps_a_newer_model_when_no_live_list_was_read() -> None:
    assert agy_model_args("gemini-3.9-flash", "high", None, live=False) == [
        "--model",
        "gemini-3.9-flash",
        "--effort",
        "high",
    ]


def test_an_ineligible_gemini_account_is_an_account_problem_not_a_network_one() -> None:
    from dodaios.brain import manager

    message = (
        "IneligibleTierError: This client is no longer supported for Gemini Code Assist "
        "for individuals. Please migrate to Antigravity"
    )
    assert manager._classify_provider_error(message, default="call_fail") == "account_blocked"
