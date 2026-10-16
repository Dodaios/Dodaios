"""Sign in with ChatGPT (chatgpt-plan): OAuth lifecycle and the Responses brain.

Every network call goes through ``httpx.MockTransport``; no real endpoint,
browser or token is touched.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from jarvis.core.protocols import BrainMessage, BrainRequest
from jarvis.plugins.brain import chatgpt_plan, chatgpt_plan_auth
from jarvis.plugins.brain.chatgpt_plan_auth import (
    ISSUER,
    MODELS_URL,
    PLAN_SCOPE,
    SCOPES,
    TOKEN_URL,
    Attempt,
    ChatGPTPlanError,
    PlanAuth,
    Store,
    build_authorize_url,
    pkce_pair,
    redact,
    validate_id_token,
)

CLIENT_ID = "oaiapp_test123"
JWKS_URL = "https://auth.example/jwks"
REVOKE_URL = "https://auth.example/revoke"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(KEY.public_key()))
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _id_token(key: Any = KEY, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "user-1",
        "email": "person@example.com",
        "nonce": "n-1",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


class FakeOpenAI:
    """Routes for discovery, JWKS, token, revoke and models; records each call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.token_reply: tuple[int, dict[str, Any]] = (200, {})
        self.models_reply: tuple[int, dict[str, Any]] = (200, {"models": []})
        self.refresh_count = 0
        self._mu = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        with self._mu:
            self.calls.append((url, form))
        if url.startswith(f"{ISSUER}/.well-known"):
            return httpx.Response(
                200, json={"jwks_uri": JWKS_URL, "revocation_endpoint": REVOKE_URL}
            )
        if url == JWKS_URL:
            return httpx.Response(200, json=_jwks())
        if url == TOKEN_URL:
            if form.get("grant_type") == "refresh_token":
                with self._mu:
                    self.refresh_count += 1
                time.sleep(0.05)  # widen the race window for the lock test
            status, body = self.token_reply
            return httpx.Response(status, json=body)
        if url == REVOKE_URL:
            return httpx.Response(200)
        if url == MODELS_URL:
            status, body = self.models_reply
            return httpx.Response(status, json=body)
        return httpx.Response(404)


@pytest.fixture
def fake() -> FakeOpenAI:
    return FakeOpenAI()


@pytest.fixture
def plan(tmp_path, fake, monkeypatch) -> PlanAuth:
    monkeypatch.setattr(chatgpt_plan_auth, "_sleep", lambda _s: None)
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    opened: list[str] = []
    return PlanAuth(store=Store(tmp_path), client=lambda: client, open_browser=opened.append)


def _attempt(*, reauth: bool = False, client_id: str = "dynamic_agent_client") -> Attempt:
    return Attempt(
        state="s-1",
        nonce="n-1",
        verifier="v" * 43,
        redirect_uri="http://127.0.0.1:5555/auth/callback",
        client_id=client_id,
        reauth=reauth,
    )


def _signed_in(plan: PlanAuth, *, scope: str = SCOPES, expires_in: float = 3600) -> None:
    plan.store.write(
        {
            "client_id": CLIENT_ID,
            "sub": "user-1",
            "email": "person@example.com",
            "scope": scope,
            "tokens": {
                "access_token": "at-old",
                "refresh_token": "rt-old",
                "id_token": "idt",
                "expires_at": time.time() + expires_in,
            },
        }
    )


def _token_body(**extra: Any) -> dict[str, Any]:
    body = {
        "access_token": "at-new",
        "refresh_token": "rt-new",
        "id_token": _id_token(),
        "expires_in": 3600,
        "scope": SCOPES,
    }
    body.update(extra)
    return body


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ---- PKCE and authorize URL ----------------------------------------------


def test_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = pkce_pair()
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert 43 <= len(verifier) <= 128


