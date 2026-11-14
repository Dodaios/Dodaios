"""A job that was set up is ready only when what it needs is reachable.

The live case: the lead created an agent with a daily X post and a launch on
Reddit, Hacker News and Product Hunt, and answered "done". X was not connected
and no login existed, so no run could have posted anything.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from dodaios.brain.lead_doctrine import LEAD_DOCTRINE
from dodaios.commands.registry import get_command
from dodaios.plugins.tool.app_command import AppCommandTool
from dodaios.society import connect_tool, credentials, readiness, routine_runner
from dodaios.society.credentials import CredentialVault
from dodaios.society.login_tool import LOGIN_TOOL_NAME, lead_login_tools
from dodaios.society.readiness import BLOCKED, READY, UNVERIFIED, check_readiness
from dodaios.society.runtime import SocietyRuntime
from dodaios.tasks.store import TaskStore
from dodaios.ui.web.society_routes import router
from tests.fakes.fake_secret_store import FakeSecretStore

HERALD = SimpleNamespace(
    agent_id="herald", name="Herald", title="Marketing", description="", focus=[]
)
SERVICES = ["x", "Reddit", "Hacker News", "Product Hunt"]


class _Runtime:
    def __init__(self, unconnected: set[str]) -> None:
        self.unconnected = unconnected

    def catalog(self) -> list[Any]:
        return []

    def unconnected_plugins(self) -> list[str]:
        return sorted(self.unconnected)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CredentialVault:
    store = CredentialVault(tmp_path / "credentials", secrets=FakeSecretStore())
    monkeypatch.setattr(credentials, "current_vault", lambda: store)
    return store


@pytest.fixture
def rt(monkeypatch: pytest.MonkeyPatch, vault: CredentialVault) -> _Runtime:
    runtime = _Runtime({"x"})
    monkeypatch.setattr(
        connect_tool, "_plugin_connected", lambda plugin_id: plugin_id not in runtime.unconnected
    )

    async def seat(_rt: Any, _agent: Any, _task_id: str) -> tuple[str, str, str, str]:
        return "", "", "", ""  # no provider: the seat preflight has nothing to refuse

    monkeypatch.setattr(routine_runner, "_seat_for_run", seat)
    return runtime


def _fixes(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(b["fix"]["tool"], b["fix"]["args"]) for b in result["blockers"]]


async def test_the_marketing_setup_is_blocked_until_x_is_connected_and_logins_exist(
    rt: _Runtime, vault: CredentialVault
) -> None:
    result = await check_readiness(rt, HERALD, services=SERVICES)
    assert result["status"] == BLOCKED
    assert _fixes(result) == [
        ("society_request_connect", {"kind": "plugin", "id": "x"}),
        ("society_request_login", {"site": "Reddit", "agent": "herald"}),
        ("society_request_login", {"site": "Hacker News", "agent": "herald"}),
        ("society_request_login", {"site": "Product Hunt", "agent": "herald"}),
    ]
    assert "NOT READY" in result["instruction"] and "Do not say it is done" in result["instruction"]
    assert result["checked"][:2] == ["X (Twitter)", "Reddit"]

    rt.unconnected.clear()
    for site, url in (
        ("reddit", "reddit.com"), ("hacker_news", "news.ycombinator.com"),
        ("product_hunt", "producthunt.com"),
    ):
        vault.store_login("herald", site, "user", "a long password", url=url)
    assert await check_readiness(rt, HERALD, services=SERVICES) == {
        "checked": ["X (Twitter)", "Reddit", "Hacker News", "Product Hunt", "model seat"],
        "status": READY,
    }


async def test_a_plugin_the_prompt_names_is_found_without_being_declared(rt: _Runtime) -> None:
    result = await check_readiness(rt, HERALD, texts=("Daily post", "Post the update on X."))
    assert result["status"] == BLOCKED
    assert _fixes(result) == [("society_request_connect", {"kind": "plugin", "id": "x"})]
    # A lower-case x in running text is not the service; a longer name is matched as a word.
    rt.unconnected.update({"linkedin"})
    quiet = await check_readiness(rt, HERALD, texts=("Compare 3 x 4 layouts for LinkedIn.",))
    assert _fixes(quiet) == [("society_request_connect", {"kind": "plugin", "id": "linkedin"})]


async def test_nothing_named_and_nothing_missing_is_unverified_not_ready(rt: _Runtime) -> None:
    result = await check_readiness(rt, HERALD, texts=("Summarise my notes.",))
    assert result["status"] == UNVERIFIED and "society-check-readiness" in result["instruction"]
    assert (await check_readiness(rt, HERALD, services=[]))["status"] == READY


async def test_a_login_stands_in_for_the_plugin_and_other_names_resolve(
    rt: _Runtime, vault: CredentialVault
) -> None:
    by_other_name = await check_readiness(rt, HERALD, services=["Twitter"])
    assert _fixes(by_other_name) == [("society_request_connect", {"kind": "plugin", "id": "x"})]
    vault.store_login("herald", "twitter", "user", "a long password", url="x.com")
    assert (await check_readiness(rt, HERALD, services=["Twitter"]))["status"] == READY


async def test_an_unusable_model_seat_blocks(rt: _Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_seat(_rt: Any, _agent: Any, _task_id: str) -> Any:
        raise RuntimeError("The routine has no model seat: pick a model for the agent.")

    monkeypatch.setattr(routine_runner, "_seat_for_run", no_seat)
    result = await check_readiness(rt, HERALD, services=[], task_ids=("t1", "t2"))
    assert result["status"] == BLOCKED
    assert [b["kind"] for b in result["blockers"]] == ["seat"]  # one seat, told once
    assert "no model seat" in result["blockers"][0]["missing"]


async def test_unknown_state_is_never_a_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(credentials, "current_vault", lambda: None)
    monkeypatch.setattr(connect_tool, "_plugin_connected", lambda plugin_id: None)

    async def broken(*_a: Any) -> Any:
        raise ValueError("no config")

    monkeypatch.setattr(routine_runner, "_seat_for_run", broken)
    result = await check_readiness(SimpleNamespace(), HERALD, services=SERVICES)
    assert result["status"] == READY


# ------------------------------------------------------------- through the commands


@pytest.fixture
async def commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vault: CredentialVault):
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, plugin_state=lambda: (["x"], set()))
    tasks = TaskStore(tmp_path / "tasks.db")
    await tasks.init()
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    app.state.task_store = tasks
    monkeypatch.setattr(connect_tool, "current_runtime", lambda: runtime, raising=False)
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: runtime)
    loader = AppCommandTool(transport=httpx.ASGITransport(app=app))
    try:
        yield {tool.name: tool for tool in loader.expand()}
    finally:
        await runtime.close()
        await tasks.close()


def _ctx() -> SimpleNamespace:
    from uuid import uuid4

    return SimpleNamespace(config={"output_language": "en"}, trace_id=uuid4())


async def test_creating_the_agent_and_its_routine_reports_what_blocks_them(commands) -> None:
    created = await commands["society-create-agent"].execute(
        {"name": "Herald", "title": "Marketing", "services": SERVICES}, _ctx()
    )
    assert created.success, created.error
    assert created.output["response"]["readiness"]["status"] == BLOCKED
    routine = await commands["society-create-routine"].execute(
        {
            "agent_id": "herald",
            "title": "Daily post",
            "prompt": "Write one post about the product and publish it on X.",
            "schedule": {"kind": "every", "interval_seconds": 86_400},
        },
        _ctx(),
    )
    assert routine.success, routine.error
    found = routine.output["response"]["readiness"]
    assert found["status"] == BLOCKED
    assert ("society_request_connect", {"kind": "plugin", "id": "x"}) in _fixes(found)

    check = await commands["society-check-readiness"].execute(
        {"agent_id": "herald", "services": ["reddit"]}, _ctx()
    )
    assert check.success, check.error
    body = check.output["response"]
    assert body["routines"] == 1
    # The routine's own prompt still names X, Reddit has no login, and this bare
    # install has no model a routine could run on.
    assert {tool for tool, _ in _fixes(body["readiness"])} == {
        "society_request_connect", "society_request_login", "society-switch-agent-model",
    }
    seat = next(b for b in body["readiness"]["blockers"] if b["kind"] == "seat")
    assert "no model seat" in seat["missing"]


def test_the_rule_reaches_the_lead_with_the_tools_and_in_its_doctrine() -> None:
    for name in ("society-create-agent", "society-create-routine"):
        command = get_command(name)
        assert "services" in command.params["properties"]
        assert "only status 'ready'" in command.description
    assert get_command("society-check-readiness") is not None
    assert "ready only when its readiness status is 'ready'" in LEAD_DOCTRINE


# ------------------------------------------------------------- the lead's login card


async def test_the_lead_asks_for_a_team_agents_login_in_its_own_chat(
    monkeypatch: pytest.MonkeyPatch, vault: CredentialVault
) -> None:
    opened: list[tuple[str, str, str]] = []

    class _Chat:
        async def open_credential_request(self, session_id, spec, save, *, asker="", **_kw):
            opened.append((session_id, spec.env, asker))
            await save('{"username": "user", "password": "a long password"}')
            return "req-1"

        async def wait_credential_request(self, _session_id, _request_id, _timeout):
            return None

    class _Roster:
        async def resolve(self, target: str) -> Any:
            return HERALD if target.lower() == "herald" else None

    runtime = SimpleNamespace(
        lead_id="jarvis", roster=_Roster(), chat_service=lambda: _Chat(),
        cached_agent=lambda _id: None,
    )
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: runtime)
    monkeypatch.setattr("dodaios.society.display_name.lead_display_name", lambda *_a: "Nova")
    saved: list[tuple[str, str]] = []

    async def save_login(agent_id: str, key: str, _value: str, **_kw: Any) -> None:
        saved.append((agent_id, key))

    monkeypatch.setattr(credentials, "save_requested_login", save_login)
    tool = lead_login_tools(SimpleNamespace(session_id="lead-chat"))[LOGIN_TOOL_NAME]
    args = {"site": "Reddit", "url": "https://www.reddit.com/login", "description": "To post."}
    result = await tool.execute({**args, "agent": "Herald"}, None)
    assert result.success and result.output["status"] == "waiting"
    assert opened == [("lead-chat", "reddit", "Nova")] and saved == [("herald", "reddit")]
    unknown = await tool.execute({**args, "agent": "Nobody"}, None)
    assert not unknown.success and "no team agent" in unknown.error
    assert lead_login_tools(SimpleNamespace(session_id="")) == {}
    assert readiness.READY == "ready"
