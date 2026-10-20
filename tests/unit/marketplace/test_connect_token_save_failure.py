"""connect_start's background _drive() persists a grant before it checks it.

Two orderings matter here:

* `connect_poll` must never report "connected" before the token actually
  landed in the TokenStore (a save failure, or a crash right after
  `await_completion`, once let the poll report a token that was never stored).
* A completed browser consent is stored BEFORE the resource check runs. A
  check that fails for any reason other than the provider refusing the
  credential (a missing scope, an outage, an empty tool list) leaves the
  plugin connected with a degraded capability, instead of throwing the grant
  away and sending the user through the browser again. A credential the
  provider rejects (HTTP 401) is still an error and leaves the store as it was.

Every connect flow (PKCE loopback, DCR, device) shares this drive, so each
one is exercised with a fake handler.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import BackgroundTasks, Response

from dodaios.marketplace import connection_verification as verification
from dodaios.marketplace.auth.base import AuthSession, FlowResult
from dodaios.marketplace.token_store import InMemoryBackend, Tokens, TokenStore
from dodaios.ui.web import marketplace_routes as mr

# Captured before any test patches `mr.load_catalog`.
_load_shipped_catalog = mr.load_catalog


def _Catalog(specs):  # noqa: N802 - reads like the catalog it builds
    """The real shipped catalog, narrowed to the plugins under test."""
    return _load_shipped_catalog().model_copy(update={"plugins": list(specs)})


def _pkce_spec(client_id: str, plugin_id: str | None = None):
    for spec in _load_shipped_catalog().plugins:
        if plugin_id is not None and spec.id != plugin_id:
            continue
        if spec.auth is not None and getattr(spec.auth, "mode", "") == "oauth_pkce_loopback":
            return spec.model_copy(
                update={"auth": spec.auth.model_copy(update={"client_id": client_id})}
            )
    pytest.skip("no oauth_pkce_loopback plugin in catalog")


def _spec_for(flow: str):
    if flow == "pkce":
        return _pkce_spec("real-client-id.apps.example")
    if flow == "dcr":
        return _load_shipped_catalog().by_id("notion")
    spec = _load_shipped_catalog().by_id("github")
    assert spec.auth.mode == "oauth_device_flow"
    return spec


class _FakeHandler:
    """Stands in for a real auth handler: returns a session immediately and a
    completed FlowResult carrying tokens, without ever touching a socket or a
    real OAuth provider."""

    def __init__(self, *args, **kwargs) -> None:
        self.args = args

    async def start(self, plugin_spec) -> AuthSession:
        return AuthSession(
            flow_id=f"test-flow-{plugin_spec.id}",
            plugin_id=plugin_spec.id,
            kind="browser_redirect",
        )

    async def await_completion(self, session: AuthSession) -> FlowResult:
        return FlowResult(tokens=Tokens(access="tok-123", refresh="ref-1"), error=None)


@pytest.fixture
def store(monkeypatch) -> TokenStore:
    """One in-memory token store shared by every `TokenStore()` the routes open."""
    backend = InMemoryBackend()
    monkeypatch.setattr(mr, "TokenStore", lambda: TokenStore(backend=backend))
    monkeypatch.setattr(mr, "_refresh_plugin_in_live_registry", lambda plugin_id: None)
    return TokenStore(backend=backend)


@pytest.fixture
def _capture_background_tasks(monkeypatch):
    """connect_start fires `_drive()` via `asyncio.create_task` and returns
    immediately — capture the task so the test can await it before polling."""
    real_create_task = asyncio.create_task
    captured: list[asyncio.Task] = []

    def _capturing(coro, **kwargs):
        task = real_create_task(coro, **kwargs)
        captured.append(task)
        return task

    monkeypatch.setattr(mr.asyncio, "create_task", _capturing)
    return captured


def _verifier(failure: verification.ConnectionVerificationError | None, seen: list | None = None):
    async def verify(spec, tokens):
        if seen is not None:
            seen.append(tokens)
        if failure is not None:
            raise failure

    return verify


async def _start_and_drain(
    monkeypatch, capture_background_tasks, *, flow: str = "pkce", spec=None
) -> tuple[str, str]:
    spec = spec if spec is not None else _spec_for(flow)
    monkeypatch.setattr(mr, "load_catalog", lambda: _Catalog([spec]))
    monkeypatch.setattr(
        "dodaios.marketplace.connect_helpers.resolve_pkce_client",
        lambda pid, cid, csec: ("real-client-id.apps.example", None),
    )
    monkeypatch.setattr(
        "dodaios.marketplace.publisher_clients.resolve_publisher_client",
        lambda pid, cid, csec: ("real-device-client", None, "publisher"),
    )
    monkeypatch.setattr(mr, "PkceLoopbackHandler", _FakeHandler)
    monkeypatch.setattr(mr, "DeviceFlowHandler", _FakeHandler)
    monkeypatch.setattr(mr, "_build_dcr_handler", lambda *a: _FakeHandler())

    session = await mr.connect_start(spec.id, BackgroundTasks())
    for task in capture_background_tasks:
        await task
    return session["plugin_id"], session["flow_id"]


@pytest.mark.asyncio
async def test_connect_poll_reports_error_when_token_save_fails(
    monkeypatch, store, _capture_background_tasks
) -> None:
    def _raising_save(self, plugin_id, tokens) -> None:
        raise RuntimeError("simulated keyring save failure")

    monkeypatch.setattr(mr, "verify_connection", _verifier(None))
    monkeypatch.setattr(TokenStore, "save", _raising_save)

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks)

    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["pkce", "dcr", "device"])
async def test_verified_grant_is_saved_and_reported_connected(
    monkeypatch, store, _capture_background_tasks, flow
) -> None:
    monkeypatch.setattr(mr, "verify_connection", _verifier(None))

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks, flow=flow)

    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "connected"
    assert result["capability_state"] == "verified"
    saved = store.load(plugin_id)
    assert saved is not None and saved.access == "tok-123"
    assert saved.extra["capability_state"] == "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["pkce", "dcr", "device"])
@pytest.mark.parametrize(
    "reason", ["forbidden", "rate_limited", "unavailable"], ids=["403", "429", "outage"]
)
async def test_failed_capability_check_keeps_the_grant_connected_but_degraded(
    monkeypatch, store, _capture_background_tasks, flow, reason
) -> None:
    """The bug: a capability/health probe failure threw away a valid grant."""
    stored_during_check: list[Tokens | None] = []

    async def verify(spec, tokens):
        # The grant is already durable while the check runs: a crash or an
        # outage here can no longer lose the consent.
        stored_during_check.append(store.load(spec.id))
        raise verification.ConnectionVerificationError(
            "The provider connection check failed. Check account access and try again.",
            reason=reason,
        )

    monkeypatch.setattr(mr, "verify_connection", verify)

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks, flow=flow)

    assert stored_during_check[0] is not None
    assert stored_during_check[0].access == "tok-123"
    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "connected"
    assert result["capability_state"] == "degraded"
    assert result["capability_reason"] == reason
    assert result["capability_message"].startswith("The provider connection check failed")
    saved = store.load(plugin_id)
    assert saved is not None
    assert saved.access == "tok-123" and saved.refresh == "ref-1"
    assert saved.needs_reauth is False
    assert saved.extra["capability_state"] == "degraded"

    listing = await mr.list_plugins(Response())
    item = next(p for p in listing["plugins"] if p["id"] == plugin_id)
    assert item["status"] == "connected"
    assert item["capability_state"] == "degraded"
    assert item["capability_reason"] == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["pkce", "dcr", "device"])
async def test_rejected_grant_is_not_kept_and_reports_error(
    monkeypatch, store, _capture_background_tasks, flow
) -> None:
    """A credential the provider refuses (401 at verify) is handled as before."""
    failure = verification.ConnectionVerificationError(
        "The provider rejected the authorization. Connect again.", reason="unauthorized"
    )
    monkeypatch.setattr(mr, "verify_connection", _verifier(failure))

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks, flow=flow)

    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "error"
    assert result["error"] == "The provider rejected the authorization. Connect again."
    assert result["error_code"] == "provider_unreachable"
    assert store.load(plugin_id) is None


@pytest.mark.asyncio
async def test_real_401_from_the_provider_rejects_and_restores_the_previous_grant(
    monkeypatch, store, _capture_background_tasks
) -> None:
    """End to end through the real verifier: Google Drive answers 401."""
    spec = _pkce_spec("real-client-id.apps.example", plugin_id="google_drive")
    previous = Tokens(access="old", needs_reauth=True, reauth_reason="provider_rejected")
    store.save(spec.id, previous)
    original = httpx.AsyncClient
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"error": "private-provider-token"})

    monkeypatch.setattr(
        verification.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks, spec=spec)

    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "error"
    assert "private-provider-token" not in result["error"]
    assert requests and requests[0].headers["Authorization"] == "Bearer tok-123"
    # The reconnect that was refused leaves the earlier grant exactly as it was.
    assert store.load(plugin_id) == previous


@pytest.mark.asyncio
async def test_real_403_from_the_provider_keeps_the_grant_degraded(
    monkeypatch, store, _capture_background_tasks
) -> None:
    """End to end through the real verifier: signed in, but a scope is missing."""
    spec = _pkce_spec("real-client-id.apps.example", plugin_id="google_drive")
    original = httpx.AsyncClient

    monkeypatch.setattr(
        verification.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(lambda request: httpx.Response(403, json={})),
        ),
    )

    plugin_id, flow_id = await _start_and_drain(monkeypatch, _capture_background_tasks, spec=spec)

    result = await mr.connect_poll(plugin_id, flow_id)
    assert result["state"] == "connected"
    assert result["capability_state"] == "degraded"
    assert result["capability_reason"] == "forbidden"
    assert store.load(plugin_id).access == "tok-123"


@pytest.mark.asyncio
async def test_reconnect_during_the_check_is_not_overwritten(
    monkeypatch, store, _capture_background_tasks
) -> None:
    """A newer grant saved while the check ran wins over the health update."""
    newer = Tokens(access="newer")

    async def verify(spec, tokens):
        store.save(spec.id, newer)
        raise verification.ConnectionVerificationError("x", reason="unauthorized")

    monkeypatch.setattr(mr, "verify_connection", verify)

    plugin_id, _ = await _start_and_drain(monkeypatch, _capture_background_tasks)

    assert store.load(plugin_id) == newer


@pytest.mark.asyncio
async def test_cancelled_reconnect_does_not_replace_needs_reauth_grant(
    monkeypatch, store, _capture_background_tasks
) -> None:
    release = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()

    class _DelayedPkceHandler(_FakeHandler):
        async def await_completion(self, session: AuthSession) -> FlowResult:
            await release.wait()
            return FlowResult(tokens=Tokens(access="replacement"), error=None)

        async def cancel(self, session: AuthSession) -> None:
            cleanup_started.set()
            await finish_cleanup.wait()

    spec = _pkce_spec("real-client-id.apps.example")
    store.save(spec.id, Tokens(access="expired", needs_reauth=True))
    checked: list[Tokens] = []
    monkeypatch.setattr(mr, "verify_connection", _verifier(None, checked))

    monkeypatch.setattr(mr, "load_catalog", lambda: _Catalog([spec]))
    monkeypatch.setattr(
        "dodaios.marketplace.connect_helpers.resolve_pkce_client",
        lambda pid, cid, csec: ("real-client-id.apps.example", None),
    )
    monkeypatch.setattr(mr, "PkceLoopbackHandler", _DelayedPkceHandler)

    session = await mr.connect_start(spec.id, BackgroundTasks())
    cancel_task = asyncio.create_task(mr.cancel_connect(spec.id, session["flow_id"]))
    await cleanup_started.wait()
    release.set()
    for task in list(_capture_background_tasks):
        if task is not cancel_task:
            await task

    finish_cleanup.set()
    result = await cancel_task
    assert result["state"] == "cancelled"
    saved = store.load(spec.id)
    assert saved.access == "expired"
    assert saved.needs_reauth is True
    assert checked == []
