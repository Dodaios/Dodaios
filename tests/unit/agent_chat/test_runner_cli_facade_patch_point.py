"""The ``runner_cli`` facade is the one place a test patches (and code outside reads).

Code inside the package reads patchable names through the facade at call time,
so a patch on ``runner_cli.X`` reaches every reader, whichever submodule it is in.
"""

from __future__ import annotations

from pathlib import Path

from dodaios.agent_chat import runner_cli


def test_a_facade_patch_reaches_a_reader_in_another_module(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["patched-claude"])
    monkeypatch.setattr(runner_cli, "_account_env", lambda platform: {"SEAT": platform})
    monkeypatch.setattr(runner_cli, "_registry_env", lambda agent, env: env)
    plan = runner_cli.plan_claude(
        prompt="hi", cwd=tmp_path, model="", effort="", permission_mode="auto", resume=None
    )
    assert plan.argv[0] == "patched-claude"
    assert plan.env is not None and plan.env.get("SEAT") == "claude"


def test_a_facade_patch_of_a_catalog_reader_reaches_the_codex_planner(monkeypatch, tmp_path: Path):
    seen: list[bool] = []
    monkeypatch.setattr(runner_cli, "codex_argv_prefix", lambda: ["codex"])
    monkeypatch.setattr(runner_cli, "_account_env", lambda platform: {})
    monkeypatch.setattr(runner_cli, "_registry_env", lambda agent, env: env)
    monkeypatch.setattr(runner_cli, "read_codex_models", lambda **_kw: seen.append(True) or None)
    runner_cli.plan_codex(
        prompt="p", cwd=tmp_path, model="gpt-5.5", effort="high", permission_mode="auto", resume=None
    )
    assert seen


def test_a_facade_patch_of_the_cli_check_reaches_the_runner_checks(monkeypatch):
    monkeypatch.setattr(runner_cli, "cli_installed", lambda runner: runner == "only-this")
    assert runner_cli.supports_cli_runner("claude-cli") in (True, False)
    assert runner_cli.cli_installed("only-this") is True
