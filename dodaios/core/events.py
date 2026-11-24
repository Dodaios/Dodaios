"""Immutable event dataclasses for the internal bus; ``trace_id`` correlates one conversation
turn."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from .protocols import HarnessResult, HarnessTask, RiskTier, Transcript
from .turn_language import DEFAULT_LOCALE

# Every supported locale is equal: a missing language falls back to the shared default, never one
# language.
_DEFAULT_EVENT_LANGUAGE: Final[str] = DEFAULT_LOCALE


def _now_ns() -> int:
    return time.time_ns()


def _new_trace() -> UUID:
    return uuid4()


@dataclass(frozen=True, slots=True)
class Event:
    """Base class for all events — carries correlation and timing information."""
    trace_id: UUID = field(default_factory=_new_trace)
    timestamp_ns: int = field(default_factory=_now_ns)
    source_layer: str = ""


@dataclass(frozen=True, slots=True)
class HotkeyPressed(Event):
    combo: str = ""


@dataclass(frozen=True, slots=True)
class WakeWordDetected(Event):
    keyword: str = ""
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class WakeCandidateDetected(Event):
    """Optimistic, visual-only wake hint; never reaches the recorder, telemetry or brain."""
    active: bool = True
    keyword: str = ""


@dataclass(frozen=True, slots=True)
class ListeningStarted(Event):
    """Jarvis opens the microphone for an utterance."""
    pass


@dataclass(frozen=True, slots=True)
class UtteranceCaptured(Event):
    audio_ref: str = ""      # content hash for the flight recorder
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class TranscriptPartial(Event):
    transcript: Transcript | None = None


@dataclass(frozen=True, slots=True)
class TranscriptFinal(Event):
    transcript: Transcript | None = None
    continues_previous: bool = False


@dataclass(frozen=True, slots=True)
class TranscriptionUpdate(Event):
    text: str = ""
    is_final: bool = False


@dataclass(frozen=True, slots=True)
class VoiceTranscriptUpdated(Event):
    """Idempotent caption snapshot for one continuous-voice speech segment."""

    session_id: str = ""
    segment_id: str = ""
    role: Literal["user", "assistant"] = "user"
    text: str = ""
    start_ms: int = 0
    end_ms: int = 0
    revision: int = 1
    attachments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceContentShown(Event):
    """Content shown on screen during a spoken conversation instead of read out."""

    session_id: str = ""
    title: str = ""
    markdown: str = ""


@dataclass(frozen=True, slots=True)
class ReasoningSummaryUpdated(Event):
    """Provider-exposed reasoning summary, never private reasoning or audio."""

    response_id: str = ""
    text: str = ""
    done: bool = False


@dataclass(frozen=True, slots=True)
class TranscriptPolished(Event):
    """A finished voice turn re-read as prose; arrives after the turn ran (fail-open)."""

    text: str = ""
    raw_text: str = ""
    status: str = ""
    provider: str = ""
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class DictationTranscript(Event):
    """Text of a finished dictation; separate from ``TranscriptionUpdate`` (voice hot path)."""

    text: str = ""
    is_final: bool = False
    #: Resolved route, never ``auto``: ``insert`` (foreign app) or ``chat`` (Jarvis's window); empty
    #: = older backend.
    target: str = ""


@dataclass(frozen=True, slots=True)
class DictationCompleted(Event):
    """A dictation finished: what was produced and where it ended up."""

    text: str = ""
    raw_text: str = ""
    #: One of ``dodaios.dictation.outcomes.DICTATION_OUTCOMES``.
    outcome: str = ""
    detail: str = ""
    method: str = ""
    language: str = ""
    duration_s: float = 0.0
    removed_words: int = 0
    #: Why transcription failed; ``None`` otherwise. Separates ``failed`` from ``empty``.
    error: str | None = None
    #: Polish pass status (``dodaios.dictation.polish.POLISH_STATUSES``); ``""`` = never ran.
    #: ``translated``: ``language`` stays the SPOKEN one.
    polish_status: str = ""
    #: Credential family that answered (``groq``/``gemini``/...); a family id, never a model id.
    polish_provider: str = ""
    polish_latency_ms: int = 0
    stt_providers: tuple[str, ...] = ()
    stt_models: tuple[str, ...] = ()
    detected_languages: tuple[str, ...] = ()
    stt_latency_ms: int = 0
    #: Recognizer calls: one per piece plus each failed call handed on or retried.
    stt_calls: int = 0
    stt_errors: tuple[str, ...] = ()
    #: Compact audit facts (piece count, wait after stop, preprocessing); English machine data.
    stt_audit: tuple[str, ...] = ()
    audio_sample_rate_hz: int = 0
    audio_rms: float = 0.0
    audio_clipping_ratio: float = 0.0
    audio_dropouts: int = 0
    audio_dropout_ms: int = 0


#: Reasons a dictation start is refused (single shared vocabulary). ``voice_session_active`` is
#: LEGACY, kept for older backends.
DICTATION_REFUSAL_REASONS: Final[tuple[str, ...]] = (
    "microphone_unavailable",
    "no_stt",
    "already_running",
    "handover_failed",
    "voice_session_active",
    "pipeline_not_running",
    "nothing_to_paste",
    "history_disabled",
    "paste_unavailable",
)


@dataclass(frozen=True, slots=True)
class DictationStarted(Event):
    """A dictation turn began, before the first audio frame; ``target`` is the raw request."""

    target: str = ""


@dataclass(frozen=True, slots=True)
class DictationTranscribing(Event):
    """Recording stopped; the final transcription is running. ``DictationCompleted`` follows."""


@dataclass(frozen=True, slots=True)
class DictationRefused(Event):
    """A dictation could not start; ``reason`` is from ``DICTATION_REFUSAL_REASONS``."""

    reason: str = ""
    detail: str = ""


#: Product features that can ask for an OS permission (TypeScript twin:
#: ``frontend/src/lib/permissionEvents.ts``).
PERMISSION_FEATURES: Final[tuple[str, ...]] = (
    "voice",
    "dictation",
    "wake_word",
    "computer_use",
    "screen_context",
    "appshot",
    "window_control",
    "dictation_insert",
    "global_shortcuts",
    "audio_ducking",
    "browser_voice",
)

#: Why a feature waits: ``not_determined``, ``denied``, ``restricted`` (profile forbids it),
#: ``needs_settings`` (user flips it in System Settings), ``restart_hint`` (never automatic),
#: ``unavailable``.
PERMISSION_NEEDED_REASONS: Final[tuple[str, ...]] = (
    "not_determined",
    "denied",
    "restricted",
    "needs_settings",
    "restart_hint",
    "unavailable",
)

PERMISSION_NEEDED_PHASES: Final[tuple[str, ...]] = ("os_dialog", "blocked")

#: What caused the episode: ``user`` (a gesture; the app shows its one toast) or ``background``
#: (the app shows nothing, except for the always-listening wake word).
PERMISSION_NEEDED_ORIGINS: Final[tuple[str, ...]] = ("user", "background")


@dataclass(frozen=True, slots=True)
class PermissionNeeded(Event):
    """A feature waits on an OS permission (one coalesced episode per family and feature).

    ``detail`` is for logs only (never exception text, paths or titles); the UI renders i18n copy.
    """

    permissions: tuple[str, ...] = ()
    feature: str = ""
    reason: str = ""
    phase: str = ""
    origin: str = ""
    target: str = ""
    can_prompt: bool = False
    can_open_settings: bool = False
    outside_app: bool = False
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PermissionResolved(Event):
    """The episode ended: granted, or closed unresolved after ten idle minutes."""

    permissions: tuple[str, ...] = ()
    feature: str = ""
    granted: bool = False


#: Why the microphone cannot be heard though permission is granted: ``not_answering`` (OS audio
#: layer silent) or ``silent`` (exact digital silence).
MICROPHONE_TROUBLE_REASONS: Final[tuple[str, ...]] = ("not_answering", "silent")


@dataclass(frozen=True, slots=True)
class MicrophoneTrouble(Event):
    """The microphone cannot be heard; once per episode, on the edge."""

    reason: str = ""
    device: str = ""
    feature: str = ""
    automatic: bool = False


@dataclass(frozen=True, slots=True)
class MicrophoneRecovered(Event):
    """The episode a ``MicrophoneTrouble`` opened is over: the input is heard again."""

    device: str = ""


@dataclass(frozen=True, slots=True)
class IntentClassified(Event):
    intent: str = ""         # "ask" | "execute" | "recall" | "interrupt" | "switch_provider"
    risk_tier: RiskTier = "safe"
    entities: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BrainProviderSwitched(Event):
    from_provider: str = ""
    to_provider: str = ""


@dataclass(frozen=True, slots=True)
class FrontierModelSwitched(Event):
    """A newer model was switched to automatically; the frontend asks for confirmation."""
    provider: str = ""
    tier: str = ""        # "fast" | "deep"
    old_model: str = ""
    new_model: str = ""


@dataclass(frozen=True, slots=True)
class SecretConfigured(Event):
    """A secret was saved or deleted; the UI flips provider cards. The value is NEVER included."""
    key: str = ""
    action: str = "set"  # "set" | "delete"


@dataclass(frozen=True, slots=True)
class ProviderHealthChanged(Event):
    """The passive provider-health record changed; trigger only, never a body or secret."""
    provider: str = ""
    modality: str = ""
    status: str = ""


@dataclass(frozen=True, slots=True)
class UiLanguageChanged(Event):
    """The interface language changed; the frontend switches its i18n live."""
    language: str = ""  # "en" | "de" | "es" | "zh"


@dataclass(frozen=True, slots=True)
class UiThemeChanged(Event):
    """The app's colour theme changed; the frontend repaints live."""
    theme: str = ""  # "dark" | "light" | "system"


