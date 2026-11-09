"""User-added CLIs with a headless command are thread providers."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agent_chat import catalog
from dodaios.agent_chat import runner_cli as rc
from dodaios.workspace import custom_clis


@pytest.fixture(autouse=True)
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "clis"
    monkeypatch.setattr(custom_clis, "workspace_clis_dir", lambda: root)
    monkeypatch.setattr(custom_clis, "workspace_clis_path", lambda: root / "custom.json")
    monkeypatch.setattr(rc, "_which", lambda *names: f"/bin/{names[0]}")
    monkeypatch.setattr(rc, "_account_env", lambda platform: {"BASE": "1"})
    monkeypatch.setattr(rc, "_registry_env", lambda agent, base: dict(base))
    yield


def test_expand_template_keeps_the_prompt_one_argument() -> None:
    argv, stdin = custom_clis.expand_template(
        'mycli -p {prompt} --id {session}', prompt='say "hi" && rm', session="s1"
    )
    assert argv == ["mycli", "-p", 'say "hi" && rm', "--id", "s1"]
    assert stdin is False
    argv, stdin = custom_clis.expand_template("mycli --stdin", prompt="x")
    assert argv == ["mycli", "--stdin"] and stdin is True


def test_only_entries_with_a_headless_command_become_rows() -> None:
    custom_clis.create_custom_cli("Plain Grid", "plaingrid")
    entry = custom_clis.create_custom_cli(
        "Headless One", "hl", headless_command="hl -p {prompt}"
    )
    rows = catalog.custom_rows()
    assert [r.id for r in rows] == ["custom-" + entry.id]
    row = catalog.provider_row("custom-" + entry.id)
    assert row is not None and row.runner == "custom-cli" and row.agent == entry.id
    assert row.to_dict()["effort_levels"] == []
    assert "custom-" + entry.id in catalog.known_provider_ids()
    assert catalog.provider_row("claude-api") is not None  # built-ins untouched


def test_plan_runs_stdout_as_plain_text() -> None:
    entry = custom_clis.create_custom_cli(
        "Headless One", "hl", headless_command="FOO=1 hl -p {prompt}"
    )
    plan = rc.plan_custom_cli(provider="custom-" + entry.id, prompt="hello", cwd=Path("."))
    assert plan.argv == ["/bin/hl", "-p", "hello"]
    assert plan.shape == "text" and plan.stdin_text is None
    assert plan.env["FOO"] == "1" and plan.vendor_session is None


def test_prompt_goes_to_stdin_without_placeholder() -> None:
    entry = custom_clis.create_custom_cli("Stdin", "sc", headless_command="sc --quiet")
    plan = rc.plan_custom_cli(provider="custom-" + entry.id, prompt="hello", cwd=Path("."))
    assert plan.argv == ["/bin/sc", "--quiet"] and plan.stdin_text == "hello"


def test_resume_template_used_with_the_session() -> None:
    entry = custom_clis.create_custom_cli(
        "Resumer",
        "rs",
        headless_command="rs -p {prompt}",
        headless_resume="rs -p {prompt} --resume {session}",
    )
    pid = "custom-" + entry.id
    first = rc.plan_custom_cli(provider=pid, prompt="a", cwd=Path("."))
    assert first.vendor_session and "--resume" not in first.argv
    second = rc.plan_custom_cli(
        provider=pid, prompt="b", cwd=Path("."), resume=first.vendor_session
    )
    assert second.argv[-2:] == ["--resume", first.vendor_session]


def test_missing_entry_or_binary_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(rc.CliUnavailable):
        rc.plan_custom_cli(provider="custom-gone", prompt="x", cwd=Path("."))
    entry = custom_clis.create_custom_cli("Nope", "nope", headless_command="nope {prompt}")
    monkeypatch.setattr(rc, "_which", lambda *names: None)
    with pytest.raises(rc.CliUnavailable):
        rc.plan_custom_cli(provider="custom-" + entry.id, prompt="x", cwd=Path("."))


def test_update_clears_the_spec() -> None:
    entry = custom_clis.create_custom_cli("U", "u", headless_command="u {prompt}")
    custom_clis.update_custom_cli(entry.id, headless_command="")
    assert catalog.custom_rows() == ()