def test_first_login_url_uses_dynamic_client_and_agent_name() -> None:
    q = _query(build_authorize_url(_attempt(), host_id="urn:uuid:x", challenge="c"))
    assert q["client_id"] == "dynamic_agent_client"
    assert q["code_challenge_method"] == "S256"
    assert PLAN_SCOPE in q["scope"].split()
    assert q["agent_name_hint"] == "Dodaios"
    assert "id_token_hint" not in q


def test_reauth_url_carries_hints_not_agent_name() -> None:
    url = build_authorize_url(
        _attempt(reauth=True, client_id=CLIENT_ID),
        host_id="urn:uuid:x",
        challenge="c",
        id_token_hint="idt",  # noqa: S106
        login_hint="person@example.com",
    )
    q = _query(url)
    assert q["client_id"] == CLIENT_ID
    assert q["id_token_hint"] == "idt"  # noqa: S105
    assert "agent_name_hint" not in q


def test_host_id_persists(tmp_path) -> None:
    first = Store(tmp_path).host_id()
    assert first.startswith("urn:uuid:")
    assert Store(tmp_path).host_id() == first


# ---- callback --------------------------------------------------------------


def test_callback_registers_client_and_stores_account(plan, fake) -> None:
    fake.token_reply = (200, _token_body())
    plan._attempt = _attempt()
    ok, _msg = plan.handle_callback({"state": "s-1", "code": "c-1", "client_id": CLIENT_ID})
    assert ok
    exchange = next(f for u, f in fake.calls if u == TOKEN_URL)
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == CLIENT_ID
    assert exchange["code_verifier"] == "v" * 43
    data = plan.store.read()
    assert data["client_id"] == CLIENT_ID
    assert data["sub"] == "user-1"
    status = plan.status()
    assert status["signed_in"] and status["plan_enabled"] and status["registered"]


def test_state_mismatch_is_rejected_without_exchange(plan, fake) -> None:
    plan._attempt = _attempt()
    ok, msg = plan.handle_callback({"state": "other", "code": "c-1", "client_id": CLIENT_ID})
    assert not ok and "stale" in msg
    assert not fake.calls
    assert plan._attempt is not None  # a stray request does not cancel the real attempt


def test_access_denied_marks_login_denied(plan) -> None:
    plan._attempt = _attempt()
    ok, _ = plan.handle_callback({"state": "s-1", "error": "access_denied"})
    assert not ok
    assert plan.status()["login"] == "denied"


@pytest.mark.parametrize("returned", ["", "dynamic_agent_client"])
def test_first_login_needs_a_registered_client(plan, fake, returned) -> None:
    plan._attempt = _attempt()
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c", "client_id": returned})
    assert not ok
    assert plan.status()["error"] == "registration_incomplete"
    assert not fake.calls


def test_reauth_reuses_stored_client_id(plan, fake) -> None:
    _signed_in(plan)
    fake.token_reply = (200, _token_body())
    plan._attempt = _attempt(reauth=True, client_id=CLIENT_ID)
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c"})
    assert ok
    exchange = next(f for u, f in fake.calls if u == TOKEN_URL)
    assert exchange["client_id"] == CLIENT_ID


def test_reauth_rejects_other_client(plan) -> None:
    _signed_in(plan)
    plan._attempt = _attempt(reauth=True, client_id=CLIENT_ID)
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c", "client_id": "oaiapp_other"})
    assert not ok and plan.status()["error"] == "client_mismatch"


def test_reauth_rejects_other_account(plan, fake) -> None:
    _signed_in(plan)
    fake.token_reply = (200, _token_body(id_token=_id_token(sub="user-2")))
    plan._attempt = _attempt(reauth=True, client_id=CLIENT_ID)
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c"})
    assert not ok and plan.status()["error"] == "account_mismatch"
    assert plan.store.read()["tokens"]["access_token"] == "at-old"  # noqa: S105


