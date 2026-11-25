"""A Claude Code seat's "/" list is the list the CLI itself reports.

The CLI names every command it accepts in a thread (its built-ins such as
``/goal``, the skills, the plugin commands): in the answer to the control
handshake, in each turn's ``system/init`` and whenever the set changes. The
composer shows that list and nothing else, the way the CLI's own terminal does;
a thread that has not run a turn asks the CLI once, without a model call.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import runner_cli, typeahead

REPORT = [
    {"name": "goal", "description": "Set a goal", "argumentHint": "", "builtin": True},
    {
        "name": "usage",
        "description": "Show session cost\nand plan usage",
        "argumentHint": "",
        "aliases": ["cost", "stats"],
    },
    {"name": "effort", "description": "Set effort level", "argumentHint": "<low|high>"},
    {"name": "deploy", "description": "Ship it"},
    {"name": "__remote-workflow", "description": "plumbing"},
    {"name": "bad name!", "description": "never a command"},
]


def _slash(folder: Path, query: str = "", runner: str = "claude-cli") -> list[dict]:
    return typeahead.suggest(runner=runner, cwd=folder, trigger="/", query=query, limit=1000)[
        "items"
    ]


def test_the_reported_list_is_the_slash_list(tmp_path: Path):
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT)
    rows = _slash(tmp_path)
    # By name, as the CLI's terminal lists them; its plumbing is not offered.
    assert [r["value"] for r in rows] == ["deploy", "effort", "goal", "usage"]
    by_name = {r["value"]: r for r in rows}
    assert by_name["effort"]["argument_hint"] == "<low|high>"
    assert by_name["usage"]["aliases"] == ["cost", "stats"]
    assert by_name["usage"]["hint"] == "Show session cost and plan usage"
    assert {r["kind"] for r in rows} == {"command"}
    # Another seat's list is its own.
    assert typeahead.suggest(runner="codex-cli", cwd=tmp_path, trigger="/")["items"] == []


def test_the_disk_does_not_add_to_what_the_cli_reports(tmp_path: Path, monkeypatch):
    """A skill folder the CLI did not load must not be offered as a command."""
    home = tmp_path / "account"
    home.mkdir()
    monkeypatch.setattr(typeahead, "claude_config_dir", lambda: home)
    skill = tmp_path / ".claude" / "skills" / "half-written"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: half-written\n---\n", encoding="utf-8")

    assert [r["value"] for r in _slash(tmp_path)] == ["half-written"]  # the CLI is silent
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT)
    assert "half-written" not in [r["value"] for r in _slash(tmp_path)]


def test_an_alias_finds_its_command(tmp_path: Path):
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT)
    assert [r["value"] for r in _slash(tmp_path, "cost")] == ["usage"]
    assert [r["value"] for r in _slash(tmp_path, "c")] == ["usage"]


def test_a_names_only_report_keeps_details_and_drops_what_is_gone(tmp_path: Path):
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT)
    # ``system/init`` of a later turn: names only, and "deploy" was removed.
    typeahead.remember_cli_commands("claude-cli", tmp_path, ["goal", "/usage", "fresh"])
    by_name = {r["value"]: r for r in _slash(tmp_path)}
    assert sorted(by_name) == ["fresh", "goal", "usage"]
    assert by_name["usage"]["aliases"] == ["cost", "stats"]
    assert by_name["goal"]["hint"] == "Set a goal"
    assert by_name["fresh"]["hint"] == ""


def test_a_thread_without_a_turn_asks_the_cli_once(tmp_path: Path, monkeypatch):
    asked: list[tuple[str, Path]] = []

    def _answer(runner: str, folder: Path | None):
        asked.append((runner, folder))
        return REPORT

    monkeypatch.undo()  # the real ``_ask_cli``; only the process behind it is a stand-in
    monkeypatch.setattr(runner_cli, "read_claude_commands", _answer)
    assert "goal" in [r["value"] for r in _slash(tmp_path)]
    assert "goal" in [r["value"] for r in _slash(tmp_path, "go")]
    assert asked == [("claude-cli", tmp_path)]
    # Another folder has its own skills, so it is asked for itself.
    other = tmp_path / "other"
    other.mkdir()
    _slash(other)
    assert [folder for _, folder in asked] == [tmp_path, other]


def test_an_old_list_is_asked_again(tmp_path: Path, monkeypatch):
    calls = {"n": 0}

    def _answer(runner: str, folder: Path | None):
        calls["n"] += 1
        return [{"name": f"v{calls['n']}", "description": ""}]

    monkeypatch.undo()
    monkeypatch.setattr(runner_cli, "read_claude_commands", _answer)
    clock = {"now": 1000.0}
    monkeypatch.setattr(typeahead.time, "monotonic", lambda: clock["now"])
    assert [r["value"] for r in _slash(tmp_path)] == ["v1"]
    clock["now"] += typeahead._CLI_LIST_TTL_S - 1
    assert [r["value"] for r in _slash(tmp_path)] == ["v1"]
    clock["now"] += 2
    assert [r["value"] for r in _slash(tmp_path)] == ["v2"]


def test_a_silent_cli_falls_back_to_the_disk_and_is_left_alone_for_a_while(
    tmp_path: Path, monkeypatch
):
    home = tmp_path / "account"
    home.mkdir()
    skill = tmp_path / ".claude" / "skills" / "deploy"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: Ship it\n---\n", encoding="utf-8"
    )
    calls = {"n": 0}

    def _silent(runner: str, folder: Path | None):
        calls["n"] += 1
        return None

    monkeypatch.undo()
    monkeypatch.setattr(typeahead, "claude_config_dir", lambda: home)
    monkeypatch.setattr(runner_cli, "read_claude_commands", _silent)
    clock = {"now": 50.0}
    monkeypatch.setattr(typeahead.time, "monotonic", lambda: clock["now"])
    for _ in range(3):  # three keystrokes, one attempt
        assert [r["value"] for r in _slash(tmp_path)] == ["deploy"]
    assert calls["n"] == 1
    clock["now"] += typeahead._CLI_RETRY_S + 1
    _slash(tmp_path)
    assert calls["n"] == 2


def test_a_probe_keeps_the_mcp_prompts_a_turn_reported(tmp_path: Path):
    """The probe starts no MCP server, so it cannot see their prompts."""
    typeahead.remember_cli_commands(
        "claude-cli",
        tmp_path,
        [*REPORT, {"name": "mcp__docs__search", "description": "Search the docs"}],
    )
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT[:1], from_probe=True)
    assert [r["value"] for r in _slash(tmp_path)] == ["goal", "mcp__docs__search"]
    # A turn's own report is the whole truth again.
    typeahead.remember_cli_commands("claude-cli", tmp_path, REPORT[:1])
    assert [r["value"] for r in _slash(tmp_path)] == ["goal"]


# ------------------------------------------------------------ the probe itself


def test_the_three_stream_lines_that_carry_the_list():
    full = [{"name": "goal", "description": "Set a goal"}]
    handshake = {"type": "control_response", "response": {"response": {"commands": full}}}
    assert runner_cli.claude_reported_commands(handshake) == full
    init = {"type": "system", "subtype": "init", "slash_commands": ["goal", "compact"]}
    assert runner_cli.claude_reported_commands(init) == ["goal", "compact"]
    changed = {"type": "system", "subtype": "commands_changed", "commands": full}
    assert runner_cli.claude_reported_commands(changed) == full
    # Anything else that happens to carry a "commands" key is not a report.
    assert runner_cli.claude_reported_commands({"type": "assistant", "commands": full}) is None
    assert runner_cli.claude_reported_commands({"type": "control_response"}) is None


def test_the_probe_sends_the_handshake_only_and_leaves_nothing_behind(tmp_path, monkeypatch):
    seen: dict = {}

    def _run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        lines = [
            "not json",
            json.dumps({"type": "system", "subtype": "hook_started"}),
            json.dumps(
                {
                    "type": "control_response",
                    "response": {"subtype": "success", "response": {"commands": REPORT}},
                }
            ),
        ]
        return SimpleNamespace(stdout="\n".join(lines).encode("utf-8"), returncode=0)

    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "_account_env", lambda platform: {"SEAT": platform})
    monkeypatch.setattr(subprocess, "run", _run)

    assert runner_cli.read_claude_commands("claude-cli", tmp_path) == REPORT
    argv = seen["argv"]
    assert argv[0] == "claude" and "--print" in argv
    # Typing "/" is not work: no session file, no MCP server, no hook.
    assert "--no-session-persistence" in argv and "--strict-mcp-config" in argv
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}
    # The handshake is all the CLI is told; stdin then ends, so no turn starts.
    sent = [json.loads(line) for line in seen["input"].decode("utf-8").splitlines()]
    assert [m["type"] for m in sent] == ["control_request"]
    assert sent[0]["request"]["subtype"] == "initialize"
    assert seen["cwd"] == str(tmp_path) and seen["env"] == {"SEAT": "claude"}
    assert seen["timeout"] > 0


@pytest.mark.parametrize(
    "failure",
    [
        runner_cli.CliUnavailable("Claude Code (claude) is not installed or not on PATH."),
        subprocess.TimeoutExpired(cmd="claude", timeout=1),
        OSError("gone"),
    ],
)
def test_a_cli_that_cannot_answer_is_no_list_not_an_error(tmp_path, monkeypatch, failure):
    def _run(argv, **kwargs):
        raise failure

    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "_account_env", lambda platform: {})
    monkeypatch.setattr(subprocess, "run", _run)
    assert runner_cli.read_claude_commands("claude-cli", tmp_path) is None


def test_an_older_cli_that_prints_no_list_is_no_list(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "_account_env", lambda platform: {})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(
            stdout=b"error: unknown option '--no-session-persistence'\n", returncode=1
        ),
    )
    assert runner_cli.read_claude_commands("claude-cli", tmp_path) is None