@dataclass(frozen=True, slots=True)
class UiDesignChanged(Event):
    """A design was made, changed, deleted or switched (docs/designs.md)."""
    active: str = ""


@dataclass(frozen=True, slots=True)
class ActionProposed(Event):
    tool_name: str = ""
    # One id per executed call, shared by its ActionProposed and ActionExecuted/ActionDenied, so
    # parallel results pair with their call.
    call_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = "safe"
    # The brain's rationale next to this tool call; redacted and length-capped.
    rationale: str = ""
    # Where the call's target came from (ADR-0040, record only): effect kind, target class
    # (``dodaios.safety.origin.TARGET_ORIGINS``) and source tool. Never the value.
    effect: str = ""
    target_origin: str = ""
    origin_source: str = ""


@dataclass(frozen=True, slots=True)
class ActionApprovalRequired(Event):
    """A tool call is paused until this trace receives a decision; ``args_preview`` is redacted."""

    tool_name: str = ""
    risk_tier: RiskTier = "ask"
    reason: str = "risk_tier"  # "risk_tier" | "plausibility" | "trust" | "reversibility"
    args_preview: str = ""
    expires_at_ns: int = 0
    mission_id: str | None = None
    worker_id: str | None = None
    #: Correlation for a surface answering its own approval cards (``agent-chat:<session_id>``).
    approval_ref: str | None = None
    effect: str = ""
    target_origin: str = ""
    origin_source: str = ""


@dataclass(frozen=True, slots=True)
class ActionApproved(Event):
    tool_name: str = ""
    approved_by: str = "auto"  # "auto" | "user" | "whitelist"


@dataclass(frozen=True, slots=True)
class ActionDenied(Event):
    tool_name: str = ""
    reason: str = ""
    call_id: str = ""  # see ActionProposed.call_id


@dataclass(frozen=True, slots=True)
class ActionExecuted(Event):
    tool_name: str = ""
    call_id: str = ""  # see ActionProposed.call_id
    success: bool = False
    duration_ms: int = 0
    error: str | None = None
    output_preview: str = ""
    receipt_id: str = ""
    receipt_state: str = ""
    receipt_summary: str = ""
    receipt_link: str = ""


@dataclass(frozen=True, slots=True)
class HarnessDispatched(Event):
    harness: str = ""
    task: HarnessTask | None = None