def test_nonce_mismatch_fails_login(plan, fake) -> None:
    fake.token_reply = (200, _token_body(id_token=_id_token(nonce="other")))
    plan._attempt = _attempt()
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c", "client_id": CLIENT_ID})
    assert not ok and plan.status()["error"] == "nonce_mismatch"
    assert "tokens" not in plan.store.read()


def test_missing_plan_scope_is_signed_in_without_plan(plan, fake) -> None:
    fake.token_reply = (200, _token_body(scope="openid profile email offline_access"))
    plan._attempt = _attempt()
    ok, _ = plan.handle_callback({"state": "s-1", "code": "c", "client_id": CLIENT_ID})
    assert ok
    status = plan.status()
    assert status["signed_in"] and not status["plan_enabled"]
    assert not plan.connected()


# ---- ID token validation ---------------------------------------------------


@pytest.mark.parametrize(
    ("token", "code"),
    [
        (lambda: _id_token(key=OTHER_KEY), "id_token_invalid"),
        (lambda: _id_token(iss="https://evil.example"), "id_token_invalid"),
        (lambda: _id_token(aud="oaiapp_other"), "id_token_invalid"),
        (lambda: _id_token(exp=int(time.time()) - 60), "id_token_expired"),
        (lambda: _id_token(nonce="other"), "nonce_mismatch"),
    ],
    ids=["bad_signature", "wrong_issuer", "wrong_audience", "expired", "nonce"],
)
def test_id_token_rejections(token, code) -> None:
    with pytest.raises(ChatGPTPlanError) as exc:
        validate_id_token(token(), jwks=_jwks(), client_id=CLIENT_ID, nonce="n-1")
    assert exc.value.code == code


def test_valid_id_token_returns_claims() -> None:
    claims = validate_id_token(_id_token(), jwks=_jwks(), client_id=CLIENT_ID, nonce="n-1")
    assert claims["sub"] == "user-1"


# ---- tokens ----------------------------------------------------------------


def test_fresh_token_needs_no_refresh(plan, fake) -> None:
    _signed_in(plan)
    assert plan.access_token() == "at-old"
    assert fake.refresh_count == 0


def test_refresh_rotates_refresh_token(plan, fake) -> None:
    _signed_in(plan, expires_in=10)
    fake.token_reply = (200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600})
    assert plan.access_token() == "at-2"
    sent = next(f for u, f in fake.calls if u == TOKEN_URL)
    assert sent["refresh_token"] == "rt-old" and sent["client_id"] == CLIENT_ID  # noqa: S105
    assert plan.store.read()["tokens"]["refresh_token"] == "rt-2"  # noqa: S105


def test_refresh_without_rotation_keeps_old_refresh_token(plan, fake) -> None:
    _signed_in(plan, expires_in=10)
    fake.token_reply = (200, {"access_token": "at-2", "expires_in": 3600})
    plan.access_token()
    assert plan.store.read()["tokens"]["refresh_token"] == "rt-old"  # noqa: S105


def test_parallel_refresh_posts_once(plan, fake) -> None:
    _signed_in(plan, expires_in=10)
    fake.token_reply = (200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600})
    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(plan.access_token())) for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results == ["at-2"] * 5
    assert fake.refresh_count == 1


def test_refresh_invalid_grant_requires_reauth(plan, fake) -> None:
    _signed_in(plan, expires_in=10)
    fake.token_reply = (400, {"error": "invalid_grant"})
    with pytest.raises(ChatGPTPlanError) as exc:
        plan.access_token()
    assert exc.value.code == "reauthorization_required"
    assert not plan.status()["signed_in"]
    assert plan.store.read()["client_id"] == CLIENT_ID


def test_refresh_invalid_client(plan, fake) -> None:
    _signed_in(plan, expires_in=10)
    fake.token_reply = (401, {"error": "invalid_client"})
    with pytest.raises(ChatGPTPlanError) as exc:
        plan.access_token()
    assert exc.value.code == "invalid_client"


