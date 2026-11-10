"""The phone companion: pairing, paired devices, and the lead conversation for a phone.

Two halves with two credentials:

* ``/api/mobile/pair/code``, ``/api/mobile/devices*``, ``/api/mobile/status``,
  ``/api/mobile/whatsapp`` are the DESKTOP's: the person at the window mints a
  pairing code and manages phones. They sit behind the ordinary outer boundary
  (session cookie or local open access) like every other settings route.
* ``/api/mobile/app/*`` is the PHONE's: every call carries the device token a
  redeemed pairing code answered with (``Authorization: Bearer mdt_...``).
  :mod:`dodaios.ui.web.surface_security` accepts that token for this prefix
  only; :func:`require_device` checks it again here and names the device.
  ``POST /api/mobile/pair/redeem`` is the one call a not-yet-paired phone may
  make, and it needs a live code.

A phone token never opens the desktop routes, the Control API or a WebSocket.
Plain HTTP is accepted from private (LAN) addresses only; from anywhere else
the companion needs HTTPS (see ``docs/mobile-companion.md``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from dodaios.mobile.devices import PairedDevice, PairingError, PushSubscription, get_devices

log = logging.getLogger(__name__)

router = APIRouter(tags=["mobile"])

#: Where the frontend build puts the phone app (``frontend/m/index.html``).
MOBILE_INDEX = Path(__file__).resolve().parent / "dist" / "m" / "index.html"
#: Phone-facing prefix: the only paths a device token opens.
APP_PREFIX = "/api/mobile/app/"
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_MAX_VOICE_NOTE_BYTES = 16_000 * 2 * 120  # two minutes of 16 kHz int16 mono


def _json(value: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})


def _failure(exc: PairingError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


# --------------------------------------------------------------- transport


def _client_is_private(request: Request) -> bool:
    client = request.client
    host = str(client[0]) if client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:  # a hostname, not an address: only "localhost" is local
        return host == "localhost"
    return address.is_private or address.is_loopback or address.is_link_local


def transport_allowed(request: Request) -> bool:
    """HTTPS anywhere; plain HTTP only from a private (LAN) or loopback peer."""
    if request.url.scheme in {"https", "wss"}:
        return True
    return _client_is_private(request)


def _require_transport(request: Request) -> None:
    if not transport_allowed(request):
        raise HTTPException(
            403, "The phone companion needs HTTPS outside your own network."
        )


def _bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def require_device(request: Request) -> PairedDevice:
    """FastAPI dependency: the paired phone behind this call, or 401."""
    _require_transport(request)
    device = get_devices().authenticate(_bearer(request))
    if device is None:
        raise HTTPException(
            401,
            "This phone is not paired. Scan the pairing code in Settings → Phone.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        get_devices().touch(device.id)
    except Exception:  # noqa: BLE001 — a last-seen stamp is never worth failing a call
        log.debug("mobile: last-seen stamp failed", exc_info=True)
    return device


# ------------------------------------------------------------ desktop side


def _bind_host() -> str:
    return (os.environ.get("JARVIS_BIND_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def lan_addresses() -> list[str]:
    """This machine's private IPv4 addresses, the one with a default route first."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET; nothing is sent
            found.append(probe.getsockname()[0])
    except OSError:  # no default route: the host list below still answers
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(str(info[4][0]))
    except OSError:  # a host without a resolvable name has no extra addresses
        pass
    out: list[str] = []
    for host in found:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:  # getaddrinfo answered a name, not an address: skip it
            continue
        if address.is_loopback or address.is_link_local or host in out:
            continue
        if address.is_private:
            out.append(host)
    return out


def _port(request: Request) -> int:
    return int(request.url.port or (443 if request.url.scheme == "https" else 80))


def _assistant_name(request: Request) -> str:
    from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name

    config = getattr(request.app.state, "config", None)
    try:
        return resolve_assistant_name(config) if config is not None else DEFAULT_ASSISTANT_NAME
    except Exception:  # noqa: BLE001 — the neutral word is a fine name
        return DEFAULT_ASSISTANT_NAME


def _listening(request: Request) -> dict[str, Any]:
    host = _bind_host()
    loopback_only = host in _LOOPBACK
    return {
        "bind_host": host,
        "loopback_only": loopback_only,
        "port": _port(request),
        "https": request.url.scheme == "https",
        "lan_addresses": [] if loopback_only else lan_addresses(),
    }