@dataclass(frozen=True, slots=True)
class HarnessProgress(Event):
    harness: str = ""
    result: HarnessResult | None = None


@dataclass(frozen=True, slots=True)
class HarnessCompleted(Event):
    harness: str = ""
    result: HarnessResult | None = None


@dataclass(frozen=True, slots=True)
class ResponseGenerated(Event):
    text: str = ""
    language: str = ""
    audio_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechSpoken(Event):
    """Text the playback surface accepted: the authoritative transcript track (AP-9 / AD-OE2)."""
    text: str = ""
    language: str = _DEFAULT_EVENT_LANGUAGE
    spoken_kind: str = "other"
    # Diagnostic that was NOT spoken; None normally.
    detail: str | None = None
    # Voice that spoke this (name, family); None = unknown, never guess from the brain provider.
    voice: str | None = None
    voice_provider: str | None = None
    # True when a classic TTS engine rendered this voice; False when it is only the requested pin.
    voice_verified: bool = True


@dataclass(frozen=True, slots=True)
class MemoryUpdated(Event):
    namespace: str = ""
    key: str = ""
    operation: str = "put"   # "put" | "forget"


@dataclass(frozen=True, slots=True)
class MemoryFileWrite(Event):
    """An agent's memory file is being written or the write settled; carries no path, text or
    error."""
    update_id: str = ""
    agent_id: str = ""
    file: str = ""           # bare name, e.g. "MEMORY.md"; "" when not known yet
    phase: str = "pending"   # pending | saved | unchanged | failed
    operation: str = "edit"  # add | replace | remove | edit


@dataclass(frozen=True, slots=True)
class ProfileUpdated(Event):
    """The Curator wrote a fact to USER.md / people/*.md; the UI may show a "learned" badge."""
    subject: str = ""           # "user" | "person:laura" | "soul"
    cluster: str = ""           # identity | communication | work_style | ...
    field: str = ""             # z.B. "humor_types" oder "observation"
    operation: str = "set"      # set | append | observation
    confidence: float = 1.0
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class ContactChanged(Event):
    """A contact in the address book was written or removed; feeds the wiki contact mirror."""
    action: str = ""
    slug: str = ""
    name: str = ""


@dataclass(frozen=True, slots=True)
class ConfigReloaded(Event):
    changed_keys: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SystemStarted(Event):
    version: str = ""


@dataclass(frozen=True, slots=True)
class SystemStopping(Event):
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SystemStateChanged(Event):
    """High-level supervisor state — rendered by the UI as a pulse badge."""
    new_state: str = "IDLE"         # IDLE | LISTENING | THINKING | SPEAKING | ERROR | PAUSED
    previous: str = "IDLE"


@dataclass(frozen=True, slots=True)
class NavigateSidebar(Event):
    """Ask the desktop UI to switch section; ``target`` narrows to an agent, chat or thread."""
    section: str = ""
    target: str = ""
    target_id: str = ""


@dataclass(frozen=True, slots=True)
class DetachedViewOpened(Event):
    """A section now lives in its own detached window; the origin window unmounts its instance."""
    view: str = ""


@dataclass(frozen=True, slots=True)
class DetachedViewClosed(Event):
    """A detached desktop window was closed; its section returns to the app."""
    view: str = ""


@dataclass(frozen=True, slots=True)
class AgenticIdeTerminalsAdded(Event):
    """Panes were added to the Agentic-IDE workspace from outside its view (voice, CLI)."""
    session_id: str = ""
    names: tuple[str, ...] = ()
    agent: str = ""
    folder: str = ""


@dataclass(frozen=True, slots=True)
class AgenticIdeTerminalsClosed(Event):
    """Panes were closed outside the Agentic-IDE workspace view."""

    session_id: str = ""
    names: tuple[str, ...] = ()
    folder: str = ""


@dataclass(frozen=True, slots=True)
class AgenticIdeWorkspaceChanged(Event):
    """A workspace was opened, restored, activated, renamed or closed; clients re-read the state."""
    session_id: str = ""
    reason: str = ""
    folder: str = ""
    name: str = ""
    open_workspaces: int = 0


@dataclass(frozen=True, slots=True)
class AgenticIdePaneActivity(Event):
    """One pane's agent changed state; the payload is the activity half of a panes row."""
    session_id: str = ""
    key: str = ""
    name: str = ""
    status: str = ""
    activity: str = ""
    activity_since: float = 0.0
    worked: bool = False


@dataclass(frozen=True, slots=True)
class AgenticIdePromptSent(Event):
    """A prompt was typed into one pane by Jarvis; ``submitted`` is true, false or null (unseen)."""
    session_id: str = ""
    terminal: str = ""
    agent: str = ""
    submitted: bool | None = None
    preview: str = ""


@dataclass(frozen=True, slots=True)
class AgenticIdeComposeProgress(Event):
    """One beat of a task brief being written; ``message`` is displayed, never parsed."""

    session_id: str = ""
    terminal: str = ""
    stage: str = ""
    message: str = ""
    kind: str = ""


@dataclass(frozen=True, slots=True)
class AgenticIdeCodingModeChanged(Event):
    """The focused coding mode was switched; ``enabled`` is the EFFECTIVE mode."""

    session_id: str = ""
    enabled: bool = False
    folder: str = ""
    workspace: str = ""


@dataclass(frozen=True, slots=True)
class ThreadCreated(Event):
    thread_id: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class MessageSent(Event):
    """User message — originates from the web UI or the voice pipeline."""
    thread_id: str = ""
    role: str = "user"              # "user" | "assistant" | "system"
    text: str = ""


@dataclass(frozen=True, slots=True)
class TerminalSpawned(Event):
    """A new PTY session was started."""
    terminal_id: str = ""
    shell_id: str = ""
    pid: int = 0


@dataclass(frozen=True, slots=True)
class TerminalOutput(Event):
    """Byte chunk from the PTY — streamed to the UI."""
    terminal_id: str = ""
    data: str = ""


