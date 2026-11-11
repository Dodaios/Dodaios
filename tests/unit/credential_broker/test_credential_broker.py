"""Credential broker: handles in, values only inside the executor, canary never leaks."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.service import _redact_credentials
from dodaios.credential_broker import (
    BackendError,
    BitwardenBackend,
    CredentialBroker,
    Handle,
    LocalVaultBackend,
    OnePasswordBackend,
    Secrets,
    SiteRules,
    find_handles,
    parse_handle,
    redact_active,
)
from dodaios.society.browser.bridge import prepare_broker_logins
from dodaios.society.credentials import CredentialVault
from dodaios.trust.audit import AuditLog
from tests.fakes.fake_secret_store import FakeSecretStore

CANARY = "Cnry-9f3a7c1e5b-hunter2"
SEED = "JBSWY3DPEHPK3PXP"
HANDLE = Handle("github.com", "owner")


@pytest.fixture(autouse=True)
def _no_leaked_leases() -> Any:
    from dodaios.credential_broker import broker as broker_module

    broker_module._ACTIVE.clear()
    yield
    broker_module._ACTIVE.clear()


class FakeBackend:
    name = "local"

    def __init__(self, secrets: Secrets | None = None, *, fail: str = "") -> None:
        self.secrets = secrets or Secrets("owner@example.com", CANARY, SEED)
        self.fail = fail
        self.resolves = 0

    def status(self) -> Any:
        return SimpleNamespace(to_dict=lambda: {"name": self.name})

    def list_handles(self, agent_id: str, domain: str | None = None) -> list[Any]:
        return []

    def resolve(self, agent_id: str, handle: Handle) -> Secrets:
        self.resolves += 1
        if self.fail:
            raise BackendError(self.fail)
        return self.secrets


def make_broker(tmp_path: Path, backend: Any | None = None) -> tuple[CredentialBroker, AuditLog]:
    audit = AuditLog(tmp_path / "audit.db")
    broker = CredentialBroker(
        {"local": backend or FakeBackend()}, SiteRules(tmp_path / "settings.json"),
        audit=lambda: audit,
    )
    return broker, audit


def asker(answer: bool) -> tuple[Any, list[Handle]]:
    asked: list[Handle] = []

    async def authorize(handle: Handle) -> bool:
        asked.append(handle)
        return answer

    return authorize, asked


# ----------------------------------------------------------------- handles


def test_handles_parse_and_are_found_in_text() -> None:
    assert parse_handle("cred:github.com/owner") == HANDLE
    assert parse_handle("cred:github/owner") is None
    text = "use cred:github.com/owner, cred:accounts.google.com/me.work, cred:github.com/owner"
    assert [str(h) for h in find_handles(text)] == [
        "cred:github.com/owner", "cred:accounts.google.com/me.work",
    ]
    assert HANDLE.placeholder_base == "cred_github_com_owner"


# ----------------------------------------------------------- approval flow


async def test_first_login_on_a_site_asks_then_the_rule_answers(tmp_path: Path) -> None:
    broker, _ = make_broker(tmp_path)
    authorize, asked = asker(True)
    first = await broker.prepare_browser("ada", "sign in with cred:github.com/owner", authorize)
    assert asked == [HANDLE] and first.used == ["cred:github.com/owner"]
    first.release()
    second = await broker.prepare_browser("ada", "again cred:github.com/owner", authorize)
    assert asked == [HANDLE]  # not asked again
    second.release()
    rule = broker.rules.find("ada", "github.com")
    assert rule is not None
    assert broker.rules.find("bob", "github.com") is None  # rules are per agent
    broker.rules.revoke(rule["id"])
    third = await broker.prepare_browser("ada", "cred:github.com/owner", authorize)
    assert len(asked) == 2  # revoked: asks again
    third.release()


async def test_a_declined_login_releases_nothing(tmp_path: Path) -> None:
    backend = FakeBackend()
    broker, audit = make_broker(tmp_path, backend)
    authorize, _ = asker(False)
    lease = await broker.prepare_browser("ada", "use cred:github.com/owner", authorize)
    assert lease.sensitive_data == {} and backend.resolves == 0
    assert "did not allow" in lease.task and CANARY not in lease.task
    assert broker.rules.find("ada", "github.com") is None
    assert '"denied"' in audit.export("json")[1]


async def test_a_locked_manager_is_reported_not_guessed(tmp_path: Path) -> None:
    broker, _ = make_broker(tmp_path, FakeBackend(fail="Bitwarden is locked or did not answer"))
    authorize, _ = asker(True)
    lease = await broker.prepare_browser("ada", "use cred:github.com/owner", authorize)
    assert lease.sensitive_data == {}
    assert "locked" in lease.unavailable["cred:github.com/owner"]
    assert "do not guess a password" in lease.task


# ------------------------------------------------------------- the browser


async def test_the_browser_gets_values_the_model_gets_placeholders(tmp_path: Path) -> None:
    broker, _ = make_broker(tmp_path)
    authorize, _ = asker(True)
    lease = await broker.prepare_browser("ada", "log in: cred:github.com/owner", authorize)
    scoped = lease.sensitive_data["*.github.com"]
    assert scoped["cred_github_com_owner_password"] == CANARY
    assert scoped["cred_github_com_owner_bu_2fa_code"] == SEED
    for value in (CANARY, SEED, "owner@example.com"):
        assert value not in lease.task
    assert "<secret>cred_github_com_owner_password</secret>" in lease.task
    assert "cred_github_com_owner_bu_2fa_code" in lease.task
    lease.release()
    assert lease.sensitive_data == {}


async def test_without_a_totp_item_the_owner_takes_over(tmp_path: Path) -> None:
    broker, _ = make_broker(tmp_path, FakeBackend(Secrets("owner", CANARY)))
    authorize, _ = asker(True)
    lease = await broker.prepare_browser("ada", "cred:github.com/owner", authorize)
    assert "bu_2fa_code" not in json.dumps(lease.sensitive_data)
    assert "take over the browser" in lease.task and "never read one-time codes" in lease.task
    rule = broker.rules.find("ada", "github.com")
    assert rule is not None and broker.rules.set_otp_from_mail(rule["id"], True)
    again = await broker.prepare_browser("ada", "cred:github.com/owner", authorize)
    assert "allowed reading it from their mail" in again.task


# ------------------------------------------------------------------ canary


async def test_canary_never_leaves_the_executor(tmp_path: Path) -> None:
    broker, audit = make_broker(tmp_path)
    authorize, _ = asker(True)
    lease = await broker.prepare_browser("ada", "sign in cred:github.com/owner", authorize)
    as_b64 = base64.b64encode(CANARY.encode()).decode()
    page_result = {
        "ok": True,
        "final_result": f"typed {CANARY} then {as_b64}",
        "urls": [f"https://github.com/?p={CANARY}"],
        "errors": [f"echo {SEED}"],
        "nested": {"deep": [("x", f"pw={CANARY}")]},
    }
    # The tool result, as the model reads it.
    result = json.dumps(lease.redact(page_result))
    assert CANARY not in result and SEED not in result and as_b64 not in result
    assert CANARY not in lease.redact(f"boom {CANARY}")

    # Every chat event while the task runs (the event log and the live stream).
    event = {"kind": "tool_result", "payload": {"text": f"saw {as_b64}", "n": 3}}
    out = json.dumps(await _redact_credentials("society:ada", event))
    assert CANARY not in out and as_b64 not in out
    assert "[credential cred:github.com/owner]" in out
    assert CANARY not in json.dumps(redact_active({"a": [CANARY]}))

    # Traces and receipts: the audit log holds the handle and nothing else.
    dump = audit.export("json")[1]
    assert "cred:github.com/owner" in dump
    assert CANARY not in dump and SEED not in dump and "owner@example.com" not in dump

    # The settings file the owner can read.
    assert CANARY not in (tmp_path / "settings.json").read_text(encoding="utf-8")

    lease.release()
    assert redact_active({"a": CANARY}) == {"a": CANARY}  # nothing is kept past the task


# ------------------------------------------------------------ the bridge


class _Approvals:
    def __init__(self, state: str) -> None:
        self.state = state
        self.enqueued: list[dict[str, Any]] = []

    async def enqueue(self, **kw: Any) -> Any:
        self.enqueued.append(kw)
        return SimpleNamespace(id="ap1")

    async def get(self, approval_id: str) -> Any:
        return SimpleNamespace(state=self.state)

    async def resolve(self, *_a: Any, **_k: Any) -> None:
        return None


async def test_the_bridge_asks_the_owner_with_a_card_that_names_the_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker, _ = make_broker(tmp_path)
    monkeypatch.setattr("dodaios.credential_broker.broker_for", lambda _d: broker)
    approvals = _Approvals("approved")
    runtime = SimpleNamespace(approvals=approvals, data_dir=tmp_path)
    live = SimpleNamespace(sessions={})
    caller = SimpleNamespace(agent_id="ada")
    lease = await prepare_broker_logins(
        runtime, caller, live, "go cred:github.com/owner", trace_id="t1", session_id="s1",
    )
    assert lease is not None and lease.used == ["cred:github.com/owner"]
    assert approvals.enqueued[0]["capability"] == "core:credentials"
    assert approvals.enqueued[0]["action"]["handle"] == "cred:github.com/owner"
    assert approvals.enqueued[0]["summary"].split()[3] == "github.com"
    assert CANARY not in json.dumps(approvals.enqueued)
    lease.release()
    assert await prepare_broker_logins(
        runtime, caller, live, "no handle here", trace_id="t", session_id="s",
    ) is None


async def test_a_denied_card_keeps_the_values_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    broker, _ = make_broker(tmp_path, backend)
    monkeypatch.setattr("dodaios.credential_broker.broker_for", lambda _d: broker)
    runtime = SimpleNamespace(approvals=_Approvals("denied"), data_dir=tmp_path)
    lease = await prepare_broker_logins(
        runtime, SimpleNamespace(agent_id="ada"), SimpleNamespace(sessions={}),
        "go cred:github.com/owner", trace_id="t", session_id="s",
    )
    assert lease is not None and lease.sensitive_data == {} and backend.resolves == 0


# --------------------------------------------------------------- backends

BW_ITEMS = [
    {"type": 1, "name": "GitHub (owner)", "login": {
        "username": "owner", "password": CANARY, "totp": SEED,
        "uris": [{"uri": "https://github.com/login"}]}},
    {"type": 1, "name": "GitHub work", "login": {
        "username": "w", "password": "other-secret-value",
        "uris": [{"uri": "https://gist.github.com"}]}},
    {"type": 2, "name": "A note", "login": None},
]


def bw_runner(state: str, items: list[dict[str, Any]], calls: list[Any]) -> Any:
    def run(argv: Any, env: dict[str, str]) -> tuple[int, str]:
        calls.append((list(argv), dict(env)))
        if argv[1] == "status":
            return 0, json.dumps({"status": state})
        if state != "unlocked":
            return 1, ""
        return 0, json.dumps(items)

    return run


def test_bitwarden_status_lookup_and_totp() -> None:
    calls: list[Any] = []
    absent = BitwardenBackend(bw_runner("unlocked", [], calls), which=lambda _n: None)
    assert absent.status().state == "not_installed"
    locked = BitwardenBackend(bw_runner("locked", [], calls), which=lambda _n: "bw")
    assert locked.status().state == "locked" and not locked.status().unlocked
    with pytest.raises(BackendError):
        locked.list_handles("ada")
    bw = BitwardenBackend(bw_runner("unlocked", BW_ITEMS, calls), which=lambda _n: "bw")
    bw.set_session("owner-session-key")
    assert bw.status().unlocked
    infos = bw.list_handles("ada", "github.com")
    assert {i.handle for i in infos} == {
        "cred:github.com/github-owner", "cred:github.com/github-work",
    }
    assert next(i for i in infos if i.account == "github-owner").has_totp
    assert CANARY not in json.dumps([i.to_dict() for i in infos])
    secrets = bw.resolve("ada", Handle("github.com", "github-owner"))
    assert (secrets.username, secrets.password, secrets.totp_seed) == ("owner", CANARY, SEED)
    assert CANARY not in repr(secrets)
    with pytest.raises(BackendError):
        bw.resolve("ada", Handle("github.com", "missing"))
    # The owner's session key travels in the environment, never in argv; nothing
    # ever calls unlock or login, so there is no master-password path.
    for argv, _env in calls:
        assert "owner-session-key" not in " ".join(argv)
        assert argv[1] in {"status", "list"}
    assert any(env.get("BW_SESSION") == "owner-session-key" for _, env in calls)


def op_runner(signed_in: bool, calls: list[list[str]]) -> Any:
    def run(argv: Any, env: dict[str, str]) -> tuple[int, str]:
        calls.append(list(argv))
        if argv[1] == "whoami":
            return (0 if signed_in else 1), ""
        if not signed_in:
            return 1, ""
        if argv[2] == "list":
            return 0, json.dumps([
                {"id": "i1", "title": "GitHub", "urls": [{"href": "https://github.com"}]},
                {"id": "i2", "title": "Bank", "urls": [{"href": "https://bank.example.org"}]},
            ])
        return 0, json.dumps({"fields": [
            {"purpose": "USERNAME", "value": "owner"},
            {"purpose": "PASSWORD", "value": CANARY},
            {"type": "OTP", "value": f"otpauth://totp/x?secret={SEED}&issuer=GitHub"},
        ]})

    return run


def test_one_password_status_lookup_and_totp() -> None:
    calls: list[list[str]] = []
    absent = OnePasswordBackend(op_runner(True, calls), which=lambda _n: None)
    assert absent.status().state == "not_installed"
    out = OnePasswordBackend(op_runner(False, calls), which=lambda _n: "op")
    assert out.status().state == "locked"
    with pytest.raises(BackendError):
        out.resolve("ada", Handle("github.com", "github"))
    op = OnePasswordBackend(op_runner(True, calls), which=lambda _n: "op")
    assert op.status().unlocked
    assert [i.handle for i in op.list_handles("ada", "github.com")] == ["cred:github.com/github"]
    secrets = op.resolve("ada", Handle("github.com", "github"))
    assert (secrets.username, secrets.password, secrets.totp_seed) == ("owner", CANARY, SEED)
    verbs = {a for argv in calls for a in argv}
    assert not verbs & {"signin", "create", "edit", "delete", "unlock"}


def test_the_local_vault_backend_lists_handles_and_resolves(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path / "v", secrets=FakeSecretStore())
    vault.store_login("ada", "github", "owner", CANARY, url="https://github.com/login")
    backend = LocalVaultBackend(lambda: vault)
    assert backend.status().unlocked
    infos = backend.list_handles("ada")
    assert [i.handle for i in infos] == ["cred:github.com/github"]
    assert CANARY not in json.dumps([i.to_dict() for i in infos])
    secrets = backend.resolve("ada", Handle("github.com", "github"))
    assert secrets.password == CANARY and secrets.totp_seed is None
    with pytest.raises(BackendError):
        backend.resolve("bob", Handle("github.com", "github"))


def test_the_owner_chooses_the_backend_and_it_persists(tmp_path: Path) -> None:
    def build() -> CredentialBroker:
        return CredentialBroker(
            {"local": FakeBackend(), "bitwarden": FakeBackend()}, SiteRules(tmp_path / "s.json"),
        )

    broker = build()
    assert broker.active_name() == "local"
    broker.set_backend("bitwarden")
    again = build()
    assert again.active_name() == "bitwarden"
    with pytest.raises(ValueError):
        again.set_backend("nope")
    assert asyncio.run(again.statuses()) == [{"name": "local"}, {"name": "local"}]


def test_a_look_alike_host_never_matches_the_credential(tmp_path: Path) -> None:
    from urllib.parse import urlparse

    evil = "https://github.com.evil.example/login"
    assert urlparse(evil).hostname != "github.com"
    items = [
        {"type": 1, "name": "Evil", "login": {
            "username": "u", "password": "pw-evil-value", "uris": [{"uri": evil}]}},
        {"type": 1, "name": "Evil2", "login": {
            "username": "u", "password": "pw-evil-value", "uris": [{"uri": "https://evilgithub.com"}]}},
    ]
    bw = BitwardenBackend(bw_runner("unlocked", items, []), which=lambda _n: "bw")
    assert bw.list_handles("ada", "github.com") == []
    with pytest.raises(BackendError):
        bw.resolve("ada", Handle("github.com", "evil"))
    broker, _ = make_broker(tmp_path)
    broker.rules.add("ada", HANDLE)
    assert broker.rules.find("ada", "github.com.evil.example") is None
    assert broker.rules.find("ada", "evilgithub.com") is None
