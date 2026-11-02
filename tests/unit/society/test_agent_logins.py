"""Website logins and connect cards: the agent signs in and connects without seeing secrets."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.credential_requests import CLI, LOGIN, PLUGIN, CredentialSpec
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.society import connect_tool, credentials
from dodaios.society.connect_tool import RequestConnectTool, Target
from dodaios.society.credentials import CredentialError, CredentialVault, login_key, login_site
from dodaios.society.login_tool import LOGIN_TOOL_NAME, RequestLoginTool
from tests.fakes.fake_secret_store import FakeSecretStore

USER = "ada.lovelace@example.org"
PASSWORD = "c0rrect horse battery"  # noqa: S105 — a test value
SID = "society:ada"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CredentialVault:
    store = CredentialVault(tmp_path / "credentials", secrets=FakeSecretStore())
    monkeypatch.setattr(credentials, "current_vault", lambda: store)
    return store


# ------------------------------------------------------------------ the vault


def test_a_site_is_bound_to_its_registrable_domain() -> None:
    assert login_site("https://www.reddit.com/login") == (
        "https://www.reddit.com/login", "reddit.com"
    )
    assert login_site("news.ycombinator.com/login")[1] == "ycombinator.com"
    assert login_site("https://forum.example.co.uk/")[1] == "example.co.uk"
    for bad in ("", "localhost", "http://127.0.0.1/login", "ftp://example.com", "co.uk"):
        with pytest.raises(CredentialError):
            login_site(bad)
    assert login_key("Hacker News") == "hacker_news"
    assert login_key("9gag") == "site_9gag"
    with pytest.raises(CredentialError):
        login_key("  ")


def test_a_login_keeps_its_values_out_of_the_index(vault: CredentialVault) -> None:
    vault.store("ada", "GITHUB_TOKEN", "ghp_" + "x" * 30)
    info = vault.store_login(
        "ada", "reddit", f"  {USER} ", PASSWORD, url="https://www.reddit.com/login", label="Reddit"
    )
    assert info.placeholders == ("reddit_username", "reddit_password")
    assert vault.has_login("ada", "reddit") and not vault.has_login("bob", "reddit")
    index = next(vault._root.glob("*.json")).read_text(encoding="utf-8")
    assert USER not in index and PASSWORD not in index
    assert json.loads(index)["logins"][0]["domain"] == "reddit.com"
    # Tokens and logins share the index file; writing one keeps the other.
    assert [row.env for row in vault.list("ada")] == ["GITHUB_TOKEN"]
    assert vault.browser_secrets("ada") == {
        "*.reddit.com": {"reddit_username": USER, "reddit_password": PASSWORD}
    }
    # Logins never become shell variables.
    assert set(vault.shell_env("ada")) == {"GITHUB_TOKEN"}
    vault.delete("ada", "GITHUB_TOKEN")
    assert [row.key for row in vault.list_logins("ada")] == ["reddit"]
    assert vault.delete_login("ada", "reddit") and not vault.delete_login("ada", "reddit")
    assert vault.browser_secrets("ada") == {}


def test_both_login_values_are_masked_wherever_they_show_up(vault: CredentialVault) -> None:
    vault.store_login("ada", "reddit", USER, PASSWORD, url="reddit.com")
    masked = vault.redact_payload("ada", {"text": f"signed in as {USER} with {PASSWORD}"})
    assert USER not in json.dumps(masked) and PASSWORD not in json.dumps(masked)
    assert "[credential reddit password]" in masked["text"]


def test_bad_logins_are_refused_and_nothing_is_kept(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path, secrets=FakeSecretStore())
    for user, password in (("", PASSWORD), (USER, ""), (USER, "two\nlines"), (USER, None)):
        with pytest.raises(CredentialError):
            vault.store_login("ada", "reddit", user, password, url="reddit.com")
    refusing = CredentialVault(tmp_path, secrets=FakeSecretStore(refuse=True))
    with pytest.raises(CredentialError):
        refusing.store_login("ada", "reddit", USER, PASSWORD, url="reddit.com")
    assert refusing.list_logins("ada") == []


# ------------------------------------------------------------------ the login card


async def _service_with_turn(tmp_path: Path, session_id: str = SID):
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    session = svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path),
        session_id=session_id, surface="society",
    )
    run = _Running("turn-1", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running[session.session_id] = run
    return svc, session.session_id, run.task


async def _next(q: asyncio.Queue, kind: str) -> dict[str, Any]:
    while True:
        ev = await asyncio.wait_for(q.get(), timeout=5)
        if ev["kind"] == kind:
            return ev["payload"]


def _runtime(service: Any) -> SimpleNamespace:
    return SimpleNamespace(
        chat_service=lambda: service, cached_agent=lambda _id: SimpleNamespace(name="Ada")
    )


_LOGIN_ARGS = {
    "site": "Reddit",
    "url": "https://www.reddit.com/login",
    "description": "To post your launch thread.",
}


async def test_the_login_card_saves_both_values_and_the_agent_gets_placeholders(
    tmp_path: Path, vault
) -> None:
    svc, sid, task = await _service_with_turn(tmp_path)
    q = svc.subscribe(sid)
    tool = RequestLoginTool(_runtime(svc), "ada", session_id=sid)
    first = await asyncio.wait_for(tool.execute(dict(_LOGIN_ARGS), None), timeout=1)
    assert first.success and first.output["status"] == "waiting"
    card = await _next(q, "credential_required")
    assert card["kind"] == LOGIN and card["env"] == "reddit" and card["label"] == "Reddit"
    assert card["url"] == "https://www.reddit.com/login" and card["asker"] == "Ada"
    with pytest.raises(CredentialError):  # a half-filled form keeps the card open
        await svc.submit_credential(sid, card["request_id"], json.dumps({"username": USER}))
    body = json.dumps({"username": USER, "password": PASSWORD})
    assert await svc.submit_credential(sid, card["request_id"], body)
    result = await tool.execute({"wait_for": card["request_id"]}, None)
    assert result.success and result.output["status"] == "saved"
    expected = "<secret>reddit_password</secret>"
    assert result.output["password_placeholder"] == expected  # noqa: S105
    assert result.output["domain"] == "reddit.com"
    leaked = json.dumps(result.output) + json.dumps(svc.store.list_events(sid))
    assert USER not in leaked and PASSWORD not in leaked
    again = await tool.execute(dict(_LOGIN_ARGS), None)
    assert again.success and again.output["status"] == "available"
    task.cancel()


async def test_a_restored_login_card_still_saves_into_the_vault(tmp_path: Path, vault) -> None:
    spec = CredentialSpec.build(
        "reddit", "Reddit", "why", kind=LOGIN, url="https://www.reddit.com/login"
    )
    save = AgentChatService._restore_credential_save(SID, spec)
    assert save is not None
    await save(json.dumps({"username": USER, "password": PASSWORD}))
    assert vault.browser_secrets("ada")["*.reddit.com"]["reddit_username"] == USER


async def test_bad_login_requests_never_open_a_card(vault) -> None:
    opened: list[Any] = []
    service = SimpleNamespace(open_credential_request=lambda *a, **k: opened.append(a))
    tool = RequestLoginTool(_runtime(service), "ada", session_id=SID)
    for bad in ({"url": "http://10.0.0.1/"}, {"site": " "}, {"description": " "}):
        result = await tool.execute({**_LOGIN_ARGS, **bad}, None)
        assert not result.success and "invalid request" in (result.error or "")
    routine = RequestLoginTool(_runtime(service), "ada", session_id="society:ada:routine:t:r")
    assert (await routine.execute(dict(_LOGIN_ARGS), None)).output["status"] == "unattended"
    assert opened == []


def test_the_login_and_connect_tools_are_offered_outside_routines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.society import surface

    browser = SimpleNamespace(is_installed=lambda: False, live=SimpleNamespace(model_resolver=None))
    rt = SimpleNamespace(browser=browser, chat_service=lambda: None, cached_agent=lambda _: None)
    monkeypatch.setattr(surface, "current_runtime", lambda: rt)
    canonical = SimpleNamespace(session_id="society:ada", cwd="", permission_mode="")
    routine = SimpleNamespace(
        session_id="society:ada:routine:t1:run1", cwd="", permission_mode="bypass"
    )
    offered = surface.society_tools(None, None, canonical)
    assert LOGIN_TOOL_NAME in offered and connect_tool.CONNECT_TOOL_NAME in offered
    assert LOGIN_TOOL_NAME not in surface.society_tools(None, None, routine)


async def test_the_briefing_names_stored_logins_by_placeholder(
    tmp_path: Path, vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.society.surface import _credential_line

    monkeypatch.setattr(credentials, "vault_for", lambda _data_dir: vault)
    vault.store_login("ada", "hacker_news", USER, PASSWORD, url="news.ycombinator.com")
    line = await _credential_line(SimpleNamespace(data_dir=tmp_path), "ada")
    assert "<secret>hacker_news_password</secret>" in line
    assert vault.list_logins("ada")[0].domain == "ycombinator.com"
    assert USER not in line and PASSWORD not in line


# ------------------------------------------------------------------ the browser


def _runner():
    previous = sys.stdout
    try:
        from dodaios.society.browser import live_runner
    finally:
        sys.stdout = previous
    return live_runner


def test_the_runner_hands_back_placeholders_instead_of_typed_values() -> None:
    live_runner = _runner()
    secrets = {"*.reddit.com": {"reddit_username": USER, "reddit_password": PASSWORD}}
    result = live_runner.scrub_secrets(
        secrets, {"final_result": f"Logged in as {USER}", "errors": [f"bad {PASSWORD}"]}
    )
    assert result == {
        "final_result": "Logged in as <secret>reddit_username</secret>",
        "errors": ["bad <secret>reddit_password</secret>"],
    }
    assert live_runner.typed_secret({"input": {"index": 3, "text": "<secret>x</secret>"}})
    assert not live_runner.typed_secret({"input": {"index": 3, "text": "hello"}})
    assert live_runner.scrub_secrets(None, {"a": 1}) == {"a": 1}


async def test_the_browser_run_receives_only_this_agents_logins(vault) -> None:
    from dodaios.society.browser.bridge import stored_logins

    vault.store_login("ada", "reddit", USER, PASSWORD, url="reddit.com")
    assert await stored_logins("ada") == {
        "*.reddit.com": {"reddit_username": USER, "reddit_password": PASSWORD}
    }
    assert await stored_logins("bob") == {}


# ------------------------------------------------------------------ the connect card


async def test_the_connect_card_closes_only_once_the_service_is_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"connected": False}

    def resolve(kind: str, raw: str) -> Target | None:
        if raw != "github":
            return None
        return Target(kind, "github", "GitHub", state["connected"])

    monkeypatch.setattr(connect_tool, "resolve_target", resolve)
    svc, sid, task = await _service_with_turn(tmp_path)
    q = svc.subscribe(sid)
    tool = RequestConnectTool(_runtime(svc), "ada", session_id=sid)
    args = {"kind": PLUGIN, "id": "github", "reason": "To read your open issues."}
    first = await tool.execute(dict(args), None)
    assert first.success and first.output["status"] == "waiting"
    card = await _next(q, "credential_required")
    assert card["kind"] == PLUGIN and card["env"] == "github" and card["label"] == "GitHub"
    with pytest.raises(CredentialError):  # the card cannot claim a connection that is not there
        await svc.submit_credential(sid, card["request_id"], "connected")
    state["connected"] = True
    assert await svc.submit_credential(sid, card["request_id"], "connected")
    done = await tool.execute({"wait_for": card["request_id"]}, None)
    assert done.success and done.output["status"] == "connected"
    again = await tool.execute(dict(args), None)
    assert again.output["status"] == "connected"  # no second card
    unknown = await tool.execute({**args, "id": "nope"}, None)
    assert not unknown.success and "no plugin named" in (unknown.error or "")
    wrong = await tool.execute({**args, "kind": "mcp"}, None)
    assert not wrong.success
    task.cancel()


async def test_a_restored_connect_card_still_checks_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        connect_tool, "resolve_target", lambda kind, raw: Target(kind, raw, "gh", False)
    )
    save = AgentChatService._restore_credential_save(
        SID, CredentialSpec.build("gh", "GitHub CLI", "why", kind=CLI)
    )
    assert save is not None
    with pytest.raises(CredentialError):
        await save("connected")


def test_a_public_username_is_typed_as_is_and_never_masked(vault: CredentialVault) -> None:
    # A site username such as the project's own name is public; masking it
    # would rewrite every mention of the project in the chat and the pages.
    vault.store_login("ada", "hacker_news", "dodaios", PASSWORD, url="news.ycombinator.com")
    assert vault.browser_secrets("ada") == {
        "*.ycombinator.com": {"hacker_news_password": PASSWORD}
    }
    assert vault.public_username("ada", "hacker_news") == "dodaios"
    text = "mcp__dodaios__society_ask_user posts for Dodaios/dodaios"
    assert vault.redact("ada", text) == text
    assert vault.redact("ada", f"pw={PASSWORD}") == "pw=[credential hacker_news password]"


def test_an_email_username_stays_a_placeholder(vault: CredentialVault) -> None:
    vault.store_login("ada", "reddit", USER, PASSWORD, url="reddit.com")
    assert vault.public_username("ada", "reddit") is None
    assert set(vault.browser_secrets("ada")["*.reddit.com"]) == {
        "reddit_username", "reddit_password"
    }


async def test_the_agent_gets_a_public_username_in_plain_text(tmp_path: Path, vault) -> None:
    vault.store_login("ada", "hacker_news", "dodaios", PASSWORD, url="news.ycombinator.com")
    tool = RequestLoginTool(_runtime(None), "ada", session_id=SID)
    result = await tool.execute(
        {"site": "Hacker News", "url": "news.ycombinator.com/login", "description": "why"}, None
    )
    assert result.output["status"] == "available"
    assert result.output["username"] == "dodaios"
    assert "logins_typed" in result.output["note"] and PASSWORD not in json.dumps(result.output)