@dataclass(frozen=True, slots=True)
class TerminalClosed(Event):
    """The PTY process has exited (or was closed)."""
    terminal_id: str = ""
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class TerminalCommandExecuted(Event):
    """Audit event on Enter; TUI apps may yield garbage."""
    terminal_id: str = ""
    shell_id: str = ""
    command: str = ""


@dataclass(frozen=True, slots=True)
class AnnouncementRequested(Event):
    """A short interstitial announcement for the TTS pipeline; ``interrupt`` cuts speech, ``normal``
    queues."""
    text: str = ""
    # The strings ARE the Literal values; UP037 would unquote them wrongly.
    priority: Literal["normal", "interrupt"] = "normal"  # noqa: UP037
    language: str = _DEFAULT_EVENT_LANGUAGE
    # Producer discriminator; None for legacy callers. ``progress`` is droppable when stale.
    kind: Literal["preamble", "completion", "subagent", "info", "progress"] | None = None  # noqa: UP037
    detail: str | None = None
    # Raw material for a live model to phrase itself; classic TTS speaks ``text``. Never spoken
    # verbatim.
    report: str | None = None


@dataclass(frozen=True, slots=True)
class DelegationResultReady(Event):
    """A coding result addressed to one existing Jarvis text conversation."""

    session_id: str = ""
    request_id: str = ""
    agent_name: str = ""
    status: str = ""
    text: str = ""
    report: str = ""
    thread_id: str = ""


@dataclass(frozen=True, slots=True)
class MissionCompleted(Event):
    """Terminal mission outcome, bridged from ``MissionBus`` onto the global bus for When-Then
    rules.

    Flat fields on purpose: the scheduler's safe-AST ``filter_expr`` only compares top-level fields.
    """
    mission_id: str = ""
    status: Literal["approved", "failed", "cancelled", "timed_out"] = "approved"  # noqa: UP037
    summary_de: str = ""
    summary_en: str = ""
    result_uri: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class VoiceMuteToggleRequested(Event):
    """User requested a global voice-mute toggle; the pipeline owns the (idempotent) flip."""
    source: str = ""


@dataclass(frozen=True, slots=True)
class DictationPromptModePauseToggleRequested(Event):
    """A surface asked to PAUSE or RESUME Prompt Mode (a runtime hold; the setting stays as set)."""
    source: str = ""


@dataclass(frozen=True, slots=True)
class DictationPromptModeChanged(Event):
    """Authoritative broadcast that ``[dictation].prompt_mode`` changed; ``paused`` is a runtime
    hold."""
    enabled: bool = False
    paused: bool = False
    source: str = ""


@dataclass(frozen=True, slots=True)
class ShowWindowRequested(Event):
    """User asked to bring the desktop window to the foreground (overlay right-click)."""
    source: str = ""


@dataclass(frozen=True, slots=True)
class VoiceMuteChanged(Event):
    """Authoritative broadcast that the voice-mute state flipped; the pipeline is the only
    writer."""
    muted: bool = False
    source: str = ""


@dataclass(frozen=True, slots=True)
class VoiceInputHeld(Event):
    """A live call's microphone is held back while a dictation runs beside it."""
    held: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class VoiceSpeakerMuteChanged(Event):
    """The assistant's voice went silent or audible (session-only); ``revision`` orders updates."""
    muted: bool = False
    source: str = ""
    volume: float = 1.0
    revision: int = 0


@dataclass(frozen=True, slots=True)
class ComposeRequested(Event):
    """A surface asked for a fresh typed conversation (the bar's pen control)."""
    source: str = ""


@dataclass(frozen=True, slots=True)
class PetChanged(Event):
    """The active pet changed (docs/pets.md); ``pet_id`` is a built-in or custom ``u...`` id."""
    pet_id: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class KillRequested(Event):
    """An emergency stop was triggered (hotkey, voice, tray, web UI button)."""
    source: str = ""                    # "hotkey" | "voice" | "tray" | "web"
    reason: str = "user_request"


@dataclass(frozen=True, slots=True)
class KillAcknowledged(Event):
    """A subscriber (CancelToken holder) confirms it has observed the kill signal."""
    holder: str = ""                    # "cu_loop" | "brain_stream" | "task_runner" | ...
    took_ms: int = 0                    # Zeit zwischen KillRequested und Ack


@dataclass(frozen=True, slots=True)
class TaskCancelled(Event):
    """A concrete task/operation was stopped by the kill signal."""
    task_id: str = ""
    reason: str = "kill_switch"


@dataclass(frozen=True, slots=True)
class BudgetWarning(Event):
    """80 % pre-warning. The UI should display this as a banner."""
    scope: str = "task"                 # "task" | "daily"
    spent_eur: float = 0.0
    limit_eur: float = 0.0


@dataclass(frozen=True, slots=True)
class BudgetExceeded(Event):
    """Budget exceeded — the CancelToken has been set."""
    scope: str = "task"
    spent_eur: float = 0.0
    limit_eur: float = 0.0


@dataclass(frozen=True, slots=True)
class CooldownStarted(Event):
    until_ns: int = 0
    reason: str = "budget_daily_exceeded"


@dataclass(frozen=True, slots=True)
class CooldownEnded(Event):
    pass


@dataclass(frozen=True, slots=True)
class ObservationCaptured(Event):
    """The vision engine produced a new observation snapshot."""
    source: str = "composite"           # matches VisionSource.kind
    window_title: str = ""
    node_count: int = 0
    screenshot_hash: str = ""
    screenshot_path: str | None = None


@dataclass(frozen=True, slots=True)
class VisionInjected(Event):
    """The RouterBrain injected a screen observation as an image block; telemetry only."""
    screenshot_hash: str = ""
    bytes_size: int = 0                 # size of the raw PNG data block
    capture_age_ms: int = 0             # age of the observation at inject time


@dataclass(frozen=True, slots=True)
class ScreenCaptureAnnounced(Event):
    """A Screen Context capture is about to happen; published BEFORE any pixels are grabbed."""
    target_kind: str = "monitor"
    target_label: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ScreenCaptureGrabbed(Event):
    """Raw pixels were grabbed; dimensions only, pixels never enter the bus."""

    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class ScreenCaptureCompleted(Event):
    """A Screen Context capture finished (the receipt); metadata only, never screen content."""
    target_kind: str = "monitor"
    target_label: str = ""
    width: int = 0
    height: int = 0
    bytes_size: int = 0
    redaction_count: int = 0
    degradation_count: int = 0
    ui_text_source: str = "none"


