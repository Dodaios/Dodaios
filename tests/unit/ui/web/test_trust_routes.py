"""HTTP API of the trust layer (``trust_routes``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core.protocols import ToolResult
from dodaios.trust.recipients import known_recipients
from dodaios.trust.rules import trust_rules
from dodaios.trust.undo import undo_ledger
from dodaios.ui.web import trust_routes
from dodaios.ui.web.trust_routes import router


class _Chat:
    def __init__(self) -> None:
        self.forgotten: list[dict[str, Any]] = []

    def forget_standing_rule(self, rule: dict[str, Any]) -> None:
        self.forgotten.append(rule)


@pytest.fixture
def client() -> tuple[TestClient, _Chat]:
    app = FastAPI()
    app.include_router(router)
    chat = _Chat()
    app.state.agent_chat = chat
    return TestClient(app), chat


def test_rules_are_listed_and_revoked(client, monkeypatch) -> None:
    http, chat = client

    async def no_agents() -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(trust_routes, "_agent_rules", no_agents)
    rule = trust_rules().add(tool="Bash", kind="command", target="npm test", label="npm test")
    body = http.get("/api/trust/rules").json()
    assert [r["id"] for r in body["rules"]] == [rule["id"]]
    assert body["hard_limits"] == ["money", "credentials", "permanent_delete", "new_recipient"]

    gone = http.delete(f"/api/trust/rules/{rule['id']}")
    assert gone.status_code == 200 and gone.json()["rule"]["id"] == rule["id"]
    assert chat.forgotten == [rule], "an open chat stops honouring the rule too"
    assert trust_rules().items() == []
    assert http.delete(f"/api/trust/rules/{rule['id']}").status_code == 404


def test_agent_rules_come_from_the_roster(client, monkeypatch) -> None:
    http, _chat = client
    agent = SimpleNamespace(
        agent_id="ada",
        title="Ada",
        approval_rules={
            "always_allow": ["plugin:gmail:send", "plugin:calendar"],
            "require_approval": [],
        },
    )

    class _Roster:
        async def list(self):
            return [agent]

    monkeypatch.setattr(
        "dodaios.society.runtime.current_runtime", lambda: SimpleNamespace(roster=_Roster())
    )
    rows = http.get("/api/trust/rules").json()["agent_rules"]
    assert [(r["agent"], r["pattern"], r["label"]) for r in rows] == [
        ("Ada", "plugin:gmail:send", "Always allow send with gmail"),
        ("Ada", "plugin:calendar", "Always allow calendar"),
    ]


def test_undo_runs_the_inverse_through_the_runner(client, monkeypatch) -> None:
    http, _chat = client
    ran: list[tuple[str, dict[str, Any]]] = []

    async def runner(tool: str, args: dict[str, Any], entry: dict[str, Any]) -> ToolResult:
        ran.append((tool, args))
        return ToolResult(success=True, output="ok")

    undo_ledger().set_runner(runner)
    entry = undo_ledger().record(
        "gmail",
        {"action": "modify_message", "message_id": "m1", "remove_labels": ["INBOX"]},
        {},
        None,
    )
    assert http.get("/api/trust/undo").json()["entries"][0]["id"] == entry["id"]
    done = http.post(f"/api/trust/undo/{entry['id']}")
    assert done.status_code == 200 and done.json()["ok"] is True
    assert ran == [
        (
            "gmail",
            {
                "action": "modify_message",
                "message_id": "m1",
                "add_labels": ["INBOX"],
                "remove_labels": [],
            },
        )
    ]
    assert http.post("/api/trust/undo/nope").status_code == 404


def test_the_undo_runner_stamps_undo_of_and_runs_unattended(monkeypatch) -> None:
    import asyncio

    seen: list[Any] = []

    class _Gateway:
        async def execute(self, name, arguments, request):
            seen.append((name, arguments, request))
            return ToolResult(success=True, output="ok")

    monkeypatch.setattr("dodaios.core.runtime_refs.get_supervisor_tool_gateway", lambda: _Gateway())
    asyncio.run(
        trust_routes._run_inverse(
            "gmail", {"action": "x"}, {"id": "u1", "label": "Archived a mail"}
        )
    )
    name, arguments, request = seen[0]
    assert (name, arguments) == ("gmail", {"action": "x"})
    assert request.config_snapshot == {"undo_of": "u1", "approval_surface": "unattended"}
    assert request.origin == "trust-undo"


def test_privacy_and_recipients(client, monkeypatch) -> None:
    http, _chat = client
    monkeypatch.setattr(
        "dodaios.trust.privacy.overview", lambda cfg: {"accounts": [], "cfg": cfg is None}
    )
    assert http.get("/api/trust/privacy").json() == {"accounts": [], "cfg": True}

    known_recipients().remember(["ada@example.com"])
    assert [r["recipient"] for r in http.get("/api/trust/recipients").json()["recipients"]] == [
        "ada@example.com"
    ]
    assert http.delete("/api/trust/recipients?recipient=ada@example.com").status_code == 200
    assert http.delete("/api/trust/recipients?recipient=ada@example.com").status_code == 404


# ------------------------------------------------------------ credentials


def test_credentials_overview_lists_handles_never_values(client, monkeypatch, tmp_path) -> None:
    from dodaios.credential_broker import CredentialBroker, Handle, LocalVaultBackend, SiteRules
    from dodaios.society.credentials import CredentialVault
    from tests.fakes.fake_secret_store import FakeSecretStore

    http, _chat = client
    canary = "Cnry-route-9f3a7c1e5b"
    vault = CredentialVault(tmp_path / "v", secrets=FakeSecretStore())
    vault.store_login("ada", "github", "owner", canary, url="https://github.com/login")
    broker = CredentialBroker({"local": LocalVaultBackend(lambda: vault)}, SiteRules(tmp_path / "s.json"))
    broker.rules.add("ada", Handle("github.com", "github"))

    async def roster() -> list[Any]:
        return [SimpleNamespace(agent_id="ada", name="Ada")]

    runtime = SimpleNamespace(data_dir=tmp_path, roster=SimpleNamespace(list=roster))
    monkeypatch.setattr(trust_routes, "_broker", lambda: (broker, runtime))
    body = http.get("/api/trust/credentials").json()
    assert body["backend"] == "local"
    assert [h["handle"] for h in body["handles"]] == ["cred:github.com/github"]
    assert body["handles"][0]["agent"] == "Ada"
    assert canary not in http.get("/api/trust/credentials").text
    rule = body["rules"][0]
    assert http.put(f"/api/trust/credentials/rules/{rule['id']}/otp-mail", json={"on": True}).status_code == 200
    assert broker.rules.items()[0]["otp_from_mail"] is True
    assert http.put("/api/trust/credentials/backend", json={"name": "nope"}).status_code == 400
    assert http.put(
        "/api/trust/credentials/session", json={"backend": "local", "key": "x"}
    ).status_code == 400
    assert http.delete(f"/api/trust/credentials/rules/{rule['id']}").status_code == 200
    assert http.delete(f"/api/trust/credentials/rules/{rule['id']}").status_code == 404
