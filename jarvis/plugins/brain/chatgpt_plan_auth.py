"""Sign in with ChatGPT: OAuth, token storage and the model catalog.

The ``chatgpt-plan`` brain runs turns on the user's own ChatGPT plan through
OpenAI's public Sign in with ChatGPT flow (token sharing for open-source
agents). This module owns everything except inference:

* authorization code + PKCE (S256) in the system browser, with a loopback
  listener on ``http://127.0.0.1:<port>/auth/callback`` started before the
  browser opens; a fresh ``state``, ``nonce`` and verifier every attempt;
* the first sign-in registers with ``client_id=dynamic_agent_client`` and the
  callback returns the issued ``oaiapp_...`` id, which is stored and reused;
  ``dynamic_agent_client`` itself is never stored;
* ID-token validation against the issuer's JWKS (signature, ``iss``, ``aud``,
  ``exp``, ``nonce``); ``sub`` is the identity and must match on reauth;
* refresh under a cross-process file lock, re-reading the store inside it, and
  revocation on sign-out.

Storage: one JSON file under the user data dir, written atomically (temp file +
replace) with mode 0600. Not the OS keyring: the Windows credential vault caps a
blob at about 2.5 KB and the three JWTs together are larger. Nothing here logs a
token, and any URL that carries ``id_token_hint`` is redacted before logging.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt

log = logging.getLogger(__name__)

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
MODELS_URL = f"{RESOURCE}/models"
DYNAMIC_CLIENT = "dynamic_agent_client"
AGENT_NAME = "Dodaios"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
CALLBACK_PATH = "/auth/callback"
USAGE_URL = "https://chatgpt.com/settings/usage"
LOGIN_TIMEOUT_S = 600.0
REFRESH_MARGIN_S = 120.0
LOCK_TIMEOUT_S = 30.0
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_RETRY_DELAYS = (0.5, 1.5, 4.0)

# Refresh codes after which only a new sign-in helps (token-reference).
REAUTH_CODES = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)

_SECRET_PARAMS = re.compile(
    r"((?:id_token_hint|code|code_verifier|refresh_token|access_token|id_token|token)=)[^&\s]+"
)


class ChatGPTPlanError(RuntimeError):
    """A typed sign-in or plan failure; ``code`` drives the UI and recovery."""

    def __init__(
        self, code: str, message: str, *, status: int | None = None, request_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id


def redact(text: str) -> str:
    """Strip token-bearing query/form values (``id_token_hint`` included)."""
    return _SECRET_PARAMS.sub(r"\1[redacted]", text)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """``(verifier, S256 challenge)``, base64url without padding."""
    verifier = _b64url(secrets.token_bytes(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


# ---- storage ---------------------------------------------------------------


def store_dir() -> Path:
    from jarvis.core.paths import user_data_dir  # noqa: PLC0415 — lazy, off the boot path

    return user_data_dir() / "data" / "chatgpt_plan"


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """A blocking cross-process lock on *path*, given up after *timeout*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")  # noqa: SIM115 — closed in finally
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt  # noqa: PLC0415

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl  # noqa: PLC0415

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:  # lock held by another process: wait and retry until the deadline
                if time.monotonic() >= deadline:
                    raise ChatGPTPlanError(
                        "lock_timeout", "The ChatGPT sign-in store is busy."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Unlocking a lock we never got; closing the handle releases it anyway.
            log.debug("chatgpt-plan: lock release skipped")
        fh.close()


class Store:
    """The account file (metadata + tokens) and its lock."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root or store_dir()

    @property
    def path(self) -> Path:
        return self.root / "account.json"

    def lock(self) -> contextlib.AbstractContextManager[None]:
        return file_lock(self.root / "account.lock")

    def read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # no store yet simply means signed out
            return {}
        except (OSError, ValueError):
            log.warning("chatgpt-plan: the account file is unreadable; treating it as signed out")
            return {}
        return data if isinstance(data, dict) else {}

    def write(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".account-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def host_id(self) -> str:
        """The per-install ``ext_agent_host_id``, created before the first sign-in."""
        with self.lock():
            data = self.read()
            host = data.get("ext_agent_host_id")
            if not isinstance(host, str) or not host.startswith("urn:uuid:"):
                host = f"urn:uuid:{uuid.uuid4()}"
                data["ext_agent_host_id"] = host
                self.write(data)
            return host


# ---- HTTP ------------------------------------------------------------------

ClientFactory = Callable[[], httpx.Client]


_POOL: Any = None


def _default_client() -> httpx.Client:
    global _POOL
    if _POOL is None:
        from jarvis.core.http_pool import SyncHttpClientPool  # noqa: PLC0415

        _POOL = SyncHttpClientPool(timeout_s=20.0)
    return _POOL.client()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _error_code(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:  # a non-JSON error body carries no code; the caller maps by status
        return ""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("type") or "")
    return str(err or body.get("code") or "")


def _post_form(client: httpx.Client, url: str, data: dict[str, str]) -> httpx.Response:
    """POST with bounded backoff on network errors and 5xx; 4xx returns at once."""
    last: Exception | None = None
    for delay in (0.0, *_RETRY_DELAYS):
        if delay:
            _sleep(delay)
        try:
            resp = client.post(url, data=data, timeout=HTTP_TIMEOUT)
        except httpx.HTTPError as exc:  # kept in last and raised once retries run out
            last = exc
            continue
        if resp.status_code < 500:
            return resp
        last = ChatGPTPlanError(
            "server_error",
            f"{urlparse(url).path} returned {resp.status_code}",
            status=resp.status_code,
        )
    if isinstance(last, ChatGPTPlanError):
        raise last
    raise ChatGPTPlanError("network", f"{urlparse(url).netloc} is not reachable.") from last


# ---- ID token --------------------------------------------------------------


@dataclass
class Discovery:
    jwks_uri: str
    revocation_endpoint: str


def discover(client: httpx.Client) -> Discovery:
    resp = client.get(DISCOVERY_URL, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    doc = resp.json()
    return Discovery(
        jwks_uri=str(doc["jwks_uri"]), revocation_endpoint=str(doc.get("revocation_endpoint") or "")
    )


def validate_id_token(
    id_token: str, *, jwks: dict[str, Any], client_id: str, nonce: str | None
) -> dict[str, Any]:
    """Check signature, issuer, audience, expiry and nonce; return the claims."""
    try:
        kid = jwt.get_unverified_header(id_token).get("kid")
        keys = jwt.PyJWKSet.from_dict(jwks).keys
        key = next((k for k in keys if kid is None or k.key_id == kid), None)
        if key is None:
            raise ChatGPTPlanError("id_token_invalid", "The ID token's signing key is unknown.")
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256", "ES256", "PS256"],
            audience=client_id,
            issuer=ISSUER,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ChatGPTPlanError("id_token_expired", "The ID token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise ChatGPTPlanError(
            "id_token_invalid", f"The ID token is invalid: {type(exc).__name__}"
        ) from exc
    if nonce is not None and claims.get("nonce") != nonce:
        raise ChatGPTPlanError(
            "nonce_mismatch", "The ID token answers a different sign-in attempt."
        )
    return claims


# ---- sign-in ---------------------------------------------------------------


@dataclass
class Attempt:
    state: str
    nonce: str
    verifier: str
    redirect_uri: str
    client_id: str
    reauth: bool
    created: float = field(default_factory=time.monotonic)


def build_authorize_url(
    attempt: Attempt,
    *,
    host_id: str,
    challenge: str,
    id_token_hint: str | None = None,
    login_hint: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": attempt.client_id,
        "redirect_uri": attempt.redirect_uri,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": attempt.state,
        "nonce": attempt.nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "ext_agent_host_id": host_id,
    }
    if attempt.reauth:
        if id_token_hint:
            params["id_token_hint"] = id_token_hint
        if login_hint:
            params["login_hint"] = login_hint
    else:
        params["agent_name_hint"] = AGENT_NAME
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _scopes(value: Any) -> list[str]:
    return value.split() if isinstance(value, str) else []


class PlanAuth:
    """Sign-in state machine and token lifecycle for one install."""

    def __init__(
        self,
        store: Store | None = None,
        client: ClientFactory | None = None,
        open_browser: Callable[[str], Any] | None = None,
    ) -> None:
        self.store = store or Store()
        self._client = client or _default_client
        self._open = open_browser or webbrowser.open
        self._attempt: Attempt | None = None
        self._server: http.server.ThreadingHTTPServer | None = None
        self._login_state = "idle"  # idle | pending | denied | failed
        self._login_error = ""
        self._mu = threading.Lock()
        self._discovery: Discovery | None = None

    # -- status ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """UI view of the account; never contains a token."""
        data = self.store.read()
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else None
        scopes = _scopes(data.get("scope"))
        signed_in = bool(tokens and tokens.get("refresh_token"))
        with self._mu:
            login_state, login_error = self._login_state, self._login_error
        return {
            "signed_in": signed_in,
            "account": data.get("email") or data.get("name") or "",
            "plan_enabled": signed_in and PLAN_SCOPE in scopes,
            "model": data.get("model") or "",
            "registered": bool(data.get("client_id")),
            "notice_seen": bool(data.get("notice_seen")),
            "login": login_state,
            "error": login_error,
            "usage_url": USAGE_URL,
        }

    def connected(self) -> bool:
        s = self.status()
        return bool(s["signed_in"] and s["plan_enabled"])

    def update_meta(self, **values: Any) -> None:
        """Store non-sensitive settings (model, notice_seen)."""
        with self.store.lock():
            data = self.store.read()
            data.update(values)
            self.store.write(data)

    # -- authorize --------------------------------------------------------

    def start_login(self, *, reauth: bool = False) -> str:
        """Open the listener, then the browser; return the (redacted) authorize URL."""
        host_id = self.store.host_id()
        data = self.store.read()
        client_id = data.get("client_id") if isinstance(data.get("client_id"), str) else ""
        if reauth and not client_id:
            reauth = False
        self._stop_server()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        port = server.server_address[1]
        verifier, challenge = pkce_pair()
        attempt = Attempt(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            verifier=verifier,
            redirect_uri=f"http://127.0.0.1:{port}{CALLBACK_PATH}",
            client_id=client_id if reauth else DYNAMIC_CLIENT,
            reauth=reauth,
        )
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        url = build_authorize_url(
            attempt,
            host_id=host_id,
            challenge=challenge,
            id_token_hint=tokens.get("id_token") if reauth else None,
            login_hint=data.get("email") if reauth else None,
        )
        with self._mu:
            self._attempt = attempt
            self._server = server
            self._login_state, self._login_error = "pending", ""
        threading.Thread(
            target=server.serve_forever, name="chatgpt-plan-callback", daemon=True
        ).start()
        threading.Timer(LOGIN_TIMEOUT_S, self._expire, args=(attempt.state,)).start()
        self._open(url)
        log.info("chatgpt-plan: sign-in opened in the browser (%s)", redact(url))
        return redact(url)

    def _expire(self, state: str) -> None:
        with self._mu:
            if self._attempt and self._attempt.state == state:
                self._attempt = None
                self._login_state, self._login_error = "failed", "login_timeout"
        self._stop_server()

    def _stop_server(self) -> None:
        with self._mu:
            server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=_shutdown, args=(server,), daemon=True).start()

    def handle_callback(self, query: dict[str, str]) -> tuple[bool, str]:
        """Finish an attempt from the callback query; ``(ok, user message)``."""
        with self._mu:
            attempt = self._attempt
        if attempt is None or not secrets.compare_digest(query.get("state", ""), attempt.state):
            return False, "This sign-in link is stale or was not started by Dodaios."
        with self._mu:
            self._attempt = None
        try:
            if query.get("error"):
                code = query["error"]
                self._finish("denied" if code == "access_denied" else "failed", code)
                return (
                    False,
                    "Sign-in was cancelled."
                    if code == "access_denied"
                    else f"Sign-in failed: {code}",
                )
            self._complete(attempt, query)
        except ChatGPTPlanError as exc:
            log.warning("chatgpt-plan: sign-in failed (%s)", exc.code)
            self._finish("failed", exc.code)
            return False, f"Sign-in failed: {exc}"
        self._finish("idle", "")
        return True, "Signed in. You can close this tab and return to Dodaios."

    def _finish(self, state: str, error: str) -> None:
        with self._mu:
            self._login_state, self._login_error = state, error
        self._stop_server()

    def _complete(self, attempt: Attempt, query: dict[str, str]) -> None:
        code = query.get("code") or ""
        if not code:
            raise ChatGPTPlanError("no_code", "The callback carried no authorization code.")
        stored = self.store.read()
        known = stored.get("client_id") if isinstance(stored.get("client_id"), str) else ""
        returned = query.get("client_id") or ""
        if attempt.reauth:
            if returned and returned != known:
                raise ChatGPTPlanError("client_mismatch", "The callback names a different client.")
            client_id = known
        else:
            if not returned or returned == DYNAMIC_CLIENT:
                raise ChatGPTPlanError(
                    "registration_incomplete", "OpenAI did not issue a client id; sign in again."
                )
            client_id = returned
        client = self._client()
        resp = _post_form(
            client,
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": attempt.verifier,
                "redirect_uri": attempt.redirect_uri,
                "resource": RESOURCE,
            },
        )
        if resp.status_code != 200:
            err = _error_code(resp)
            raise ChatGPTPlanError(
                "invalid_grant" if err == "invalid_grant" else "token_exchange_failed",
                f"The token exchange failed ({resp.status_code} {err}).".strip(),
                status=resp.status_code,
            )
        tokens = resp.json()
        claims = validate_id_token(
            str(tokens.get("id_token") or ""),
            jwks=self._jwks(client),
            client_id=client_id,
            nonce=attempt.nonce,
        )
        with self.store.lock():
            data = self.store.read()
            if attempt.reauth and data.get("sub") and data["sub"] != claims["sub"]:
                raise ChatGPTPlanError(
                    "account_mismatch", "Reauthorize with the same ChatGPT account."
                )
            if data.get("sub") and data["sub"] != claims["sub"]:
                data.pop("model", None)  # another account: its catalog differs
            data.update(
                {
                    "client_id": client_id,
                    "sub": claims["sub"],
                    "email": claims.get("email") or "",
                    "name": claims.get("name") or "",
                    "scope": tokens.get("scope") or "",
                    "tokens": _token_record(tokens),
                }
            )
            self.store.write(data)

    def _jwks(self, client: httpx.Client) -> dict[str, Any]:
        resp = client.get(self.discovery(client).jwks_uri, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def discovery(self, client: httpx.Client | None = None) -> Discovery:
        if self._discovery is None:
            self._discovery = discover(client or self._client())
        return self._discovery

    # -- tokens -----------------------------------------------------------

    def access_token(self, *, force_refresh: bool = False) -> str:
        """A valid access token, refreshed under the cross-process lock if due."""
        data = self.store.read()
        tok = _tokens_of(data)
        if not force_refresh and _fresh(tok):
            return str(tok["access_token"])
        with self.store.lock():
            data = self.store.read()  # another process may have refreshed meanwhile
            tok = _tokens_of(data)
            if not force_refresh and _fresh(tok):
                return str(tok["access_token"])
            if not tok.get("refresh_token") or not data.get("client_id"):
                raise ChatGPTPlanError("not_signed_in", "Sign in with ChatGPT first.")
            resp = _post_form(
                self._client(),
                TOKEN_URL,
                {
                    "grant_type": "refresh_token",
                    "client_id": str(data["client_id"]),
                    "refresh_token": str(tok["refresh_token"]),
                    "resource": RESOURCE,
                },
            )
            if resp.status_code != 200:
                err = _error_code(resp)
                if err == "invalid_client":
                    raise ChatGPTPlanError(
                        "invalid_client",
                        "OpenAI rejected the Dodaios client id.",
                        status=resp.status_code,
                    )
                if err in REAUTH_CODES or resp.status_code in (400, 401):
                    data.pop("tokens", None)
                    self.store.write(data)
                    raise ChatGPTPlanError(
                        "reauthorization_required",
                        "Your ChatGPT sign-in expired; reauthorize.",
                        status=resp.status_code,
                    )
                raise ChatGPTPlanError(
                    "refresh_failed",
                    f"Token refresh failed ({resp.status_code}).",
                    status=resp.status_code,
                )
            fresh = resp.json()
            record = _token_record(fresh, previous=tok)
            data["tokens"] = record
            if fresh.get("scope"):
                data["scope"] = fresh["scope"]
            self.store.write(data)
            return str(record["access_token"])

    def logout(self) -> bool:
        """Revoke the refresh token, then clear tokens locally either way."""
        revoked = False
        with self.store.lock():
            data = self.store.read()
            refresh = _tokens_of(data).get("refresh_token")
            client_id = data.get("client_id")
            data.pop("tokens", None)
            for key in ("scope", "sub", "email", "name", "model"):
                data.pop(key, None)
            self.store.write(data)
        if refresh and client_id:
            try:
                client = self._client()
                endpoint = self.discovery(client).revocation_endpoint
                if endpoint:
                    resp = _post_form(
                        client,
                        endpoint,
                        {
                            "token": str(refresh),
                            "token_type_hint": "refresh_token",
                            "client_id": str(client_id),
                        },
                    )
                    revoked = resp.status_code == 200
            except (ChatGPTPlanError, httpx.HTTPError) as exc:
                # Local sign-out already happened; the token expires server-side.
                log.warning("chatgpt-plan: revocation failed (%s)", type(exc).__name__)
        return revoked

    # -- models -----------------------------------------------------------

    def models(self) -> list[dict[str, str]]:
        """The account's listed models, in server order."""
        token = self.access_token()
        resp = self._client().get(
            MODELS_URL, headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT
        )
        if resp.status_code != 200:
            raise ChatGPTPlanError(
                "models_failed",
                f"The model list failed ({resp.status_code}).",
                status=resp.status_code,
                request_id=resp.headers.get("x-request-id"),
            )
        return parse_models(resp.json())


def parse_models(payload: Any) -> list[dict[str, str]]:
    rows = payload.get("models") if isinstance(payload, dict) else None
    out: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("visibility") != "list":
            continue
        slug = row.get("slug")
        if isinstance(slug, str) and slug:
            out.append({"slug": slug, "display_name": str(row.get("display_name") or slug)})
    return out


def _tokens_of(data: dict[str, Any]) -> dict[str, Any]:
    tok = data.get("tokens")
    return tok if isinstance(tok, dict) else {}


def _fresh(tok: dict[str, Any]) -> bool:
    if not tok.get("access_token"):
        return False
    now = time.time()
    if now >= float(tok.get("expires_at") or 0) - REFRESH_MARGIN_S:
        return False
    # earliest_refresh_at only says when a refresh is allowed; a valid token stays in use.
    return True


def _token_record(tokens: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    prev = previous or {}
    now = time.time()
    return {
        "access_token": tokens.get("access_token") or "",
        # A refresh response rotates the refresh token; keep the old one only if none came back.
        "refresh_token": tokens.get("refresh_token") or prev.get("refresh_token") or "",
        "id_token": tokens.get("id_token") or prev.get("id_token") or "",
        "expires_at": now + float(tokens.get("expires_in") or 3600),
        "earliest_refresh_at": tokens.get("earliest_refresh_at"),
    }


# ---- loopback callback -----------------------------------------------------

_PAGE = (
    "<!doctype html><meta charset=utf-8><title>Dodaios</title>"
    "<body style='font-family:system-ui;padding:3rem'><p>{}</p></body>"
)


def _shutdown(server: http.server.ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _handler_for(auth: PlanAuth) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — stdlib hook name
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return
            query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
            ok, message = auth.handle_callback(query)
            body = _PAGE.format(message.replace("<", "&lt;")).encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # The request line carries the authorization code; never log it raw.
            log.debug("chatgpt-plan callback: %s", redact(format % args))

    return Handler


_auth: PlanAuth | None = None


def auth() -> PlanAuth:
    global _auth
    if _auth is None:
        _auth = PlanAuth()
    return _auth
