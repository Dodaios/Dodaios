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


class SpeechPipeline:
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

    def _select_probe_stt(self, utterance: Any) -> Any:
        """Use a separate wake engine or a concurrency-safe final provider."""
        wake = getattr(self, "_stt", None)
        candidate = wake if wake is not None else utterance
        if candidate is utterance and not getattr(
            candidate, "supports_concurrent_transcription", True
        ):
            # Cancelling an async preview does not stop its native worker.
            # A local final decode must never compete with that same engine.
            return None
        from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

        return wrap_stt_with_dictionary(candidate)

    def _vision_cfg(self) -> Any:
        """Liefert RouterVisionConfig oder None (tolerant zu fehlender Config)."""
        cfg = self._config
        if cfg is None:
            return None
        return getattr(getattr(getattr(cfg, "brain", None), "router", None), "vision", None)

    def _maybe_toggle_vision_on_state(self, new_state: str) -> None:
        """Pausiert/resumed den VisionContextProvider anhand Pipeline-State.

        No-op wenn kein Provider injected oder pause_on_idle=False.
        """
        if self._vision_provider is None:
            return
        vcfg = self._vision_cfg()
        pause_on_idle = getattr(vcfg, "pause_on_idle", True) if vcfg is not None else True
        if not pause_on_idle:
            return
        if new_state == "IDLE":
            try:
                self._vision_provider.pause()
            except Exception as exc:  # noqa: BLE001
                log.warning("Vision-pause() bei IDLE fehlgeschlagen: %s", exc)
        elif new_state in ("LISTENING", "THINKING", "SPEAKING"):
            try:
                self._vision_provider.resume()
            except Exception as exc:  # noqa: BLE001
                log.warning("Vision-resume() bei %s fehlgeschlagen: %s", new_state, exc)

    def _background_capture_allowed(self) -> bool:
        """Silent gate for BACKGROUND capture (wake word, barge-in): a live grant only.

        Never asks the OS and never opens the device. An undecided microphone is
        closed here because nothing the user did is waiting on it: the wake loop
        parks and a gesture elsewhere asks. Does not apply Jarvis mute.
        """
        gate = getattr(self, "_activation_gate", None)
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception as exc:  # noqa: BLE001
            log.warning("Voice capture permission gate failed closed: %s", exc)
            return False

    def _user_capture_allowed(self) -> bool:
        """Silent gate for USER-started capture (push-to-talk, voice session, dictation).

        True unless the microphone is denied, restricted or unavailable: an
        undecided microphone is usable because the gesture itself asks (see
        ``_ensure_microphone``). Never asks and never opens the device.
        """
        gate = getattr(self, "_user_activation_gate", None)
        if gate is None:
            return True
        try:
            return bool(gate())
        except Exception as exc:  # noqa: BLE001
            log.warning("Voice user-capture permission gate failed closed: %s", exc)
            return False

    def _permission_service(self) -> Any:
        """The injected ``PermissionGate``, else the process service (resolved per call)."""
        gate = getattr(self, "_permission_gate", None)
        if gate is not None:
            return gate
        from dodaios.platform.permission_service import get_permission_service

        return get_permission_service()

    def _ensure_microphone(self, feature: str) -> str | None:
        """THE ask of a voice gesture: ``ensure(MICROPHONE, wait_s=0)``.

        Returns ``None`` when the microphone is granted (or this is not a TCC
        platform), else a finished English sentence saying why not. ``wait_s=0``
        is the loop-safe form: a first press may make macOS show its dialog and
        returns PENDING at once, so the press that raised the dialog is NOT
        started retroactively (the UI says "allowed - press again"). The service
        publishes the ``PermissionNeeded`` episode itself, a denial included.
        Never raises; a failed read refuses.
        """
        try:
            result = self._permission_service().ensure(
                "microphone", feature=feature, interactive=True, wait_s=0.0
            )
        except Exception:  # noqa: BLE001 - an unreadable permission must not start the capture
            log.warning("The microphone permission check for %s failed.", feature, exc_info=True)
            return _MICROPHONE_REFUSED_SENTENCE
        if result.granted:
            return None
        return str(result.user_detail or "") or _MICROPHONE_REFUSED_SENTENCE

    async def _on_permission_resolved(self, event: PermissionResolved) -> None:
        """A microphone grant wakes a wake loop that is parked on the permission.

        Runs on the loop (bus dispatch), so setting the asyncio event is safe. A
        resolution while the loop is not parked changes nothing: a wake capture
        that is already running must not be torn down by a dictation's grant.
        """
        if not event.granted or "microphone" not in event.permissions:
            return
        if getattr(self, "_wake_parked_on_permission", False):
            self._wake_reload_event.set()

    def _dictation_blocks_activation(self) -> bool:
        """True while a running dictation must keep the wake word silent.

        The maintainer's contract: a dictation turn owns the microphone, so the
        words being dictated must never trip the wake word (and two native input
        streams must never race for the same device — BUG-014 / AP-24).

        This is a STATE gate, not the content gate AP-27 forbids: it asks
        whether an application task is alive, with zero reference to audio or to
        any transcript, exactly like the three gates it sits beside
        (``_wake_lock_until``, mute, ``_state != IDLE``). It changes WHEN wake is
        listened to, never HOW a candidate is judged.

        Two independent things must BOTH hold for wake to stay blocked:

        1. A dictation task is alive — either the recording itself
           (``_dictation_task``) or the handover that is ending a voice
           conversation to get the microphone for one
           (``_dictation_handover_task``). Derived from ``task.done()``, never a
           bare bool somebody has to remember to clear — a crashed, cancelled or
           returned task is ``done()``, so the block lifts by itself.
        2. The watchdog deadline has not passed. ``_dictation_wake_block_until``
           is a timestamp set at start, mirroring ``_wake_lock_until``. A task
           that somehow hangs forever therefore still cannot deafen the wake
           word beyond it.

        The handover half matters as much as the recording half: ending the
        conversation returns the pipeline to IDLE with the wake loop free to
        re-arm, and a wake word firing in that gap would take the microphone
        straight back from the user who just pressed the dictation key.

        All defaults fail OPEN (no task → False, missing deadline → 0.0 →
        False), because the failure this guards against is BUG-037: permanently
        deaf with no visible cause and only a restart to fix.
        """
        task = getattr(self, "_dictation_task", None)
        if task is None or task.done():
            task = getattr(self, "_dictation_handover_task", None)
        if task is None or task.done():
            return False
        return time.time() < float(getattr(self, "_dictation_wake_block_until", 0.0))

    def _activation_state_allows(self) -> bool:
        """The non-permission half of the gate: mute, a running dictation, mic ownership.

        Split out so a gesture entry point can refuse for these reasons BEFORE it
        asks the OS for anything (a muted press must not raise a macOS dialog), and
        so the wake loop can tell "waiting on the permission" from "waiting on the
        state" and park only for the first.
        """
        if getattr(self, "_muted", False):
            return False
        if self._dictation_blocks_activation():
            return False
        from dodaios.live.runtime import owns_microphone

        return not owns_microphone(
            except_session_id=getattr(self, "_current_voice_session_id", None)
        )

    def _activation_block_reason(
        self, *, explicit: bool = False, include_permission: bool = True
    ) -> str:
        """The honest English reason ``_activation_allowed`` is saying no.

        One source for every log line that reports the closed gate. It exists
        because those lines used to hardcode two guesses ("muted" /
        "window not visible?"), and the wrong guess once misled a live freeze
        diagnosis. Returns an empty string when the gate is open. ``explicit``
        selects the user-gesture permission predicate, as in ``_activation_allowed``.
        ``include_permission=False`` names only the state half (a gesture entry
        point that refused on the state alone and must not report the microphone).
        """
        if getattr(self, "_muted", False):
            return "voice is muted"
        if self._dictation_blocks_activation():
            return "a dictation is running"
        if not include_permission:
            return ""
        permitted = self._user_capture_allowed() if explicit else self._background_capture_allowed()
        if not permitted:
            return (
                "microphone access is not granted"
                if not explicit
                else "microphone access is denied or unavailable"
            )
        return ""

    def _activation_allowed(self) -> bool:
        """True when external UI/lifecycle state permits BACKGROUND voice activation.

        While muted (mascot doubleClick → ``_muted=True``) we always
        return False so the wake-loop ignores every detection. The loop
        keeps spinning; unmuting is one bool flip away.

        A running dictation closes the same gate (``_dictation_blocks_activation``)
        — one edit reaches all three wake gates (loop entry, pre-emit, state
        loop) plus the push-to-talk and ``request_voice_session`` entry points,
        because the state half of this predicate is shared with all of them
        (``_activation_state_allows``).

        The permission half is ``_background_capture_allowed``: a live microphone
        GRANT. A deliberate user action (the call key, push-to-talk, the speak
        button) uses ``_gesture_activation_allowed`` instead, which only needs the
        microphone not to be refused, because the gesture is what asks the OS.
        Neither ever asks from here.

        ``getattr`` defaults to False for pipelines constructed via
        ``__new__`` (used by privacy/vision unit tests that bypass
        ``__init__``) — those instances are never muted by definition.

        NB: ``dictation_available`` / ``start_dictation`` deliberately do NOT
        consult this predicate. Routing them through here would make a
        dictation forbid its own successor.
        """
        return self._activation_state_allows() and self._background_capture_allowed()

    def _gesture_activation_allowed(self) -> bool:
        """``_activation_allowed`` for a deliberate user action (key, button, bar click).

        Same state half (mute, a running dictation, mic ownership); the permission
        half is ``_user_capture_allowed``: true unless the microphone is denied,
        restricted or unavailable. The wake word is NOT such an action and never
        passes through here.
        """
        return self._activation_state_allows() and self._user_capture_allowed()

    @property
    def is_muted(self) -> bool:
        """Snapshot of the global voice mute flag.

        Public so tests and the REST surface can read the live value
        without going through the bus.
        """
        return self._muted

    async def toggle_mute(self, source: str = "") -> bool:
        """Flip the microphone mute for the assistant and return the new value.

        The REST twin of publishing ``VoiceMuteToggleRequested``: the same
        handler flips it and broadcasts ``VoiceMuteChanged``, so a running
        call (``live/session.py``) and every other mirror follow.
        """
        from dodaios.core.events import VoiceMuteToggleRequested

        await self._on_mute_toggle_requested(VoiceMuteToggleRequested(source=source))
        return self._muted

    async def _on_mute_toggle_requested(
        self, event: VoiceMuteToggleRequested
    ) -> None:
        """Flip the mute flag and broadcast the authoritative state.

        Idempotent toggle: callers do not have to know the current state.
        We log the change at INFO so the live log carries an audit trail.
        """
        new_value = not self._muted
        self._muted = new_value
        log.info(
            "🔇 Voice mute %s (source=%s)",
            "ENABLED" if new_value else "disabled",
            event.source or "unknown",
        )
        # Mute is INPUT-ONLY (maintainer intent 2026-06-29: "mute my mic FOR
        # Jarvis, do NOT mute Jarvis — other things keep working"). We deliberately
        # do NOT call self._player.stop() here: that ran Pa_AbortStream
        # (stream.abort) mid-TTS-write, which (a) contradicted the input-only
        # intent and (b) wedged the shared WASAPI device — the next wake-mic then
        # opened "successfully" but delivered only dead/silent frames (no
        # rolling-whisper, no 3 s Mic-Stall fire), so "Hey <wake>" silently
        # stopped working after a mute-during-speech + hangup. Jarvis finishes the
        # current sentence; new _speak() calls are still suppressed while muted,
        # and the user's input frames are dropped at our boundary — the OS mic is
        # untouched. Forensic: data/jarvis_desktop.log 2026-06-29 14:09–14:12.
        if self._bus is None:
            return
        try:
            await self._bus.publish(
                VoiceMuteChanged(muted=new_value, source=event.source)
            )
        except Exception:  # noqa: BLE001
            log.exception("VoiceMuteChanged publish failed")

    async def _on_prompt_mode_pause_toggle_requested(
        self, event: DictationPromptModePauseToggleRequested
    ) -> None:
        """Pause or resume Prompt Mode and broadcast the new state.

        Idempotent like the mute toggle: the caller does not know the current
        state. Deliberately NOT a settings write — the value in jarvis.toml is
        left alone, so the settings card keeps showing the switch on and one
        more click on the bar brings the rewriting back.
        """
        from dodaios.dictation.prompt_mode_switch import toggle_prompt_mode_pause

        await toggle_prompt_mode_pause(
            cfg=getattr(self, "_dictation_cfg", None),
            bus=self._bus,
            source=event.source or "unknown",
        )

    async def _emit_wake(self, keyword: str, confidence: float = 0.0) -> None:
        self._wake_detected_monotonic = time.monotonic()
        self._last_wake_keyword = keyword
        if self._bus is not None:
            try:
                await self._bus.publish(
                    WakeWordDetected(
                        source_layer="speech",
                        keyword=keyword,
                        confidence=confidence,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("WakeWordDetected publish failed: %s", exc)

    async def _publish_event(self, event: Any) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish(event)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s publish failed: %s", type(event).__name__, exc)

    def _publish_event_soon(self, event: Any) -> None:
        """Publish from SYNCHRONOUS code without blocking the caller.

        ``start_dictation`` and the dictation teardown both have to announce
        themselves from places that cannot ``await``: a plain method, and a
        ``finally`` in a task that may already be cancelled. Scheduling the
        publish as its own task keeps both honest — a cancelled dictation still
        gets its terminal event out, and a broken subscriber can never propagate
        back into the caller (AP-18).

        A missing bus or a missing loop is a clean no-op: unit tests build
        pipelines via ``__new__`` and must not need an event bus to exercise the
        dictation lane.
        """
        if getattr(self, "_bus", None) is None:
            return

        def _spawn(loop: asyncio.AbstractEventLoop) -> None:
            # Hold a strong reference until the publish finishes: the event loop
            # only keeps a weak one, so a fire-and-forget task can be collected
            # mid-flight and the event would simply vanish.
            pending = getattr(self, "_detached_publishes", None)
            if pending is None:
                pending = set()
                self._detached_publishes = pending
            task = loop.create_task(self._publish_event(event))
            pending.add(task)
            task.add_done_callback(pending.discard)

        try:
            _spawn(asyncio.get_running_loop())
            return
        except RuntimeError:
            pass
        owner = getattr(self, "_runtime_loop", None)
        if owner is None or not owner.is_running():
            log.debug("%s not published: no running loop.", type(event).__name__)
            return
        try:
            owner.call_soon_threadsafe(_spawn, owner)
        except RuntimeError as exc:
            log.debug("%s publish scheduling failed: %s", type(event).__name__, exc)

    # ------------------------------------------------------------------
    # Skills-Brain-Integration: Phase Skills-1
    # ------------------------------------------------------------------

    @staticmethod
    def _is_agent_reply(event: AnnouncementRequested) -> bool:
        """A readback that is owed to the user but must wait for an open call.

        An agent's reply, and every piece of background news nobody asked for
        in this conversation (a routine or automation result, a scheduled job
        failing or recovering). Spoken into an idle machine it is Jarvis
        talking without having been called; held here, it is delivered at the
        next call, once, and only after the audio actually finished.
        """
        return event.source_layer in _HELD_FOR_CALL_SOURCES and event.kind in _READBACK_KINDS

    @staticmethod
    def _live_call() -> Any | None:
        """The browser or native live call that owns the voice right now.

        Such a call runs beside this pipeline (``dodaios.live``): the pipeline
        never sees its turns, and its handle is not ``_active_realtime_handle``.
        Owed agent replies and readbacks still have to reach it (live
        2026-10-02: Scout's report waited in silence for the whole call).
        """
        from dodaios.live.runtime import active

        return next(
            (
                session
                for session in active()
                if getattr(session, "is_active", False)
                and SpeechPipeline._is_side_call(session)
            ),
            None,
        )

    @staticmethod
    def _is_side_call(session: Any) -> bool:
        """A live call this pipeline does not drive itself.

        A desktop realtime call (``surface="desktop"``) is driven by
        ``_active_realtime_session``, which settles its replies on
        ``turn_complete``; only browser/native calls need the pause signals.
        """
        return getattr(session, "surface", "browser") != "desktop"

    def _realtime_voice_handle(self) -> Any | None:
        """The duplex session that speaks for Jarvis now, desktop or live call."""
        handle = getattr(self, "_active_realtime_handle", None)
        if handle is not None:
            return handle
        return self._live_call()

    def _agent_reply_floor_open(self) -> bool:
        """Whether an owed reply may start now without talking over anyone."""
        live = self._live_call()
        if live is not None:
            return bool(getattr(live, "ready_for_report", True))
        return getattr(self, "_turn_state", TurnTakingState.IDLE) is TurnTakingState.LISTENING

    def _agent_reply_needs_session(self) -> bool:
        if self._live_call() is not None:
            # A live call is an open, available session of its own; its
            # pauses decide the timing (``_agent_reply_floor_open``).
            return bool(getattr(self, "_muted", False))
        hangup = getattr(self, "_hangup_event", None)
        return bool(
            getattr(self, "_muted", False)
            or (hangup is not None and hangup.is_set())
            or getattr(self, "_turn_state", TurnTakingState.IDLE) is TurnTakingState.IDLE
            or getattr(self, "_voice_engine_transitioning", False)
        )

    def _defer_agent_reply(self, event: AnnouncementRequested) -> None:
        pending = getattr(self, "_deferred_announcements", None)
        if pending is None:
            pending = self._deferred_announcements = []
        if event not in pending:
            pending.append(event)

    def _settle_agent_reply(self, *, completed: bool) -> None:
        """Only a drained speaker queue confirms a realtime agent readback."""
        event = getattr(self, "_agent_reply_inflight", None)
        self._agent_reply_inflight = None
        self._agent_reply_inflight_text = ""
        self._agent_reply_inflight_session = None
        if event is not None and not completed:
            retries = getattr(self, "_agent_reply_retries", None)
            if retries is None:
                retries = self._agent_reply_retries = []
            if event not in retries:
                retries.append(event)
            log.info("Agent reply interrupted; retained for the next voice session")

    def _restore_agent_replies(self) -> None:
        """Rejoin the existing floor-aware queue when a new call starts."""
        for event in getattr(self, "_agent_reply_retries", []):
            self._defer_agent_reply(event)
        self._agent_reply_retries = []
        pending = getattr(self, "_deferred_announcements", None)
        if pending:
            pending.sort(key=lambda event: event.timestamp_ns)

    def live_call_paused(self, session: Any) -> None:
        """Consume the receipt on the call's loop, then settle on the pipeline loop."""
        if not self._is_side_call(session):
            return
        take = getattr(session, "take_report_outcome", None)
        outcome = take() if callable(take) else ""
        self._call_on_runtime_loop(self._on_live_call_boundary, session, outcome, False)

    def live_call_ended(self, session: Any) -> None:
        if not self._is_side_call(session):
            return
        take = getattr(session, "take_report_outcome", None)
        outcome = take() if callable(take) else ""
        self._call_on_runtime_loop(self._on_live_call_boundary, session, outcome, True)

    def _call_on_runtime_loop(self, callback: Any, *args: Any) -> None:
        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None  # A native callback may arrive without an event loop.
        if owner is not None and owner.is_running() and current is not owner:
            owner.call_soon_threadsafe(callback, *args)
        elif current is not None:
            callback(*args)

    def _on_live_call_boundary(self, session: Any, outcome: str, ended: bool) -> None:
        current_live = session is self._live_call()
        session_id = str(getattr(session, "session_id", ""))
        if (
            not ended and current_live
            and getattr(self, "_live_replies_restored_for", None) != session_id
        ):
            # Restore earlier calls before settling this call's failed report;
            # that fresh failure must not immediately restart inference here.
            self._live_replies_restored_for = session_id
            self._restore_agent_replies()
        if getattr(self, "_agent_reply_inflight_session", None) is session:
            if outcome in {"completed", "failed"} or ended:
                # A failed/cancelled/unfinished report stays owed to the next
                # call. Never loop through inference merely because audio failed.
                self._settle_agent_reply(completed=outcome == "completed")
        if ended:
            return
        if not current_live:
            return
        self._schedule_delegation_results()
        if getattr(self, "_deferred_announcements", None):
            self._retry_agent_reply_after_boundary()

    def _requeue_unvoiced_reply(self, event: AnnouncementRequested) -> None:
        """A reply the live model never started stays first in line.

        Bounded per reply: a call that keeps ignoring it hands it to the next
        call instead of retrying forever. The chat notice holds it either way.
        """
        attempts = getattr(self, "_agent_reply_attempts", None)
        if attempts is None:
            attempts = self._agent_reply_attempts = {}
        key = (event.source_layer, event.trace_id, event.detail)
        attempts[key] = attempts.get(key, 0) + 1
        if attempts[key] >= _LIVE_REPLY_MAX_ATTEMPTS:
            attempts.pop(key, None)
            retries = getattr(self, "_agent_reply_retries", None)
            if retries is None:
                retries = self._agent_reply_retries = []
            if event not in retries:
                retries.append(event)
            log.warning("Agent reply was not voiced by the live call; retained for the next call")
            return
        pending = getattr(self, "_deferred_announcements", None)
        if pending is None:
            pending = self._deferred_announcements = []
        if event not in pending:
            pending.insert(0, event)
        log.info("Agent reply was not voiced yet; offering it again at the next pause")

    def _retry_agent_reply_after_boundary(self) -> None:
        """Let the live wrapper finish resetting after the speaker drains."""
        previous = getattr(self, "_agent_reply_retry_task", None)
        if previous is not None and not previous.done():
            return
        if self._agent_reply_needs_session():
            return
        self._agent_reply_retry_task = asyncio.create_task(
            self._retry_pending_agent_replies(), name="agent-reply-boundary"
        )

    async def _retry_pending_agent_replies(self) -> None:
        while True:
            # No provider request is made while its wrapper reports busy.
            # This closes the gap between the desktop's LISTENING callback
            # and the provider wrapper clearing its completed turn state.
            await asyncio.sleep(0.1)
            if (
                self._agent_reply_needs_session()
                or not self._agent_reply_floor_open()
                or getattr(self, "_agent_reply_inflight", None) is not None
            ):
                return
            # A live call has no turn boundary this pipeline sees, so its
            # parked completion readbacks are offered at the same pauses.
            live = self._live_call() is not None
            event = next((event for event in self._deferred_announcements
                          if self._is_agent_reply(event)
                          or (live and event.kind in _READBACK_KINDS)), None)
            if event is None:
                return
            self._deferred_announcements.remove(event)
            try:
                await self._on_announcement(event)
            except asyncio.CancelledError:
                self._defer_agent_reply(event)
                raise
            except Exception:
                self._defer_agent_reply(event)
                log.warning("Agent reply retry failed; retained for a later turn", exc_info=True)
                return
            if live and event in self._deferred_announcements:
                # The live call refused it although it reported a pause (a
                # failed send). Count it and wait for the next pause instead
                # of retrying ten times a second.
                self._deferred_announcements.remove(event)
                self._requeue_unvoiced_reply(event)
                return

    async def _on_announcement(
        self, event: AnnouncementRequested, *, cancel_heartbeats: bool = True
    ) -> None:
        """Deliver a readback through the live voice or the classic TTS path.

        Agent replies wait for an open call. Interrupt-priority announcements
        retain the existing player-stop behavior. Classic playback uses
        synthesize() and play_chunks(), the same path as ordinary answers,
        and only inside an open voice session. ``cancel_heartbeats=False``
        lets a caller that already retired its own spawn watchdog keep the
        other missions' heartbeats alive.
        """
        event_kind = getattr(event, "kind", None)
        is_readback = event_kind in _READBACK_KINDS
        is_agent_reply = self._is_agent_reply(event)
        if is_readback:
            # Muting controls audio, not conversational memory. A mission that
            # finishes while muted must still be available to the next follow-up.
            session = getattr(self, "_active_realtime_handle", None)
            remember = getattr(session, "remember_announcement_context", None)
            if callable(remember):
                try:
                    # The full report too, so "what exactly did it change?"
                    # can be answered on the next turn.
                    report = str(getattr(event, "report", None) or "").strip()
                    remember(
                        text=event.text,
                        spoken_kind=event_kind,
                        detail=getattr(event, "detail", None),
                        **({"report": report} if report else {}),
                    )
                except Exception:  # noqa: BLE001 -- memory mirror is best-effort
                    log.debug(
                        "Realtime announcement context mirror failed",
                        exc_info=True,
                    )
        from dodaios.core.delegation import RESULT_SOURCES, ResultInbox

        if event.source_layer in RESULT_SOURCES:
            inbox = getattr(self, "_delegation_inbox", None)
            if inbox is None:
                inbox = self._delegation_inbox = ResultInbox()
            inbox.add(event)
            self._schedule_delegation_results()
            return
        if is_agent_reply:
            if event == getattr(self, "_agent_reply_inflight", None):
                return
            if (
                event.source_layer == "delegation.batch"
                and not self._agent_reply_floor_open()
            ):
                self._defer_agent_reply(event)
                return
            if self._agent_reply_needs_session():
                self._defer_agent_reply(event)
                log.info("Agent reply retained until an unmuted voice session is available")
                return
        if getattr(self, "_muted", False):
            log.debug("Announcement suppressed — voice muted: %r", event.text)
            return
        # Hangup-Gate: once "auflegen" fired, queued/late announcements
        # (Flash-Brain preamble, spawn-watchdog, late background readback)
        # must not punch through. The gate clears at the start of the next
        # session in `_state_loop` (line ~1726).
        hangup = getattr(self, "_hangup_event", None)
        # A readback (kind in _READBACK_KINDS — "completion" or "subagent") is a
        # FRESH turn delivering the answer the user asked for — an offloaded
        # background mission/sub-agent that finished after "auflegen" — so it must
        # punch through the hangup gate (AD-OE5/OE6 zero-silent-drop). A stale
        # preamble / untagged late announcement stays dropped. Live bug
        # 2026-06-14: a heavy research mission's result was silently dropped
        # because the user hung up 13 s after the optimistic ACK.
        # Since 2026-10-05 a readback passes this gate only to reach a live
        # call that is still open; the classic-voice gate further down keeps
        # it silent once no voice session is open.
        if hangup is not None and hangup.is_set() and not is_readback:
            log.info(
                "Announcement nach Hangup unterdrückt: %r", event.text[:80]
            )
            return
        # A completion / sub-agent readback IS the mission's answer — cancel any
        # pending "still on it" heartbeats so a reassurance never lands AFTER the
        # result (the success path does not publish JarvisAgentBackgroundCompleted,
        # so the heartbeat is not otherwise drained on completion). 2026-06-19.
        if is_readback and cancel_heartbeats:
            self._cancel_spawn_heartbeats()
        log.info(
            "📢 Announcement: %r (prio=%s lang=%s)",
            event.text, event.priority, event.language,
        )
        # When the Pre-Thinking-Ack Flash-Brain is wired in, the legacy
        # per-tool template emitter on `brain.router.ack` would double-speak:
        # the Flash-Brain already published its preamble on
        # `brain.ack_brain`, and the router's `generate_ack(tool_name, ...)`
        # callback would fire afterwards on the same utterance. Silently
        # drop the legacy source while the Flash-Brain is active so the user
        # only hears one ack per turn.
        if (
            getattr(self, "_ack_brain", None) is not None
            and getattr(event, "source_layer", None) == "brain.router.ack"
        ):
            log.debug(
                "Skipping legacy router-ack announcement %r — Flash-Brain active.",
                event.text,
            )
            return
        is_preamble = event_kind == "preamble"
        is_progress = event_kind == "progress"
        # 2026-05-26 cross-surface voice incoherence guard. After an
        # interrupt-priority announcement (typically a MissionFailed
        # readback) the user has just heard a terminal statement; a
        # follow-up "preamble" from any subscriber (Flash-Brain or
        # skill announcement) lands as an incoherent
        # second sentence — see diagnosis README. Suppress preambles
        # inside the configured quiet window.
        if is_preamble and self._last_interrupt_announcement_ts is not None:
            ack_cfg = (
                getattr(self._config, "ack_brain", None)
                if self._config is not None
                else None
            )
            quiet_ms = getattr(
                ack_cfg, "suppress_preamble_after_interrupt_ms", 5000
            )
            if quiet_ms > 0:
                elapsed = time.monotonic() - self._last_interrupt_announcement_ts
                if elapsed * 1000.0 < quiet_ms:
                    log.info(
                        "Preamble announcement suppressed — within %d ms "
                        "post-interrupt quiet window (elapsed=%.0f ms): %r",
                        quiet_ms, elapsed * 1000.0, event.text[:80],
                    )
                    return
        # Symmetric turn-boundary guard (AD-OE5) + idle guard (live bug 2026-07-01).
        # A background "still on it" heartbeat (kind="progress") is only meaningful
        # while the user is ACTIVELY in a session waiting for the mission — the mic
        # is open and Jarvis is LISTENING. It is dropped in every other state:
        # during a foreground turn (THINKING/JARVIS_SPEAKING/…) it would talk over
        # that turn, and while IDLE there is NO active session at all, so speaking
        # it is Jarvis "talking out of nowhere" into a machine the user walked away
        # from (live bug 2026-07-01: a force-spawned mission's three bounded beats
        # spoke into fresh, empty wake sessions after the user hung up). An
        # interrupt is a deliberate barge and still punches through.
        current_turn_state = (
            TurnTakingState.LISTENING if self._live_call() is not None
            else getattr(self, "_turn_state", TurnTakingState.IDLE)
        )
        if (
            event.priority != "interrupt"
            and is_progress
            and current_turn_state is not TurnTakingState.LISTENING
        ):
            log.info(
                "Progress announcement dropped — no active listening session (%s): %r",
                getattr(current_turn_state, "value", current_turn_state),
                event.text[:80],
            )
            return
        if event.priority != "interrupt" and (
            current_turn_state in _USER_HOLDS_FLOOR_STATES
        ):
            # A preamble or a "still on it" heartbeat (kind="progress") is only
            # meaningful in the moment — once the user holds the floor it is
            # stale, so DROP it (never defer/replay it after the user finishes or
            # after the mission answer; events.py: progress = "droppable when
            # stale"). Completion/readback below owes the user information and is
            # deferred instead.
            if is_preamble or is_progress:
                log.info(
                    "Announcement dropped — user holds the floor (%s): %r",
                    event_kind or "normal",
                    event.text[:80],
                )
                return
            # Completion/readback owes the user information → park it and flush
            # at the next turn-boundary (AD-OE6 zero-silent-drop).
            if is_agent_reply:
                self._defer_agent_reply(event)
            else:
                self._deferred_announcements.append(event)
            log.info(
                "Announcement deferred — user holds the floor: %r",
                event.text[:80],
            )
            return
        # A preamble ("I'm about to think about this") is only coherent BEFORE
        # the answer is voiced. If the turn is already JARVIS_SPEAKING by the
        # time it reaches the handler, the answer (or another readback) is being
        # spoken right now, so the preamble is stale → drop it instead of
        # queueing it behind the answer on the shared player (live bug
        # 2026-06-20: the ack "Ich schaue mir jetzt …" played AFTER the tool
        # result). The floor guard above only covers the USER holding the floor;
        # this covers Jarvis already speaking. The remaining race — the answer
        # starting DURING the preamble's synthesis / play-lock wait — is caught
        # by the should_play predicate handed to play_chunks below.
        if is_preamble and (
            getattr(self, "_turn_state", TurnTakingState.IDLE)
            is TurnTakingState.JARVIS_SPEAKING
        ):
            log.info(
                "Preamble dropped — the assistant is already speaking the answer: %r",
                event.text[:80],
            )
            return
        # Usefulness gate (2026-07-06 interim-ack redesign): the grounded
        # router ack publishes the instant a tool is SELECTED — too early to
        # know whether the bridge is even needed. When the voice turn is
        # currently PROCESSING, hold the ack for the commit grace and only
        # speak it if the brain is STILL busy afterwards (same AD-OE5 helper
        # the Flash-Brain streaming path uses); a turn that answers within
        # the grace stays ack-free. Announcements arriving with no voice turn
        # in flight (chat path) keep legacy behavior.
        source_layer = getattr(event, "source_layer", None)
        is_instant_ack = bool(
            is_preamble and source_layer == self._INSTANT_ACK_SOURCE_LAYER
        )
        if (
            is_preamble
            and source_layer == "brain.router.ack"
            and self._interim_line_spoke_recently(PROGRESS_AFTER_S)
        ):
            # Instant acknowledgment (2026-08-17): the user just heard an
            # interim line for this turn. A second "let me check" seconds later
            # is the double-tap; the grounded router ack is welcome again only
            # once the wait has grown long enough to deserve a progress line.
            last = getattr(self, "_last_preamble_spoken", None)
            log.info(
                "Grounded ack dropped — an interim line spoke %.1fs ago: %r",
                time.monotonic() - (last[1] if last else time.monotonic()),
                event.text[:80],
            )
            return
        if (
            is_preamble
            and source_layer == "brain.router.ack"
            and getattr(self, "_turn_state", TurnTakingState.IDLE)
            is TurnTakingState.PROCESSING
        ):
            ack_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
            commit_grace_ms = int(
                getattr(ack_cfg, "grounded_ack_commit_grace_ms", 900) or 0
            )
            if commit_grace_ms > 0 and not await self._await_ack_turn_commit(
                commit_grace_ms
            ):
                log.info(
                    "Grounded ack dropped — turn left PROCESSING during the "
                    "%d ms commit grace (state=%s): %r",
                    commit_grace_ms,
                    getattr(self._turn_state, "name", self._turn_state),
                    event.text[:80],
                )
                return
        if event.priority == "interrupt":
            # Arm the quiet window BEFORE TTS so a synchronous publish of a
            # preamble immediately afterwards sees the up-to-date timestamp.
            self._last_interrupt_announcement_ts = time.monotonic()
            try:
                self._player.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("Player-Stop vor Announcement fehlgeschlagen: %s", exc)
        # Phase-1 output filter also applies to bus announcements (skill
        # output, Jarvis-Agent announce, vision privacy notices). Mandate path #2.
        # Pre-Thinking-Ack Flash-Brain (kind="preamble"): the AckGenerator
        # already ran scrub_for_voice with ack_mode=True. We still re-scrub
        # here as a safety net, but pass ack_mode=is_preamble so legitimate
        # filler-opener phrases ("Lass mich kurz nachschauen.") are
        # preserved on the second pass too.
        # Resolve the announcement's spoken language through the ONE
        # authoritative resolver — the live brain.reply_language pin and the
        # sticky conversation_language win over whatever an emitter stamped on
        # the event, and an undetectable/None tag falls back to the resolved
        # turn language, never a hardcoded German default (forensic 2026-06-23:
        # a German voice chat spoke an English "ANNOUNCEMENT" because
        # event.language was trusted verbatim). The event tag is only a hint,
        # passed where the STT tag normally goes.
        ann_lang = self._output_language(event.language, event.text or "")
        scrubbed = scrub_for_voice(
            event.text, language=ann_lang, ack_mode=is_preamble
        )
        if scrubbed.actions:
            log.info(
                "🧹 Announcement-Filter [%s]: %s (fallback=%s)",
                ann_lang, scrubbed.actions, scrubbed.fallback_used,
            )
        if is_harmless_scrub_residue(scrubbed):
            # The whole announcement was filler/honorific/markdown, so the
            # residue guard emptied it and handed back the generic error
            # phrase. Nothing failed — speaking it would report an incident
            # that never happened. Stay silent, but say so in the log.
            log.info(
                "Announcement carried no substance (%s) — staying silent "
                "instead of speaking the error phrase: %r",
                scrubbed.actions,
                (event.text or "")[:80],
            )
            return
        if not scrubbed.cleaned.strip():
            log.info("Announcement nach Filter leer — schweige.")
            return
        # Duplicate-wording safety net (2026-07-06 interim-ack redesign): no
        # emitter may speak the SAME preamble/progress line twice in quick
        # succession, regardless of source (grounded ack, Flash-Brain, skill) —
        # forensic 2026-07-05: one session spoke the identical grounded ack
        # three times. Only the ephemeral kinds are deduped;
        # completion/interrupt readbacks deliver owed answers and may repeat.
        if is_preamble or is_progress:
            dedup_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
            dedup_window_s = float(
                getattr(dedup_cfg, "preamble_dedup_window_s", 180) or 0
            )
            spoken_text = scrubbed.cleaned.strip()
            last_spoken = getattr(self, "_last_preamble_spoken", None)
            if (
                not is_instant_ack
                and dedup_window_s > 0
                and last_spoken is not None
                and last_spoken[0] == spoken_text
                and (time.monotonic() - last_spoken[1]) < dedup_window_s
            ):
                log.info(
                    "Preamble dropped — identical wording spoken %.0fs ago: %r",
                    time.monotonic() - last_spoken[1],
                    event.text[:80],
                )
                return
            # v2 anti-loop backstop: hard cap on spoken preamble/progress
            # lines per rolling 60 s window, ANY source. Kills the historical
            # "kept saying it forever" bug class at the last shared
            # chokepoint. Completion/interrupt readbacks never enter this
            # branch (owed answers are exempt).
            rate_limit = int(
                getattr(dedup_cfg, "preamble_rate_limit_per_min", 3) or 0
            )
            spoken_times = getattr(self, "_preamble_spoken_times", None)
            if spoken_times is None:
                spoken_times = deque(maxlen=32)
                self._preamble_spoken_times = spoken_times
            now_monotonic = time.monotonic()
            # The instant ack is exempt from the anti-loop cap: it is armed
            # exactly once per user utterance and cancels its predecessor, so
            # it cannot loop -- and a user issuing four commands in a minute
            # deserves four first-signs-of-life (maintainer rule 2026-08-17).
            if rate_limit > 0 and not is_instant_ack:
                recent_count = sum(
                    1 for t in spoken_times if now_monotonic - t < 60.0
                )
                if recent_count >= rate_limit:
                    log.warning(
                        "Preamble dropped — rate-limit backstop (%d spoken in "
                        "the last 60s, cap %d): %r",
                        recent_count, rate_limit, event.text[:80],
                    )
                    return
            self._last_preamble_spoken = (spoken_text, now_monotonic)
            if is_instant_ack:
                # Not counted against the cap either: one instant line must
                # never eat the budget of a later owed progress line.
                self._note_instant_ack_spoken(spoken_text, now_monotonic)
            else:
                spoken_times.append(now_monotonic)
        if await self._deliver_announcement_via_realtime(
            event,
            text=scrubbed.cleaned,
            language=ann_lang,
        ):
            return
        if self._realtime_session_owns_voice():
            # The live call rejected the delivery only because it is BUSY
            # (its delegate turn is thinking). The classic TTS voice must
            # never speak into a healthy realtime call — the user hears a
            # sudden second voice/engine (forensic 2026-07-13 17:39, the
            # wiki preamble). Ephemeral lines are stale by the time the
            # live model could speak them → drop; owed readbacks are parked
            # and replayed at the next turn boundary, where the idle live
            # model accepts them (or the call has ended and classic TTS is
            # the honest remaining surface).
            if is_preamble or is_progress:
                log.info(
                    "Announcement dropped — a live realtime call owns the "
                    "voice: %r",
                    event.text[:80],
                )
                return
            if is_agent_reply:
                self._defer_agent_reply(event)
                self._retry_agent_reply_after_boundary()
            else:
                self._deferred_announcements.append(event)
            log.info(
                "Announcement deferred — a live realtime call owns the "
                "voice: %r",
                event.text[:80],
            )
            return
        if is_agent_reply and self._agent_reply_needs_session():
            self._defer_agent_reply(event)
            return
        # The classic TTS voice speaks only inside a conversation the user
        # opened. Checked at the moment of SPEAKING, not only at arrival: the
        # user can hang up during the scrub/dedup/realtime probe above. Every
        # kind is covered — a mission, routine or sub-agent result that lands
        # while no session is open, or after a hang-up, is not voiced out of
        # nowhere (user decision 2026-10-05, replaces the AD-OE6 readback
        # punch-through). The result stays in the app and in the realtime
        # announcement memory mirrored at the top of this handler.
        if not self._classic_voice_session_open():
            if is_agent_reply:
                # Owed to the user at the next call, delivered once.
                self._defer_agent_reply(event)
                return
            log.info(
                "Announcement not spoken — no open voice session (kind=%s): %r",
                event_kind or "normal",
                event.text[:80],
            )
            return
        # Document the announcement in the session log — it is voiced through
        # this bypass path, not _speak, so it would otherwise be invisible.
        # ``detail`` carries an optional technical diagnostic (e.g. a failed
        # Computer-Use exit code + harness reason) that is NOT spoken but is
        # surfaced in the transcript for debugging.
        # A finished sub-agent / mission readback (completion / subagent) hands
        # the floor BACK to the user — drive the UI/orb into SPEAKING for its
        # duration so the mascot animates. The out-of-band announcement path
        # bypasses the turn-state machine, which is why a readback used to play
        # with no visual "Jarvis is talking" signal (2026-06-19). Only readbacks
        # animate (a preamble / progress nudge keeps its prior visual), and the
        # restore is DETERMINISTIC — IDLE once the user has hung up, else
        # LISTENING (the mic is still open). Not capturing a prior state keeps
        # this race-free against a concurrently-flushed deferred announcement.
        animate = is_readback and self._supervisor is not None
        if animate:
            await self._transition("SPEAKING")
        self._assistant_work_count = getattr(self, "_assistant_work_count", 0) + 1
        agent_reply_completed = False
        try:
            # Drive the TTS pin from the SAME resolved language as the scrub,
            # not from event.language again — a None/auto tag here used to send
            # language_code=None, which lets the multilingual TTS (Cartesia)
            # fall back to its English voice on German text (the British-accent
            # symptom; forensic 2026-06-23).
            lang_code = self._bcp47(ann_lang)
            self._register_assistant_speech(scrubbed.cleaned)
            try:
                chunks = self._tts.synthesize(scrubbed.cleaned, language_code=lang_code)
            except TypeError:
                chunks = self._tts.synthesize(scrubbed.cleaned)
            if is_preamble or is_agent_reply:
                # Staleness gate evaluated by the player right before it writes
                # audio: if the answer has started speaking by the time the
                # preamble's synthesis + play-lock wait completes, drop it so it
                # is never voiced after the answer (2026-06-20 misorder fix).
                # TypeError fallback mirrors the synthesize() compat shim above:
                # an older player / test fake without the should_play kwarg still
                # plays (the synchronous JARVIS_SPEAKING guard already covers the
                # already-speaking case; only the in-flight race is then uncovered).
                try:
                    playback_result = await self._player.play_chunks(
                        chunks,
                        should_play=lambda: (
                            not self._agent_reply_needs_session()
                            and (event.source_layer != "delegation.batch"
                                 or self._turn_state is TurnTakingState.LISTENING)
                            if is_agent_reply
                            else getattr(self, "_turn_state", TurnTakingState.IDLE)
                            is not TurnTakingState.JARVIS_SPEAKING
                        ),
                    )
                except TypeError:
                    playback_result = await self._player.play_chunks(chunks)
            else:
                playback_result = await self._player.play_chunks(chunks)
            agent_reply_completed = self._playback_confirmed(playback_result) and (
                not is_agent_reply or not self._agent_reply_needs_session()
            )
            if agent_reply_completed:
                self._emit_spoken(
                    scrubbed.cleaned,
                    ann_lang,
                    _announcement_spoken_kind(getattr(event, "kind", None)),
                    getattr(event, "detail", None),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Announcement playback failed: %s", exc)
        finally:
            if is_agent_reply and not agent_reply_completed:
                self._defer_agent_reply(event)
            self._assistant_work_count -= 1
            if animate:
                hungup = hangup is not None and hangup.is_set()
                await self._transition("IDLE" if hungup else "LISTENING")

    def _realtime_session_owns_voice(self) -> bool:
        """True while an accepted realtime call is the only valid voice.

        Provider health is deliberately irrelevant here. The handle is cleared
        only after the realtime lifecycle unwinds; until then, classic TTS must
        stay silent rather than becoming a second voice inside the same call.
        """
        return self._realtime_voice_handle() is not None

    def _classic_voice_session_open(self) -> bool:
        """True while the user is in an open classic-pipeline conversation.

        The classic TTS voice may speak an announcement only here. With no
        session (idle, hung up, or still choosing its engine), a classic
        readback would be Jarvis talking out of nowhere in a second voice;
        background results stay in the app and the conversation memory.
        """
        hangup = getattr(self, "_hangup_event", None)
        return bool(
            getattr(self, "_current_voice_session_id", None) is not None
            and not (hangup is not None and hangup.is_set())
            and not getattr(self, "_voice_engine_transitioning", False)
            and getattr(self, "_turn_state", TurnTakingState.IDLE)
            is not TurnTakingState.IDLE
        )

    def _schedule_delegation_results(self) -> None:
        """One coalescing task; a user's conversation always keeps the floor."""
        inbox = getattr(self, "_delegation_inbox", None)
        task = getattr(self, "_delegation_result_task", None)
        if (
            inbox is None or not inbox.pending
            or (task is not None and not task.done())
            or self._agent_reply_needs_session()
            or not self._agent_reply_floor_open()
            or getattr(self, "_agent_reply_inflight", None) is not None
        ):
            return
        self._delegation_result_task = asyncio.create_task(
            self._flush_delegation_results(), name="delegation-results"
        )

    async def _flush_delegation_results(self) -> None:
        from dodaios.core.delegation import BATCH_WINDOW_S

        event = None
        try:
            await asyncio.sleep(BATCH_WINDOW_S)
            if (
                self._agent_reply_needs_session()
                or not self._agent_reply_floor_open()
                or getattr(self, "_agent_reply_inflight", None) is not None
            ):
                return
            event = self._delegation_inbox.take()
            if event is not None:
                await self._on_announcement(event)
        except asyncio.CancelledError:
            if event is not None:
                self._defer_agent_reply(event)
            raise
        except Exception:
            if event is not None:
                self._defer_agent_reply(event)
            log.warning("Delegation result delivery deferred", exc_info=True)
        finally:
            self._delegation_result_task = None
            self._schedule_delegation_results()

    async def _deliver_announcement_via_realtime(
        self,
        event: AnnouncementRequested,
        *,
        text: str,
        language: str,
    ) -> bool:
        """Offer a standardized readback to the active duplex model.

        The live wrapper rejects busy, failed, or unsupported sessions. While
        the accepted realtime handle still exists, ``_on_announcement`` drops
        or defers that output; only a fully unwound call may use classic TTS.
        """
        session = self._realtime_voice_handle()
        deliver = getattr(session, "deliver_announcement", None)
        if not callable(deliver):
            return False
        agent_reply = self._is_agent_reply(event)
        browser = session is self._live_call()
        report = str(getattr(event, "report", None) or "").strip()
        if browser and agent_reply and not report:
            report = text
        receipt_capable = callable(getattr(session, "take_report_outcome", None)) and hasattr(
            session, "report_pending"
        )
        # Native handles settle on their existing audio/turn callbacks. Legacy
        # API browser handles only promise boolean acceptance, so waiting for a
        # subscription-only report receipt would strand every later handoff.
        tracked_reply = (
            (agent_reply and not browser)
            or bool(browser and receipt_capable and (agent_reply or report))
        )
        if tracked_reply:
            if getattr(self, "_agent_reply_inflight", None) is not None:
                return False
            # Register before transport I/O so fast playback cannot race acceptance.
            self._agent_reply_inflight = event
            self._agent_reply_inflight_text = text
            self._agent_reply_inflight_session = session
        accepted = False
        # The raw report goes to the live model as data to reason over; only
        # sessions that understand it are handed the keyword.
        extra: dict[str, Any] = {"report": report} if report else {}
        try:
            async def handoff() -> bool:
                return bool(await deliver(
                    text=text,
                    language=language,
                    spoken_kind=_announcement_spoken_kind(
                        getattr(event, "kind", None)
                    ),
                    detail=getattr(event, "detail", None),
                    **extra,
                ))

            if browser:
                from dodaios.live.runtime import on_session_loop

                accepted = bool(await on_session_loop(session, handoff))
            else:
                accepted = await handoff()
        except Exception as exc:  # noqa: BLE001 -- classic path is load-bearing
            log.warning("Realtime announcement handoff failed: %s", exc)
            return False
        finally:
            if tracked_reply and not accepted and self._agent_reply_inflight is event:
                self._agent_reply_inflight = None
                self._agent_reply_inflight_text = ""
                self._agent_reply_inflight_session = None
        if accepted:
            log.info(
                "Announcement handed to active realtime provider %s: %r",
                getattr(self, "_active_realtime_provider", "") or "unknown",
                text[:80],
            )
        return accepted

    # ------------------------------------------------------------------
    # Instant acknowledgment (2026-08-17)
    # ------------------------------------------------------------------

    _INSTANT_ACK_SOURCE_LAYER = "brain.instant_ack"

    def _instant_ack_compose_all(self) -> bool:
        ack_cfg = getattr(getattr(self, "_config", None), "ack_brain", None)
        return bool(getattr(ack_cfg, "instant_ack_compose_all", False))

    async def _on_action_proposed(self, event: ActionProposed) -> None:
        """Remember the tool the current voice turn is running (progress line)."""
        if getattr(self, "_turn_state", TurnTakingState.IDLE) is not TurnTakingState.PROCESSING:
            return

    def _interim_line_spoke_recently(self, within_s: float) -> bool:
        """Any preamble/progress line (instant ack, router ack, heartbeat) just spoke."""
        last = getattr(self, "_last_preamble_spoken", None)
        return bool(last is not None and (time.monotonic() - last[1]) < within_s)

    def _note_instant_ack_spoken(self, text: str, at: float | None = None) -> None:
        """Record the moment an instant ack actually went to the speaker.

        ``at`` is the same monotonic stamp stored in ``_last_preamble_spoken``
        so the progress line can tell the turn's own ack from other emitters.
        """
        note_spoken(text)

    async def _await_ack_turn_commit(self, grace_ms: int) -> bool:
        """Poll the turn-state for up to ``grace_ms``; True only if it stays
        PROCESSING throughout — the continuation grace from AD-OE5.

        The Pre-Thinking-Ack is ready a few hundred ms after the VAD endpoint,
        often before the VAD has registered that the user merely paused and kept
        talking. Returning False the instant the turn leaves PROCESSING (the
        continuation interrupt flips it to LISTENING/USER_SPEAKING, or the brain
        answered → JARVIS_SPEAKING) lets the caller drop the ack before it can
        speak over the user.
        """
        step_s = 0.05
        steps = max(1, int(grace_ms / 1000.0 / step_s))
        for _ in range(steps):
            if self._turn_state is not TurnTakingState.PROCESSING:
                return False
            await asyncio.sleep(step_s)
        return self._turn_state is TurnTakingState.PROCESSING

    async def _on_background_completed(
        self, event: JarvisAgentBackgroundCompleted
    ) -> None:
        """Announce a finished background Jarvis-Agent task.

        The readback goes through ``_on_announcement`` like every other
        announcement: an open realtime call speaks it, an open classic
        session speaks it, and with no open voice session it is not voiced
        at all (user decision 2026-10-05: no spoken news out of nowhere).

        CRIT-5 (2026-05-17): cancel the oldest pending spawn-watchdog --
        FIFO matches the sequential dispatch model. If the watchdog has
        already fired and emitted "Bin noch dran.", the cancel is a
        cheap no-op.
        """
        if self._spawn_watchdog_tasks:
            task = self._spawn_watchdog_tasks.pop(0)
            if not task.done():
                task.cancel()
        if getattr(self, "_muted", False):
            log.debug("Background-completed announcement suppressed — voice muted")
            return
        # WS3b (live bug 2026-06-14): a Jarvis-Agent mission that completes AFTER
        # the user hung up still owes them its result. This readback is a FRESH
        # turn (the answer they asked for), not a stale leftover from the aborted
        # turn, so it must NOT be dropped by the hangup gate (AD-OE6
        # zero-silent-drop). The mission ran in its own subprocess + Job Object;
        # hangup never killed it. The mute guard above still silences a
        # deliberately-muted session, and the phrases below stay priority
        # "normal" → queued behind any current speech, never barging
        # mid-utterance (AD-OE5).
        # Resolve the readback language from the original request utterance,
        # falling back to the worker summary text (pin > conversation-stickiness
        # > detected utterance/summary > default) so an English/Spanish user
        # never hears "Fertig." in German, and the "Done./Fertig." prefix never
        # mismatches the summary language (forensic 2026-06-23: announcement
        # emitters bypassed the resolver).
        lang = self._output_language(
            None,
            getattr(event, "utterance", "") or getattr(event, "summary", "") or "",
        )
        ph = self._BG_READBACK_PHRASES.get(lang, self._BG_READBACK_PHRASES["en"])
        if event.success and event.summary:
            summ = event.summary.strip()
            if len(summ) > 200:
                summ = summ[:200].rsplit(" ", 1)[0] + "…"
            text = ph["done_summ"].format(s=summ)
        elif event.success:
            text = ph["done"]
        else:
            err_short = (event.error or ph["unknown_err"])[:80]
            text = ph["fail"].format(e=err_short)
        # Defense-in-Depth: Summary/Error kann aus dem Jarvis-Agent-Pfad kommen
        # und Engineering-Tokens (Sub-Agent, Subprocess, MCP) enthalten.
        # scrub_for_voice filtert die raus, sonst leakt Worker-Mechanik
        # in den Voice-Kanal (vgl. Mandat-Pfad #2 Output-Filter).
        scrubbed = scrub_for_voice(text, language=lang)
        if scrubbed.actions:
            log.info(
                "🧹 Background-Filter: %s (fallback=%s)",
                scrubbed.actions, scrubbed.fallback_used,
            )
        if is_harmless_scrub_residue(scrubbed) or not scrubbed.cleaned.strip():
            # The worker's own summary did not survive the filter. Speaking the
            # residue guard's error phrase would invent a failure on a mission
            # that succeeded as often as not — but silence is not the answer
            # either: the user is waiting for THIS result (AD-OE6,
            # zero-silent-drop). Retry with the deterministic phrase that
            # carries no summary, which is hand-tuned to pass the filter.
            plain = (
                ph["done"] if event.success
                else ph["fail"].format(e=ph["unknown_err"])
            )
            log.info(
                "Agent background finished (success=%s) — the readback "
                "carried no substance (%s), falling back to the summary-less "
                "phrase instead of the error phrase: %r",
                event.success,
                scrubbed.actions,
                text[:80],
            )
            if plain != text:
                scrubbed = scrub_for_voice(plain, language=lang)
            if is_harmless_scrub_residue(scrubbed) or not scrubbed.cleaned.strip():
                # Even the canned line does not survive. Staying silent beats
                # claiming a failure, but it means a completion went
                # unannounced — say so in the log, loudly.
                log.warning(
                    "Agent background finished (success=%s) and was "
                    "NEVER announced: both the summary and the canned phrase "
                    "were filtered away (%s)",
                    event.success,
                    scrubbed.actions,
                )
                return
        cleaned = scrubbed.cleaned.strip()
        log.info(
            "Agent background finished (success=%s, duration=%.1fs) — readback: %r",
            event.success, event.duration_s, cleaned,
        )
        # One choke point for every spoken announcement: ``_on_announcement``
        # hands the readback to an open realtime call, defers it while the
        # user holds the floor, and never lets the classic TTS voice speak
        # it outside an open voice session.
        await self._on_announcement(
            AnnouncementRequested(
                source_layer="harness.jarvis_agent.background",
                text=cleaned,
                language=lang,
                priority="normal",
                kind="subagent",
            ),
            # The FIFO pop above retired this mission's own watchdog; a
            # newer mission that is still running keeps its heartbeat.
            cancel_heartbeats=False,
        )

    async def _on_spawn_announcement(self, event: JarvisAgentAnnouncement) -> None:
        """Spawn-ACK ist auf User-Wunsch (2026-05-12) deaktiviert.

        History:
            2026-04-25 .. 2026-05-10 — Pfad war stumm (User-Wunsch).
            2026-05-11 — kurz reaktiviert mit fixer Phrase "Okay, mache ich."
                         weil der User ein Voice-Feedback wollte um stille
                         Timeouts vom erfolgreichen Spawn unterscheiden zu
                         koennen.
            2026-05-12 — User widerruft. Jede Spawn-ACK-Phrase nervt; der
                         User unterscheidet Spawn vs. Timeout jetzt visuell
                         (Sub-Agents-Board) und ueber den Background-
                         Completed-Voice-Readback am Ende der Mission.

        Der Bus-Event selbst (``JarvisAgentAnnouncement``) wird in
        ``spawn_worker.py`` weiterhin publisht und vom UI gelesen — wir
        unterdruecken hier nur den Voice-Pfad. Cleanup-Logging behalten wir
        einmalig pro Event, damit man im Log noch sehen kann dass der ACK
        absichtlich ueber-sprungen wurde (debug-friendly bei spaeteren
        Voice-Bug-Reports).
        """
        log.info(
            "Spawn-ACK suppress't (User-Wunsch 2026-05-12) — action=%r target=%r",
            event.action, event.target,
        )
        # CRIT-5 (2026-05-17) + heartbeat rework (2026-06-19): schedule the
        # background-mission heartbeat so the user hears a varied, language-
        # resolved "still on it" reassurance while a long mission runs (first
        # beat well before the old 90 s, then bounded). _on_background_completed
        # cancels it on the crash path; a completion readback cancels it via
        # _cancel_spawn_heartbeats in the happy path.
        self._schedule_spawn_watchdog()
        return

    def _schedule_spawn_watchdog(self) -> None:
        """Start the background-mission heartbeat: a bounded series of varied,
        language-resolved "still on it" reassurances while the mission has not
        completed (see ``_spawn_watchdog_body``). FIFO-cancelled by
        ``_on_background_completed``; also cancelled on a completion readback via
        ``_cancel_spawn_heartbeats``."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._spawn_watchdog_body(
                origin_session_id=getattr(self, "_current_voice_session_id", None)
            ),
            name=f"spawn-watchdog-{len(self._spawn_watchdog_tasks)}",
        )
        self._spawn_watchdog_tasks.append(task)

    def _pick_heartbeat_phrase(self) -> tuple[str, str]:
        """Pick one varied "still on it" heartbeat phrase + its language.

        Language flows through the single output-language resolver
        (``_output_language``: ``brain.reply_language`` pin > sticky
        conversation language > ``DEFAULT_LOCALE``) — never hard-coded "de", so
        a German / English / Spanish conversation hears the heartbeat in its own
        language. The phrase comes from the varied ``STILL_RUNNING_PHRASES`` pool
        with a small no-repeat guard so consecutive beats differ. The pool lives
        in the allowlisted spawn-announcement module (keeps the German/Spanish
        runtime strings out of this file); a lazy import + neutral fallback keeps
        the spoken path crash-proof.
        """
        lang = _phrase_lang(self._output_language(None, ""))
        try:
            from dodaios.brain.ack_brain.spawn_announcement import (  # noqa: PLC0415
                STILL_RUNNING_PHRASES,
            )

            pool = STILL_RUNNING_PHRASES.get(lang) or STILL_RUNNING_PHRASES["en"]
        except Exception:  # noqa: BLE001 — the heartbeat must never crash the loop
            return ("Still working on it.", lang)
        recent = getattr(self, "_heartbeat_recent", None)
        choices = [p for p in pool if recent is None or p not in recent] or list(pool)
        choice = random.choice(choices)  # noqa: S311 — phrase variety, not crypto
        if recent is not None:
            recent.append(choice)
        return (choice, lang)

    async def _spawn_watchdog_body(
        self, *, origin_session_id: str | None = None
    ) -> None:
        """Speak a bounded, varied, language-resolved "still on it" heartbeat
        while a background mission runs.

        Replaces the old one-shot, German-only "Bin noch dran." (2026-06-19):
        the first beat fires after ``_spawn_watchdog_delay_s`` (90 s of silence
        read as a crash), then up to ``_heartbeat_max_count`` total,
        ``_heartbeat_interval_s`` apart, so the wait feels alive instead of dead.
        Each beat is picked fresh (``_pick_heartbeat_phrase``) and emitted as a
        ``priority="normal"`` ``AnnouncementRequested`` — which the AD-OE5 floor
        guard in ``_on_announcement`` drops if the user holds the floor (never
        speaks over the user). A muted session stays silent. ``CancelledError``
        (mission finished / completion readback) exits quietly.

        On EVERY terminal path the task removes itself from
        ``_spawn_watchdog_tasks``. That list is the "background mission in flight"
        signal read by ``_active_session``'s idle-timeout override and by
        ``_finish_after_response``; a done-but-still-listed task would hold the
        voice session open forever, because the success path never publishes the
        ``JarvisAgentBackgroundCompleted`` event that would otherwise drain it. The
        hard cap bounds the in-flight hold to the heartbeat lifetime.

        A beat belongs to the voice session the mission was started in
        (``origin_session_id``; ``None`` for a typed chat). It is skipped once
        a DIFFERENT voice session is open: that call never asked for the
        mission, and inside a live call the line lands as backend commentary
        that the duplex model voices over the user and that stalls its reply
        to a short greeting (live bug 2026-10-02 17:58, "Hallo, was geht ab?"
        unanswered for 6 s after a chat mission's beat entered the new call).
        """
        try:
            max_count = max(1, getattr(self, "_heartbeat_max_count", 3))
            interval = getattr(self, "_heartbeat_interval_s", 60.0)
            delay = self._spawn_watchdog_delay_s
            for beat in range(1, max_count + 1):
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                delay = interval
                if getattr(self, "_muted", False):
                    log.debug("Spawn-heartbeat: muted, skipping beat %d", beat)
                    continue
                current_session_id = getattr(self, "_current_voice_session_id", None)
                if (
                    current_session_id is not None
                    and current_session_id != origin_session_id
                ):
                    log.info(
                        "Spawn-heartbeat #%d skipped — the mission was not "
                        "started in the open voice session",
                        beat,
                    )
                    continue
                if self._bus is None:
                    return
                phrase, lang = self._pick_heartbeat_phrase()
                log.info(
                    "Spawn-heartbeat #%d (mission still running) — %r (%s)",
                    beat, phrase, lang,
                )
                try:
                    await self._bus.publish(
                        AnnouncementRequested(
                            text=phrase,
                            language=lang,
                            priority="normal",
                            # "progress" = droppable when stale: if the user
                            # holds the floor when this lands, _on_announcement
                            # DROPS it (never defers/replays a stale "still on
                            # it" after the user finishes or after the answer).
                            kind="progress",
                        )
                    )
                except Exception:  # noqa: BLE001
                    log.warning(
                        "Spawn-heartbeat: AnnouncementRequested publish failed",
                        exc_info=True,
                    )
        finally:
            # Self-remove on every exit. _on_background_completed may have
            # already popped this task (FIFO cancel) — remove() is then a
            # harmless no-op (ValueError swallowed).
            me = asyncio.current_task()
            try:
                self._spawn_watchdog_tasks.remove(me)
            except ValueError:
                pass

    def _cancel_spawn_heartbeats(self) -> None:
        """Cancel every pending spawn heartbeat.

        Called when a mission delivers its actual answer (a readback —
        ``kind="completion"`` or ``kind="subagent"``) so Jarvis never says "still
        on it" right AFTER the result. The
        success path does not publish ``JarvisAgentBackgroundCompleted``, so the
        heartbeat is otherwise only drained by its own cap; this is the precise
        hook that silences it the moment the answer lands. Each cancelled task
        still self-removes from ``_spawn_watchdog_tasks`` in its ``finally``.
        """
        tasks = getattr(self, "_spawn_watchdog_tasks", None)
        if not tasks:
            return
        for task in list(tasks):
            if not task.done():
                task.cancel()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        # Capture the loop that owns ``_call_event`` / ``_hangup_event`` before
        # warm-up. UI controls can become clickable while warm-up is still in
        # progress, so recording it later would leave a small unsafe window.
        self._runtime_loop = asyncio.get_running_loop()
        await self._warmup()
        # Permanent-Vision: Background-Refresh-Loop hier im Pipeline-Event-Loop
        # starten. Ohne das kriegt `VisionContextProvider.current()` nie einen
        # gecachten Frame und der Router-Brain sieht den Screen nicht. Fehler
        # beim Start duerfen die Voice-Session nicht toeten — Text-Only-
        # Fallback greift weiter.
        if self._vision_provider is not None:
            try:
                await self._vision_provider.start()
                log.info("VisionContextProvider Background-Loop gestartet.")
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "VisionContextProvider.start() fehlgeschlagen — "
                    "Router laeuft ohne Screen-Kontext: %s",
                    exc,
                    exc_info=True,
                )
        # Dictation wants BOTH key edges; call/hangup keep the single-fire-on-
        # release contract. One producer for boot and live re-arm.
        hotkey_bindings, ptt_events = self._build_hotkey_bindings()
        log.info(
            "Pipeline ready. CALL=[%s] HANGUP=[%s] DICTATE=[%s/%s] "
            "DICTATE-TOGGLE=[%s] PASTE-LAST=[%s] OWW=%s "
            "WAKE=%s (threshold=%.2f) WHISPER-WAKE=%s TURN-MODE=%s",
            ", ".join(self._call_hotkeys),
            ", ".join(self._hangup_hotkeys),
            ", ".join(self._dictate_hotkeys) or "off",
            self._dictate_mode,
            ", ".join(getattr(self, "_dictate_toggle_hotkeys", None) or []) or "off",
            ", ".join(getattr(self, "_paste_last_hotkeys", None) or []) or "off",
            "on" if self._openwakeword_enabled else "off",
            list(self._wake._keywords),
            self._wake._threshold,
            "on" if self._whisper_wake_enabled else "off",
            # Observability for the single-turn vs conversation pendulum: the
            # mode was previously invisible in the log, which made it impossible
            # to tell from telemetry whether a `turn_complete` hangup was the
            # configured single-turn behavior or a regression. See
            # feedback_voice_session_mode + BUG-009-style env-propagation traps.
            "conversation (until 'auflegen'/idle/hotkey)"
            if self._continue_listening_after_response
            else "single-turn (fresh wake per turn)",
        )
        def _log_task_exit(task: asyncio.Task) -> None:
            # Asyncio verschluckt Task-Exceptions sonst silent — wir hatten
            # genau diesen Bug 2026-04-26 (Mic-Open mit ungueltiger Sample-Rate
            # killte den Wake-Task ohne ein einziges Log).
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error(
                    "Pipeline-Task '%s' beendet mit Exception: %s",
                    task.get_name(),
                    exc,
                    exc_info=exc,
                )

        async with HotkeyTrigger(hotkey_bindings, push_to_talk=ptt_events) as trigger:
            # Kept for the hold-key watchdog (``_watch_dictation_hold_key``),
            # which asks the live trigger whether the chord is physically down.
            self._hotkey_trigger = trigger
            hotkey_task = asyncio.create_task(self._hotkey_loop(trigger), name="hotkey")
            hotkey_task.add_done_callback(_log_task_exit)
            # Live keybind re-arm: set_keybinds() flips _hotkey_reload_event and
            # this task re-registers the new combos in place (no app restart).
            hotkey_reload_task = asyncio.create_task(
                self._hotkey_reload_loop(trigger), name="hotkey-reload"
            )
            hotkey_reload_task.add_done_callback(_log_task_exit)
            wake_task = (
                asyncio.create_task(self._wake_loop(), name="wake")
                if self._wake_listening_enabled()
                else None
            )
            if wake_task is not None:
                wake_task.add_done_callback(_log_task_exit)
            else:
                log.info(
                    "Wake listener disabled; microphone stays closed until a hotkey call."
                )
            main_task = asyncio.create_task(self._state_loop(), name="state")
            main_task.add_done_callback(_log_task_exit)

            try:
                await main_task
            finally:
                self._hotkey_trigger = None
                tasks_to_cancel: list[asyncio.Task] = [hotkey_task, hotkey_reload_task]
                if wake_task is not None:
                    tasks_to_cancel.append(wake_task)
                for t in tasks_to_cancel:
                    t.cancel()
                for t in tasks_to_cancel:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: S110
                        # Shutdown has already cancelled these owned tasks.
                        pass
                if self._vision_provider is not None:
                    try:
                        await self._vision_provider.stop()
                    except Exception as exc:  # noqa: BLE001
                        log.debug("VisionContextProvider.stop() swallow: %s", exc)
                # Phase-B confirmation-audio render is fire-and-forget; cancel it
                # here so it is never orphaned past pipeline shutdown.
                await self._cancel_warmup_background()

    async def _emit_boot_status(self, *, ready: bool, detail: str = "") -> None:
        """Publish a VoiceBootStatus on the bus (guarded — never breaks boot).

        ``ready=False`` is emitted at the very start of warm-up; ``ready=True``
        only once ALL deferred loaders (wake model + VAD + TTS client) have
        completed, from ``_warmup_deferred_loaders`` — the first honest moment
        the user can both be heard AND get a spoken reply. (It runs after Phase A
        has returned, so the wake loop is already listening by then.)
        """
        if self._bus is None:
            return
        try:
            await self._bus.publish(VoiceBootStatus(ready=ready, detail=detail))
        except Exception as exc:  # noqa: BLE001 — status signal never breaks boot
            log.warning("VoiceBootStatus(ready=%s) publish failed: %s", ready, exc)

    async def _cancel_warmup_background(self) -> None:
        """Cancel + await the fire-and-forget warm-up tasks on shutdown.

        Three background tasks run off the wake-critical path: Phase B (the ACK +
        task-ack confirmation-audio pre-render), the deferred wake/VAD/TTS
        loaders (``_warmup_deferred_loaders``), and the boot-ready audio cue
        (``_warmup_ready_cue_task``, created at the end of the deferred loaders).
        When ``run()`` is cancelled (the normal desktop-shutdown path) all must
        be cancelled and awaited, otherwise they are orphaned: under
        ``pythonw.exe`` there is no stderr to surface the "Task exception was
        never retrieved" warning, and a late TTS render could write stale PCM
        into ``_ack_pcm`` / ``_task_ack_pcm`` after a live TTS-provider switch
        already cleared them. Guarded so shutdown never raises.
        """
        self._dictation_warmup_shutdown = True
        for attr in (
            "_warmup_background_task",
            "_warmup_ready_cue_task",
            "_deferred_warmup_task",
            "_dictation_warmup_task",
            "_voice_stt_warmup_task",
            "_audio_topology_task",
        ):
            task = getattr(self, attr, None)
            if task is None:
                continue
            if not task.done():
                task.cancel()
            try:
                # Bounded: a wedged native call inside a background worker
                # (e.g. a PortAudio re-init mid-refresh) must not hang the
                # whole shutdown; the orphaned worker dies with the process.
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except TimeoutError:
                log.warning(
                    "Warm-up background task %s did not stop within 2s.", attr
                )
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                # Shutdown is best-effort after the bounded wait above.
                pass
            setattr(self, attr, None)

    async def _warmup(self) -> None:
        log.info("Warm-up: Whisper / Silero / Wake-Word / TTS …")
        await self._emit_boot_status(ready=False, detail="warmup_start")

        # --- Phase A: start the wake LOOP, nothing else -------------------
        # Phase A blocks on the absolute minimum so the wake loop is listening
        # fast: the audio-device table settling (BUG-014 guard) and the wake
        # start. The heavy VAD / STT / TTS loads are deliberately NOT here — they
        # move to the background ``_warmup_deferred_loaders`` so they never gate
        # wake-loop start. NOTE: a started wake loop is NOT the same as "ready to
        # converse"; honest readiness (incl. TTS) is signalled later, from the
        # deferred loaders (see below).
        phase_a_start = time.monotonic()
        await self._warmup_phase_a()
        phase_a_ms = (time.monotonic() - phase_a_start) * 1000.0
        log.info("Warm-up Phase A (critical listening path) done in %.0f ms.", phase_a_ms)
        # Honest readiness (2026-06-29): Phase A only starts the wake LOOP — it
        # does NOT mean the user can hold a conversation yet (VAD + TTS, and the
        # custom-wake Whisper model, are still loading in
        # _warmup_deferred_loaders below). Readiness is therefore NOT signalled
        # here. BOTH the VoiceBootStatus(ready=True) and the audible "you can
        # speak" cue now fire at the END of _warmup_deferred_loaders — the first
        # moment wake (model) + VAD + TTS are ALL genuinely up. Previously the
        # openWakeWord path flipped ready in Phase A and the custom-phrase path
        # flipped it right after the wake model alone — either way the UI said
        # "ready" while TTS was still loading, so the user spoke and nothing came
        # back ("it says ready but I can't talk"). ready=False was already
        # emitted at warmup_start above, so the UI stays in its honest
        # "starting up / preparing to listen" state until the deferred loaders
        # complete.

        # --- Phase B: confirmation audio, off the critical path -----------
        # Pre-rendering the ACK + ~20 task-ack phrases used to dominate warm-up
        # (~20 sequential TTS round-trips). Fire it as a background task so it
        # never delays the ready signal; if the wake word fires before the ACK
        # is cached, the chime above plays instead.
        self._warmup_background_task = asyncio.create_task(
            self._warmup_phase_b(), name="warmup-confirmation-audio"
        )
        log.info("Warm-up Phase A complete — confirmation audio rendering in background.")

    def _log_audio_topology_done(self, task: asyncio.Task) -> None:
        """A silently dead hot-swap watcher must leave a diagnostic (BUG-102)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("Audio topology watcher died: %s", exc)

    def _log_warmup_ready_cue_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Warm-up ready cue failed: %s", exc)

    async def _warmup_phase_a(self) -> None:
        """Bring up ONLY the wake-critical listening path, then return.

        The wake loop is started the moment this returns, so it must block on
        the absolute minimum: the audio-device table settling (BUG-014 guard)
        and the OpenWakeWord model starting. That is everything the wake path
        needs to hear "Hey Jarvis" and spawn the orb.

        The heavy VAD / STT / TTS-client loads are deliberately NOT here. Each
        of them lazy-imports a large C-extension (onnxruntime for the wake model
        and Silero-VAD, ctranslate2 for local Whisper); run concurrently inside
        the boot storm they serialize on the Python import lock and starve to
        7-24 s (measured: ``wake-start=14187, vad-load=12672``). Because the wake
        loop used to start only after the WHOLE warm-up finished, gating it on
        those loads left the wake word dead for that entire window — the
        "~10 s delay / nothing spawns" regression. They are only needed AFTER a
        wake and are lazy-safe (each object re-ensures its model on first use),
        so they move to a background deferred task (``_warmup_deferred_loaders``)
        that never gates wake readiness.
        """
        async def _start_wake() -> None:
            if self._openwakeword_enabled:
                await self._wake.start()

        # return_exceptions=True (inside _gather_timed): a slow/failing loader
        # must not abort the other. The per-loader timing exposes which one
        # dominates the wake-critical warm-up (boot-perf forensic).
        timings, results = await _gather_timed(
            [
                ("audio-stabilize", self._stabilize_audio_devices),
                ("wake-start", _start_wake),
            ]
        )
        log.info(
            "Warm-up Phase A (wake-critical) per-loader (ms): %s",
            ", ".join(
                f"{name}={timings[name]:.0f}"
                for name in sorted(timings, key=lambda n: -timings[n])
            ),
        )
        for name, res in zip(("audio-stabilize", "wake-start"), results, strict=True):
            if isinstance(res, Exception):
                log.warning("Warm-up Phase A task '%s' failed: %s", name, res)

        # Heavy model loads move off the wake-ready path — fire-and-forget so a
        # wake can fire (and the orb spawn) while they are still loading. A wake
        # that arrives first simply triggers a one-off lazy load on the VAD/STT
        # object instead of waiting out the whole warm-up. Cancelled on shutdown
        # via ``_cancel_warmup_background``.
        self._deferred_warmup_task = asyncio.create_task(
            self._warmup_deferred_loaders(), name="warmup-deferred-loaders"
        )

    async def _warmup_deferred_loaders(self) -> None:
        """Background pre-load of the FULL conversational stack (wake model +
        VAD + TTS), then signal HONEST readiness.

        Runs OFF the wake-critical path (see ``_warmup_phase_a``): the wake loop
        is already listening by the time this starts, so a wake mid-load just
        triggers a one-off lazy load on the VAD/STT/TTS object. What this owns is
        the *honest* readiness signal — ``VoiceBootStatus(ready=True)`` and the
        audible "you can speak" cue fire ONLY at the very end, once wake (model),
        VAD endpointing AND the TTS reply path are all initialized. Flipping
        ready before TTS was up was the "it says ready but I can't talk" bug
        (2026-06-29).

        Ordering / GIL: the wake-model load is the one heavy CUDA/GIL step, kept
        FIRST and ALONE (racing it against the VAD load serialized both on the
        import + CUDA-init lock to ~11.8 s — forensic 2026-06-22). The TTS client
        init is network-bound (releases the GIL on I/O), so it is kicked off
        CONCURRENTLY with the wake warm-up to overlap its latency instead of
        paying it sequentially afterwards. VAD loads after the wake model. Every
        load is guarded so one slow/failing load never strands readiness — it
        will lazy-load / fall back on first use.
        """
        deferred_t0 = time.monotonic()

        # TTS client init is network-bound → overlap it with the (CUDA-heavy)
        # wake warm-up rather than adding it on afterwards. Idempotent: a later
        # lazy ``_ensure_client`` on first synth is a harmless no-op.
        async def _init_tts() -> None:
            await asyncio.to_thread(self._tts._ensure_client)

        tts_task = asyncio.create_task(_init_tts(), name="warmup-tts-init")
        try:
            # PRIORITY: pre-warm the WAKE model FIRST and ALONE. For a custom wake
            # phrase (stt_match / rolling-whisper) ``self._stt`` IS the wake model,
            # and until it is in memory + warmed the wake loop cannot transcribe.
            # Prime with one REAL inference (not just the model load): the first
            # transcribe is cold (CUDA kernel JIT / cuDNN algo search), and that
            # cost used to land on the user's first "Hey Jarvis" (swallowed wake,
            # forensic 2026-06-28). ``warm_up`` pays it here; falls back to
            # ``_ensure_model``.
            if self._stt is not None:
                _wake_t0 = time.monotonic()
                try:
                    _prime = getattr(self._stt, "warm_up", None)
                    await asyncio.to_thread(
                        _prime if callable(_prime) else self._stt._ensure_model
                    )
                    log.info(
                        "Wake-model pre-warm done in %.0f ms (priority, no GIL race).",
                        (time.monotonic() - _wake_t0) * 1000.0,
                    )
                except Exception as exc:  # noqa: BLE001 — lazy load on first use still works
                    log.warning("Wake-model pre-warm failed (will lazy-load): %s", exc)

            # Join the concurrently-running TTS init (started before the wake warm).
            tts_err: Exception | None = None
            try:
                await tts_task
            except Exception as exc:  # noqa: BLE001 — lazy load on first synth still works
                tts_err = exc
                log.warning("Warm-up deferred loader 'tts-init' failed: %s", exc)

            log.info(
                "Warm-up deferred loaders done in %.0f ms (tts-init=%s).",
                (time.monotonic() - deferred_t0) * 1000.0,
                "ok" if tts_err is None else "failed",
            )

            # --- HONEST READINESS: the full stack is up (or attempted) ------
            # Wake model warmed + VAD loaded + TTS client init done → the user
            # can now actually be heard AND get a spoken reply. Signal ready and
            # play the audible cue here, exactly once, at the first truthful
            # moment. Even on a failed VAD/TTS load we still flip ready (each
            # lazy-loads / falls back on first use) rather than stranding the UI
            # in "starting up" forever. The cue is fire-and-forget so a
            # slow/wedged output device never sits between ready=True and a
            # responsive wake loop.
            await self._emit_boot_status(ready=True, detail="listening")
            self._warmup_ready_cue_task = asyncio.create_task(
                self._play_ready_cue(), name="warmup-ready-cue"
            )
            self._warmup_ready_cue_task.add_done_callback(self._log_warmup_ready_cue_done)
            # Hot-swap watcher (BUG-102): starts only AFTER honest readiness —
            # never on the boot critical path (AP-26). Polls the out-of-process
            # device probe and refreshes PortAudio when a headset is plugged
            # in or pulled, so mic and speaker follow the user's devices at
            # runtime on every OS instead of dying on a frozen device table.
            # ``getattr`` default keeps ``__new__``-built test/hot-reload
            # instances (which skip ``__init__``) working.
            if getattr(self, "_audio_topology_task", None) is None:
                from dodaios.audio.topology import watch_topology

                self._audio_topology_task = asyncio.create_task(
                    watch_topology(self._player, self._output_device),
                    name="audio-topology-watch",
                )
                self._audio_topology_task.add_done_callback(
                    self._log_audio_topology_done
                )
            # Warming voice/wake STT above does not warm dictation's separate,
            # prompt-free provider. Start it only AFTER honest readiness so its
            # model load + first CUDA decode can never delay boot (AP-26).
            self._schedule_dictation_warmup()
            # Same for a local utterance engine that is not the wake engine.
            self._ensure_voice_stt_warmup()
        finally:
            # Never orphan the concurrently-started TTS init: if this deferred
            # task is cancelled (desktop shutdown) before the ``await tts_task``
            # join above is reached, CancelledError propagates straight here. Cancel
            # + await it so a late ``_ensure_client`` failure can't surface as an
            # unretrieved-exception warning under pythonw.exe. No-op on the normal
            # path (tts_task already awaited → done). Swallowed; re-raises the
            # original CancelledError after cleanup.
            if not tts_task.done():
                tts_task.cancel()
                try:
                    await tts_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                    # Preserve the original cancellation after owned-task cleanup.
                    pass

    async def _warmup_phase_b(self) -> None:
        """Background pre-render of confirmation audio (never blocks ready).

        Order matters: the wake ACK "Ja?" is rendered first (highest priority —
        it is the immediate wake feedback), then the task-ack phrases are
        rendered concurrently. Fully guarded; any failure degrades to the chime.
        """
        bg_start = time.monotonic()
        await self._prerender_ack_phrase()
        await self._prerender_task_acks()
        bg_ms = (time.monotonic() - bg_start) * 1000.0
        log.info("Warm-up Phase B (confirmation audio) done in %.0f ms.", bg_ms)

    async def _prerender_ack_phrase(self) -> None:
        """Cache the wake-ACK phrase ("Ja?") PCM, or fall back to the chime."""
        # Skip the ACK pre-render when the phrase is empty (user preference: no
        # spoken wake reaction, chime only). Gemini-TTS would raise an API error
        # on "" anyway.
        if not self._ack_phrase:
            log.info("ACK phrase disabled — chime only on wake.")
            self._ack_pcm = b""
            return
        try:
            log.info("Pre-rendering ACK phrase '%s' …", self._ack_phrase)
            chunks: list[AudioChunk] = []
            async for c in self._tts.synthesize(self._ack_phrase):
                chunks.append(c)
            self._ack_pcm = b"".join(c.pcm for c in chunks)
            log.info("ACK phrase cached (%d KB).", len(self._ack_pcm) // 1024)
        except Exception as exc:  # noqa: BLE001
            log.warning("ACK pre-render failed (%s) — chime only as feedback.", exc)
            self._ack_pcm = b""

    async def _stabilize_audio_devices(self) -> None:
        """Wait for the audio device enumeration to settle, then re-resolve the
        output device against the now-fresh PortAudio table.

        Permanent cure for the post-reboot device-index drift (BUG-014 class):
        Jarvis can autostart before Windows finishes enumerating audio
        endpoints, freezing a partial table that points the speaker index at a
        stale/silent device. Fully guarded — must never block or break boot.
        """
        try:
            # If the launcher prefetched the (blocking ~1.5 s) device settle in a
            # daemon thread at boot, reuse its already-settled result instead of
            # re-paying the poll wait on the wake-critical path. Falls back to a
            # fresh settle when no prefetch ran / it is still polling — identical
            # to today's behavior, so this can only help, never slow boot.
            from dodaios.audio.device_init import get_prefetched_audio_result

            info = get_prefetched_audio_result()
            if info is None:
                info = await asyncio.to_thread(wait_for_stable_audio_devices)
            log.info(
                "Audio-Geräte stabilisiert: %d Geräte (stable=%s, %.1fs, %d reinit).",
                info.get("device_count", 0),
                info.get("stable"),
                info.get("waited_s", 0.0),
                info.get("reinits", 0),
            )
            self._player.set_device(self._output_device)
        except Exception as exc:  # noqa: BLE001 — audio robustness never breaks boot
            log.warning("Audio-Geräte-Stabilisierung übersprungen (%s).", exc)

    async def _play_ready_cue(self) -> None:
        """Play the ascending boot-ready tone once. Silent no-op on a headless
        VPS / when no output device exists, or when the global "Sound effects"
        switch is off — never raises."""
        await self._play_earcon(READY_PCM)

    async def _prerender_task_acks(self) -> None:
        phrases = iter_all_start_ack()
        log.info("Pre-rendere %d Task-Ack-Phrasen …", len(phrases))

        async def _render_one(lang: str, phrase: str) -> bool:
            """Render + cache one phrase. Returns True on a non-empty cache.

            Each call writes a distinct ``(lang, phrase)`` key into the shared
            dict; the write sits between two awaits, so the cooperative
            event-loop scheduler never preempts it (these are asyncio tasks on
            one loop, not OS threads) — concurrent writes are safe without a
            lock. A single failure degrades to no cache entry → chime fallback,
            never raises.
            """
            try:
                chunks: list[AudioChunk] = []
                try:
                    it = self._tts.synthesize(phrase, language_code=self._bcp47(lang))
                except TypeError:
                    it = self._tts.synthesize(phrase)
                async for c in it:
                    chunks.append(c)
                pcm = b"".join(c.pcm for c in chunks)
                if pcm:
                    self._task_ack_pcm[(lang, phrase)] = pcm
                    return True
            except Exception as exc:  # noqa: BLE001
                log.warning("Task-Ack pre-render '%s' (%s) fehlgeschlagen: %s", phrase, lang, exc)
            return False

        # Render all phrases concurrently — the dominant warm-up cost was these
        # ~20 sequential TTS round-trips. _render_one never raises, so a plain
        # gather is enough (no return_exceptions needed).
        results = await asyncio.gather(*(_render_one(lang, phrase) for lang, phrase in phrases))
        ok = sum(1 for r in results if r)
        log.info("Task-Ack-Cache: %d/%d Phrasen bereit.", ok, len(phrases))

    # ------------------------------------------------------------------
    # Hotkey-Loop
    # ------------------------------------------------------------------

    async def _hotkey_loop(self, trigger: HotkeyTrigger) -> None:
        async for event_name in trigger.events():
            # One raising handler must not end this loop: it is the ONLY
            # consumer of every global shortcut, and its death is invisible
            # from the desktop (a log line the WebView cannot show) — every
            # key simply stops working until a restart. The edge is dropped,
            # the next one is served (AP-18 for the hotkey lane, BUG-191).
            try:
                self._dispatch_hotkey_event(event_name)
            except Exception:  # noqa: BLE001 — contained on purpose, logged in full
                log.exception("Hotkey %r handler failed; the edge was dropped.", event_name)

    def _dispatch_hotkey_event(self, event_name: str) -> None:
        """Route one hotkey edge to its handler (the body of ``_hotkey_loop``)."""
        if event_name == "call":
            log.info("📞 CALL via Hotkey")
            # A deliberate key press — exempt from the post-hangup wake
            # lock (no speaker-echo path), same contract as PTT below. It is
            # also the gesture that may ask macOS for the microphone: the first
            # press of an undecided microphone raises the dialog and starts
            # nothing ("allowed - press again").
            if self._state == PipelineState.IDLE and self._activation_state_allows():
                refusal = self._ensure_microphone("voice")
                if refusal is not None:
                    log.info("Call key ignored: %s", refusal)
                    return
            self._explicit_call_pending = True
            self._call_event.set()
        elif event_name == "dictate_press":
            self._on_dictate_press()
        elif event_name == "dictate_release":
            self._on_dictate_release()
        elif event_name == "dictate_cancel":
            self._on_dictate_cancel()
        elif event_name == "dictate_early":
            self._on_dictate_early()
        elif event_name == "dictate_abandon":
            self._on_dictate_abandon()
        elif event_name == "dictate":
            # Legacy [dictation].mode = "toggle": one press starts, the
            # next stops. Only reached when the HOLD key is in toggle mode.
            self._on_dictate_toggle()
        elif event_name == "dictate_toggle":
            # The dedicated hands-free key. Same handler, its own binding.
            self._on_dictate_toggle()
        elif event_name == "paste_last":
            self._on_paste_last()
        elif event_name == "hangup":
            log.info("📵 HANGUP via Hotkey")
            self._trigger_voice_hangup()

    # ------------------------------------------------------------------
    # Dictation hotkey edges
    # ------------------------------------------------------------------

    def _on_dictate_press(self) -> None:
        """Dictation key DOWN — start recording into the focused text field.

        Idempotent by design: every backend reports a press exactly once per
        real chord-down (the Windows poller too — ``HotkeyChecker.run`` fires
        ``on_press`` only on the ``key_state != 1`` transition, whatever older
        comments in this file claimed), but a stray duplicate edge inside the
        grace window is still treated as the same hold. Only the first edge
        from "key up" starts anything.

        **The latch heals itself.** A key-up edge can be lost — the pynput and
        Quartz backends clear their own chord state without firing ``on_release``
        when the input permission is revoked mid-chord, and a focus change, a
        UAC prompt or an RDP reconnect can do the same. A latch that only a
        release could clear then swallowed EVERY later press, which presents as
        "the dictation shortcut just stopped working" with no error and no way
        back except an app restart. So a press that arrives long after the last
        one reported the key down is treated as what it physically is — a fresh
        press on a key nobody is holding — not as a repeat. A second press edge
        can only exist if the chord went up in between, so anything past the
        grace window is either a lost key-up or a genuinely new press, and both
        want the same repair.

        **A press while a dictation nobody is holding is running is its STOP**
        (BUG-191). The latch says "up", yet the lane is busy: a hands-free key,
        the bar, a REST call started it — or a release edge never made it here
        and the recording is still open. Before this, that press went to
        ``start_dictation``, was refused as ``already_running`` (a refusal the
        bar deliberately paints as nothing), and the latch was dropped again:
        the key did nothing, visibly, forever, and only a restart ended the
        recording. The dictation key is the kill switch of its own lane — an
        explicit press ends whatever is running and delivers it, which is what
        the user pressing it means.
        """
        if getattr(self, "_dictate_early_pending", False):
            # The confirmation of a solo hold key whose recording already
            # started at key-down (``_on_dictate_early``): it is a dictation
            # now, and the release submits it. Nothing else to do: should the
            # early recording have ended meanwhile, this hold started one
            # already, and a second one on the same hold would surprise.
            self._dictate_early_pending = False
            log.debug("Dictation key held alone — the early recording stays.")
            return
        now = time.monotonic()
        last_seen = float(getattr(self, "_dictate_key_seen_at", 0.0))
        latched = bool(getattr(self, "_dictate_key_down", False))
        stale = latched and (now - last_seen) > _DICTATE_HOLD_REPEAT_GRACE_S
        self._dictate_key_seen_at = now
        if latched and not stale:
            return  # the same hold, re-reported inside the grace window
        if stale:
            log.info(
                "Dictation key-up edge was lost %.1fs ago — clearing the stale "
                "hold latch so the shortcut keeps working.",
                now - last_seen,
            )
            self._dictate_key_down = False
            if self.dictation_active():
                # The orphaned recording is still running with the microphone
                # open. Treat this press as the release that never arrived:
                # finish and deliver what was said instead of starting a second
                # dictation on top of it. The latch is clear, so the user's next
                # press starts a fresh one.
                self.stop_dictation()
                return
        if self.dictation_active():
            log.info(
                "Dictation key pressed while a dictation nobody is holding is "
                "still running (via=%s, %.1fs since the last edge) — finishing "
                "it instead of refusing the press.",
                getattr(self, "_dictation_started_by", "") or "unknown",
                now - last_seen if last_seen else 0.0,
            )
            self.stop_dictation()
            return
        self._dictate_key_down = True
        log.info("Dictation key down — starting a hold recording.")
        if not self.start_dictation(
            target=self._configured_dictation_target(), source="hold_key"
        ):
            # Could not start (no microphone, no STT). Drop the latch
            # immediately so the NEXT press is a fresh attempt rather than
            # being swallowed as a repeat. A live voice session is NOT one of
            # these: it is accepted and handed over, and the latch has to stay
            # so the release can cancel a handover that is still running.
            self._dictate_key_down = False

    def _on_dictate_early(self) -> None:
        """A modifier-only hold key went down ALONE: start recording at once.

        Such a key (a bare ``cmd``) is confirmed as a dictation only after it
        was held alone for ``SOLO_HOLD_S``, because it is also the first half
        of every shortcut that uses it. Waiting for that before anything
        happened made the Dodaios Bar rise a noticeable moment after the key
        went down (reported 2026-11-14). So the recording, and with it the
        bar, starts here at key-down, on approval: ``dictate_press`` confirms
        it, ``dictate_abandon`` (a shortcut, or a tap) takes it back without a
        trace.

        Only the plain start is taken early. Everything that would be seen or
        felt when the hold turns out to be ``cmd+c`` waits for the
        confirmation, which then runs the ordinary press: a refusal (it paints
        a cross on the bar), a voice conversation (the handover hangs it up,
        and beside a live call its input is held), a dictation that is already
        running (the press is its stop) and a microphone macOS has not decided
        on yet (the press may raise the system dialog).
        """
        if getattr(self, "_dictate_key_down", False) or self.dictation_active():
            return
        if not self._dictation_can_start_quietly():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # the confirmation's ordinary press says why
        self._dictate_key_seen_at = time.monotonic()
        self._dictate_key_down = True
        self._dictate_early_pending = True
        log.info("Dictation key down alone — starting the hold recording at once.")
        self._commit_dictation(
            loop, target=self._configured_dictation_target(), source="hold_key"
        )

    def _dictation_can_start_quietly(self) -> bool:
        """Would a dictation start right now with nothing but its bar to show?

        ``start_dictation``'s checks without any of its side effects: nothing
        is refused, published or asked. ``False`` for anything that is not the
        plain start.
        """
        if getattr(self, "_utterance_stt", None) is None:
            return False
        if self._live_call_owns_microphone() or self._voice_session_holds_microphone():
            return False
        if not self._user_capture_allowed():
            return False
        try:
            state = self._permission_service().check("microphone")
        except Exception:  # noqa: BLE001 - unknown: the confirmed press asks properly
            log.debug("Microphone state unreadable for an early dictation start.", exc_info=True)
            return False
        return str(getattr(state, "value", state)) in ("granted", "not_required")

    def _on_dictate_abandon(self) -> None:
        """The early start of a solo hold key was a shortcut or a tap: undo it.

        Another key joined inside the window (``cmd+c``), or the key went up
        before it (a tap on Command). Nobody dictated, so the recording goes
        the way the bar's X sends it, and leaves nothing behind: no history
        row, no statistics, no "nothing was heard" mark. The bar rests again.
        """
        if not getattr(self, "_dictate_early_pending", False):
            return  # nothing started early; the confirmation never came either
        self._dictate_early_pending = False
        if not getattr(self, "_dictate_key_down", False):
            return
        self._dictate_key_down = False
        if not self.dictation_active():
            return
        log.info("Dictation key was a shortcut or a tap — taking the early recording back.")
        self._dictation_leave_no_trace = True
        self.request_dictation_stop(discard=True)

    def _on_dictate_release(self) -> None:
        """Dictation key UP — stop recording and submit what was held."""
        if not self._dictate_key_down:
            log.debug("Dictation key up with no hold latched — nothing to submit.")
            return
        self._dictate_key_down = False
        log.info(
            "Dictation key up after %.1fs — submitting the hold recording.",
            time.monotonic() - float(getattr(self, "_dictate_key_seen_at", 0.0) or 0.0),
        )
        self.stop_dictation()

    def _on_dictate_cancel(self) -> None:
        """Another key joined a modifier-only hold key: it was a shortcut.

        Only a modifier-only dictation key sends this (``SOLO_HOLD_EVENTS``),
        when a key or click joins after the hold had already started the
        recording: ``cmd`` held a moment, then ``tab``. The recording is
        discarded the way the bar's X discards it, so nothing is read or
        typed, no "nothing was heard" mark follows, and the bar rests at once.
        """
        if not self._dictate_key_down:
            log.debug("Dictation key cancel with no hold latched — nothing to discard.")
            return
        self._dictate_key_down = False
        log.info("Dictation key joined by another key — discarding the hold recording.")
        self.request_dictation_stop(discard=True)

    def _on_dictate_toggle(self) -> None:
        """Toggle mode: start if idle, stop if running.

        ``dictation_active`` covers the handover window too, so the second press
        of a hands-free toggle cancels a voice-session handover that has not
        finished instead of falling through and asking for a second dictation.
        """
        if self.dictation_active():
            log.info("Dictation toggle key — stopping the running dictation.")
            self.stop_dictation()
            return
        log.info("Dictation toggle key — starting a hands-free recording.")
        self.start_dictation(
            target=self._configured_dictation_target(), source="toggle_key"
        )

    def _on_paste_last(self) -> None:
        """"Insert the last dictation again" key — re-deliver the last transcript.

        Needs no microphone, no speech-to-text and no recording, which is the
        whole point: it stays useful exactly where dictation itself cannot run.

        Scheduled as a task rather than executed here, because the work behind
        it is blocking — it parses the history file and sleeps around the paste
        chord — and this handler runs ON the pipeline's event loop, the same
        loop a live voice turn uses (AP-9). A press while one is still running
        is dropped rather than queued: two overlapping pastes race over the
        clipboard restore and the loser puts the WRONG content back.
        """
        if getattr(self, "_paste_last_busy", False):
            log.debug("paste-last key ignored: a paste is already in flight")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("paste-last key ignored: no running event loop")
            return
        self._paste_last_busy = True
        loop.create_task(self._paste_last_dictation(), name="dictation-paste-last")

    async def _paste_last_dictation(self) -> None:
        """The blocking half of :meth:`_on_paste_last`. Never raises.

        Goes through ``insert_last_dictation`` — the SAME delivery path the
        REST route and a fresh dictation use — so the three can never drift
        apart. Anything short of "the text was typed where you were pointing"
        is announced on the bus instead of logged: the reported bug for this
        whole feature was a key that looked bound and did nothing visible.
        """
        try:
            from dodaios.dictation.insert import insert_last_dictation

            result = await asyncio.to_thread(
                insert_last_dictation, settings=getattr(self, "_dictation_cfg", None)
            )
        except Exception as exc:  # noqa: BLE001 — a paste is never worth a crash
            log.warning("paste-last failed (non-fatal)", exc_info=True)
            self._refuse_dictation(
                "paste_unavailable",
                "The last dictation could not be pasted again "
                f"({type(exc).__name__}).",
            )
            return
        finally:
            self._paste_last_busy = False

        reason = str(getattr(result, "reason", "") or "")
        detail = str(getattr(result, "detail", "") or "")
        insert = getattr(result, "insert", None)
        status = str(getattr(insert, "status", "") or "")
        log.info(
            "📋 paste-last: ok=%s reason=%s status=%s (%d chars)",
            bool(getattr(result, "ok", False)),
            reason or "-",
            status or "-",
            len(str(getattr(result, "text", "") or "")),
        )
        if getattr(result, "ok", False) and status not in ("clipboard_only", "paste_sent"):
            return  # the text is in the field the user was looking at — proof enough
        # Everything else owes an explanation: nothing saved, history off, or a
        # host that cannot type into another window (the text is on the
        # clipboard then, which the detail sentence says).
        token = {
            "not_found": "nothing_to_paste",
            "history_disabled": "history_disabled",
        }.get(reason, "paste_unavailable")
        self._refuse_dictation(
            token, detail or "The last dictation could not be pasted again."
        )

    def _configured_dictation_target(self) -> str:
        """``[dictation].target`` — ``auto`` by default, resolved at start."""
        cfg = getattr(self, "_dictation_cfg", None)
        return str(getattr(cfg, "target", "auto") or "auto")

    def request_voice_session(
        self, *, seed_messages: list[tuple[str, str]] | None = None
    ) -> bool:
        """``start_voice_session`` for a caller that only needs armed / not armed."""
        return not self.start_voice_session(seed_messages=seed_messages)

    def _activation_state_refusal(self) -> str:
        """Which half of ``_activation_state_allows`` said no, as a refusal code."""
        if getattr(self, "_muted", False):
            return start_refusal.MUTED
        if self._dictation_blocks_activation():
            return start_refusal.DICTATION
        return start_refusal.MICROPHONE_IN_USE

    def start_voice_session(
        self, *, seed_messages: list[tuple[str, str]] | None = None
    ) -> str:
        """Arm a wake-style voice session from outside the audio path.

        The "Speak in this conversation" button (``POST /api/chats/{kind}/
        {cid}/speak``) calls this to start a session that already remembers a
        past conversation — functionally "Hey Jarvis", but with seeded context.

        Web routes run on the pipeline loop, while the native Jarvis Bar calls
        this from its dedicated Tk thread. The final arming edge is therefore
        marshalled through the owner loop when necessary; setting an
        ``asyncio.Event`` directly from Tk can leave the selector asleep until
        unrelated I/O happens to wake it.

        Returns ``""`` when the session was armed, otherwise the one reason it
        was not, from ``dodaios.speech.start_refusal`` (a no-op: a session is
        already active or arming, voice is muted, a dictation or a browser call
        holds the microphone, or the microphone is not granted). The caller
        shows that reason; it must never guess one. The brain is seeded ONLY
        when we actually arm, so a rejected request never pollutes an unrelated
        in-flight session's history. Like PTT (an explicit user action with no
        audio-echo path), the post-hangup wake-lock is intentionally not
        consulted here.
        """
        if self._state != PipelineState.IDLE:
            log.info("request_voice_session ignored: pipeline not idle.")
            return start_refusal.BUSY
        if not self._activation_state_allows():
            log.info(
                "request_voice_session ignored: %s",
                self._activation_block_reason(explicit=True, include_permission=False)
                or "another call owns the microphone",
            )
            return self._activation_state_refusal()
        # Gesture entry: the speak button / bar click may ask macOS for the
        # microphone. A first request raises the dialog and returns False (the UI
        # says "allowed - press again"); the session is never armed retroactively.
        # A denied microphone reaches ``ensure`` too (toast, not silence).
        refusal = self._ensure_microphone("voice")
        if refusal is not None:
            log.info("request_voice_session ignored: %s", refusal)
            return start_refusal.MICROPHONE
        if seed_messages:
            brain = getattr(self, "_brain", None)
            seed = getattr(brain, "seed_history", None)
            if callable(seed):
                try:
                    seed(seed_messages)
                except Exception:  # noqa: BLE001 — seeding must never block arming
                    log.warning(
                        "request_voice_session: brain seed failed", exc_info=True
                    )
        self._last_wake_keyword = "chat_resume"
        log.info(
            "Voice session requested (wake-style, seeded=%d turns).",
            len(seed_messages or []),
        )
        self._explicit_call_pending = True
        return "" if self._arm_call_event() else start_refusal.UNAVAILABLE

    def request_voice_hangup(self) -> bool:
        """Hang up the voice channel from outside the audio path.

        The voice orb's click and ``jarvis api voice hangup`` land here — the
        same absolute-kill contract as the hangup hotkey (2026-05-20: no matter
        what is playing or queued, the voice channel goes silent now). Safe to
        call while idle; answers ``False`` instead of raising so a UI click can
        report honestly rather than 500.
        """
        try:
            self._trigger_voice_hangup()
            return True
        except Exception:  # noqa: BLE001 — a failed hangup must report, never raise
            log.warning("request_voice_hangup failed", exc_info=True)
            return False

    def _arm_call_event(self) -> bool:
        """Set the call edge on its owning asyncio loop.

        Native overlay callbacks run on a Tk thread. ``asyncio.Event.set`` may
        flip the flag from that thread without waking the loop's selector, so
        the state task resumes only after an unrelated timer or socket event.
        ``call_soon_threadsafe`` provides both the wakeup and the memory edge.
        Same-loop callers retain the direct, allocation-free path.
        """
        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(self._call_event.set)
                return True
            except RuntimeError:
                log.warning("Voice session request failed: owner loop is closed.")
                return False
        self._call_event.set()
        return True

    def voice_engine_status(self) -> dict[str, Any]:
        """Snapshot the voice call state for the UI.

        ``active_session_provider``/``model`` name what the open call really
        uses; they stay empty until its provider confirmed the session.
        """
        session_id = getattr(self, "_current_voice_session_id", None)
        return {
            "session_active": bool(session_id),
            "session_id": str(session_id or ""),
            "active_session_provider": getattr(self, "_active_realtime_provider", ""),
            "active_session_model": getattr(self, "_active_realtime_model", ""),
            "transitioning": bool(
                getattr(self, "_voice_engine_transitioning", False)
                or getattr(self, "_reopen_after_engine_change", False)
            ),
            # Why the LAST realtime start attempt failed (None once a session
            # is up): {provider, message, at}. The surfaces render it when a
            # connecting window closes without a session instead of falling
            # silently back to "idle".
            "last_start_error": getattr(self, "_last_realtime_start_error", None),
        }

    def reconnect_realtime_session(self, *, reason: str) -> bool:
        """Reconnect an active realtime call after provider/model changes."""
        if self._state == PipelineState.IDLE:
            return False
        return self._schedule_engine_reopen(reason)

    def _schedule_engine_reopen(self, reason: str) -> bool:
        if self._state == PipelineState.IDLE:
            return False
        self._reopen_after_engine_change = True
        self._engine_change_reason = str(reason or "configuration_change")
        self._voice_engine_transitioning = True
        log.info(
            "Voice engine changed during an active session; reconnecting (%s).",
            self._engine_change_reason,
        )
        self._trigger_voice_hangup()
        return True

    def _post_hangup_lock_seconds(self) -> float:
        """Wake-lock duration for the session that just ended (one-shot).

        SHORT (`_explicit_hangup_lock_s`) after a user HARD hangup — the
        JarvisBar close / hotkey / "auflegen" stopped the player, so there is no
        TTS tail to echo and the long lock would only swallow the user's very
        next "Hey <wake>". Otherwise the FULL `_post_hangup_lock_s` guards the
        speaker tail of a natural end / farewell. Consumes the hard-hangup flag
        so it applies to exactly one session end.
        """
        hard = self._explicit_hard_hangup
        self._explicit_hard_hangup = False
        return self._explicit_hangup_lock_s if hard else self._post_hangup_lock_s

    def request_hangup(self) -> None:
        """End the live voice session from outside the audio path.

        The jarvis-bar's hover-to-close cross calls this (and any future UI
        close affordance). The bar runs on a dedicated Tk thread, while the
        hangup event and its waiters belong to the pipeline's asyncio loop.
        Marshal the complete hard-stop chokepoint onto that owning loop; calling
        ``asyncio.Event.set()`` directly from Tk is unsupported and can fail to
        wake the waiter until unrelated I/O arrives. Repeated clicks during one
        teardown are idempotent. A no-op request while idle is cleared when the
        next session starts.
        """
        pending = getattr(self, "_external_hangup_pending", None)
        handoff_close = getattr(self, "_wake_handoff_hangup_pending", None)
        handoff_ready = bool(
            getattr(self, "_state", PipelineState.IDLE) is PipelineState.IDLE
            and getattr(self, "_wake_handoff_ready", None)
            and self._wake_handoff_ready.is_set()
        )
        candidate_active = bool(
            getattr(self, "_state", PipelineState.IDLE) is PipelineState.IDLE
            and getattr(self, "_wake_preroll_active", False)
        )
        if handoff_ready and handoff_close is not None:
            # Set synchronously on the caller thread. The owner-loop callback
            # can otherwise lose a race with the already-armed state task.
            handoff_close.set()
        if (
            pending is not None
            and pending.is_set()
            and not handoff_ready
            and not candidate_active
        ):
            # A second stop gesture while the first is still being honoured
            # is idempotent — unless the first one is OLD. A hangup that has
            # been "pending" for many seconds with the session still active
            # is a teardown that never finished (BUG-185: a swallowed cancel
            # left the pipeline stuck in its own finally for an afternoon).
            # That must not vanish at debug level: say it, and let the
            # request through so the chokepoint runs again.
            requested_at = float(getattr(self, "_hangup_requested_at", 0.0) or 0.0)
            age = time.monotonic() - requested_at if requested_at else 0.0
            if age < _HANGUP_LATCH_STALE_S:
                log.debug("request_hangup ignored: external hangup already pending")
                return
            log.warning(
                "request_hangup: a hangup has been pending for %.1fs and the "
                "voice session is still active — the teardown did not finish; "
                "delivering the stop again (BUG-185).",
                age,
            )
        if pending is not None:
            pending.set()
        self._hangup_requested_at = time.monotonic()
        log.info("📵 request_hangup — closing the voice session")

        def _dispatch() -> None:
            try:
                if (
                    getattr(self, "_state", PipelineState.IDLE)
                    is PipelineState.IDLE
                    and getattr(self, "_wake_handoff_ready", None)
                    and self._wake_handoff_ready.is_set()
                    and handoff_close is not None
                ):
                    handoff_close.set()
                if (
                    getattr(self, "_state", PipelineState.IDLE)
                    is PipelineState.IDLE
                    and getattr(self, "_wake_preroll_active", False)
                ):
                    # The bar can be visible during wake verification before a
                    # real session exists. Its X cancels that candidate; it
                    # must not be reinterpreted as a new voice-session click.
                    cancel_event = getattr(self, "_wake_cancel_event", None)
                    if cancel_event is not None:
                        cancel_event.set()
                    if pending is not None:
                        pending.clear()
                    return
                self._trigger_voice_hangup()
            except Exception:
                # A failed dispatch must be retryable; successful requests stay
                # latched until the authoritative session teardown reaches IDLE.
                if pending is not None:
                    pending.clear()
                raise

        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(_dispatch)
                return
            except RuntimeError:
                # The loop closed between is_running() and scheduling. The
                # synchronous fallback still stops audio/CU and is harmless
                # when no asyncio waiter remains alive.
                log.debug("request_hangup: owner loop closed during dispatch")
        _dispatch()

    def is_session_active(self) -> bool:
        """Ground truth for "a live voice session is in progress right now".

        The jarvis-bar uses this to decide whether a close-X click is a real
        hang-up or a useless no-op. The bar's visual mode can get stuck in the
        active "listen" look when a wake popped it but the post-hangup wake-lock
        cooldown rejected the session — no ``VoiceSessionStarted`` is published
        and no ``IDLE`` state follows, so nothing resets the bar (freeze
        forensic 2026-06-28).

        ``_state`` becomes ACTIVE before ``VoiceSessionStarted`` is published,
        while ``_turn_state`` does not leave IDLE until every start subscriber
        returns. A slow subscriber therefore creates a real session-start window
        where checking only the turn-state misclassifies the visible X as an
        idle-body click and calls ``request_voice_session()`` instead of hanging
        up. Treat either lifecycle signal as active so the close control remains
        valid throughout startup, the live turn, and teardown. A visible wake
        candidate also counts as active for this control only: its close action
        routes to ``request_hangup()``, which retracts the pending candidate
        instead of accidentally starting a session.
        """
        return (
            getattr(self, "_state", PipelineState.IDLE) is not PipelineState.IDLE
            or
            getattr(self, "_turn_state", TurnTakingState.IDLE)
            is not TurnTakingState.IDLE
            or bool(getattr(self, "_wake_preroll_active", False))
            or bool(
                getattr(self, "_wake_handoff_ready", None)
                and self._wake_handoff_ready.is_set()
            )
        )

    def _trigger_voice_hangup(self, *, stop_player: bool = True) -> None:
        """Hard-stop the voice channel — the single hangup chokepoint.

        User intent (2026-05-20): "auflegen" is an absolute kill switch.
        No matter what Jarvis is currently saying, announcing, or queueing,
        a hangup must silence the voice channel immediately. Background
        Jarvis-Agent missions keep running (they live in their own subprocess
        + Job Object); only their *voice readback* is suppressed via the
        ``_hangup_event`` gate on the bus-driven announcement handlers.

        ``stop_player=False`` is used when the brain itself emitted the
        farewell ("Goodbye.") — we let that final utterance play.
        """
        confirmation = getattr(self, "_hangup_confirmation", None)
        if confirmation is not None:
            confirmation.reset()

        if not getattr(self, "_termination_producer", ""):
            self._termination_producer = "speech.pipeline._trigger_voice_hangup"
        if stop_player:
            try:
                self._player.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("Stopping the player during hangup failed: %s", exc)
            # Player stopped => no TTS tail => the next session end uses the
            # SHORT wake-lock so the user can re-wake immediately. A farewell
            # hangup (stop_player=False) keeps the full speaker-tail guard.
            self._explicit_hard_hangup = True
        self._hangup_event.set()
        # BUG-CU-HANGUP (2026-05-28): "auflegen" must also STOP a running
        # Computer-Use mission immediately — otherwise Jarvis keeps clicking
        # the screen in the background after the user told it to stop. This is
        # CU-scoped (cancels only the active CU token), so Jarvis-Agent
        # background missions are unaffected (their voice readback is muted via
        # the _hangup_event gate, matching the documented hangup contract).
        try:
            from dodaios.harness.computer_use_context import cancel_active_cu
            if cancel_active_cu("voice_hangup"):
                log.info("Voice-Hangup: active Computer-Use mission cancelled.")
        except Exception:  # noqa: BLE001 — hangup must never crash
            log.debug("CU cancel-on-hangup failed (non-fatal)", exc_info=True)
        # The X must also stop a CHAT turn, not only a voice turn. A chat turn
        # runs on a separate dispatcher (``desktop_app._on_user_message``) that
        # never observes ``_hangup_event`` — so before this it kept thinking
        # through every X press (live bug 2026-06-19: ~27 ignored presses). The
        # cancel is edge-triggered and loop-safe (this may run on the Tk thread).
        try:
            from dodaios.core.runtime_refs import cancel_active_chat_turn
            if cancel_active_chat_turn():
                log.info("Voice-Hangup: active chat turn cancelled.")
        except Exception:  # noqa: BLE001 — hangup must never crash
            log.debug("chat-turn cancel-on-hangup failed (non-fatal)", exc_info=True)

    # ------------------------------------------------------------------
    # Wake loop and capture handoff
    # ------------------------------------------------------------------

    def _begin_wake_preroll(
        self, recent: tuple[AudioChunk, ...] = ()
    ) -> None:
        """Retain audio from the first truthful wake visual onward."""
        if self._wake_preroll_active:
            return
        self._pending_session_preroll.clear()
        self._pending_session_preroll.extend(recent)
        self._wake_preroll_active = True
        self._wake_preroll_confirmed = False

    def _discard_wake_preroll(self) -> None:
        self._wake_preroll_active = False
        self._wake_preroll_confirmed = False
        self._pending_session_preroll.clear()

    def _take_wake_preroll(self) -> tuple[AudioChunk, ...]:
        chunks = (
            tuple(self._pending_session_preroll)
            if self._wake_preroll_confirmed
            else ()
        )
        self._discard_wake_preroll()
        return chunks

    async def _claim_wake_capture_for_session(
        self,
    ) -> _SessionInputBuffer | None:
        """Transfer the live wake mic to the session without closing it."""
        if self._wake_handoff_ready.is_set():
            buffer = self._wake_handoff_buffer
            self._wake_handoff_buffer = None
            self._wake_handoff_ready.clear()
            if buffer is None:
                raise RuntimeError("Wake microphone offered an empty handoff.")
            return buffer
        if self._wake_capture_released.is_set():
            # The wake task may already have passed its IDLE check and be one
            # scheduling turn away from entering the capture context. Give it
            # that turn before deciding no wake microphone exists; otherwise a
            # hotkey can open a second native stream during the pre-open race.
            await asyncio.sleep(0)
            if self._wake_capture_released.is_set():
                return None
        self._wake_stop_event.set()
        handoff_wait = asyncio.create_task(
            self._wake_handoff_ready.wait(), name="wake-handoff-ready"
        )
        release_wait = asyncio.create_task(
            self._wake_capture_released.wait(), name="wake-capture-release"
        )
        try:
            await asyncio.wait(
                {handoff_wait, release_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (handoff_wait, release_wait):
                if not task.done():
                    task.cancel()
            for task in (handoff_wait, release_wait):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._wake_stop_event.clear()
        # Prefer a concrete handoff if readiness and physical release raced in
        # the same loop tick. Otherwise the old wake stream is authoritatively
        # closed and the caller may safely open one fallback capture.
        if not self._wake_handoff_ready.is_set():
            if self._wake_capture_released.is_set():
                return None
            raise RuntimeError("Wake microphone ownership ended ambiguously.")
        buffer = self._wake_handoff_buffer
        self._wake_handoff_buffer = None
        self._wake_handoff_ready.clear()
        if buffer is None:
            raise RuntimeError("Wake microphone handoff produced no input buffer.")
        return buffer

    async def _abort_pending_wake_handoff(self) -> None:
        """Release an offered wake stream when the state loop rejects the call."""
        wake_capture_was_open = not self._wake_capture_released.is_set()
        preview_was_visible = bool(
            self._wake_preroll_active or self._wake_handoff_ready.is_set()
        )
        self._discard_wake_preroll()
        try:
            buffer = await self._claim_wake_capture_for_session()
        except Exception as exc:  # noqa: BLE001 - rejection must not kill state loop
            log.warning("Pending wake handoff could not be released: %s", exc)
            self._wake_cancel_event.set()
            self._wake_handoff_hangup_pending.clear()
            self._external_hangup_pending.clear()
            self._hangup_event.clear()
            self._explicit_hard_hangup = False
            return
        if buffer is not None:
            await buffer.close()
            await self._wake_capture_released.wait()
        try:
            if preview_was_visible or wake_capture_was_open or buffer is not None:
                # WakeWordDetected may already have put the bar into LISTENING
                # even though no VoiceSessionStarted will follow. Explicitly
                # retract that preview so UI state matches the mic lease.
                await self._publish_event(
                    WakeCandidateDetected(source_layer="speech", active=False)
                )
        finally:
            self._wake_handoff_hangup_pending.clear()
            self._external_hangup_pending.clear()
            self._hangup_event.clear()
            self._explicit_hard_hangup = False

    def _realtime_browser_audio(self, config: Any = None) -> bool:
        """Resolve browser audio with the live embedded renderer, when known."""
        from dodaios.realtime.factory import realtime_browser_audio

        renderer = None
        renderer_getter = getattr(self, "_realtime_audio_renderer", None)
        if callable(renderer_getter):
            try:
                renderer = renderer_getter()
            except Exception as exc:  # noqa: BLE001 - keep the provider default on probe failure
                log.warning(
                    "Embedded audio renderer probe failed (%s); using provider default.",
                    type(exc).__name__,
                )
        selected_config = getattr(self, "_config", None) if config is None else config
        return realtime_browser_audio(selected_config, desktop_renderer=renderer)

    @asynccontextmanager
    async def _capture_first_session_input(
        self,
    ) -> AsyncIterator[_SessionInputBuffer]:
        """Borrow the wake mic or open exactly one fallback session mic."""
        config = getattr(self, "_config", None)
        # An unpinned engine is resolved from the credentials, so the answer
        # is read off the voice loop, like the session build.
        browser_media = bool(
            await _run_voice_critical_thread(lambda: self._realtime_browser_audio(config))
        )
        buffer = await self._claim_wake_capture_for_session()
        if browser_media and buffer is None:
            browser_buffer = _SessionInputBuffer()
            try:
                yield browser_buffer
            finally:
                await browser_buffer.close()
            return
        if buffer is not None:
            try:
                yield buffer
            finally:
                await buffer.close()
                # ``buffer.released`` lets the wake owner begin teardown. Wait
                # for the stronger signal too so no disconnect sound or engine
                # re-arm can race the still-open native microphone.
                await self._wake_capture_released.wait()
            return

        async with MicrophoneCapture(
            device=self._input_device,
            max_queue_chunks=REALTIME_QUEUE_CHUNKS,
            device_priority=self._input_priority,
        ) as mic:
            buffer = _SessionInputBuffer(capture=mic)

            async def _unmuted_capture() -> AsyncIterator[AudioChunk]:
                async for chunk in mic.stream():
                    # Filter at capture time, not only at the eventual consumer:
                    # a realtime fallback may replay retained frames after the
                    # user unmutes and must never resurrect muted audio.
                    if not getattr(self, "_muted", False):
                        yield chunk

            buffer.start(_unmuted_capture())
            try:
                yield buffer
            finally:
                await buffer.close()

    async def _release_unclaimed_wake_handoff(self) -> None:
        """Give back a wake stream that was offered but never taken.

        The wake owner parks on ``buffer.released`` once it has offered its
        stream, so a claimer that unwinds between the offer and the claim would
        strand it there — it cannot even reach its own cleanup. Closing the
        buffer here is the release signal. Safe to call when nothing is pending,
        and it never suspends for an offered handoff (that buffer has no pump
        task), so it also works from inside a task being cancelled.
        """
        buffer = getattr(self, "_wake_handoff_buffer", None)
        ready = getattr(self, "_wake_handoff_ready", None)
        if buffer is None and (ready is None or not ready.is_set()):
            return
        self._wake_handoff_buffer = None
        if ready is not None:
            ready.clear()
        if buffer is not None:
            await buffer.close()

    async def _claim_wake_capture_for_dictation(self) -> _SessionInputBuffer | None:
        """Take the wake microphone over for a dictation, or return ``None``.

        A dictation is a session start like any other: whatever already owns the
        input device hands the live stream over, so the two never run side by
        side. Without this the common case — the wake loop sitting in
        ``_run_parallel_wake``, its steady state whenever Jarvis is idle — meant
        a dictation key press opened a SECOND native input stream on the same
        device for the whole dictation (AP-24 / the BUG-014 family).

        ``None`` means "no wake stream exists"; the caller then opens exactly one
        capture of its own. A pipeline built via ``__new__`` (the unit-test
        pattern) has no wake plumbing at all and takes the same path.
        """
        if getattr(self, "_wake_handoff_ready", None) is None:
            return None
        try:
            return await self._claim_wake_capture_for_session()
        except asyncio.CancelledError:
            # A dictation cancelled INSIDE the handoff window would otherwise
            # leave the wake loop waiting forever on a stream nobody will ever
            # release: permanently deaf with an app restart as the only cure
            # (BUG-037). Give the offered stream back before unwinding.
            await self._release_unclaimed_wake_handoff()
            raise
        except Exception as exc:  # noqa: BLE001 — never a crashed dictation
            log.warning("Dictation could not take over the wake microphone: %s", exc)
            await self._release_unclaimed_wake_handoff()
        # The lease ended ambiguously. Waiting for the wake side to finish
        # closing is the only safe way to reach a fallback capture; opening one
        # now could be the second stream this whole path exists to prevent.
        try:
            await asyncio.wait_for(
                self._wake_capture_released.wait(),
                timeout=_DICTATION_WAKE_RELEASE_TIMEOUT_S,
            )
        except TimeoutError:
            raise RuntimeError(
                "The wake microphone did not release in time; refusing to open "
                "a second input stream for this dictation."
            ) from None
        return None

    @asynccontextmanager
    async def _capture_dictation_input(self) -> AsyncIterator[_ChunkSource]:
        """Own exactly ONE microphone for the duration of a dictation.

        Mirrors ``_capture_first_session_input``: borrow the live wake stream
        when there is one, otherwise open a single fallback capture. On the way
        out the borrowed stream is closed and the wake owner is awaited, so the
        wake loop re-arms its own microphone as soon as the dictation's block on
        activation lifts — including on the crash path, because the release runs
        in a ``finally``.

        Either way the stream ends up bound for a BULK consumer. That mattered
        more than it looked: the borrowed path is the one that actually runs on
        any install with a wake word, and it used to inherit the wake stream's
        shallow default. So the deep queue written for dictation below was dead
        code on exactly the machines that needed it, and a stalled loop cost
        seconds of speech — measured on the maintainer's box at 7.4 s gone from
        a 15.4 s recording, with nothing anywhere saying so.
        """
        buffer = await self._claim_wake_capture_for_dictation()
        if buffer is not None:
            restore_depth: int | None = None
            capture = getattr(buffer, "capture", None)
            if capture is not None:
                try:
                    restore_depth = capture.set_queue_depth(
                        _DICTATION_CAPTURE_QUEUE_CHUNKS
                    )
                except Exception:  # noqa: BLE001 — a bound is a safeguard, never a gate
                    log.debug("dictation could not deepen the capture queue", exc_info=True)
            try:
                yield buffer
            finally:
                if capture is not None and restore_depth is not None:
                    # Hand the wake detector its shallow bound back. Leaving the
                    # deep one on would trade this fix for the other failure:
                    # a wake word scored against seconds-stale audio.
                    try:
                        capture.set_queue_depth(restore_depth)
                    except Exception:  # noqa: BLE001 — teardown never fails a dictation
                        log.debug("capture queue depth not restored", exc_info=True)
                # ``close()`` sets ``released`` before it awaits anything, so
                # the wake owner is freed even if this task is being cancelled.
                await buffer.close()
                # BOUNDED. This used to wait forever, and a wake owner whose
                # teardown wedged would have held the dictation task — and
                # every "a dictation is already running" refusal — open until
                # a restart (BUG-191 family). The wake side is told, loudly,
                # and the dictation goes on to deliver what it recorded.
                try:
                    await asyncio.wait_for(
                        self._wake_capture_released.wait(),
                        timeout=_DICTATION_WAKE_RELEASE_TIMEOUT_S,
                    )
                except TimeoutError:
                    log.warning(
                        "The wake microphone did not confirm its release within "
                        "%.1fs after the dictation gave the stream back — "
                        "finishing the dictation anyway.",
                        _DICTATION_WAKE_RELEASE_TIMEOUT_S,
                    )
            return

        async with MicrophoneCapture(
            device=self._input_device,
            device_priority=self._input_priority,
            # A dictation is a BULK consumer: every frame is the user's words,
            # so the queue's drop-oldest policy deletes speech rather than
            # staleness. It cannot be turned off (the audio thread must never
            # block), so the defence is depth — enough slack that a slow
            # provider call cannot cost words.
            max_queue_chunks=_DICTATION_CAPTURE_QUEUE_CHUNKS,
            # A key press / button started this capture, so a lost grant is
            # reported as a user-origin ``dictation`` episode.
            permission_feature="dictation",
            interactive=True,
        ) as mic:
            yield mic

    def _wake_listening_enabled(self) -> bool:
        return self._openwakeword_enabled or self._whisper_wake_enabled

    async def _wait_while_wake_disabled(self) -> None:
        """Wait on ``_wake_reload_event`` while both wake detectors are off.

        Touches no permission and opens no episode: a switched-off wake word never
        owns the microphone permission (P7). Returns at once when a detector is on.
        """
        while not self._wake_listening_enabled():
            log.warning(
                "Both wake detectors are disabled — wake is PARKED until a "
                "wake-word change re-enables one (voice still works via hotkey). "
                "Waiting on a live wake-plan reload, not sleeping forever."
            )
            try:
                await asyncio.wait_for(self._wake_reload_event.wait(), timeout=30.0)
            except TimeoutError:
                pass  # the 30 s fallback poll: no reload came, the loop re-reads the plan
            finally:
                self._wake_reload_event.clear()

    async def _wake_loop(self) -> None:
        """Listen for a wake phrase through two parallel paths while idle.

        One microphone stream fans out into two queues:
        (1) openWakeWord queue -> fast primary detector.
        (2) Whisper wake queue -> robust fallback.

        The first detector hit arms ``call_event`` and cancels both detectors.
        """
        log.info(
            "Wake-Loop gestartet (oww=%s, whisper=%s, gate=%s).",
            "on" if self._openwakeword_enabled else "off",
            "on" if self._whisper_wake_enabled else "off",
            "open" if self._activation_allowed() else "closed",
        )
        # Both detectors off: PARK, do not die. The old code did
        # ``await asyncio.Event().wait()`` on a FRESH event nobody ever sets —
        # a permanent sleep that not even a later live wake-word change could
        # re-arm (only an app restart). Wait on ``_wake_reload_event`` instead so
        # a ``set_wake_plan`` that re-enables a detector wakes the loop back up,
        # in-app. The 30 s timeout re-logs the parked state so a genuinely dead
        # listener stays visible without busy-spinning. (Mission: "no dead state
        # blocks waking"; AP-22: recovery must be reachable in-app, not a restart.)
        await self._wait_while_wake_disabled()
        gate_blocked_logged_at = 0.0
        stuck_logged_at = 0.0
        while True:
            # Re-checked on EVERY pass, not only before the loop: a user who
            # switches the wake word OFF while the loop is parked on the
            # microphone permission must send it back to the "disabled" wait,
            # or it would re-open a wake_word permission episode every park
            # interval for a feature nobody switched on (P7).
            await self._wait_while_wake_disabled()
            if not self._activation_allowed():
                now = time.time()
                if now - gate_blocked_logged_at > 30.0:
                    # Name the REAL reason. This line used to guess between two
                    # causes and the wrong guess once misled a live freeze
                    # diagnosis, so the reason comes from ONE resolver that
                    # knows every branch of the gate — including a running
                    # dictation, which is the third way to close it.
                    log.info(
                        "Wake loop is waiting — activation gate closed (%s).",
                        self._activation_block_reason() or "reason unknown",
                    )
                    gate_blocked_logged_at = now
                if self._activation_state_allows():
                    # Only the microphone permission is missing. Mute, a running
                    # dictation and mic ownership change on their own clock and
                    # keep the short poll below; a permission changes rarely and
                    # announces itself, so the loop PARKS instead of re-probing.
                    await self._park_until_microphone_allowed()
                else:
                    await asyncio.sleep(0.25)
                continue
            if self._state != PipelineState.IDLE:
                await asyncio.sleep(0.1)
                continue
            try:
                log.info(
                    "🎧 Wake-Listener aktiv — sag '%s' …",
                    getattr(self, "_wake_phrase_label", "the wake word"),
                )
                await self._run_parallel_wake()
            except MicrophoneAccessError as exc:
                # The grant is missing or was just lost: not a crash, so no
                # traceback and no 0.5 s retry churn. Park until it is granted.
                log.info("Wake listening paused: %s", exc)
                await self._park_until_microphone_allowed()
            except MicrophoneStuckError as exc:
                # The audio system stopped answering for the microphone. Not a
                # crash either: the capture has told the person, and asking
                # again every half second would only fill the log. Listening
                # resumes by itself once the audio system answers.
                now = time.time()
                if now - stuck_logged_at > _WAKE_STUCK_LOG_EVERY_S:
                    log.warning("Wake listening paused: %s", exc)
                    stuck_logged_at = now
                await asyncio.sleep(_WAKE_STUCK_RETRY_S)
            except Exception as exc:  # noqa: BLE001
                log.exception("Wake loop failed: %s", exc)
                await asyncio.sleep(0.5)

    async def _park_until_microphone_allowed(self) -> None:
        """Park the wake loop until the microphone is granted (never asks).

        The wake word is a background feature: it must not make macOS ask, and it
        must not poll either. So the loop opens ONE background-origin episode
        (``ensure(interactive=False)``: no request, status snapshot only), which is
        what lets the permission service watcher notice a grant given later in
        System Settings and publish ``PermissionResolved``; ``_on_permission_resolved``
        then sets ``_wake_reload_event``. ``set_wake_plan`` and the 30 s fallback
        timeout wake the loop through the same event, so a missed edge costs at most
        half a minute, never a restart. The episode is re-opened on each wake-up
        that still finds the gate closed (idempotent in the service: same episode,
        no second event), which also revives one the service expired after ten
        minutes of nobody touching it.
        """
        if not self._wake_listening_enabled():
            return  # switched off since the caller read the gate: no episode (P7)
        self._wake_parked_on_permission = True
        try:
            try:
                opened = await self._permission_service().ensure_async(
                    "microphone", feature="wake_word", interactive=False
                )
            except Exception:  # noqa: BLE001 - the park must work without the episode
                log.debug("Opening the wake-word permission episode failed.", exc_info=True)
            else:
                if opened.granted:
                    # Granted between the gate read and now: no episode was opened,
                    # so no edge will come. Let the caller re-read the gate.
                    await asyncio.sleep(0.25)
                    return
            try:
                await asyncio.wait_for(
                    self._wake_reload_event.wait(), timeout=_WAKE_PERMISSION_PARK_S
                )
            except TimeoutError:
                pass  # fallback poll: the caller re-reads the gate
        finally:
            self._wake_parked_on_permission = False
            self._wake_reload_event.clear()

    def _should_show_optimistic_candidate(self) -> bool:
        """Whether an unverified OWW hit may pop the overlay bar immediately.

        The optimistic reveal exists so a genuine "Hey Jarvis" feels instant on
        the precise pretrained model, where false candidates are rare and a
        reject costs one brief bar flash. Custom ONNX and Vosk grammar stage-one
        candidates both match ordinary speech frequently, so those engines wait
        for the authoritative ``WakeWordDetected`` event after full verification.
        (vosk_kws additionally gets the PROVIDER-gated early candidate below —
        that one is mini-verified, not raw, and does not pass through here.)
        """
        if self._state != PipelineState.IDLE:
            return False
        if self._dictation_blocks_activation():
            # A dictation leaves ``_state`` at IDLE on purpose, so without this
            # clause an unverified candidate would still flash the bar out of
            # its dictation look and back, mid-recording.
            return False
        plan = getattr(self, "_wake_plan", None)
        if plan is None:
            return True
        return getattr(plan, "engine", "") == "openwakeword"

    async def _vosk_early_candidate_listener(self, active: bool) -> None:
        """Visual-only bar signal from the vosk provider's mini-verify.

        Deliberately NOT routed through ``_should_show_optimistic_candidate``:
        that helper gates the RAW pre-verify reveal (openwakeword-only, see
        revert 5fe5c4d2). The vosk provider only calls this after its
        mini-verify passed — re-score confidence + span RMS + localized sound
        confirm on the truncated ring — measured at 0/2500 room-speech windows
        shown for "hey jarvis" (calibration 2026-07-11), so the flicker class
        that forced the revert cannot recur. Retracts (active=False) always
        pass through so a shown bar can never stay stuck.
        """
        if active and self._state != PipelineState.IDLE:
            return  # a session is already running; nothing to reveal
        if active and self._dictation_blocks_activation():
            return  # a dictation owns the bar; never flash the wake look over it
        if active:
            self._begin_wake_preroll()
        else:
            self._discard_wake_preroll()
        await self._publish_event(
            WakeCandidateDetected(source_layer="speech", active=active)
        )

    async def _verify_oww_hit(self, pcm_snapshot: bytes) -> bool:
        """Second-stage gate: ask the utterance STT whether the few seconds
        leading up to an OpenWakeWord hit actually contained the configured
        wake phrase. Returns True if the phrase's matcher confirms it.

        STT-outage failure modes degrade OPEN (return True with a log line) so
        a misconfigured STT, a network blip, or a rate-limit cannot brick the
        wake — we'd rather accept the occasional false positive than have the
        user shout into a dead listener. A clear, non-matching transcript
        (genuine other speech) suppresses, preserving the bare-"Jarvis"
        BUG-009 guard. How a WORKING STT that heard no speech (empty
        transcript / silence-hallucination boilerplate) is treated depends on
        the engine: a user-trained custom_onnx hit SUPPRESSES (live forensic
        2026-07-01 — such models false-fire on breath/noise, so "no speech
        heard" is evidence of a false fire, not an STT problem), while any
        other OWW hit keeps the historical degrade-open behaviour (forensic
        2026-06-28 — short real wakes often mis-transcribe to nothing).
        """
        if not self._require_hey_prefix:
            return True
        # The STT re-verification runs for user-trained custom_onnx models
        # (live forensic 2026-07-01: a few-shot model scored breath/ambient/
        # other speech up to 1.000 — a false-positive storm; the transcript
        # matched against the phrase's own sound-folded fuzzy matcher is the
        # real discriminator). Since the product ships no pretrained model
        # (design 2026-07-07), custom_onnx plans are the only source of OWW
        # hits; vosk_kws is exempt via verify_prefix=False (its own confirm).
        plan = getattr(self, "_wake_plan", None)
        if plan is not None and not getattr(plan, "verify_prefix", True):
            return True
        # A user-trained custom_onnx model is a WEAK discriminator (live
        # forensic 2026-07-01/02: scores up to 1.000 on breath/ambient/other
        # speech, 15 fires in 25 s at the worst). Its hits get the strict
        # treatment throughout this gate.
        custom_model_hit = (
            plan is not None and getattr(plan, "engine", "") == "custom_onnx"
        )
        # Silence gate (custom only, BEFORE any STT round-trip): a hit whose
        # trailing audio is essentially silent is a breath/noise false fire by
        # definition — there is no speech an STT could confirm. Suppressing it
        # here (a) kills the "fires out of nowhere" storm at zero cost and
        # (b) stops the fire flood from hammering the verify STT into
        # 429/timeouts (live 2026-07-02: that flood-induced outage is what
        # opened the degrade-open hole and produced ghost activations).
        if custom_model_hit and pcm_snapshot:
            tail_rms = pcm_tail_rms(pcm_snapshot)
            if tail_rms < CUSTOM_WAKE_MIN_RMS:
                log.info(
                    "wake-verify: suppressed — near-silent audio "
                    "(rms %.4f < %.3f) on a custom-model hit; skipping STT",
                    tail_rms,
                    CUSTOM_WAKE_MIN_RMS,
                )
                return False
        if self._utterance_stt is None:
            log.warning(
                "require_hey_prefix=True but no utterance STT — accepting OWW hit"
            )
            return True
        # Nothing captured yet (empty ring buffer) — there is genuinely no audio
        # to confirm the wake, so reject without an STT round-trip. (Whether a
        # NON-empty buffer with no usable transcript suppresses or degrades
        # open is engine-dependent — see below.)
        if not pcm_snapshot:
            return False
        # Pass the RESOLVED wake language. Omitting it fell back to the
        # parameter default ("de"), so every custom-model wake on earth was
        # verified by telling the cloud STT the audio is German — a systematic
        # garble for an English, Spanish or any other user, on the one engine
        # AP-25 names as the endgame. Uses the same resolver the wake plan and
        # the model download use, so selection and verification always agree.
        try:
            from dodaios.speech.wake_model_fetch import resolve_wake_language

            verify_language = resolve_wake_language(self._config)
        except Exception:  # noqa: BLE001 — never let a language lookup kill a wake
            verify_language = None
        matched, text = await verify_wake_with_stt(
            self._utterance_stt,
            pcm_snapshot,
            language=verify_language,
            matcher=getattr(self, "_wake_matcher", None),
        )
        if matched:
            return True
        # For a custom-model hit, a WORKING STT that heard no wake phrase —
        # an empty transcript or a known silence-hallucination boilerplate —
        # is evidence of a false fire and must SUPPRESS. Any other OWW hit
        # keeps the documented degrade-open behaviour (historical forensic
        # 2026-06-28: false fires happened on real speech, so an empty
        # transcript there really does mean the STT failed).
        #
        # Persistent verify-STT failure (Groq 429/503/timeout after retries):
        # - non-custom hit: degrade OPEN. Candidates are rare, so an
        #   unreachable STT is a provider problem, not evidence about what the
        #   user said; accepting keeps the wake alive through an outage (AP-22).
        # - custom_onnx: FAIL CLOSED (live 2026-07-02, 3 ghost activations
        #   overnight). The fire flood of a weak model eventually hits an STT
        #   timeout, and degrade-open then activates Jarvis although nobody
        #   spoke. The session a wake opens needs that same STT to hear
        #   anything (it would be a deaf session), and hotkey/orb-click remain
        #   as in-app activation paths — honest degradation, not a bricked
        #   wake.
        if text is None:
            if custom_model_hit:
                log.info(
                    "wake-verify: suppressed — verify STT unreachable on a "
                    "custom-model hit (fail-closed: the session would be deaf "
                    "without STT; hotkey/orb-click still activate)"
                )
                return False
            log.info(
                "wake-verify: verify STT unreachable on a strong OWW hit — "
                "accepting (degrade-open; an STT outage must not brick the "
                "wake, AP-22)"
            )
            return True
        text = text.strip()
        # KNOWN STT hallucination boilerplate ("Untertitelung des ZDF, 2020",
        # "Vielen Dank."). Whisper emits these on silence/noise buffers.
        # - custom_onnx: the buffer held silence/noise → the model false-fired
        #   on breath/ambient → suppress (fail-closed).
        # - non-custom hit: forensic 2026-06-28 showed short REAL wake
        #   buffers hallucinate these for ~half of all valid wakes → accept
        #   (degrade-open), else the wake "stops working" intermittently.
        # An arbitrary non-matching transcript (genuine OTHER speech) still
        # suppresses for both, so the bare-"Jarvis" guard (BUG-009) stays.
        if text and _STT_HALLUCINATION_RE.search(text) is not None:
            if custom_model_hit:
                log.info(
                    "wake-verify: suppressed — STT hallucination %r on a "
                    "custom-model hit (silence/noise false fire, fail-closed)",
                    text[:80],
                )
                return False
            log.info(
                "wake-verify: STT hallucination %r on a strong OWW hit — "
                "accepting (degrade-open, not a real rejection)",
                text[:80],
            )
            return True
        # The verify STT WORKED and produced an empty transcript.
        # - custom_onnx: no speech in the buffer → breath/noise false fire →
        #   suppress. This is the "fires out of nowhere" half of the
        #   2026-07-01 storm.
        # - non-custom hit: an empty transcription on a strong hit is far
        #   more likely a silence-mis-transcription of a short real wake than
        #   a spontaneous model fire → accept (degrade-open, forensic
        #   2026-06-28 "the wake sometimes stops working entirely").
        if not text:
            if custom_model_hit:
                log.info(
                    "wake-verify: suppressed — empty transcript on a "
                    "custom-model hit (no speech captured, fail-closed)"
                )
                return False
            log.info(
                "wake-verify: verify STT returned no transcript on a strong OWW "
                "hit — accepting (degrade-open)"
            )
            return True
        log.info(
            "wake-verify: suppressed — transcript %r has no wake prefix", text[:80]
        )
        return False

    async def _run_parallel_wake(self) -> None:
        """Fan one wake microphone into all detectors until the first hit."""
        # Detector backlogs are latency budgets, not arbitrary chunk counts.
        # Keep OWW within ~0.6 s and the slower Whisper consumer within ~1.2 s;
        # both queues drop oldest on overflow, so an overloaded host evaluates
        # recent audio instead of a wake word heard several seconds ago.
        #
        # A detector that can CATCH UP in batches (``coalesce_catchup_s``, see
        # ``_wake_catchup_budget``) may declare a deeper ``intake_backlog_s``:
        # its confirm pass blocks its own consumption for 0.4-0.9 s on a weak
        # CPU, which overflowed the 0.6 s queue at every candidate (live
        # 2026-08-19, ``oww_q=19``) and dropped frames INSIDE the audio it
        # was about to verify — the re-score then heard '' and the user had to
        # repeat. With batching it drains a deeper backlog in one or two
        # decodes, so nothing it could still use is ever dropped; a detector
        # without batching keeps the shallow budget, because for it a deeper
        # queue would only mean a later wake.
        coalesce, intake_chunks = _wake_catchup_budget(self._wake)
        oww_queue: asyncio.Queue = asyncio.Queue(maxsize=intake_chunks)
        whisper_queue: asyncio.Queue = asyncio.Queue(
            maxsize=REALTIME_QUEUE_CHUNKS * 2
        )
        detector_queues = [oww_queue] if self._openwakeword_enabled else []
        if self._whisper_wake_enabled and self._whisper_wake is not None:
            detector_queues.append(whisper_queue)
        if not detector_queues:
            await asyncio.sleep(1.0)
            return

        # Rolling PCM ring buffer for post-OWW prefix verification (see
        # ``_verify_oww_hit``). 2.5 s at 16 kHz mono int16 ≈ 80 kB, well above
        # the longest natural "Hey Jarvis" plus a little headroom. We keep the
        # buffer regardless of whether prefix verification is enabled so the
        # cost is identical between modes and a runtime config flip never
        # needs to re-arm fanout.
        ring_bytes = bytearray()
        RING_MAX = 16_000 * 2 * 3  # ~3 s
        # Rolling overlap for the EXPLICIT (hotkey/PTT) handoff seed: it must
        # cover the whole press-to-claim latency — key poll (~20 ms), the
        # cross-thread call edge, one state-loop turn and the stop-event round
        # trip — or the user's first syllables land in the wake detectors
        # instead of the session.
        recent_chunks: deque[AudioChunk] = deque(
            maxlen=capture_chunks_for_duration(0.5)
        )  # ~500 ms overlap
        wake_confirmed = False
        handoff_buffer: _SessionInputBuffer | None = None

        async def _fanout(mic: MicrophoneCapture) -> None:
            source_error: BaseException | None = None
            try:
                async for chunk in mic.stream():
                    # Input mute (Jarvis-scoped): if the user mutes while a wake
                    # session is already mid-wait, stop feeding the detectors so
                    # Jarvis goes deaf immediately — without touching the OS mic.
                    # (A fresh mute while IDLE is already handled by _wake_loop's
                    # _activation_allowed() gate, which never opens the mic.)
                    muted = getattr(self, "_muted", False)
                    # A dictation is the second way this stream stops belonging
                    # to the wake word. It is the same STATE gate the activation
                    # predicate uses (never transcript content — AP-27).
                    dictating = self._dictation_blocks_activation()
                    if handoff_buffer is not None:
                        # The stream has been handed to whoever claimed it. Mute
                        # still starves a VOICE session (input-only mute), but
                        # never the dictation lane: an explicit dictation press
                        # is the user deliberately speaking into their own text
                        # field, and the lane's own fallback capture has always
                        # ignored mute. Dropping frames here would make a
                        # dictation silently record nothing whenever the wake
                        # microphone happened to be the one it took over.
                        if muted and not dictating:
                            continue
                        handoff_buffer.put(chunk)
                        continue
                    if muted or dictating:
                        # Nothing claimed the stream, so these frames would go
                        # to the wake detectors. While a dictation is running
                        # they are the user's dictated words: feeding them to a
                        # detector both risks tripping the wake word mid-
                        # dictation and shares this native engine with the
                        # dictation's own transcription (AP-24).
                        continue
                    ring_bytes.extend(chunk.pcm)
                    if len(ring_bytes) > RING_MAX:
                        del ring_bytes[: len(ring_bytes) - RING_MAX]
                    recent_chunks.append(chunk)
                    if self._wake_preroll_active:
                        self._pending_session_preroll.append(chunk)
                        _feed_live_mic_level(chunk)
                    for q in detector_queues:
                        try:
                            q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            # Keep detector latency bounded by dropping its oldest frame.
                            try:
                                q.get_nowait()
                                q.put_nowait(chunk)
                            except asyncio.QueueEmpty:
                                pass
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - surface to consumers
                source_error = exc
                raise
            finally:
                if handoff_buffer is not None:
                    handoff_buffer.finish(error=source_error)

        def _activate_handoff(*, confirmed: bool) -> _SessionInputBuffer:
            nonlocal handoff_buffer
            if handoff_buffer is not None:
                return handoff_buffer
            if confirmed:
                initial = self._take_wake_preroll()
            else:
                # An explicit click/hotkey may arrive while a wake candidate is
                # still being verified. Preserve that already-visible interval;
                # otherwise seed the full rolling overlap. The user starts
                # talking AT the press, and the press precedes this claim by
                # the key-poll + call-edge + state-loop latency — seeding only
                # the last block (the old behaviour) cut the first syllables
                # off every "press and talk" capture.
                initial = (
                    tuple(self._pending_session_preroll)
                    if self._wake_preroll_active
                    else tuple(recent_chunks)
                )
                self._discard_wake_preroll()
            handoff_buffer = _SessionInputBuffer(initial=initial, capture=mic)
            self._wake_handoff_buffer = handoff_buffer
            self._wake_handoff_ready.set()
            return handoff_buffer

        async def _run_oww() -> str:
            # Capability-gated catch-up: a detector that can consume variable
            # chunk sizes (vosk_kws) advertises how much backlogged audio may
            # be coalesced into one catch-up batch, so a busy CPU never leaves
            # it grinding through seconds-stale audio (the inconsistent
            # multi-second wake delay, live 2026-07-21). ``coalesce`` comes
            # from the same resolver that sized the queue above.
            async for kw in self._wake.detect(
                _queue_iter(oww_queue, coalesce_max_chunks=coalesce)
            ):
                return f"oww:{kw}"
            return ""

        async def _run_whisper() -> str:
            if self._whisper_wake is None:
                await asyncio.Event().wait()  # never completes
                return ""
            async for kw in self._whisper_wake.detect(_queue_iter(whisper_queue)):
                return f"whisper:{kw}"
            return ""

        # NOTE: the wake mic keeps the DEEP default queue on purpose. Its
        # detectors offload inference (openWakeWord ``to_thread``; whisper-wake
        # ``await transcribe_pcm``), so the event loop stays free and the cheap
        # ``_fanout`` drains this queue near-instantly — it never fills, so a
        # shallow depth would be inert here anyway. The wake path's real staleness
        # lever is the per-detector queues below (``oww_queue`` / ``whisper_queue``),
        # which belong to the wake layer; this change deliberately does not touch
        # them. The drop-OLDEST overflow policy (capture ``_safe_put``) still
        # applies and is safe here.
        async with _wake_capture_with_release(
            MicrophoneCapture(
                device=self._input_device,
                device_priority=self._input_priority,
                # Background capture: it never makes macOS ask (the gate above
                # already required a live grant) and reports a lost grant as
                # ``wake_word``.
                permission_feature="wake_word",
                interactive=False,
            ),
            self._wake_capture_released,
        ) as mic:
            fanout_task = asyncio.create_task(_fanout(mic), name="fanout")
            oww_task = (
                asyncio.create_task(_run_oww(), name="oww-wake")
                if self._openwakeword_enabled
                else None
            )
            tasks = [fanout_task]
            if oww_task is not None:
                tasks.append(oww_task)
            if self._whisper_wake_enabled:
                whisper_task = asyncio.create_task(_run_whisper(), name="whisper-wake")
                tasks.append(whisper_task)
            else:
                whisper_task = None  # type: ignore[assignment]

            async def _detector_heartbeat() -> None:
                """Log every ten seconds while all detector tasks remain alive.

                Missing output while the watchdog is running exposes a silently
                failed task, such as a queue deadlock or swallowed exception.
                """
                def _detector_state(task: asyncio.Task[Any] | None) -> str:
                    """alive / parked / FAILED / off.

                    ``DEAD`` used to cover all of "stopped normally",
                    "cancelled" and "raised", so the log screamed DEAD for the
                    ENTIRELY NORMAL case of a detector parked while a voice
                    session owns the microphone — verified against the desktop
                    logs, where every DEAD window coincides with an active
                    session and recovers when it ends. That cost a forensic
                    detour: a healthy state that reads as a crash is worse than
                    no signal at all.
                    """
                    if task is None:
                        return "off"
                    if not task.done():
                        return "alive"
                    if task.cancelled():
                        return "parked"
                    return "FAILED" if task.exception() is not None else "parked"

                while True:
                    await asyncio.sleep(10.0)
                    # The detector's OWN counters name exactly the failure modes
                    # a recall complaint has to distinguish (candidates seen,
                    # gated on energy, suppressed by the confirm, suppressed by
                    # cooldown, fired). They were maintained and never read, so
                    # "how many of my wakes were suppressed?" needed a debugger.
                    # Read-only: nothing here may ever feed a decision.
                    try:
                        stats = getattr(self._wake, "stats", None)
                        detector_stats = stats() if callable(stats) else {}
                    except Exception:  # noqa: BLE001 — diagnostics never break the loop
                        detector_stats = {}
                    log.info(
                        "wake-detectors-heartbeat: fanout=%s oww=%s whisper=%s "
                        "oww_q=%d wsp_q=%d%s",
                        "alive" if not fanout_task.done() else "FAILED",
                        _detector_state(oww_task),
                        _detector_state(whisper_task),
                        oww_queue.qsize(),
                        whisper_queue.qsize(),
                        (
                            " " + " ".join(f"{k}={v}" for k, v in detector_stats.items())
                            if detector_stats
                            else ""
                        ),
                    )
                    # Surface a detector task that exited with an exception.
                    for t in (oww_task, whisper_task):
                        if t is None or not t.done():
                            continue
                        try:
                            t.result()
                        except asyncio.CancelledError:
                            pass
                        except Exception as exc:  # noqa: BLE001
                            log.error("Detector task %s failed: %s", t.get_name(), exc)

            heartbeat_task = asyncio.create_task(_detector_heartbeat(), name="wake-heartbeat")

            # Live-apply: a set_wake_plan() flips _wake_reload_event so we abort
            # this mic/detector session and let _wake_loop re-arm with the new
            # model/matcher — the wake word changes without an app restart.
            reload_task = asyncio.create_task(
                self._wake_reload_event.wait(), name="wake-reload"
            )
            tasks.append(reload_task)
            handoff_task = asyncio.create_task(
                self._wake_stop_event.wait(), name="wake-session-handoff"
            )
            tasks.append(handoff_task)
            cancel_task = asyncio.create_task(
                self._wake_cancel_event.wait(), name="wake-candidate-cancel"
            )
            tasks.append(cancel_task)

            async def _cancel_candidate() -> None:
                self._wake_cancel_event.clear()
                if self._wake_preroll_active:
                    await self._publish_event(
                        WakeCandidateDetected(source_layer="speech", active=False)
                    )
                self._discard_wake_preroll()

            try:
                # Wait for one detector, a live reload, or a session handoff.
                done, _pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                if cancel_task in done:
                    await _cancel_candidate()
                    return
                if fanout_task in done:
                    if not fanout_task.cancelled():
                        exc = fanout_task.exception()
                        if exc is not None:
                            log.warning("Wake microphone fanout ended: %s", exc)
                    return
                if handoff_task in done:
                    buffer = _activate_handoff(confirmed=False)
                    await buffer.released.wait()
                    return
                if reload_task in done:
                    self._wake_reload_event.clear()
                    log.info(
                        "🔁 Wake-Live-Reload — re-arming with the new wake word."
                    )
                    return  # finally cancels detectors + closes mic; loop re-enters
                for t in done:
                    if t in {reload_task, handoff_task, cancel_task}:
                        continue
                    result = t.result()
                    if result:
                        # The detector hit marks the earliest truthful visual
                        # edge. Do not seed pre-hit audio: it contains the wake
                        # phrase itself and could become a phantom user turn.
                        self._begin_wake_preroll()
                        log.info("🎙 Wake candidate from %s", result)
                        # Prefix verifier: an OWW hit is only a *candidate*
                        # until the cloud STT confirms "hey/hi/hallo + jarv"
                        # in the few seconds before the trigger. Whisper-wake
                        # already enforces the same pattern, so its hits skip
                        # the second stage. See ``_verify_oww_hit``.
                        if result.startswith("oww:"):
                            # Optimistic VISUAL reveal: pop the overlay bar NOW,
                            # before the slow STT prefix-verify below, so the bar
                            # feels instant on "Hey Jarvis". This is visual-only
                            # (WakeCandidateDetected never opens a session turn),
                            # so a rejected candidate costs a brief bar flash, not
                            # a phantom session — retracted just below on reject.
                            # Custom-model candidates never reveal optimistically
                            # (constant flicker, see the helper's docstring).
                            show_candidate = self._should_show_optimistic_candidate()
                            if show_candidate:
                                await self._publish_event(
                                    WakeCandidateDetected(
                                        source_layer="speech", active=True
                                    )
                                )
                            verify_task = asyncio.create_task(
                                self._verify_oww_hit(bytes(ring_bytes)),
                                name="wake-prefix-verify",
                            )
                            verify_done, _ = await asyncio.wait(
                                {
                                    verify_task,
                                    handoff_task,
                                    cancel_task,
                                    fanout_task,
                                },
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if cancel_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                await _cancel_candidate()
                                return
                            if fanout_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                await _cancel_candidate()
                                if not fanout_task.cancelled():
                                    exc = fanout_task.exception()
                                    if exc is not None:
                                        log.warning(
                                            "Wake microphone fanout ended during "
                                            "candidate verification: %s",
                                            exc,
                                        )
                                return
                            if handoff_task in verify_done:
                                verify_task.cancel()
                                try:
                                    await verify_task
                                except asyncio.CancelledError:
                                    pass
                                buffer = _activate_handoff(confirmed=False)
                                await buffer.released.wait()
                                return
                            verified = verify_task.result()
                            if not verified:
                                if show_candidate:
                                    await self._publish_event(
                                        WakeCandidateDetected(
                                            source_layer="speech", active=False
                                        )
                                    )
                                log.info(
                                    "🚫 Wake rejected: no greeting prefix in the "
                                    "last three seconds of transcript."
                                )
                                # Clear the detector's debounce cooldown: this
                                # candidate was a false positive, so a genuine
                                # "Hey Jarvis" spoken right after must NOT be
                                # swallowed for the full cooldown window.
                                note_rejected = getattr(
                                    self._wake, "note_rejected_candidate", None
                                )
                                if callable(note_rejected):
                                    note_rejected()
                                break
                        log.info("🎙 Wake confirmed by %s", result)
                        if self._state == PipelineState.IDLE:
                            # The state-loop SILENTLY drops a wake that arrives
                            # inside the post-hangup echo lock (or when the app
                            # is not activatable) — it just ``continue``s. But
                            # _emit_wake below publishes WakeWordDetected, which
                            # flips the overlay bar to its "listen" look. Emitting
                            # for a wake the loop will then drop leaves the bar
                            # stuck "listening" with no session behind it, and the
                            # user is ignored ("wake triggers, nothing happens").
                            # Mirror the loop's gate HERE, before _emit_wake, and
                            # retract the optimistic candidate instead of lying.
                            now = time.time()
                            locked = now < self._wake_lock_until
                            # The vosk provider may have shown a mini-verified
                            # early candidate for THIS wake — consume the flag
                            # either way; retract below if the wake is dropped.
                            consume = getattr(
                                self._wake, "consume_early_candidate", None
                            )
                            early_shown = consume() if callable(consume) else False
                            if locked or not self._activation_allowed():
                                if locals().get("show_candidate") or early_shown:
                                    await self._publish_event(
                                        WakeCandidateDetected(
                                            source_layer="speech", active=False
                                        )
                                    )
                                if locked:
                                    log.info(
                                        "🔒 Wake lock active; discarding detection "
                                        "for another %.1fs.",
                                        max(0.0, self._wake_lock_until - now),
                                    )
                                else:
                                    # Same resolver as every other gated site —
                                    # a hardcoded guess here named the wrong
                                    # cause during a live diagnosis.
                                    log.info(
                                        "Wake detection discarded: %s.",
                                        self._activation_block_reason()
                                        or "activation not allowed",
                                    )
                                break
                            # The UI consumes WakeWordDetected plus supervisor
                            # state to reveal its listening surface.
                            keyword = result.split(":", 1)[-1] if ":" in result else result
                            self._wake_preroll_confirmed = True
                            wake_confirmed = True
                            buffer = _activate_handoff(confirmed=True)
                            await self._emit_wake(keyword)
                            self._arm_call_event()
                            await buffer.released.wait()
                        break
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: S110 - teardown
                    pass
                for t in tasks:
                    if not t.done():
                        t.cancel()
                for t in tasks:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):  # noqa: S110 - teardown
                        pass
                # An exception/cancellation between offering the buffer and the
                # state loop claiming it must not leave a ready latch pointing
                # at stale audio for the next activation.
                if (
                    handoff_buffer is not None
                    and self._wake_handoff_buffer is handoff_buffer
                ):
                    self._wake_handoff_buffer = None
                    self._wake_handoff_ready.clear()
                    await handoff_buffer.close()
                self._wake_cancel_event.clear()
                self._wake_stop_event.clear()
                if not wake_confirmed:
                    self._discard_wake_preroll()

    # ------------------------------------------------------------------
    # State-Loop
    # ------------------------------------------------------------------

    async def _state_loop(self) -> None:
        while True:
            await self._call_event.wait()
            self._call_event.clear()
            now = time.time()
            # Consume the explicit-edge marker for THIS call before any gate
            # decides.
            explicit_call = bool(getattr(self, "_explicit_call_pending", False))
            self._explicit_call_pending = False
            allowed = (
                self._gesture_activation_allowed()
                if explicit_call
                else self._activation_allowed()
            )
            if not allowed:
                # Resolved, never guessed: this backstop closes for a mute and
                # for a running dictation too, and a log line that names the
                # window instead is exactly what misled an earlier diagnosis.
                # A deliberate press (``explicit_call``) is judged by the
                # user-gesture predicate, a wake word by the background one.
                log.info(
                    "Voice call ignored: %s.",
                    self._activation_block_reason(explicit=explicit_call)
                    or "activation not allowed",
                )
                await self._abort_pending_wake_handoff()
                continue
            if now < self._wake_lock_until and not explicit_call:
                # The speaker-echo lock gates only WAKE-WORD calls: the tail of
                # Jarvis' own TTS can re-trigger the wake word, but it cannot
                # press a key. Dropping explicit presses here made a quick
                # follow-up ("press and talk") record nothing until the lock
                # expired — the opening words of the capture were missing.
                remaining = self._wake_lock_until - now
                log.info("Wake lock active; ignoring call for %.1fs.", remaining)
                await self._abort_pending_wake_handoff()
                continue
            # Preserve a close accepted after the confirmed wake offered its
            # microphone but before this loop entered ACTIVE. Clearing it here
            # would reopen the visibly closed bar and submit the buffered words.
            handoff_offered = bool(
                self._wake_handoff_buffer is not None
                or self._wake_handoff_ready.is_set()
            )
            handoff_close_latch = getattr(
                self, "_wake_handoff_hangup_pending", None
            )
            preserve_handoff_close = bool(
                handoff_offered
                and handoff_close_latch is not None
                and handoff_close_latch.is_set()
            )
            if handoff_close_latch is not None:
                handoff_close_latch.clear()
            if not preserve_handoff_close:
                self._external_hangup_pending.clear()
                self._hangup_event.clear()
                self._hangup_confirmation = HangupConfirmation()
                # Forget a hard-hangup flag left by a no-op while truly idle.
                # A close after handoff is real and retains the short wake lock.
                self._explicit_hard_hangup = False
            self._state = PipelineState.ACTIVE
            self._voice_start_monotonic = (
                time.monotonic() if explicit_call
                else getattr(self, "_wake_detected_monotonic", None) or time.monotonic()
            )
            self._wake_detected_monotonic = None
            self._listening_cue_started = False
            self._listening_cue_task: asyncio.Task[None] | None = None
            session_id = str(uuid4())
            self._termination_producer = ""
            self._termination_detail = {}
            self._idle_deadline_monotonic = None
            self._last_user_activity_monotonic = None
            self._last_answer_floor_monotonic = None
            self._previous_turn_state = None
            self._current_voice_session_id = session_id
            self._restore_agent_replies()
            self._active_realtime_provider = ""
            self._active_realtime_model = ""
            self._voice_engine_transitioning = True
            session_started_at = time.time()
            wake_keyword = self._last_wake_keyword or "hotkey"
            self._last_wake_keyword = ""
            hangup_reason = HANGUP_ERROR
            try:
                # Reuse the already-open wake microphone when available. The
                # handoff never owns two native streams at once and retains all
                # frames heard after the visible wake candidate.
                async with self._capture_first_session_input() as input_buffer:
                    # This event is the UI's authoritative "being listened to
                    # now" signal. Capture is already armed before any
                    # subscriber can reveal the listening bar.
                    await self._publish_event(
                        VoiceSessionStarted(
                            source_layer="speech.pipeline",
                            session_id=session_id,
                            wake_keyword=wake_keyword,
                            language=DEFAULT_LOCALE,
                        )
                    )
                    # A close accepted while a slow start subscriber runs must
                    # release the borrowed capture without entering a provider.
                    if (
                        self._hangup_event.is_set()
                        or self._external_hangup_pending.is_set()
                    ):
                        hangup_reason = HANGUP_HOTKEY
                        self._termination_producer = "speech.pipeline._state_loop.startup_hangup"
                        log.info("Voice session cancelled during startup.")
                    else:
                        log.info("Voice session accepted.")
                        await self._set_turn_state(TurnTakingState.LISTENING)
                        # The selected engine confirms readiness with a brief
                        # non-speech cue. Never play the legacy spoken ACK or
                        # pause capture: the opening words are already buffered.
                        hangup_reason = await self._active_session(
                            input_buffer=input_buffer
                        )
            except asyncio.CancelledError:
                hangup_reason = HANGUP_SHUTDOWN
                self._termination_producer = "speech.pipeline._state_loop.cancelled"
                raise
            except Exception as exc:  # noqa: BLE001
                self._termination_producer = "speech.pipeline._state_loop.error"
                log.exception("Voice session failed: %s", exc)
            finally:
                cue = getattr(self, "_listening_cue_task", None)
                if cue is not None:
                    await cancel_and_reap(
                        cue,
                        budget_s=_SESSION_TASK_REAP_BUDGET_S,
                        heartbeat_s=_SESSION_TASK_REAP_HEARTBEAT_S,
                    )
                    self._listening_cue_task = None
                termination = self._termination_snapshot(hangup_reason)
                reopen_after_engine_change = bool(
                    getattr(self, "_reopen_after_engine_change", False)
                )
                engine_change_reason = str(
                    getattr(self, "_engine_change_reason", "")
                )
                self._reopen_after_engine_change = False
                self._engine_change_reason = ""
                self._current_voice_session_id = None
                self._active_realtime_provider = ""
                self._active_realtime_model = ""
                self._voice_engine_transitioning = False
                # PTT is one-shot per hold — disarm before the next session so a
                # stale flag can never reroute a later wake-word session into
                # the raw-recording path.
                # Hanging up ends a coding-agent brief that is still being
                # written, the same way it does on the realtime engine (see
                # ``RealtimeVoiceSession._abandon_spoken_workspace_briefs``):
                # composing takes 10-30 s, and a pane typed into after the user
                # stopped waiting is work they no longer asked for. Idempotent —
                # a realtime call that already dropped its briefs leaves none
                # here. Skipped on an engine reconnect: that session re-arms and
                # the order the user gave is still live.
                if not reopen_after_engine_change:
                    try:
                        from dodaios.agentic_ide.fanout import cancel_spoken_deliveries

                        cancel_spoken_deliveries(
                            reason=f"the call ended ({hangup_reason or 'unknown'})"
                        )
                    except Exception:  # noqa: BLE001 — teardown must never crash
                        log.debug("Workspace brief teardown failed", exc_info=True)
                # Whatever was spoken after the last utterance (the goodbye, a
                # late announcement) is settled BEFORE the session closes, or
                # the recorder has no open session to file it under.
                spend = getattr(self, "_speech_spend", None)
                if spend is not None:
                    spend.flush()
                await self._publish_event(
                    VoiceSessionEnded(
                        source_layer=termination["producer"],
                        session_id=session_id,
                        hangup_reason=hangup_reason,
                        duration_s=max(0.0, time.time() - session_started_at),
                        detail=json.dumps(termination, ensure_ascii=True),
                    )
                )
                self._state = PipelineState.IDLE
                # Return the supervisor to IDLE and hide the active surface.
                await self._set_turn_state(TurnTakingState.IDLE)
                self._external_hangup_pending.clear()
                if reopen_after_engine_change and self._activation_allowed():
                    # An internal engine reconnect has no response tail to
                    # protect against. Re-arm immediately with the latest
                    # config; a disconnect earcon would leak into the new mic.
                    self._explicit_hard_hangup = False
                    self._wake_lock_until = 0.0
                    self._last_wake_keyword = "engine_switch"
                    self._call_event.set()
                    log.info(
                        "Voice session re-armed after engine change (%s).",
                        engine_change_reason or "configuration_change",
                    )
                else:
                    # Normal disconnect earcon followed by speaker-echo lock.
                    # Skipped when the dictation lane is what ended this session:
                    # the user's microphone is open a few milliseconds later (or
                    # already is), and a tone played into it is speaker echo the
                    # transcription then has to eat.
                    if not self._dictation_blocks_activation():
                        await self._play_earcon(DISCONNECT_PCM)
                    lock_s = self._post_hangup_lock_seconds()
                    self._wake_lock_until = time.time() + lock_s
                    log.info(
                        "Voice session ended; returning to idle (wake lock %.1fs).",
                        lock_s,
                    )

    def _earcons_enabled(self) -> bool:
        """Whether synthesized UI earcons may play.

        Read fresh from the shared config object so the Settings → Behavior
        "Sound effects" master switch applies live (no restart). Defensive
        default ``True`` — a missing field must never silence tones.
        """
        ui = getattr(getattr(self, "_config", None), "ui", None)
        return bool(getattr(ui, "sound_effects", True))

    async def _play_earcon(
        self, pcm: bytes, *, sample_rate: int = CHIME_SAMPLE_RATE
    ) -> None:
        """Play a synthesized earcon unless the global "Sound effects" switch
        is off. Never raises — an earcon failure must not crash a turn (AD-OE6).
        Does NOT gate the spoken TTS voice, which is not an earcon.
        """
        if not self._earcons_enabled():
            return
        try:
            await self._player.play_pcm(pcm, sample_rate=sample_rate)
        except Exception as exc:  # noqa: BLE001
            log.debug("Earcon playback skipped (%s).", exc)

    def _start_listening_cue(self) -> None:
        """Confirm native capture once, without blocking or suppressing input."""
        if getattr(self, "_listening_cue_started", False):
            return
        self._listening_cue_started = True
        if (
            not self._earcons_enabled()
            or self.is_speaker_muted
            or getattr(self, "_muted", False)
            or self._hangup_event.is_set()
            # Read defensively: a pipeline assembled without __init__ (the realtime
            # handshake test doubles) has no external-hangup flag yet.
            or (pending := getattr(self, "_external_hangup_pending", None)) is not None
            and pending.is_set()
        ):
            return
        self._listening_cue_task = asyncio.create_task(
            self._play_earcon(CHIME_PCM), name="voice-listening-cue"
        )

    @asynccontextmanager
    async def _session_input_source(
        self,
        input_buffer: _SessionInputBuffer | None,
        *,
        discard_suppressed: bool = False,
    ) -> AsyncIterator[AsyncIterator[AudioChunk]]:
        """Yield a pre-opened session stream or own a fallback capture."""
        if input_buffer is not None:
            discard_before = (
                lambda: int(getattr(self, "_input_suppressed_until_ns", 0))
            ) if discard_suppressed else None
            yield input_buffer.stream(discard_before_ns=discard_before)
            return
        async with MicrophoneCapture(
            device=self._input_device,
            max_queue_chunks=REALTIME_QUEUE_CHUNKS,
            device_priority=self._input_priority,
        ) as mic:
            yield mic.stream()

    async def _active_session(
        self, *, input_buffer: _SessionInputBuffer | None = None
    ) -> str:
        self._last_answer_floor_monotonic = None
        self._voice_engine_transitioning = True
        return await self._active_realtime_session(input_buffer=input_buffer)

    async def _active_realtime_session(
        self, *, input_buffer: _SessionInputBuffer | None = None
    ) -> str:
        """Run one desktop duplex session; returns its hangup reason.

        Imports stay lazy so the optional realtime stack never enters the boot
        critical path. The session owns provider-family fallback and resampling;
        this adapter owns only the local microphone, speaker, and lifecycle.
        Desktop starts half-duplex because PortAudio has no portable acoustic
        echo cancellation. The browser surface provides full duplex with Web
        Audio echo cancellation.
        """
        from dodaios.speech.realtime_session_runner import RealtimeSessionRunner

        return await RealtimeSessionRunner(self, input_buffer).run()

    # ------------------------------------------------------------------
    # Chat mic-dictation (transcribe-only → chat input, never the brain)
    # ------------------------------------------------------------------

    def dictation_available(self) -> bool:
        """True if the server can run mic-dictation (a mic + an STT exist).

        Lets the UI hide the mic button on a headless host with no capture
        device (cloud-first: a missing capability is a clean no-op, AD-OE6).

        The microphone PERMISSION is deliberately not a term here: the button
        must be visible on a fresh Mac, where the first press is what asks.
        ``start_dictation`` refuses honestly when the permission is missing.
        """
        return self._utterance_stt is not None and self._input_device != "none"

    def dictation_engine_status(self) -> dict[str, Any]:
        """Which recognizer reads the next dictation, for the UI. Never raises.

        ``provider`` / ``model`` name the engine that answers the next press
        and ``local`` says whether it runs on this computer; ``fallback`` is
        the stand-in behind it. ``detail`` is one sentence for the person
        when recognition is not where the settings suggest: no key saved, or
        a slow on-device model in use while a faster one could be downloaded.
        """
        try:
            return dict(self._dictation_resolution().status())
        except Exception as exc:  # noqa: BLE001 — a status probe never breaks the view
            log.debug("dictation engine status unavailable (%s)", exc)
            return {
                "local": False,
                "provider": "",
                "model": "",
                "fallback": "",
                "detail": "",
            }

    def start_dictation(self, *, target: str = "chat", source: str = "api") -> bool:
        """Begin a transcribe-only dictation session (idempotent-safe).

        ``source`` names the door the request came through — ``hold_key``,
        ``toggle_key``, ``ws``, ``rest`` or the default ``api`` — purely so the
        start line in the log says so and the hold-key watchdog knows whether a
        release edge is owed (BUG-191: a recording that never ended could not
        be traced to its trigger, because the log never said which one it was).

        ``target`` decides where the finished transcript goes:

        * ``"chat"`` — publish the transcript only. This is the chat composer's
          mic button: the text lands in the app's own input box.
        * ``"insert"`` — additionally paste it into the focused text field of
          whatever application is in front. This is dictation mode proper.

        Returns ``False`` when it cannot start — no microphone, no STT, or a
        dictation already running. A live voice conversation is NOT one of
        those cases any more: see the handover below.

        **The dictation key wins.** Pressing it is a deliberate, explicit user
        action; a conversation left open in the background is not. On this
        machine's configuration a session never ends by itself (idle auto-hangup
        is off by maintainer mandate and the hangup key is unbound), so a single
        wake word at any point in the day used to make EVERY later dictation
        press refuse — silently — until the app was restarted. So a press now
        hangs the conversation up through the ordinary hangup chokepoint (the
        same one the bar's close-X uses), waits for the microphone to actually
        come back, and then records. This is the maintainer's own kill-switch
        doctrine: an explicit stop gesture beats whatever Jarvis is in the
        middle of, INCLUDING a half-spoken answer, and the answer is cut off the
        clean way — the player stops, the session unwinds through its normal
        teardown, and a bounded wait means a wedged teardown refuses honestly
        instead of hanging or deafening the key forever.

        **Every refusal is announced**, not just logged: each one publishes a
        ``DictationRefused`` carrying a stable reason token and a finished
        English sentence. Before that, a refused shortcut produced a
        ``log.info`` in a file the desktop app cannot display, so
        the key simply did nothing and the user had no way to learn why. The
        boolean return is unchanged, so every existing caller (hotkey edge, WS
        handler, REST route) keeps working; ``True`` from the handover path
        means "accepted", and its failure arrives as ``DictationRefused``.

        This NEVER routes to the brain: it spawns ``_dictation_session`` which
        only publishes ``DictationStarted`` / ``DictationTranscript`` /
        ``DictationTranscribing`` / ``DictationCompleted`` events.
        """
        if self._utterance_stt is None:
            self._refuse_dictation(
                "no_stt",
                "No speech-to-text provider is configured, so there is nothing "
                "to transcribe with. Add a provider key in Settings.",
            )
            return False
        if self.dictation_active():
            self._refuse_dictation(
                "already_running",
                "A dictation is already recording.",
            )
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._refuse_dictation(
                "pipeline_not_running",
                "The voice pipeline is not running, so dictation cannot start.",
            )
            return False
        # The press is the gesture that may ask macOS for the microphone. A first
        # press of an undecided microphone raises the OS dialog and refuses THIS
        # press ("microphone_unavailable" + the PermissionNeeded episode the
        # service publishes); nothing starts retroactively once it is answered, the
        # UI says "allowed - press again". The refusal sentence comes from the
        # permission layer's fixed templates, never from exception text.
        refusal = self._ensure_microphone("dictation")
        if refusal is None and not self._user_capture_allowed():
            refusal = _MICROPHONE_REFUSED_SENTENCE
        if refusal is not None:
            self._refuse_dictation("microphone_unavailable", refusal)
            return False
        if self._live_call_owns_microphone():
            # A live call keeps running: its input is held, not hung up.
            return self._commit_dictation(
                loop, target=target, source=source, beside_call=True
            )
        if self._voice_session_holds_microphone():
            return self._begin_dictation_handover(loop, target=target, source=source)
        return self._commit_dictation(loop, target=target, source=source)

    def _live_call_owns_microphone(self) -> bool:
        """True while a live realtime call captures the microphone in the WebView.

        Such a call owns its own capture (getUserMedia, with the browser's echo
        cancellation), so a dictation does not have to take the device away
        from it. Instead the dictation records through its own capture and the
        call's input is HELD until the text is delivered (``VoiceInputHeld``):
        the conversation stays open and the dictated words never become a turn.
        """
        try:
            from dodaios.live.runtime import owns_microphone
        except Exception:  # noqa: BLE001 — no live stack means no live call
            log.debug("live call registry unavailable", exc_info=True)
            return False
        return owns_microphone()

    @property
    def is_voice_input_held(self) -> bool:
        """Whether a dictation currently holds a live call's input back.

        Read by a call that starts DURING such a dictation, so it adopts the
        hold instead of hearing the dictated words.
        """
        return bool(getattr(self, "_voice_input_held", False))

    def _set_voice_input_held(self, held: bool) -> None:
        """Hold or release a live call's input and tell the call. Never raises."""
        if bool(getattr(self, "_voice_input_held", False)) == held:
            return
        self._voice_input_held = held
        log.info(
            "Live call input %s for the dictation.",
            "held" if held else "released",
        )
        self._publish_event_soon(VoiceInputHeld(held=held, reason="dictation"))

    def _on_beside_call_dictation_done(self, _task: asyncio.Task[None]) -> None:
        """Give the call its voice back once the dictation has fully ended.

        A done-callback rather than a ``finally``: it runs for every end of the
        task, including one cancelled before its first step, so the call can
        never be left deaf. The task ends only after the text was delivered,
        which is the moment the user may talk to the call again.
        """
        try:
            self._dictation_beside_call = False
            self._set_voice_input_held(False)
        except Exception:  # noqa: BLE001 — a release must never become a crash
            log.warning("Releasing the live call input failed", exc_info=True)

    def _voice_session_holds_microphone(self) -> bool:
        """True while the VOICE lane owns the one input device.

        The dictation lane must then not open a stream of its own (AP-24 /
        the BUG-014 family). ``getattr`` defaults keep pipelines built via
        ``__new__`` working.
        """
        return getattr(self, "_state", PipelineState.IDLE) is not PipelineState.IDLE

    def _begin_dictation_handover(
        self, loop: asyncio.AbstractEventLoop, *, target: str, source: str = "api"
    ) -> bool:
        """Take the microphone from a live voice conversation, then dictate.

        Returns ``True`` when the press is ACCEPTED: the conversation has been
        told to hang up and the dictation starts a moment later, once the device
        has actually been released. That ordering is the whole point, because
        two native input streams on one device is the AP-24 class of bug.
        ``False`` means the hangup itself could not even be requested, which is
        refused out loud like any other dead end.

        The wake gate is closed here rather than at the commit point: ending the
        conversation returns the pipeline to IDLE with the wake loop free to
        re-arm, and a wake word firing inside that gap would take the microphone
        straight back from the user who just pressed the key. The deadline
        covers only the handover — ``_commit_dictation`` re-arms it for the
        recording — so a handover that dies without running its own teardown
        still cannot deafen wake for more than this window (BUG-037).
        """
        self._dictation_wake_block_until = (
            time.time() + _DICTATION_HANDOVER_TIMEOUT_S + 1.0
        )
        try:
            # Hang up SYNCHRONOUSLY, on the press itself — never from inside the
            # waiting task. A task cancelled before its first step (a
            # press-and-release a few milliseconds apart, which is a normal
            # human gesture) never executes a single line of its body, so a
            # hangup scheduled in there would simply not happen and the key
            # would be back to doing nothing at all.
            #
            # This is the ordinary hangup entry point — the same one the bar's
            # close-X calls. It stops the player immediately, cancels a running
            # Computer-Use mission and a live chat turn, and lets the session
            # unwind through its own teardown. Deliberately NOT a second
            # teardown of our own: one chokepoint, one contract.
            self.request_hangup()
        except Exception as exc:  # noqa: BLE001 — an honest refusal, not a crash
            log.warning("Dictation handover could not hang up the session: %s", exc)
            self._refuse_dictation(
                "handover_failed",
                "The running voice conversation could not be ended, so the "
                "dictation did not start. Close the voice bar and press the "
                "key again.",
            )
            return False
        task = loop.create_task(
            self._dictate_when_the_microphone_is_free(loop, target=target, source=source),
            name="dictation-handover",
        )
        # The terminal guarantee lives in a done-callback, not in the
        # coroutine's own ``except``, for the same never-started reason.
        task.add_done_callback(self._on_handover_settled)
        self._dictation_handover_task = task
        log.info(
            "Dictation key pressed during a live voice session — hung up, "
            "waiting for the microphone."
        )
        return True

    async def _dictate_when_the_microphone_is_free(
        self, loop: asyncio.AbstractEventLoop, *, target: str, source: str = "api"
    ) -> None:
        """Wait for the hung-up session to release the device, then dictate.

        The hangup has already been requested (see ``_begin_dictation_handover``);
        this is only the wait, and it is BOUNDED. The pipeline reaches IDLE after
        its capture context has exited, so waiting for that state is what keeps
        the dictation from opening a second native stream on the same device
        (AP-24). Nothing here can leave the wake gate closed — the gate is
        derived from this task being alive, so it reopens the moment this
        returns, raises or is cancelled (BUG-037).
        """
        try:
            deadline = loop.time() + _DICTATION_HANDOVER_TIMEOUT_S
            while self._voice_session_holds_microphone():
                if loop.time() >= deadline:
                    log.warning(
                        "Dictation handover timed out after %.1fs — the voice "
                        "session still holds the microphone.",
                        _DICTATION_HANDOVER_TIMEOUT_S,
                    )
                    self._refuse_dictation(
                        "handover_failed",
                        "The voice conversation did not give the microphone back "
                        "in time, so the dictation did not start. Try the key "
                        "again in a moment.",
                    )
                    return
                await asyncio.sleep(_DICTATION_HANDOVER_POLL_S)
            self._commit_dictation(loop, target=target, source=source)
        finally:
            # Not the terminal guarantee — a task cancelled before its first
            # step never runs this. ``_on_handover_settled`` is what always
            # runs; this only releases the handle as early as possible.
            self._dictation_handover_task = None

    def _on_handover_settled(self, task: asyncio.Task[None]) -> None:
        """Terminal guarantee for the handover: it commits, or it explains.

        Runs for EVERY end of the handover task, including one cancelled before
        it ever started — the fastest press-and-release, and the case a plain
        ``except asyncio.CancelledError`` inside the coroutine silently misses.
        Never raises: a callback that throws here would surface as a stray
        "exception in callback" and take the explanation with it (AP-18).
        """
        try:
            if getattr(self, "_dictation_handover_task", None) is task:
                self._dictation_handover_task = None
            if task.cancelled():
                # The key was let go (or a toggle stopped it) while the
                # conversation was still shutting down. Starting the recording
                # now would leave a dictation nobody is holding a key for,
                # running to the duration cap — so say what happened instead.
                # The hangup itself already went through, which is exactly why
                # pressing again works — USUALLY. The sentence checks rather
                # than assumes: a session whose teardown is wedged still holds
                # the device at this moment (BUG-185), and "the microphone is
                # free now" was exactly the lie the user read ten times in a
                # row while nothing they pressed could work.
                if self._voice_session_holds_microphone():
                    detail = (
                        "The voice conversation is still shutting down, so "
                        "nothing was recorded. Hold the key a little longer, "
                        "or press it again once the voice bar has closed."
                    )
                else:
                    detail = (
                        "The voice conversation was still shutting down when "
                        "the dictation key was released, so nothing was "
                        "recorded. The microphone is free now — press the key "
                        "again."
                    )
                self._refuse_dictation("handover_failed", detail)
                return
            error = task.exception()
            if error is not None:
                log.warning("Dictation handover failed: %s", error, exc_info=error)
                self._refuse_dictation(
                    "handover_failed",
                    "Handing the microphone over from the voice conversation "
                    "failed, so the dictation did not start. Try the key again.",
                )
        except Exception:  # noqa: BLE001 — a refusal must never become a crash
            log.debug("Dictation handover callback failed", exc_info=True)

    def _commit_dictation(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        target: str,
        source: str = "api",
        beside_call: bool = False,
    ) -> bool:
        """Arm the wake block, announce the turn and spawn the recording task.

        The commit point shared by the direct start and the handover, so both
        arrive in the dictation lane through exactly one door. Always returns
        ``True``; every reason not to be here is checked by ``start_dictation``.

        ``beside_call`` means a live call keeps running next to this dictation:
        its input is held until the task ends, and the call's hangup event is
        left alone — it belongs to the call, not to this recording.
        """
        self._dictation_started_by = str(source or "api")
        self._dictation_discard_requested = False
        self._dictation_leave_no_trace = False
        self._dictation_beside_call = beside_call
        # A fresh dictation session must NOT inherit a stale hangup. ``_hangup_event``
        # is set by every "auflegen" and is otherwise only cleared when the next
        # VOICE session is accepted (``_run_session``). The dictation lane shares
        # that event in its ``asyncio.wait`` gate, so a leftover hangup from an
        # earlier voice call would finalize this session on its first tick — the
        # mic appears to "stop the instant you click it". Clear it here, mirroring
        # the voice-path ``self._hangup_event.clear()`` at session accept. Beside
        # a live call the event is the CALL's: clearing it could swallow a
        # hangup the user just asked for, and the lane does not wait on it.
        hangup = getattr(self, "_hangup_event", None)
        if hangup is not None and not beside_call:
            hangup.clear()
        if beside_call:
            # Held BEFORE the recording task exists, so the call stops hearing
            # the user as early as possible.
            self._set_voice_input_held(True)
        # Stored RAW ("auto" / "insert" / "chat"). ``auto`` is resolved when the
        # recording ENDS, not here: the window that matters is the one in front
        # when the text is delivered. Clicking "Start dictating" in the app and
        # then switching to the target application is a normal flow, and
        # resolving at start would have sent that text to the chat box.
        self._dictation_target = target if target in ("insert", "chat") else "auto"
        self._dictation_stop_event = asyncio.Event()
        # Watchdog deadline for the wake-word block (see
        # ``_dictation_blocks_activation``). It is a TIMESTAMP, copying the
        # ``_wake_lock_until`` pattern, so a dictation task that somehow never
        # terminates still cannot leave the wake word deaf forever — the worst
        # case is bounded instead of needing an app restart (BUG-037). The
        # allowance on top of the recording cap covers the closing
        # transcription, which runs after the microphone is already released.
        # A 0 recording ceiling means "speak as long as you like", and this
        # deadline must NOT inherit that. Unbounded here would re-open BUG-037:
        # a dictation task that somehow never terminates would leave the wake
        # word deaf until the app is restarted. So an unlimited recording still
        # gets a bounded — generously bounded — wake block. The two are allowed
        # to disagree: the worst case of this one expiring early is a wake word
        # that answers during a very long dictation, which is recoverable in a
        # second; the worst case of it never expiring needs a restart.
        block_s = getattr(self, "_dictation_max_s", _DICTATION_DEFAULT_MAX_S)
        if not block_s:
            block_s = _DICTATION_UNBOUNDED_WAKE_BLOCK_S
        self._dictation_wake_block_until = time.time() + float(block_s) + 60.0
        # Reset BEFORE the task exists: the teardown guarantee below reads this
        # to decide whether a terminal event still has to be published.
        self._dictation_completion_published = False
        # Announce the turn BEFORE the first audio frame. Queued ahead of the
        # session task on purpose: nothing has opened the microphone yet when
        # this method returns, so a UI surface can show "listening" at key-down
        # speed instead of waiting for the first partial transcript — which
        # costs a partial interval plus an STT round-trip, and for a short press
        # never arrives at all.
        self._publish_event_soon(
            DictationStarted(
                source_layer="speech.dictation", target=self._dictation_target
            )
        )
        self._dictation_task = loop.create_task(
            self._dictation_session(), name="dictation"
        )
        if beside_call:
            self._dictation_task.add_done_callback(self._on_beside_call_dictation_done)
        log.info(
            "🎙️ dictation started (transcribe-only, target=%s, via=%s%s).",
            self._dictation_target,
            self._dictation_started_by,
            ", beside a live call" if beside_call else "",
        )
        return True

    def _refuse_dictation(self, reason: str, detail: str) -> None:
        """Log AND announce a refused dictation start.

        ``reason`` must come from ``DICTATION_REFUSAL_REASONS`` — the single
        vocabulary for this value, checked here so a new branch that forgets to
        extend it is caught in the log instead of reaching a UI that has never
        heard of the token (AP-4 / BUG-008).
        """
        if reason not in DICTATION_REFUSAL_REASONS:
            log.warning(
                "Unknown dictation refusal reason %r — add it to "
                "DICTATION_REFUSAL_REASONS.",
                reason,
            )
        log.info("start_dictation refused (%s): %s", reason, detail)
        self._publish_event_soon(
            DictationRefused(
                source_layer="speech.dictation", reason=reason, detail=detail
            )
        )

    def dictation_active(self) -> bool:
        """Is the dictation lane engaged right now? (REST/UI status, cheap.)

        True for the recording AND for the handover that is clearing a voice
        conversation out of the way for one. Both count, because both mean the
        key has been pressed and the lane is owed exactly one outcome — a second
        start in that window is the ``already_running`` no-op, not a race for
        the microphone.
        """
        for name in ("_dictation_task", "_dictation_handover_task"):
            task = getattr(self, name, None)
            if task is not None and not task.done():
                return True
        return False

    def stop_dictation(self) -> bool:
        """Signal the active dictation session to finish (best-effort).

        A handover still in flight is CANCELLED rather than stopped: the
        recording it was about to start has not begun, and letting it start now
        would leave a dictation nobody is holding a key for, running to the
        duration cap. The cancellation publishes its own refusal, so a hold
        gesture released mid-handover still tells the user what happened.
        """
        handover = getattr(self, "_dictation_handover_task", None)
        if handover is not None and not handover.done():
            handover.cancel()
            # Belt and braces: should a recording ALSO be alive (a handover
            # that already committed but has not cleared its handle yet), the
            # stop must reach it too — returning here used to leave the
            # recording running with the stop swallowed (BUG-191).
            task = getattr(self, "_dictation_task", None)
            if task is not None and not task.done():
                self._dictation_stop_event.set()
            return True
        if self._dictation_task is None or self._dictation_task.done():
            return False
        self._dictation_stop_event.set()
        return True

    def request_dictation_stop(self, *, discard: bool = False) -> bool:
        """End a running dictation from OUTSIDE the pipeline's loop — the bar's X.

        The dictation counterpart of ``request_hangup``: the Jarvis Bar runs on
        its own Tk thread (or in a child process, on macOS), while the stop
        event and its waiter belong to the pipeline's asyncio loop, so the
        request is marshalled onto that loop. ``discard=True`` is what the
        close-X means — make it go away, deliver nothing — and matches what the
        same X does to a voice session; the default finishes and delivers, like
        the key. Returns whether a dictation was there to stop, so a caller can
        tell "stopped" from "nothing was running".

        Until BUG-191 the bar drew its X in the dictation modes and resolved
        every click on it to nothing, on the theory that another way to stop
        always existed. With a lost release edge there was none.
        """
        active = self.dictation_active()
        if not active:
            log.debug("request_dictation_stop: no dictation is running.")
            return False
        log.info(
            "📵 request_dictation_stop — %s the running dictation (via=%s).",
            "discarding" if discard else "finishing",
            getattr(self, "_dictation_started_by", "") or "unknown",
        )

        def _dispatch() -> None:
            try:
                if discard:
                    self._dictation_discard_requested = True
                self._dictate_key_down = False
                self.stop_dictation()
                if discard:
                    # The stop event only ends capture. After release the lane
                    # may be waiting on model startup, STT or formatting, so an
                    # explicit discard must cancel that work as well. The task's
                    # completion handler closes the UI and releases the wake gate.
                    task = getattr(self, "_dictation_task", None)
                    if task is not None and not task.done():
                        # Let a just-created session enter its cleanup scope
                        # before cancellation; repeated X clicks must not cancel
                        # the cleanup itself.
                        def _cancel() -> None:
                            if not task.done() and not task.cancelling():
                                task.cancel()

                        if current is not None or (
                            owner is not None and owner.is_running()
                        ):
                            asyncio.get_running_loop().call_soon(_cancel)
                        else:
                            _cancel()
            except Exception:  # noqa: BLE001 — a stop gesture must never crash
                log.exception("request_dictation_stop dispatch failed")

        owner = getattr(self, "_runtime_loop", None)
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if owner is not None and owner.is_running() and current is not owner:
            try:
                owner.call_soon_threadsafe(_dispatch)
                return True
            except RuntimeError:
                log.debug("request_dictation_stop: owner loop closed during dispatch")
        _dispatch()
        return True

    async def _watch_dictation_hold_key(self) -> None:
        """Finish a HOLD recording whose key is physically up — the lost release.

        Runs beside the recording only for a dictation the hold key started.
        Every ``_DICTATE_HOLD_WATCH_POLL_S`` it asks the live trigger whether
        the dictation chord is down. ``None`` means this backend cannot tell
        (no listener, no package, Wayland): the watchdog stands down at once
        and the lane keeps working from edges alone — it never invents a
        release. ``False`` for ``_DICTATE_HOLD_LOST_RELEASE_S`` straight means
        the key-up happened and its edge never arrived; the recording is then
        ended through the same stop event a real release sets, so what was
        said is delivered exactly as if the edge had come (BUG-191).
        """
        trigger = getattr(self, "_hotkey_trigger", None)
        probe = getattr(trigger, "chord_is_down", None)
        if trigger is None or not callable(probe):
            return
        up_since: float | None = None
        while True:
            answer = probe("dictate")
            if answer is None:
                log.debug(
                    "hold-key watchdog: this hotkey backend cannot report key "
                    "state — the recording relies on the release edge alone."
                )
                return
            now = time.monotonic()
            if answer:
                up_since = None
            elif up_since is None:
                up_since = now
            elif now - up_since >= _DICTATE_HOLD_LOST_RELEASE_S:
                log.warning(
                    "The dictation hold key has been physically up for %.1fs and "
                    "no release edge arrived — finishing the recording as the "
                    "release would have (the key-up edge was lost).",
                    now - up_since,
                )
                self._dictate_key_down = False
                self._dictation_stop_event.set()
                return
            await asyncio.sleep(_DICTATE_HOLD_WATCH_POLL_S)

    def _dictation_expected_language(self) -> str:
        """The language the next dictation is expected in: a code, or ``auto``.

        The dictation language when one is chosen; otherwise the language
        recent dictations were in. It decides which on-device model can read
        the recording, and what a clip too short to detect from is told.
        """
        cfg = getattr(self, "_dictation_cfg", None)
        pinned = str(getattr(cfg, "language", "auto") or "auto").strip().lower() or "auto"
        if pinned != "auto":
            return pinned
        try:
            return self._recent_dictation_language() or "auto"
        except Exception:  # noqa: BLE001 — a hint, never a gate
            log.debug("recent dictation language unavailable", exc_info=True)
            return "auto"

    def _dictation_resolution(self) -> Any:
        """The recognizers for the next dictation, resolved when something changed.

        Kept between dictations and resolved again when a speech key was saved
        or removed, an on-device model appeared, or the expected language
        changed (``_reset_dictation_stt`` drops it on a settings change). So a
        key pasted in the settings counts from the next press on, without a
        restart. The rules are in :mod:`dodaios.dictation.recognizers`.
        """
        # One resolution at a time: a dictation resolves in a worker thread
        # while the status route may ask on the event loop.
        with _DICTATION_RESOLUTION_LOCK:
            return self._resolve_dictation_recognizers()

    def _resolve_dictation_recognizers(self) -> Any:
        """The body of ``_dictation_resolution``, under its lock."""
        from dodaios.dictation.recognizers import (
            Resolution,
            credential_signature,
            parakeet_ready,
            resolve_recognizers,
        )
        from dodaios.dictation.take import Recognizer

        config = getattr(self, "_config", None)
        stt_cfg = getattr(config, "stt", None) if config is not None else None
        if stt_cfg is None:
            # A pipeline without a configuration reads with its voice provider.
            voice = getattr(self, "_utterance_stt", None)
            if voice is None:
                return Resolution()
            return Resolution(
                recognizers=(
                    Recognizer(
                        id=str(getattr(voice, "name", "") or type(voice).__name__),
                        provider=voice,
                        on_device=bool(getattr(voice, "runs_on_device", False)),
                    ),
                )
            )

        dictation_cfg = getattr(self, "_dictation_cfg", None)
        language = self._dictation_expected_language()
        has_parakeet = parakeet_ready()
        signature = (credential_signature(stt_cfg), language, has_parakeet)
        cached = getattr(self, "_dictation_resolution_cache", None)
        if cached is not None and cached[0] == signature:
            return cached[1]

        from dodaios.plugins.stt import (
            _stt_family_has_key,
            available_stt_provider_names,
            build_named_stt_provider,
            build_stt_from_config,
            provider_runs_on_device,
        )

        configured = str(getattr(stt_cfg, "provider", "") or "").strip()
        own_prompt = str(getattr(dictation_cfg, "bias_prompt", "") or "").strip()

        def _build(name: str) -> Any | None:
            # No vocabulary in the decoder prompt: a recognizer recites a
            # primed word list over pauses. The vocabulary corrects the
            # finished text instead (see ``_wrap``).
            try:
                patched = stt_cfg.model_copy(
                    update={"provider": name, "bias_prompt": own_prompt}
                )
                return build_stt_from_config(patched, dictionary_bias=False)
            except Exception as exc:  # noqa: BLE001 — one engine less, not no dictation
                log.warning("Dictation recognizer %s could not be built: %s", name, exc)
                return None

        def _cloud(name: str) -> Any | None:
            instance = _build(name)
            # A provider without a usable key is built as the local floor;
            # that is not the cloud provider asked for.
            built_as = str(getattr(instance, "name", "") or "")
            if instance is None or (built_as and provider_runs_on_device(built_as)):
                return None
            return instance

        def _keyed_cloud_names() -> list[str]:
            names = [n for n in available_stt_provider_names() if not provider_runs_on_device(n)]
            if (
                configured
                and configured not in names
                and not provider_runs_on_device(configured)
                and _stt_family_has_key(configured)
            ):
                names.insert(0, configured)
            return names

        def _whisper_in_process() -> Any | None:
            try:
                return build_named_stt_provider(
                    "faster-whisper", stt_cfg, dictionary_bias=False
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("in-process Whisper unavailable for dictation: %s", exc)
                return None

        def _wrap(provider: Any) -> Any:
            try:
                from dodaios.speech.stt_dictionary import wrap_stt_with_dictionary

                provider = wrap_stt_with_dictionary(provider)
            except Exception as exc:  # noqa: BLE001 — corrections are not load-bearing
                log.warning("STT dictionary wrapper unavailable for dictation: %s", exc)
            return meter_stt(
                provider, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
            )

        worker = self._dictation_local_final(dictation_cfg)
        has_accelerator = False
        if worker is not None:
            from dodaios.dictation.local_final import _no_accelerator_answers

            has_accelerator = not _no_accelerator_answers()
            # Without a graphics card the worker reads on the CPU: slow, but
            # the only Whisper there is on such a host.
            worker._allow_cpu = not has_accelerator

        try:
            faster_whisper_here = "faster-whisper" in available_stt_provider_names()
        except Exception:  # noqa: BLE001
            faster_whisper_here = False

        resolution = resolve_recognizers(
            stt_cfg,
            language=language,
            cloud=_cloud,
            keyed_cloud_names=_keyed_cloud_names,
            runs_on_device=provider_runs_on_device,
            whisper_worker=worker,
            whisper_has_accelerator=has_accelerator,
            parakeet=self._dictation_parakeet if has_parakeet else None,
            configured_local=_build,
            whisper_in_process=_whisper_in_process if faster_whisper_here else None,
            wrap=_wrap,
        )
        if worker is not None:
            worker.cloud_behind = any(not r.on_device for r in resolution.recognizers[1:])
        self._dictation_resolution_cache = (signature, resolution)
        log.info(
            "Dictation recognizers: %s%s",
            " -> ".join(
                f"{r.id}{'/' + r.model if r.model else ''}"
                f"{' (on this computer)' if r.on_device else ''}"
                for r in resolution.recognizers
            )
            or "<none>",
            f" [{resolution.detail}]" if resolution.detail else "",
        )
        return resolution

    def _dictation_parakeet(self) -> Any | None:
        """The one Parakeet recognizer of this pipeline, built on first use."""
        instance = getattr(self, "_dictation_parakeet_instance", None)
        if instance is None:
            try:
                from dodaios.plugins.stt.parakeet_local import ParakeetLocalSTT

                instance = ParakeetLocalSTT()
            except Exception as exc:  # noqa: BLE001 — the other recognizers remain
                log.warning("Parakeet recognizer unavailable for dictation: %s", exc)
                return None
            self._dictation_parakeet_instance = instance
        return instance

    def _rest_dictation_parakeet(self) -> None:
        """Free the Parakeet model after a while without a dictation.

        The loaded model holds about 1.5 GB of memory and loads in about a
        second, while the person is already speaking. So it is released after
        at most three minutes without a dictation, sooner than the idle time
        the settings give the local engines, and loaded again with the next
        key press. An idle time of 0 keeps it loaded.
        """
        handle = getattr(self, "_dictation_parakeet_rest", None)
        if handle is not None:
            handle.cancel()
            self._dictation_parakeet_rest = None
        instance = getattr(self, "_dictation_parakeet_instance", None)
        idle_s = self._dictation_idle_release_s(getattr(self, "_dictation_cfg", None))
        if instance is None or idle_s <= 0:
            return
        idle_s = min(idle_s, _DICTATION_PARAKEET_REST_S)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _release() -> None:
            self._dictation_parakeet_rest = None
            if self.dictation_active():
                return
            # Dropping the reference is the whole release; the next dictation
            # builds the recognizer again.
            instance._recognizer = None
            log.info("Parakeet model released after %.0f s without a dictation.", idle_s)

        self._dictation_parakeet_rest = loop.call_later(idle_s, _release)

    def _dictation_stt(self) -> Any:
        """A provider-shaped reader for a finished recording, or ``None``.

        For the callers outside a live dictation (reading a kept recording
        again, a voice note from the phone). It reads through the same
        recognizers, in the same way, as a dictation does.
        """
        try:
            if not self._dictation_resolution().recognizers:
                return None
        except Exception as exc:  # noqa: BLE001 — the voice provider can still read
            log.warning("Dictation recognizers could not be resolved: %s", exc)
            return getattr(self, "_utterance_stt", None)
        from dodaios.dictation.take import RecordingReader

        return RecordingReader(
            lambda: self._dictation_resolution().recognizers,
            language_hint=self._recent_dictation_language,
        )

    def _schedule_dictation_warmup(self, provider: Any = None) -> None:  # noqa: ARG002
        """Start the local Whisper worker off the key-press path. Never raises.

        Only that engine is started ahead: on a machine with a graphics card
        its first start can take minutes. A cloud provider has nothing to
        load, and the Parakeet model loads in about a second when the key
        goes down.
        """
        if getattr(self, "_dictation_warmup_shutdown", False):
            return
        try:
            loop = asyncio.get_running_loop()
            recognizers = self._dictation_resolution().recognizers
        except Exception as exc:  # noqa: BLE001 — the first press loads it instead
            log.debug("dictation warm-up skipped: %s", exc)
            return
        if not recognizers or recognizers[0].id != "faster-whisper":
            return
        warm = getattr(recognizers[0].provider, "warm_up", None)
        current = getattr(self, "_dictation_warmup_task", None)
        if not callable(warm) or (current is not None and not current.done()):
            return

        async def _warm() -> None:
            started = time.monotonic()
            try:
                await asyncio.to_thread(warm)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the first press loads it instead
                log.warning("Dictation recognizer warm-up failed: %s", exc)
            else:
                log.info(
                    "Dictation recognizer warm-up done in %.0f ms.",
                    (time.monotonic() - started) * 1000.0,
                )

        self._dictation_warmup_task = loop.create_task(_warm(), name="dictation-stt-warmup")

    @staticmethod
    def _dictation_idle_release_s(dictation_cfg: Any) -> float:
        """Seconds without a dictation after which the local engines are released."""
        from dodaios.dictation.idle_release import DEFAULT_IDLE_MINUTES

        minutes = getattr(dictation_cfg, "local_idle_minutes", None)
        try:
            return max(0.0, float(DEFAULT_IDLE_MINUTES if minutes is None else minutes)) * 60.0
        except (TypeError, ValueError):
            return DEFAULT_IDLE_MINUTES * 60.0

    def _dictation_local_final(self, dictation_cfg: Any) -> Any:
        """The out-of-process local Whisper engine of this pipeline, or ``None``.

        ``None`` when the person switched it off (``[dictation].local_engine``)
        or the local runtime is not importable here. One instance is kept for
        the life of the pipeline, because it owns a worker process; it is
        replaced only when its model or memory setting changed. What changes
        from press to press (free accelerator memory, a worker that fails to
        start) is the engine's own business: it refuses such a call with a
        failure the take answers by moving to the next recognizer.
        """
        cached = getattr(self, "_dictation_whisper_worker", None)
        if not bool(getattr(dictation_cfg, "local_engine", True)):
            if cached is not None:
                self._dictation_whisper_worker = None
                self._close_dictation_worker(cached[1])
            return None
        try:
            from dodaios.dictation.local_final import (
                DEFAULT_FINAL_MODEL,
                DEFAULT_MIN_FREE_GB,
                LocalFinalSTT,
            )
            from dodaios.dictation.local_preview import faster_whisper_available

            if not faster_whisper_available():
                return None
            model = str(getattr(dictation_cfg, "local_model", "") or "").strip()
            min_free = getattr(dictation_cfg, "local_min_free_gb", DEFAULT_MIN_FREE_GB)
            key = (
                model or DEFAULT_FINAL_MODEL,
                float(min_free if min_free is not None else 0.0),
                self._dictation_idle_release_s(dictation_cfg),
            )
            if cached is not None and cached[0] == key:
                return cached[1]
            if cached is not None:
                self._close_dictation_worker(cached[1])
            worker = LocalFinalSTT(key[0], min_free_gb=key[1], idle_release_s=key[2])
            self._dictation_whisper_worker = (key, worker)
            return worker
        except Exception as exc:  # noqa: BLE001 — the other recognizers remain
            log.warning("Local Whisper engine unavailable for dictation (%s).", exc)
            return None

    @staticmethod
    def _close_dictation_worker(worker: Any) -> None:
        """Stop a replaced local Whisper engine's worker process. Never raises."""
        try:
            worker.close()
        except Exception:  # noqa: BLE001 — a worker that will not close is already gone
            log.debug("closing the replaced dictation worker failed", exc_info=True)

    def _reset_dictation_stt(self) -> None:
        """Drop what a provider or language change makes stale.

        Called from every place that swaps the voice provider, the recognition
        language or a dictation setting. The dictation's recognizers are
        resolved again on the next press, and the voice lane's crossover cache
        is cleared with them: it holds provider instances built from the old
        language and a chain resolved against the old provider.
        """
        self._dictation_resolution_cache = None

    def _dictation_protected_terms(self) -> tuple[str, ...]:
        """Spellings the polish pass may not "correct" into something familiar.

        The reference dictation tool's own documentation warns about this
        failure direction explicitly: a rewrite model turns an unfamiliar
        technical term into the common word it resembles, and the user cannot
        tell it happened because the sentence still reads fine. So the words a
        user has already told us they care about travel with the request and are
        checked afterwards by the drift guard.

        Three sources: the STT dictionary (words the user added by hand for
        exactly this reason, plus the shipped defaults they kept), the configured wake
        word (a name, and names are what get "corrected"), and the assistant
        name derived from it. Nothing here is a secret and nothing is free text
        from a voice turn — AP-2 territory stays out of the prompt.

        Never raises and never blocks: an unreadable dictionary costs the guard
        its input, not the user their dictation.
        """
        terms: list[str] = []
        try:
            # Shipped defaults included (the product name, PyPI, GitHub …):
            # a rewrite model "correcting" them is the same failure.
            from dodaios.speech.stt_dictionary import dictionary_protected_words

            terms.extend(dictionary_protected_words())
        except Exception as exc:  # noqa: BLE001 — an unreadable store is not fatal
            log.debug("dictation protected terms: dictionary unavailable (%s)", exc)
        phrase = getattr(self, "_wake_phrase_label", "") or ""
        for word in str(phrase).split():
            if len(word) >= 2:
                terms.append(word)
        seen: set[str] = set()
        unique: list[str] = []
        for term in terms:
            key = term.strip().casefold()
            if key and key not in seen:
                seen.add(key)
                unique.append(term.strip())
        return tuple(unique)

    async def _dictation_session(self) -> None:
        """Record one dictation, recognize it once, deliver the text.

        The microphone is taken over (or opened when nothing else holds it)
        and everything it hears goes into one take
        (:mod:`dodaios.dictation.take`). No text exists while the person
        speaks: the take cuts a long recording at the speaker's own pauses and
        reads each piece once, in the background, so after the stop only the
        last piece is left to read. Then the text is formatted, delivered and
        recorded by ``_finish_dictation``.

        The stop event, the recording cap, a hangup and the end of the input
        stream each end the recording; a hangup or the bar's discard delivers
        nothing. The brain, TTS and the turn state machine are not involved,
        and the whole session is fail-open so a dictation error never breaks a
        later voice turn. Exactly one ``DictationCompleted`` ends it.
        """
        from dodaios.dictation.audio_preprocessing import (
            AudioQualityAccumulator,
            assess_desktop_audio_preprocessing,
        )
        from dodaios.dictation.take import MIN_SPEECH_S, Take, TakeResult

        # ``getattr`` defaults keep pipelines built via ``__new__`` working.
        cfg = getattr(self, "_dictation_cfg", None)
        target = getattr(self, "_dictation_target", "chat")
        pinned_language = (
            str(getattr(cfg, "language", "auto") or "auto").strip().lower() or "auto"
        )
        # The take starts without its recognizers, so nothing stands between
        # the key press and the open microphone. Which engines read it is
        # found out beside the recording, off the event loop: after a saved
        # key or on the first press that means building providers and asking
        # the hardware, and a first word must not be lost to that.
        take = Take(
            None,
            language=pinned_language,
            language_hint=self._recent_dictation_language(),
        )

        async def _find_recognizers() -> None:
            recognizers: tuple[Any, ...] = ()
            try:
                resolution = await asyncio.to_thread(self._dictation_resolution)
                recognizers = tuple(resolution.recognizers)
            except Exception as exc:  # noqa: BLE001 — reported as "nothing to read with"
                log.warning("Dictation recognizers could not be resolved: %s", exc)
            take.set_recognizers(recognizers)
            # The engine starts loading while the person speaks, not with the
            # first piece to read.
            take.warm()

        recognizers_task = asyncio.create_task(
            _find_recognizers(), name="dictation-recognizers"
        )
        handle = getattr(self, "_dictation_parakeet_rest", None)
        if handle is not None:
            handle.cancel()
            self._dictation_parakeet_rest = None

        audio_cfg = getattr(getattr(self, "_config", None), "audio", None)
        audio_preprocessing = assess_desktop_audio_preprocessing(
            echo_cancellation_requested=bool(
                getattr(audio_cfg, "echo_cancellation", True)
            ),
        )
        audio_quality = AudioQualityAccumulator()
        capture_reported_dropouts = 0
        capture_restart_count = 0
        capture_overflows = 0
        started_at = time.monotonic()
        hung_up = False
        # Set when the RECORDING ended before the person did.
        capture_error: str | None = None
        # True once delivery was entered, so the crash handler below never
        # delivers a second time.
        finished = False
        try:
            # ONE microphone owner at a time: this takes the live wake stream
            # over when there is one and opens its own capture otherwise
            # (AP-24). The wake side gets its stream back on exit.
            async with self._capture_dictation_input() as source:
                # PortAudio's overflow counter is cumulative for the stream;
                # what this dictation lost is the difference from here.
                overflow_base = _capture_counter(source, "overflow_count")

                async def _drain() -> None:
                    async for chunk in source.stream():
                        audio_quality.add_chunk(
                            chunk.pcm,
                            sample_rate_hz=int(
                                getattr(chunk, "sample_rate", 16_000) or 16_000
                            ),
                            timestamp_ns=int(getattr(chunk, "timestamp_ns", 0) or 0),
                        )
                        take.feed(chunk.pcm)
                        # The live loudness moves the bar's and the composer's
                        # waveform; zero cost when nobody is subscribed.
                        if mic_level.has_subscribers():
                            samples = pcm_bytes_to_np(chunk.pcm)
                            if samples.size:
                                mic_level.feed(
                                    float(np.sqrt(np.mean(np.square(samples))))
                                )

                drain_task = asyncio.create_task(_drain(), name="dictation-drain")
                stop_task = asyncio.create_task(self._dictation_stop_event.wait())
                # Beside a live call the hangup event is the CALL's: hanging up
                # the conversation must not throw away what is being dictated.
                hangup_event = (
                    asyncio.Event()
                    if getattr(self, "_dictation_beside_call", False)
                    else self._hangup_event
                )
                hangup_task = asyncio.create_task(hangup_event.wait())
                # A recording the HOLD key started is owed a release edge; the
                # watchdog sets the stop event when the key is physically up
                # and that edge never came (BUG-191).
                hold_task = (
                    asyncio.create_task(
                        self._watch_dictation_hold_key(), name="dictation-hold-watch"
                    )
                    if getattr(self, "_dictation_started_by", "") == "hold_key"
                    else None
                )
                try:
                    done, _pending = await asyncio.wait(
                        {stop_task, hangup_task, drain_task},
                        # ``None`` waits as long as it takes, which is what a
                        # cap of 0 means.
                        timeout=self._dictation_max_s or None,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    hung_up = hangup_task in done or hangup_event.is_set()
                    if getattr(self, "_dictation_discard_requested", False):
                        # The bar's close-X: nothing read, nothing delivered.
                        hung_up = True
                    if stop_task in done:
                        ended_by = "discard" if hung_up else "stop"
                    elif hangup_task in done:
                        ended_by = "hangup"
                    elif drain_task in done:
                        ended_by = "input ended"
                    else:
                        ended_by = f"the {self._dictation_max_s:.0f}s recording cap"
                    log.info(
                        "dictation recording ended by %s after %.1fs (via=%s).",
                        ended_by,
                        time.monotonic() - started_at,
                        getattr(self, "_dictation_started_by", "") or "unknown",
                    )
                    if drain_task in done and not drain_task.cancelled():
                        drain_exc = drain_task.exception()
                        if drain_exc is not None:
                            # The microphone went away. What was recorded is
                            # still read; the outcome says the recording was
                            # cut short instead of presenting it as whole.
                            capture_error = "recording_interrupted"
                            log.warning(
                                "dictation recording ended early — %s: %s",
                                capture_error,
                                f"{type(drain_exc).__name__}: {drain_exc}".strip(),
                            )
                        else:
                            log.info(
                                "dictation input stream ended; reading what was "
                                "recorded."
                            )
                    capture_overflows = max(
                        0, _capture_counter(source, "overflow_count") - overflow_base
                    )
                    capture_reported_dropouts = (
                        int(getattr(source, "dropped_frames", 0) or 0) + capture_overflows
                    )
                    capture_restart_count = int(getattr(source, "restart_count", 0) or 0)
                finally:
                    side_tasks = [drain_task, stop_task, hangup_task]
                    if hold_task is not None:
                        side_tasks.append(hold_task)
                    for t in side_tasks:
                        t.cancel()
                    for t in side_tasks:
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110
                            # Cancelled above; a drain error was read already.
                            pass

            # The microphone is closed on every end path. Now is the moment to
            # say "no longer listening, still working". A hangup skips it:
            # nothing is read and ``DictationCompleted`` follows at once.
            if hung_up:
                take.cancel()
                result = TakeResult(duration_s=take.duration_s)
            else:
                await self._publish_dictation_event(
                    DictationTranscribing(source_layer="speech.dictation")
                )
                await recognizers_task
                result = await take.finish()

            wall_clock_s = max(0.0, time.monotonic() - started_at)
            quality_metrics = audio_quality.snapshot(
                reported_dropouts=capture_reported_dropouts
            )
            finished = True
            final_text = await self._finish_dictation(
                raw_text=result.text,
                language=result.language,
                # The length of the recording, from the audio itself: the
                # statistics divide the word count by it.
                duration_s=result.duration_s,
                target=target,
                hung_up=hung_up,
                # A recording that ended early outranks a recognition error:
                # it explains a short text every later layer would otherwise
                # present as complete.
                stt_error=capture_error or result.error,
                lost_audio_s=result.lost_audio_s,
                dropped_audio_s=quality_metrics.dropout_duration_ms / 1000.0,
                no_speech=not hung_up and result.speech_s < MIN_SPEECH_S,
                audio=take.audio,
                stt_providers=result.recognizers,
                stt_models=result.models,
                detected_languages=result.languages,
                stt_latency_ms=result.latency_ms,
                stt_calls=result.calls,
                stt_errors=result.errors,
                stt_audit=(
                    *result.audit(),
                    f"capture_overflows:{capture_overflows}",
                    f"capture_restarts:{capture_restart_count}",
                    *audio_preprocessing.audit(),
                ),
                audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                audio_rms=quality_metrics.rms,
                audio_clipping_ratio=quality_metrics.clipping_ratio,
                audio_dropouts=quality_metrics.dropout_count,
                audio_dropout_ms=quality_metrics.dropout_duration_ms,
            )
            log.info(
                "🎙️ dictation ended (%d chars, %.1fs recorded, %.1fs of speech, "
                "%.1fs elapsed, text %.2fs after the stop, target=%s, read by %s "
                "in %d piece(s), %d of %d reading(s) ahead kept%s%s%s).",
                len(final_text),
                result.duration_s,
                result.speech_s,
                wall_clock_s,
                result.wait_after_stop_ms / 1000.0,
                target,
                ", ".join(result.recognizers) or "nothing",
                result.pieces,
                result.reads_ahead_kept,
                result.reads_ahead,
                ", hung up" if hung_up else "",
                f", capture: {capture_error}" if capture_error else "",
                (
                    f", LOST {result.lost_audio_s:.1f}s of speech "
                    f"({result.error}: {result.error_detail or 'no detail'})"
                    if result.lost_audio_s
                    else (
                        f", {len(result.errors)} failed call(s) covered by the stand-in"
                        if result.errors
                        else ""
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 — dictation must never break voice
            log.warning("dictation session crashed (non-fatal)", exc_info=True)
            if finished:
                # Delivery published its own final text; entering it again
                # would publish twice.
                return
            # Before delivery: the failure goes THROUGH the normal finish, so
            # it is published, recorded as ``failed`` and keeps its recording.
            try:
                quality_metrics = audio_quality.snapshot(
                    reported_dropouts=capture_reported_dropouts
                )
                await self._finish_dictation(
                    raw_text="",
                    language="",
                    duration_s=take.duration_s,
                    target=target,
                    hung_up=False,
                    stt_error=classify_stt_failure(exc),
                    audio=take.audio,
                    audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                    audio_rms=quality_metrics.rms,
                    audio_clipping_ratio=quality_metrics.clipping_ratio,
                    audio_dropouts=quality_metrics.dropout_count,
                    audio_dropout_ms=quality_metrics.dropout_duration_ms,
                )
            except Exception:  # noqa: BLE001 — the fallback must not raise either
                log.debug("dictation failure record failed", exc_info=True)
                try:
                    await self._publish_event(
                        DictationTranscript(
                            source_layer="speech.dictation", text="", is_final=True
                        )
                    )
                except Exception:  # noqa: BLE001, S110
                    # The primary failure is already logged; this event is optional.
                    pass
        finally:
            # Nothing of this recording keeps reading after the session, and
            # the Parakeet model is released once nobody has dictated for a
            # while.
            take.cancel()
            if not recognizers_task.done():
                recognizers_task.cancel()
            try:
                self._rest_dictation_parakeet()
            except Exception:  # noqa: BLE001 — a release is tidying, never a gate
                log.debug("Parakeet idle release not scheduled", exc_info=True)
            # Terminal-event guarantee. Surfaces open on ``DictationStarted``
            # and close on ``DictationCompleted``. A cancellation skips the
            # handler above and a crash inside delivery can end before its own
            # completion; both land here. Scheduled rather than awaited,
            # because awaiting inside a cancelled task is not reliable.
            if not getattr(self, "_dictation_completion_published", True):
                self._dictation_completion_published = True
                quality_metrics = audio_quality.snapshot(
                    reported_dropouts=capture_reported_dropouts
                )
                self._publish_event_soon(
                    DictationCompleted(
                        source_layer="speech.dictation",
                        outcome="cancelled",
                        # A hold key's early start taken back by a shortcut
                        # is not news: nobody dictated, so nothing is said.
                        detail=(
                            ""
                            if getattr(self, "_dictation_leave_no_trace", False)
                            else "The dictation ended before it produced text."
                        ),
                        duration_s=take.duration_s,
                        audio_sample_rate_hz=quality_metrics.sample_rate_hz,
                        audio_rms=quality_metrics.rms,
                        audio_clipping_ratio=quality_metrics.clipping_ratio,
                        audio_dropouts=quality_metrics.dropout_count,
                        audio_dropout_ms=quality_metrics.dropout_duration_ms,
                    )
                )

    #: How much audio a CLOUD reading needs before it is allowed to steer later
    #: dictations. Under this, the provider is guessing from too little context
    #: — which is the defect this anchor exists to route around, so accepting a
    #: short reading here would let the guess teach itself.
    _LANGUAGE_ANCHOR_MIN_S = 6.0

    #: How many readings the anchor remembers. Small enough to follow a speaker
    #: who switches language within a few dictations, large enough that one
    #: mis-detected clip cannot flip it on its own.
    _LANGUAGE_ANCHOR_HISTORY = 5

    def _remember_dictation_language(self, language: str, *, on_device: bool) -> None:
        """Record one reading of what this user dictates in. Never raises.

        The anchor behind ``_recent_dictation_language``. An ``on_device``
        reading is trusted outright — a local decoder cannot have translated the
        audio, so its answer is about the SOUND. A cloud reading is a claim
        about a transcript that may itself be a translation, so the caller only
        offers one when there was enough audio to make the claim worth
        something, and it still only ever gets a vote rather than the decision.
        """
        code = str(language or "").strip().lower()
        if not code or code in ("auto", "unknown", "und"):
            return
        readings = getattr(self, "_dictation_language_readings", None)
        if readings is None:
            from collections import deque

            readings = deque(maxlen=self._LANGUAGE_ANCHOR_HISTORY)
            self._dictation_language_readings = readings
        # An on-device reading is worth the whole window, because it is the one
        # signal a translation cannot fake: one of them outvotes a run of cloud
        # guesses instead of waiting its turn behind them.
        readings.extend([code] * (readings.maxlen if on_device else 1))

    def _prime_dictation_language_anchor(self) -> None:
        """Seed the anchor from the stored history, once per process.

        Without this the anchor is empty after every app start, so the first
        short dictation of a session is back to asking two seconds of audio
        which language it is — the exact case this exists to avoid. The history
        already holds the answer: what this person dictated in yesterday is a
        better opening guess than nothing at all.

        Cheap enough to do inline (measured: ~1.6 ms for a 147 KB history) and
        it happens on the first dictation, never at boot (AP-26). Failure is a
        no-op: an unreadable history costs an opening guess, never a dictation.
        """
        if getattr(self, "_dictation_anchor_primed", False):
            return
        self._dictation_anchor_primed = True
        try:
            from dodaios.dictation.history import DictationHistory

            entries = DictationHistory().list_all(include_discarded=True)
            recent = [
                entry
                for entry in entries
                if float(getattr(entry, "duration_s", 0.0) or 0.0)
                >= self._LANGUAGE_ANCHOR_MIN_S
            ][: self._LANGUAGE_ANCHOR_HISTORY]
            # Oldest first, so the newest readings are the ones the bounded
            # window keeps — a person who switched language last week must not
            # be anchored to the language they used before that.
            for entry in reversed(recent):
                self._remember_dictation_language(
                    str(getattr(entry, "language", "") or ""), on_device=False
                )
        except Exception:  # noqa: BLE001 — an opening guess is never worth a failure
            log.debug("dictation language anchor priming failed", exc_info=True)

    def _recent_dictation_language(self) -> str:
        """The language recent dictations agree on, or ``""`` when unclear.

        Read at the START of a dictation, where it becomes the session language
        a short recording could never establish for itself. A MAJORITY rather
        than the last reading, so a single mis-detected clip cannot redirect the
        next one; ties resolve to ``""``, which simply restores auto-detect.
        """
        self._prime_dictation_language_anchor()
        readings = getattr(self, "_dictation_language_readings", None)
        if not readings:
            return ""
        from collections import Counter

        counts = Counter(readings).most_common()
        if len(counts) > 1 and counts[0][1] == counts[1][1]:
            return ""
        return counts[0][0]

    async def _publish_dictation_event(self, event: Any) -> bool:
        """Deliver to healthy observers in order without waiting on a dead UI.

        The bus fans out concurrently, so an unrelated stalled observer cannot
        delay a healthy recipient. The bounded await still joins cancellation;
        no publication task is left behind to reorder a later dictation.
        """
        try:
            await asyncio.wait_for(
                self._publish_event(event), timeout=_DICTATION_EVENT_TIMEOUT_S
            )
        except TimeoutError:
            log.warning(
                "Dictation event %s exceeded %.1fs; abandoning stalled observers.",
                type(event).__name__,
                _DICTATION_EVENT_TIMEOUT_S,
            )
            return False
        return True

    async def _tell_silent_microphone(self, input_name: str) -> None:
        """Publish which microphone a dictation heard nothing from (never raises).

        The window turns it into the notice that names the input and opens the
        microphone picker; the bar keeps showing the dictation's own sentence.
        """
        try:
            await self._publish_event(
                MicrophoneTrouble(
                    source_layer="speech.pipeline",
                    reason="silent",
                    device=input_name,
                    feature="dictation",
                    automatic=getattr(self, "_input_device", None) == "auto-headset",
                )
            )
        except Exception:  # noqa: BLE001 - a notice must never cost the dictation its result
            log.debug("The silent-microphone notice could not be published.", exc_info=True)

    async def _finish_dictation(
        self,
        *,
        raw_text: str,
        language: str,
        duration_s: float,
        target: str,
        hung_up: bool,
        stt_error: str | None = None,
        lost_audio_s: float = 0.0,
        dropped_audio_s: float = 0.0,
        audio: bytes | None = None,
        stt_providers: tuple[str, ...] = (),
        stt_models: tuple[str, ...] = (),
        detected_languages: tuple[str, ...] = (),
        stt_latency_ms: int = 0,
        stt_calls: int = 0,
        stt_errors: tuple[str, ...] = (),
        stt_audit: tuple[str, ...] = (),
        audio_sample_rate_hz: int = 0,
        audio_rms: float = 0.0,
        audio_clipping_ratio: float = 0.0,
        audio_dropouts: int = 0,
        audio_dropout_ms: int = 0,
        no_speech: bool = False,
    ) -> str:
        """Format, deliver and record one finished dictation. Returns the text.

        ``no_speech`` says the recording held no speech at all (a tap on the
        key, a muted or wrong microphone). No recognizer was asked then, and
        the outcome names the microphone as the thing to check.

        Split out of ``_dictation_session`` so the delivery half is testable
        without a microphone. Every step degrades on its own: a failed cleanup
        falls back to the raw transcript, a failed insertion falls back to "it
        is on your clipboard", and a failed history write costs nothing but the
        history entry.

        ``stt_error`` is the transcription failure, if there was one. It is what
        makes ``failed`` distinguishable from ``empty``, so it is carried into
        the completion event and the history row rather than logged and dropped.
        It is normalised to a reason code HERE rather than trusted from the
        caller: this method is the one place the value is persisted and
        published, and a raw provider string reaching it is exactly how a Python
        exception class and a vendor URL ended up rendered under a user's own
        dictated words. A backstop at the store beats a rule every future caller
        has to remember.

        ``lost_audio_s`` is how many seconds of the recording were attempted
        and never read — see the ``partial`` entry in
        ``dodaios.dictation.outcomes``. It is a SEPARATE argument from
        ``stt_error`` on purpose, and the distinction is the whole of the fix:
        an error says something went wrong, this says something was lost, and
        only the second one is a reason to stop calling the dictation a success
        and to keep its audio. Defaults to zero so every existing caller (and
        the crash path below) keeps today's behaviour exactly.

        ``dropped_audio_s`` is the OTHER way to end up missing words, and it is
        kept apart from ``lost_audio_s`` because the two owe the user different
        sentences. Lost audio was recorded and never read — a retry could still
        read it, which is what Restore offers. Dropped audio was never recorded:
        the capture queue overflowed while the loop was busy and those frames
        are gone, so promising Restore would point at a button that cannot help.
        Both degrade the outcome to ``partial``; only the first one promises
        anything.

        ``audio`` is the session's raw PCM; it is written to a local sidecar
        only when the dictation left the user missing words AND they allow it
        (``[dictation].keep_failed_audio``), which is what a later Restore
        transcribes again.
        """
        finish_started = time.perf_counter()
        stt_error = normalize_stt_failure(stt_error)
        cleaned = raw_text
        removed_words = 0
        cleanup_reason = ""
        cfg = getattr(self, "_dictation_cfg", None)

        # A user-pinned ``[dictation].language`` outranks whatever the provider
        # reported. Without this the cleanup rules see the provider's guess —
        # and a provider that answers "unknown" leaves every dictation with
        # reason="no_rules", i.e. no cleanup at all despite an explicit pin.
        pinned = str(getattr(cfg, "language", "auto") or "auto").strip().lower()
        # Which language the cleanup rules — and the polish pass — run in. The
        # decision itself lives in ``resolve_dictation_language`` at module
        # level, because the Restore route re-transcribes the same audio and has
        # to reach the same answer. A hangup transcribed nothing, so there is no
        # text to resolve from and the reported tag stands.
        effective_language = resolve_dictation_language(
            pinned=pinned,
            reported=language,
            text="" if hung_up else raw_text,
        )

        # Teach the anchor what this user dictates in, so the NEXT recording —
        # which may be two seconds of "carry on" — is not left asking a clip too
        # short to answer. Only a long recording votes: a short one is exactly
        # the case the provider gets wrong, and letting it vote would let the
        # guess confirm itself. The reading is the resolved language, so a user
        # pin outranks everything here as it does everywhere else.
        if not hung_up and duration_s >= self._LANGUAGE_ANCHOR_MIN_S:
            try:
                self._remember_dictation_language(
                    effective_language, on_device=False
                )
            except Exception:  # noqa: BLE001 — an anchor is a hint, never a gate
                log.debug("dictation language anchor update failed", exc_info=True)

        if raw_text and not hung_up:
            # The rules that turn the recognizer's text into the dictation:
            # pause marks out, spoken paragraph and line commands in,
            # hesitation sounds out, punctuation repaired. No model call.
            try:
                from dodaios.dictation.formatting import format_dictation

                formatted = format_dictation(
                    raw_text,
                    language=effective_language,
                    fillers=bool(getattr(cfg, "remove_fillers", True)),
                    paragraphs=bool(getattr(cfg, "auto_paragraphs", True)),
                    max_removed_fraction=float(
                        getattr(cfg, "filler_max_removed_fraction", 0.25)
                    ),
                )
                cleaned = formatted.text
                removed_words = formatted.removed_words
                cleanup_reason = formatted.filler_reason
            except Exception:  # noqa: BLE001 — never lose the text to a formatting bug
                log.warning("dictation formatting failed; using the recognized text",
                            exc_info=True)
                cleaned = raw_text

        # Two kinds of text must never reach a document, and both used to.
        #
        # (a) Whisper's silence boilerplate. Every Whisper-family model answers a
        #     near-silent microphone with the same handful of subtitle credits
        #     and video outros — 12 of the first 26 rows of the live history are
        #     "Thank you." or "Thank you for watching!", none of them spoken. The
        #     repo has owned the marker list for months and the voice lane
        #     filters on it in four places; the dictation lane never did.
        # (b) A transcript with no WORDS in it. A bare "." was pasted into a live
        #     document (history row 2026-07-28T18:10:30) and the clipboard was
        #     then restored over it, so the user was left holding a stray full
        #     stop and no way back to what they had copied.
        #
        # Blanking the text HERE, rather than only skipping the insertion, is
        # deliberate: the final transcript published below also feeds the chat
        # composer and the bar, and a dictation that reports "empty" while its
        # text already sits in the composer is the same defect in a different
        # window. ``raw_text`` is untouched, so the history row still shows what
        # the provider returned and a later Restore can transcribe the audio
        # again. Fail-open like every other step here: a broken gate costs the
        # gate, never the user's words.
        rejected_detail = ""
        if no_speech and not stt_error:
            rejected_detail = (
                "No speech was heard, so nothing was inserted. Check that the "
                "right microphone is selected and not muted."
            )
            if audio_sample_rate_hz > 0 and audio_rms == 0.0 and duration_s >= 0.5:
                # Exact zeros are not a quiet room: the input carries nothing.
                # Say WHICH input: "the microphone" is whichever one the
                # automatic choice landed on, and the person cannot see that.
                silent_input = last_input_name()
                named = f"The microphone '{silent_input}'" if silent_input else "The microphone"
                rejected_detail = (
                    f"{named} delivered no signal at all, so nothing was "
                    "inserted. Choose another microphone in Settings, or check "
                    "that this one is not muted."
                )
                await self._tell_silent_microphone(silent_input)
        if raw_text.strip() and not cleaned.strip() and not hung_up and not rejected_detail:
            # The rules left nothing: the recognizer returned marks, no words.
            rejected_detail = (
                "The dictation produced punctuation but no words, so "
                "nothing was inserted."
            )
        if cleaned.strip() and not hung_up:
            try:
                from dodaios.dictation.cleanup import count_words

                if count_words(cleaned) == 0:
                    rejected_detail = (
                        "The dictation produced punctuation but no words, so "
                        "nothing was inserted."
                    )
                elif _is_silence_hallucination(cleaned, duration_s):
                    rejected_detail = (
                        "The audio was too quiet to resolve, so nothing was "
                        "inserted."
                    )
                if rejected_detail:
                    log.info(
                        "dictation delivery refused (%.1fs of audio, %r): %s",
                        duration_s,
                        cleaned[:80],
                        rejected_detail,
                    )
                    cleaned = ""
            except Exception:  # noqa: BLE001 — a broken guard never eats the text
                log.debug("dictation delivery gate failed", exc_info=True)
                rejected_detail = ""

        # The generative polish pass — the second read-over that turns a
        # transcript into written prose (punctuation, sentence structure, the
        # capitalisation our own ~8 s segment boundaries destroy). No regex can
        # do this, which is why the deterministic cleanup above closes only half
        # the gap.
        #
        # It sits HERE, after the delivery gates and before the publish, for two
        # reasons. After the gates, so we never spend a model call polishing
        # boilerplate we are about to throw away. Before the publish, so the
        # chat composer, the Jarvis Bar and the insertion all see the SAME
        # string — a polished paste next to an unpolished composer is the kind
        # of divergence nobody can explain afterwards. ``raw_text`` is untouched
        # and still reaches the history, so the user can always recover the
        # words they actually said.
        #
        # Fail-open twice over: ``polish_transcript`` itself never raises and
        # returns the raw text on every non-``applied`` status, and this block
        # additionally catches anything the import or the call surfaces. The
        # import is INSIDE the function (AP-26) exactly like ``clean_transcript``
        # above — nothing about the polish pass may reach the boot path.
        # The same pass also delivers the dictation in a fixed language when
        # ``[dictation].translate`` is on — one model call does both, so a
        # translation costs the same single round trip a polish does.
        polish_status = ""
        polish_provider = ""
        polish_latency_ms = 0
        if cleaned.strip() and not hung_up:
            try:
                from dodaios.dictation.polish import (
                    polish_enabled,
                    polish_transcript,
                    resolve_translate_target,
                )

                # Resolved HERE and not inside the pass so both callers of the
                # pass — this one and the Restore route — reach the same answer
                # from the same function, exactly like ``effective_language``
                # above. It reads the CONFIG only, deliberately NOT
                # ``effective_language``: deciding per dictation whether to
                # translate, based on a recognizer tag that is documented to be
                # wrong, is what made the delivered language alternate between
                # two with nothing the user touched explaining it.
                translate_to = resolve_translate_target(cfg)

                # Prompt Mode outranks both passes: the whole dictation is
                # rewritten into a brief for a coding agent, so neither the
                # wording pass nor the translator has anything left to do.
                # When it cannot deliver (no writer, timeout, an answer that
                # is not a prompt) the dictation falls through to the passes
                # below exactly as if the switch were off.
                from dodaios.dictation.prompt_mode import (
                    STATUS_PROMPTED,
                    compose_prompt,
                    prompt_mode_enabled,
                )

                prompted = False
                if prompt_mode_enabled(cfg):
                    result = await compose_prompt(
                        cleaned,
                        cfg=cfg,
                        protected_terms=self._dictation_protected_terms(),
                        language=effective_language,
                    )
                    prompted = result.status == STATUS_PROMPTED
                    log.info(
                        "dictation prompt mode: %s (%s, %d ms%s).",
                        result.status,
                        result.provider or "no writer",
                        result.latency_ms,
                        f", {result.reason}" if result.reason else "",
                    )
                    if prompted:
                        cleaned = result.text
                        polish_status = result.status
                        polish_provider = result.provider
                        polish_latency_ms = result.latency_ms

                if prompted:
                    pass  # delivered above; the passes below are superseded
                elif polish_enabled(cfg) or translate_to:
                    result = await polish_transcript(
                        cleaned,
                        language=effective_language,
                        cfg=cfg,
                        protected_terms=self._dictation_protected_terms(),
                        style=str(getattr(cfg, "polish_style", "neutral") or "neutral"),
                        translate_to=translate_to,
                    )
                    cleaned = result.text
                    polish_status = result.status
                    polish_provider = result.provider
                    polish_latency_ms = result.latency_ms
                    log.info(
                        "dictation %s: %s (%s, %d ms%s).",
                        f"translation to {translate_to}" if translate_to else "polish",
                        polish_status,
                        polish_provider or "no provider",
                        polish_latency_ms,
                        f", {result.reason}" if result.reason else "",
                    )
                else:
                    polish_status = "off"
            except Exception:  # noqa: BLE001 — never lose the text to the polish pass
                log.warning(
                    "dictation polish failed; using the unpolished transcript",
                    exc_info=True,
                )
                polish_status = "provider_error"

        # Resolve ``auto`` now: the foreground window at DELIVERY time is the
        # one the user means, not the one that happened to be in front when
        # recording started.
        #
        # Resolved BEFORE the publish below because the answer RIDES on that
        # event. The UI sees a final transcript on both routes, so without it
        # there is no way to tell "this belongs in the app" from "this is
        # already being pasted into another program" — and a UI that guessed
        # would write a dictation meant for a foreign window into whatever
        # Jarvis field last had focus.
        resolved_target = target
        if target not in ("insert", "chat"):
            try:
                from dodaios.dictation.insert import resolve_target

                resolved_target = resolve_target(target)
            except Exception:  # noqa: BLE001 — an unreadable foreground is not fatal
                log.debug("dictation target resolution failed", exc_info=True)
                resolved_target = "insert"

        formatting_ms = round((time.perf_counter() - finish_started) * 1000.0)
        notification_ms = 0
        insertion_ms = 0
        final_notification_status = "complete"
        insert_result = None

        async def notify_final() -> None:
            nonlocal notification_ms, final_notification_status
            started = time.perf_counter()
            try:
                complete = await self._publish_dictation_event(
                    DictationTranscript(
                        source_layer="speech.dictation",
                        text=cleaned,
                        is_final=True,
                        target=resolved_target,
                    )
                )
                if not complete:
                    final_notification_status = "observer_timeout"
            except Exception:
                final_notification_status = "failed"
                log.warning("dictation final publish failed", exc_info=True)
            finally:
                notification_ms = round((time.perf_counter() - started) * 1000.0)

        async def insert_external() -> None:
            nonlocal insert_result, insertion_ms
            started = time.perf_counter()
            try:
                insert_result = await asyncio.to_thread(self._insert_dictation, cleaned)
            except Exception:
                log.warning("dictation insertion failed", exc_info=True)
            finally:
                insertion_ms = round((time.perf_counter() - started) * 1000.0)

        # Healthy UI clients receive the final text even if OS insertion fails.
        # An external paste starts alongside notification: its destination must
        # not drift while an unrelated UI observer is holding up the bus.
        try:
            if resolved_target == "insert" and cleaned.strip() and not hung_up:
                await asyncio.gather(notify_final(), insert_external())
            else:
                await notify_final()
        except Exception as exc:  # noqa: BLE001
            log.warning("dictation final delivery failed: %s", exc)

        outcome_name = "chat"
        detail = ""
        method = ""
        if hung_up:
            outcome_name = "cancelled"
        elif not cleaned.strip():
            # Nothing to deliver. WHY there is nothing is the whole point of
            # this branch: a provider error is a "failed" the user can act on
            # (fix the key, switch provider), silence is just an "empty".
            outcome_name = "failed" if stt_error else "empty"
            if stt_error:
                # ``detail`` is the sentence surfaces without a locale of their
                # own show verbatim (the Jarvis Bar, the CLI) — and until now a
                # failed dictation left it empty, so the bar said nothing at all
                # about why the words never arrived. The localized half is the
                # reason CODE on ``error``, which the UI translates.
                detail = stt_failure_message(stt_error)
                # Every provider failed and the words exist only as audio now.
                # That audio is kept for exactly this case (``failed`` is a
                # recoverable outcome), so the notice says where to get the
                # words back — the 2026-10-20 lost dictation told the user only
                # that the service "could not be reached". Promised only when
                # the sidecar will really be written: history on, the user's
                # keep switch on, and audio captured.
                if (
                    audio
                    and bool(getattr(cfg, "history_enabled", True))
                    and bool(getattr(cfg, "keep_failed_audio", True))
                ):
                    detail += (
                        " The audio was kept — use Restore in the dictation "
                        "history to try again."
                    )
            elif rejected_detail:
                # Nothing arrived because what arrived was not speech. Saying so
                # is the difference between "your microphone heard nothing" and
                # an unexplained empty result after the user clearly spoke.
                detail = rejected_detail
        elif resolved_target == "insert":
            if insert_result is None:
                outcome_name = "failed"
                detail = "The text could not be inserted."
                if bool(getattr(cfg, "history_enabled", True)):
                    detail += " It is available in dictation history."
            else:
                outcome_name = insert_result.status
                detail = insert_result.detail
                method = insert_result.method

        # A dictation that delivered SOME words and permanently lost others is
        # not a success, whichever way the surviving fragment was delivered.
        # This is the maintainer's original complaint: 37.7 s of speech, a 429
        # from the provider, three words in the field, outcome ``inserted`` —
        # and because a success is not recoverable, the audio was deleted and
        # the history offered no Restore. Unrecoverable by construction.
        #
        # It is keyed on the LOSS, never on ``stt_error``: a failure on the last
        # probe tick whose tail then fell under the minimum segment size leaves
        # a stale error on a complete transcript, and degrading that would be
        # the same lie told backwards. ``hung_up`` still wins — the user
        # cancelled, and every unread second after that is their decision, not a
        # fault. An empty result stays ``failed``/``empty``: there is no
        # "partial" of nothing.
        if lost_audio_s > 0 and not hung_up and cleaned.strip():
            outcome_name = "partial"
            # Only promise Restore when the recording is actually being kept.
            # ``[dictation].keep_failed_audio`` is the user's switch, and a
            # message pointing at a button that will not be there is a worse
            # answer than the plain statement of what was lost.
            lost_note = (
                f"About {lost_audio_s:.1f}s of the recording could not be "
                "transcribed, so words are missing."
            )
            if bool(getattr(cfg, "keep_failed_audio", True)):
                lost_note += (
                    " The audio was kept — use Restore in the dictation "
                    "history to try again."
                )
            why = stt_failure_message(stt_error) if stt_error else ""
            # ``detail`` is the sentence locale-less surfaces (the Jarvis Bar,
            # the CLI) show verbatim, so the delivery detail is kept rather than
            # replaced: "words are missing" and "it went to the clipboard" are
            # both true and the user needs both. The localized half stays the
            # reason CODE on ``error``, which the UI translates.
            detail = " ".join(part for part in (lost_note, why, detail) if part)
            log.warning(
                "dictation degraded to partial: %.1fs of audio never "
                "transcribed (%s); the recording is kept for Restore.",
                lost_audio_s,
                stt_error or "unknown",
            )

        # The other hole, and the one nothing used to mention: frames the
        # CAPTURE dropped. When the event loop stalls longer than the mic
        # queue holds, ``_safe_put`` deletes the oldest frame per arrival and
        # that speech never becomes audio anyone can read — measured across 797
        # live dictations at 56 % of them losing something and one losing 7.4 s
        # out of 15.4 s, every one of them delivered as a clean success.
        #
        # Said FIRST when both holes are present: this is the unrecoverable
        # one. It also deliberately does not mention Restore — the audio it
        # would re-read is the audio that was never recorded.
        if (
            dropped_audio_s >= _DICTATION_DROPPED_AUDIO_NOTICE_S
            and not hung_up
            and cleaned.strip()
        ):
            outcome_name = "partial"
            detail = " ".join(
                part
                for part in (
                    f"About {dropped_audio_s:.1f}s of audio was lost while "
                    "recording, so words are missing.",
                    detail,
                )
                if part
            )
            log.warning(
                "dictation degraded to partial: %.1fs of audio never reached "
                "the recording (capture queue overflow) — not recoverable.",
                dropped_audio_s,
            )

        delivery_audit = (
            *stt_audit,
            f"formatting_wait_ms:{formatting_ms}",
            f"final_notification_wait_ms:{notification_ms}",
            f"insertion_wait_ms:{insertion_ms}",
            f"finish_wait_ms:{round((time.perf_counter() - finish_started) * 1000.0)}",
            f"final_notification:{final_notification_status}",
        )

        # Mark the turn closed BEFORE the publish attempt: this flag answers
        # "does the teardown still owe a terminal event", and a publish that
        # raised is not a reason to fire a second, contradictory completion.
        self._dictation_completion_published = True
        try:
            await self._publish_dictation_event(
                DictationCompleted(
                    source_layer="speech.dictation",
                    text=cleaned,
                    raw_text=raw_text,
                    outcome=outcome_name,
                    detail=detail,
                    method=method,
                    language=effective_language,
                    duration_s=duration_s,
                    removed_words=removed_words,
                    error=stt_error,
                    polish_status=polish_status,
                    polish_provider=polish_provider,
                    polish_latency_ms=polish_latency_ms,
                    stt_providers=stt_providers,
                    stt_models=stt_models,
                    detected_languages=detected_languages,
                    stt_latency_ms=max(0, int(stt_latency_ms)),
                    stt_calls=max(0, int(stt_calls)),
                    stt_errors=stt_errors,
                    stt_audit=delivery_audit,
                    audio_sample_rate_hz=max(0, int(audio_sample_rate_hz)),
                    audio_rms=max(0.0, float(audio_rms)),
                    audio_clipping_ratio=max(0.0, float(audio_clipping_ratio)),
                    audio_dropouts=max(0, int(audio_dropouts)),
                    audio_dropout_ms=max(0, int(audio_dropout_ms)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("dictation completion publish failed: %s", exc)

        await self._record_dictation(
            raw_text=raw_text,
            cleaned=cleaned,
            language=effective_language,
            duration_s=duration_s,
            outcome_name=outcome_name,
            method=method,
            removed_words=removed_words,
            cleanup_reason=cleanup_reason,
            stt_error=stt_error,
            audio=audio,
            polish_status=polish_status,
            polish_provider=polish_provider,
            polish_latency_ms=polish_latency_ms,
            stt_providers=stt_providers,
            stt_models=stt_models,
            detected_languages=detected_languages,
            stt_latency_ms=max(0, int(stt_latency_ms)),
            stt_calls=max(0, int(stt_calls)),
            stt_errors=stt_errors,
            stt_audit=delivery_audit,
            audio_sample_rate_hz=max(0, int(audio_sample_rate_hz)),
            audio_rms=max(0.0, float(audio_rms)),
            audio_clipping_ratio=max(0.0, float(audio_clipping_ratio)),
            audio_dropouts=max(0, int(audio_dropouts)),
            audio_dropout_ms=max(0, int(audio_dropout_ms)),
        )
        return cleaned

    async def _record_dictation(
        self,
        *,
        raw_text: str,
        cleaned: str,
        language: str,
        duration_s: float,
        outcome_name: str,
        method: str,
        removed_words: int,
        cleanup_reason: str,
        stt_error: str | None,
        audio: bytes | None,
        polish_status: str = "",
        polish_provider: str = "",
        polish_latency_ms: int = 0,
        stt_providers: tuple[str, ...] = (),
        stt_models: tuple[str, ...] = (),
        detected_languages: tuple[str, ...] = (),
        stt_latency_ms: int = 0,
        stt_calls: int = 0,
        stt_errors: tuple[str, ...] = (),
        stt_audit: tuple[str, ...] = (),
        audio_sample_rate_hz: int = 0,
        audio_rms: float = 0.0,
        audio_clipping_ratio: float = 0.0,
        audio_dropouts: int = 0,
        audio_dropout_ms: int = 0,
    ) -> None:
        """Write the history row and, when warranted, the audio sidecar.

        Split out of ``_finish_dictation`` because it is the only part that
        touches the disk: the caller has already published everything the UI
        needs, so nothing in here is allowed to change what the user sees. All
        of it is best-effort — a failed history write costs the history entry
        and nothing else.

        The ``polish_*`` values are offered to the store and dropped when it
        does not want them yet — see the ``TypeError`` branch below. A history
        row is worth more than the three fields describing how it was formatted.
        """
        from dodaios.dictation.outcomes import is_recoverable

        cfg = getattr(self, "_dictation_cfg", None)
        # A dictation that produced nothing is recorded too when its outcome
        # says the user LOST something (partial / failed / cancelled / empty):
        # that row is the only place a later Restore can start from.
        if not (raw_text or is_recoverable(outcome_name)):
            return
        if getattr(self, "_dictation_leave_no_trace", False) and outcome_name == "cancelled":
            # The early start of a hold key that turned out to be a shortcut
            # (``_on_dictate_abandon``): nobody dictated, nothing was lost.
            return
        if not getattr(cfg, "history_enabled", True):
            return

        entry = None
        history = None
        try:
            from dodaios.dictation.history import DictationHistory

            history = DictationHistory()
            fields: dict[str, Any] = dict(
                raw_text=raw_text,
                text=cleaned,
                language=language,
                duration_s=duration_s,
                outcome=outcome_name,
                method=method,
                removed_words=removed_words,
                cleanup_reason=cleanup_reason,
                error=stt_error,
                max_entries=int(getattr(cfg, "history_max_entries", 200)),
                retention_days=int(getattr(cfg, "history_retention_days", 30)),
            )
            extra = {
                "polish_status": polish_status,
                "polish_provider": polish_provider,
                "polish_latency_ms": polish_latency_ms,
                "stt_providers": stt_providers,
                "stt_models": stt_models,
                "detected_languages": detected_languages,
                "stt_latency_ms": max(0, int(stt_latency_ms)),
                "stt_calls": max(0, int(stt_calls)),
                "stt_errors": stt_errors,
                "stt_audit": stt_audit,
                "audio_sample_rate_hz": max(0, int(audio_sample_rate_hz)),
                "audio_rms": max(0.0, float(audio_rms)),
                "audio_clipping_ratio": max(0.0, float(audio_clipping_ratio)),
                "audio_dropouts": max(0, int(audio_dropouts)),
                "audio_dropout_ms": max(0, int(audio_dropout_ms)),
            }
            try:
                entry = await asyncio.to_thread(history.add, **fields, **extra)
            except TypeError:
                # The store predates these fields. Writing the row WITHOUT them
                # is the right degradation: the user's words are the payload,
                # and "how it was formatted" is metadata about the payload. The
                # alternative — letting the TypeError fall into the handler
                # below — silently drops the whole dictation from the history,
                # which is a far worse answer to a version skew.
                log.debug(
                    "dictation history does not carry the polish fields yet; "
                    "storing the row without them."
                )
                entry = await asyncio.to_thread(history.add, **fields)
        except Exception:  # noqa: BLE001 — history is never worth a failure
            log.debug("dictation history write failed", exc_info=True)
            return

        # Audio is the most sensitive thing this application ever stores, so it
        # is written on exactly one path: the user allowed it AND the dictation
        # left them missing words (``RECOVERABLE_OUTCOMES``). Never on a plain
        # success — but ``partial`` is in that set precisely because the words
        # it did deliver are not the ones it lost.
        if (
            entry is None
            or history is None
            or not audio
            or not bool(getattr(cfg, "keep_failed_audio", True))
            or not is_recoverable(outcome_name)
        ):
            return
        try:
            from dodaios.dictation.audio import prune_audio, save_dictation_audio

            path = await asyncio.to_thread(
                save_dictation_audio, entry.id, audio, directory=history.audio_dir
            )
            if path is not None:
                await asyncio.to_thread(
                    history.update, entry.id, audio_path=str(path)
                )
            # Retention runs after the write, off the delivery path: the
            # transcript is already in front of the user by now.
            await asyncio.to_thread(
                prune_audio,
                max_files=int(getattr(cfg, "audio_max_files", 20)),
                retention_days=int(getattr(cfg, "audio_retention_days", 7)),
                directory=history.audio_dir,
            )
        except Exception:  # noqa: BLE001 — a lost recovery option, not a lost dictation
            log.debug("dictation audio sidecar failed", exc_info=True)

    def _insert_dictation(self, text: str):
        """Blocking insertion, run off the event loop. Never raises.

        ``insert_text`` sleeps around the paste chord and talks to the OS
        clipboard, so it must not run on the pipeline's loop — a 250 ms block
        there is a stutter in the voice path.
        """
        from dodaios.dictation.insert import InsertResult, insert_text

        cfg = getattr(self, "_dictation_cfg", None)
        try:
            return insert_text(
                text,
                method=str(getattr(cfg, "insert_method", "clipboard")),
                paste_chord=str(getattr(cfg, "paste_chord", "auto")),
                delay_ms=int(getattr(cfg, "paste_delay_ms", 120)),
                delay_after_ms=int(getattr(cfg, "paste_delay_after_ms", 120)),
                restore_clipboard=bool(getattr(cfg, "restore_clipboard", True)),
            )
        except Exception as exc:  # noqa: BLE001 — degrade to an honest report
            log.warning("dictation insertion failed: %s", exc, exc_info=True)
            return InsertResult(
                status="unavailable",
                detail=(
                    "The text could not be inserted here. It is kept in the "
                    "dictation history."
                ),
                clipboard_holds_text=False,
            )

    async def _session_input_stream(
        self, chunks: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[AudioChunk]:
        """Filter mic frames captured during/after Jarvis TTS output."""
        dropped = 0
        async for chunk in chunks:
            # Input mute (Jarvis-scoped): while muted, drop the user's audio at
            # OUR input boundary so Jarvis stops hearing them mid-session —
            # without touching the OS microphone, so every other app keeps the
            # mic. The mute flag already gated wake activation + TTS output; this
            # closes the active-session input gap ("ich rede, aber er hoert mich
            # trotzdem", 2026-06-28).  # i18n-allow
            if getattr(self, "_muted", False):
                continue
            if self._should_drop_session_input(chunk):
                dropped += 1
                continue
            if dropped:
                log.info("TTS echo guard: dropped %d mic chunk(s).", dropped)
                dropped = 0
            # Realtime sessions bypass the VAD, where mic_level.feed normally
            # lives, so feed the live loudness here — after the mute and echo
            # filters, so suppressed audio honestly shows dark bars. Same
            # normalized RMS as the VAD/PTT sites; zero-cost without overlay.
            if mic_level.has_subscribers():
                samples = pcm_bytes_to_np(chunk.pcm)
                if samples.size:
                    mic_level.feed(float(np.sqrt(np.mean(np.square(samples)))))
            yield chunk

    def _should_drop_session_input(self, chunk: AudioChunk) -> bool:
        until_ns = getattr(self, "_input_suppressed_until_ns", 0)
        if until_ns <= 0:
            return False
        chunk_ts = getattr(chunk, "timestamp_ns", 0) or time.time_ns()
        if chunk_ts < until_ns:
            return True
        self._input_suppressed_until_ns = 0
        return False

    def _suppress_session_input_after_tts(self, reason: str) -> None:
        seconds = max(0.0, float(getattr(self, "_post_tts_listen_suppression_s", 0.0)))
        if seconds <= 0.0:
            return
        until_ns = time.time_ns() + int(seconds * 1_000_000_000)
        previous = getattr(self, "_input_suppressed_until_ns", 0)
        self._input_suppressed_until_ns = max(previous, until_ns)
        log.info("TTS echo lock armed: %.1fs (%s).", seconds, reason)

    # --- Self-echo TEXT guard (BUG-084) --------------------------------- #
    # The logic lives in dodaios.speech.echo_guard.SelfEchoGuard so the
    # realtime session shares ONE implementation (BUG-089) instead of a
    # drifting copy; these thin delegates keep the pipeline's historical
    # call sites and test surface unchanged.

    def _echo_text_guard(self) -> SelfEchoGuard:
        guard = getattr(self, "_self_echo_guard", None)
        if guard is None:
            guard = SelfEchoGuard()
            self._self_echo_guard = guard
        return guard

    def _register_assistant_speech(self, text: str) -> None:
        """Remember what Jarvis is about to voice as an echo-guard reference."""

        self._echo_text_guard().register(text)

    def _touch_assistant_speech_activity(self) -> None:
        """Stamp 'assistant audio was active around now' for the echo guard."""

        self._echo_text_guard().touch()

    async def _on_audio_out_first(self, event: AudioOutFirst) -> None:
        """Mark perceived time-to-first-audio once per turn (ack or brain)."""
        tracker = self._latency_tracker
        if tracker is not None and not self._latency_first_audio_marked:
            self._latency_first_audio_marked = True
            tracker.mark(LatencyPhase.TURN_TO_FIRST_AUDIO)

    def _ensure_voice_stt_warmup(self) -> asyncio.Task[None] | None:
        """The running warm-up of a cold local voice engine, started if needed.

        ``_warmup_deferred_loaders`` only warms ``self._stt`` (the wake engine),
        and on a Vosk-wake install the utterance provider is a separate object
        nothing ever primed — its first build then landed inside the first
        spoken turn's 8 s budget (measured on an RTX 4060: 10.6 s build + 2.4 s
        first decode standalone, ~25 s inside the app, then 0.5 s per decode).
        Returns ``None`` when there is nothing to wait for, including every
        cloud provider, which has no ``warm_up``.
        """
        provider = getattr(self, "_utterance_stt", None)
        warm_up = getattr(provider, "warm_up", None)
        if not callable(warm_up) or getattr(provider, "is_warm", True) is not False:
            return None
        task = getattr(self, "_voice_stt_warmup_task", None)
        if (
            task is not None
            and not task.done()
            and getattr(self, "_voice_stt_warmup_provider", None) is provider
        ):
            return task
        if getattr(self, "_dictation_warmup_shutdown", False):
            return None

        def _log_failure(done: asyncio.Task[None]) -> None:
            if not done.cancelled() and done.exception() is not None:
                log.warning("Voice STT warm-up failed: %s", done.exception())

        task = asyncio.create_task(
            asyncio.to_thread(warm_up), name="voice-stt-warmup"
        )
        task.add_done_callback(_log_failure)
        self._voice_stt_warmup_task = task
        self._voice_stt_warmup_provider = provider
        return task

    def _speech_trace(self) -> str:
        """The turn a metered speech call belongs to, or "" between turns."""
        tracker = getattr(self, "_latency_tracker", None)
        return str(getattr(tracker, "trace_id", "") or "")

    # --- Completion timeout helpers (zero-silent-drop fallback) ------------ #

        # No TTS, no state ping-pong, no interruption.

    # --- Clarifying-question timer (Zwischenfrage; AD-OE6 for the hold) ----- #

    # --- Continuation drain timer (autonomous flush; AD-OE6 zero-silent-drop) - #

    async def _notify_voice_unavailable(self, phrase: str, *, spoken: bool) -> None:
        """Say (or, with a live capture microphone, show) why a call ended.

        ``phrase`` is the provider's refusal (dodaios.speech.provider_refusal),
        already in the call's language; empty means the generic line that no
        realtime provider is ready.
        """
        if spoken:
            await self._speak_realtime_unavailable(phrase or None)
            return
        lang = _phrase_lang(self._output_language(None, ""))
        await self._publish_event(
            MessageSent(
                source_layer="speech.pipeline",
                thread_id="voice",
                role="system",
                text=phrase or _REALTIME_UNAVAILABLE_PHRASE[lang],
            )
        )

    async def _speak_realtime_unavailable(self, phrase: str | None = None) -> None:
        """Speak why the realtime call could not start or went on.

        ``phrase`` replaces the generic line with the provider's actual
        refusal (dodaios.speech.provider_refusal), already in the call's
        language.
        """
        lang = _phrase_lang(self._output_language(None, ""))
        phrase = phrase or _REALTIME_UNAVAILABLE_PHRASE[lang]
        try:
            await self._set_turn_state(TurnTakingState.JARVIS_SPEAKING)
            await self._speak(
                phrase,
                language=lang,
                kind=SPOKEN_KIND_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001 — fallback must never block recovery
            log.warning("Realtime-unavailable fallback speak failed: %s", exc)

    def _abort_playback_device(self) -> None:
        """Unblock + tear down the live output stream after a playback stall."""
        player = getattr(self, "_player", None)
        if player is None:
            return
        if hasattr(player, "abort_active"):
            player.abort_active()
        else:  # older player without the Wave-1 hook
            player.stop()

    async def _await_playback(
        self,
        play_task: asyncio.Task[Any],
        extra_tasks: set[asyncio.Task[Any]],
    ) -> set[asyncio.Task[Any]]:
        """Wait for a TTS playback task, aborting a wedged device fast.

        The dominant 60-156 s voice-hang root cause was a wedged output device:
        PortAudio's blocking ``stream.write`` got stuck in its ``to_thread``
        worker (which Python cannot cancel), so ``play_task`` never completed and
        the only escape was a 120 s ceiling. This poll loop watches the player's
        write-progress (``last_write_ns``): a mid-playback gap of
        ``_speak_playback_stall_s`` means the device is wedged → we call
        ``player.abort_active()`` (Pa_AbortStream) to unblock the write so the
        turn unwinds in ~5 s and the session re-arms. A ``_speak_playback_
        ceiling_s`` absolute backstop covers anything the progress signal misses.

        Returns the set of completed tasks, or an EMPTY set when it aborted on a
        stall/ceiling (the device has already been torn down + the event logged).
        Cross-platform: pure asyncio + PortAudio abort.
        """
        ceiling = getattr(self, "_speak_playback_ceiling_s", _TTS_PLAYBACK_CEILING_S)
        stall_s = getattr(self, "_speak_playback_stall_s", _TTS_PLAYBACK_STALL_S)
        watch = {play_task, *extra_tasks}
        start = time.monotonic()
        while True:
            done, _pending = await asyncio.wait(
                watch, timeout=0.25, return_when=asyncio.FIRST_COMPLETED
            )
            if done:
                return done
            player = getattr(self, "_player", None)
            last_write = getattr(player, "last_write_ns", 0) if player is not None else 0
            owner_missing = object()
            owner_task_id = (
                getattr(player, "last_write_owner_task_id", owner_missing)
                if player is not None
                else owner_missing
            )
            if owner_task_id is not owner_missing and owner_task_id != id(play_task):
                last_write = 0
            if last_write <= 0:
                # No first frame yet: the synthesize / first-frame window. A slow
                # TTS provider must NOT be misread as a device wedge — that false
                # abort (on every turn whose brain/synthesize took > stall_s) was
                # the "Jarvis listens forever / answer never heard" root cause.
                # Only a generous no-first-frame backstop applies here; it covers
                # a provider that never yields any audio at all.
                #
                # The turn is actively WORKING whenever EITHER heartbeat landed
                # AFTER this await began — in both cases the brain simply has not
                # started narrating yet, so there is legitimately nothing to play.
                # Re-arm the window from the LATER heartbeat so the ceiling bounds
                # silence since the LAST sign of life, never total work time.
                #   • ``_long_tool_last_activity`` — a computer_use step
                #     (ObservationCaptured/ActionPlanned → _on_agent_progress).
                #     Live bug 2026-06-09 ("öffne CapCut"): the CU loop was
                #     beheaded on step 4 at 20 s and the turn came back empty/mute.
                #   • ``_brain_last_progress`` — the brain's own round/token
                #     heartbeat (_mark_brain_progress, pinged on every tool-use-
                #     loop round AND every streamed token; the SAME signal the
                #     brain stall guard trusts). Live bug 2026-06-14 14:21 + 14:24
                #     (a weather question): a NON-desktop tool loop (geocode +
                #     DuckDuckGo + open-meteo, ~20 s of real work) emits no CU
                #     step, so before this the 20 s ceiling beheaded the working
                #     turn and the user heard "that took too long" + a hang-up.
                #   • ``_brain_thinking_heartbeat`` — the PRE-first-token think
                #     pulse from _run_brain_with_stall_guard. Live bug 2026-06-14
                #     16:17 (a trip-research turn): the deep brain built an
                #     18k-token cache then thought silently with no on_progress
                #     and no token, so the two heartbeats above never moved and
                #     the 20 s ceiling beheaded a working brain.
                # Strictly-greater keeps a heartbeat from BEFORE this await out of
                # the decision — per-unit re-arm, the BUG-032 stale-counter
                # lesson; the brain stall guard applies the same suspension to its
                # absolute ceiling. Once the brain finishes producing text both
                # heartbeats freeze, so a genuinely wedged TTS provider (text fed,
                # no audio) is still aborted ``ceiling`` s after the last progress.
                heartbeat = max(
                    getattr(self, "_long_tool_last_activity", 0.0),
                    getattr(self, "_brain_last_progress", 0.0),
                    getattr(self, "_brain_thinking_heartbeat", 0.0),
                )
                if heartbeat > start:
                    start = heartbeat
                if (time.monotonic() - start) >= ceiling:
                    log.warning(
                        "TTS produced no audio within %.0fs — aborting "
                        "(no first frame).", ceiling,
                    )
                    self._abort_playback_device()
                    return set()
                continue
            # Playback has started: only a genuine MID-playback gap (frames were
            # flowing, then froze) is a device wedge. An actively-progressing long
            # answer keeps last_write fresh and is never aborted — the old flat
            # total-time ceiling used to truncate any spoken turn over ~20 s.
            if _playback_progress_stalled(last_write, stall_s):
                log.warning(
                    "TTS playback stalled — no audio frames for %.1fs — aborting "
                    "device + unwinding turn (device-wedge recovery).", stall_s,
                )
                self._abort_playback_device()
                return set()

    def _resolve_realtime_surface_tts(self, provider: str) -> Any | None:
        """TTS for re-rendering a realtime turn locally (mode separation).

        STRICT separation (maintainer mandate 2026-07-17): resolves ONLY the
        active realtime provider's own TTS family, keyed through the realtime
        credential slots and speaking the session voice. The pipeline ``[tts]``
        instance is never a candidate — ``None`` means "keep the turn
        text-only". Cached per provider; never raises.
        """
        key = (provider or "").strip().lower()
        if not key:
            return None
        cached = getattr(self, "_realtime_surface_tts_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            from dodaios.plugins.tts import build_realtime_surface_tts

            built = build_realtime_surface_tts(self._config, key)
        except Exception:  # noqa: BLE001 — the emergency voice must never break the turn
            built = None
        if built is not None:
            # Every readback and announcement spoken DURING a realtime call
            # goes through this voice; on a realtime-first box that is nearly
            # all of the TTS spend, and it was the one voice nobody metered.
            built = meter_tts(
                built, getattr(self, "_speech_spend", None), trace_id=self._speech_trace
            )
        self._realtime_surface_tts_cache = (key, built)
        return built

    def _emit_spoken(
        self,
        text: str,
        language: str | None,
        kind: str,
        detail: str | None = None,
        tts: Any | None = None,
    ) -> None:
        """Publish one playback-confirmed phrase to the audible transcript.

        Callers own the playback receipt and invoke this only after audio was
        accepted. Normal replies and supplemental phrases share this event.
        Publishing remains fire-and-forget so the passive recorder cannot add
        latency to the voice path. Empty text and a missing bus are no-ops.
        """
        if not text or not text.strip():
            return
        bus = getattr(self, "_bus", None)
        if bus is None:
            return
        try:
            # Which voice actually spoke: every classic-path phrase renders
            # through self._tts, whose providers record their resolved voice
            # per utterance (last_voice protocol, 2026-07-17). Read after
            # playback so a fallback takeover reports the TAKEOVER voice.
            # A caller that rendered through a DIFFERENT instance (realtime
            # surface fallback) passes it in so the label stays honest.
            if tts is None:
                tts = getattr(self, "_tts", None)
            voice = getattr(tts, "last_voice", None)
            voice_provider = getattr(tts, "last_voice_provider", None) or getattr(
                tts, "name", None
            )
            event = SpeechSpoken(
                source_layer="speech.pipeline",
                text=text,
                language=(language or "en"),
                spoken_kind=kind,
                detail=(detail or None),
                voice=voice,
                voice_provider=voice_provider if voice else None,
            )
            asyncio.create_task(bus.publish(event))  # noqa: RUF006 — fire-and-forget
        except Exception:  # noqa: BLE001 — telemetry must never break the turn
            log.debug("SpeechSpoken emit failed", exc_info=True)

    def _playback_confirmed(self, result: object) -> bool:
        """Interpret a player receipt without breaking compatible older players.

        The built-in player returns an explicit boolean. Older compatible
        players returned ``None`` after successful consumption, so only those
        non-built-in implementations retain the legacy success interpretation.
        """
        if isinstance(self._player, AudioPlayer):
            return result is True
        return result is not False

    #: Spoken readback for a Jarvis-Agent background task that finished off the
    #: chat path. de/en/es/pt so the readback follows the conversation language
    #: instead of a hardcoded German literal (forensic 2026-06-23). German
    #: strings are TTS product surface, not source artifacts (i18n-allow).
    _BG_READBACK_PHRASES: dict[str, dict[str, str]] = {
        "de": {
            "done": "Fertig.",  # i18n-allow
            "done_summ": "Fertig. {s}",  # i18n-allow
            "fail": "Das hat nicht geklappt. {e}",  # i18n-allow
            "unknown_err": "unbekannter Fehler",  # i18n-allow
        },
        "en": {
            "done": "Done.",
            "done_summ": "Done. {s}",
            "fail": "That didn't work. {e}",
            "unknown_err": "unknown error",
        },
        "es": {
            "done": "Listo.",
            "done_summ": "Listo. {s}",
            "fail": "Eso no funcionó. {e}",
            "unknown_err": "error desconocido",
        },
        "pt": {
            "done": "Feito.",
            "done_summ": "Feito. {s}",
            "fail": "Isso não funcionou. {e}",
            "unknown_err": "erro desconhecido",
        },
    }

    _BCP47: dict[str, str] = {
        "de": "de-DE", "en": "en-US", "es": "es-ES", "pt": "pt-PT", "fr": "fr-FR",
    }

    @classmethod
    def _bcp47(cls, lang: object) -> str | None:
        """Map a de/en/es/pt turn-language code to a TTS BCP-47 locale, else None.

        Single source for the whole pipeline — replaces four hand-copied maps,
        one of which (the task-ack prerender) had silently dropped ``es``, so a
        Spanish turn there got no language pin and the multilingual TTS could
        code-switch.
        """
        return cls._BCP47.get(str(lang or "").lower())

    def _output_language(self, stt_language: object, text: str) -> str:
        """Resolve THIS turn's output language for EVERY spoken/written layer.

        Honors the live ``brain.reply_language`` pin (the desktop Languages
        view) so a user-selected language reaches the ack preamble, the canned
        status / clarify / timeout phrases and the TTS voice — not only the
        deep-brain reply (forensic 2026-06-18: a German utterance mis-heard as
        English text drove the whole chain English because the pipeline
        re-derived language from text/STT alone). ``auto``/unset mirrors the
        detected input language. Single source for the whole pipeline, per
        AGENTS.md "Runtime Output Language". The live pin lives on the
        BrainManager (hot-reloaded via ``set_reply_language``); the config is
        only consulted when the brain callback does not expose the pin (tests /
        mock brains).
        """
        brain = getattr(self, "_brain", None)
        pin = getattr(brain, "reply_language", None)
        if pin is None:
            cfg = getattr(self, "_config", None)
            pin = getattr(getattr(cfg, "brain", None), "reply_language", None)
        # French is a spoken pin without a translated phrase catalog. Canned
        # phrases still fall back to English; the TTS voice follows the pin.
        if str(pin or "").strip().lower() == "fr":
            return "fr"
        # Conversation stickiness: a thin interjection ("Now") inherits the
        # running conversation language instead of flipping ack/phrases/TTS
        # (forensic 2026-06-18). The brain owns the sticky conversation language.
        # An undetectable turn falls back to English (DEFAULT_LOCALE), never
        # the UI language: the interface language says nothing about the
        # language spoken (forensic 2026-10-19).
        conv = getattr(brain, "conversation_language", "")
        return resolve_output_language(
            pin, stt_language, text, conversation_language=conv,
            default=DEFAULT_LOCALE,
        )

    async def _speak(
        self, text: str, language: str | None = None, *, kind: str = "reply"
    ) -> bool:
        """Speak text aloud — with a barge-in monitor.

        `language` = "de"/"en" (Whisper code) is mapped to "de-DE"/"en-US"
        and passed to TTS (the voice stays the same — Gemini voices are
        language-agnostic).

        ``kind`` tags what is being voiced for the Transcription log. The
        default ``"reply"`` is the ordinary brain answer; canned phrases pass
        their specific kind. Both are published only after playback succeeds.

        ``_barge_monitor`` runs on a separate mic instance in parallel with
        playback. When Silero VAD detects user speech there (threshold 0.8,
        3 consecutive frames, 400 ms grace period), player playback stops
        immediately. Return value: ``True`` when barged in.

        When muted (mascot doubleClick), we short-circuit: no synthesize
        call, no playback. We return ``False`` (no barge-in occurred) so
        callers that branch on ``barged`` behave consistently.
        """
        if getattr(self, "_muted", False):
            # INFO, not debug: a muted drop makes the whole turn inaudible
            # while the transcript claims Jarvis spoke — forensics must see
            # the audible gap without a debug build (live 2026-07-21 17:45).
            log.info(
                "_speak suppressed — voice muted (kind=%s, %d chars stay "
                "text-only)",
                kind,
                len(text),
            )
            return False
        # Double-answer guard (live complaint 2026-06-30): once a timeout /
        # "couldn't finish" notice closed THIS utterance, an ordinary brain
        # ANSWER (kind="reply", the default) must NOT also be voiced — a stalled
        # tool that timed out and then re-answered for the same content. Gate
        # ONLY the brain answer: every canned notice (timeout / clarify / ack /
        # unavailable) and every background mission readback (completion /
        # subagent / announcement) carries its own kind and is intentionally
        # exempt, so a legitimately-spawned later result still speaks. The flag
        # re-arms at the next utterance finalize. Before ``_emit_spoken`` so a
        # suppressed answer — never actually voiced — is not logged.
        if kind == "reply" and getattr(self, "_brain_timeout_spoken_this_turn", False):
            log.info(
                "Brain answer suppressed — a timeout notice already closed this "
                "turn (no double-answer)."
            )
            return False
        lang_code = self._bcp47(language)
        # Echo-guard reference (BUG-084): whatever we voice may come back
        # through the mic as speaker echo.
        self._register_assistant_speech(text)
        try:
            chunks = self._tts.synthesize(text, language_code=lang_code)
        except TypeError:
            chunks = self._tts.synthesize(text)

        play_task = asyncio.create_task(self._player.play_chunks(chunks), name="tts-play")
        barge_task = asyncio.create_task(self._barge_monitor(), name="barge-monitor")
        # Hangup is the hard kill-switch ("auflegen"): a hangup mid-phrase must
        # abort _speak at once. Without watching the event here, a stalled
        # output device — or a hangup fired during a fallback phrase
        # (_speak_brain_unavailable / _speak_brain_timeout) — keeps ``play_task``
        # pending until the no-first-frame ceiling, so ``_speak`` never returns and the
        # voice session wedges in JARVIS_SPEAKING (same root cause as
        # _brain_streaming; live bug 2026-06-01). Treat it like a barge-in.
        # getattr-fallback: test fixtures build the pipeline via ``__new__``
        # and don't set ``_hangup_event`` — a fresh never-set Event keeps the
        # behaviour identical to pre-fix (the waiter simply never fires).
        hangup_event = getattr(self, "_hangup_event", None) or asyncio.Event()
        hangup_task = asyncio.create_task(
            hangup_event.wait(), name="hangup-during-speak"
        )
        barged = False
        # A stalled output device (blocking ``stream.write``) or a stalled TTS
        # stream can wedge ``play_chunks``. The watchdog aborts a wedged device
        # in ~5 s (vs the old 120 s ceiling) so ``_speak`` always returns and the
        # voice session can never freeze with ``self._state`` stuck at ACTIVE
        # (the wake loop only re-arms in IDLE).
        try:
            done = await self._await_playback(play_task, {barge_task, hangup_task})
            if not done:
                # Watchdog already aborted the wedged device + logged the reason.
                pass
            elif hangup_task in done and not hangup_task.cancelled():
                log.info("📵 Hangup during TTS — aborting turn")
                self._player.stop()
                barged = True
            else:
                if barge_task in done and not barge_task.cancelled():
                    if barge_task.result():
                        log.info("🛑 Barge-in — stoppe TTS-Playback")
                        self._player.stop()
                        barged = True
                if (
                    barge_task in done
                    and not barge_task.cancelled()
                    and not barged
                    and not play_task.done()
                ):
                    # Barge monitor returned without barging (mic ended/error)
                    # but playback is still running — wait it out under the same
                    # device-wedge watchdog, still abortable by a hangup.
                    tail_done = await self._await_playback(play_task, {hangup_task})
                    if play_task not in tail_done:
                        if hangup_task in tail_done:
                            log.info("📵 Hangup during TTS — aborting turn")
                            barged = True
                        # else: watchdog already aborted the wedged device + logged.
                        self._player.stop()
        except Exception as exc:  # noqa: BLE001
            log.exception("Playback failure: %s", exc)
        finally:
            for t in (play_task, barge_task, hangup_task):
                if not t.done():
                    t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: S110
                    # Owned playback tasks were explicitly cancelled above.
                    pass
        if (
            play_task.done()
            and not play_task.cancelled()
            and play_task.exception() is None
            and self._playback_confirmed(play_task.result())
        ):
            self._emit_spoken(text, language, kind)
        # Echo-guard activity stamp (BUG-084) — unconditional: after a FALSE
        # barge (our own echo confirmed as "user speech") there is no post-TTS
        # suppression at all, so the text guard is the only thing standing
        # between the echo tail and a brain turn.
        self._touch_assistant_speech_activity()
        if not barged:
            self._suppress_session_input_after_tts("response")
        return barged

    async def _barge_monitor(
        self, *, grace_s: float | None = None, respect_input_suppression: bool = False
    ) -> bool:
        """Listen on a second mic instance for the user speaking over Jarvis'
        TTS output. Returns ``True`` as soon as that is confirmed.

        History: barge-in used to fire almost immediately after TTS start
        (~600 ms) and truncated the answer — speaker→mic echo (user feedback
        2026-04-22). The conservative policy (1.5 s grace, Silero 0.97, 12
        consecutive frames ≈ 380 ms) fixed headphone leakage but NOT open
        laptop speakers next to a built-in mic: there the assistant's own
        voice is loud, sustained, and perfectly speech-shaped, so Silero —
        which cannot tell whose voice it hears — confirmed a "barge" against
        the assistant itself. That false confirm truncated the audible answer
        AND (because a barge keeps the session listening with no post-TTS
        suppression) let the echo tail become the next "user" turn: the
        BUG-084 self-talk loop on the Mac test machine.

        This monitor therefore reuses the shared
        ``DesktopRealtimeBargeInDetector`` (the BUG-062 realtime fix) instead
        of a bare Silero loop, gaining its two defenses:

        - the static RMS energy pre-gate (quiet frames never reach ONNX), and
        - the BUG-084 adaptive echo floor, calibrated per answer from the
          grace-window frames — which during playback ARE our own echo.

        Every ``feed`` runs in a worker thread: the per-frame ONNX inference
        used to run synchronously on the voice event loop and starved the
        ~120 ms playback write batches on slow CPUs (BUG-062 cause #2 —
        constant stutter / multi-second pauses on the Intel-Mac test machine).
        """
        from dodaios.realtime.desktop import DesktopRealtimeBargeInDetector
        from dodaios.speech.barge_in import profile_for

        # ONE policy for both voice paths ([voice] barge_in; issue #153). The
        # caller's explicit grace stays for the thinking-interrupt monitor;
        # the default grace is the profile's.
        profile = profile_for(getattr(self, "_config", None))
        if not profile.enabled:
            # The person chose to let the assistant finish. Nothing to listen
            # for; the playback waiter continues on its own.
            return False
        detector = DesktopRealtimeBargeInDetector(
            output_active=level_tap.playback_active,
            **profile.detector_kwargs(grace_s=grace_s),
        )
        try:
            # Model load off the event loop — it shares the turn with live
            # audio playback.
            await asyncio.to_thread(detector.warmup)
        except asyncio.CancelledError:
            return False
        detector.start_output()

        try:
            async with MicrophoneCapture(
                device=self._input_device,
                max_queue_chunks=REALTIME_QUEUE_CHUNKS,
                device_priority=self._input_priority,
            ) as mic:
                async for chunk in mic.stream():
                    # Honour the global mute (orb double-click → _muted=True):
                    # while muted the user has told us to stop listening, so a
                    # barge must never fire on this second mic — mirrors
                    # _activation_allowed / _speak, which both short-circuit on
                    # _muted. Without this the thinking-interrupt monitor aborted a
                    # muted-but-still-working turn (live bug 2026-07-01).
                    if getattr(self, "_muted", False):
                        continue
                    # Echo-suppression (spec §4.2): while our own ACK/preamble
                    # audio is still within the post-TTS suppression window, skip
                    # detection so the thinking-interrupt monitor never mistakes
                    # the preamble's speaker->mic leakage for the user speaking.
                    # Pure read (no mutation) to avoid racing the session-input
                    # dropper that shares _input_suppressed_until_ns.
                    if respect_input_suppression:
                        until_ns = getattr(self, "_input_suppressed_until_ns", 0)
                        chunk_ts = getattr(chunk, "timestamp_ns", 0) or time.time_ns()
                        if until_ns > 0 and chunk_ts < until_ns:
                            continue
                    if await asyncio.to_thread(detector.feed, chunk.pcm) is not None:
                        return True
        except asyncio.CancelledError:
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("Barge-in monitor error: %s", exc)
        return False


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