@dataclass(frozen=True, slots=True)
class AppshotTaken(Event):
    """An appshot was captured and handed to the conversation; metadata only."""

    appshot_id: str = ""
    trigger: str = ""
    delivered_to: str = ""
    target_label: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class AppshotEditRequested(Event):
    """The user clicked the appshot card: open the editor on the last appshot."""

    appshot_id: str = ""


@dataclass(frozen=True, slots=True)
class JarvisXItemCreated(Event):
    """Jarvis X saved a new screenshot or recording; metadata only."""

    id: str = ""
    kind: str = ""
    mode: str = ""


@dataclass(frozen=True, slots=True)
class JarvisXItemUpdated(Event):
    """A library item changed (an annotated copy was saved)."""

    id: str = ""


@dataclass(frozen=True, slots=True)
class JarvisXItemDeleted(Event):
    """A library item and its files were deleted."""

    id: str = ""


@dataclass(frozen=True, slots=True)
class JarvisXRecordingChanged(Event):
    """A Jarvis X recording started or stopped (not per second)."""

    recording: bool = False
    mode: str = ""
    elapsed_s: float = 0.0


@dataclass(frozen=True, slots=True)
class ActionPlanned(Event):
    """The CU loop planner proposed the next action (before execution)."""
    action_kind: str = ""               # "click" | "type" | "hotkey" | "wait" | "verify"
    target_hint: str = ""               # e.g. "{role:Button,name:Save}"


@dataclass(frozen=True, slots=True)
class ActionVerified(Event):
    """Post-execution verify: did the action produce the expected effect?"""
    action_kind: str = ""
    success: bool = False
    reason: str = ""                    # on fail: what did the verify observer see?


@dataclass(frozen=True, slots=True)
class CUStepProfiled(Event):
    """One Computer-Use loop phase finished; per-phase latency and a liveness heartbeat."""
    phase: Literal[
        "observe", "uia", "plan", "think", "act", "verify", "settle",
    ] = "observe"  # noqa: UP037
    duration_ms: int = 0
    step_idx: int = 0
    engine: str = "v1"
    cache_read_tokens: int = 0


@dataclass(frozen=True, slots=True)
class CUControlStarted(Event):
    """A Computer-Use mission took control of the local mouse/keyboard; missions publish pairs."""
    mission_id: str = ""


@dataclass(frozen=True, slots=True)
class CUControlEnded(Event):
    """A Computer-Use mission released control (published in ``finally``)."""
    mission_id: str = ""
    reason: str = "finished"


#: Liveness events of the CU loop; ``_on_agent_progress`` subscribes to EXACTLY this tuple
#: (tests/unit/harness/test_cu_wave0.py).
CU_PROGRESS_EVENTS: tuple[type, ...] = (
    ObservationCaptured,
    ActionPlanned,
    CUStepProfiled,
)


@dataclass(frozen=True, slots=True)
class TaskScheduled(Event):
    task_id: str = ""
    trigger_type: str = ""              # "after_delay" | "at_time" | "on_event"
    due_at_ns: int = 0
    title: str = ""


@dataclass(frozen=True, slots=True)
class TaskStarted(Event):
    task_id: str = ""


@dataclass(frozen=True, slots=True)
class TaskStepRecorded(Event):
    task_id: str = ""
    seq: int = 0
    kind: str = ""                      # "observation" | "action" | "verify" | "log"


@dataclass(frozen=True, slots=True)
class TaskCompleted(Event):
    task_id: str = ""
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class TaskFailed(Event):
    task_id: str = ""
    error: str = ""
    will_retry: bool = False


@dataclass(frozen=True, slots=True)
class TaskInterrupted(Event):
    """Found on app startup: the task was in state 'running' (cleaned up on startup, ADR-0003)."""
    task_id: str = ""


@dataclass(frozen=True, slots=True)
class AdminOperationRequested(Event):
    op_id: str = ""                     # UUID des Requests
    op_type: str = ""                   # "install_winget" | ...
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class AdminOperationCompleted(Event):
    op_id: str = ""
    op_type: str = ""
    success: bool = False
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class AdminOperationRejected(Event):
    """The destructive prompt was declined, HMAC validation failed, or the op is not allowlisted."""
    op_id: str = ""
    op_type: str = ""
    reason: str = ""                    # "user_declined" | "hmac_invalid" | "not_whitelisted" | ...


@dataclass(frozen=True, slots=True)
class CliStatusChanged(Event):
    """The status of a CLI changed (installed/connected/error)."""
    cli_name: str = ""
    old_status: str = ""          # connected/disconnected/not_installed/error/checking
    new_status: str = ""
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CliInstallProgress(Event):
    """Streaming install output (emitted after every stdout line)."""
    cli_name: str = ""
    job_id: str = ""
    line: str = ""
    done: bool = False
    exit_code: int | None = None


@dataclass(frozen=True, slots=True)
class CliConnectProgress(Event):
    """Streaming connect output for OAuth flows."""
    cli_name: str = ""
    job_id: str = ""
    line: str = ""
    step: str = ""                # browser_open / polling / done / cancelled / timeout
    done: bool = False


@dataclass(frozen=True, slots=True)
class CliInvoked(Event):
    """The brain or user invoked a CLI (drives the pulse indicator in the UI)."""
    cli_name: str = ""
    caller: str = ""              # brain / user / skill:<name>
    command_preview: str = ""


@dataclass(frozen=True, slots=True)
class CliInvocationFinished(Event):
    """Companion event to ``CliInvoked`` — triggers history invalidation in the UI."""
    cli_name: str = ""
    exit_code: int | None = None
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class BrainToolsChanged(Event):
    """The brain tool set changed at runtime (a CLI connected or disconnected)."""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Event):
    layer: str = ""
    error_type: str = ""
    message: str = ""
    recoverable: bool = True



