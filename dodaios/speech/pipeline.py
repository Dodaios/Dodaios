"""Speech pipeline with call/hangup state and parallel wake detection.

Wake detection runs in IDLE through two paths sharing one microphone fanout:

1. openWakeWord -- fast (15-30 ms), but less robust across pronunciations.
2. Whisper wake -- robust (800-1200 ms) and natively multilingual.

Activation feedback is visual while capture is live, avoiding both an input
dead zone and speaker echo in the recorded utterance. Global call/hangup
hotkeys remain active alongside wake detection.
"""
from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import random
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import numpy as np

from dodaios.audio import level_tap, mic_level
from dodaios.audio.capture import (
    REALTIME_QUEUE_CHUNKS,
    MicrophoneAccessError,
    MicrophoneCapture,
    MicrophoneStuckError,
    capture_chunks_for_duration,
    last_input_name,
    pcm_bytes_to_np,
)
from dodaios.audio.chime import (
    CHIME_PCM,
    CHIME_SAMPLE_RATE,
    DISCONNECT_PCM,
    READY_PCM,
)
from dodaios.audio.device_init import wait_for_stable_audio_devices
from dodaios.audio.effects import bind_shared_audio_player
from dodaios.audio.player import AudioPlayer
from dodaios.brain.output_filter import scrub_for_voice
from dodaios.brain.scrub_verdict import is_harmless_scrub_residue
from dodaios.core.cancellation import cancel_and_reap
from dodaios.core.events import (
    DICTATION_REFUSAL_REASONS,
    ActionProposed,
    AnnouncementRequested,
    AudioOutFirst,
    DictationCompleted,
    DictationPromptModePauseToggleRequested,
    DictationRefused,
    DictationStarted,
    DictationTranscribing,
    DictationTranscript,
    JarvisAgentAnnouncement,
    JarvisAgentBackgroundCompleted,
    MessageSent,
    MicrophoneTrouble,
    PermissionResolved,
    SpeechSpoken,
    VoiceBootStatus,
    VoiceInputHeld,
    VoiceMuteChanged,
    VoiceMuteToggleRequested,
    VoiceSessionEnded,
    VoiceSessionStarted,
    VoiceSpeakerMuteChanged,
    WakeCandidateDetected,
    WakeWordDetected,
)
from dodaios.core.protocols import AudioChunk
from dodaios.core.turn_language import (
    DEFAULT_LOCALE,
    normalize_language_tag,
    resolve_output_language,
)
from dodaios.i18n import catalog as i18n_catalog
from dodaios.plugins.stt.fwhisper import FasterWhisperProvider
from dodaios.plugins.tts.gemini_flash_tts import GeminiFlashTTS
from dodaios.plugins.wake.openwakeword_provider import (
    OpenWakeWordProvider,
)
from dodaios.sessions.constants import (
    HANGUP_ERROR,
    HANGUP_HOTKEY,
    HANGUP_SHUTDOWN,
    SPOKEN_KIND_ANNOUNCEMENT,
    SPOKEN_KIND_COMPLETION,
    SPOKEN_KIND_PREAMBLE,
    SPOKEN_KIND_PROGRESS,
    SPOKEN_KIND_SUBAGENT,
    SPOKEN_KIND_UNAVAILABLE,
)
from dodaios.speech import start_refusal
from dodaios.speech.echo_guard import SelfEchoGuard
from dodaios.speech.hangup import (
    HangupConfirmation,
)
from dodaios.speech.persona import iter_all_start_ack
from dodaios.speech.rolling_whisper_wake import RollingWhisperWake
from dodaios.speech.stt_failure import (
    classify_stt_failure,
    normalize_stt_failure,
    stt_failure_message,
)
from dodaios.speech.usage_meter import meter_stt, meter_tts
from dodaios.speech.usage_sink import SpeechSpendRecorder
from dodaios.speech.wake_verifier import (
    CUSTOM_WAKE_MIN_RMS,
    pcm_tail_rms,
    verify_wake_with_stt,
)
from dodaios.telemetry.latency import LatencyPhase, LatencyTracker
from dodaios.trigger.hotkey import HotkeyTrigger
from dodaios.voice.instant_ack import (
    PROGRESS_AFTER_S,
    note_spoken,
)

if TYPE_CHECKING:
    from dodaios.core.bus import EventBus
    from dodaios.state.supervisor import Supervisor


log = logging.getLogger("dodaios.speech.pipeline")

# Supervisor state for "a realtime transport is opening but cannot carry the
# call yet". A subscription transport spends 15-45 s here, and the session is
# already accepted into LISTENING by then — so without its own state every
# surface claims the user is being heard while the provider has not accepted a
# single frame (ST-7). The orb surface already speaks this vocabulary
# (``dodaios/overlay/surface.py``); the supervisor enum and the orb bus bridge
# are what carry it there. ``Supervisor.set_state`` ignores a state it does not
# know, so this degrades to the previous behaviour with one warning rather than
# raising on an install whose enum predates it.
_REALTIME_CONNECTING_STATE = "CONNECTING"