def test_logout_revokes_and_clears(plan, fake) -> None:
    _signed_in(plan)
    plan.update_meta(model="gpt-x")
    assert plan.logout() is True
    revoke = next(f for u, f in fake.calls if u == REVOKE_URL)
    assert revoke == {
        "token": "rt-old",
        "token_type_hint": "refresh_token",
        "client_id": CLIENT_ID,
    }
    data = plan.store.read()
    for key in ("tokens", "scope", "sub", "email", "model"):
        assert key not in data
    assert data["client_id"] == CLIENT_ID  # the registration is reused by the next sign-in
    assert not plan.status()["signed_in"]


def test_status_and_redaction_never_reveal_tokens(plan) -> None:
    _signed_in(plan)
    text = json.dumps(plan.status())
    for secret in ("at-old", "rt-old", "idt"):
        assert secret not in text
    line = redact("GET /cb?code=abc&state=s&id_token_hint=eyJx refresh_token=rt1&access_token=at1")
    for secret in ("abc", "eyJx", "rt1", "at1"):
        assert secret not in line


# ---- models ----------------------------------------------------------------


def test_model_catalog_keeps_listed_rows(plan, fake) -> None:
    _signed_in(plan)
    fake.models_reply = (
        200,
        {
            "models": [
                {"slug": "gpt-a", "display_name": "GPT A", "visibility": "list"},
                {"slug": "gpt-hidden", "visibility": "hide"},
                {"slug": "gpt-b", "visibility": "list"},
            ]
        },
    )
    assert plan.models() == [
        {"slug": "gpt-a", "display_name": "GPT A"},
        {"slug": "gpt-b", "display_name": "gpt-b"},
    ]


def test_model_catalog_failure(plan, fake) -> None:
    _signed_in(plan)
    fake.models_reply = (403, {})
    with pytest.raises(ChatGPTPlanError) as exc:
        plan.models()
    assert exc.value.code == "models_failed"


# ---- brain -----------------------------------------------------------------


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


class FakeResponses:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert str(request.url) == chatgpt_plan.RESPONSES_URL
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def brain_env(plan, monkeypatch):
    _signed_in(plan)
    plan.update_meta(model="gpt-a")
    monkeypatch.setattr(chatgpt_plan_auth, "_auth", plan)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-never-be-sent")
    sleeps: list[float] = []

    async def no_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(chatgpt_plan.asyncio, "sleep", no_sleep)
    real = httpx.AsyncClient

    def install(replies: list[Any]) -> FakeResponses:
        server = FakeResponses(replies)

        def factory(**kwargs: Any) -> httpx.AsyncClient:
            return real(transport=httpx.MockTransport(server.handler), **kwargs)

        monkeypatch.setattr(chatgpt_plan.httpx, "AsyncClient", factory)
        return server

    return install, sleeps


def _req() -> BrainRequest:
    return BrainRequest(
        system="Be brief.",
        messages=[
            BrainMessage(role="system", content="Extra rule."),
            BrainMessage(role="user", content="Antworte exakt: DODAIOS-SIWC-OK"),
        ],
    )


async def _collect(brain: chatgpt_plan.ChatGPTPlanBrain) -> list[Any]:
    return [d async for d in brain.complete(_req())]


def _completed() -> httpx.Response:
    return httpx.Response(200, content=_sse({"type": "response.completed", "response": {}}))


def test_body_is_minimal_and_stateless() -> None:
    assert chatgpt_plan.build_body(_req(), "gpt-a") == {
        "model": "gpt-a",
        "input": [{"role": "user", "content": "Antworte exakt: DODAIOS-SIWC-OK"}],
        "store": False,
        "stream": True,
        "instructions": "Be brief.\n\nExtra rule.",
    }


