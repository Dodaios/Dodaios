"""The code builder's seat (which CLI may run on the plan) and idle detection."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli
from dodaios.self_build.code import idle, seat

# ------------------------------------------------------------------ Codex on the plan


def _codex_home(tmp_path: Path, auth: dict[str, Any], config: str = "") -> Path:
    home = tmp_path / ".codex"
    home.mkdir(parents=True)
    (home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    if config:
        (home / "config.toml").write_text(config, encoding="utf-8")
    return home


PLAN_AUTH: dict[str, Any] = {
    "auth_mode": "chatgpt",
    "OPENAI_API_KEY": None,
    "tokens": {"access_token": "a", "refresh_token": "r", "id_token": "x.y.z"},
}


def test_codex_plan_login_is_strict(tmp_path: Path) -> None:
    assert seat.codex_plan_login(_codex_home(tmp_path / "a", PLAN_AUTH))
    # No auth_mode field (older CLIs) with ChatGPT tokens is still the plan.
    legacy = {k: v for k, v in PLAN_AUTH.items() if k != "auth_mode"}
    assert seat.codex_plan_login(_codex_home(tmp_path / "b", legacy))
    # A stored API key, an API auth mode, or no tokens: not the plan.
    assert not seat.codex_plan_login(
        _codex_home(tmp_path / "c", {**PLAN_AUTH, "OPENAI_API_KEY": "sk-stored"})
    )
    api_mode = {**PLAN_AUTH, "auth_mode": "apikey"}
    assert not seat.codex_plan_login(_codex_home(tmp_path / "d", api_mode))
    assert not seat.codex_plan_login(_codex_home(tmp_path / "e", {"auth_mode": "chatgpt"}))
    assert not seat.codex_plan_login(tmp_path / "missing")
    # config.toml forcing the API login at the top level wins; inside a profile it does not.
    assert not seat.codex_plan_login(
        _codex_home(tmp_path / "f", PLAN_AUTH, 'model = "x"\nforced_login_method = "api"\n')
    )
    assert seat.codex_plan_login(
        _codex_home(
            tmp_path / "g",
            PLAN_AUTH,
            'model = "x"\n[profiles.local]\nforced_login_method = "api"\n',
        )
    )


def _one_row(monkeypatch: pytest.MonkeyPatch, *, runner: str, agent: str, label: str) -> None:
    from dodaios.brain import background_policy

    row = SimpleNamespace(id=f"{agent}-row", agent=agent, label=label)
    monkeypatch.setattr(seat, "_rows", lambda: [row])
    monkeypatch.setattr(
        "dodaios.agent_chat.service.resolve_runner", lambda provider, surface="agent": runner
    )
    monkeypatch.setattr(seat, "_cooling", lambda r: False)
    monkeypatch.setattr(seat, "_window_full", lambda platform: False)
    monkeypatch.setattr(background_policy, "login_state", lambda provider: True)


def test_codex_with_a_key_in_the_app_runs_on_the_plan_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _one_row(monkeypatch, runner="codex-cli", agent="codex", label="Codex")
    home = _codex_home(tmp_path, PLAN_AUTH)
    monkeypatch.setattr(seat, "_codex_home", lambda: home)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-app")
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    chosen, why = seat.choose({"codex": True})
    assert chosen is not None, why
    assert set(chosen.drop_env) == {"OPENAI_API_KEY", "CODEX_API_KEY"}
    # The app's own environment is untouched.
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-app"


def test_codex_without_a_plan_login_is_still_skipped_while_a_key_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _one_row(monkeypatch, runner="codex-cli", agent="codex", label="Codex")
    home = _codex_home(tmp_path, {**PLAN_AUTH, "OPENAI_API_KEY": "sk-stored"})
    monkeypatch.setattr(seat, "_codex_home", lambda: home)
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    chosen, why = seat.choose({"codex": True})
    assert chosen is None and "API key" in why
    monkeypatch.delenv("CODEX_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    chosen, _ = seat.choose({"codex": True})
    assert chosen is not None and chosen.drop_env == ()


def test_claude_with_a_key_in_the_environment_is_still_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _one_row(monkeypatch, runner="claude-cli", agent="claude", label="Claude Code")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    chosen, why = seat.choose({"claude": True})
    assert chosen is None and "API key" in why


def test_child_env_drops_apply_to_that_session_only() -> None:
    runner_cli.drop_child_env("s1", ("OPENAI_API_KEY", "CODEX_API_KEY"))
    try:
        env = {"OPENAI_API_KEY": "k", "codex_api_key": "k2", "PATH": "/bin"}
        runner_cli.apply_child_env_drops("s1", env)
        assert env == {"PATH": "/bin"}  # case-insensitive, like Windows' environment
        other = {"OPENAI_API_KEY": "k"}
        runner_cli.apply_child_env_drops("s2", other)
        assert other == {"OPENAI_API_KEY": "k"}
    finally:
        runner_cli.release_child_env("s1")
    env = {"OPENAI_API_KEY": "k"}
    runner_cli.apply_child_env_drops("s1", env)
    assert env == {"OPENAI_API_KEY": "k"}


def test_thread_runner_strips_the_key_while_its_run_lasts(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.self_build.code.runner import ThreadRunner

    monkeypatch.setattr(
        "dodaios.agent_chat.service.resolve_runner", lambda provider, surface="agent": "codex-cli"
    )
    seen: dict[str, Any] = {}

    class Chat:
        store = SimpleNamespace(
            list_events=lambda sid, tail=None: [
                {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": "done"}},
                {"kind": "turn_finished", "payload": {"turn_id": "t1", "status": "done"}},
            ]
        )

        def create_session(self, **kwargs: Any) -> Any:
            return SimpleNamespace(session_id="s7")

        async def send(self, sid: str, text: str, *, author: dict[str, str]) -> str:
            env = {"OPENAI_API_KEY": "sk-app", "HOME": "/h"}
            runner_cli.apply_child_env_drops(sid, env)  # what the turn's planner does
            seen["env"] = env
            return "t1"

        def is_running(self, sid: str) -> bool:
            return False

    result = asyncio.run(
        ThreadRunner(lambda: Chat()).run(
            provider="codex",
            folder="/w",
            prompt="p",
            title="t",
            timeout_s=60,
            should_stop=lambda: False,
            drop_env=("OPENAI_API_KEY", "CODEX_API_KEY"),
        )
    )
    assert result.ok
    assert seen["env"] == {"HOME": "/h"}
    assert "s7" not in runner_cli._CHILD_ENV_DROPS  # released after the run


# ------------------------------------------------------------------ idle detection


def _fake(outputs: dict[str, str | None]) -> Any:
    calls: list[list[str]] = []

    def run(argv: list[str]) -> str | None:
        calls.append(argv)
        joined = " ".join(argv)
        for needle, out in outputs.items():
            if needle in joined:
                return out
        return None

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_macos_reads_hid_idle_time_from_its_own_line() -> None:
    out = (
        "+-o Root  <class IORegistryEntry, id 0x100000100, retain 26>\n"
        "  +-o IOHIDSystem  <class IOHIDSystem, id 0x100000465, registered, matched, "
        "active, busy 0 (0 ms), retain 39>\n"
        "      {\n"
        '        "HIDIdleTime" = 1200000000000\n'
        "      }\n"
    )
    run = _fake({"ioreg": out})
    assert idle.os_idle_s(platform="darwin", run=run) == 1200.0
    assert run.calls[0][:3] == ["ioreg", "-c", "IOHIDSystem"]
    assert idle.os_idle_s(platform="darwin", run=_fake({})) is None


def test_linux_gnome_idle_monitor_over_gdbus_or_dbus_send() -> None:
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    run = _fake({"gdbus call --session --dest org.gnome.Mutter.IdleMonitor": "(uint64 905000,)\n"})
    assert idle.os_idle_s(platform="linux", run=run, env=env) == 905.0
    run = _fake(
        {
            "dbus-send --session --print-reply --dest=org.gnome.Mutter.IdleMonitor": (
                "method return time=1.2 sender=:1.5 -> destination=:1.9 serial=7 "
                "reply_serial=2\n   uint64 61000\n"
            )
        }
    )
    assert idle.os_idle_s(platform="linux", run=run, env=env) == 61.0


def test_linux_xprintidle_only_outside_wayland() -> None:
    run = _fake({"xprintidle": "1800000\n"})
    assert idle.os_idle_s(platform="linux", run=run, env={"DISPLAY": ":0"}) == 1800.0
    # Under Wayland xprintidle sees only X clients: never asked.
    run = _fake({"xprintidle": "1800000\n"})
    env = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "wayland"}
    assert idle.os_idle_s(platform="linux", run=run, env=env) is None
    assert not any(argv[0] == "xprintidle" for argv in run.calls)


def test_linux_screensaver_active_time_is_a_lower_bound() -> None:
    run = _fake(
        {
            "ScreenSaver.GetActiveTime": "(uint32 1300,)\n",
            "ScreenSaver.GetActive": "(true,)\n",
        }
    )
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    assert idle.os_idle_s(platform="linux", run=run, env=env) == 1300.0
    # Not active: no reading from the screen saver (the person may be typing).
    run = _fake({"ScreenSaver.GetActive": "(false,)\n"})
    assert idle.os_idle_s(platform="linux", run=run, env=env) is None


def test_linux_logind_idle_hint() -> None:
    now = 2_000_000.0
    since_us = int((now - 1000.0) * 1e6)
    run = _fake({"loginctl": f"IdleHint=yes\nIdleSinceHint={since_us}\n"})
    env = {"XDG_SESSION_ID": "c2"}
    assert idle.os_idle_s(platform="linux", run=run, env=env, now=now) == pytest.approx(1000.0)
    assert run.calls[-1][:3] == ["loginctl", "show-session", "c2"]
    # "no" is what desktops that never set the hint say too: unknown, not "busy".
    run = _fake({"loginctl": "IdleHint=no\nIdleSinceHint=0\n"})
    assert idle.os_idle_s(platform="linux", run=run, env=env, now=now) is None


def test_linux_without_any_reading_leaves_it_to_the_ide(monkeypatch: pytest.MonkeyPatch) -> None:
    assert idle.os_idle_s(platform="linux", run=_fake({}), env={}) is None
    monkeypatch.setattr(idle, "os_idle_s", lambda: None)
    monkeypatch.setattr(idle, "dodaios_idle_s", lambda: None)
    monkeypatch.setattr(idle, "ide_idle_s", lambda: None)
    assert idle.person_idle()
    monkeypatch.setattr(idle, "ide_idle_s", lambda: 30.0)
    assert not idle.person_idle()


# ------------------------------------------------------------------ the GitHub account


def test_viewer_without_read_org_still_knows_the_person(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.agentic_ide import github_link
    from dodaios.self_build.code.github import GitHubApi

    def graphql(token: str, query: str, variables: Any = None) -> dict[str, Any]:
        if "organizations" in query:
            # What GitHub answers a token from the in-app connection (no read:org).
            raise github_link.GitHubError("GitHub could not answer this request.")
        return {"data": {"viewer": {"login": "me"}}}

    monkeypatch.setattr(github_link, "graphql", graphql)
    who = GitHubApi("t").viewer()
    assert who.login == "me" and who.admin_orgs == frozenset()
    assert who.owns("me/proj") and not who.owns("some-org/proj")

    def with_orgs(token: str, query: str, variables: Any = None) -> dict[str, Any]:
        if "organizations" in query:
            nodes = [
                {"login": "Org", "viewerCanAdminister": True},
                {"login": "other", "viewerCanAdminister": False},
            ]
            return {"data": {"viewer": {"organizations": {"nodes": nodes}}}}
        return {"data": {"viewer": {"login": "me"}}}

    monkeypatch.setattr(github_link, "graphql", with_orgs)
    assert GitHubApi("t").viewer().admin_orgs == frozenset({"org"})


# ------------------------------------------------------------------ the pull request text


def test_pull_request_text_carries_no_local_paths() -> None:
    from dodaios.self_build.code.builder import scrub

    worktree = r"C:\Users\me\proj\.worktrees\dodaios-issue-1-x"
    text = (
        rf"Edited {worktree}\calc.py and ran (`C:\Program Files\Python311\python.exe -m pytest`)."
        "\nAlso see /home/me/proj/notes.txt and /Users/me/x.\nKept `tests/test_calc.py`."
    )
    out = scrub(text, worktree)
    assert "Edited calc.py" in out
    assert "Program Files" not in out and "Python311" not in out
    assert "/home/me" not in out and "/Users/me" not in out
    assert "`tests/test_calc.py`" in out  # repository paths stay


def test_leftover_worktree_folder_goes_only_when_it_holds_caches(tmp_path: Path) -> None:
    from dodaios.self_build.code.builder import _drop_if_empty, _sweep

    parent = tmp_path / ".worktrees"
    left = parent / "dodaios-issue-1-x"
    (left / "tests" / "__pycache__").mkdir(parents=True)
    (left / "tests" / "__pycache__" / "test_calc.pyc").write_bytes(b"x")
    (left / "__pycache__").mkdir()
    _sweep(left)
    _drop_if_empty(parent)
    assert not left.exists() and not parent.exists()

    kept = parent / "dodaios-issue-2-y"
    kept.mkdir(parents=True)
    (kept / "notes.txt").write_text("the person's", encoding="utf-8")
    _sweep(kept)
    _drop_if_empty(parent)
    assert (kept / "notes.txt").exists()


def test_summary_is_the_agents_closing_message() -> None:
    from dodaios.self_build.code.runner import final_message

    events = [
        {"kind": "assistant_text", "payload": {"turn_id": "t0", "text": "old turn"}},
        {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": "I'll inspect first."}},
        {"kind": "tool_call", "payload": {"turn_id": "t1", "name": "edit"}},
        {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": "Added neg() and a test."}},
        {"kind": "assistant_text", "payload": {"turn_id": "t1", "text": "  "}},
        {"kind": "turn_finished", "payload": {"turn_id": "t1", "status": "done"}},
    ]
    assert final_message(events, "t1") == "Added neg() and a test."
    assert final_message(events, "t9") == ""


def test_sweep_retries_while_a_file_is_still_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from dodaios.self_build.code.builder import _sweep

    left = tmp_path / ".worktrees" / "dodaios-issue-1-x"
    (left / "__pycache__").mkdir(parents=True)
    (left / "__pycache__" / "calc.pyc").write_bytes(b"x")
    real = shutil.rmtree
    calls: list[int] = []

    def flaky(path: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("in use")
        real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    _sweep(left, pause_s=0)
    assert not left.exists() and len(calls) == 2


def test_git_calls_survive_deep_windows_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live: a worktree 213 characters deep made ``git diff base..HEAD`` fail with
    "Filename too long" (git also stats the range as a path) and left the worktree
    behind on removal. Every loop git call allows long paths, and the range is
    marked as a revision with ``--``."""
    from dodaios.self_build.code import builder, gitcmd

    seen: list[list[str]] = []

    def run(argv: list[str], cwd: Any, *, timeout: float = 0, env: Any = None) -> Any:
        seen.append(list(argv))
        if argv[-1] == "--abbrev-ref" or "--abbrev-ref" in argv:
            return gitcmd.Result(0, "dodaios/issue-1-x\n", "")
        if "--quiet" in argv:
            return gitcmd.Result(0, "", "")
        return gitcmd.Result(0, "calc.py\n", "")

    monkeypatch.setattr(gitcmd, "run", run)
    assert builder.collect("/w", "dodaios/issue-1-x", "abc", "fix: x") == ["calc.py"]
    assert all(
        argv[:5] == ["git", "-c", "core.quotepath=off", "-c", "core.longpaths=true"]
        for argv in seen
    )
    diff = next(argv for argv in seen if "--name-only" in argv)
    assert diff[-2:] == ["abc..HEAD", "--"]