@dataclass(frozen=True, slots=True)
class WorkflowScheduled(Event):
    """A workflow was scheduled; the UI updates the dashboard's next-run time from it."""
    workflow_id: str = ""
    next_run_ns: int = 0
    # ``missed``: the previous slot passed while the app was down and was skipped.
    reason: str = "cron_next"


@dataclass(frozen=True, slots=True)
class WorkflowActivationChanged(Event):
    """A workflow definition was explicitly enabled or disabled."""
    workflow_id: str = ""
    enabled: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowStarted(Event):
    """A workflow run is starting — either manually or triggered by cron."""
    workflow_id: str = ""
    run_id: str = ""
    trigger: str = "manual"         # "manual" | "cron" | "event"
    title: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowStepStarted(Event):
    run_id: str = ""
    step_index: int = 0
    kind: str = ""                  # "brain_prompt" | "harness_dispatch" | "speak" | "tool_call"
    label: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowStepCompleted(Event):
    run_id: str = ""
    step_index: int = 0
    success: bool = False
    duration_ms: int = 0
    output_preview: str = ""        # max 240 characters, for the UI timeline
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowCompleted(Event):
    workflow_id: str = ""
    run_id: str = ""
    success: bool = False
    duration_ms: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class JarvisAgentTaskStarted(Event):
    parent_trace_id: UUID | None = None
    utterance: str = ""
    context_hints: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    max_duration_s: int = 0
    depth: int = 0


@dataclass(frozen=True, slots=True)
class JarvisAgentReviewTriggered(Event):
    iteration: int = 0


@dataclass(frozen=True, slots=True)
class JarvisAgentTaskCompleted(Event):
    success: bool = False
    summary: str = ""
    full_log_len: int = 0
    duration_s: float = 0.0
    cost_estimate_usd: float = 0.0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BrainTurnStarted(Event):
    parent_trace_id: UUID | None = None
    provider: str = ""
    model: str = ""
    intent_level: str = ""
    system_prompt_preview: str = ""


@dataclass(frozen=True, slots=True)
class BrainTurnCompleted(Event):
    tokens_in: int = 0
    tokens_out: int = 0
    #: Prompt tokens served from the vendor's cache; kept apart from the UNCACHED ``tokens_in``.
    tokens_cached: int = 0
    cost_usd: float = 0.0
    text_len: int = 0
    finish_reason: str = ""
    # The SUCCESSFUL provider/model: BrainTurnStarted can fire several times per turn (fallback
    # chain), Completed only when tokens arrived.
    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class BrainTTFT(Event):
    """Time to first token; ``cache_hit`` = ``cache_read_input_tokens > 0``."""
    cache_hit: bool = False
    model: str = ""


@dataclass(frozen=True, slots=True)
class AudioOutFirst(Event):
    """First audible output began; the last stage event of a voice turn (TTFW)."""
    pass


class LatencyPhase(StrEnum):
    """Single source of truth for latency span names; ``LatencySpan`` rejects unlisted ones."""

    STT_FINALIZE = "stt_finalize"
    INTENT_DECISION = "intent_decision"
    ACK_FIRST_TOKEN = "ack_first_token"  # noqa: S105 — phase name, not a secret
    ACK_FIRST_AUDIO = "ack_first_audio"
    BRAIN_FIRST_TOKEN = "brain_first_token"  # noqa: S105 — phase name, not a secret
    BRAIN_FIRST_AUDIO = "brain_first_audio"
    TURN_TO_FIRST_AUDIO = "turn_to_first_audio"
    STT_FIRST_PARTIAL = "stt_first_partial"
    BRAIN_REQUEST_SENT = "brain_request_sent"  # noqa: S105
    BRAIN_LAST_TOKEN = "brain_last_token"  # noqa: S105
    TTS_REQUEST_SENT = "tts_request_sent"  # noqa: S105
    TTS_FIRST_CHUNK = "tts_first_chunk"
    TTS_STREAM_DONE = "tts_stream_done"
    # Realtime duplex mode; FIRST_AUDIO is the provider's first delta (before scrub-hold).
    REALTIME_INPUT_COMMITTED = "realtime_input_committed"
    REALTIME_ROUTING_DECISION = "realtime_routing_decision"
    REALTIME_FIRST_TRANSCRIPT = "realtime_first_transcript"
    REALTIME_FIRST_AUDIO = "realtime_first_audio"
    REALTIME_DELEGATE_STARTED = "realtime_delegate_started"
    REALTIME_DELEGATE_BRIDGE_REQUESTED = "realtime_delegate_bridge_requested"
    REALTIME_DELEGATE_COMPLETED = "realtime_delegate_completed"
    # The provider closed a content-bearing turn without output and was re-asked natively.
    REALTIME_EMPTY_TURN_REASK = "realtime_empty_turn_reask"
    REALTIME_TOOL_COMPLETED = "realtime_tool_completed"
    REALTIME_SCRUB_CANCEL = "realtime_scrub_cancel"
    REALTIME_CANCEL = "realtime_cancel"
    REALTIME_TURN_COMPLETE = "realtime_turn_complete"


_LATENCY_PHASE_VALUES: frozenset[str] = frozenset(p.value for p in LatencyPhase)


@dataclass(frozen=True, slots=True)
class LatencySpan(Event):
    """A measured interval on the voice hot path; ``timestamp_ns`` stays wall-clock."""

    phase: str = ""
    duration_ms: float = 0.0
    t_start_ns: int = 0
    t_end_ns: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if self.phase not in _LATENCY_PHASE_VALUES:
            raise ValueError(f"unknown latency phase: {self.phase!r}")


@dataclass(frozen=True, slots=True)
class LatencyTurnComplete(Event):
    """All per-turn latency marks were emitted; carries the anchor and stage offsets (ms)."""

    anchor_ns: int = 0
    stages_ms: dict[str, float] = field(default_factory=dict)
    stt_input_audio_ms: float = -1.0
    brain_input_tokens: int = -1
    brain_output_tokens: int = -1
    tts_input_chars: int = -1
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SpeechUsageRecorded(Event):
    """What one turn spent on hearing (per audio second) and speaking (per character)."""

    stage: str = ""
    provider: str = ""
    voice: str = ""
    chars: int = 0
    audio_ms: float = 0.0
    cost_usd: float = 0.0
    price_source: str = "unknown"


