"""xAI Grok realtime voice (Voice Agent API) provider plugin.

One WebSocket to ``wss://api.x.ai/v1/realtime``: PCM16 at 24 kHz in both
directions, base64 inside JSON events, function tools declared on the session.
The wire looks like OpenAI Realtime, but this adapter deliberately does NOT
reuse the manual-response contract of ``openai_realtime`` (``create_response:
false`` plus a client ``response.cancel`` on every barge-in). That contract is
what wedged the first Grok adapter in July 2026 (BUG-064): after a client
cancel the xAI server dropped the session settings and went deaf.

Here the server owns the turn, the way the ChatGPT Live and Gemini Live
sessions work: its own VAD closes the user's turn, it creates the response
itself and it stops its own reply when the user talks over it. The client
never cancels a response the server already interrupted. The session runs
under ``dodaios.live.native.NativeLiveVoiceSession``, which executes the
function calls and feeds their results back.

Per the plugin rule this module imports no ``dodaios.*`` at module import;
the websocket stack is imported lazily when a call starts (AP-26).
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import uuid4

log = logging.getLogger(__name__)

_ENDPOINT = "wss://api.x.ai/v1/realtime"
_HOST = "api.x.ai"
_MODEL = "grok-voice-latest"
_RATE = 24_000
_DEFAULT_VOICE = "eve"
_TRANSCRIPTION_MODEL = "grok-transcribe"
_OPEN_TIMEOUT_S = 15.0
# How long the server may take to confirm the session settings. A session
# that never confirms them would talk with xAI defaults (no tools, no
# instructions), which is worse than an honest refusal.
_SESSION_READY_TIMEOUT_S = 10.0
_MAX_MESSAGE_BYTES = 8_000_000
# xAI wants regional codes for these two languages (language_hint is BCP-47).
_LANGUAGE_HINTS = {
    "de": "de",
    "en": "en",
    "fr": "fr",
    "it": "it",
    "ja": "ja",
    "es": "es-ES",
    "pt": "pt-BR",
}

# One fixed sentence per refusal. The provider's body never reaches the user.
_START_REFUSALS = {
    "bad_key": "xAI rejected the API key. Check the xAI Grok key under API Keys.",
    "access_denied": (
        "xAI denied this API key access to Grok voice. Check the key's "
        "permissions and the team's credit in the xAI Console."
    ),
    "rate_limited": "xAI is rate limiting this API key. Try again in a moment.",
    "model_unavailable": "This xAI API key cannot use the selected Grok voice model.",
    "invalid_configuration": (
        "xAI rejected the voice session settings. Check the Grok voice and "
        "model under API Keys."
    ),
    "unreachable": "Grok voice is temporarily unavailable. Try again shortly.",
}


def _refusal_for_status(status: int) -> str:
    if status == 401:
        return "bad_key"
    if status == 403:
        return "access_denied"
    if status == 404:
        return "model_unavailable"
    if status == 429:
        return "rate_limited"
    if status in {400, 422}:
        return "invalid_configuration"
    return "unreachable"


def _start_error(code: str, technical: str) -> Exception:
    """A ``VoiceStartError`` carrying the fixed sentence for ``code``."""
    protocols = importlib.import_module("dodaios.core.protocols")
    return protocols.VoiceStartError(
        technical, user_message=_START_REFUSALS[code], code=code
    )


@dataclass(frozen=True, slots=True)
class _PcmChunk:
    pcm: bytes
    sample_rate: int
    timestamp_ns: int = 0


@dataclass(frozen=True, slots=True)
class _ProviderEvent:
    type: str
    audio: _PcmChunk | None = None
    text: str | None = None
    is_final: bool = False
    error: str | None = None
    recoverable: bool = False
    item_id: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    usage: dict[str, int] | None = None


def _language_hint(cfg: Any) -> str:
    language = str(getattr(cfg, "input_language", "auto") or "auto")
    language = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return _LANGUAGE_HINTS.get(language, "")


def session_payload(cfg: Any) -> dict[str, Any]:
    """The ``session.update`` body for one call.

    Server VAD with automatic responses: the server closes the turn, answers
    and stops its own reply on a barge-in. No silence window is sent; the July
    2026 adapter learned that xAI ignores it, so sending one only pretends.
    """
    transcription: dict[str, Any] = {"model": _TRANSCRIPTION_MODEL}
    hint = _language_hint(cfg)
    if hint:
        transcription["language_hint"] = hint
    voice = str(getattr(cfg, "voice", "") or "").strip()
    if not voice or voice == "auto":
        voice = _DEFAULT_VOICE
    session: dict[str, Any] = {
        "instructions": str(getattr(cfg, "instructions", "") or ""),
        "voice": voice,
        "turn_detection": {"type": "server_vad"},
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": _RATE},
                "transcription": transcription,
            },
            "output": {"format": {"type": "audio/pcm", "rate": _RATE}},
        },
    }
    tools = _function_tools(getattr(cfg, "tools", ()) or ())
    if tools:
        session["tools"] = tools
    return session


def _function_tools(tools: Any) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": str(tool.get("name", "")),
            "description": str(tool.get("description", "")),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        }
        for tool in tuple(tools or ())
        if isinstance(tool, dict) and tool.get("name")
    ]


def _history_items(history: Any) -> list[dict[str, Any]]:
    """Seed items for the earlier conversation (a reconnect or a resumed call)."""
    items: list[dict[str, Any]] = []
    for message in tuple(history or ()):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "") or "")
        text = str(message.get("text", "") or "").strip()
        if not text or role not in {"user", "assistant"}:
            continue
        content_type = "input_text" if role == "user" else "output_text"
        items.append({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
            },
        })
    return items


def _count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        # A usage field the provider omits or sends oddly counts as zero;
        # metering must never break a live call.
        return 0


def _usage(response: Any) -> dict[str, int] | None:
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    total_in = _count(usage.get("input_tokens"))
    total_out = _count(usage.get("output_tokens"))
    if total_in <= 0 and total_out <= 0:
        return None
    in_details = usage.get("input_token_details") or {}
    out_details = usage.get("output_token_details") or {}
    return {
        "input_total": total_in,
        "output_total": total_out,
        "input_text": _count(in_details.get("text_tokens")),
        "input_audio": _count(in_details.get("audio_tokens")),
        "input_cached": _count(in_details.get("cached_tokens")),
        "output_text": _count(out_details.get("text_tokens")),
        "output_audio": _count(out_details.get("audio_tokens")),
    }


def _error_text(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        code = str(error.get("code", "") or error.get("type", "") or "").strip()
        message = str(error.get("message", "") or "").strip()
    else:
        code, message = "", str(error or event.get("message", "") or "").strip()
    if code and message:
        return f"{code}: {message}"[:800]
    return (message or code or "Grok voice session error")[:800]


#: Server event type -> the session method that translates it.
_EVENT_HANDLERS = {
    "response.created": "_on_response_created",
    "response.output_audio.delta": "_on_audio_delta",
    "response.audio.delta": "_on_audio_delta",
    "response.output_audio_transcript.delta": "_on_transcript_delta",
    "response.output_audio_transcript.done": "_on_transcript_done",
    "conversation.item.input_audio_transcription.updated": "_on_input_updated",
    "conversation.item.input_audio_transcription.completed": "_on_input_completed",
    "input_audio_buffer.speech_started": "_on_speech_started",
    "response.function_call_arguments.done": "_on_function_call",
    "response.done": "_on_response_done",
    "error": "_on_error",
}


class GrokRealtimeSession:
    """One live Grok call: the socket plus the response bookkeeping."""

    # The server answers at its own VAD boundary; the orchestrator must not
    # request responses for transcribed turns.
    creates_responses_automatically = True
    supports_tool_updates = True

    def __init__(self, socket: Any, *, model: str, session_id: str = "") -> None:
        self._socket = socket
        self.model = model
        self.session_id = session_id or str(uuid4())
        self._closed = False
        self._response_active = False
        # True after the server signalled the user's speech during a reply:
        # xAI interrupts its own response then, so a client cancel would be a
        # second cancel of the same response (the July 2026 wedge trigger).
        self._server_interrupting = False
        self._transcript_streamed = False
        self._response_had_tool_calls = False
        self._tool_response_done = False
        self._pending_call_ids: set[str] = set()
        # A text turn or tool continuation that arrived while a response was
        # still running; xAI accepts one active response per conversation.
        self._deferred_response = False

    async def _send(self, event: dict[str, Any]) -> None:
        await self._socket.send(json.dumps(event))

    async def send_audio(self, chunk: Any) -> None:
        sample_rate = int(getattr(chunk, "sample_rate", 0) or 0)
        if sample_rate != _RATE:
            raise ValueError(f"Grok voice requires {_RATE} Hz PCM; received {sample_rate} Hz")
        pcm = bytes(getattr(chunk, "pcm", b"") or b"")
        if not pcm or self._closed:
            return
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode("ascii"),
        })

    async def receive(self) -> AsyncIterator[_ProviderEvent]:
        """Normalized events until the socket ends.

        A dropped connection surfaces as ``ConnectionError`` so the live
        session's recovery reopens the call; a clean close after ``close()``
        simply ends the stream.
        """
        while True:
            try:
                raw = await self._socket.recv()
            except Exception as exc:  # broad-except: any transport end is a dropped call
                if self._closed:
                    return
                raise ConnectionError(
                    f"Grok voice connection lost ({type(exc).__name__})"
                ) from exc
            if isinstance(raw, (bytes, bytearray)):
                # Audio travels as JSON (transport "json"); a binary frame is
                # not part of this session's contract.
                continue
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                log.warning("grok-realtime: unreadable server event skipped")
                continue
            if not isinstance(event, dict):
                continue
            async for out in self._dispatch(event):
                yield out

    async def _dispatch(self, event: dict[str, Any]) -> AsyncIterator[_ProviderEvent]:
        name = _EVENT_HANDLERS.get(str(event.get("type", "") or ""))
        if name is None:
            return
        for out in await getattr(self, name)(event):
            yield out

    async def _on_response_created(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        del event
        self._response_active = True
        self._server_interrupting = False
        self._transcript_streamed = False
        self._response_had_tool_calls = False
        return []

    async def _on_audio_delta(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        try:
            pcm = base64.b64decode(str(event.get("delta", "") or ""))
        except (TypeError, ValueError):
            log.warning("grok-realtime: undecodable audio delta skipped")
            return []
        if not pcm:
            return []
        return [_ProviderEvent(type="audio_delta", audio=_PcmChunk(pcm=pcm, sample_rate=_RATE))]

    async def _on_transcript_delta(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        self._transcript_streamed = True
        text = str(event.get("delta", "") or "")
        return [_ProviderEvent(type="output_transcript_delta", text=text)] if text else []

    async def _on_transcript_done(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        # Only when no delta came: a server that sends both must not deliver
        # the line twice.
        text = str(event.get("transcript", "") or "")
        if not text or self._transcript_streamed:
            return []
        return [_ProviderEvent(type="output_transcript_delta", text=text)]

    async def _on_input_updated(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        # Cumulative text of the turn so far, not a delta.
        text = str(event.get("transcript", "") or "")
        if not text:
            return []
        return [_ProviderEvent(
            type="input_transcript", text=text, is_final=False,
            item_id=str(event.get("item_id", "") or "") or None,
        )]

    async def _on_input_completed(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        return [_ProviderEvent(
            type="input_transcript",
            text=str(event.get("transcript", "") or ""),
            is_final=True,
            item_id=str(event.get("item_id", "") or "") or None,
        )]

    async def _on_speech_started(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        del event
        if self._response_active:
            self._server_interrupting = True
        return [_ProviderEvent(type="speech_started")]

    async def _on_function_call(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        call_id = str(event.get("call_id", "") or "")
        self._response_had_tool_calls = True
        if call_id:
            self._pending_call_ids.add(call_id)
        try:
            arguments = json.loads(str(event.get("arguments", "") or "{}"))
        except (TypeError, ValueError):
            # Malformed arguments count as none; the tool layer then names the
            # missing field honestly.
            arguments = {}
        return [_ProviderEvent(
            type="tool_call",
            call_id=call_id,
            tool_name=str(event.get("name", "") or ""),
            tool_args=arguments if isinstance(arguments, dict) else {},
        )]

    async def _on_error(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        # xAI documents most errors as recoverable with the session still
        # open; a dead socket ends receive() instead.
        return [_ProviderEvent(type="error", error=_error_text(event), recoverable=True)]

    async def _on_response_done(self, event: dict[str, Any]) -> list[_ProviderEvent]:
        raw_response = event.get("response")
        response: dict[str, Any] = raw_response if isinstance(raw_response, dict) else {}
        self._response_active = False
        self._server_interrupting = False
        out: list[_ProviderEvent] = []
        usage = _usage(response)
        if usage is not None:
            out.append(_ProviderEvent(type="usage", usage=usage))
        status = str(response.get("status", "") or "").lower()
        if status == "failed":
            out.append(_ProviderEvent(
                type="error", error="Grok voice response failed", recoverable=True
            ))
        if self._response_had_tool_calls and status not in {"cancelled", "failed"}:
            # The answer continues once every function result is back.
            self._response_had_tool_calls = False
            self._tool_response_done = True
            await self._continue_after_tools()
            return out
        self._response_had_tool_calls = False
        # Before returning: the consumer may not pull another event for a long
        # time, and a deferred typed turn must not wait for it.
        if self._deferred_response:
            self._deferred_response = False
            await self._create_response()
        # A cancelled reply ends its turn too; the barge-in itself already
        # arrived as speech_started.
        out.append(_ProviderEvent(type="turn_complete"))
        return out

    async def _create_response(self) -> None:
        if self._closed:
            return
        if self._response_active:
            self._deferred_response = True
            return
        # Marked active at once so a second caller defers instead of racing a
        # second response.create before response.created arrives.
        self._response_active = True
        await self._send({"type": "response.create"})

    async def _continue_after_tools(self) -> None:
        if self._tool_response_done and not self._pending_call_ids:
            self._tool_response_done = False
            await self._create_response()

    async def request_response(self, *, required_tool: str | None = None) -> None:
        del required_tool  # Grok answers with whatever tool the turn needs.
        await self._create_response()

    async def send_text(self, text: str) -> None:
        """A typed turn or an application report: a user item, then a reply."""
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": str(text)}],
            },
        })
        await self._create_response()

    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None:
        del name  # the call id names the call on this wire
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False, default=str),
            },
        })
        self._pending_call_ids.discard(call_id)
        await self._continue_after_tools()

    async def update_session(
        self,
        *,
        instructions: str | None = None,
        language: str | None = None,
        tools: tuple[dict[str, Any], ...] | None = None,
        **_ignored: Any,
    ) -> None:
        """Send only what changed. Grok follows the user's language by itself."""
        del language
        session: dict[str, Any] = {}
        if instructions is not None:
            session["instructions"] = str(instructions)
        if tools is not None:
            session["tools"] = _function_tools(tools)
        if session:
            await self._send({"type": "session.update", "session": session})

    async def interrupt(self) -> None:
        """Stop the running reply, unless the server already stopped it."""
        if not self._response_active or self._server_interrupting or self._closed:
            return
        self._server_interrupting = True
        await self._send({"type": "response.cancel"})

    async def truncate(self, audio_end_ms: int) -> None:
        del audio_end_ms  # the server truncates its own reply on a barge-in

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._socket.close()
        except Exception as exc:  # noqa: BLE001  # broad-except: closing a dead socket is fine
            log.debug("grok-realtime: socket close failed (%s)", type(exc).__name__)