@router.get("/api/mobile/status", operation_id="mobile_status")
def mobile_status(request: Request) -> JSONResponse:
    """What the Phone settings page shows: paired phones, push readiness, reachability."""
    from dodaios.channels.whatsapp import load_whatsapp_config, whatsapp_status
    from dodaios.mobile.webpush import get_vapid

    devices = get_devices()
    try:
        push_key = get_vapid().public_key_b64url()
    except Exception:  # noqa: BLE001 — push stays off when the key cannot be written
        log.warning("mobile: VAPID key unavailable", exc_info=True)
        push_key = ""
    return _json(
        {
            "devices": devices.public_devices(),
            "open_codes": devices.open_codes(),
            "push_ready": bool(push_key),
            "listening": _listening(request),
            "whatsapp": whatsapp_status(load_whatsapp_config(), request.app.state),
        }
    )


@router.post("/api/mobile/pair/code", operation_id="mobile_pair_code")
def create_pairing_code(request: Request) -> JSONResponse:
    """A five-minute, single-use code and the links a phone on this network can open."""
    issued = get_devices().issue_code()
    listening = _listening(request)
    scheme = "https" if listening["https"] else "http"
    urls = [
        f"{scheme}://{host}:{listening['port']}/m/#pair={issued['code']}"
        for host in listening["lan_addresses"]
    ]
    return _json({**issued, "urls": urls, "listening": listening})


@router.get("/api/mobile/devices", operation_id="mobile_devices")
def list_devices() -> JSONResponse:
    return _json({"devices": get_devices().public_devices()})


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/api/mobile/devices/{device_id}", operation_id="mobile_device_rename")
def rename_device(device_id: str, body: RenameBody) -> JSONResponse:
    try:
        return _json(get_devices().rename(device_id, body.name).public())
    except PairingError as exc:
        raise _failure(exc) from exc


@router.delete("/api/mobile/devices/{device_id}", operation_id="mobile_device_revoke")
def revoke_device(device_id: str) -> JSONResponse:
    """Forget a phone: its token and its notifications stop at once."""
    removed = get_devices().revoke(device_id)
    if not removed:
        raise HTTPException(404, "No such phone.")
    return _json({"removed": True})


class WhatsAppBody(BaseModel):
    enabled: bool


@router.get("/api/mobile/whatsapp", operation_id="mobile_whatsapp_status")
def whatsapp_state(request: Request) -> JSONResponse:
    from dodaios.channels.whatsapp import load_whatsapp_config, whatsapp_status

    return _json(whatsapp_status(load_whatsapp_config(), request.app.state))


@router.put("/api/mobile/whatsapp", operation_id="mobile_whatsapp_toggle")
def whatsapp_toggle(request: Request, body: WhatsAppBody) -> JSONResponse:
    """Turn the owner-only WhatsApp channel on or off (applies on the next start)."""
    from dodaios.channels.whatsapp import (
        load_whatsapp_config,
        save_whatsapp_config,
        whatsapp_status,
    )

    config = load_whatsapp_config()
    config.enabled = body.enabled
    save_whatsapp_config(config)
    return _json(whatsapp_status(config, request.app.state))


# --------------------------------------------------------------- the page


@router.get("/m", include_in_schema=False, response_model=None)
@router.get("/m/", include_in_schema=False, response_model=None)
def mobile_page() -> FileResponse | JSONResponse:
    """The installable phone app (a separate, tiny bundle; see ``frontend/m``)."""
    if not MOBILE_INDEX.is_file():
        return _json({"detail": "The phone app is not part of this build."}, 404)
    return FileResponse(
        str(MOBILE_INDEX), headers={"Cache-Control": "no-store, max-age=0"}, media_type="text/html"
    )


# ---------------------------------------------------------------- pairing


class RedeemBody(BaseModel):
    code: str = Field(min_length=1, max_length=64, repr=False)
    name: str = Field(default="Phone", max_length=120)


@router.post("/api/mobile/pair/redeem", operation_id="mobile_pair_redeem")
def redeem_pairing_code(request: Request, body: RedeemBody) -> JSONResponse:
    """Spend a shown code for this phone's token (returned once, never stored)."""
    _require_transport(request)
    try:
        device, token = get_devices().redeem(
            body.code, body.name, user_agent=request.headers.get("user-agent", "")
        )
    except PairingError as exc:
        raise _failure(exc) from exc
    log.info("mobile: a phone paired (%s)", device.id)
    return _json(
        {
            "token": token,
            "device": device.public(),
            "assistant_name": _assistant_name(request),
        }
    )


# ------------------------------------------------------------- phone side


def _service(request: Request) -> Any:
    from .agent_chat_routes import _service as chat_service

    svc = chat_service(request)
    try:
        from dodaios.mobile.notify import notifier

        notifier().attach_service(svc)
    except Exception:  # noqa: BLE001 — pushes for notices are optional
        log.debug("mobile: notice listener not attached", exc_info=True)
    return svc


