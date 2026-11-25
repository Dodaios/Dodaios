"""Typing-only view of the host class for the mixins in this package.

The mixins read attributes the host `__init__` sets and call methods their
sibling mixins define. This class declares them so the type checker sees them.
It is imported under `TYPE_CHECKING` only; at run time the mixins derive from
`object` and nothing here exists.
"""
from __future__ import annotations

import asyncio
import collections
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from dodaios.audio.player import AudioPlayer
from dodaios.core.bus import EventBus
from dodaios.core.delegation import ResultInbox
from dodaios.core.events import AnnouncementRequested
from dodaios.core.protocols import AudioChunk
from dodaios.plugins.stt.fwhisper import FasterWhisperProvider
from dodaios.plugins.tts.gemini_flash_tts import GeminiFlashTTS
from dodaios.plugins.wake.openwakeword_provider import OpenWakeWordProvider
from dodaios.plugins.wake.vosk_kws_provider import VoskKwsProvider
from dodaios.speech.echo_guard import SelfEchoGuard
from dodaios.speech.hangup import HangupConfirmation
from dodaios.speech.pipeline import (
    BrainCallback,
    PipelineState,
    TurnTakingState,
    _ChunkSource,
    _SessionInputBuffer,
)
from dodaios.speech.rolling_whisper_wake import RollingWhisperWake
from dodaios.speech.usage_sink import SpeechSpendRecorder
from dodaios.state.supervisor import Supervisor
from dodaios.telemetry.latency import LatencyTracker
from dodaios.trigger.hotkey import HotkeyTrigger