@dataclass(frozen=True, slots=True)
class VoiceBootStatus(Event):
    """Voice warm-up readiness; drives the UI "voice starting" badge (``voice_usable`` is the strict
    contract)."""
    ready: bool = False
    detail: str = ""

    @property
    def voice_usable(self) -> bool:
        """Whether this event truthfully confirms a usable local voice path."""
        return self.ready and self.detail not in {
            "voice_unavailable",
            "watchdog_timeout",
        }


@dataclass(frozen=True, slots=True)
class VoiceSessionStarted(Event):
    """Wake word detected — a new voice session is starting."""
    session_id: str = ""
    wake_keyword: str = ""
    language: str = _DEFAULT_EVENT_LANGUAGE


@dataclass(frozen=True, slots=True)
class BrowserVoiceRequested(Event):
    """A desktop trigger hands a voice call to the browser media owner."""

    action: Literal["start", "stop"] = "start"
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class RealtimeSessionReady(Event):
    """A duplex provider accepted the effective session configuration."""

    session_id: str = ""
    provider: str = ""
    model: str = ""
    surface: str = ""
    input_sample_rate: int = 0
    output_sample_rate: int = 0
    #: The call's output language (bare tag) from the ONE turn-language resolver.
    language: str = ""


@dataclass(frozen=True, slots=True)
class VoiceTurnStarted(Event):
    """A new turn within the active session is starting."""
    session_id: str = ""
    turn_id: str = ""
    turn_index: int = 0


@dataclass(frozen=True, slots=True)
class VoiceTurnCompleted(Event):
    """Turn complete — Jarvis has replied, pipeline returns to LISTENING."""
    session_id: str = ""
    turn_id: str = ""
    user_text: str = ""
    user_lang: str = _DEFAULT_EVENT_LANGUAGE
    jarvis_text: str = ""
    jarvis_lang: str = _DEFAULT_EVENT_LANGUAGE
    tier: str = ""
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_total_ms: int = 0
    tool_calls: tuple[str, ...] = ()
    voice: str | None = None
    voice_provider: str | None = None


@dataclass(frozen=True, slots=True)
class VoiceSessionEnded(Event):
    """Session ended (voice_pattern / hotkey / idle_timeout / shutdown / error)."""
    session_id: str = ""
    hangup_reason: str = ""
    turn_count: int = 0
    duration_s: float = 0.0
    detail: str = ""


@dataclass(frozen=True, slots=True)
class VoiceProviderRefused(Event):
    """A realtime provider refused to start a call; ``message`` is authored text, never a provider
    body (AP-34)."""

    session_id: str = ""
    provider: str = ""
    kind: str = ""
    message: str = ""
    continued_on: str = ""


@dataclass(frozen=True, slots=True)
class RealtimeSessionPostmortem(Event):
    """Health counters of one finished realtime session (flight recorder only; no transcript
    text)."""

    session_id: str = ""
    provider: str = ""
    surface: str = ""
    hangup_reason: str = ""
    duration_ms: int = 0
    ready_ms: int = 0
    first_audio_ms: int = 0
    #: First user FINAL to first AUDIBLE provider frame (the perceived wait); 0 = never measured.
    first_final_to_first_audio_ms: int = 0
    turns_completed: int = 0
    rebuilds: int = 0
    stun_retries: int = 0
    ungrounded_captions_dropped: int = 0
    ungrounded_responses_refused: int = 0
    trusted_permit_responses: int = 0
    quiescence_boundary_turns: int = 0
    terminal_item_turns: int = 0
    #: Back-to-back responses that spliced into one playback stream (<1.5 s).
    response_splices: int = 0
    sequenced_boundaries: int = 0
    output_shadow_recovery_attempts: int = 0
    output_shadow_recovery_successes: int = 0
    output_shadow_recovery_exhausted: int = 0
    output_terminal_recovery_attempts: int = 0
    output_terminal_recovery_successes: int = 0
    output_transcript_recovery_failures: int = 0
    response_identity_drops: int = 0
    late_response_readoptions: int = 0
    unsafe_output_cancellations: int = 0
    public_fact_grounding_attempts: int = 0
    public_fact_grounding_successes: int = 0
    public_fact_grounding_failures: int = 0
    output_language_mismatches: int = 0
    output_language_retries: int = 0
    output_language_failures: int = 0
    delegate_delivery_claims: int = 0
    delegate_deliveries_completed: int = 0
    delegate_delivery_recoveries: int = 0
    delegate_delivery_duplicates_suppressed: int = 0
    delegate_deliveries_detached: int = 0
    #: ADR-0035 hybrid tool mode: native calls, failures, refusals, and turns handed to the Tool
    #: Model.
    native_tool_calls: int = 0
    native_tool_failures: int = 0
    native_tool_denied: int = 0
    delegate_cu_dispatches: int = 0
    #: Provider generations discarded whole: started after a readback with no user input (BUG-143).
    stale_generations_dropped: int = 0
    opening_responses_bounded: int = 0
    self_dialogue_rebuilds: int = 0
    handoff_action_turns: int = 0
    handoff_requests: int = 0
    handoff_delegate_dispatches: int = 0
    handoff_declines: int = 0
    handoff_obligation_misses: int = 0
    #: Delegate-by-default dispatches on a tool-less transport (session delegated instead of letting
    #: the far end answer).
    handoff_ambiguous_delegations: int = 0
    mute_emergency_releases: int = 0
    sender_pacing_resyncs: int = 0
    sender_shed_frames: int = 0
    sender_catchup_dropped_frames: int = 0
    recv_dropped_frames: int = 0
    max_loop_stall_ms: int = 0
    language_flips: int = 0
    #: False when teardown abandoned a provider socket or the stream failed.
    close_clean: bool = True