async def _run_voice_critical_thread(fn: Callable[[], Any]) -> Any:
    """Run blocking voice startup work outside the shared default executor.

    Wake and local-STT implementations legitimately use ``asyncio.to_thread``
    for native inference. A slow or un-cancellable inference can occupy every
    default-pool worker, so queueing realtime session assembly there creates a
    false LISTENING state: the microphone is buffered, but the provider cannot
    begin accepting that audio until a worker becomes free. A fresh daemon
    thread keeps this voice-critical control path independent and cannot hold
    process shutdown open if a platform credential backend itself wedges.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def _resolve(setter: Callable[[Any], None], value: Any) -> None:
        if not future.done():
            setter(value)

    def _runner() -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - relay to async caller
            callback = future.set_exception
            value: Any = exc
        else:
            callback = future.set_result
            value = result
        try:
            loop.call_soon_threadsafe(_resolve, callback, value)
        except RuntimeError:
            # The owning loop may close while an un-cancellable native call is
            # still unwinding. The daemon thread can then finish silently.
            pass

    threading.Thread(
        target=_runner,
        name="jarvis-voice-critical",
        daemon=True,
    ).start()
    return await future


async def _gather_timed(
    named_thunks: list[tuple[str, Callable[[], Awaitable[Any]]]],
) -> tuple[dict[str, float], list[Any]]:
    """Run named async thunks concurrently and time each one individually.

    Returns ``(timings_ms, results)`` where ``timings_ms[name]`` is the
    per-thunk wall-clock in milliseconds (recorded even if the thunk raises) and
    ``results`` mirrors ``asyncio.gather(..., return_exceptions=True)`` order:
    each entry is the thunk's return value or its captured exception. Used to
    expose which Phase-A loader dominates warm-up (the gather otherwise hides
    per-loader cost behind its slowest member).
    """
    timings: dict[str, float] = {}

    async def _run(name: str, thunk: Callable[[], Awaitable[Any]]) -> Any:
        t0 = time.monotonic()
        try:
            return await thunk()
        finally:
            timings[name] = (time.monotonic() - t0) * 1000.0

    results = await asyncio.gather(
        *(_run(name, thunk) for name, thunk in named_thunks),
        return_exceptions=True,
    )
    return timings, list(results)


BrainCallback = Callable[[str], Awaitable[str]]


# AnnouncementRequested.kind values that deliver an answer the user is owed — a
# finished background mission / sub-agent / worker / Jarvis-Agent result. These
# punch through the hangup gate (AD-OE5/OE6 zero-silent-drop) and cancel any
# pending "still on it" heartbeat. ``subagent`` is the attributed sibling of
# ``completion``: same delivery semantics, but rendered as its own transcript
# track ("Jarvis Sub-Agent / Output").
_READBACK_KINDS: frozenset[str] = frozenset(
    {SPOKEN_KIND_COMPLETION, SPOKEN_KIND_SUBAGENT}
)


#: Readback sources that never speak outside a call (see ``_is_agent_reply``).
#: A mission the user just asked for is not here: its answer may still punch
#: through the hangup gate (AD-OE5/OE6). Explicit delegations wait for a call
#: and a conversational pause; their results never open a call themselves.
#: How often a live call may leave the same owed reply unvoiced (no answer
#: started) before it waits for the next call instead.
_LIVE_REPLY_MAX_ATTEMPTS = 3

_HELD_FOR_CALL_SOURCES: frozenset[str] = frozenset(
    {
        "society.lead",
        "agentic_ide.readback",
        "delegation.batch",
        "tasks.runner",
        "workflows.runner",
        "workflows.scheduler",
        "desktop_app.conductor",
    }
)


def _announcement_spoken_kind(kind: str | None) -> str:
    """Map an ``AnnouncementRequested.kind`` to a ``SpeechSpoken.spoken_kind``.

    AnnouncementRequested carries {``preamble``, ``completion``, ``subagent``,
    ``info``, ``progress``, ``None``}. The first four map 1:1 onto the
    spoken-track vocabulary; ``info`` and the legacy ``None`` default (skill-
    output callers) fall back to the generic ``announcement`` tag.
    """
    if kind in (
        SPOKEN_KIND_PREAMBLE,
        SPOKEN_KIND_COMPLETION,
        SPOKEN_KIND_SUBAGENT,
        SPOKEN_KIND_PROGRESS,
    ):
        return kind
    return SPOKEN_KIND_ANNOUNCEMENT


async def _echo_brain(text: str) -> str:
    return text


# Honest cross-family fallback when a requested duplex provider cannot open a
# session. The classic pipeline remains available for this voice call so a
# missing key, exhausted balance, unsupported model, or network outage never
# turns the Realtime switch into a silent dead end (AP-22/AP-23).
_REALTIME_UNAVAILABLE_PHRASE: dict[str, str] = i18n_catalog.table("speech.realtime_unavailable")

_PHRASE_LANGS: frozenset[str] = frozenset({"de", "en", "es", "pt"})


def _phrase_lang(lang: str | None) -> str:
    """Normalize a detected-language tag to a canned-phrase key ("de"/"en"/"es"/"pt").

    The utterance language reaches the phrase pickers in two shapes: full
    language NAMES from the STT transcript (``(transcript.language or
    "en").lower()`` → ``"german"``/``"spanish"`` for Groq Whisper) and
    BCP-47-ish CODES ("de", "de-DE", "es-ES") from config pins / announcements.
    Both collapse through the canonical ``normalize_language_tag`` so every
    supported language (de/en/es/pt) selects its own phrase set; anything
    unrecognised falls back to ``DEFAULT_LOCALE``. The pickers used to test
    ``lang.startswith("de")`` only — ``"german"`` does not start with "de", so
    every canned AD-OE6 fallback (clarify question, action-done ack,
    brain-timeout, brain/STT-unavailable, smalltalk fallback) was spoken in
    ENGLISH to a German speaker, and the German variants were dead code (live
    bug 2026-06-09: "antwortet fast immer mit einer englischen
    Standardphrase"); a Spanish speaker hit the same trap until this normalizer
    learned ``es`` (Runtime Output Language doctrine). The canned tables now
    carry every supported language (de/en/es/pt).
    """
    code = normalize_language_tag(lang)
    return code if code in _PHRASE_LANGS else DEFAULT_LOCALE


# Hard ceiling on a single TTS playback. PortAudio's blocking ``stream.write``
# waits for output-buffer room, and a flaky output device can make it (or a
# stalled TTS chunk generator) block forever — observed live as a 10 s
# OutputStream stall plus ``Invalid sample rate -9997`` retries. Without a
# bound, ``_speak`` never returns, which wedges ``_handle_utterance`` ->
# ``_active_session`` so the ``_state_loop`` finally that resets
# ``self._state`` to IDLE never runs and the wake loop stops re-arming
# ("Hey Jarvis" goes permanently deaf until restart). AD-OE6 — recover, never
# silently hang.
#
# 2026-06-08 (Wave-1 latency fix): the old ceiling was 120 s — the live root
# cause of the 60-156 s voice-hangs on "open app" turns (a wedged output device
# left ``stream.write`` blocked and this ceiling was the ONLY escape).
#
# 2026-06-08 (watchdog redesign): the ceiling now bounds ONLY the no-first-frame
# window — a TTS provider that never yields any audio. It no longer caps total
# playback, so a legitimately long spoken answer is never truncated mid-speech;
# an ACTIVE playback is governed solely by the mid-playback no-progress stall
# below. This pairs with ``AudioPlayer.play_chunks`` resetting ``last_write_ns``
# per playback, so the watchdog's "no first frame yet" (<=0) guard works on
# EVERY turn — not just the first — instead of reading a stale cross-turn
# timestamp and falsely aborting a fresh, still-synthesizing answer.
_TTS_PLAYBACK_CEILING_S: float = 20.0
# Mid-playback no-audio-frame gap that means the output device is wedged (a
# healthy ~60 ms sub-block write returns far inside this). Trips the watchdog →
# ``player.abort_active()`` → turn unwinds → session re-arms.
_TTS_PLAYBACK_STALL_S: float = 5.0
def _playback_progress_stalled(last_write_ns: int, stall_s: float) -> bool:
    """True when audio frames stopped reaching PortAudio for ``stall_s``.

    ``last_write_ns == 0`` (no frame produced yet) is deliberately NOT a stall:
    the first-token / producer window is owned by the brain stall guard, so a
    slow first token must not be misread here as a device wedge. Only a
    *mid-playback* gap trips this. Cross-platform — pure monotonic-clock math.
    """
    if last_write_ns <= 0:
        return False
    return (time.monotonic_ns() - last_write_ns) >= int(stall_s * 1e9)


def _stt_crossover_would_leave_the_machine() -> bool:
    """Whether an AUTOMATIC STT crossover would be this host's first upload.

    Delegates to ``dodaios.dictation.polish_client.stt_runs_on_device`` — the
    SAME predicate the dictation polish pass consults before it may send a
    transcript to a cloud model, which in turn asks the repo's existing
    ``stt_family_id`` rather than matching provider names (AP-21). One question
    with two answers is how two lanes end up disagreeing, and this pair
    disagreed in the worse direction: the polish pass refused to upload the
    TEXT while the crossover was still free to upload the AUDIO that text was
    derived from. A recording is strictly more sensitive than its transcript —
    it carries the voice itself and whatever else was audible in the room — so
    refusing the smaller of the two while permitting the larger is not a
    position that can be defended to a user.

    Fails CLOSED, exactly like the predicate it delegates to: a host whose
    recognizer cannot be determined keeps its audio. The two mistakes are not
    symmetric. Guessing "local" costs a crossover on a turn that had already
    failed and that the user hears fail. Guessing "cloud" uploads the recording
    of somebody who picked an on-device recognizer to prevent precisely that,
    and nothing on screen would ever tell them.
    """
    try:
        from dodaios.dictation.polish_client import stt_runs_on_device

        return stt_runs_on_device()
    except Exception as exc:  # noqa: BLE001 — an unanswerable question keeps the audio
        log.warning(
            "Could not determine whether the configured recognizer runs on this "
            "machine (%s); declining the automatic STT crossover so the audio "
            "stays here.",
            exc,
        )
        return True


_SESSION_START_BUFFER_MAX_BYTES = 16_000 * 2 * 30  # 30 s of mono PCM16
_REALTIME_POST_OUTPUT_ECHO_GUARD_S = 0.5
_REALTIME_OUTPUT_LATENCY_CAP_S = 5.0
# The post-output echo tail splits into two phases. Only its leading part is
# physically audible speaker audio (the device's reported output latency plus
# an acoustic-decay/capture-buffering margin); microphone frames captured there
# are genuine echo territory and stay detector-only. Frames captured in the
# REMAINDER of the tail are silent-room or user speech: they are buffered and
# forwarded to the provider when the tail expires instead of being dropped —
# dropping them was the "the first 1-2 s after Jarvis stops talking are deaf"
# defect (a user answering immediately lost the whole utterance onset unless
# it survived the strict local barge confirm).
_REALTIME_HW_ECHO_TAIL_MARGIN_S = 0.25
# Bound on buffered tail audio; the tail itself is capped at
# _REALTIME_POST_OUTPUT_ECHO_GUARD_S + _REALTIME_OUTPUT_LATENCY_CAP_S (~5.5 s
# of 16 kHz mono PCM16 ≈ 176 kB), so this never truncates in practice.
_REALTIME_TAIL_PENDING_MAX_BYTES = 256_000
# How long the microphone must stay quiet after a turn is committed before
# speaking into the silent THINKING wait counts as an interruption rather than
# the tail of the utterance that started it. The provider commits on ITS OWN
# VAD, mid-sentence when a filler pause fools it, so the first moments after a
# commit are exactly when the user is most likely to still be talking (the turn
# fragmentation the session's own _user_is_speaking hold answers). Long enough
# to clear that overlap, short enough that a deliberate interruption a beat
# after Jarvis goes quiet still lands.
_THINKING_BARGE_QUIET_S = 0.35


def _feed_live_mic_level(chunk: AudioChunk) -> None:
    """Publish one captured frame's RMS to the native overlay level channel."""
    if not mic_level.has_subscribers():
        return
    samples = pcm_bytes_to_np(chunk.pcm)
    if samples.size:
        mic_level.feed(float(np.sqrt(np.mean(np.square(samples)))))


class _ChunkSource(Protocol):
    """Anything one lane can drain audio frames from.

    Satisfied by both ``MicrophoneCapture`` (a lane that opened the device
    itself) and ``_SessionInputBuffer`` (a lane that took over a stream some
    other lane already had open). Having the two behind one shape is what lets
    the dictation lane accept either without a second native input stream.
    """

    def stream(self) -> AsyncIterator[AudioChunk]: ...


# How long a dictation waits for an ambiguous wake-microphone lease to end
# before it gives up. Only reachable if the handoff itself failed; the honest
# outcome is a refused dictation, never a second stream on the same device.
_DICTATION_WAKE_RELEASE_TIMEOUT_S = 3.0

# Longest gap between two "dictation key is down" reports that still counts as
# ONE hold. The polling hotkey backend re-reports a held chord every few tens of
# milliseconds, and the edge-driven backends (pynput / Quartz) report a press
# exactly once per real chord-down — so nothing legitimate lands anywhere near
# this window, while a press past it can only be a fresh press or a key-up that
# was never delivered. See ``SpeechPipeline._on_dictate_press``.
_DICTATE_HOLD_REPEAT_GRACE_S = 2.0

# Teardown of a voice session's child tasks (the microphone pump, the provider
# wait, the hangup waiter): how long each one is re-cancelled before the
# teardown abandons it and moves on (BUG-185). On Python 3.11 a cancel can be
# swallowed by ``asyncio.wait_for`` (CPython gh-86296); a bare ``await task``
# after ONE cancel then waits forever, which is exactly how the pipeline stood
# stuck in its teardown for an entire afternoon with the microphone deaf. The
# budget is short on purpose — the dictation handover gives a session
# ``_DICTATION_HANDOVER_TIMEOUT_S`` to release the device — and the heartbeat
# doubles as the timer that keeps a cancel from being lost on the Windows
# proactor loop (BUG-081).
_SESSION_TASK_REAP_BUDGET_S = 3.0
_SESSION_TASK_REAP_HEARTBEAT_S = 0.5

# A hangup request older than this with the session still active is not "one
# already pending" — it is a teardown that has not completed, and the next
# explicit stop gesture must say so instead of being ignored at debug level.
_HANGUP_LATCH_STALE_S = 10.0

# How long an explicit dictation key press waits for a live voice conversation
# to give the microphone back before it gives up and says so.
#
# The press WINS over the session (see ``_begin_dictation_handover``), but the
# wait has to be bounded: a teardown that wedges must not leave the shortcut
# permanently dead — the very failure mode this whole lane exists to remove. A
# hangup stops the player immediately and unwinds through the normal session
# teardown, which is itself bounded, so anything past this window is a wedge and
# an honest refusal beats an endless spinner.
_DICTATION_HANDOVER_TIMEOUT_S = 5.0

# Poll interval while waiting for that handover. There is no single event that
# means "the session released the input device" — the state machine reaches IDLE
# only after its capture context has exited — so the wait watches that state.
# Small enough to be imperceptible, large enough not to spin the loop.
_DICTATION_HANDOVER_POLL_S = 0.02

# Said when a voice gesture is refused and the permission layer has no sentence of
# its own (an unreadable permission, an injected gate that only says "no").
_MICROPHONE_REFUSED_SENTENCE = "Microphone access is not available for Dodaios right now."

# How long the wake loop parks on the microphone permission before it re-reads the
# gate on its own. The grant normally wakes it at once (PermissionResolved); this
# is the fallback for an edge that never arrived.
_WAKE_PERMISSION_PARK_S = 30.0

# How long the wake loop waits before it asks again for a microphone the audio
# system stopped answering for. The capture answers such a retry at once and
# starts no native call while the first one is outstanding, so this only sets
# how soon listening resumes after the audio system answered.
_WAKE_STUCK_RETRY_S = 2.0
# The same stuck microphone is written to the log this often, not on every retry.
_WAKE_STUCK_LOG_EVERY_S = 300.0


# Fallback recording ceiling for a MISSING or unparseable ``[dictation]
# max_seconds``. A configured 0.0 is not missing — it is the user asking for no
# ceiling at all — and is preserved rather than replaced by this.
_DICTATION_DEFAULT_MAX_S = 1800.0

# The hold-key watchdog (BUG-191). While a HOLD-started dictation records, the
# hotkey backend is asked whether the chord is still physically down. The
# press/release EDGES can be lost between the OS poller and this pipeline — a
# checker restart mid-hold, a handler that raised, a registry re-arm — and a
# lane that only ever hears edges then records until its 30-minute cap with
# nothing the user presses able to stop it. The keyboard itself cannot go
# stale: a chord that reads "up" for this long, with no release edge having
# arrived, IS the release, and the recording is finished the way a release
# would finish it. One second is far longer than any poll jitter and far
# shorter than a user notices; the poll is cheap (one ``GetAsyncKeyState``
# sweep). A backend that cannot see the keyboard answers ``None`` and the
# watchdog stands down — it never invents a release.
_DICTATE_HOLD_LOST_RELEASE_S = 1.0
_DICTATE_HOLD_WATCH_POLL_S = 0.25

# How long the wake word stays blocked when the recording itself is unbounded.
# The block exists so a wedged dictation task cannot leave the wake word deaf
# until the app is restarted (BUG-037), so it may never be unbounded even when
# the recording is. An hour is far past any real dictation while still being a
# deadline that arrives.
_DICTATION_UNBOUNDED_WAKE_BLOCK_S = 3600.0


def _capture_counter(source: object, name: str) -> int:
    """A cumulative capture counter, wherever the stream keeps it.

    A dictation that borrows the wake stream sees a handoff buffer whose
    ``capture`` attribute is the microphone; one that opened its own stream
    sees the microphone directly. Either way a missing counter reads as zero —
    an honest degrade on a source that cannot report it.
    """
    for holder in (source, getattr(source, "capture", None)):
        if holder is None:
            continue
        value = getattr(holder, name, None)
        if value is not None:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def resolve_dictation_language(*, pinned: str, reported: str, text: str) -> str:
    """Which language a finished dictation is treated as. Never raises.

    Module-level and public because TWO paths finish a dictation — the live
    delivery in ``_finish_dictation`` and the Restore route's re-transcription —
    and a second copy of this decision is how the same recording would end up
    cleaned under two different rule sets depending on which button produced it.

    Three signals, and the ORDER between them is the whole fix:

    1. **The user's pin wins, always.** It is the one signal a person can set,
       so overruling it would leave them no way to be right.
    2. **Otherwise the TEXT outranks a provider tag that CONTRADICTS it.** The
       cloud Whisper APIs report a language on every request and report it
       confidently when it is wrong: the live 2026-07-28 history has German
       dictations tagged "English". The old gate only consulted the text when
       the tag was UNPARSEABLE, and ``normalize_language_tag`` turns "English"
       into "en", never "unknown" — so a confidently wrong tag always won. What
       that costs is not cosmetic: the English filler list used to contain "er",
       a top-frequency German pronoun, so a German sentence tagged English came
       back with its pronouns deleted and the cleanup reported a clean success.
    3. **A tag we cannot place stays exactly as it is.** ``detect_text_language``
       only knows de/en/es, so letting it overrule a "French" or "ja" tag would
       relabel that dictation as whichever of the three it scored highest on and
       then run THAT language's filler rules over it. Keeping the tag makes the
       cleanup a documented no-op (``reason="no_rules"``), which is the honest
       answer for ~95 of the 100 recognition languages this feature supports.

    **The answer is a CODE whenever one exists.** A tag we can place comes back
    as ``de`` / ``en`` / ``es``, never as the provider's own spelling of it.
    This is not cosmetic. The cloud Whisper APIs answer with the language NAME
    ("German"), every consumer downstream keys off this string, and the polish
    pass's rare-token guard — the one that stops a formatter from replacing
    words the user actually said — looks its vocabulary up by two-letter code
    and silently disables itself on anything else. Returning the raw tag
    therefore armed that guard only when the provider had been WRONG (the
    detector then supplied a real code) and disarmed it on every dictation the
    provider got RIGHT, which is the overwhelming majority. Live evidence:
    "kannst du es bitte mein download video abspeichern" was delivered as
    "Kannst du es bitte herunterladen?" — three content words replaced, no
    guard fired.  # i18n-allow: verbatim German transcript under test
    A tag with no code stays verbatim, so the honest no-op in point 3 is
    unchanged.

    A provider that reports nothing at all is the one case where the text is the
    only signal there is: ``[dictation].language = auto`` (the shipped default)
    plus a silent provider used to leave the cleanup with "no rules for this
    language", so every hesitation sound the user made shipped straight into the
    text while the setting said the cleanup was on.

    Everything resolves through the canonical resolver's helpers — no layer
    invents its own detection.
    """
    pin = str(pinned or "").strip().lower()
    if pin not in ("", "auto"):
        return pin
    tag = str(reported or "")
    try:
        from dodaios.core.turn_language import resolve_transcript_language

        # Points 2 and 3 above live in the canonical resolver, which the voice
        # lane's transcript filter reads too — one decision, not two copies
        # that drift the first time either is touched.
        code = resolve_transcript_language(tag, text)
        if code != "unknown":
            if code != normalize_language_tag(tag):
                log.debug(
                    "dictation language resolved from the transcript: %s "
                    "(the provider reported %r)",
                    code,
                    tag,
                )
            # The tag stands as a CODE whenever it has one. Reaching that case
            # is the NORMAL one (the provider agreed with the text), which is
            # exactly why handing the provider's own spelling on from here
            # disarmed the guards on nearly every dictation.
            return code
    except Exception:  # noqa: BLE001 — a detection hiccup is not fatal
        log.debug("dictation language detection failed", exc_info=True)
    return tag


# The longest the Parakeet model stays loaded without a dictation.
_DICTATION_PARAKEET_REST_S = 180.0

# Serializes the resolution of the dictation's recognizers across the event
# loop and the worker thread a dictation resolves in.
_DICTATION_RESOLUTION_LOCK = threading.Lock()

# How much audio the CAPTURE may lose before the dictation says so. Frames the
# queue dropped are not a transcription failure — they never became audio at
# all, so no retry, no re-read and no Restore can bring them back; the only
# honest thing left is to tell the user their recording has a hole in it.
#
# The floor is a WORD. At the measured 2.5 tokens per second of speech one word
# is ~400 ms, so anything under half a second cannot have taken a whole one and
# saying "words are missing" would be the wrong kind of true. Across the same
# 797 live dictations this marks 10.8 % of them — every one a real loss, and
# every one previously delivered as if it were complete.
_DICTATION_DROPPED_AUDIO_NOTICE_S = 0.5


# Queue depth for a dictation that opens its own microphone. The capture queue
# drops the OLDEST chunk when it overflows — correct for wake/VAD, where stale
# audio is worse than missing audio, and exactly wrong here: for a dictation
# every frame is the user's words. ~10 s of slack absorbs a provider stall
# without deleting speech. Express it as time so capture-block tuning never
# silently shrinks the safety margin.
_DICTATION_CAPTURE_QUEUE_CHUNKS = capture_chunks_for_duration(10.0)


# Dictation notifications update UI state; they must not inherit the bus's
# five-second observer timeout before a finished transcript can be delivered.
_DICTATION_EVENT_TIMEOUT_S = 1.0


class _SessionInputBuffer:
    """Replayable bounded handoff for one continuously captured mic stream.

    Capture begins before ``VoiceSessionStarted`` is published, so the Jarvis
    Bar never advertises LISTENING ahead of the microphone. Frames arriving
    while start subscribers, realtime session assembly, or a provider handshake
    run are retained in order. Each new consumer starts
    at sequence zero, allowing classic STT to replay the opening if a realtime
    provider fails before accepting it. The byte cap is time-format based; if a
    consumer ever falls behind it, the stream fails explicitly instead of
    silently dropping the beginning of the user's command.
    """

    def __init__(
        self,
        *,
        initial: tuple[AudioChunk, ...] = (),
        max_buffer_bytes: int = _SESSION_START_BUFFER_MAX_BYTES,
        capture: MicrophoneCapture | None = None,
    ) -> None:
        #: The still-open stream behind this handoff, when the frames come from
        #: a live microphone rather than a test's hand-fed list. Carried purely
        #: so a consumer that takes the stream over can re-bound its queue for
        #: the kind of consumer IT is — a dictation records every frame, while
        #: the wake detector this stream was opened for wants shallow and fresh
        #: (``MicrophoneCapture.set_queue_depth``). ``None`` means there is
        #: nothing to re-bound, which every caller treats as fine.
        self.capture = capture
        self._chunks: deque[tuple[int, AudioChunk]] = deque()
        self._max_buffer_bytes = max(1, int(max_buffer_bytes))
        self._retained_bytes = 0
        # Latest timestamp among evicted frames. None means at least one frame
        # had no trustworthy capture timestamp, so skipping a gap is unsafe.
        self._evicted_through_ns: int | None = 0
        self._next_seq = 0
        self._updated = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None
        self._source_done = False
        self._closed = False
        self._active_consumers = 0
        self.released = asyncio.Event()
        for chunk in initial:
            self._append(chunk, publish_level=False)

    def start(self, source: AsyncIterator[AudioChunk]) -> None:
        if self._pump_task is not None:
            return
        self._pump_task = asyncio.create_task(
            self._pump(source), name="voice-session-mic-buffer"
        )

    def put(self, chunk: AudioChunk) -> None:
        if not self._closed:
            # While no voice engine consumes the stream, this buffer is the
            # only place that can animate the visible startup bar. An active
            # classic/realtime consumer owns level feeding; switching back here
            # between consumers keeps fallback teardown from flattening the bar.
            self._append(chunk, publish_level=self._active_consumers == 0)

    def _append(self, chunk: AudioChunk, *, publish_level: bool) -> None:
        chunk_bytes = len(chunk.pcm)
        while (
            self._chunks
            and self._retained_bytes + chunk_bytes > self._max_buffer_bytes
        ):
            _seq, dropped = self._chunks.popleft()
            self._retained_bytes = max(0, self._retained_bytes - len(dropped.pcm))
            timestamp = int(dropped.timestamp_ns or 0)
            if timestamp <= 0 or self._evicted_through_ns is None:
                self._evicted_through_ns = None
            else:
                self._evicted_through_ns = max(self._evicted_through_ns, timestamp)
        self._chunks.append((self._next_seq, chunk))
        self._retained_bytes += chunk_bytes
        self._next_seq += 1
        if publish_level:
            _feed_live_mic_level(chunk)
        self._updated.set()

    async def _pump(self, source: AsyncIterator[AudioChunk]) -> None:
        try:
            async for chunk in source:
                self.put(chunk)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - replay on the consumer
            self.finish(error=exc)
        finally:
            self.finish()

    def finish(self, *, error: BaseException | None = None) -> None:
        """Mark a manually fed source as terminal and wake its consumers."""
        if error is not None and self._error is None:
            self._error = error
        self._source_done = True
        self._updated.set()

    async def stream(
        self, *, discard_before_ns: Callable[[], int] | None = None
    ) -> AsyncIterator[AudioChunk]:
        self._active_consumers += 1
        cursor = 0
        try:
            while True:
                if self._chunks:
                    earliest = self._chunks[0][0]
                    if cursor < earliest:
                        discard_before = discard_before_ns() if discard_before_ns else 0
                        can_skip_suppressed = (
                            cursor > 0
                            and self._evicted_through_ns is not None
                            and 0 < self._evicted_through_ns < discard_before
                        )
                        if not can_skip_suppressed:
                            raise RuntimeError(
                                "Voice input exceeded the 30-second replay window; "
                                "refusing to drop the command prefix."
                            )
                        # An inline reply pauses VAD while capture keeps running.
                        # Its post-TTS echo guard already rejects these frames;
                        # apply that SAME cutoff before enforcing replay bounds.
                        # New user audio and first-consumer startup are protected.
                        log.debug(
                            "Skipped %d expired voice-input frames after assistant playback.",
                            earliest - cursor,
                        )
                        cursor = earliest
                    offset = cursor - earliest
                    if 0 <= offset < len(self._chunks):
                        _seq, chunk = self._chunks[offset]
                        cursor += 1
                        yield chunk
                        continue
                if self._closed or self._source_done:
                    if self._error is not None:
                        raise self._error
                    return
                self._updated.clear()
                if self._chunks and cursor < self._next_seq:
                    continue
                await self._updated.wait()
        finally:
            self._active_consumers = max(0, self._active_consumers - 1)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._updated.set()
        self.released.set()
        task = self._pump_task
        self._pump_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@asynccontextmanager
async def _wake_capture_with_release(
    capture: MicrophoneCapture,
    released: asyncio.Event,
) -> AsyncIterator[MicrophoneCapture]:
    """Signal only after the wake microphone has fully closed."""
    released.clear()
    try:
        async with capture as mic:
            yield mic
    finally:
        released.set()


class PipelineState(enum.Enum):
    IDLE = "idle"
    ACTIVE = "active"


class TurnTakingState(enum.Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    USER_SPEAKING = "USER_SPEAKING"
    WAITING_FOR_FINAL_TRANSCRIPT = "WAITING_FOR_FINAL_TRANSCRIPT"
    PROCESSING = "PROCESSING"
    # Final transcript classified as syntactically open-ended (incomplete-prompt
    # completion buffer pending). Pipeline stays silent, mic open, until a
    # continuation arrives or the per-gap timeout flushes the fragment to the
    # brain (AD-OE6 — zero silent drops). See
    # docs/superpowers/specs/2026-05-25-incomplete-prompt-completion-design.md.
    WAITING_FOR_COMPLETION = "WAITING_FOR_COMPLETION"
    JARVIS_SPEAKING = "JARVIS_SPEAKING"


# Turn-states in which the user holds the floor: the mic is open and they are
# speaking or their words are still being finalised. While in any of these, an
# asynchronous non-interrupt announcement (ack preamble, mission/background
# readback, workflow completion) must NOT barge — AD-OE5 "speak ONLY at the next
# turn-boundary". A preamble is then dropped (ephemeral); a completion is
# deferred and flushed when the floor clears (AD-OE6 zero-silent-drop).
_USER_HOLDS_FLOOR_STATES: frozenset[TurnTakingState] = frozenset({
    TurnTakingState.USER_SPEAKING,
    TurnTakingState.WAITING_FOR_FINAL_TRANSCRIPT,
    TurnTakingState.WAITING_FOR_COMPLETION,
})

# Hang-up patterns + the END_CALL sentinel live in dodaios/speech/hangup.py
# (shared, stdlib-only, also imported by dodaios/telephony/session.py). HANGUP_RE,
# contains_end_signal and is_legacy_farewell are imported at the top of this module.

# STT hallucination markers (YouTube end cards, ad outros, copyright strings
# Whisper emits on an empty mic / speaker leak). Blocked before the brain
# call. Single definition lives in wake_constants (the rolling wake's
# bias-echo confirm consumes the same list — BUG-008 drift rule).
# The short-recording + whole-utterance verdict itself lives beside the pattern
# in that same leaf module, because the realtime input recognizer needs exactly
# this judgement too and a second copy would drift (BUG-008).
from dodaios.core.wake_constants import (  # noqa: E402
    STT_HALLUCINATION_RE as _STT_HALLUCINATION_RE,
)
from dodaios.core.wake_constants import (  # noqa: E402
    is_silence_hallucination as _is_silence_hallucination,
)

# Kurzes ACK das beim Wake gesprochen wird. Leer = nur der Chime spielt,
# keine gesprochene Phrase — User-Praeferenz 2026-04-24: die JARVIS-
# Persona-Phrasen ("Sir?", "Sofort.", "Mach ich.") klingen peinlich, raus.
ACK_PHRASE = ""


def _wake_catchup_budget(detector: Any) -> tuple[int, int]:
    """Resolve a wake detector's fanout budgets: (coalesce chunks, queue depth).

    Both are TIME budgets the detector declares in seconds and this turns into
    capture blocks — ``capture_chunks_for_duration`` is the one place that
    knows the block size, so a block-size change can never silently shrink a
    "1 s batch" to 320 ms again (that is exactly what happened when the block
    went from 100 ms to 32 ms under a chunk-count attribute).

    * ``coalesce_catchup_s`` > 0: the detector can consume variable buffer
      sizes, so a backlog may be drained as ONE batch covering that much
      audio (see ``_queue_iter``). Absent/0 → no coalescing (1).
    * ``intake_backlog_s``: how far behind live audio the detector may fall
      before the fanout drops its oldest frame. Honoured ONLY for a detector
      that coalesces — one that cannot catch up must stay near-present on the
      generic ``REALTIME_QUEUE_CHUNKS`` budget, or a deeper queue would only
      mean a later wake. Floored at the generic budget.
    """
    coalesce = 1
    try:
        coalesce_s = float(getattr(detector, "coalesce_catchup_s", 0.0) or 0.0)
    except (TypeError, ValueError):
        coalesce_s = 0.0
    if coalesce_s > 0.0:
        coalesce = max(2, capture_chunks_for_duration(coalesce_s))
    depth = REALTIME_QUEUE_CHUNKS
    if coalesce > 1:
        try:
            backlog_s = float(getattr(detector, "intake_backlog_s", 0.0) or 0.0)
        except (TypeError, ValueError):
            backlog_s = 0.0
        if backlog_s > 0.0:
            depth = max(REALTIME_QUEUE_CHUNKS, capture_chunks_for_duration(backlog_s))
    return coalesce, depth


async def _queue_iter(
    q: asyncio.Queue, *, coalesce_max_chunks: int = 1
) -> AsyncIterator[AudioChunk]:
    """Adapt a queue into an async iterator for wake detectors.

    ``coalesce_max_chunks`` > 1 turns a BACKLOG into catch-up batches: after
    the blocking get, every chunk already waiting in the queue (up to the cap)
    is drained non-blocking and concatenated into ONE AudioChunk. A detector
    that falls behind live audio on a busy desktop CPU (live forensic
    2026-07-21: oww_q pinned at 50 → the wake word was heard FIVE SECONDS
    late) then pays its per-chunk loop/decode overhead once per batch instead
    of once per 100 ms block and catches back up to the present instead of
    grinding through stale audio at the same rate it arrives. When the
    consumer is keeping up the queue is empty and every chunk passes through
    untouched, so the caught-up hot path is byte-identical to before. Only a
    detector that declares the capability (``coalesce_catchup_s``, resolved by
    ``_wake_catchup_budget``) gets batches — a provider with fixed frame-size
    expectations keeps the per-chunk contract.
    """
    while True:
        chunk = await q.get()
        if chunk is None:  # Sentinel
            return
        if coalesce_max_chunks > 1 and not q.empty():
            parts = [chunk.pcm]
            ended = False
            while len(parts) < coalesce_max_chunks:
                try:
                    nxt = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if nxt is None:  # Sentinel mid-drain: flush, then end
                    ended = True
                    break
                parts.append(nxt.pcm)
            if len(parts) > 1:
                chunk = AudioChunk(
                    pcm=b"".join(parts),
                    sample_rate=chunk.sample_rate,
                    timestamp_ns=chunk.timestamp_ns,
                    channels=chunk.channels,
                )
            if ended:
                yield chunk
                return
        yield chunk


def _default_tts_for_pipeline(config: Any) -> Any:
    """The default TTS when the caller supplies none — key-aware (AP-22).

    Mirrors the STT default a few lines into ``__init__``: build through the same
    key-aware ``build_tts_from_config`` the real construction paths use, so a
    single-key user's spoken output — INCLUDING the deterministic "couldn't
    understand you" readback — crosses to whatever TTS family the user actually
    has a key for instead of being hard-pinned to a keyless Gemini default that
    goes silently mute (AP-22/AP-6). Degrades to a bare ``GeminiFlashTTS`` only
    when there is no config or the factory itself fails, so voice boot is never
    broken. (In practice every real caller passes a TTS built this way already;
    this closes the latent ``tts=None`` fallback that ignored the user's key.)
    """
    if config is not None and getattr(config, "tts", None) is not None:
        try:
            from dodaios.plugins.tts import build_tts_from_config

            return build_tts_from_config(config.tts)
        except Exception as exc:  # noqa: BLE001 — a TTS build must never break voice boot
            log.warning("TTS factory failed (%s); using the default Gemini voice.", exc)
    return GeminiFlashTTS()


def _owns_ambient_duties() -> bool:
    """May this process arm the wake word and the global hotkeys?

    Only the default instance of the app does (``dodaios.core.instance``); a
    second instance started beside it for development must not compete for the
    microphone or the key combos. Lazy import keeps the pipeline's import cost
    unchanged; the lookup is a dict read.
    """
    from dodaios.core.instance import current_instance

    return current_instance().owns_ambient_duties


# The method bodies live in the mixins below. They read this module's names through
# `_pl` at call time, so every module-level name here has to exist before they load.
from dodaios.speech.pipeline_parts.announcements import AnnouncementsMixin  # noqa: E402
from dodaios.speech.pipeline_parts.boot import BootWarmupMixin  # noqa: E402
from dodaios.speech.pipeline_parts.call_lifecycle import CallLifecycleMixin  # noqa: E402
from dodaios.speech.pipeline_parts.dictation_control import DictationControlMixin  # noqa: E402
from dodaios.speech.pipeline_parts.dictation_session import DictationSessionMixin  # noqa: E402
from dodaios.speech.pipeline_parts.events_replies import EventsAndRepliesMixin  # noqa: E402
from dodaios.speech.pipeline_parts.hotkey_dispatch import HotkeyDispatchMixin  # noqa: E402
from dodaios.speech.pipeline_parts.instant_ack import InstantAckMixin  # noqa: E402
from dodaios.speech.pipeline_parts.session_loop import SessionLoopMixin  # noqa: E402
from dodaios.speech.pipeline_parts.speak_playback import SpeakPlaybackMixin  # noqa: E402
from dodaios.speech.pipeline_parts.vad_activation import VadActivationMixin  # noqa: E402
from dodaios.speech.pipeline_parts.wake import WakeMixin  # noqa: E402


class SpeechPipeline(
    VadActivationMixin,
    EventsAndRepliesMixin,
    AnnouncementsMixin,
    InstantAckMixin,
    BootWarmupMixin,
    HotkeyDispatchMixin,
    CallLifecycleMixin,
    WakeMixin,
    SessionLoopMixin,
    DictationControlMixin,
    DictationSessionMixin,
    SpeakPlaybackMixin,
):
    """End-to-End Pipeline mit Call/Hangup-Lifecycle + Parallel-Wake."""

    def __init__(
        self,
        call_hotkeys: tuple[str, ...] = ("ctrl+right_alt+j", "f3+f4"),
        hangup_hotkeys: tuple[str, ...] = ("f1+f2",),
        # Legacy keyword seed for the no-plan provider. Empty: no wake model
        # ships (design 2026-07-07); only a wake plan arms a real detector.
        wake_keywords: tuple[str, ...] = (),
        wake_threshold: float = 0.10,
        stt: FasterWhisperProvider | None = None,
        tts: GeminiFlashTTS | None = None,
        wake: OpenWakeWordProvider | None = None,
        brain_callback: BrainCallback | None = None,
        # No-PROGRESS (stall) window for a streaming brain turn — NOT a total
        # wall-clock cap. The deadline resets every time the turn makes progress
        # (a streamed text chunk OR a tool-use-loop boundary, see
        # ``_run_brain_with_stall_guard`` + ``_mark_brain_progress``). It fires
        # the spoken fallback only when the provider is genuinely STALLED — no
        # progress at all for this long — which is the original liveness guard
        # ("Jarvis stopped thinking and never replied"). Live bug 2026-06-01:
        # this used to be a TOTAL cap (25 s), so a vision question that ran a
        # Gemini tool-use loop (image upload + context cache + function_call +
        # tool execution) legitimately exceeded it and was guillotined mid-work —
        # Jarvis looked lazy while it was still working. Idle-hangup is no longer
        # a coupling concern (the old "MUST be < idle_timeout" rule): the brain
        # turn is awaited INLINE in ``_active_session`` (pipeline.py ~2748), so
        # the idle timer never ticks during PROCESSING — which frees us to widen
        # this from 25 s to 30 s (2x the observed worst-case no-progress gap of
        # ~15 s, still below the provider's own ~40 s stream timeout so the
        # provider's error path wins on a true hang). KNOWN LIMITATION: the
        # window also covers a single model round's *pre-first-output* think time
        # (image processing before the first delta). If that ever exceeds this
        # value the fallback still fires — there is no progress signal during the
        # in-flight HTTP request. Raise this (not the ceiling) for a
        # consistently-slow vision profile.
        brain_timeout_s: float = 30.0,
        input_device: int | str | None = None,
        output_device: int | str | None = None,
        idle_timeout_s: float = 30.0,
        post_tts_listen_suppression_s: float = 0.8,
        # User-Mandat 2026-05-18: Jarvis darf NUR nach explizitem "Hey Jarvis"
        # einen Turn starten. Wenn False (Default), endet die Session direkt
        # nach der TTS-Antwort mit hangup_reason=turn_complete und der Wake-
        # Listener ist wieder die einzige Eintrittstuer — kein Open-Mic-
        # Folgeturn, der auf Hintergrundgespraeche / TV / Mit-Bewohner
        # triggert. Wenn True, bleibt die Session nach der Antwort offen und
        # weitere Turns laufen ohne neues Wake bis HANGUP_RE / idle_timeout_s
        # / Hotkey die Session beendet (Legacy-Konversationsmodus 2026-05-05
        # bis 2026-05-18). Production-Wiring liest cfg.trigger.single_turn_mode
        # und uebersetzt es in ``not single_turn_mode`` an dieser Stelle.
        continue_listening_after_response: bool = False,
        enable_openwakeword: bool = True,
        enable_whisper_wake: bool = True,
        # When True (default), an OpenWakeWord hit is a *candidate* only: the
        # wake loop transcribes the few seconds before the hit with the
        # configured utterance STT (e.g. Groq) and requires a strict
        # "hey/hi/hallo + jarv" pattern before activating. Eliminates the
        # bare-"Jarvis" false fires from the neural model without pendulumming
        # the OWW threshold (BUG-009 floor stays intact). Production wiring
        # reads ``cfg.trigger.require_hey_prefix``.
        require_hey_prefix: bool = True,
        # When False, NO local FasterWhisperProvider is built (cloud-first
        # lightweight wake: openWakeWord only, no GPU, no ~1 GB model). The
        # RollingWhisperWake backstop and the faster-whisper VAD probe are
        # then disabled. An explicitly passed ``stt`` always wins regardless
        # of this flag. Default True preserves the legacy heavy-path behaviour.
        enable_local_whisper: bool = True,
        ack_phrase: str = ACK_PHRASE,
        bus: EventBus | None = None,
        supervisor: Supervisor | None = None,
        config: Any = None,
        vision_provider: Any = None,
        realtime_audio_renderer: Callable[[], str | None] | None = None,
        activation_gate: Callable[[], bool] | None = None,
        # Silent predicate for a USER gesture (push-to-talk, a voice session,
        # dictation): true unless the microphone is refused. ``activation_gate``
        # stays the BACKGROUND one (wake word, barge-in: a live grant only).
        # Neither asks the OS; the gesture entry points do, through
        # ``permission_gate`` (the permission service by default).
        user_activation_gate: Callable[[], bool] | None = None,
        permission_gate: Any = None,
        # Pre-Thinking-Ack Flash-Brain (spec: 2026-05-11-pre-thinking-ack-
        # flash-brain-design.md). When provided, every user utterance kicks
        # off a parallel acknowledgment LLM call BEFORE the main brain
        # starts thinking. Output is published as
        # AnnouncementRequested(kind="preamble") so the existing
        # _on_announcement handler runs it through TTS. None disables the
        # feature without changing any code paths.
        ack_brain: Any = None,
        # Resolved custom-wake-word plan (dodaios.speech.wake_phrase.WakeWordPlan).
        # When None (every legacy call site + all existing tests) the wake path
        # is byte-identical to the historical "Hey Jarvis" behaviour. When set,
        # it overrides the OWW model + threshold, the prefix-verifier matcher,
        # and the rolling-whisper pattern from the plan.
        wake_plan: Any = None,
        # Dictation mode: hold (or toggle) to speak, the transcript is inserted
        # into whatever text field has focus. Empty (the default) means no
        # shortcut is armed — dictation is then started from the bar, the UI or
        # the CLI. Deliberately its OWN binding rather than a revival of the
        # deprecated ptt slot: dictation never reaches the brain.
        dictate_hotkeys: tuple[str, ...] = (),
        dictate_mode: str = "hold",
        # Hands-free dictation: press once to start, press again to stop. Its
        # OWN binding, independent of ``dictate_mode`` — a user may have a hold
        # key and a toggle key armed at the same time, and the legacy
        # ``[dictation].mode = "toggle"`` still only governs ``dictate_hotkeys``.
        dictate_toggle_hotkeys: tuple[str, ...] = (),
        # "Insert the last dictation again" — its own binding, because it needs
        # neither a microphone nor a speech-to-text provider and therefore stays
        # useful on a host where dictation itself cannot run. It was editable in
        # the Voice → Shortcuts tab for a while WITHOUT arriving here: the save
        # persisted, the UI showed the new combo, and the key did nothing —
        # forever, restart included (the AP-4 trap: one layer never told).
        paste_last_hotkeys: tuple[str, ...] = (),
        # Resolved DictationConfig (dodaios.core.config.DictationConfig) or None.
        # None keeps every legacy call site and test on the built-in defaults.
        dictation_config: Any = None,
    ) -> None:
        self._call_hotkeys = call_hotkeys
        self._hangup_hotkeys = hangup_hotkeys
        self._dictate_hotkeys = list(dictate_hotkeys)
        self._dictate_toggle_hotkeys = list(dictate_toggle_hotkeys)
        self._paste_last_hotkeys = list(paste_last_hotkeys)
        # Speaker mute = TTS volume 0. The muted-ness last broadcast as
        # ``VoiceSpeakerMuteChanged``; ``set_tts_volume`` runs on the REST
        # threadpool AND the overlay's Tk thread, so the compare-and-set that
        # decides "did it flip?" holds this lock. ``None`` = nothing broadcast
        # yet, so the first change is compared against the configured volume.
        self._speaker_mute_lock = threading.RLock()
        self._speaker_muted = False
        self._speaker_output_revision = 0
        self._speaker_muted_last: bool | None = None
        # One paste at a time — two overlapping ones race over the clipboard
        # restore and the loser puts the wrong content back (see _on_paste_last).
        self._paste_last_busy = False
        self._dictate_mode = "toggle" if str(dictate_mode).lower() == "toggle" else "hold"
        self._dictation_cfg = dictation_config
        # A DELIBERATE user activation edge (the CALL hotkey, the
        # "Speak in this conversation" button) is pending in ``_call_event``.
        # The state loop consumes this to exempt exactly that call from the
        # post-hangup wake lock: the lock exists so Jarvis' own speaker tail
        # cannot re-trigger the WAKE WORD (audio echo), and a key press has no
        # echo path. Dropping explicit presses under the lock made recording
        # start only after the lock expired — the user was already talking and
        # the opening 1-3 s of every quick follow-up were missing (live
        # 2026-07-31).
        self._explicit_call_pending = False
        # Chat mic-dictation: transcribe-only into the chat input box, never to
        # the brain. A SEPARATE lane from the voice path — its own stop event +
        # task so it can never touch ``_handle_utterance`` / the wake loop.
        self._dictation_stop_event = asyncio.Event()
        self._dictation_task: asyncio.Task[None] | None = None
        # The short-lived task that ends a live voice conversation so this
        # dictation can have the microphone. Alive only between the key press
        # and the moment ``_dictation_task`` exists (or the handover is refused),
        # and never both at once. See ``_begin_dictation_handover``.
        self._dictation_handover_task: asyncio.Task[None] | None = None
        # A dictation started beside a live call, and whether that call's input
        # is held for it. See ``_live_call_owns_microphone``.
        self._dictation_beside_call = False
        self._voice_input_held = False
        # 0.0 is a real value here — "no ceiling" — so it must NOT be coerced
        # to a default the way an absent or malformed setting is. The old
        # ``or 300.0`` did exactly that and made the off switch unreachable
        # (AP-31: a switch whose value is ignored). Only a missing or
        # unparseable setting falls back.
        raw_max_s = getattr(
            self._dictation_cfg, "max_seconds", _DICTATION_DEFAULT_MAX_S
        )
        try:
            configured_max_s = float(raw_max_s)
        except (TypeError, ValueError):
            # A hand-edited jarvis.toml must never fail to boot (AP-16), but it
            # must also not fail QUIETLY: the user typed something here and is
            # about to get a ceiling they did not ask for.
            log.warning(
                "[dictation].max_seconds is not a number (%r); using %.0fs. "
                "Set 0 for no recording ceiling.",
                raw_max_s,
                _DICTATION_DEFAULT_MAX_S,
            )
            configured_max_s = _DICTATION_DEFAULT_MAX_S
        self._dictation_max_s = max(0.0, configured_max_s)
        # Strong references to fire-and-forget bus publishes (see
        # ``_publish_event_soon``); entries remove themselves when they finish.
        self._detached_publishes: set[asyncio.Task[None]] = set()
        # Deadline that BOUNDS the wake-word block a dictation imposes. 0.0 is
        # "no block", so an instance that never dictates can never go deaf.
        self._dictation_wake_block_until = 0.0
        # Whether the current dictation already published its terminal
        # ``DictationCompleted``. Starts True ("nothing owed") so no teardown
        # can fire a completion for a dictation that never ran.
        self._dictation_completion_published = True
        # Where the finished transcript goes for the CURRENT dictation run:
        # "chat" only publishes the transcript event (the chat composer's mic
        # button), "insert" additionally pastes it into the focused field of
        # whatever app is in front. Set per start_dictation call, never global.
        self._dictation_target = "chat"
        # The dictation's recognizers, resolved on the first press and never
        # at boot (AP-26): ``(signature, resolution)``, or ``None`` when a
        # provider, language or settings change asked for a fresh resolution
        # (see ``_dictation_resolution``).
        self._dictation_resolution_cache: Any = None
        # The on-device engines a dictation can read with. Each is built on
        # first use and kept, because one owns a worker process and the other
        # a loaded model.
        self._dictation_whisper_worker: Any = None
        self._dictation_parakeet_instance: Any = None
        self._dictation_parakeet_rest: Any = None
        # True while a hold-mode dictation key is physically down, as far as
        # the press/release EDGES have told us. (The Windows poller fires
        # on_press ONCE per chord-down
        # — ``HotkeyChecker.run`` gates it on ``key_state != 1`` — so this is an
        # edge latch, not a heartbeat; the physical truth is asked separately
        # through ``HotkeyTrigger.chord_is_down`` while a hold records.)
        self._dictate_key_down = False
        # Monotonic time of the last press edge that reported the key as down.
        # It is what makes the latch above self-healing: see
        # ``_on_dictate_press`` and ``_DICTATE_HOLD_REPEAT_GRACE_S``.
        self._dictate_key_seen_at = 0.0
        # The live ``HotkeyTrigger`` while the pipeline runs — the hold-key
        # watchdog asks it whether the dictation chord is physically down.
        self._hotkey_trigger: Any = None
        # Which door the running dictation came through (``hold_key``,
        # ``toggle_key``, ``ws``, ``rest``, ``api``). Logged on start so the
        # next "it never stopped" report can be read, and it decides whether the
        # hold-key watchdog applies: only a hold-started recording is owed a
        # release edge.
        self._dictation_started_by = ""
        # Set by ``request_dictation_stop(discard=True)`` — the bar's close-X.
        # The recording ends through the ordinary stop event, and this flag
        # makes the session treat it as a hangup: nothing transcribed, nothing
        # delivered. Reset at every commit.
        self._dictation_discard_requested = False
        # Set when the early start of a solo hold key is taken back
        # (``_on_dictate_abandon``): that discard writes no history row.
        self._dictation_leave_no_trace = False
        # True between a solo hold key's early start and its confirmation.
        self._dictate_early_pending = False
        # ``self._stt`` is the LOCAL FasterWhisperProvider used by the wake
        # backstop + VAD endpoint-probe (many calls/sec, a cloud round-trip
        # would be too slow). In the cloud-first lightweight path it is None:
        # openWakeWord alone handles wake and no local Whisper is loaded.
        # An explicitly passed ``stt`` always wins; otherwise build one only
        # when the heavy local path is enabled.
        if stt is not None:
            self._stt = stt
        elif enable_local_whisper:
            self._stt = FasterWhisperProvider()
        else:
            self._stt = None
        # ``self._utterance_stt`` is the post-wake final transcription. It
        # honours ``cfg.stt.provider`` and may resolve to a cloud STT (Groq,
        # OpenAI, Deepgram). Defaults to the local instance if no config is
        # passed in (may be None in the lightweight path).
        self._utterance_stt: Any = self._stt
        if config is not None and getattr(config, "stt", None) is not None:
            try:
                from dodaios.plugins.stt import build_stt_from_config

                resolved = build_stt_from_config(config.stt)
                # The configured final recognizer owns its model and settings,
                # even when the wake recognizer uses the same provider class.
                if resolved is not None and resolved is not self._stt:
                    self._utterance_stt = resolved
                    log.info(
                        "Utterance-STT provider resolved: %s (wake stays local)",
                        type(resolved).__name__,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Utterance-STT factory failed (%s); reusing local Whisper for utterances.",
                    exc,
                )
        # Runtime fallback (AP-22). ``build_stt_from_config`` only crosses to
        # another provider when the configured one has no KEY — a build-time
        # decision. A provider that fails at CALL time (a 429 mid-dictation, an
        # expired key, a 503) had no way out, so one rate limit deleted the
        # user's words while three other keyed providers sat unused. The chain
        # is names-only until something actually fails, so this costs the boot
        # path nothing (AP-26).
        #
        # Skipped entirely for an on-device recognizer, and this is the SAME
        # privacy floor ``_resolve_stt_fallback_chain`` applies: every alternate
        # ``alternate_provider_names`` can offer a locally-configured user is a
        # cloud one (it appends the local engine only when it is NOT the
        # configured provider), so this wrapper is the earliest and widest of
        # the automatic doors out of the machine — it sits on the utterance
        # provider every voice turn uses. Someone who chose an on-device
        # recognizer chose it so their recordings would stay here; an automatic
        # upload on the first 429 is not a fallback they agreed to. Pinning
        # ``[stt].fallback`` to a provider id still crosses, through the
        # resolver above.
        if (
            config is not None
            and getattr(config, "stt", None) is not None
            and not _stt_crossover_would_leave_the_machine()
        ):
            try:
                from dodaios.speech.stt_fallback import wrap_stt_with_fallback

                self._utterance_stt = wrap_stt_with_fallback(
                    self._utterance_stt, config.stt
                )
            except Exception as exc:  # noqa: BLE001 — never block voice boot
                log.warning("STT fallback chain unavailable: %s", exc)
        # Live transcript preview uses the cheap local probe when available.
        # In lightweight mode there is no local Whisper, but the post-wake
        # utterance STT may still exist (cloud provider). Keep that path alive
        # so the Listening bubble does not stay stuck on "...".
        self._probe_stt: Any = self._select_probe_stt(self._utterance_stt)
        # User STT dictionary (dictation-tool-style custom vocabulary): wrap the
        # utterance + preview handles so EVERY provider's transcript gets the
        # user's corrections — brain turns, chat dictation, and the live
        # preview alike (pure string ops, hot-path safe). The wake path
        # (``self._stt``, wake whisper, echo confirm) stays UNWRAPPED: wake
        # matching must never see rewritten transcripts (AP-27 territory).
        try:
            from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

            self._utterance_stt = wrap_stt_with_dictionary(self._utterance_stt)
            self._probe_stt = wrap_stt_with_dictionary(self._probe_stt)
        except Exception as exc:  # noqa: BLE001 — corrections must never break voice boot
            log.warning("STT dictionary wrapper unavailable: %s", exc)
        self._tts = tts or _default_tts_for_pipeline(config)
        # Keep the user's activation preference separate from the detector
        # selected by the current wake plan. A phrase/model can change while
        # always-on listening is disabled; that must update the prepared plan
        # without silently opening the microphone. Older/duck-typed callers
        # without a TriggerConfig keep the legacy behaviour where a later
        # set_wake_plan() arms the resolved detector.
        trigger_cfg = getattr(config, "trigger", None)
        configured_wake_enabled = getattr(trigger_cfg, "wake_word_enabled", None)
        self._wake_word_enabled: bool | None = (
            bool(configured_wake_enabled)
            if configured_wake_enabled is not None
            else None
        )
        # A non-default instance of the desktop app (``dodaios.core.instance``,
        # the "dev" app beside the live one) never listens for the wake word
        # and never arms a global hotkey — the microphone and the key combos
        # belong to the default app; two listeners would both answer. The
        # in-window mic button and the chat still work, so voice can be tested.
        if not _owns_ambient_duties():
            self._wake_word_enabled = False
            enable_openwakeword = False
            enable_whisper_wake = False
        self._openwakeword_enabled = enable_openwakeword
        # Custom-wake-word plan (dodaios.speech.wake_phrase.WakeWordPlan) or None.
        # When None, the wake path is byte-identical to the legacy "Hey Jarvis"
        # behaviour (every existing test + call site). When set, the plan drives
        # the OWW model + threshold, the prefix-verifier matcher, and the
        # rolling-whisper pattern.
        self._wake_plan = wake_plan
        self._wake_matcher = getattr(wake_plan, "matcher", None)
        # Human label for the wake-listener log line so debugging reflects the
        # actually-configured phrase ("Computer") instead of a hardcoded
        # "Hey Jarvis" when a custom wake word is in use.
        self._wake_phrase_label = getattr(wake_plan, "phrase", None) or "the wake word"
        # Live-apply signal: set_wake_plan() flips this so a running
        # _run_parallel_wake aborts early and _wake_loop re-arms with the new
        # detector/model/matcher — the wake word changes WITHOUT an app restart.
        self._wake_reload_event = asyncio.Event()
        # Live-apply signal: set_keybinds() flips this so the running hotkey
        # trigger re-arms with the new Call/Hangup/Talk combos — a keybind change
        # takes effect WITHOUT an app restart (mirrors the wake live-reload).
        self._hotkey_reload_event = asyncio.Event()
        if wake is not None:
            self._wake = wake
        elif wake_plan is not None and getattr(wake_plan, "engine", "") == "vosk_kws":
            # Any-word Vosk grammar KWS (design spec 2026-07-05): identical
            # CPU-only detector on every OS, phrase is pure configuration.
            from dodaios.plugins.wake.vosk_kws_provider import VoskKwsProvider

            self._wake = VoskKwsProvider(
                phrase=wake_plan.phrase,
                model_path=wake_plan.vosk_model_path or "",
                model_paths=getattr(wake_plan, "vosk_model_paths", ()),
                keyword=wake_plan.oww_keyword,
                early_candidate_listener=self._vosk_early_candidate_listener,
            )
        elif wake_plan is not None:
            self._wake = OpenWakeWordProvider(
                keywords=(wake_plan.oww_keyword,),
                activation_threshold=wake_plan.threshold,
                model_path=wake_plan.oww_model_path,
                # A user-trained custom_onnx model fires on normal-volume speech
                # (~0.9) and must NOT be fed the amplify-only AGC: it lifts quiet
                # BREATH to full scale, which the model then fires on at ~1.0 (live
                # 2026-07-01 "triggers on breathing"). Raw audio scores breath ~0.
                # The pretrained OWW models DO need the AGC (they fire at 0.15-0.23).
                gain_normalization=getattr(wake_plan, "engine", "") != "custom_onnx",
            )
        else:
            self._wake = OpenWakeWordProvider(
                keywords=wake_keywords, activation_threshold=wake_threshold
            )
        # Rolling-window Whisper: transcribes the last ~2 s of audio on a poll
        # cadence and matches the wake phrase. No VAD-endpoint dependency, so
        # it stays robust on a quiet mic. It needs BOTH a local Whisper engine
        # AND a phrase matcher: with no wake plan there is no phrase to listen
        # for (no shipped default pattern — design 2026-07-07), so no rolling
        # detector is armed; a later set_wake_plan() arms one live. The
        # enabled flag stays in lockstep so the heartbeat reports whisper=off
        # instead of a phantom on.
        if (
            enable_whisper_wake
            and self._stt is not None
            and self._wake_matcher is not None
        ):
            self._whisper_wake = RollingWhisperWake(
                self._stt,
                pattern=self._wake_matcher,
                poll_interval_s=self._wake_poll_interval(),
            )
            self._whisper_wake_enabled = True
        else:
            self._whisper_wake = None
            self._whisper_wake_enabled = False
        # require_hey_prefix may arrive either as an explicit kwarg or from
        # cfg.trigger.require_hey_prefix. The kwarg wins so tests can override.
        cfg_require = True
        if config is not None and getattr(config, "trigger", None) is not None:
            cfg_require = bool(
                getattr(config.trigger, "require_hey_prefix", True)
            )
        self._require_hey_prefix = bool(require_hey_prefix) and cfg_require
        self._base_brain: BrainCallback = brain_callback or _echo_brain
        self._brain: BrainCallback = self._base_brain
        # Flash-Brain reference (None when feature disabled).
        self._ack_brain: Any = ack_brain
        self._turn_state = TurnTakingState.IDLE
        self._brain_timeout_s = max(1.0, float(brain_timeout_s))
        self._brain_last_progress = time.monotonic()
        # Pre-first-token "still-thinking" heartbeat (WS2, live bug 2026-06-14):
        # a dedicated monotonic stamp the no-first-frame ceiling re-arm reads, so
        # a deep brain that thinks for tens of seconds before its first token (no
        # on_progress, no tool round) is not beheaded. Pinged by
        # _run_brain_with_stall_guard only while pre-first-token. Kept SEPARATE
        # from _brain_last_progress so the 30 s brain no-progress stall guard
        # stays intact. 0.0 = no turn in flight / not thinking.
        self._brain_thinking_heartbeat: float = 0.0
        # Monotonic stamp of the last *long-running desktop tool* heartbeat
        # (computer_use loop step → ObservationCaptured/ActionPlanned on the bus
        # → _on_agent_progress). While these keep arriving the absolute ceiling
        # is suspended in _run_brain_with_stall_guard, so a legitimately long
        # multi-step desktop automation is never guillotined mid-work (live bug
        # 2026-06-07: a 10-step OBS automation was cut off at 30 s). 0.0 = never
        # seen, so the ceiling applies normally to ordinary chat/vision turns.
        self._long_tool_last_activity: float = 0.0
        # Hard ceiling on a single TTS playback (see _TTS_PLAYBACK_CEILING_S).
        # Guards against a stalled output device / TTS stream wedging _speak —
        # which would freeze the voice session and stop the wake loop re-arming.
        self._speak_playback_ceiling_s = _TTS_PLAYBACK_CEILING_S
        # Mid-playback device-wedge detector (Wave-1 latency fix). Polls the
        # player's write-progress and aborts a stalled device in ~5 s instead of
        # waiting out the ceiling — the core fix for the 60-156 s "open app"
        # voice-hangs.
        self._speak_playback_stall_s = _TTS_PLAYBACK_STALL_S
        # Per-turn terminal mark: a timeout / "couldn't finish" notice already
        # spoke for this utterance, so the outcome is closed. The double-answer
        # guard in ``_speak`` reads it to suppress a late/abandoned brain ANSWER
        # (kind="reply") that would otherwise speak a SECOND time for the same
        # content (live complaint 2026-06-30: a stalled tool timed out, then the
        # turn re-answered). Re-armed at every utterance finalize.
        self._brain_timeout_spoken_this_turn = False
        # Bus injected so AudioPlayer publishes AudioOutFirst on the first
        # audible sample — UI subscribers (orb mouth animation + SPEAKING
        # bubble) sync to actual audio start, not the early SPEAKING state.
        # Master output volume (0.0–1.0) from [tts].volume. Defensive getattr
        # chain: ``config`` may be None (test fixtures) and older TOMLs predate
        # the field — both fall back to full volume.
        _tts_volume = getattr(getattr(config, "tts", None), "volume", 1.0)
        # Optional user device-name priority ([audio].*_device_priority) fed into
        # the "auto-headset" resolver so an uncommon headset/mic wins by name
        # without a code edit. Defensive getattr: ``config`` may be None (test
        # fixtures) and older TOMLs predate the fields — both mean "no override".
        _audio_cfg = getattr(config, "audio", None)
        self._output_priority: tuple[str, ...] = tuple(
            getattr(_audio_cfg, "output_device_priority", None) or ()
        )
        self._input_priority: tuple[str, ...] = tuple(
            getattr(_audio_cfg, "input_device_priority", None) or ()
        )
        self._player = AudioPlayer(
            device=output_device,
            bus=bus,
            volume=_tts_volume,
            device_priority=self._output_priority,
        )
        bind_shared_audio_player(self._player)
        # Kept so warm-up can re-resolve the output device against a freshly
        # re-enumerated PortAudio table (post-reboot idx-drift cure, BUG-014).
        self._output_device = output_device
        self._input_device = input_device
        # Idle/silence auto-hangup. A value <= 0 DISABLES it: the session then
        # waits forever for the next utterance or a manual hangup (hotkey /
        # "auflegen"), exactly the "stay active until I hang up" mandate
        # (2026-06-30). ``_idle_timeout_s`` is kept at a sane POSITIVE value even
        # when disabled because the re-arm grace fields below are derived from it
        # and the grace math must never see a zero/negative window; those graces
        # are only consulted on the idle-expiry branch, which is unreachable once
        # the hangup is disabled (the loop passes ``timeout=None`` to asyncio.wait).
        self._idle_hangup_enabled = idle_timeout_s > 0
        self._idle_timeout_s = idle_timeout_s if idle_timeout_s > 0 else 30.0
        # Monotonic timestamp of the moment Jarvis last STOPPED speaking an
        # inline answer (SPEAKING -> LISTENING). A long turn dispatched OFF the
        # ``_active_session`` loop — the delegation grace / completion timer buffers
        # a complete-looking command and answers it ~24 s later — leaves the idle
        # window that was armed at the user's utterance still ticking through the
        # whole turn, so it expires seconds after the answer lands and hangs up on
        # a user who never asked to (forensic 2026-06-27 08:49: a "switch the
        # worker" command answered after ~24 s; the 30 s window armed at the
        # utterance expired 6 s later). The idle-expiry branch grants ONE fresh
        # window while within this grace (== one idle window).
        self._last_answer_floor_monotonic: float | None = None
        self._assistant_work_count = 0
        self._termination_producer = ""
        self._termination_detail: dict[str, Any] = {}
        self._idle_deadline_monotonic: float | None = None
        self._previous_turn_state: str | None = None
        self._post_tts_listen_suppression_s = post_tts_listen_suppression_s
        self._input_suppressed_until_ns: int = 0
        self._continue_listening_after_response = continue_listening_after_response
        self._ack_phrase = ack_phrase

        self._state = PipelineState.IDLE
        self._call_event = asyncio.Event()
        self._hangup_confirmation = HangupConfirmation()
        self._hangup_event = asyncio.Event()
        # Wake and session capture use the same physical input device. A wake
        # stream must close before the session stream opens, while frames heard
        # after the visible wake candidate are retained for the session.
        self._wake_capture_released = asyncio.Event()
        self._wake_capture_released.set()
        self._wake_stop_event = asyncio.Event()
        self._wake_cancel_event = asyncio.Event()
        self._wake_handoff_ready = asyncio.Event()
        self._wake_handoff_buffer: _SessionInputBuffer | None = None
        self._wake_preroll_active = False
        self._wake_preroll_confirmed = False
        # Candidate verification is bounded; retain its short post-reveal
        # window in full so the first spoken word can never fall off a
        # chunk-count deque before the live handoff is accepted.
        self._pending_session_preroll: deque[AudioChunk] = deque()
        # ``request_hangup`` is also called by the JarvisBar's dedicated Tk
        # thread. asyncio primitives are not thread-safe, so ``run()`` records
        # their owning loop and external callers marshal the hangup onto it.
        self._runtime_loop: asyncio.AbstractEventLoop | None = None
        # A thread-safe edge latch keeps repeated X clicks from queueing the
        # expensive hard-stop path more than once during the same teardown.
        self._external_hangup_pending = threading.Event()
        # Distinguish a close that arrived after a wake stream was offered from
        # an older no-op hangup while truly idle. Both otherwise share the same
        # asyncio hangup event when the state loop begins.
        self._wake_handoff_hangup_pending = threading.Event()
        self._current_voice_session_id: str | None = None
        # Configured voice mode and effective in-flight engine are deliberately
        # separate. A settings write can happen while a call is already open;
        # without this runtime state the UI used to report "Realtime" while the
        # existing call continued through classic STT -> Brain -> TTS.
        self._active_realtime_provider: str = ""
        self._active_realtime_model: str = ""
        self._active_realtime_handle: Any | None = None
        self._voice_engine_transitioning: bool = False
        self._reopen_after_engine_change: bool = False
        self._engine_change_reason: str = ""
        # Optional event-bus integration. With no bus, transition and emit
        # calls are backward-compatible no-ops.
        self._bus = bus
        # Speech spend. The meter wraps the providers rather than the dozen
        # call sites that use them, so a synthesis added later is counted
        # without anyone remembering to count it. Only the two that bill are
        # wrapped: ``self._stt`` is the local wake/VAD Whisper, free and
        # called many times a second, and metering it would be noise on the
        # hot path for a number that is always zero.
        # No bus means no spend can be published (no sink), but the providers
        # are still wrapped: the same wrapper feeds the provider-health record
        # behind the status dots, which must not depend on the cost sink.
        self._speech_spend = SpeechSpendRecorder(bus) if bus is not None else None
        self._tts = meter_tts(self._tts, self._speech_spend, trace_id=self._speech_trace)
        self._utterance_stt = meter_stt(
            self._utterance_stt, self._speech_spend, trace_id=self._speech_trace
        )
        self._supervisor = supervisor
        # Permanent Vision (Wave 2 B7) is optional. Without an injected
        # provider, every vision hook is a no-op.
        self._config = config
        self._vision_provider = vision_provider
        self._realtime_audio_renderer = realtime_audio_renderer
        self._activation_gate = activation_gate or (lambda: True)
        self._user_activation_gate = user_activation_gate or (lambda: True)
        self._permission_gate = permission_gate
        # True only while the wake loop is parked on the microphone permission:
        # the one state in which a PermissionResolved edge should wake it.
        self._wake_parked_on_permission = False
        # Wave 0 (omni-latency): per-turn hot-path latency tracker. Anchored at
        # utterance finalize in ``_handle_utterance``; ``None`` until a turn runs.
        self._latency_tracker: LatencyTracker | None = None
        self._latency_first_audio_marked = False
        # Wake-Cooldown nach Hangup: verhindert dass TTS-Ausgabe den Mic
        # selbst wieder als "Hey Jarvis" triggert (Speaker→Mic-Feedback-Loop).
        self._wake_lock_until: float = 0.0
        self._post_hangup_lock_s: float = 3.0
        # A user-initiated HARD hangup (JarvisBar close, hotkey, "auflegen")
        # stops the player, so there is NO TTS tail to echo — the long
        # post-hangup lock then only DEAFENS the wake to the user's very next
        # "Hey <wake>" ("say it twice", live log 2026-07-02 18:40/18:46). Such a
        # hangup uses this SHORT lock instead: just past the disconnect earcon,
        # not the 3 s speaker-tail guard. Set by ``_trigger_voice_hangup`` when
        # it stops the player; reset per session so a no-op hangup while idle
        # cannot shorten a later natural end's lock.
        self._explicit_hangup_lock_s: float = 0.4
        self._explicit_hard_hangup: bool = False
        self._last_wake_keyword: str = ""
        # 2026-05-26: timestamp of the last priority="interrupt"
        # announcement, used by ``_on_announcement`` to gate preamble-class
        # announcements that would otherwise produce cross-surface voice
        # incoherence.  See diagnosis in
        # docs/plans/voice-phrase-mismatch-2026-05-26/README.md and the
        # ``suppress_preamble_after_interrupt_ms`` knob on AckBrainConfig.
        self._last_interrupt_announcement_ts: float | None = None
        # 2026-07-06 interim-ack redesign: (text, monotonic) of the last SPOKEN
        # preamble/progress announcement. ``_on_announcement`` drops a new
        # preamble/progress line with identical wording inside the
        # ``preamble_dedup_window_s`` window — no emitter may repeat itself
        # verbatim in quick succession (forensic 2026-07-05: the identical
        # grounded ack spoke three times in one session).
        self._last_preamble_spoken: tuple[str, float] | None = None
        # v2 anti-loop backstop: monotonic timestamps of SPOKEN preamble/
        # progress lines. ``_on_announcement`` drops anything beyond
        # ``preamble_rate_limit_per_min`` in a rolling 60 s window so the
        # historical "kept repeating forever" bug class dies at this shared
        # chokepoint no matter which emitter misbehaves.
        self._preamble_spoken_times: deque[float] = deque(maxlen=32)
        # AD-OE5/OE6: completion-class announcements that arrive while the user
        # holds the floor are parked here and flushed at the next turn-boundary
        # (when the turn-state returns to LISTENING/IDLE) instead of barging
        # mid-utterance. Preambles are dropped, not parked — they are stale by
        # the time the user finishes. See ``_on_announcement`` + ``_set_turn_state``.
        self._deferred_announcements: list[AnnouncementRequested] = []
        self._agent_reply_inflight: AnnouncementRequested | None = None
        self._agent_reply_inflight_text = ""
        self._agent_reply_retries: list[AnnouncementRequested] = []
        self._agent_reply_retry_task: asyncio.Task[None] | None = None
        # Optional pre-rendered acknowledgement PCM, populated during warmup.
        self._ack_pcm: bytes = b""
        # Pre-rendered Task-Ack-Phrasen ("Sofort.", "Right away." …) als PCM-Cache.
        # Key: (lang, phrase_text) → PCM-Bytes. Abspielrate siehe GeminiFlashTTS (24 kHz).
        self._task_ack_pcm: dict[tuple[str, str], bytes] = {}

        # Global voice mute — toggled via mascot doubleClick (and any
        # future trigger surface that publishes VoiceMuteToggleRequested).
        # While True, ``_activation_allowed`` returns False so the wake
        # path never fires, and every TTS exit short-circuits. The wake-
        # loop itself keeps running; unmuting is instantaneous.
        self._muted: bool = False

        # CRIT-5 watchdog (user decision 2026-05-17): when the user fires a
        # force-spawn-worker, the worker subprocess runs silently for the
        # duration of the mission. Per the 2026-05-12 calibration, the
        # Spawn-ACK is intentionally suppressed -- but Audit-1 found the
        # resulting 40-90 s silence leaves the user unable to tell whether
        # Jarvis is working or stuck. Compromise: at 90 s we emit a single
        # discrete "Bin noch dran." via AnnouncementRequested. Cancel
        # the watchdog on JarvisAgentBackgroundCompleted so successful
        # short missions stay silent. FIFO list, one entry per pending
        # spawn -- matches the sequential-dispatch model of the voice
        # pipeline. The 90 s threshold is well past the typical short
        # mission (8-30 s) and avoids spamming the user every spawn.
        self._spawn_watchdog_tasks: list[asyncio.Task[None]] = []
        # First "still on it" heartbeat fires after this delay; 90 s of pure
        # silence read as a crash (2026-06-19), so the first reassurance comes
        # sooner. Then up to ``_heartbeat_max_count`` total, ``_heartbeat_interval_s``
        # apart, while the mission is in flight — hard-bounded so it can never run
        # forever (the in-flight hold equals the watchdog lifetime, see
        # _live_spawn_watchdogs). Tests override these.
        # 30 -> 20 s (2026-08-17, instant-ack contract): the user heard the
        # handover line at the start; twenty seconds of nothing afterwards
        # is where "is it still working?" begins.
        self._spawn_watchdog_delay_s: float = 20.0
        self._heartbeat_interval_s: float = 60.0
        self._heartbeat_max_count: int = 3
        self._heartbeat_recent: deque[str] = deque(maxlen=2)

        # TTS announcement bridge (Phase 5 CL-13): router/tools emit
        # `AnnouncementRequested` when they want to give the user an interim
        # announcement (e.g. "Starting a sub-agent, one moment."), without
        # going through the brain path. The handler speaks directly via TTS.
        if self._bus is not None:
            self._bus.subscribe(AnnouncementRequested, self._on_announcement)
            # A microphone grant (from the OS dialog, or from System Settings and
            # seen by the service watcher) wakes a wake loop parked on it.
            self._bus.subscribe(PermissionResolved, self._on_permission_resolved)
            # Fire-and-forget Jarvis-Agent: when a background run finishes,
            # a proactive voice announcement ("Sir, done. <summary>") — so
            # the user finds out even if they did something else in the
            # meantime.
            self._bus.subscribe(
                JarvisAgentBackgroundCompleted, self._on_background_completed
            )
            # Spawn-Ansage: dynamisch aus action/target geformt.
            self._bus.subscribe(JarvisAgentAnnouncement, self._on_spawn_announcement)
            # Mute toggle from any trigger surface (mascot doubleClick,
            # future hotkey/REST). The handler flips ``self._muted`` and
            # republishes the authoritative state on the bus.
            self._bus.subscribe(
                VoiceMuteToggleRequested, self._on_mute_toggle_requested
            )
            # Prompt Mode toggle from the Jarvis bar's sparkle. The pipeline
            # holds the live dictation config, so it owns the flip and answers
            # with DictationPromptModeChanged for every mirror of the switch.
            self._bus.subscribe(
                DictationPromptModePauseToggleRequested,
                self._on_prompt_mode_pause_toggle_requested,
            )
            # Wave 0 (omni-latency): perceived time-to-first-audio (ack OR
            # brain, whichever speaks first) feeds the per-turn latency tracker.
            self._bus.subscribe(AudioOutFirst, self._on_audio_out_first)
            # Instant-ack progress line (2026-08-17): remember which tool the
            # turn is actually running so a long wait gets an HONEST "still
            # searching" instead of a generic filler.
            self._bus.subscribe(ActionProposed, self._on_action_proposed)

        # Phase-B warm-up (confirmation-audio pre-render) runs off the critical
        # path so voice can declare ready early. Kept on the instance so tests
        # (and a graceful shutdown) can await it.
        self._warmup_background_task: asyncio.Task | None = None
        # Audible boot-ready cue. It must never sit between ready=True and the
        # wake loop; slow output devices can block playback for seconds.
        self._warmup_ready_cue_task: asyncio.Task | None = None
        # Deferred wake-non-critical loaders (VAD/STT/TTS) run off the
        # wake-ready path so "Hey Jarvis" responds without waiting out the
        # 7-24 s starved warm-up (see ``_warmup_phase_a``). Kept on the instance
        # so a graceful shutdown can cancel + await it.
        self._deferred_warmup_task: asyncio.Task | None = None
        # The local Whisper worker of the dictation is started only after
        # honest readiness; the task is tracked for shutdown.
        self._dictation_warmup_task: asyncio.Task | None = None
        self._dictation_warmup_shutdown = False
        self._voice_stt_warmup_task: asyncio.Task | None = None
        self._voice_stt_warmup_provider: Any = None
        self._audio_topology_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Live-Provider-Switch (Voice ohne Pipeline-Restart)
    # ------------------------------------------------------------------

    def set_tts(self, new_tts: Any) -> None:
        """Tauscht den TTS-Provider live aus. Kein Pipeline-Restart noetig.

        Der naechste ``_speak()``-Aufruf nutzt automatisch die neue Instanz —
        ein bereits laufender ``synthesize()``-AsyncGen wird nicht
        unterbrochen, weil er an die alte Instanz gebunden ist (sauberer
        Cut-over).

        **Cache-Invalidierung:** Pre-renderte ACK-/Task-Ack-PCM stammen aus
        dem alten Provider und wuerden sonst beim naechsten Wake/Brain-Delay
        in der alten Stimme abgespielt — das war der "warum hoere ich noch
        die alte Stimme nach dem Switch"-Bug. Wir leeren die Caches, der
        naechste Wake rendert sie auto neu (oder skippt bei leerem
        ``ACK_PHRASE``).
        """
        old = type(self._tts).__name__
        new = type(new_tts).__name__
        log.info("TTS live switch: %s -> %s (caches invalidated)", old, new)
        # The replacement is metered like the one it replaces, or spend would
        # stop being recorded the first time someone changed voice.
        self._tts = meter_tts(new_tts, self._speech_spend, trace_id=self._speech_trace)
        self._ack_pcm = b""
        self._task_ack_pcm.clear()

    def set_stt_provider(self, provider: str, *, model: str | None = None) -> bool:
        """Live-apply an utterance STT provider without restarting the app.

        The wake recognizer is intentionally left alone: it is a local,
        latency-sensitive detector with a separate lifecycle. Voice turns and
        dictation use the newly built provider from the next transcription.
        A dictation already in flight keeps its existing local reference and
        finishes normally, which avoids reaching into a native inference
        engine while it is running (AP-24).

        The new provider is fully constructed before any live reference or
        configuration value is changed. A failed build therefore leaves the
        current provider usable and returns ``False`` to the REST route.
        """
        normalized = str(provider or "").strip()
        cfg_stt = getattr(getattr(self, "_config", None), "stt", None)
        if not normalized or cfg_stt is None:
            return False

        updates: dict[str, Any] = {"provider": normalized}
        if model is not None:
            updates["model"] = model
        try:
            candidate = cfg_stt.model_copy(update=updates)
        except AttributeError:
            # Lightweight test doubles may not be Pydantic models. Preserve
            # their remaining attributes through a read-only overlay.
            class _CandidateConfig:
                def __getattr__(_self, name: str) -> Any:
                    if name in updates:
                        return updates[name]
                    return getattr(cfg_stt, name)

            candidate = _CandidateConfig()

        try:
            from dodaios.plugins.stt import (
                build_stt_from_config,
                provider_runs_on_device,
            )

            rebuilt = build_stt_from_config(candidate)
            actual = str(getattr(rebuilt, "name", "") or "").strip()
            if actual and actual != normalized:
                log.error(
                    "STT live switch resolved %s instead of requested %s; "
                    "keeping the current provider.",
                    actual,
                    normalized,
                )
                return False

            if not provider_runs_on_device(normalized):
                from dodaios.speech.stt_fallback import wrap_stt_with_fallback

                rebuilt = wrap_stt_with_fallback(rebuilt, candidate)

            from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

            rebuilt = wrap_stt_with_dictionary(rebuilt)
        except Exception as exc:  # noqa: BLE001 — preserve the working provider
            log.error(
                "STT live switch to %s failed; keeping the current provider: %s",
                normalized,
                exc,
                exc_info=True,
            )
            return False

        previous = getattr(self, "_utterance_stt", None)
        # Re-wrapped like ``set_tts`` does, or hearing spend would stop being
        # recorded the first time someone changed the STT provider.
        self._utterance_stt = meter_stt(
            rebuilt, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
        )
        # A lightweight/cloud-first pipeline has no local preview recognizer,
        # so its preview must follow the selected provider. A heavy wake path
        # keeps its dedicated local probe.
        self._probe_stt = self._select_probe_stt(rebuilt)
        try:
            cfg_stt.provider = normalized
            if model is not None:
                cfg_stt.model = model
        except Exception as exc:  # noqa: BLE001 — runtime cut-over already succeeded
            log.debug("In-memory STT config update skipped: %s", exc)

        # Dictation owns a prompt-free instance and a separate fallback chain;
        # both must be rebuilt from the new provider on the next key press.
        self._reset_dictation_stt()
        self._schedule_dictation_warmup()
        log.info(
            "STT live switch applied: %s -> %s (dictation cache invalidated).",
            type(previous).__name__ if previous is not None else "none",
            normalized,
        )
        return True

    def set_stt_language(self, language: str) -> bool:
        """Live-apply a new recognition language. Returns True when it took.

        The utterance recogniser carries its language from construction, so
        changing the setting used to do nothing at all until the app was
        restarted — while the settings route reported the change as applied,
        because "applied" only ever meant the WAKE plan. The honest outcome is
        either a recogniser that actually speaks the new language now, or a
        False the caller can turn into "restart to apply".

        Rebuilding is cheap: cloud providers are a constructor plus an HTTP
        client, and the local faster-whisper loads its weights lazily on the
        first transcription. The swap is a clean cut-over like ``set_tts`` — an
        in-flight transcription keeps the old instance and finishes normally
        (AP-24: never reach into a native engine that is mid-inference).

        The WAKE recogniser (``self._stt``) is deliberately untouched: it is
        acoustically tied to the wake phrase and has its own language setting.
        """
        cfg_stt = getattr(getattr(self, "_config", None), "stt", None)
        if cfg_stt is None:
            return False
        try:
            cfg_stt.language = language
        except Exception as exc:  # noqa: BLE001 — a frozen model is not an error
            log.debug("in-memory stt.language update skipped: %s", exc)
        try:
            from dodaios.plugins.stt import build_stt_from_config

            rebuilt = build_stt_from_config(cfg_stt)
        except Exception as exc:  # noqa: BLE001 — never break voice on a settings click
            log.warning("STT language live-switch failed to build a provider: %s", exc)
            return False
        if rebuilt is None:
            return False

        try:
            from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

            rebuilt = wrap_stt_with_dictionary(rebuilt)
        except Exception as exc:  # noqa: BLE001 — corrections are not load-bearing here
            log.debug("STT dictionary wrapper unavailable on live switch: %s", exc)

        # Same rule as ``set_stt_provider``: the meter wraps the new instance.
        self._utterance_stt = meter_stt(
            rebuilt, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
        )
        # Re-select after wrapping: wrapper identity is not provider identity.
        self._probe_stt = self._select_probe_stt(rebuilt)
        # The dictation lane holds its OWN instance (no voice bias prompt), so a
        # switch that only rebuilt the voice one would leave dictation
        # transcribing in the previous recognition language for the rest of the
        # process — a setting that appears to apply and silently does not.
        self._reset_dictation_stt()
        self._schedule_dictation_warmup()
        log.info(
            "STT-Live-Switch: recognition language is now %r (%s)",
            language,
            type(rebuilt).__name__,
        )
        return True

    def set_tts_volume(self, volume: float, *, source: str = "") -> None:
        """Change playback volume without clearing the independent speaker mute.

        Publish a complete output snapshot for native and browser sinks. The
        lock serializes callers from the bar and REST threads; events are
        delivered on the pipeline loop. No configuration is written here.
        """
        target = float(volume)
        lock = getattr(self, "_speaker_mute_lock", None)
        if lock is None:
            # Pipelines built via ``__new__`` in tests skip ``__init__``.
            lock = self._speaker_mute_lock = threading.RLock()
        with lock:
            last = getattr(self, "_speaker_muted_last", None)
            was_muted = self.get_tts_volume() <= 0.0 if last is None else last
            # Remembered even without a player, so a headless mute/unmute
            # reads back what was asked for instead of the boot value.
            self._tts_volume_requested = max(0.0, min(1.0, target))
            player = getattr(self, "_player", None)
            setter = getattr(player, "set_volume", None)
            if callable(setter):
                setter(target)
            muted = self.is_speaker_muted
            mute_setter = getattr(player, "set_muted", None)
            if callable(mute_setter):
                mute_setter(muted or self.get_tts_volume() <= 0.0)
            self._speaker_muted_last = muted
            if muted != was_muted:
                log.info(
                    "Speaker %s (source=%s)", "muted" if muted else "unmuted", source or "unknown"
                )
            self._publish_speaker_state(source)

    @property
    def is_speaker_muted(self) -> bool:
        return bool(getattr(self, "_speaker_muted", False))

    def speaker_output_state(self) -> dict[str, Any]:
        """The state seeded to new/reconnected audio outputs before playback."""
        with self._speaker_mute_lock:
            return {
                "muted": self.is_speaker_muted,
                "volume": self.get_tts_volume(),
                "revision": getattr(self, "_speaker_output_revision", 0),
            }

    def _publish_speaker_state(self, source: str) -> None:
        self._speaker_output_revision = getattr(self, "_speaker_output_revision", 0) + 1
        self._publish_event_soon(VoiceSpeakerMuteChanged(
            muted=self.is_speaker_muted, source=source,
            volume=self.get_tts_volume(), revision=self._speaker_output_revision,
        ))

    def set_speaker_muted(self, muted: bool, *, source: str = "") -> bool:
        """Mute output only; preserve microphone, work, session and volume."""
        with self._speaker_mute_lock:
            self._speaker_muted = bool(muted)
            setter = getattr(getattr(self, "_player", None), "set_muted", None)
            if callable(setter):
                setter(self.is_speaker_muted or self.get_tts_volume() <= 0.0)
            self._publish_speaker_state(source)
            return self.is_speaker_muted

    def toggle_speaker_mute(self, *, source: str = "") -> bool:
        with self._speaker_mute_lock:
            return self.set_speaker_muted(not self.is_speaker_muted, source=source)

    def get_tts_volume(self) -> float:
        """The master TTS output volume in effect right now (0.0–1.0).

        The live player's volume when there is a player, else the last value
        ``set_tts_volume`` was asked for, else the configured ``[tts].volume``,
        else full volume. The orb's speaker disc reads this to decide whether
        a click mutes or unmutes; without it every click read "audible" and the
        voice could be muted but never brought back.
        """
        player = getattr(self, "_player", None)
        live = getattr(player, "_volume", None)
        if isinstance(live, int | float) and not isinstance(live, bool):
            return max(0.0, min(1.0, float(live)))
        requested = getattr(self, "_tts_volume_requested", None)
        if isinstance(requested, int | float):
            return float(requested)
        configured = getattr(getattr(getattr(self, "_config", None), "tts", None), "volume", None)
        try:
            return max(0.0, min(1.0, float(configured))) if configured is not None else 1.0
        except (TypeError, ValueError):  # Invalid legacy volume values use the audible default.
            return 1.0

    def set_audio_devices(
        self,
        *,
        input_device: str | None = None,
        output_device: str | None = None,
    ) -> None:
        """Live-apply a Settings device pick — no app/pipeline restart.

        ``None`` leaves a side unchanged; a device NAME pins it and the
        ``"auto-headset"`` sentinel restores automatic selection (resolution
        happens at stream-open time in the player/capture resolvers).

        - Output: ``AudioPlayer.set_device`` re-resolves and tears down the
          persistent stream, so the next utterance plays on the new device.
        - Input: every mic open reads ``self._input_device`` (per-turn opens
          pick it up naturally); the long-lived wake session is re-armed via
          ``_wake_reload_event`` — the same live-reload contract as
          ``set_wake_plan`` — so the always-on mic reopens on the new device
          within a moment.
        """
        if output_device is not None:
            self._output_device = output_device or None
            player = getattr(self, "_player", None)
            setter = getattr(player, "set_device", None)
            if callable(setter):
                setter(self._output_device)
        if input_device is not None:
            self._input_device = input_device or None
            reload_event = getattr(self, "_wake_reload_event", None)
            if reload_event is not None:
                reload_event.set()

    def _wake_poll_interval(self) -> float:
        """The stt_match wake poll interval — always the fastest calibrated
        value (the user-facing Sensitivity slider was removed 2026-07-10;
        "always spawn at maximum speed on every OS" is now unconditional, not
        a slider-derived choice)."""
        from dodaios.speech.wake_phrase import WAKE_POLL_INTERVAL_S

        return WAKE_POLL_INTERVAL_S

    def set_wake_plan(self, plan: Any) -> None:
        """Live-apply a resolved WakeWordPlan — no app/pipeline restart.

        Root cause of "only Hey Jarvis works": the wake model + matcher are
        wired ONCE at construction, so a UI/toml change never reached the
        running detector. This rebuilds the wake detection in place:

        - openwakeword / custom_onnx -> swap in a new OpenWakeWordProvider for
          the plan's model; the neural model is reloaded lazily on the next
          wake-loop entry.
        - stt_match (an arbitrary custom phrase) -> build a local Whisper engine
          if absent, enable the RollingWhisperWake transcript matcher, and turn
          OpenWakeWord off (the neural model cannot detect an arbitrary phrase).

        After updating the references it flips ``_wake_reload_event`` so the
        running ``_run_parallel_wake`` aborts and ``_wake_loop`` re-arms with the
        new detectors (mic is reopened cleanly). Mirrors the ``set_tts``
        live-switch contract. Safe to call from the FastAPI handler thread — it
        shares the pipeline's event loop.
        """
        wake_preference = getattr(self, "_wake_word_enabled", None)
        wake_enabled = True if wake_preference is None else bool(wake_preference)
        prev = getattr(self._wake_plan, "oww_keyword", None)
        self._wake_plan = plan
        self._wake_matcher = getattr(plan, "matcher", None)
        self._wake_phrase_label = getattr(plan, "phrase", None) or "the wake word"
        engine = getattr(plan, "engine", "openwakeword")

        # A Faster-Whisper wake provider reads its phrase bias on every call.
        # Update it through a capability method so switching between arbitrary
        # stt_match phrases cannot keep transcribing with the old wake word.
        # Clear the bias on non-stt plans because the same provider can also
        # serve the live transcript preview.
        set_initial_prompt = getattr(self._stt, "set_initial_prompt", None)
        if callable(set_initial_prompt):
            prompt = getattr(plan, "phrase", None) if engine == "stt_match" else None
            set_initial_prompt(prompt)

        # Build a local Whisper engine on demand for the stt_match path. The
        # provider __init__ is light (the model loads lazily on first
        # transcription), so this does not block the caller.
        if (
            wake_enabled
            and getattr(plan, "needs_local_whisper", False)
            and self._stt is None
        ):
            try:
                from dodaios.plugins.stt import build_wake_whisper

                stt_cfg = getattr(self._config, "stt", None)
                lang = getattr(stt_cfg, "language", None)
                lang = None if lang in ("", "auto", None) else lang
                # Small CPU wake model (cfg.stt.wake_*), not the heavy utterance
                # model — keeps a live wake-word switch fast (Blackwell CUDA load
                # is ~71 s; base/cpu ~0.45 s, measured). Seed the prompt with the
                # custom phrase so the small model transcribes the (proper-noun)
                # wake name instead of a common word — forensic 2026-06-22.
                # fast_first: this runs on a live settings switch (often from
                # the FastAPI handler), so it must stay non-blocking. The
                # non-fast build now runs the one-time GPU inference probe
                # (blocking up to minutes on a cache miss) — that belongs to
                # the boot hot-swap only. Trade-off: after a LIVE wake-word
                # switch the stt_match wake runs on base/cpu until the next
                # app start, whose background hot-swap restores turbo/cuda.
                self._stt = build_wake_whisper(
                    stt_cfg,
                    language=lang,
                    wake_phrase=getattr(plan, "phrase", None),
                    fast_first=True,
                )
                if self._probe_stt is None:
                    try:
                        from dodaios.speech.stt_dictionary import (
                            wrap_stt_with_dictionary,
                        )

                        self._probe_stt = wrap_stt_with_dictionary(self._stt)
                    except Exception:  # noqa: BLE001 — preview must survive without it
                        self._probe_stt = self._stt
                log.info("Wake-Live-Switch: built local Whisper for custom phrase.")
            except Exception as exc:  # noqa: BLE001 — degrade, never crash the switch
                log.warning("Wake-Live-Switch: local Whisper build failed: %s", exc)

        if not getattr(plan, "wake_available", True):
            # No local model for the user's OWN word — arm NO detector. This is
            # the explicit, honest "wake off, use the Call shortcut" mode
            # (product rule 2026-07-04), NOT a dead listener. Do NOT fall back to
            # the bundled branded 'Hey Rhasspy'
            # model — listening for a word the user never says is the bug we are
            # removing. Installing the local speech pack (any word) or a custom
            # .onnx re-arms the wake via a later set_wake_plan.
            self._openwakeword_enabled = False
            self._whisper_wake_enabled = False
            if self._whisper_wake is not None and self._wake_matcher is not None:
                self._whisper_wake._pattern = self._wake_matcher  # noqa: SLF001
            log.info(
                "Wake-Live-Switch: no local model for %r — wake word OFF; "
                "the Call shortcut is the activation. Install the local "
                "speech pack (works for any word) or supply a custom .onnx to "
                "enable the wake word.",
                self._wake_phrase_label,
            )
        elif engine == "vosk_kws":
            # Any-word Vosk grammar KWS (design spec 2026-07-05) — same
            # detector on every OS; the phrase is pure configuration, so a
            # live wake-word change is just a new provider instance.
            from dodaios.plugins.wake.vosk_kws_provider import VoskKwsProvider

            self._wake = VoskKwsProvider(
                phrase=plan.phrase,
                model_path=getattr(plan, "vosk_model_path", None) or "",
                model_paths=getattr(plan, "vosk_model_paths", ()),
                keyword=plan.oww_keyword,
                early_candidate_listener=self._vosk_early_candidate_listener,
            )
            self._openwakeword_enabled = wake_enabled
            if self._whisper_wake is not None and self._wake_matcher is not None:
                self._whisper_wake._pattern = self._wake_matcher  # noqa: SLF001
            self._whisper_wake_enabled = False
        elif engine in ("openwakeword", "custom_onnx"):
            self._wake = OpenWakeWordProvider(
                keywords=(plan.oww_keyword,),
                activation_threshold=plan.threshold,
                model_path=plan.oww_model_path,
                # No amplify-only AGC for a user-trained custom model — it lifts
                # quiet breath to full scale and false-fires (see the ctor site).
                gain_normalization=engine != "custom_onnx",
            )
            self._openwakeword_enabled = wake_enabled
            # OWW stands alone for a live switch (lightweight default). The heavy
            # RollingWhisperWake backstop is a boot-time opt-in (heavy_local_whisper),
            # not part of a live wake-word change — turn it off here so switching
            # back to "Hey Jarvis" does not leave a stale custom-phrase matcher
            # running. Keep the pattern in sync in case it is re-enabled.
            if self._whisper_wake is not None and self._wake_matcher is not None:
                self._whisper_wake._pattern = self._wake_matcher  # noqa: SLF001
            self._whisper_wake_enabled = False
        else:  # stt_match — arbitrary phrase via local-Whisper transcript match
            if not wake_enabled:
                self._openwakeword_enabled = False
                self._whisper_wake_enabled = False
            elif self._stt is not None:
                self._openwakeword_enabled = False
                self._whisper_wake = RollingWhisperWake(
                    self._stt,
                    pattern=self._wake_matcher,
                    poll_interval_s=self._wake_poll_interval(),
                )
                self._whisper_wake_enabled = True
            else:
                # stt_match was requested but the local Whisper engine could not
                # be built. Product rule (2026-07-04): do NOT fall back to a
                # branded 'Hey Rhasspy' model (listening for a word the user never
                # says). Arm NO detector — the wake word is OFF and the honest
                # activation is the Call shortcut. This is an explicit,
                # user-visible mode, not a silent dead listener; installing or
                # repairing the local speech pack re-arms the custom phrase via a
                # later set_wake_plan.
                self._openwakeword_enabled = False
                self._whisper_wake_enabled = False
                log.warning(
                    "Wake-Live-Switch: stt_match requested but no local Whisper "
                    "could be built for %r — wake word OFF; use the Call shortcut. "
                    "Install or repair the local speech pack (works "
                    "for any word) or supply a custom .onnx to enable it.",
                    self._wake_phrase_label,
                )

        log.info(
            "Wake-Live-Switch: %s -> engine=%s keyword=%s (oww=%s whisper=%s)",
            prev,
            engine,
            getattr(plan, "oww_keyword", "?"),
            self._openwakeword_enabled,
            self._whisper_wake_enabled,
        )
        # Re-arm the running wake loop with the new detectors.
        self._wake_reload_event.set()

    def set_wake_activation(self, enabled: bool) -> None:
        """Enable or park always-on wake listening without restarting.

        The configured plan stays resident while disabled so hotkeys and the
        rest of the audio pipeline remain untouched. Enabling re-applies that
        plan, lazily preparing any detector it needs, and both transitions wake
        the parked/running wake loop through the existing reload event.
        """
        self._wake_word_enabled = bool(enabled) and _owns_ambient_duties()
        plan = getattr(self, "_wake_plan", None)
        if self._wake_word_enabled and plan is not None:
            self.set_wake_plan(plan)
            return

        self._openwakeword_enabled = False
        self._whisper_wake_enabled = False
        self._wake_reload_event.set()

    def set_keybinds(
        self,
        *,
        call: list[str] | None = None,
        hangup: list[str] | None = None,
        dictate: list[str] | None = None,
        dictate_toggle: list[str] | None = None,
        paste_last: list[str] | None = None,
    ) -> None:
        """Live-apply changed voice keybinds — no app/pipeline restart.

        Root cause of "I set a key and pressing it does nothing": the Call /
        Hangup / Talk combos are armed once at pipeline start (the
        ``async with HotkeyTrigger`` block), so a UI/toml save only reached the
        OS on the next boot. This updates the stored combos and flips
        ``_hotkey_reload_event`` so the running hotkey trigger re-arms in place.

        Mirrors the ``set_wake_plan`` live-apply contract: safe to call from the
        FastAPI handler thread — it shares the pipeline's event loop. Only the
        actions passed are changed; ``None`` leaves that action untouched.

        Every keyword here is spelled exactly like its entry in
        ``config_writer.KEYBIND_ACTIONS``: the settings route calls
        ``set_keybinds(**{action: [...]})``, so a keyword that drifts from the
        action string turns a successful save into a silent no-op — and a
        keyword that is MISSING turns it into a ``TypeError`` the route catches
        and reports as "applies on restart", which is worse: it is a promise
        nothing downstream keeps. Every action in ``KEYBIND_ACTIONS`` therefore
        needs a keyword here, and a binding in ``_build_hotkey_bindings``.
        """
        if call is not None:
            self._call_hotkeys = list(call)
        if hangup is not None:
            self._hangup_hotkeys = list(hangup)
        if dictate is not None:
            self._dictate_hotkeys = list(dictate)
        if dictate_toggle is not None:
            self._dictate_toggle_hotkeys = list(dictate_toggle)
        if paste_last is not None:
            self._paste_last_hotkeys = list(paste_last)
        log.info(
            "Keybinds live-switched: CALL=[%s] HANGUP=[%s] DICTATE=[%s] "
            "DICTATE-TOGGLE=[%s] PASTE-LAST=[%s]",
            ", ".join(self._call_hotkeys),
            ", ".join(self._hangup_hotkeys),
            ", ".join(self._dictate_hotkeys) or "off",
            ", ".join(self._dictate_toggle_hotkeys) or "off",
            ", ".join(getattr(self, "_paste_last_hotkeys", None) or []) or "off",
        )
        self._hotkey_reload_event.set()

    async def _hotkey_reload_loop(self, trigger: HotkeyTrigger) -> None:
        """Re-arm the live hotkey trigger whenever set_keybinds flips the event.

        Keeps the outer ``async with HotkeyTrigger`` (and the whole voice
        session) intact — only the OS registrations are swapped — so a keybind
        change applies without an app restart. A failed re-arm is contained
        inside ``HotkeyTrigger.rearm`` (degrade, never raise).
        """
        while True:
            await self._hotkey_reload_event.wait()
            self._hotkey_reload_event.clear()
            bindings, edge_events = self._build_hotkey_bindings()
            await trigger.rearm(bindings, push_to_talk=edge_events)

    def _build_hotkey_bindings(self) -> tuple[dict[str, list[str]], set[str]]:
        """The live binding table + the set of bindings wanting BOTH key edges.

        One producer for both arming sites (``run`` at start, ``_hotkey_reload_loop``
        on a live keybind change). They used to build this dict twice; a third
        action made that duplication a drift bug waiting to happen — a shortcut
        that works at boot but not after a Settings save, or the reverse.
        """
        edge_events: set[str] = set()
        if not _owns_ambient_duties():
            # Global hotkeys are the default app's; see __init__.
            return {"call": [], "hangup": []}, edge_events
        bindings: dict[str, list[str]] = {
            "call": list(self._call_hotkeys),
            "hangup": list(self._hangup_hotkeys),
        }
        if self._dictate_hotkeys:
            bindings["dictate"] = list(self._dictate_hotkeys)
            # Hold mode needs the release edge to know when to submit; toggle
            # mode deliberately gets the legacy single-fire-on-release contract
            # so holding the key does not start and stop repeatedly.
            if self._dictate_mode == "hold":
                edge_events.add("dictate")
        # ``getattr`` default: unit tests build pipelines via ``__new__`` and set
        # only the attributes they care about, a widely used pattern in this repo.
        dictate_toggle = getattr(self, "_dictate_toggle_hotkeys", None) or []
        if dictate_toggle:
            bindings["dictate_toggle"] = list(dictate_toggle)
            # Never an edge binding: the whole point of a toggle is one event
            # per press. Asking for both edges would start on the down edge and
            # stop again on the up edge, i.e. turn it back into push-to-talk.
        paste_last = getattr(self, "_paste_last_hotkeys", None) or []
        if paste_last:
            # Single-fire on release, like every non-hold action: holding the
            # key must paste once, not once per polling tick.
            bindings["paste_last"] = list(paste_last)
        return bindings, edge_events

    # ------------------------------------------------------------------
    # Bus / supervisor helpers — a no-op when nothing is configured
    # ------------------------------------------------------------------

    async def _transition(self, new_state: str) -> None:
        # This only DISPLAYS state, so nothing in it may end a call. A pipeline
        # assembled without a supervisor (headless, and every unit test that
        # builds one field by field) must still run the call to completion —
        # before this was defensive, adding one status update to the realtime
        # path aborted the whole session loop on a missing attribute.
        supervisor = getattr(self, "_supervisor", None)
        if supervisor is not None:
            try:
                await supervisor.set_state(new_state)
            except Exception as exc:  # noqa: BLE001
                log.warning("Supervisor-Transition zu %s fehlgeschlagen: %s", new_state, exc)
        # Permanent-Vision Privacy-Hook (Wave-2 B7): bei IDLE pausieren,
        # bei ACTIVE-Familie (LISTENING/THINKING/SPEAKING) resumen.
        try:
            self._maybe_toggle_vision_on_state(new_state)
        except Exception:  # noqa: BLE001
            log.debug(
                "Vision toggle for state %s skipped (pipeline without vision)",
                new_state,
                exc_info=True,
            )

    async def _set_turn_state(
        self,
        new_state: TurnTakingState,
        *,
        only_from: TurnTakingState | None = None,
    ) -> None:
        previous = getattr(self, "_turn_state", TurnTakingState.IDLE)
        # Conditional transition (``only_from``): apply ONLY when the state is
        # still the expected origin. Used by callbacks that may race a newer
        # state (a late VAD false-start endpoint must never yank the machine
        # out of JARVIS_SPEAKING).
        if only_from is not None and previous != only_from:
            return
        if previous != new_state:
            self._previous_turn_state = previous.value
            log.info("turn-state: %s -> %s", previous.value, new_state.value)
        # Jarvis just STOPPED speaking → the floor goes back to the user. Stamp it
        # so the idle loop can grant a fresh listening window even when the turn
        # ran off the main loop (delegation grace / completion timer) and left the
        # original idle window ticking (forensic 2026-06-27 08:49).
        if (
            previous == TurnTakingState.JARVIS_SPEAKING
            and new_state == TurnTakingState.LISTENING
        ):
            self._last_answer_floor_monotonic = time.monotonic()
        self._turn_state = new_state
        if new_state is TurnTakingState.LISTENING:
            self._schedule_delegation_results()
        if new_state is TurnTakingState.IDLE:
            for task_name in ("_agent_reply_retry_task", "_delegation_result_task"):
                retry = getattr(self, task_name, None)
                if retry is not None and retry is not asyncio.current_task():
                    retry.cancel()
                    await asyncio.gather(retry, return_exceptions=True)
        await self._transition(self._supervisor_state_for_turn(new_state))
        # Turn-boundary: the floor has cleared → flush any announcements that
        # were deferred while the user was speaking (AD-OE6 zero-silent-drop).
        # Replayed through ``_on_announcement`` so they re-run every guard
        # (hangup, mute, the now-passing floor check). Scheduled, not awaited,
        # so a deferred readback's playback never blocks the state machine.
        if (
            new_state in (TurnTakingState.LISTENING, TurnTakingState.IDLE)
            and getattr(self, "_deferred_announcements", None)
        ):
            pending = self._deferred_announcements
            self._deferred_announcements = []
            for event in pending:
                if new_state is TurnTakingState.IDLE and self._is_agent_reply(event):
                    self._defer_agent_reply(event)
                    continue
                asyncio.create_task(
                    self._on_announcement(event), name="deferred-announcement"
                )

    def _assistant_work_in_flight(self) -> bool:
        """Owned off-loop work keeps idle expiry from closing a busy session."""
        return bool(getattr(self, "_assistant_work_count", 0))

    def _termination_snapshot(self, reason: str) -> dict[str, Any]:
        """Bounded diagnostics, without user text, collected before teardown."""
        from dodaios.harness.computer_use_context import cu_mission_active

        continuing = getattr(self, "_continue_listening_after_response", None)
        state = getattr(self, "_turn_state", None)
        detail = dict(getattr(self, "_termination_detail", {}))
        detail.update({
            "hangup_reason": reason,
            "producer": getattr(self, "_termination_producer", "")
            or "speech.pipeline._state_loop.finalize",
            "continue_listening_after_response": continuing,
            "single_turn_mode": None if continuing is None else not continuing,
            "idle_timeout_s": (
                getattr(self, "_idle_timeout_s", None)
                if getattr(self, "_idle_hangup_enabled", True) else 0
            ),
            "idle_deadline_monotonic": getattr(self, "_idle_deadline_monotonic", None),
            "last_activity_monotonic": getattr(self, "_last_user_activity_monotonic", None),
            "last_answer_floor_monotonic": getattr(self, "_last_answer_floor_monotonic", None),
            "turn_state": getattr(state, "value", None),
            "previous_turn_state": getattr(self, "_previous_turn_state", None),
            "assistant_work_active": self._assistant_work_in_flight(),
            "tool_active": None,
            "screen_active": None,
            "computer_use_active": cu_mission_active(),
        })
        return detail

    @staticmethod
    def _supervisor_state_for_turn(state: TurnTakingState) -> str:
        if state == TurnTakingState.IDLE:
            return "IDLE"
        if state in (
            TurnTakingState.LISTENING,
            TurnTakingState.USER_SPEAKING,
            TurnTakingState.WAITING_FOR_FINAL_TRANSCRIPT,
        ):
            return "LISTENING"
        if state == TurnTakingState.PROCESSING:
            return "THINKING"
        if state == TurnTakingState.JARVIS_SPEAKING:
            return "SPEAKING"
        return "IDLE"


# ----------------------------------------------------------------------
# CLI-Entry
# ----------------------------------------------------------------------

def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and not os.environ.get(k):
            os.environ[k] = v


async def _main() -> None:
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    )
    _load_env()

    from dodaios.core import config as cfg
    config = cfg.load_config()

    stt = FasterWhisperProvider(
        model=config.stt.model,
        device=config.stt.device,
        compute_type=config.stt.compute_type,
        language=config.stt.language if config.stt.language != "auto" else None,
    )
    from dodaios.plugins.tts import build_tts_from_config
    tts = build_tts_from_config(config.tts)
    # The env override stays available for quick CLI tests.
    env_voice = os.environ.get("JARVIS_TTS_VOICE")
    if env_voice and hasattr(tts, "_default_voice"):
        tts._default_voice = env_voice
    from dodaios.brain.factory import build_default_brain
    brain = build_default_brain()

    pipeline = SpeechPipeline(
        call_hotkeys=config.trigger.resolve_hotkeys(),
        dictate_hotkeys=(
            (config.trigger.hotkey_dictate,)
            if config.trigger.hotkey_dictate.strip()
            else ()
        ),
        dictate_toggle_hotkeys=(
            (config.trigger.hotkey_dictate_toggle,)
            if config.trigger.hotkey_dictate_toggle.strip()
            else ()
        ),
        paste_last_hotkeys=(
            (config.trigger.hotkey_paste_last,)
            if config.trigger.hotkey_paste_last.strip()
            else ()
        ),
        dictate_mode=config.dictation.mode,
        dictation_config=config.dictation,
        hangup_hotkeys=(
            (config.trigger.hotkey_hangup,)
            if config.trigger.hotkey_hangup.strip()
            else ()
        ),
        wake_keywords=(),
        wake_threshold=0.15,
        stt=stt,
        tts=tts,
        brain_callback=brain,
        enable_whisper_wake=True,
        # Mirror the production wiring (desktop_app / watchdog): the config
        # field is canonical; without this line the constructor default
        # (False) silently overrides the shipped conversation-mode default.
        continue_listening_after_response=not config.trigger.single_turn_mode,
        idle_timeout_s=config.trigger.session_idle_timeout_s,
        input_device=config.audio.input_device or None,
        output_device=config.audio.output_device or None,
    )
    print()
    print("=" * 64)
    print("  Dodaios — Speech pipeline")
    print("=" * 64)
    print("  CALL    :  say your wake word           |  Ctrl+RightAlt+J  |  F3+F4")
    # i18n-allow: quoted German hang-up trigger phrase
    print("  HANG UP :  say 'auflegen'               |  F1+F2")
    print("  QUIT    :  Ctrl+C in the terminal")
    print()
    print("  When Dodaios hears you: chime + a short spoken ack back.")
    print("  The live score log shows whether the wake word triggers.")
    print("=" * 64)
    print()
    await pipeline.run()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nBeendet.")
