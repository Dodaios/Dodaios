"""Ask is binding on a Claude Code seat (dodaios/agent_chat/runner_cli.py).

Claude Code loads the person's own settings files, whose allow list can name
``Edit``, ``Write`` or ``PowerShell``; without more, an agent in Ask wrote
files with no approval card (live finding 2026-10-28). The seat adds ask rules
for this process only, answers reads of Dodaios' own tools without a card,
and answers a repeat that an earlier "Always allow" covers itself.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.core.branding import MCP_TOOLS_SERVER_NAME
from tests.unit.agent_chat.test_turn_prompts import (
    _can_use,
    _fake_claude,
    _FakeChat,
    _session,
)

_MCP = f"mcp__{MCP_TOOLS_SERVER_NAME}__"


def _plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str) -> list[str]:
    monkeypatch.setattr(rc, "claude_argv_prefix", lambda: ["claude"])
    return rc.plan_claude(
        prompt="hi", cwd=tmp_path, model="", effort="", permission_mode=mode, resume=None
    ).argv


def test_ask_adds_process_only_ask_rules_for_writes_and_commands(monkeypatch, tmp_path):
    argv = _plan(monkeypatch, tmp_path, "default")
    assert argv[argv.index("--permission-mode") + 1] == "default"
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert set(settings) == {"permissions"}
    assert set(settings["permissions"]) == {"ask"}
    assert {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"} <= set(
        settings["permissions"]["ask"]
    )
    # The person's settings are never replaced: no source is switched off.
    assert "--setting-sources" not in argv
    # The society word "ask" lands on the same mode and the same rules.
    assert "--settings" in _plan(monkeypatch, tmp_path, "ask")


@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits", "plan", "auto", "dontAsk"])
def test_other_modes_behave_as_before(monkeypatch, tmp_path, mode):
    assert "--settings" not in _plan(monkeypatch, tmp_path, mode)


def test_glm_rides_the_same_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(rc, "_registry_env", lambda agent, base: dict(base))
    argv = rc.plan_glm(
        prompt="hi", cwd=tmp_path, model="", effort="", permission_mode="default", resume=None
    ).argv
    assert "Write" in json.loads(argv[argv.index("--settings") + 1])["permissions"]["ask"]


def test_always_allow_rules_cover_only_what_they_name():
    whole = [{"type": "addRules", "behavior": "allow", "rules": [{"toolName": "Write"}]}]
    assert rc.claude_rules_cover(whole, "Write", {"file_path": "a.txt"})
    assert not rc.claude_rules_cover(whole, "Edit", {"file_path": "a.txt"})

    prefix = [
        {
            "type": "addRules",
            "behavior": "allow",
            "rules": [{"toolName": "Bash", "ruleContent": "git log:*"}],
        }
    ]
    assert rc.claude_rules_cover(prefix, "Bash", {"command": "git log --oneline"})
    assert rc.claude_rules_cover(prefix, "Bash", {"command": "git log"})
    assert not rc.claude_rules_cover(prefix, "Bash", {"command": "git push"})
    assert not rc.claude_rules_cover(prefix, "PowerShell", {"command": "git log"})
    # A prefix rule speaks for one command, never for a chained or redirected line.
    for chained in (
        "git log && rm -rf ~",
        "git log; del x",
        "git log | sh",
        "git log > out.txt",
        "git log $(whoami)",
        "git log `whoami`",
        "git log\nrm -rf ~",
    ):
        assert not rc.claude_rules_cover(prefix, "Bash", {"command": chained}), chained
    # The whole tool allowed (no rule content) still covers any line.
    whole_shell = [{"type": "addRules", "behavior": "allow", "rules": [{"toolName": "Bash"}]}]
    assert rc.claude_rules_cover(whole_shell, "Bash", {"command": "git log && ls"})

    edits = [{"type": "setMode", "mode": "acceptEdits", "destination": "session"}]
    assert rc.claude_rules_cover(edits, "Edit", {})
    assert not rc.claude_rules_cover(edits, "Bash", {"command": "ls"})

    deny = [{"type": "addRules", "behavior": "deny", "rules": [{"toolName": "Write"}]}]
    assert not rc.claude_rules_cover(deny, "Write", {})
    assert not rc.claude_rules_cover([], "Write", {})


def _turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requests: list[dict[str, Any]],
    *,
    decision: str = "allow",
    surface: str = "agent",
    mode: str = "default",
    session_id: str = "s1",
) -> tuple[list[dict[str, Any]], list[str]]:
    out = tmp_path / "answers.json"
    plan = rc.CliPlan(
        _fake_claude(requests, out),
        dict(os.environ),
        rc.claude_stream_input("hi"),
        "claude",
        "v1",
        keep_stdin=True,
        control_init=rc.claude_control_init(),
    )
    monkeypatch.setitem(rc._PLANNERS, "claude-cli", lambda **kw: plan)
    asked: list[str] = []

    async def emit(_ev: dict[str, Any]) -> None:
        return None

    async def ask(_call_id: str, name: str, *_: object) -> str:
        asked.append(name)
        return decision

    session = replace(
        _session(tmp_path, "claude-api", surface=surface, mode=mode), session_id=session_id
    )
    handle = TurnHandle(
        session=session,
        turn_id="t1",
        emit=emit,
        request_approval=ask,
        cancel=asyncio.Event(),
        control_service=_FakeChat(),
    )
    asyncio.run(rc.run_cli_turn(handle, "hi", "claude-cli"))
    return json.loads(out.read_text(encoding="utf-8")), asked


def test_a_write_asks_on_the_card_and_always_allow_answers_the_repeat(monkeypatch, tmp_path):
    requests = [
        _can_use("Write", {"file_path": "a.txt", "content": "x"}, "r1"),
        _can_use("Write", {"file_path": "b.txt", "content": "y"}, "r2"),
        _can_use("Bash", {"command": "echo hi"}, "r3"),
    ]
    answers, asked = _turn(monkeypatch, tmp_path, requests, decision="allow_always")
    # The first Write and the shell command reach the card; the second Write
    # is covered by the rule the first "Always allow" gave this process.
    assert asked == ["Write", "Bash"]
    assert [a["behavior"] for a in answers] == ["allow", "allow", "allow"]
    assert answers[0]["updatedPermissions"][0]["destination"] == "session"
    assert "updatedPermissions" not in answers[1]


def test_a_denied_write_does_not_run(monkeypatch, tmp_path):
    answers, asked = _turn(
        monkeypatch, tmp_path, [_can_use("Write", {"file_path": "a.txt"})], decision="deny"
    )
    assert asked == ["Write"]
    assert answers == [{"behavior": "deny", "message": "The person declined this action."}]


def _read_only(names: set[str]):
    async def wire_read_only(_session_id: str, wire: str, _args: Any = None) -> bool:
        return wire in names

    return wire_read_only


def test_reads_of_dodaios_tools_need_no_card_but_writes_do(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "dodaios.mcp.dodaios_tools_server.wire_read_only", _read_only({"society_routines"})
    )
    requests = [
        _can_use(_MCP + "society_routines", {}, "r1"),
        _can_use(_MCP + "society-create-routine", {"title": "x"}, "r2"),
    ]
    answers, asked = _turn(monkeypatch, tmp_path, requests)
    assert asked == [_MCP + "society-create-routine"]
    assert [a["behavior"] for a in answers] == ["allow", "allow"]


def test_an_agents_own_require_approval_rule_still_asks_for_a_read(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "dodaios.mcp.dodaios_tools_server.wire_read_only", _read_only({"society_routines"})
    )
    ruled: list[str] = []

    def requires(_session_id: str, tool: str, _args: dict[str, Any]) -> bool:
        ruled.append(tool)
        return True

    monkeypatch.setattr("dodaios.society.surface.requires_explicit_approval", requires)
    _, asked = _turn(
        monkeypatch,
        tmp_path,
        [_can_use(_MCP + "society_routines", {})],
        surface="society",
        mode="ask",
        session_id="society:reader",
    )
    assert ruled == ["society_routines"]
    assert asked == [_MCP + "society_routines"]


def test_always_ask_and_other_servers_keep_asking_for_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "dodaios.mcp.dodaios_tools_server.wire_read_only", _read_only({"society_routines"})
    )
    _, asked = _turn(
        monkeypatch, tmp_path, [_can_use(_MCP + "society_routines", {})], mode="always_ask"
    )
    assert asked == [_MCP + "society_routines"]
    _, asked = _turn(monkeypatch, tmp_path, [_can_use("mcp__other__society_routines", {})])
    assert asked == ["mcp__other__society_routines"]


async def test_the_tool_server_judges_reads_like_its_read_only_hint(monkeypatch):
    from types import SimpleNamespace

    from dodaios.mcp import dodaios_tools_server as server

    entries = [
        SimpleNamespace(name="society_routines", risk_tier="safe", is_action_tool=False),
        SimpleNamespace(name="society_shell", risk_tier="monitor", is_action_tool=False),
        SimpleNamespace(name="open-app", risk_tier="safe", is_action_tool=True),
        SimpleNamespace(
            name="society_propose_change",
            risk_tier="safe",
            is_action_tool=False,
            risk_tier_for_args=lambda args: "monitor" if args.get("mode") == "apply" else "safe",
        ),
    ]
    seen: list[str | None] = []

    async def catalog() -> dict[str, Any]:
        seen.append(server.CHAT_SESSION_REF.get())
        return {entry.name: entry for entry in entries}

    monkeypatch.setattr(server, "_session_wire_catalog", catalog)
    assert await server.wire_read_only("society:a", "society_routines")
    assert not await server.wire_read_only("society:a", "society_shell")
    assert not await server.wire_read_only("society:a", "open-app")
    assert not await server.wire_read_only("society:a", "missing")
    assert await server.wire_read_only("society:a", "society_propose_change", {})
    assert not await server.wire_read_only(
        "society:a", "society_propose_change", {"mode": "apply"}
    )
    assert set(seen) == {"society:a"}
    assert server.CHAT_SESSION_REF.get() is None