@dataclass(frozen=True, slots=True)
class ToolCallStarted(Event):
    parent_trace_id: UUID | None = None
    tool_name: str = ""
    args_preview: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallCompleted(Event):
    success: bool = False
    duration_ms: float = 0.0
    output_preview: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AssistantTextDelta(Event):
    """The assistant's reply while still being produced; ``text`` is the CUMULATIVE snapshot, never
    a chunk."""

    text: str = ""
    thread_id: str = ""
    channel: str = ""
    done: bool = False


@dataclass(frozen=True, slots=True)
class JarvisAgentBackgroundCompleted(Event):
    """A background Jarvis-Agent task finished; TTS should speak proactively."""
    success: bool = False
    utterance: str = ""       # what the user originally said
    summary: str = ""          # TTS-tauglich, max 120 Tokens
    error: str | None = None
    duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class JarvisAgentAnnouncement(Event):
    """Jarvis-Agent spawn start signal for UI/telemetry, without a voice ACK."""
    action: str = ""   # z.B. "eine Flask-App baut"
    target: str = ""   # z.B. "auf Port 8000"


@dataclass(frozen=True, slots=True)
class AchievementUnlocked(Event):
    """An achievement was just unlocked; the UI shows a toast. Published once per achievement."""
    achievement_id: str = ""
    title: str = ""
    description: str = ""
    tier: str = "mastery"        # "mastery" | "reflection" | "social"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BioFeedbackRecorded(Event):
    """The user clicked a reaction button under the AI profile.

    Kinds: ``trifft`` (accurate)  # i18n-allow: API contract identifier
    ``trifft_nicht`` (off the mark)  # i18n-allow: API contract identifier
    ``haerter`` (more pointed)  # i18n-allow: API contract identifier
    """
    bio_generated_at: str = ""
    # API/DB identifiers matched in logic.  # i18n-allow
    kind: str = ""  # "trifft" | "trifft_nicht" | "haerter"  # i18n-allow


@dataclass(frozen=True, slots=True)
class IdleEntered(Event):
    """The user has had no mouse/keyboard input for a while (no built-in watcher publishes it
    now)."""
    idle_since_ns: int = 0



@dataclass(frozen=True, slots=True)
class SocietyCheckpointChanged(Event):
    """A society agent's derived place on the island changed; the World stage re-reads its
    roster."""

    agent_id: str = ""
    checkpoint: str = ""
    previous: str = ""


@dataclass(frozen=True, slots=True)
class SocietyQuestChanged(Event):
    """A quest on the society's board changed state; the Quest Board re-reads its list."""

    quest_id: str = ""
    state: str = ""
    previous: str = ""
    agent_id: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class SocietyTeamChanged(Event):
    """A team's lead, goals or tasks changed; the team board re-reads."""

    group_id: str = ""
    goal_id: str = ""
    state: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SocietyMessageSent(Event):
    """One agent spoke to another or into a room; ``text`` is a preview, never the body.

    The board trace rides as ``society_trace`` because the WS sanitizer lifts ``trace_id`` out.
    """

    event_id: str = ""
    seq: int = 0
    msg_type: str = ""
    from_agent: str = ""
    #: "" means the line went into a room rather than to one teammate.
    to_agent: str = ""
    #: "" means a direct message.
    room_id: str = ""
    #: Named for the builtin it would otherwise shadow (``round``).
    room_round: int = 0
    society_trace: str = ""
    text: str = ""
    text_chars: int = 0
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SocietyRoomChanged(Event):
    """A bounded group discussion opened or settled (``dodaios/society/rooms.py``)."""

    room_id: str = ""
    phase: str = ""
    opened_by: str = ""
    members: tuple[str, ...] = ()
    topic: str = ""
    reason: str = ""
    rounds: int = 0
    messages: int = 0
    max_rounds: int = 0
    max_messages: int = 0
    society_trace: str = ""



@dataclass(frozen=True, slots=True)
class UserVisibleFeedback(Event):
    """Generalised "did the user receive the feedback?" event (ADR-0016): intent vs observed."""
    surface: str = ""
    expected: dict[str, Any] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class OrbResetRequested(Event):
    """User asked to reset the orb to its default anchor (BUG-027 / L2).

    Literal voice phrases from the local action gate:
    "Orb zurück",  # i18n-allow: German voice-trigger phrase matched in logic
    "wo bist du",  # i18n-allow: German voice-trigger phrase matched in logic
    or "reset orb". ``ui.orb.bus_bridge`` dispatches the reset onto the Tk thread.
    """
    source: str = ""  # "voice" | "tray" | "test"


@dataclass(frozen=True, slots=True)
class MarketplaceItemInstalled(Event):
    """One marketplace entry just landed on this machine, from any surface."""
    kind: str = ""  # "skill" | "plugin" | "agent"
    item_id: str = ""
    title: str = ""
    ready: bool = False


@dataclass(frozen=True, slots=True)
class SelfBuildChanged(Event):
    """A build in the self-building ledger was opened or changed state."""

    build_id: str = ""
    kind: str = ""
    state: str = ""
    title: str = ""


@dataclass(frozen=True, slots=True)
class SelfChangeChanged(Event):
    """A self-change was recorded or changed state (candidate, trial, live, reverted)."""

    change_id: str = ""
    surface: str = ""
    state: str = ""
    target: str = ""


@dataclass(frozen=True, slots=True)
class NodeChanged(Event):
    """A node was created or revised (published by :mod:`dodaios.nodes.live` after every store
    write).

    See ``docs/node-live-build.md``; a person's save never starts a playback.
    """

    node_id: str = ""
    ref: str = ""
    slug: str = ""
    node_type: str = ""
    title: str = ""
    version: int = 0
    previous_version: int = 0
    updated_at: float = 0.0
    action: str = ""
    rewrite: bool = False
    #: The ``changes`` applied, in order (JSON Pointer ops); a value too large to send is ``None``,
    #: marked ``value_omitted``.
    ops: list[dict[str, Any]] = field(default_factory=list)
    author_kind: str = "person"
    author_name: str = ""
    #: Tells authors apart: ``lead``, ``agent:<id>``, ``thread:<session id>``.
    author_id: str = ""
    session_id: str = ""
    step: str = ""