def test_streaming_turn_completes(brain_env) -> None:
    install, _ = brain_env
    server = install(
        [
            httpx.Response(
                200,
                content=_sse(
                    {"type": "response.output_text.delta", "delta": "DODAIOS-"},
                    {"type": "response.output_text.delta", "delta": "SIWC-OK"},
                    {"type": "response.completed", "response": {}},
                ),
            )
        ]
    )
    deltas = asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain("chatgpt-plan/gpt-a")))
    assert "".join(d.content or "" for d in deltas) == "DODAIOS-SIWC-OK"
    assert deltas[-1].finish_reason == "stop"
    req = server.requests[0]
    assert req.headers["authorization"] == "Bearer at-old"
    sent = json.loads(req.content)
    assert sent["store"] is False and sent["stream"] is True and sent["model"] == "gpt-a"


def test_failed_event_maps_code(brain_env) -> None:
    install, _ = brain_env
    install(
        [
            httpx.Response(
                200,
                content=_sse(
                    {
                        "type": "response.failed",
                        "response": {
                            "error": {"code": "subscription_sharing_usage_limit_exceeded"}
                        },
                    }
                ),
            )
        ]
    )
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "subscription_sharing_usage_limit_exceeded"


def test_not_eligible_admission_is_not_retried(brain_env) -> None:
    install, sleeps = brain_env
    server = install(
        [
            httpx.Response(
                403,
                json={"error": {"code": "subscription_sharing_user_not_eligible"}},
                headers={"x-request-id": "req-1"},
            )
        ]
    )
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "subscription_sharing_user_not_eligible"
    assert exc.value.request_id == "req-1"
    assert len(server.requests) == 1 and not sleeps


def test_503_admission_retries_then_succeeds(brain_env) -> None:
    install, sleeps = brain_env
    server = install([httpx.Response(503, json={}), _completed()])
    asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert len(server.requests) == 2 and sleeps == [1.0]


def test_stream_without_completed_is_never_resubmitted(brain_env) -> None:
    install, _ = brain_env
    server = install(
        [httpx.Response(200, content=_sse({"type": "response.output_text.delta", "delta": "x"}))]
    )
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "incomplete_stream"
    assert len(server.requests) == 1


def test_broken_send_is_ambiguous_and_not_resent(brain_env) -> None:
    install, _ = brain_env
    server = install([httpx.ReadError("reset")])
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "submission_ambiguous"
    assert len(server.requests) == 1


def test_abort_closes_stream_without_resend(brain_env) -> None:
    install, _ = brain_env
    server = install(
        [
            httpx.Response(
                200,
                content=_sse(
                    {"type": "response.output_text.delta", "delta": "a"},
                    {"type": "response.output_text.delta", "delta": "b"},
                    {"type": "response.completed", "response": {}},
                ),
            )
        ]
    )

    async def first_then_abort() -> str:
        gen = chatgpt_plan.ChatGPTPlanBrain().complete(_req())
        first = await gen.__anext__()
        await gen.aclose()
        return first.content or ""

    assert asyncio.run(first_then_abort()) == "a"
    assert len(server.requests) == 1


def test_no_api_key_fallback_when_signed_out(brain_env, plan) -> None:
    install, _ = brain_env
    server = install([])
    plan.logout()
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "not_signed_in"
    assert not server.requests


def test_api_key_is_never_sent(brain_env) -> None:
    install, _ = brain_env
    server = install([_completed()])
    asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    for req in server.requests:
        assert "sk-must-never-be-sent" not in str(req.headers)
        assert b"sk-must-never-be-sent" not in req.content


def test_missing_plan_scope_blocks_turn(brain_env, plan) -> None:
    install, _ = brain_env
    server = install([])
    _signed_in(plan, scope="openid profile email offline_access")
    with pytest.raises(ChatGPTPlanError) as exc:
        asyncio.run(_collect(chatgpt_plan.ChatGPTPlanBrain()))
    assert exc.value.code == "plan_scope_missing"
    assert not server.requests
