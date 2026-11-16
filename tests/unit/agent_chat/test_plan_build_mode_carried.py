"""An approved plan, or a runner switch, never grants more than the person picked.

Found by the bug scan of 2026-11-16 (v5.5.0):

* A forked thread, or one taken over from a grid pane, did not carry the mode
  its plan goes on in (``build_mode``). Approving the plan fell back to the
  ladder's default, which is "bypass" on every coding ladder, while the
  permission pill named another mode (for example "Ask").
* Switching a thread's runner folded Claude Code's "Auto" (stance 2: routine
  yes, risky asks) as if it were full access, so on GLM or Grok it became
  ``bypassPermissions``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import permissions
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web import agent_chat_routes

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AgentChatService]:
    # Claude Code is "installed" and the agents' Claude runs on it, on any machine.
    monkeypatch.setattr("dodaios.agent_chat.service._claude_cli_installed", lambda: True)
    monkeypatch.setattr(
        "dodaios.agent_chat.agent_provider_prefs.forces_api", lambda *_a, **_k: False
    )
    service = AgentChatService(
        AgentChatStore(tmp_path / "chat.db"), default_cwd=lambda *_: str(tmp_path)
    )
    sent: list[str] = []

    async def send(session_id: str, text: str, *_: Any, **__: Any) -> str:
        sent.append(text)
        return "next-turn"

    service.send = send  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(agent_chat_routes.router)
    app.state.agent_chat = service
    return TestClient(app), service


def _plan_card(svc: AgentChatService, sid: str, runner: str) -> None:
    async def scenario() -> None:
        for kind, payload in (
            ("turn_started", {"turn_id": "t1"}),
            ("assistant_text", {"turn_id": "t1", "text": "1. Add the table"}),
            ("turn_finished", {"turn_id": "t1", "status": "done"}),
        ):
            await svc._emit(sid, make_event(kind, payload))
        await svc._open_turn_prompts(sid, "t1", runner)

    asyncio.run(scenario())


def _cards(svc: AgentChatService, sid: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in svc.store.list_events(sid) if e["kind"] == "plan_ready"]


# ------------------------------------------------------------------ the rule


@pytest.mark.parametrize(
    ("ladder", "lowest"),
    [
        ("claude-cli", "default"),
        ("glm-cli", "default"),
        ("codex-cli", "approve-for-me"),
        ("grok-cli", "default"),
        ("opencode-cli", "default"),
        ("agy-cli", "accept-edits"),
        ("api", "ask"),
        (permissions.JARVIS_LADDER, "ask"),
    ],
)
def test_a_plan_with_no_recorded_mode_goes_on_in_the_lowest_one(ladder: str, lowest: str) -> None:
    assert permissions.mode_after_plan(ladder, "plan", "") == lowest
    assert permissions.mode_after_plan(ladder, "plan", "plan") == lowest


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        # Claude Code's Auto is stance 2: the same stance where the target has
        # it, else the next LOWER one, never everything.
        ("claude-cli", "glm-cli", "acceptEdits"),
        ("claude-cli", "grok-cli", "default"),
        ("claude-cli", "opencode-cli", "default"),
        ("claude-cli", "api", "accept-edits"),
        ("claude-cli", "codex-cli", "auto"),
        ("codex-cli", "claude-cli", "auto"),
        # A word that means full access where it came from stays full access.
        ("opencode-cli", "claude-cli", "bypassPermissions"),
        ("api", "grok-cli", "bypassPermissions"),
    ],
)
def test_a_runner_switch_folds_auto_by_what_it_meant(
    source: str, target: str, expected: str
) -> None:
    folded = permissions.normalize_permission(target, "auto", source=source)
    assert folded == expected
    assert permissions.stance_of(folded) <= 3
    # Never above the stance the mode had where it was picked.
    assert permissions._stance(target, folded) <= permissions._stance(source, "auto")


def test_auto_from_an_unknown_runner_counts_as_its_lowest_reading() -> None:
    assert permissions.normalize_permission("grok-cli", "auto") == "default"
    assert permissions.normalize_permission("glm-cli", "auto") == "acceptEdits"
    # A mode the runner offers itself still passes through.
    assert permissions.normalize_permission("opencode-cli", "auto") == "auto"


# ------------------------------------------------------------------ fork


def test_a_fork_keeps_the_mode_its_plan_goes_on_in(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    src = svc.create_session(
        provider="openai-codex",
        permission_mode="plan",
        build_mode="approve-for-me",
        surface="agent",
    )
    res = http.post(f"/api/agent-chat/sessions/{src.session_id}/fork", json={})
    assert res.status_code == 201
    copy = res.json()["session_id"]
    assert svc.store.get_session(copy).build_mode == "approve-for-me"

    _plan_card(svc, copy, "codex-cli")
    assert _cards(svc, copy)[0]["build_mode"] == "approve-for-me"
    assert asyncio.run(svc.resolve_turn_plan(copy, "t1", "build"))
    assert svc.store.get_session(copy).permission_mode == "approve-for-me"


def test_a_fork_of_a_thread_without_a_recorded_mode_never_builds_in_bypass(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    src = svc.create_session(provider="claude-api", permission_mode="plan", surface="agent")
    assert src.build_mode == ""
    copy = http.post(f"/api/agent-chat/sessions/{src.session_id}/fork", json={}).json()[
        "session_id"
    ]

    _plan_card(svc, copy, "claude-cli")
    assert _cards(svc, copy)[0]["build_mode"] == "default"
    assert asyncio.run(svc.resolve_turn_plan(copy, "t1", "build"))
    assert svc.store.get_session(copy).permission_mode == "default"


# ------------------------------------------------------------------ pane -> thread


def _pane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, mode: str) -> None:
    term = SimpleNamespace(
        agent="codex",
        resume=SimpleNamespace(id=UUID),
        model="",
        effort="",
        permission_mode=mode,
        account="",
        cwd=lambda folder: str(tmp_path),
    )
    workspace = SimpleNamespace(folder=str(tmp_path))
    registry = SimpleNamespace(_locate=lambda name, workspace_id: (workspace, term))
    monkeypatch.setattr("dodaios.agentic_ide.session.get_registry", lambda: registry)


def test_a_thread_from_a_planning_pane_never_builds_in_the_default(
    chat: tuple[TestClient, AgentChatService], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    http, svc = chat
    _pane(monkeypatch, tmp_path, mode="plan")
    res = http.post("/api/agent-chat/sessions/from-terminal", json={"name": "C1"})
    assert res.status_code == 201
    sid = res.json()["session_id"]
    assert svc.store.get_session(sid).permission_mode == "plan"

    _plan_card(svc, sid, "codex-cli")
    assert _cards(svc, sid)[0]["build_mode"] == "approve-for-me"
    assert asyncio.run(svc.resolve_turn_plan(sid, "t1", "build"))
    assert svc.store.get_session(sid).permission_mode == "approve-for-me"


def test_a_thread_from_a_planning_pane_takes_the_pane_s_pill(
    chat: tuple[TestClient, AgentChatService], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    http, svc = chat
    _pane(monkeypatch, tmp_path, mode="plan")
    res = http.post(
        "/api/agent-chat/sessions/from-terminal", json={"name": "C1", "build_mode": "auto"}
    )
    assert svc.store.get_session(res.json()["session_id"]).build_mode == "auto"


# ------------------------------------------------------------------ the pill decides


def test_build_goes_on_in_the_mode_the_card_names(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    sid = svc.create_session(
        provider="openai-codex", permission_mode="plan", surface="agent"
    ).session_id
    _plan_card(svc, sid, "codex-cli")
    res = http.post(
        f"/api/agent-chat/sessions/{sid}/plan",
        json={"turn_id": "t1", "decision": "build", "build_mode": "auto"},
    )
    assert res.status_code == 200
    assert svc.store.get_session(sid).permission_mode == "auto"


def test_a_mode_the_ladder_does_not_offer_is_ignored(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    sid = svc.create_session(
        provider="openai-codex", permission_mode="plan", surface="agent"
    ).session_id
    _plan_card(svc, sid, "codex-cli")
    res = http.post(
        f"/api/agent-chat/sessions/{sid}/plan",
        json={"turn_id": "t1", "decision": "build", "build_mode": "bypassPermissions"},
    )
    assert res.status_code == 200
    assert svc.store.get_session(sid).permission_mode == "approve-for-me"


# ------------------------------------------------------------------ runner switch


def test_switching_claude_auto_to_glm_keeps_the_middle_step(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    sid = svc.create_session(
        provider="claude-api", permission_mode="auto", surface="agent"
    ).session_id
    res = http.patch(f"/api/agent-chat/sessions/{sid}", json={"provider": "glm"})
    assert res.status_code == 200, res.text
    assert svc.store.get_session(sid).permission_mode == "acceptEdits"


def test_switching_claude_auto_to_grok_asks(chat: tuple[TestClient, AgentChatService]) -> None:
    http, svc = chat
    sid = svc.create_session(
        provider="claude-api", permission_mode="auto", surface="agent"
    ).session_id
    res = http.patch(f"/api/agent-chat/sessions/{sid}", json={"provider": "grok-build"})
    assert res.status_code == 200, res.text
    assert svc.store.get_session(sid).permission_mode == "default"


def test_a_planning_thread_s_build_mode_moves_with_the_runner(
    chat: tuple[TestClient, AgentChatService],
) -> None:
    http, svc = chat
    sid = svc.create_session(
        provider="claude-api", permission_mode="plan", build_mode="auto", surface="agent"
    ).session_id
    res = http.patch(f"/api/agent-chat/sessions/{sid}", json={"provider": "grok-build"})
    assert res.status_code == 200, res.text
    session = svc.store.get_session(sid)
    assert (session.permission_mode, session.build_mode) == ("plan", "default")