async def _await_session_ready(socket: Any) -> None:
    """Wait for ``session.updated``; an ``error`` first means bad settings."""
    async with asyncio.timeout(_SESSION_READY_TIMEOUT_S):
        while True:
            raw = await socket.recv()
            if isinstance(raw, (bytes, bytearray)):
                continue
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                log.debug("grok-realtime: unreadable event during setup skipped")
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "session.updated":
                return
            if kind == "error":
                raise _start_error(
                    "invalid_configuration",
                    f"Grok voice rejected the session settings ({_error_text(event)}).",
                )


class GrokRealtimeProvider:
    """xAI Grok realtime voice, run by the native live voice session."""

    name = "grok-realtime"
    # The xAI account behind the Grok brain and Grok Voice TTS: one key.
    credential_family = "grok"
    supports_realtime = True
    native_tool_orchestration = True
    browser_audio = True
    # Billed per minute on the user's own xAI account: only when picked.
    implicit_usage_fallback_allowed = False
    input_sample_rate = _RATE
    output_sample_rate = _RATE
    default_model = _MODEL
    default_voice = _DEFAULT_VOICE
    credential_candidates = (
        ("grok_api_key", "GROK_API_KEY"),
        ("xai_api_key", "XAI_API_KEY"),
        ("realtime_grok_api_key", "JARVIS_REALTIME_GROK_API_KEY"),
    )

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = (api_key or "").strip()

    @property
    def duplex_unavailable_reason(self) -> str:
        if self._api_key:
            return ""
        return "Connect an xAI Grok key under API Keys before starting Grok voice."

    async def can_open_duplex_session(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    async def warm_transport(cfg: Any = None) -> None:
        """Pre-import the socket stack and resolve the host; no billed call."""
        del cfg
        from ._live_transport import warm_transport

        await warm_transport()

        def _resolve() -> None:
            try:
                import socket

                socket.getaddrinfo(_HOST, 443)
            except OSError as exc:
                # Offline or DNS-blocked: the handshake reports it honestly.
                log.debug("grok-realtime: host warm-up lookup failed (%s)", type(exc).__name__)

        await asyncio.to_thread(_resolve)

    async def open_session(self, cfg: Any) -> GrokRealtimeSession:
        if not self._api_key:
            raise _start_error("bad_key", "No xAI API key is configured for Grok voice.")
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        from ._live_transport import websocket_options

        model = str(getattr(cfg, "model", "") or "").strip() or _MODEL
        url = f"{_ENDPOINT}?model={quote(model, safe='')}"
        try:
            socket = await connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
                open_timeout=_OPEN_TIMEOUT_S,
                max_size=_MAX_MESSAGE_BYTES,
                **await websocket_options(),
            )
        except InvalidStatus as exc:
            status = int(getattr(exc.response, "status_code", 0) or 0)
            code = _refusal_for_status(status)
            raise _start_error(
                code, f"Grok voice handshake refused (HTTP {status}, {code})."
            ) from exc
        except (OSError, TimeoutError) as exc:
            raise _start_error(
                "unreachable", f"Grok voice could not connect ({type(exc).__name__})."
            ) from exc
        session = GrokRealtimeSession(socket, model=model)
        try:
            await session._send({"type": "session.update", "session": session_payload(cfg)})
            await _await_session_ready(socket)
            for item in _history_items(getattr(cfg, "history", ())):
                await session._send(item)
        except TimeoutError as exc:
            await session.close()
            raise _start_error(
                "unreachable", "Grok voice did not confirm the session settings in time."
            ) from exc
        except ConnectionClosed as exc:
            # xAI may accept the upgrade and close at once on a key it rejects.
            await session.close()
            close_code = int(getattr(getattr(exc, "rcvd", None), "code", 0) or 0)
            code = "bad_key" if close_code in {1008, 4001, 4003} else "unreachable"
            raise _start_error(
                code, f"Grok voice closed the connection during setup (close {close_code})."
            ) from exc
        except BaseException:  # broad-except: close the socket, then re-raise
            await session.close()
            raise
        log.info("grok-realtime: session ready (model %s)", model)
        return session
