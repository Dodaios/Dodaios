"""An approved plan goes on in the access mode the person picked.

While Plan is on, a thread's permission pill names the mode Build returns to.
That mode lived only in the composer and in the app's memory, so the server
fell back to the runner's default; and Claude Code refused to switch a process
that started in Plan to "Bypass permissions", so every call of the building
turn became an approval card (live 2026-11-15). The session now keeps the
mode, the CLI starts with bypass on offer where the plan returns to it, and
the turn itself follows the switch.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios import claude_auth
from dodaios.agent_chat import permissions, turn_prompts
from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.tool_read_only import chat_is_read_only, set_chat_read_only
from dodaios.ui.web.agent_chat_routes import router as chat_router
from tests.unit.agent_chat.test_turn_prompts import _can_use, _fake_claude

# ------------------------------------------------------------------ the rule


@pytest.mark.parametrize(
    ("ladder", "mode", "build", "expected"),
    [
        # In Plan: the pill's mode, whatever it is.
        ("claude-cli", "plan", "bypassPermissions", "bypassPermissions"),
        ("claude-cli", "plan", "default", "default"),
        ("claude-cli", "plan", "auto", "auto"),
        ("codex-cli", "plan", "approve-for-me", "approve-for-me"),
        # Nothing recorded (a fork or a pane taken over before the mode travelled
        # with it): the ladder's lowest mode, never its default "bypass".
        ("claude-cli", "plan", "", "default"),
        ("codex-cli", "plan", "", "approve-for-me"),
        # A mode the ladder dropped folds onto the same stance, never onto more.
        ("claude-cli", "plan", "acceptEdits", "auto"),
        ("claude-cli", "plan", "dontAsk", "default"),
        # Plan is never where Build goes.
        ("claude-cli", "plan", "plan", "default"),
        # Not in Plan: the agent planned on its own, the person's pick stands.
        ("claude-cli", "default", "", "default"),
        ("claude-cli", "default", "bypassPermissions", "default"),
        ("claude-cli", "bypassPermissions", "default", "bypassPermissions"),
    ],
)
def test_where_an_approved_plan_goes_on(ladder: str, mode: str, build: str, expected: str) -> None:
    assert permissions.mode_after_plan(ladder, mode, build) == expected


# ------------------------------------------------------------------ the store


def _new(store: AgentChatStore, tmp_path: Path, mode: str, build: str = "") -> str:
    return store.create_session(
        provider="claude-api",
        model="",
        effort="",
        cwd=str(tmp_path),
        permission_mode=mode,
        build_mode=build,
        surface="agent",
    ).session_id


def test_a_thread_keeps_its_build_mode_across_an_app_restart(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    store = AgentChatStore(path)
    started_in_plan = _new(store, tmp_path, "plan", "default")
    switched = _new(store, tmp_path, "auto")
    store.update_session(switched, permission_mode="plan")
    store.close()

    reopened = AgentChatStore(path)
    assert reopened.get_session(started_in_plan).build_mode == "default"
    assert reopened.get_session(switched).build_mode == "auto"
    assert reopened.get_session(switched).to_dict()["build_mode"] == "auto"


def test_the_build_mode_follows_the_pill_and_ends_with_plan(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    sid = _new(store, tmp_path, "bypassPermissions")
    # Only a session in Plan has a mode to return to.
    assert store.get_session(sid).build_mode == ""
    assert store.get_session(_new(store, tmp_path, "default", "auto")).build_mode == ""

    store.update_session(sid, permission_mode="plan")
    assert store.get_session(sid).build_mode == "bypassPermissions"
    # A pick on the pill while Plan is on.
    store.update_session(sid, build_mode="default")
    assert store.get_session(sid).build_mode == "default"
    # Plan again (a provider change folds the mode onto itself): the pick stays.
    store.update_session(sid, permission_mode="plan")
    assert store.get_session(sid).build_mode == "default"
    # Entering Plan with the pill's mode named wins over the mode before.
    other = _new(store, tmp_path, "bypassPermissions")
    store.update_session(other, permission_mode="plan", build_mode="auto")
    assert store.get_session(other).build_mode == "auto"

    store.update_session(sid, permission_mode="default")
    assert store.get_session(sid).build_mode == ""
    # The next round of planning starts from the mode it now has.
    store.update_session(sid, permission_mode="plan")
    assert store.get_session(sid).build_mode == "default"


def test_a_database_from_an_older_build_gets_the_column(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    store = AgentChatStore(path)
    sid = _new(store, tmp_path, "plan", "default")
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE agent_chat_sessions DROP COLUMN build_mode")
    conn.commit()
    conn.close()

    reopened = AgentChatStore(path)
    session = reopened.get_session(sid)
    assert session.permission_mode == "plan" and session.build_mode == ""
    reopened.update_session(sid, build_mode="auto")
    assert reopened.get_session(sid).build_mode == "auto"


# ------------------------------------------------------------------ the service


async def _service(
    tmp_path: Path, *, mode: str, build: str = "", provider: str = "openai-codex"
) -> tuple[AgentChatService, str, list[str]]:
    svc = AgentChatService(AgentChatStore(":memory:"))
    session = svc.create_session(
        provider=provider,
        cwd=str(tmp_path),
        permission_mode=mode,
        build_mode=build,
        surface="agent",
    )
    sent: list[str] = []

    async def send(session_id: str, text: str, *_: Any, **__: Any) -> str:
        sent.append(text)
        return "next-turn"

    svc.send = send  # type: ignore[method-assign]
    return svc, session.session_id, sent


async def _finish_turn(svc: AgentChatService, sid: str, text: str, turn_id: str = "t1") -> None:
    await svc._emit(sid, make_event("turn_started", {"turn_id": turn_id}))
    await svc._emit(sid, make_event("assistant_text", {"turn_id": turn_id, "text": text}))
    await svc._emit(sid, make_event("turn_finished", {"turn_id": turn_id, "status": "done"}))


def _kinds(svc: AgentChatService, sid: str, kind: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in svc.store.list_events(sid) if e["kind"] == kind]


def test_a_new_thread_in_plan_takes_the_pill_s_mode(tmp_path: Path) -> None:
    svc = AgentChatService(AgentChatStore(":memory:"))

    # Codex: its runner, and so its ladder, is the same on every machine.
    def create(mode: str, build: str) -> Any:
        return svc.create_session(
            provider="openai-codex",
            cwd=str(tmp_path),
            permission_mode=mode,
            build_mode=build,
            surface="agent",
        )

    assert create("plan", "approve-for-me").build_mode == "approve-for-me"
    # A mode from another ladder folds onto the same stance, never onto more.
    assert create("plan", "acceptEdits").build_mode == "auto"
    assert create("plan", "default").build_mode == "approve-for-me"
    # Plan is no build mode, and a thread that does not plan has none.
    assert create("plan", "plan").build_mode == ""
    assert create("plan", "read-only").build_mode == ""
    assert create("auto", "full-access").build_mode == ""


def test_the_plan_card_offers_the_pill_s_mode_not_the_default(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _service(tmp_path, mode="plan", build="approve-for-me")
        await _finish_turn(svc, sid, "1. Add the table")
        await svc._open_turn_prompts(sid, "t1", "codex-cli")
        assert _kinds(svc, sid, "plan_ready") == [{"turn_id": "t1", "build_mode": "approve-for-me"}]

        assert await svc.resolve_turn_plan(sid, "t1", "build")
        session = svc.store.get_session(sid)
        assert (session.permission_mode, session.build_mode) == ("approve-for-me", "")
        assert sent == [turn_prompts.PLAN_GO_AHEAD]

    asyncio.run(scenario())


def test_build_goes_to_the_pill_as_it_is_when_the_person_clicks(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, _ = await _service(tmp_path, mode="plan", build="full-access")
        await _finish_turn(svc, sid, "1. Add the table")
        await svc._open_turn_prompts(sid, "t1", "codex-cli")
        # The person lowers the pill after the card opened.
        svc.store.update_session(sid, build_mode="auto")
        assert await svc.resolve_turn_plan(sid, "t1", "build")
        assert svc.store.get_session(sid).permission_mode == "auto"

    asyncio.run(scenario())


def test_build_leaves_a_thread_alone_that_already_left_plan(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc, sid, sent = await _service(tmp_path, mode="plan", build="full-access")
        await _finish_turn(svc, sid, "1. Add the table")
        await svc._open_turn_prompts(sid, "t1", "codex-cli")
        # Plan switched off by hand, to a lower mode than the card named.
        svc.store.update_session(sid, permission_mode="approve-for-me")
        assert await svc.resolve_turn_plan(sid, "t1", "build")
        assert svc.store.get_session(sid).permission_mode == "approve-for-me"
        assert _kinds(svc, sid, "session_updated") == []
        assert sent == [turn_prompts.PLAN_GO_AHEAD]

    asyncio.run(scenario())


# ------------------------------------------------------------------ the routes


def _chat_app(tmp_path: Path) -> tuple[FastAPI, AgentChatService]:
    service = AgentChatService(
        AgentChatStore(tmp_path / "db.sqlite"), default_cwd=lambda *_: str(tmp_path)
    )
    app = FastAPI()
    app.include_router(chat_router)
    app.state.agent_chat = service
    return app, service


def test_the_composer_tells_the_thread_where_build_returns_to(tmp_path: Path) -> None:
    app, service = _chat_app(tmp_path)
    with TestClient(app) as client:
        # Codex: its runner, and so its ladder, is the same on every machine.
        created = client.post(
            "/api/agent-chat/sessions",
            json={
                "provider": "openai-codex",
                "cwd": str(tmp_path),
                "permission_mode": "plan",
                "build_mode": "approve-for-me",
                "surface": "agent",
            },
        )
        assert created.status_code == 201, created.text
        sid = created.json()["session_id"]
        assert created.json()["build_mode"] == "approve-for-me"

        # A pick on the pill while Plan is on reaches the session.
        url = f"/api/agent-chat/sessions/{sid}"
        picked = client.patch(url, json={"build_mode": "full-access"}).json()
        assert (picked["permission_mode"], picked["build_mode"]) == ("plan", "full-access")
        assert _events(service, sid)[-1] == {"build_mode": "full-access"}

        # Plan off: the thread is in the pill's mode and has nothing to return to.
        off = client.patch(url, json={"permission_mode": "full-access"}).json()
        assert (off["permission_mode"], off["build_mode"]) == ("full-access", "")
        assert _events(service, sid)[-1] == {"permission_mode": "full-access", "build_mode": ""}
        # Outside Plan a build mode means nothing and is not kept.
        ignored = client.patch(url, json={"build_mode": "approve-for-me"}).json()
        assert (ignored["permission_mode"], ignored["build_mode"]) == ("full-access", "")

        # Plan on: the mode it had is where Build returns to, and the composer hears it.
        on = client.patch(url, json={"permission_mode": "plan"}).json()
        assert (on["permission_mode"], on["build_mode"]) == ("plan", "full-access")
        assert _events(service, sid)[-1] == {"permission_mode": "plan", "build_mode": "full-access"}
        # Plan on together with the pill's mode.
        client.patch(url, json={"permission_mode": "approve-for-me"})
        both = client.patch(url, json={"permission_mode": "plan", "build_mode": "auto"}).json()
        assert (both["permission_mode"], both["build_mode"]) == ("plan", "auto")


def _events(service: AgentChatService, sid: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in service.store.list_events(sid) if e["kind"] == "session_updated"]


# ------------------------------------------------------------------ the running turn


def _claude_thread_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requests: list[dict[str, Any]],
    *,
    mode: str,
    build: str = "",
    on_plan_card: Any = None,
) -> tuple[list[dict[str, Any]], list[str], AgentChatStore, str, list[dict[str, Any]]]:
    """One Claude Code turn of a thread held in a real store; the plan card says Build."""
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
    store = AgentChatStore(":memory:")
    sid = _new(store, tmp_path, mode, build)
    asked: list[str] = []
    events: list[dict[str, Any]] = []

    async def emit(ev: dict[str, Any]) -> None:
        events.append(ev)

    async def ask(_call_id: str, name: str, *_: object) -> str:
        asked.append(name)
        if name == "ExitPlanMode" and on_plan_card is not None:
            on_plan_card(store, sid)
        return "allow"

    handle = TurnHandle(
        session=store.get_session(sid),
        turn_id="t1",
        emit=emit,
        request_approval=ask,
        cancel=asyncio.Event(),
        control_service=SimpleNamespace(store=store),
    )
    # The service marks a planning chat read-only when its turn starts.
    set_chat_read_only(sid, mode == "plan")
    try:
        asyncio.run(rc.run_cli_turn(handle, "hi", "claude-cli"))
        read_only = chat_is_read_only(sid)
    finally:
        set_chat_read_only(sid, False)
    answers = json.loads(out.read_text(encoding="utf-8"))
    assert not read_only or store.get_session(sid).permission_mode == "plan"
    return answers, asked, store, sid, events


_BUILDING = [
    _can_use("ExitPlanMode", {"plan": "1. Do it"}, "r1"),
    _can_use("Bash", {"command": "git worktree add ../fix"}, "r2"),
    _can_use("Edit", {"file_path": "a.py", "old_string": "a", "new_string": "b"}, "r3"),
]


def _set_mode(mode: str) -> list[dict[str, str]]:
    return [{"type": "setMode", "mode": mode, "destination": "session"}]


def test_after_an_approved_plan_a_bypass_thread_asks_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Live 2026-11-15: a thread started in Plan with the pill on "Bypass
    # permissions". Claude Code did not take the switch and asked about every
    # command and edit of the building turn; six approval cards followed.
    answers, asked, store, sid, events = _claude_thread_turn(
        monkeypatch, tmp_path, _BUILDING, mode="plan", build="bypassPermissions"
    )
    assert asked == ["ExitPlanMode"]
    assert [a["behavior"] for a in answers] == ["allow", "allow", "allow"]
    assert answers[0]["updatedPermissions"] == _set_mode("bypassPermissions")
    session = store.get_session(sid)
    assert (session.permission_mode, session.build_mode) == ("bypassPermissions", "")
    assert {"permission_mode": "bypassPermissions"} in [
        e["payload"] for e in events if e["kind"] == "session_updated"
    ]


def test_an_approved_plan_returns_to_the_pill_s_mode_not_to_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # "Ask before edits" with Plan on must not come out as "Bypass permissions".
    answers, asked, store, sid, _ = _claude_thread_turn(
        monkeypatch, tmp_path, _BUILDING, mode="plan", build="default"
    )
    assert answers[0]["updatedPermissions"] == _set_mode("default")
    assert asked == ["ExitPlanMode", "Bash", "Edit"]
    assert store.get_session(sid).permission_mode == "default"


def test_a_pick_made_while_the_plan_was_written_decides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    answers, asked, store, sid, _ = _claude_thread_turn(
        monkeypatch,
        tmp_path,
        _BUILDING,
        mode="plan",
        build="bypassPermissions",
        on_plan_card=lambda store, sid: store.update_session(sid, build_mode="default"),
    )
    assert answers[0]["updatedPermissions"] == _set_mode("default")
    assert asked == ["ExitPlanMode", "Bash", "Edit"]
    assert store.get_session(sid).permission_mode == "default"


@pytest.mark.parametrize(
    ("mode", "asked_after"),
    [("default", ["Bash", "Edit"]), ("bypassPermissions", [])],
)
def test_a_plan_the_agent_started_on_its_own_never_changes_the_thread_s_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, asked_after: list[str]
) -> None:
    # The thread was never switched to Plan: the model called EnterPlanMode.
    # Its approved plan used to move an "Ask before edits" thread to the
    # runner's default, "Bypass permissions".
    answers, asked, store, sid, events = _claude_thread_turn(
        monkeypatch, tmp_path, _BUILDING, mode=mode
    )
    assert answers[0]["updatedPermissions"] == _set_mode(mode)
    assert asked == ["ExitPlanMode", *asked_after]
    assert store.get_session(sid).permission_mode == mode
    assert [e for e in events if e["kind"] == "session_updated"] == []


# ------------------------------------------------------------------ the CLI's start


def _argv(mode: str) -> list[str]:
    return ["claude", "--print", "--permission-mode", mode, "--model", "opus"]


def _thread(mode: str, build: str = "", surface: str = "agent") -> SimpleNamespace:
    return SimpleNamespace(permission_mode=mode, build_mode=build, surface=surface)


@pytest.fixture
def cli_offers_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rc, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(claude_auth, "claude_cli_allow_bypass_known", lambda prefix: True)
    monkeypatch.setattr(rc, "_claude_refuses_bypass_here", lambda: False)


def test_a_planning_thread_that_returns_to_bypass_starts_with_bypass_on_offer(
    cli_offers_bypass: None,
) -> None:
    argv = _argv("plan")
    rc.allow_bypass_after_plan(argv, "claude-cli", _thread("plan", "bypassPermissions"))
    assert argv[-1] == rc.CLAUDE_ALLOW_BYPASS_FLAG
    # Once is enough.
    rc.allow_bypass_after_plan(argv, "claude-cli", _thread("plan", "bypassPermissions"))
    assert argv.count(rc.CLAUDE_ALLOW_BYPASS_FLAG) == 1
    # GLM's ladder too.
    argv = _argv("plan")
    rc.allow_bypass_after_plan(argv, "glm-cli", _thread("plan", "bypassPermissions"))
    assert rc.CLAUDE_ALLOW_BYPASS_FLAG in argv


@pytest.mark.parametrize(
    ("runner", "started_in", "thread"),
    [
        # The plan returns to a mode that asks: bypass is not offered.
        ("claude-cli", "plan", _thread("plan", "default")),
        ("claude-cli", "plan", _thread("plan", "auto")),
        ("glm-cli", "plan", _thread("plan", "acceptEdits")),
        # Nothing recorded: the plan goes on in the lowest mode, not in bypass.
        ("claude-cli", "plan", _thread("plan")),
        ("glm-cli", "plan", _thread("plan")),
        # Not a planning turn.
        ("claude-cli", "default", _thread("default")),
        ("claude-cli", "bypassPermissions", _thread("bypassPermissions")),
        # Another chat's plan approval names no mode, and another CLI has no such flag.
        ("claude-cli", "plan", _thread("plan", "bypass", surface="jarvis")),
        ("codex-cli", "plan", _thread("plan", "full-access")),
    ],
)
def test_bypass_is_offered_to_no_other_turn(
    cli_offers_bypass: None, runner: str, started_in: str, thread: SimpleNamespace
) -> None:
    argv = _argv(started_in)
    rc.allow_bypass_after_plan(argv, runner, thread)
    assert argv == _argv(started_in)


def test_a_cli_that_would_not_start_with_the_offer_is_left_without_it(
    monkeypatch: pytest.MonkeyPatch, cli_offers_bypass: None
) -> None:
    thread = _thread("plan", "bypassPermissions")
    # An older CLI does not know the flag.
    monkeypatch.setattr(claude_auth, "claude_cli_allow_bypass_known", lambda prefix: False)
    argv = _argv("plan")
    rc.allow_bypass_after_plan(argv, "claude-cli", thread)
    assert argv == _argv("plan")
    # Root outside a sandbox: Claude Code exits instead of offering bypass.
    monkeypatch.setattr(claude_auth, "claude_cli_allow_bypass_known", lambda prefix: True)
    monkeypatch.setattr(rc, "_claude_refuses_bypass_here", lambda: True)
    rc.allow_bypass_after_plan(argv, "claude-cli", thread)
    assert argv == _argv("plan")

    # No CLI at all: planning reports that, not this.
    def missing() -> list[str]:
        raise rc.CliUnavailable("not installed")

    monkeypatch.setattr(rc, "_claude_refuses_bypass_here", lambda: False)
    monkeypatch.setattr(rc, "claude_argv_prefix", missing)
    rc.allow_bypass_after_plan(argv, "claude-cli", thread)
    assert argv == _argv("plan")


def test_root_outside_a_sandbox_is_where_claude_code_refuses_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IS_SANDBOX", raising=False)
    monkeypatch.setattr(rc.os, "geteuid", lambda: 0, raising=False)
    assert rc._claude_refuses_bypass_here() is True
    monkeypatch.setenv("IS_SANDBOX", "1")
    assert rc._claude_refuses_bypass_here() is False
    monkeypatch.delenv("IS_SANDBOX")
    monkeypatch.setattr(rc.os, "geteuid", lambda: 501, raising=False)
    assert rc._claude_refuses_bypass_here() is False
