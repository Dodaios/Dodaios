"""FastAPI ``/ws/audio`` route for the browser-microphone voice bridge (B2 slice 2).

A per-connection WebSocket that receives raw int16 PCM (binary frames) + JSON
control frames from the browser and runs one realtime speech-to-speech session
(``dodaios.realtime.factory.build_realtime_session``, no sounddevice). Voice
conversations run only on realtime: when no session can be built, or the one
that runs fails, the call ends with an honest error and never continues on
another engine. The receive loop keeps the ``/ws`` AP-20 discipline: a
``RuntimeError`` on an unclean disconnect is terminal — ``break``, never
``continue``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import secrets
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from dodaios.core import config as cfg_mod
from dodaios.sessions.constants import HANGUP_ERROR, HANGUP_WS_CLOSED
from dodaios.ui.web.surface_security import credentials_valid

log = logging.getLogger("dodaios.browser_voice.route")

router = APIRouter()

_AUDIO_QUEUE_MAX_FRAMES = 32
_TRANSPORT_SEND_TIMEOUT_S = 2.0
_AUDIO_DRAIN_TIMEOUT_S = 2.0
_BROKER_AUTH_TIMEOUT_S = 3.0
# The selected voice connection could not start or failed during the call.
_VOICE_FAILED_DETAIL = (
    "The selected voice connection could not start. Check its connection and "
    "model settings."
)
# No session could be built for the selected engine at all: its sign-in or key
# is missing, or its plugin failed to load. The close reason alone ("realtime
# access unavailable") told the person nothing they could act on.
_SELECTED_VOICE_NOT_READY_DETAIL = (
    "The selected voice connection is not set up on this installation. Open "
    "API Keys > Live calls, check the sign-in or key, and save the voice "
    "setup again."
)


def _voice_failed_detail(error: BaseException | str | None) -> str:
    """The person-facing text when the selected live provider cannot go on.

    A classified failure (plan not offered, reconnect needed, allowance
    exhausted, rejected key, no credit, unreachable network, ...) keeps its
    static message so the person learns what to fix. Anything else gets the
    generic text: raw provider detail never reaches the surface.
    """
    try:
        from dodaios.live.start_failure import start_failure_reason

        reason = start_failure_reason(error)
    except Exception:  # noqa: BLE001 - the generic text is always safe
        log.debug("browser_voice: failure classification unavailable", exc_info=True)
        reason = None
    return reason or _VOICE_FAILED_DETAIL


def _browser_voice_authorized(ws: WebSocket) -> bool:
    """Apply the shared cookie/Bearer policy as route-level defense in depth.

    A peer address is not an authentication boundary: a hostile webpage can
    connect directly to a localhost WebSocket and still appear loopback to the
    server. Every client therefore needs a registered token before a
    tool-capable voice session is constructed.
    """
    return credentials_valid(ws.scope)


def _socket_peer_is_loopback(ws: WebSocket) -> bool:
    """Trust only the ASGI socket peer for the local SDP broker boundary.

    Forwarded headers and Origin are deliberately ignored: either can be
    supplied by a remote authenticated browser. IPv4-mapped IPv6 loopback is
    accepted so desktop networking behaves consistently across operating
    systems and embedded WebView implementations.
    """
    client = ws.scope.get("client")
    if not isinstance(client, (tuple, list)) or not client:
        return False
    host = str(client[0] or "").strip().strip("[]")
    if "%" in host:
        host = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:  # A non-IP host is a normal failed loopback capability check.
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return bool((mapped or address).is_loopback)


def _enqueue_audio_frame(queue: asyncio.Queue[bytes | None], data: bytes) -> bool:
    """Queue one mic frame without blocking; drop the oldest on overflow."""
    dropped = False
    if queue.full():
        try:
            queue.get_nowait()
            queue.task_done()
            dropped = True
        except asyncio.QueueEmpty:  # pragma: no cover - another task drained it
            pass
    queue.put_nowait(bytes(data))
    return dropped


async def _cancel_socket_task(task: asyncio.Task[Any]) -> None:
    """Cancel and reap one temporary WebSocket receive/wait task."""
    if not task.done():
        task.cancel()
    try:
        await task
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):  # Expected teardown.
        pass


def _build_browser_session(
    *, state: Any, cfg: Any, bus: Any, session_id: str, send_binary: Any, send_json: Any
) -> Any:
    """Build the realtime session for one browser-held call, or ``None``.

    The registry-backed factory selects every credential-ready duplex family
    in configured order; no provider name is load-bearing. ``None`` means no
    realtime provider can hold the call: the caller ends it with an honest
    error.
    """
    from dodaios.realtime.factory import build_realtime_session

    return build_realtime_session(
        cfg=cfg,
        bus=bus,
        session_id=session_id,
        send_binary=send_binary,
        send_json=send_json,
        surface="browser",
        brain=getattr(state, "brain", None),
    )


@router.websocket("/ws/realtime-transport")
async def realtime_transport_ws(ws: WebSocket) -> None:
    """Broker a local desktop WebRTC offer for subscription voice.

    Audio remains on Jarvis's existing native or ``/ws/audio`` path. This
    socket carries only one-shot SDP offers and answers. Because an answered
    offer can receive native-call audio, this broker is additionally restricted
    to the actual loopback socket peer; authentication alone is insufficient.
    """
    await ws.accept()
    if not _socket_peer_is_loopback(ws):
        await ws.close(code=4403, reason="local desktop transport required")
        return
    if not _browser_voice_authorized(ws):
        await ws.close(code=4401, reason="unauthorized")
        return

    app = ws.scope.get("app")
    state = app.state if app is not None else None

    from dodaios.realtime.offer_broker import (
        get_realtime_transport_offer_broker,
    )

    broker = get_realtime_transport_offer_broker()
    registration: Any = None
    queued_message: dict[str, Any] | None = None
    socket_closed = False
    try:
        desktop_capability = str(
            getattr(state, "realtime_transport_broker_token", "") or ""
        )
        if not desktop_capability:
            await ws.close(code=4401, reason="desktop capability unavailable")
            return
        try:
            auth_message = await asyncio.wait_for(
                ws.receive(), timeout=_BROKER_AUTH_TIMEOUT_S
            )
        except (TimeoutError, WebSocketDisconnect, RuntimeError):  # Reject failed capability proof.
            await ws.close(code=4401, reason="desktop capability required")
            return
        auth_text = auth_message.get("text")
        try:
            auth_payload = json.loads(auth_text) if auth_text is not None else None
        except (TypeError, ValueError):  # Malformed authentication is handled as absent.
            auth_payload = None
        supplied_capability = (
            str(auth_payload.get("desktop_capability", "") or "")
            if isinstance(auth_payload, dict)
            and auth_payload.get("type") == "authenticate"
            else ""
        )
        if not supplied_capability or not secrets.compare_digest(
            supplied_capability, desktop_capability
        ):
            await ws.close(code=4401, reason="invalid desktop capability")
            return
        state.realtime_transport_broker_error = ""
        log.info("Embedded desktop Realtime transport broker authenticated.")
        owner_id = f"broker-ws-{id(ws):x}"
        while not socket_closed:
            if queued_message is None:
                try:
                    message = await ws.receive()
                except (WebSocketDisconnect, RuntimeError):  # Socket teardown ends this receiver.
                    break
            else:
                message = queued_message
                queued_message = None
            if message.get("type") == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None:
                continue
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                log.debug("realtime transport dropped malformed JSON")
                continue
            if isinstance(payload, dict) and payload.get("type") == "unavailable":
                state.realtime_transport_broker_error = (
                    "The embedded desktop cannot create the WebRTC offer required "
                    "for subscription Realtime voice."
                )
                log.warning(
                    "Embedded desktop cannot create the WebRTC offer required "
                    "for subscription Realtime voice."
                )
                await ws.close(code=1011, reason="WebRTC offer unavailable")
                socket_closed = True
                break
            if not isinstance(payload, dict) or payload.get("type") != "offer":
                if isinstance(payload, dict) and payload.get("type") == "authenticate":
                    await ws.close(code=4401, reason="desktop capability replay")
                    socket_closed = True
                continue

            offer_id = str(payload.get("offer_id", "") or "").strip()
            offer_sdp = str(payload.get("webrtc_offer_sdp", "") or "")
            try:
                registration = await broker.register(
                    offer_id, offer_sdp, owner_id=owner_id
                )
            except ValueError as exc:
                log.warning("realtime transport rejected offer: %s", exc)
                await ws.send_json({"type": "release", "offer_id": offer_id})
                continue
            state.realtime_transport_broker_error = ""
            log.info("Embedded desktop registered a Realtime WebRTC offer.")

            while registration is not None:
                result_task = asyncio.create_task(
                    registration.wait(), name=f"realtime-offer-{offer_id}"
                )
                receive_task = asyncio.create_task(
                    ws.receive(), name=f"realtime-offer-receive-{offer_id}"
                )
                done, _pending = await asyncio.wait(
                    {result_task, receive_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if result_task in done:
                    await _cancel_socket_task(receive_task)
                    result = result_task.result()
                    if result.type == "answer":
                        await ws.send_json(
                            {
                                "type": "answer",
                                "offer_id": result.offer_id,
                                "webrtc_answer_sdp": result.answer_sdp,
                            }
                        )
                        # Keep the registration alive until provider close so
                        # the UI knows when to recycle its PeerConnection and
                        # publish a fresh offer for the next native call.
                        continue
                    await ws.send_json(
                        {"type": "release", "offer_id": result.offer_id}
                    )
                    registration = None
                    break

                await _cancel_socket_task(result_task)
                await registration.cancel()
                registration = None
                try:
                    next_message = receive_task.result()
                except (WebSocketDisconnect, RuntimeError):  # Socket teardown ends this offer.
                    socket_closed = True
                    break
                if next_message.get("type") == "websocket.disconnect":
                    socket_closed = True
                    break
                # A refreshed offer can replace an abandoned one on the same
                # socket. Process that already-read frame in the outer loop.
                queued_message = next_message
                break
    finally:
        if registration is not None:
            await registration.cancel()


@router.websocket("/ws/audio")
async def browser_voice_ws(ws: WebSocket) -> None:
    """Browser-microphone voice socket: run the per-connection turn loop."""
    await ws.accept()

    if not _browser_voice_authorized(ws):
        await ws.close(code=4401, reason="unauthorized")
        return

    app = ws.scope.get("app")
    state = app.state if app is not None else None
    bus = getattr(state, "bus", None)
    cfg = getattr(state, "config", None) or getattr(state, "cfg", None)
    if cfg is None:
        try:
            cfg = cfg_mod.load_config()
        except Exception:  # noqa: BLE001 - Config failure degrades to unavailable voice.
            cfg = None

    session_id = str(uuid4())

    async def _send_binary(data: bytes) -> None:
        await asyncio.wait_for(
            ws.send_bytes(data), timeout=_TRANSPORT_SEND_TIMEOUT_S
        )

    async def _send_json(msg: dict[str, Any]) -> None:
        await asyncio.wait_for(
            ws.send_json(msg), timeout=_TRANSPORT_SEND_TIMEOUT_S
        )

    from dodaios.browser_voice.output_control import BrowserOutputControl

    pipeline = getattr(state, "speech_pipeline", None)
    if pipeline is None:
        from dodaios.core.runtime_refs import get_speech_pipeline

        pipeline = get_speech_pipeline()
    output = BrowserOutputControl(
        bus=bus, pipeline=pipeline, send_json=_send_json, send_binary=_send_binary,
        volume=float(getattr(getattr(cfg, "tts", None), "volume", 1.0)),
    )
    session = _build_browser_session(
        state=state,
        cfg=cfg,
        bus=bus,
        session_id=session_id,
        send_binary=output.send_binary,
        send_json=output.send_json,
    )
    if session is None:
        log.warning("browser_voice: no realtime voice connection can hold this call")
        try:
            await _send_json(
                {"type": "provider_error", "error": _SELECTED_VOICE_NOT_READY_DETAIL}
            )
        except Exception:  # noqa: BLE001 - the close below still ends the call
            log.debug("browser_voice: unavailable-engine notice not sent", exc_info=True)
        await ws.close(code=1011, reason="realtime access unavailable")
        return

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(
        maxsize=_AUDIO_QUEUE_MAX_FRAMES
    )
    dropped_audio_frames = 0
    audio_sender_failed = asyncio.Event()
    failure_reported = False

    async def _end_on_failure(reason: str, error: BaseException | None = None) -> None:
        """End the call with the reason: realtime is the only voice engine.

        A provider that refused or failed is never replaced by another engine
        mid-call. The person hears and reads why, and the call ends. Reported
        once, however many frames or controls hit the failed session.
        """
        nonlocal failure_reported
        if failure_reported:
            return
        failure_reported = True
        from dodaios.speech import provider_refusal

        log.warning("browser_voice: realtime voice failed; ending the call: %s", reason)
        refusal = getattr(session, "start_refusal", None) or provider_refusal.describe(
            error if error is not None else reason
        )
        if refusal is not None:
            await provider_refusal.announce(
                bus,
                session_id=session_id,
                provider=str(getattr(session, "active_provider", "") or ""),
                refusal=refusal,
                language=str(getattr(session, "_language", "") or ""),
                continued_on=provider_refusal.CONTINUED_NONE,
            )
        await session.end(reason=HANGUP_ERROR)
        try:
            await _send_json(
                {
                    "type": "provider_error",
                    "error": _voice_failed_detail(error if error is not None else reason),
                }
            )
        except Exception:  # noqa: BLE001 - the provider may have torn down the wire
            log.debug("browser_voice: failure status could not be sent", exc_info=True)
        await ws.close(code=1011, reason="realtime voice failed")

    async def _send_audio_frame(data: bytes) -> None:
        if bool(getattr(session, "failed", False)):
            detail = str(getattr(session, "failure_detail", "") or "stream ended")
            await _end_on_failure(detail)
            raise RuntimeError(detail)
        try:
            await asyncio.wait_for(
                session.handle_audio_frame(data),
                timeout=_TRANSPORT_SEND_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 - terminal: the call ends with its reason
            await _end_on_failure(str(exc), exc)
            raise

    async def _audio_sender() -> None:
        while True:
            data = await audio_queue.get()
            try:
                if data is None:
                    return
                await _send_audio_frame(data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - terminal sender failure
                log.warning("browser_voice: audio sender failed: %s", exc)
                audio_sender_failed.set()
                return
            finally:
                audio_queue.task_done()

    audio_sender_task = asyncio.create_task(
        _audio_sender(), name=f"browser-audio-sender-{session_id}"
    )

    try:
        await output.start()
        while True:
            try:
                msg = await ws.receive()
            except WebSocketDisconnect:  # A peer disconnect normally terminates the receive loop.
                break
            except RuntimeError:
                # AP-20: an unclean disconnect raises RuntimeError (not
                # WebSocketDisconnect) — terminal, break (never continue).
                break
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None:
                if audio_sender_failed.is_set():
                    break
                if _enqueue_audio_frame(audio_queue, data):
                    dropped_audio_frames += 1
                continue
            text = msg.get("text")
            if text is not None:
                try:
                    control = json.loads(text)
                except Exception:  # noqa: BLE001 — malformed control frame, drop it
                    log.debug("browser_voice: dropping malformed control frame")
                    continue
                if isinstance(control, dict):
                    if control.get("type") == "audio_start":
                        raw_offer = control.get("webrtc_offer_sdp")
                        if raw_offer is not None:
                            try:
                                from dodaios.realtime.offer_broker import (
                                    validate_webrtc_offer_sdp,
                                )

                                control["webrtc_offer_sdp"] = (
                                    validate_webrtc_offer_sdp(raw_offer)
                                )
                            except ValueError as exc:
                                log.warning(
                                    "browser_voice: rejected invalid WebRTC offer: %s",
                                    exc,
                                )
                                await ws.close(code=1008, reason="invalid WebRTC offer")
                                break
                    try:
                        await session.handle_control(control)
                    except Exception as exc:  # noqa: BLE001 — AP-20: terminal
                        if control.get("type") == "audio_start":
                            await _end_on_failure(str(exc), exc)
                        else:
                            log.warning("browser_voice: control handling failed: %s", exc)
                        break
    finally:
        output.close()
        try:
            await asyncio.wait_for(
                audio_queue.join(), timeout=_AUDIO_DRAIN_TIMEOUT_S
            )
        except TimeoutError:
            log.warning(
                "browser_voice: audio drain timed out; dropping %d queued frames",
                audio_queue.qsize(),
            )
        if not audio_sender_task.done():
            try:
                audio_queue.put_nowait(None)
            except asyncio.QueueFull:  # Cancellation already makes the terminal sentinel redundant.
                audio_sender_task.cancel()
            try:
                await asyncio.wait_for(
                    audio_sender_task, timeout=_TRANSPORT_SEND_TIMEOUT_S
                )
            except (TimeoutError, asyncio.CancelledError):
                # Bounded teardown cancels a stuck sender.
                audio_sender_task.cancel()
        if dropped_audio_frames:
            log.warning(
                "browser_voice: dropped %d stale mic frames under backpressure",
                dropped_audio_frames,
            )
        # A voice hang-up ends the session with its own reason; only a plain
        # socket teardown reports ws_closed.
        end_reason = (
            str(getattr(session, "hangup_reason", "") or "") or HANGUP_WS_CLOSED
        )
        await session.end(reason=end_reason)