async def _async_service(request: Request) -> Any:
    return await asyncio.to_thread(_service, request)


@router.get("/api/mobile/app/me", operation_id="mobile_me")
def phone_me(
    request: Request, device: PairedDevice = Depends(require_device)  # noqa: B008
) -> JSONResponse:
    from dodaios.mobile.webpush import get_vapid

    try:
        push_key = get_vapid().public_key_b64url()
    except Exception:  # noqa: BLE001 — the phone shows push as unavailable
        push_key = ""
    return _json(
        {
            "device": device.public(),
            "assistant_name": _assistant_name(request),
            "push_key": push_key,
            "push_subscribed": device.push is not None,
        }
    )


@router.post("/api/mobile/app/unpair", operation_id="mobile_unpair")
def phone_unpair(
    device: PairedDevice = Depends(require_device),  # noqa: B008
) -> JSONResponse:
    get_devices().revoke(device.id)
    return _json({"removed": True})


@router.get("/api/mobile/app/lead", operation_id="mobile_lead")
async def phone_lead(
    request: Request,
    device: PairedDevice = Depends(require_device),  # noqa: B008
    tail: int = Query(160, ge=1, le=500),
) -> JSONResponse:
    """The lead conversation folded for a phone screen (newest ``tail`` events)."""
    from dodaios.agent_chat.lead import lead_session
    from dodaios.mobile.timeline import fold_events

    svc = await _async_service(request)
    session = await asyncio.to_thread(lead_session, svc)
    if session is None:
        raise HTTPException(409, "No chat provider is set up yet.")
    sid = session.session_id
    events = await asyncio.to_thread(svc.store.list_events, sid, tail=tail)
    folded = fold_events(events, running=bool(svc.is_running(sid)))
    folded["session_id"] = sid
    folded["title"] = str(getattr(session, "title", "") or "")
    return _json(folded)


class MessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


@router.post("/api/mobile/app/lead/messages", operation_id="mobile_lead_send")
async def phone_send(
    request: Request,
    body: MessageBody,
    device: PairedDevice = Depends(require_device),  # noqa: B008
) -> JSONResponse:
    """Type into the lead conversation from the phone (same queue as the desktop)."""
    from dodaios.agent_chat.lead import lead_session
    from dodaios.agent_chat.send_queue import QueueFull, send_or_queue

    svc = await _async_service(request)
    session = await asyncio.to_thread(lead_session, svc)
    if session is None:
        raise HTTPException(409, "No chat provider is set up yet.")
    try:
        turn_id, queue_id = await send_or_queue(svc, session.session_id, body.text.strip())
    except QueueFull as exc:
        raise HTTPException(409, "Too many messages are waiting.") from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    log.debug("mobile: a message from phone %s joins the conversation", device.id)
    return _json({"turn_id": turn_id, "queued": bool(queue_id), "session_id": session.session_id})


class ApprovalBody(BaseModel):
    decision: str = Field(pattern=r"^(allow|deny)$")


@router.post(
    "/api/mobile/app/lead/approvals/{approval_id}", operation_id="mobile_lead_approve"
)
async def phone_approve(
    request: Request,
    approval_id: str,
    body: ApprovalBody,
    device: PairedDevice = Depends(require_device),  # noqa: B008
) -> JSONResponse:
    """Allow or deny one waiting card from the phone. Never a standing rule."""
    from dodaios.agent_chat.lead import lead_session

    svc = await _async_service(request)
    session = await asyncio.to_thread(lead_session, svc, create=False)
    if session is None:
        raise HTTPException(404, "No conversation yet.")
    ok = svc.resolve_approval(session.session_id, approval_id, body.decision)
    if not ok:
        closer = getattr(svc, "close_stale_approval", None)
        if callable(closer) and await closer(session.session_id, approval_id):
            raise HTTPException(410, "This request expired and nothing ran.")
        raise HTTPException(404, "No such pending approval.")
    return _json({"ok": True, "approval_id": approval_id, "decision": body.decision})


