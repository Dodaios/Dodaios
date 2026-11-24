"""FastAPI routes for the Twilio telephony voice agent (contract section 4).

Base path: ``/api/telephony``.

Twilio-facing (not consumed by the UI):
  * ``POST /api/telephony/voice`` — Voice webhook; validates signature; returns
    TwiML ``<Connect><Stream>`` pointing at the media socket.
  * ``WS  /api/telephony/media``  — Media Streams socket; bridges the call to
    a realtime speech-to-speech session (``dodaios.telephony.call``).

UI-facing JSON:
  * ``GET  /api/telephony/status``
  * ``GET  /api/telephony/config``
  * ``POST /api/telephony/config``
  * ``POST /api/telephony/credentials``
  * ``POST /api/telephony/test``
  * ``POST /api/telephony/selftest``
  * ``GET  /api/telephony/calls``
  * ``GET  /api/telephony/scripts``

Graceful degradation (AD-T8): when the ``twilio`` SDK is not importable the
endpoints return ``200`` with ``available=false`` flags rather than crashing.
Mutating endpoints return ``409`` with ``{"error": ...}`` when prerequisites
are missing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, cast

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dodaios.core import config as cfg_mod
from dodaios.core.config import get_secret, set_secret
from dodaios.telephony import is_available
from dodaios.telephony.call import PhoneCall
from dodaios.telephony.constants import (
    CALL_COMPLETED,
    CALL_IN_PROGRESS,
    CallStatusLiteral,
)
from dodaios.telephony.provisioning import TelephonyProvisionError
from dodaios.telephony.security import (
    caller_allowed,
    constant_time_equals,
    generate_call_secret,
    normalize_caller,
    public_url_for,
    public_wss_url,
    validate_twilio_signature,
)
from dodaios.telephony.status import CallRecord, TelephonyManager
from dodaios.telephony.twiml import build_connect_stream_twiml, build_reject_twiml
from dodaios.ui.web.error_text import internal_error

log = logging.getLogger("dodaios.telephony.routes")

router = APIRouter(prefix="/api/telephony", tags=["telephony"])

_AUTH_TOKEN_KEY = "twilio_auth_token"  # noqa: S105 - credential-manager key name, not a value
_AUTH_TOKEN_ENV = "TWILIO_AUTH_TOKEN"  # noqa: S105 - ENV var name, not a value

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_URL_RE = re.compile(r"^https?://[^\s/]+(?:/.*)?$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_cfg(request: Request):
    cfg_attr = getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)
    if cfg_attr is not None:
        return cfg_attr
    try:
        return cfg_mod.load_config()
    except Exception:  # noqa: BLE001
        return None


def _twilio_cfg(request: Request):
    cfg = _resolve_cfg(request)
    if cfg is None:
        from dodaios.core.config import TwilioConfig

        return TwilioConfig()
    integrations = getattr(cfg, "integrations", None)
    twilio = getattr(integrations, "twilio", None)
    if twilio is None:
        from dodaios.core.config import TwilioConfig

        return TwilioConfig()
    return twilio


def _manager(request: Request) -> TelephonyManager:
    mgr = getattr(request.app.state, "telephony_manager", None)
    if mgr is None:
        mgr = TelephonyManager()
        request.app.state.telephony_manager = mgr
    return mgr


def _auth_token() -> str | None:
    return get_secret(_AUTH_TOKEN_KEY, _AUTH_TOKEN_ENV)


def _mask_sid(sid: str) -> str:
    if not sid:
        return ""
    if len(sid) <= 6:
        return "AC" + "•" * 4
    return sid[:2] + "•" * 6 + sid[-4:]


def _call_voice_info(request: Request) -> tuple[str, str]:
    """The realtime engine a phone call talks through, and its configured voice.

    Phone calls run only on realtime speech-to-speech; the selected realtime
    provider and its voice are what the caller hears. Empty when none is set.
    """
    cfg = _resolve_cfg(request)
    brain = getattr(cfg, "brain", None)
    provider = str(getattr(getattr(brain, "realtime", None), "provider", "") or "")
    settings = (getattr(brain, "providers", None) or {}).get(provider) if provider else None
    voice = str(getattr(settings, "voice", "") or "")
    return provider, voice


def _phone_ready(cfg: Any) -> bool:
    """Whether a realtime session could hold a phone call (reads credentials)."""
    if cfg is None:
        return False
    try:
        from dodaios.realtime.factory import realtime_phone_ready

        return realtime_phone_ready(cfg)
    except Exception:  # noqa: BLE001 - an unreadable stack cannot hold a call
        log.warning("telephony: realtime readiness could not be read", exc_info=True)
        return False


# Spoken by Twilio itself (TwiML <Say>) when no realtime voice can hold the call.
_NO_REALTIME_VOICE = (
    "Sorry, the assistant cannot talk on the phone right now: no live voice "
    "connection that can serve a phone line is set up."
)


def _apply_live_twilio_updates(request: Request, updates: dict[str, object]) -> None:
    """Mutate the SHARED live config's twilio block in place.

    ``post_config``/``post_credentials`` persist to ``jarvis.toml`` on disk,
    but ``request.app.state.config`` (the same object ``WebServer`` holds as
    ``self.cfg``, assigned once at boot) was never updated to match — so the
    live voice webhook and media-socket handlers, which read
    ``request.app.state.config`` directly, kept serving the STALE values
    until a full app restart even though the write to disk succeeded.

    Deliberately mutates fields on the EXISTING ``TwilioConfig`` instance
    rather than reassigning ``request.app.state.config`` to a freshly loaded
    one: ``WebServer`` holds its own reference to that same object, and
    swapping it here would only create a NEW split brain between the two.
    """
    cfg = _resolve_cfg(request)
    twilio = getattr(getattr(cfg, "integrations", None), "twilio", None)
    if twilio is None:
        return
    for field, value in updates.items():
        if hasattr(twilio, field):
            setattr(twilio, field, value)


def _config_payload(twilio, *, auth_token_set: bool) -> dict[str, object]:
    return {
        "enabled": bool(getattr(twilio, "enabled", False)),
        "account_sid": getattr(twilio, "account_sid", "") or "",
        "phone_number": getattr(twilio, "phone_number", "") or "",
        "allowed_callers": [str(n) for n in getattr(twilio, "allowed_callers", None) or []],
        "public_base_url": getattr(twilio, "public_base_url", "") or "",
        "greeting": getattr(twilio, "greeting", "") or "",
        "language_code": getattr(twilio, "language_code", "de-DE") or "de-DE",
        "fallback_mode": getattr(twilio, "fallback_mode", "media") or "media",
        "max_call_seconds": int(getattr(twilio, "max_call_seconds", 600) or 600),
        "auth_token_set": auth_token_set,
    }


# ---------------------------------------------------------------------------
# UI-facing: status / config / credentials
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status(request: Request) -> JSONResponse:
    twilio = _twilio_cfg(request)
    mgr = _manager(request)
    token = _auth_token()
    available = is_available()
    account_sid = getattr(twilio, "account_sid", "") or ""
    phone_number = getattr(twilio, "phone_number", "") or ""
    public_base_url = getattr(twilio, "public_base_url", "") or ""
    configured = bool(account_sid and phone_number and token)
    # Kept under the established wire keys: the voice a call speaks with.
    tts_provider, tts_voice = _call_voice_info(request)
    webhook_url = public_url_for(public_base_url, "/api/telephony/voice") if public_base_url else ""
    return JSONResponse(
        {
            "available": available,
            "configured": configured,
            "enabled": bool(getattr(twilio, "enabled", False)),
            "account_sid_masked": _mask_sid(account_sid),
            "phone_number": phone_number,
            "public_base_url": public_base_url,
            "webhook_url": webhook_url,
            "auth_token_set": bool(token),
            "twilio_reachable": mgr.reachable,
            "twilio_error": mgr.reachable_error,
            "tts_provider": tts_provider,
            "tts_voice": tts_voice,
            "active_calls": mgr.active_calls,
            "max_call_seconds": int(getattr(twilio, "max_call_seconds", 600) or 600),
        }
    )


@router.get("/config")
async def get_config(request: Request) -> JSONResponse:
    twilio = _twilio_cfg(request)
    return JSONResponse(_config_payload(twilio, auth_token_set=bool(_auth_token())))


class ConfigUpdate(BaseModel):
    enabled: bool | None = None
    phone_number: str | None = None
    allowed_callers: list[str] | None = Field(default=None, max_length=50)
    public_base_url: str | None = None
    greeting: str | None = None
    language_code: str | None = None
    max_call_seconds: int | None = Field(default=None, ge=10, le=7200)


@router.post("/config")
async def post_config(request: Request, body: ConfigUpdate) -> JSONResponse:
    updates: dict[str, object] = {}
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.phone_number is not None:
        pn = body.phone_number.strip()
        if pn and not _E164_RE.match(pn):
            return JSONResponse(
                {"error": "phone_number must be E.164, e.g. +49301234567"},
                status_code=422,
            )
        updates["phone_number"] = pn
    if body.allowed_callers is not None:
        callers: list[str] = []
        for entry in body.allowed_callers:
            number = normalize_caller(entry)
            if not _E164_RE.match(number):
                return JSONResponse(
                    {"error": "allowed_callers must be E.164 numbers, e.g. +4915112345678"},
                    status_code=422,
                )
            if number not in callers:
                callers.append(number)
        updates["allowed_callers"] = callers
    if body.public_base_url is not None:
        url = body.public_base_url.strip().rstrip("/")
        if url and not _URL_RE.match(url):
            return JSONResponse(
                {"error": "public_base_url must be an http(s) URL"},
                status_code=422,
            )
        updates["public_base_url"] = url
    if body.greeting is not None:
        updates["greeting"] = body.greeting.strip()
    if body.language_code is not None:
        updates["language_code"] = body.language_code.strip() or "de-DE"
    if body.max_call_seconds is not None:
        updates["max_call_seconds"] = int(body.max_call_seconds)

    if updates:
        try:
            from dodaios.core.config_writer import set_telephony_config

            set_telephony_config(updates)
        except FileNotFoundError:
            return JSONResponse(
                {"error": "jarvis.toml not found; cannot persist config"},
                status_code=409,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": internal_error("config write", exc, logger=log)}, status_code=409
            )
        # The disk write succeeded — mirror it onto the live shared config so
        # the webhook / media-socket handlers see it immediately (Bug: config
        # split-brain, see _apply_live_twilio_updates).
        _apply_live_twilio_updates(request, updates)

    # Re-read so the response reflects the freshly persisted values.
    try:
        fresh = cfg_mod.load_config()
        twilio = fresh.integrations.twilio
    except Exception:  # noqa: BLE001
        twilio = _twilio_cfg(request)
    return JSONResponse(_config_payload(twilio, auth_token_set=bool(_auth_token())))


class CredentialsUpdate(BaseModel):
    account_sid: str | None = None
    auth_token: str | None = None


@router.post("/credentials")
async def post_credentials(request: Request, body: CredentialsUpdate) -> JSONResponse:
    # Tracked so a partial commit (one half saved, the other failed) can be
    # reported honestly instead of a bare 409 that hides the half that DID
    # succeed. None = "not requested in this call".
    token_saved: bool | None = None
    sid_saved: bool | None = None

    if body.auth_token is not None and body.auth_token.strip():
        token_saved = set_secret(_AUTH_TOKEN_KEY, body.auth_token.strip())
        if not token_saved:
            return JSONResponse(
                {
                    "error": "could not store auth token in the credential manager",
                    "token_saved": False,
                    "sid_saved": sid_saved,
                },
                status_code=409,
            )
    if body.account_sid is not None and body.account_sid.strip():
        sid = body.account_sid.strip()
        if not sid.startswith("AC"):
            return JSONResponse(
                {
                    "error": "account_sid must start with 'AC'",
                    "token_saved": token_saved,
                    "sid_saved": False,
                },
                status_code=422,
            )
        try:
            from dodaios.core.config_writer import set_telephony_config

            set_telephony_config({"account_sid": sid})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "error": internal_error("config write", exc, logger=log),
                    "token_saved": token_saved,
                    "sid_saved": False,
                },
                status_code=409,
            )
        sid_saved = True
        _apply_live_twilio_updates(request, {"account_sid": sid})

    twilio = _twilio_cfg(request)
    try:
        fresh = cfg_mod.load_config()
        sid_now = fresh.integrations.twilio.account_sid
        phone_now = fresh.integrations.twilio.phone_number
    except Exception:  # noqa: BLE001
        sid_now = getattr(twilio, "account_sid", "")
        phone_now = getattr(twilio, "phone_number", "")
    configured = bool(sid_now and phone_now and _auth_token())
    return JSONResponse(
        {
            "ok": True,
            "configured": configured,
            "token_saved": token_saved,
            "sid_saved": sid_saved,
        }
    )


@router.post("/test")
async def post_test(request: Request) -> JSONResponse:
    if not is_available():
        return JSONResponse(
            {
                "ok": False,
                "reachable": False,
                "error": "twilio package not installed (pip install -e .[telephony])",
            }
        )
    # M3: prefer credentials typed in the form body (test-before-save) over the
    # persisted ones, so clicking Test with fresh creds validates THOSE — not stale
    # or absent saved values that read as a broken key.
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:  # noqa: BLE001 — no/empty body → fall back to persisted
        body = {}
    twilio = _twilio_cfg(request)
    account_sid = str(body.get("account_sid") or "").strip() or (
        getattr(twilio, "account_sid", "") or ""
    )
    token = str(body.get("auth_token") or "").strip() or _auth_token()
    mgr = _manager(request)
    # M4: honest five-layer status (PROVIDER_TEST_STATUSES) instead of a binary
    # ok/failed — bad SID, unfunded/suspended account, and an outage are different.
    # The status is classified inside provisioning (TelephonyProvisionError.status)
    # so Twilio's raw response text never reaches this payload.
    if not account_sid or not token:
        mgr.set_reachable(False, "account_sid or auth_token missing")
        return JSONResponse(
            {
                "ok": False,
                "reachable": False,
                "status": "not_configured",
                "error": "account_sid or auth_token missing",
            }
        )
    try:
        from dodaios.telephony.provisioning import verify_credentials

        info = verify_credentials(account_sid, token)
        mgr.set_reachable(True, None)
        return JSONResponse(
            {
                "ok": True,
                "reachable": True,
                "status": "ok",
                "account_status": info.get("account_status", ""),
            }
        )
    except TelephonyProvisionError as exc:
        # str(exc) is a clean sentence built by provisioning.sdk_failure / _client.
        message = str(exc)
        mgr.set_reachable(False, message)
        return JSONResponse(
            {
                "ok": False,
                "reachable": False,
                "status": exc.status,
                "error": message,
            }
        )
    except Exception as exc:  # noqa: BLE001
        message = internal_error("Twilio credential check", exc, logger=log)
        mgr.set_reachable(False, message)
        return JSONResponse(
            {
                "ok": False,
                "reachable": False,
                "status": "error",
                "error": message,
            }
        )


# ---------------------------------------------------------------------------
# UI-facing: selftest (no real call)
# ---------------------------------------------------------------------------


@router.post("/selftest")
async def post_selftest(request: Request) -> JSONResponse:
    """Check that a phone call could talk, without placing one.

    A call runs on a realtime speech-to-speech session, so the check is
    whether such a session could open for the phone (a provider that takes
    PCM itself, with its sign-in or key in place), plus the mu-law transcode
    a call's audio passes through. No provider connection is opened.
    """
    cfg = _resolve_cfg(request)
    ready = await asyncio.to_thread(_phone_ready, cfg)
    audio_bytes = 0
    error: str | None = None
    try:
        from dodaios.telephony.audio import pcm16_to_ulaw, resample_pcm16

        # 100 ms of 24 kHz silence -> 8 kHz mu-law: the outbound leg of a call.
        audio_bytes = len(pcm16_to_ulaw(resample_pcm16(b"\x00\x00" * 2400, 24_000, 8_000)))
    except Exception as exc:  # noqa: BLE001 - reported to the UI, never a 500
        error = f"audio: {internal_error('selftest transcode', exc, logger=log)}"
    if not ready and error is None:
        error = (
            "No live voice connection can take a phone call. Set one up under "
            "API Keys > Live calls; a connection that needs a browser cannot "
            "serve a phone line."
        )
    provider, _voice = _call_voice_info(request)
    return JSONResponse(
        {
            "ok": error is None,
            "transcript": "",
            "response_text": f"Calls talk through {provider}." if ready and provider else "",
            "audio_bytes": audio_bytes,
            "error": error,
        }
    )


# ---------------------------------------------------------------------------
# UI-facing: calls + scripts
# ---------------------------------------------------------------------------


@router.get("/calls")
async def get_calls(request: Request, limit: int = 20) -> JSONResponse:
    mgr = _manager(request)
    limit = max(1, min(limit, 200))
    return JSONResponse({"calls": mgr.recent_calls(limit)})


@router.get("/scripts")
async def get_scripts(request: Request) -> JSONResponse:
    twilio = _twilio_cfg(request)
    port = 8765
    base = getattr(twilio, "public_base_url", "") or "https://jarvis.example.com"
    webhook = public_url_for(base, "/api/telephony/voice")
    scripts = [
        {
            # M7: cross-platform tunnel command (Linux/macOS/Windows) — the
            # PowerShell script below is Windows-only and was the ONLY option
            # shown to every OS. Needs `cloudflared` installed.
            "name": "Public tunnel (portable)",
            "path": "",
            "description": (
                "Start a cloudflared tunnel to the local FastAPI port and copy the "
                "printed https URL into 'public_base_url'. Works on Linux, macOS and "
                "Windows (install cloudflared first)."
            ),
            "command": f"cloudflared tunnel --url http://localhost:{port}",
        },
        {
            "name": "Public tunnel (Windows dev)",
            "path": "scripts/telephony-tunnel.ps1",
            "description": (
                "Start a cloudflared tunnel to the local FastAPI port and print "
                "the public HTTPS URL to paste into 'public_base_url'. Home-PC "
                "development path (Windows PowerShell)."
            ),
            "command": f"pwsh scripts/telephony-tunnel.ps1 -Port {port}",
        },
        {
            "name": "Provision number",
            "path": "scripts/telephony_provision.py",
            "description": (
                "List buyable numbers, buy one, or point an owned number's voice webhook "
                "at Dodaios."
            ),
            "command": (
                "python scripts/telephony_provision.py set-webhook "
                f'--number "{getattr(twilio, "phone_number", "") or "+49..."}" '
                f'--url "{webhook}"'
            ),
        },
        {
            "name": "E2E probe",
            "path": "scripts/probe_telephony_e2e.py",
            "description": (
                "Drive the call bridge with a synthetic Twilio call against a fake "
                "realtime session and print what went each way. No real account needed."
            ),
            "command": "python scripts/probe_telephony_e2e.py",
        },
        {
            "name": "Caddy reverse proxy (VPS, recommended)",
            "path": "docs/telephony.md",
            "description": (
                "Caddyfile snippet that terminates TLS (Let's Encrypt) and proxies "
                "Twilio to the local FastAPI port. The cloud-first default path."
            ),
            # Real newlines so the UI (whitespace-pre-wrap) renders a proper
            # multi-line Caddyfile block and the copy button yields valid config.
            "command": (f"jarvis.example.com {{\n    reverse_proxy localhost:{port}\n}}"),
        },
    ]
    return JSONResponse({"scripts": scripts})


# ---------------------------------------------------------------------------
# UI-facing: place an outbound call (Chunk C)
# ---------------------------------------------------------------------------


class OutboundCall(BaseModel):
    to: str
    opening: str = ""


@router.post("/outbound", openapi_extra={"x-jarvis-dangerous": True})
async def post_outbound(request: Request, body: OutboundCall) -> JSONResponse:
    """Place a real outbound call to a raw E.164 number; speak ``opening`` first.

    Contact-agnostic seam (Chunk C): the body is a bare number, never a name —
    name resolution lives in Chunk B. Reads the Twilio config + the auth token
    (``get_secret``) and delegates to ``outbound.place_call`` (Contract 2).

    Graceful degradation (cloud-first): when the ``twilio`` extra is absent the
    route returns ``200`` with ``ok=false`` and a clear English hint rather than
    crashing; when the account is not fully configured it returns ``409``.
    """
    to = (body.to or "").strip()
    if not _E164_RE.match(to):
        return JSONResponse(
            {"ok": False, "error": "to must be E.164, e.g. +4915112345678"},
            status_code=422,
        )

    if not is_available():
        return JSONResponse(
            {
                "ok": False,
                "error": "twilio package not installed (pip install -e .[telephony])",
            }
        )

    twilio = _twilio_cfg(request)
    if not getattr(twilio, "enabled", False):
        return JSONResponse({"ok": False, "error": "Telephony is disabled."}, status_code=409)

    account_sid = getattr(twilio, "account_sid", "") or ""
    from_number = getattr(twilio, "phone_number", "") or ""
    public_base_url = getattr(twilio, "public_base_url", "") or ""
    token = _auth_token()
    if not (account_sid and from_number and public_base_url and token):
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "Telephony is not fully configured "
                    "(needs account SID, phone number, public base URL, and auth token)."
                ),
            },
            status_code=409,
        )

    try:
        from dodaios.telephony.outbound import place_call

        call_sid = place_call(
            to=to,
            opening=(body.opening or "").strip(),
            account_sid=account_sid,
            auth_token=token,
            from_number=from_number,
            public_base_url=public_base_url,
        )
    except TelephonyProvisionError as exc:
        # A clean English sentence: our own validation text, or the classified
        # summary from provisioning.sdk_failure — never Twilio's raw response.
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
    except Exception as exc:  # noqa: BLE001 - never 500 a UI button
        return JSONResponse(
            {"ok": False, "error": internal_error("outbound call", exc, logger=log)},
            status_code=409,
        )

    return JSONResponse({"ok": True, "call_sid": call_sid})


# ---------------------------------------------------------------------------
# Twilio-facing: voice webhook
# ---------------------------------------------------------------------------


@router.post("/voice")
async def post_voice(request: Request) -> Response:
    """Twilio Voice webhook: validate signature, return <Connect><Stream> TwiML."""
    twilio = _twilio_cfg(request)
    mgr = _manager(request)

    if not getattr(twilio, "enabled", False):
        return Response(
            content=build_reject_twiml("Telephony is currently disabled."),
            media_type="text/xml",
        )

    public_base_url = getattr(twilio, "public_base_url", "") or ""
    if not public_base_url:
        return Response(
            content=build_reject_twiml("Telephony is not configured."),
            media_type="text/xml",
        )

    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    # Signature validation against the PUBLIC url (AD-T9). Skipped only when an
    # explicit test override flag is set on app.state (integration tests).
    skip_check = bool(getattr(request.app.state, "telephony_skip_signature", False))
    if not skip_check:
        signature = request.headers.get("X-Twilio-Signature", "")
        public_voice_url = public_url_for(public_base_url, "/api/telephony/voice")
        # Outbound calls (Chunk C) reach this webhook with an ``?opening=…`` query
        # string; Twilio signs over the full URL incl. query. Inbound requests
        # carry no query, so this leaves the inbound signature byte-identical.
        if request.url.query:
            public_voice_url = f"{public_voice_url}?{request.url.query}"
        valid = validate_twilio_signature(
            auth_token=_auth_token(),
            signature=signature,
            url=public_voice_url,
            params=params,
        )
        if not valid:
            log.warning("telephony: rejected /voice with invalid signature")
            return Response(content=build_reject_twiml(), media_type="text/xml", status_code=403)

    call_sid = params.get("CallSid", "")
    from_number = params.get("From", "")
    to_number = params.get("To", "")

    # Outbound branch (Chunk C): a call placed via ``place_call`` reaches this same
    # webhook with ``Direction=outbound-api`` and an ``opening`` query param. We
    # bake ``direction=outbound`` + ``opening`` into the TwiML so the session
    # speaks it first. Inbound (no query, Direction=inbound) is unchanged.
    opening = request.query_params.get("opening", "")
    is_outbound = bool(opening) or params.get("Direction", "").lower().startswith("outbound")

    # A call someone else dialled: talking to the number is prompting the
    # assistant with its tools, so only the owner's listed numbers get a
    # session. Everyone else is hung up on before anything is built for them.
    if not is_outbound and not caller_allowed(
        from_number, getattr(twilio, "allowed_callers", None)
    ):
        log.warning("telephony: refused an inbound call from a number that is not allowed")
        return Response(content=build_reject_twiml(), media_type="text/xml")

    # A call talks only through a realtime speech-to-speech session. When none
    # can serve a phone line, Twilio says so and hangs up before any stream
    # opens (there is no other voice to fall back to).
    if not await asyncio.to_thread(_phone_ready, _resolve_cfg(request)):
        log.warning("telephony: refused a call: no realtime voice can serve a phone line")
        return Response(content=build_reject_twiml(_NO_REALTIME_VOICE), media_type="text/xml")

    secret = generate_call_secret()
    mgr.register_pending(call_sid, secret, from_number=from_number, to_number=to_number)

    wss_url = public_wss_url(public_base_url, "/api/telephony/media")
    twiml = build_connect_stream_twiml(
        wss_url=wss_url,
        secret=secret,
        call_sid=call_sid,
        language_code=getattr(twilio, "language_code", "de-DE") or "de-DE",
        direction="outbound" if is_outbound else "",
        opening=opening if is_outbound else "",
    )
    return Response(content=twiml, media_type="text/xml")


# ---------------------------------------------------------------------------
# Twilio-facing: media WebSocket
# ---------------------------------------------------------------------------


def _call_config(state: Any) -> Any:
    """The running config for a call, or a fresh load; ``None`` refuses it."""
    cfg = getattr(state, "config", None) or getattr(state, "cfg", None)
    if cfg is not None:
        return cfg
    try:
        return cfg_mod.load_config()
    except Exception:  # noqa: BLE001  # broad-except: no config means no session; refused
        log.warning("telephony: config could not be loaded for a call", exc_info=True)
        return None


@router.websocket("/media")
async def media_socket(ws: WebSocket) -> None:
    """Twilio Media Streams socket: bridge the call to a realtime session."""
    await ws.accept()

    app = ws.scope.get("app")
    state = app.state if app is not None else None
    mgr: TelephonyManager | None = getattr(state, "telephony_manager", None)
    if mgr is None:
        mgr = TelephonyManager()
        if state is not None:
            state.telephony_manager = mgr

    bus = getattr(state, "bus", None)
    cfg = _call_config(state)
    twilio = getattr(getattr(cfg, "integrations", None), "twilio", None)

    call: PhoneCall | None = None
    started_at = time.time()
    call_sid = ""
    record_status = CALL_IN_PROGRESS

    async def _send(msg: dict[str, object]) -> None:
        await ws.send_json(msg)

    async def _hang_up() -> None:
        # Closing a <Connect><Stream> socket ends the call: no TwiML follows it.
        await ws.close()

    try:
        while True:
            try:
                data = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except RuntimeError:
                # The socket is gone — e.g. starlette raises
                # RuntimeError('WebSocket is not connected ...') after an
                # unclean client disconnect or after the call hung up from our
                # side. `continue` would re-call receive_json on the dead
                # socket forever (AP-20 log-storm); leave the loop. Cleanup
                # below is unconditional (finally).
                log.info("telephony: media socket closed for %s", call_sid)
                break
            event = data.get("event")

            if event == "connected":
                continue

            if event == "start":
                if call_sid:
                    # A socket owns one authenticated identity for its lifetime.
                    await ws.close(code=1008, reason="duplicate start")
                    break
                start = data.get("start", {})
                stream_sid = start.get("streamSid", "") or data.get("streamSid", "")
                custom = start.get("customParameters", {}) or {}
                requested_call_sid = custom.get("call_sid", "") or start.get("callSid", "")
                secret = custom.get("secret", "")
                language = custom.get("language", "") or (
                    getattr(twilio, "language_code", "de-DE") if twilio else "de-DE"
                )
                # Outbound (Chunk C): direction/opening ride along in the TwiML
                # custom parameters; absent for inbound (-> defaults below).
                direction = custom.get("direction", "") or "inbound"
                opening = custom.get("opening", "")

                # Validate the per-call WS secret unless skipped for tests.
                skip = bool(getattr(state, "telephony_skip_signature", False))
                if not skip:
                    pending = mgr.consume_pending(requested_call_sid, secret)
                    if pending is None or not constant_time_equals(
                        pending.secret if pending else "", secret
                    ):
                        log.warning("telephony: media socket secret mismatch")
                        await ws.close(code=1008, reason="bad secret")
                        break
                    from_number = pending.from_number
                    to_number = pending.to_number
                else:
                    pending = mgr.peek_pending(requested_call_sid)
                    from_number = pending.from_number if pending else custom.get("from", "")
                    to_number = pending.to_number if pending else custom.get("to", "")

                if not requested_call_sid or mgr.active_session(requested_call_sid) is not None:
                    await ws.close(code=1008, reason="call already active or missing")
                    break
                call_sid = requested_call_sid
                call = _build_call(
                    state=state,
                    cfg=cfg,
                    twilio=twilio,
                    bus=bus,
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    from_number=from_number,
                    to_number=to_number,
                    language_code=language,
                    send=_send,
                    hang_up=_hang_up,
                    direction=direction,
                    opening=opening,
                )
                started_at = time.time()
                if not await call.start():
                    record_status = call.status
                    await ws.close(code=1011, reason="no realtime voice for a phone call")
                    break
                mgr.register_active(call_sid, call)
                _publish_start(bus, call_sid, from_number, to_number, stream_sid)
                continue

            if call is None:
                continue

            if event == "media":
                payload = data.get("media", {}).get("payload", "")
                if payload:
                    await call.handle_media(payload)
            elif event == "mark":
                call.handle_mark(str((data.get("mark") or {}).get("name", "") or ""))
            elif event == "stop":
                await call.end(reason="twilio_stop", status=CALL_COMPLETED)
            if call.ended:
                record_status = call.status
                break
    finally:
        if call is not None and not call.ended:
            await call.end(reason="socket_closed", status=record_status)
        if call is not None:
            record_status = call.status
        if call_sid:
            # Only remove the call this socket registered, never a replacement.
            if call is not None and mgr.active_session(call_sid) is call:
                mgr.unregister_active(call_sid)
            try:
                mgr.record_call(
                    CallRecord(
                        call_sid=call_sid,
                        from_number=call.from_number if call is not None else "",
                        to_number=call.to_number if call is not None else "",
                        started_at=started_at,
                        ended_at=time.time(),
                        duration_s=(
                            call.duration_s if call is not None else time.time() - started_at
                        ),
                        # CallRecord runtime-asserts membership in CALL_STATUSES;
                        # the cast only satisfies the static Literal annotation.
                        status=cast(CallStatusLiteral, record_status),
                        turns=call.turns if call is not None else 0,
                    )
                )
            except Exception:  # noqa: BLE001 - the recent-calls list is best-effort
                log.warning("telephony: call record for %s failed", call_sid, exc_info=True)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001, S110 - socket may already be closed
            pass


def _build_call(
    *,
    state: Any,
    cfg: Any,
    twilio: Any,
    bus: Any,
    call_sid: str,
    stream_sid: str,
    from_number: str,
    to_number: str,
    language_code: str,
    send: Any,
    hang_up: Any,
    direction: str = "inbound",
    opening: str = "",
) -> PhoneCall:
    """Build the :class:`PhoneCall` that bridges this stream to a realtime session.

    The realtime session is built with ``surface="phone"``, so only a provider
    that takes PCM itself is chosen. An integration test injects
    ``state.telephony_realtime_session_factory`` (same keywords) to run the
    bridge against a fake session.
    """
    session_factory = getattr(state, "telephony_realtime_session_factory", None)

    def build_session(*, send_binary: Any, send_json: Any, call_brief: str) -> Any:
        if session_factory is not None:
            return session_factory(
                send_binary=send_binary, send_json=send_json, call_brief=call_brief
            )
        if cfg is None:
            return None
        from dodaios.realtime.factory import PHONE_SURFACE, build_realtime_session

        return build_realtime_session(
            cfg=cfg,
            bus=bus,
            session_id=f"phone-{call_sid}",
            send_binary=send_binary,
            send_json=send_json,
            surface=PHONE_SURFACE,
            brain=getattr(state, "brain", None),
            call_brief=call_brief,
        )

    try:
        from dodaios.brain.assistant_name import resolve_assistant_name

        assistant_name = resolve_assistant_name(cfg)
    except Exception:  # noqa: BLE001 — never break call setup on name resolution
        log.debug("telephony: assistant name unavailable", exc_info=True)
        assistant_name = ""

    return PhoneCall(
        call_sid=call_sid,
        stream_sid=stream_sid,
        send=send,
        hang_up=hang_up,
        build_session=build_session,
        from_number=from_number,
        to_number=to_number,
        language_code=language_code or "de-DE",
        direction=direction or "inbound",
        opening=opening,
        greeting=getattr(twilio, "greeting", "") if twilio else "",
        assistant_name=assistant_name,
        max_call_seconds=int(getattr(twilio, "max_call_seconds", 600) or 600) if twilio else 600,
        volume=float(getattr(getattr(cfg, "tts", None), "volume", 1.0)),
        bus=bus,
    )


# bus.publish() is async (dodaios/core/bus.py); a bare un-awaited call just
# creates-and-drops a coroutine without ever running it. Fire-and-forget via
# asyncio.create_task instead, keeping a strong reference here so the event
# loop can't garbage-collect the task mid-flight (each self-discards on
# completion).
_PENDING_PUBLISH_TASKS: set[asyncio.Task[Any]] = set()


def _publish_start(bus, call_sid, from_number, to_number, stream_sid) -> None:
    if bus is None:
        return
    try:
        from dodaios.telephony.events import TelephonyCallStarted

        task = asyncio.create_task(
            bus.publish(
                TelephonyCallStarted(
                    call_sid=call_sid,
                    from_number=from_number,
                    to_number=to_number,
                    stream_sid=stream_sid,
                )
            )
        )
        _PENDING_PUBLISH_TASKS.add(task)
        task.add_done_callback(_PENDING_PUBLISH_TASKS.discard)
    except Exception:  # noqa: BLE001, S110 - bus publish is best-effort
        pass


__all__ = ["router"]
