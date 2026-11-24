"""Group ``realtime``: full-duplex speech-to-speech providers.

A realtime provider fuses recognition, reasoning, synthesis and voice-activity
detection into one stateful session. Implement :class:`RealtimeProvider` and
register the class under ``dodaios.realtime``. Import nothing heavy at module
import time: the host lists providers before it opens one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .common import AudioChunk

RealtimeEventType = Literal[
    "audio_delta",
    "output_transcript_delta",
    "input_transcript",
    "handoff_requested",
    "tool_call",
    "speech_started",
    "interrupted",
    "turn_complete",
    "usage",
    "error",
]


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """One normalized, provider-neutral event from a duplex session."""

    type: RealtimeEventType
    audio: AudioChunk | None = None  # audio_delta
    text: str | None = None  # output_transcript_delta / input_transcript
    is_final: bool = False
    shadow: bool = False  # transcript for vetting only; never shown
    voiced_ms: int = 0  # input_transcript finals: voiced duration, 0 = unknown
    ms_played: int | None = None  # speech_started: ms of our audio already heard
    error: str | None = None
    recoverable: bool = False  # the transport stays usable
    reconnect_advised: bool = False  # the provider will close the transport soon
    item_id: str | None = None
    call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    handoff_id: str | None = None
    provider_turn_id: str | None = None
    usage: dict[str, int] | None = None
    self_initiated: bool = False  # an ``interrupted`` the host itself caused
    superseded: bool = False  # the provider abandoned and regenerates the answer


@dataclass(frozen=True, slots=True)
class RealtimeSessionConfig:
    """Everything a provider needs to open one duplex session."""

    instructions: str = ""
    language: str = "en"
    input_language: str = "auto"
    language_is_pinned: bool = False
    model: str = ""  # "" = the adapter's own default
    voice: str = ""
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000
    modalities: tuple[str, ...] = ("audio",)
    turn_detection: str = "server_vad"  # "server_vad" | "semantic_vad"
    silence_duration_ms: int | None = None
    end_of_speech_sensitivity: str | None = None
    turn_pause_ms: int | None = None
    tools: tuple[dict[str, Any], ...] = ()
    history: tuple[dict[str, str], ...] = ()
    transport_offer_sdp: str = ""


@runtime_checkable
class RealtimeSession(Protocol):
    """A live duplex handle (one connection).

    Optional capabilities, read with ``getattr`` and never required:
    ``set_history_snapshot(history)``, ``direct_speech_is_authoritative``,
    ``supports_tool_results``.
    """

    session_id: str
    creates_responses_automatically: bool
    isolates_response_generations: bool

    async def send_audio(self, chunk: AudioChunk) -> None: ...
    def receive(self) -> AsyncIterator[RealtimeEvent]: ...

    async def update_session(
        self,
        *,
        instructions: str | None = None,
        language: str | None = None,
        tools: tuple[dict[str, Any], ...] | None = None,
        turn_directive: str | None = None,
        standing_directive: str | None = None,
    ) -> None: ...

    async def request_response(self, *, required_tool: str | None = None) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def truncate(self, audio_end_ms: int) -> None: ...
    async def interrupt(
        self,
        *,
        retire_input_entitlement: bool = False,
    ) -> None: ...
    async def send_tool_result(self, call_id: str, name: str, result: dict[str, Any]) -> None: ...
    async def close(self) -> None: ...


class RealtimeUnavailableError(RuntimeError):
    """A provider declined the call; the message is a sentence for the person."""


@runtime_checkable
class RealtimeProvider(Protocol):
    """The entry-point class of a realtime plugin."""

    name: str
    supports_realtime: bool
    input_sample_rate: int
    output_sample_rate: int
    credential_candidates: tuple[tuple[str, str | None], ...]

    async def can_open_duplex_session(self) -> bool: ...
    async def open_session(self, cfg: RealtimeSessionConfig) -> RealtimeSession: ...