@router.post("/api/mobile/app/lead/voice-note", operation_id="mobile_lead_voice_note")
async def phone_voice_note(
    request: Request,
    device: PairedDevice = Depends(require_device),  # noqa: B008
    sample_rate: int = Query(16_000, ge=8_000, le=48_000),
    language: str = Query("", max_length=8),
) -> JSONResponse:
    """A recorded note (16 kHz int16 mono PCM body) transcribed and sent as text."""
    if sample_rate != 16_000:
        raise HTTPException(422, "Voice notes need 16 kHz audio.")
    pcm = await request.body()
    if len(pcm) < 3200:
        raise HTTPException(422, "The recording is too short.")
    if len(pcm) > _MAX_VOICE_NOTE_BYTES:
        raise HTTPException(413, "The recording is longer than two minutes.")
    stt = _voice_note_stt()
    if stt is None:
        raise HTTPException(503, "Voice notes need a speech-to-text provider on this computer.")
    try:
        try:
            transcript = await stt.transcribe_pcm(pcm, language=language or None)
        except TypeError:  # a provider from before the keyword: the bare call is the contract
            transcript = await stt.transcribe_pcm(pcm)
    except Exception as exc:  # noqa: BLE001 — the phone shows the reason
        log.warning("mobile: voice note transcription failed: %s", exc)
        raise HTTPException(502, "The recording could not be transcribed.") from exc
    text = str(getattr(transcript, "text", transcript) or "").strip()
    if not text:
        raise HTTPException(422, "Nothing was heard in the recording.")
    from dodaios.agent_chat.lead import lead_session
    from dodaios.agent_chat.send_queue import send_or_queue

    svc = await _async_service(request)
    session = await asyncio.to_thread(lead_session, svc)
    if session is None:
        raise HTTPException(409, "No chat provider is set up yet.")
    turn_id, queue_id = await send_or_queue(svc, session.session_id, text)
    return _json({"text": text, "turn_id": turn_id, "queued": bool(queue_id)})


def _voice_note_stt() -> Any:
    """The dictation lane's recognizer (local first), or ``None`` without voice."""
    try:
        from .dictation_routes import _pipeline, _restore_stt

        return _restore_stt(_pipeline())
    except Exception:  # noqa: BLE001 — a headless host has no recognizer
        return None


# ------------------------------------------------------------------- push


class SubscriptionBody(BaseModel):
    endpoint: str = Field(min_length=8, max_length=2048)
    keys: dict[str, str]


@router.get("/api/mobile/app/push/key", operation_id="mobile_push_key")
def phone_push_key(
    device: PairedDevice = Depends(require_device),  # noqa: B008
) -> JSONResponse:
    from dodaios.mobile.webpush import get_vapid

    try:
        return _json({"key": get_vapid().public_key_b64url()})
    except Exception as exc:  # noqa: BLE001 — told as unavailable, with the reason logged
        log.warning("mobile: VAPID key unavailable", exc_info=True)
        raise HTTPException(503, "Notifications are not available on this computer.") from exc


@router.put("/api/mobile/app/push/subscription", operation_id="mobile_push_subscribe")
def phone_push_subscribe(
    body: SubscriptionBody, device: PairedDevice = Depends(require_device)  # noqa: B008
) -> JSONResponse:
    """Keep this phone's push subscription (one per device; replaces the previous)."""
    if not body.endpoint.startswith("https://"):
        raise HTTPException(422, "A push endpoint must be an HTTPS address.")
    try:
        subscription = PushSubscription(
            endpoint=body.endpoint,
            p256dh=str(body.keys.get("p256dh") or ""),
            auth=str(body.keys.get("auth") or ""),
        )
    except ValueError as exc:
        raise HTTPException(422, "The push subscription is incomplete.") from exc
    try:
        get_devices().set_push(device.id, subscription)
    except PairingError as exc:
        raise _failure(exc) from exc
    return _json({"subscribed": True})


@router.delete("/api/mobile/app/push/subscription", operation_id="mobile_push_unsubscribe")
def phone_push_unsubscribe(
    device: PairedDevice = Depends(require_device),  # noqa: B008
) -> JSONResponse:
    try:
        get_devices().set_push(device.id, None)
    except PairingError as exc:
        raise _failure(exc) from exc
    return _json({"subscribed": False})


@router.post("/api/mobile/app/push/test", operation_id="mobile_push_test")
async def phone_push_test(
    request: Request, device: PairedDevice = Depends(require_device)  # noqa: B008
) -> JSONResponse:
    """Send one test note to this phone so the person sees push works."""
    from dodaios.mobile.notify import notifier

    current = await asyncio.to_thread(get_devices().authenticate, _bearer(request))
    if current is None or current.push is None:
        raise HTTPException(409, "This phone has no notification subscription yet.")
    result = await notifier().sender.send(
        current.push,
        {
            "title": _assistant_name(request),
            "body": "Notifications reach this phone.",
            "tag": "test",
            "kind": "test",
            "url": "/m/",
        },
    )
    if result == "gone":
        await asyncio.to_thread(get_devices().set_push, device.id, None)
        raise HTTPException(410, "The phone's subscription is gone; turn notifications on again.")
    if result != "sent":
        raise HTTPException(502, "The push service did not accept the note.")
    return _json({"sent": True})


__all__ = ["APP_PREFIX", "MOBILE_INDEX", "lan_addresses", "require_device", "router"]