class SpeechPipelineHostState:
    """Attributes and cross-mixin methods of the host, typed for checking only."""

    _BG_READBACK_PHRASES: dict[str, dict[str, str]]
    _INSTANT_ACK_SOURCE_LAYER: str
    _ack_brain: Any
    _ack_pcm: bytes
    _ack_phrase: str
    _activation_gate: Callable[[], bool]
    _active_realtime_handle: Any | None
    _active_realtime_model: str
    _active_realtime_provider: str
    _agent_reply_attempts: dict[Any, Any]
    _agent_reply_inflight: AnnouncementRequested | None
    _agent_reply_inflight_session: None
    _agent_reply_inflight_text: str
    _agent_reply_retries: list[AnnouncementRequested]
    _agent_reply_retry_task: asyncio.Task[None] | None
    _assistant_work_count: Any | int
    _audio_topology_task: asyncio.Task | None
    _base_brain: BrainCallback
    _brain: BrainCallback
    _brain_last_progress: float
    _brain_thinking_heartbeat: float
    _brain_timeout_s: float
    _brain_timeout_spoken_this_turn: bool
    _bus: EventBus | None
    _call_event: asyncio.Event
    _call_hotkeys: tuple[str, ...] | list[str]
    _config: Any
    _continue_listening_after_response: bool
    _current_voice_session_id: str | None
    _deferred_announcements: list[AnnouncementRequested]
    _deferred_warmup_task: asyncio.Task | None
    _delegation_inbox: ResultInbox
    _delegation_result_task: asyncio.Task[None]
    _detached_publishes: set[asyncio.Task[None]]
    _dictate_early_pending: bool
    _dictate_hotkeys: list[str]
    _dictate_key_down: bool
    _dictate_key_seen_at: float
    _dictate_mode: str
    _dictate_toggle_hotkeys: list[str]
    _dictation_anchor_primed: bool
    _dictation_beside_call: bool
    _dictation_cfg: Any
    _dictation_completion_published: bool
    _dictation_discard_requested: bool
    _dictation_handover_task: asyncio.Task[None] | None
    _dictation_language_readings: collections.deque[Any]
    _dictation_leave_no_trace: bool
    _dictation_max_s: float
    _dictation_parakeet_instance: Any
    _dictation_parakeet_rest: Any
    _dictation_resolution_cache: Any
    _dictation_started_by: str
    _dictation_stop_event: asyncio.Event
    _dictation_target: str
    _dictation_task: asyncio.Task[None] | None
    _dictation_wake_block_until: float
    _dictation_warmup_shutdown: bool
    _dictation_warmup_task: asyncio.Task | None
    _dictation_whisper_worker: Any
    _engine_change_reason: str
    _explicit_call_pending: bool
    _explicit_hangup_lock_s: float
    _explicit_hard_hangup: bool
    _external_hangup_pending: threading.Event
    _hangup_confirmation: HangupConfirmation
    _hangup_event: asyncio.Event
    _hangup_hotkeys: tuple[str, ...] | list[str]
    _hangup_requested_at: float
    _heartbeat_interval_s: float
    _heartbeat_max_count: int
    _heartbeat_recent: deque[str]
    _hotkey_reload_event: asyncio.Event
    _hotkey_trigger: Any
    _idle_deadline_monotonic: float | None
    _idle_hangup_enabled: bool
    _idle_timeout_s: float
    _input_device: int | str | None
    _input_priority: tuple[str, ...]
    _input_suppressed_until_ns: int
    _last_answer_floor_monotonic: float | None
    _last_interrupt_announcement_ts: float | None
    _last_preamble_spoken: tuple[str, float] | None
    _last_user_activity_monotonic: None
    _last_wake_keyword: str
    _latency_first_audio_marked: bool
    _latency_tracker: LatencyTracker | None
    _listening_cue_started: bool
    _listening_cue_task: asyncio.Task[None] | None
    _live_replies_restored_for: str
    _long_tool_last_activity: float
    _muted: bool
    _openwakeword_enabled: bool
    _output_device: int | str | None
    _output_priority: tuple[str, ...]
    _paste_last_busy: bool
    _paste_last_hotkeys: list[str]
    _pending_session_preroll: deque[AudioChunk]
    _permission_gate: Any
    _player: AudioPlayer
    _post_hangup_lock_s: float
    _post_tts_listen_suppression_s: float
    _preamble_spoken_times: deque[float]
    _previous_turn_state: str | None
    _probe_stt: Any
    _realtime_audio_renderer: Callable[[], str | None] | None
    _realtime_surface_tts_cache: tuple[str, Any | None]
    _reopen_after_engine_change: bool
    _require_hey_prefix: bool
    _runtime_loop: asyncio.AbstractEventLoop | None
    _self_echo_guard: SelfEchoGuard
    _spawn_watchdog_delay_s: float
    _spawn_watchdog_tasks: list[asyncio.Task[Any]]
    _speak_playback_ceiling_s: float
    _speak_playback_stall_s: float
    _speaker_mute_lock: threading.RLock
    _speaker_muted: bool
    _speaker_muted_last: bool | None
    _speaker_output_revision: int
    _speech_spend: SpeechSpendRecorder | None
    _state: PipelineState
    _stt: FasterWhisperProvider | None
    _supervisor: Supervisor | None
    _task_ack_pcm: dict[tuple[str, str], bytes]
    _termination_detail: dict[str, Any]
    _termination_producer: str
    _tts: GeminiFlashTTS | Any
    _tts_volume_requested: float
    _turn_state: TurnTakingState
    _user_activation_gate: Callable[[], bool]
    _utterance_stt: Any
    _vision_provider: Any
    _voice_engine_transitioning: bool
    _voice_input_held: bool
    _voice_start_monotonic: float | Any
    _voice_stt_warmup_provider: Any
    _voice_stt_warmup_task: asyncio.Task | None
    _wake: OpenWakeWordProvider | VoskKwsProvider
    _wake_cancel_event: asyncio.Event
    _wake_capture_released: asyncio.Event
    _wake_detected_monotonic: float
    _wake_handoff_buffer: _SessionInputBuffer | None
    _wake_handoff_hangup_pending: threading.Event
    _wake_handoff_ready: asyncio.Event
    _wake_lock_until: float
    _wake_matcher: Any | None
    _wake_parked_on_permission: bool
    _wake_phrase_label: Any | str
    _wake_plan: Any
    _wake_preroll_active: bool
    _wake_preroll_confirmed: bool
    _wake_reload_event: asyncio.Event
    _wake_stop_event: asyncio.Event
    _wake_word_enabled: bool | None
    _warmup_background_task: asyncio.Task | None
    _warmup_ready_cue_task: asyncio.Task | None
    _whisper_wake: RollingWhisperWake | None
    _whisper_wake_enabled: bool

    async def _abort_pending_wake_handoff(self) -> None:
        raise NotImplementedError

    def _activation_allowed(self) -> bool:
        raise NotImplementedError

    def _activation_block_reason(self, *, explicit: bool=..., include_permission: bool=...) -> str:
        raise NotImplementedError

    def _activation_state_allows(self) -> bool:
        raise NotImplementedError

    def _agent_reply_floor_open(self) -> bool:
        raise NotImplementedError

    def _agent_reply_needs_session(self) -> bool:
        raise NotImplementedError

    async def _await_ack_turn_commit(self, grace_ms: int) -> bool:
        raise NotImplementedError

    @classmethod
    def _bcp47(cls, lang: object) -> str | None:
        raise NotImplementedError

    def _build_hotkey_bindings(self) -> tuple[dict[str, list[str]], set[str]]:
        raise NotImplementedError

    def _cancel_spawn_heartbeats(self) -> None:
        raise NotImplementedError

    @asynccontextmanager
    async def _capture_dictation_input(self) -> AsyncIterator[_ChunkSource]:
        raise NotImplementedError
        yield

    @asynccontextmanager
    async def _capture_first_session_input(self) -> AsyncIterator[_SessionInputBuffer]:
        raise NotImplementedError
        yield

    def _commit_dictation(self, loop: asyncio.AbstractEventLoop, *, target: str, source: str=..., beside_call: bool=...) -> bool:
        raise NotImplementedError

    def _defer_agent_reply(self, event: AnnouncementRequested) -> None:
        raise NotImplementedError

    def _dictation_blocks_activation(self) -> bool:
        raise NotImplementedError

    def _dictation_protected_terms(self) -> tuple[str, ...]:
        raise NotImplementedError

    def _dictation_resolution(self) -> Any:
        raise NotImplementedError

    async def _dictation_session(self) -> None:
        raise NotImplementedError

    def _emit_spoken(self, text: str, language: str | None, kind: str, detail: str | None=..., tts: Any | None=...) -> None:
        raise NotImplementedError

    def _ensure_microphone(self, feature: str) -> str | None:
        raise NotImplementedError

    def _ensure_voice_stt_warmup(self) -> asyncio.Task[None] | None:
        raise NotImplementedError

    def _gesture_activation_allowed(self) -> bool:
        raise NotImplementedError

    async def _hotkey_loop(self, trigger: HotkeyTrigger) -> None:
        raise NotImplementedError

    async def _hotkey_reload_loop(self, trigger: HotkeyTrigger) -> None:
        raise NotImplementedError

    def _interim_line_spoke_recently(self, within_s: float) -> bool:
        raise NotImplementedError

    @staticmethod
    def _is_agent_reply(event: AnnouncementRequested) -> bool:
        raise NotImplementedError

    @staticmethod
    def _live_call() -> Any | None:
        raise NotImplementedError

    def _live_call_owns_microphone(self) -> bool:
        raise NotImplementedError

    def _note_instant_ack_spoken(self, text: str, at: float | None=...) -> None:
        raise NotImplementedError

    async def _on_announcement(self, event: AnnouncementRequested, *, cancel_heartbeats: bool=...) -> None:
        raise NotImplementedError

    def _output_language(self, stt_language: object, text: str) -> str:
        raise NotImplementedError

    def _permission_service(self) -> Any:
        raise NotImplementedError

    async def _play_earcon(self, pcm: bytes, *, sample_rate: int=...) -> None:
        raise NotImplementedError

    def _playback_confirmed(self, result: object) -> bool:
        raise NotImplementedError

    def _post_hangup_lock_seconds(self) -> float:
        raise NotImplementedError

    async def _publish_event(self, event: Any) -> None:
        raise NotImplementedError

    def _publish_event_soon(self, event: Any) -> None:
        raise NotImplementedError

    def _realtime_voice_handle(self) -> Any | None:
        raise NotImplementedError

    def _recent_dictation_language(self) -> str:
        raise NotImplementedError

    def _refuse_dictation(self, reason: str, detail: str) -> None:
        raise NotImplementedError

    def _register_assistant_speech(self, text: str) -> None:
        raise NotImplementedError

    def _rest_dictation_parakeet(self) -> None:
        raise NotImplementedError

    def _restore_agent_replies(self) -> None:
        raise NotImplementedError

    def _retry_agent_reply_after_boundary(self) -> None:
        raise NotImplementedError

    def _schedule_delegation_results(self) -> None:
        raise NotImplementedError

    def _schedule_dictation_warmup(self, provider: Any=...) -> None:
        raise NotImplementedError

    async def _set_turn_state(self, new_state: TurnTakingState, *, only_from: TurnTakingState | None=...) -> None:
        raise NotImplementedError

    def _speech_trace(self) -> str:
        raise NotImplementedError

    async def _state_loop(self) -> None:
        raise NotImplementedError

    def _termination_snapshot(self, reason: str) -> dict[str, Any]:
        raise NotImplementedError

    async def _transition(self, new_state: str) -> None:
        raise NotImplementedError

    def _trigger_voice_hangup(self, *, stop_player: bool=...) -> None:
        raise NotImplementedError

    def _user_capture_allowed(self) -> bool:
        raise NotImplementedError

    def _voice_session_holds_microphone(self) -> bool:
        raise NotImplementedError

    def _wake_listening_enabled(self) -> bool:
        raise NotImplementedError

    async def _wake_loop(self) -> None:
        raise NotImplementedError

    async def _watch_dictation_hold_key(self) -> None:
        raise NotImplementedError

    def dictation_active(self) -> bool:
        raise NotImplementedError

    @property
    def is_speaker_muted(self) -> bool:
        raise NotImplementedError

    def request_dictation_stop(self, *, discard: bool=...) -> bool:
        raise NotImplementedError

    def request_hangup(self) -> None:
        raise NotImplementedError

    def start_dictation(self, *, target: str=..., source: str=...) -> bool:
        raise NotImplementedError

    def stop_dictation(self) -> bool:
        raise NotImplementedError
