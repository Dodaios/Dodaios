"""One phone call, held by a realtime speech-to-speech session.

A Twilio Media Streams socket carries the caller's audio as 8 kHz mu-law in
``media`` events and plays back the mu-law we send on the same socket. A
:class:`PhoneCall` sits between that socket and one realtime voice session
(``dodaios.realtime.factory.build_realtime_session`` with ``surface="phone"``):

    Twilio media (mu-law 8 kHz, base64)
      -> PCM16 8 kHz -> session.handle_audio_frame   (the session resamples)
    session send_binary (PCM16 at the provider's output rate)
      -> resample to 8 kHz -> master volume -> mu-law -> Twilio media + mark

The session owns the conversation: listening, turn taking, tools, barge-in
and the voice hang-up. This class owns only the phone line: the transcode,
flushing Twilio's playback on a barge-in, the call's brief and opening line,
the time cap, the one-decision calls (``decision_calls``) and the call
record. There is no speech-to-text, brain or text-to-speech of its own: when
the session cannot start, the call ends and says why in the log and the call
status.

The transport is injected (``send`` ships one Twilio message, ``hang_up``
closes the socket, ``build_session`` builds the realtime session), so the
class is testable with fakes and no real socket, provider or key.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.i18n import catalog as i18n_catalog
from dodaios.sessions.constants import HANGUP_CLIENT_STOP, HANGUP_ERROR

from . import decision_calls
from .audio import TWILIO_SAMPLE_RATE, Resampler, pcm16_to_ulaw, ulaw_to_pcm16
from .constants import CALL_COMPLETED, CALL_FAILED, CALL_IN_PROGRESS, CALL_NO_AUDIO

log = logging.getLogger("dodaios.telephony.call")

#: Ships one JSON-serialisable message to Twilio over the media socket.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]
#: Closes the media socket, which ends a ``<Connect><Stream>`` call.
HangUpFn = Callable[[], Awaitable[None]]
#: ``build_session(send_binary=..., send_json=..., call_brief=...)`` -> session or None.
BuildSessionFn = Callable[..., Any]

# Default greeting when TwilioConfig.greeting is empty: name-free, or with the
# assistant's own resolved name when one is set (dodaios/brain/assistant_name.py).
_DEFAULT_GREETINGS: dict[str, str] = i18n_catalog.table("telephony.default_greetings")
_NAMED_GREETINGS: dict[str, str] = i18n_catalog.table("telephony.named_greetings")

#: Fallback output rate until the session's ``audio_ready`` names its own.
_DEFAULT_OUTPUT_RATE = 24_000
#: How long one inbound frame may take to reach the session.
_AUDIO_SEND_TIMEOUT_S = 2.0
#: A trusted line (opening, decision reply) is refused while the model is busy;
#: it is offered again at this pace, this many times.
_LINE_RETRY_S = 0.5
_LINE_ATTEMPTS = 30
#: How long the call waits for a decision reply to finish playing before it
#: hangs up anyway.
_REPLY_PLAYBACK_TIMEOUT_S = 20.0
#: Quiet after the last played chunk that ends an answer (see _until_played).
_ANSWER_QUIET_S = 0.5
#: Session messages that mean the caller interrupted: Twilio must drop what it
#: still holds of the old answer.
_CLEAR_MESSAGES = frozenset({"tts_cancel", "audio_clear"})
#: Session messages that mean the session itself is over.
_CLOSED_MESSAGES = frozenset({"hangup", "audio_closed"})
#: Session messages that mean the session failed.
_FAILED_MESSAGES = frozenset({"provider_error", "audio_failed"})


class PhoneCall:
    """Bridges one Twilio media stream to one realtime voice session."""

    def __init__(
        self,
        *,
        call_sid: str,
        stream_sid: str,
        send: SendFn,
        hang_up: HangUpFn,
        build_session: BuildSessionFn,
        from_number: str = "",
        to_number: str = "",
        language_code: str = "de-DE",
        direction: str = "inbound",
        opening: str = "",
        greeting: str = "",
        assistant_name: str = "",
        max_call_seconds: int = 600,
        volume: float = 1.0,
        bus: Any = None,
    ) -> None:
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self._send = send
        self._hang_up = hang_up
        self._build_session = build_session
        self.from_number = from_number
        self.to_number = to_number
        self.language_code = language_code or "de-DE"
        self.direction = "outbound" if direction == "outbound" else "inbound"
        self.opening = (opening or "").strip()
        self.greeting = (greeting or "").strip()
        self.assistant_name = (assistant_name or "").strip()
        self.max_call_seconds = max_call_seconds
        self._volume = volume
        self._bus = bus

        self.session: Any = None
        self.status = CALL_IN_PROGRESS
        self._ended = False
        self._end_reason = ""
        self._started_at = time.time()
        self._turns = 0
        self._any_audio = False
        self._ready = False
        self._output_rate = _DEFAULT_OUTPUT_RATE
        self._out_resampler = Resampler(self._output_rate, TWILIO_SAMPLE_RATE)
        # Master-volume limiter, built on first audio so importing this module
        # costs no numpy. Stateful like the resampler.
        self._out_limiter: Any = None
        # Playback bookkeeping: every outbound chunk is followed by a mark;
        # Twilio echoes a mark once the audio before it has played.
        self._audio_chunks = 0
        self._marks_sent = 0
        self._last_mark = ""
        self._last_mark_played = ""
        # Set while Twilio has played everything sent so far.
        self._played = asyncio.Event()
        self._played.set()
        # Set by every outbound audio chunk (cleared by whoever waits for one).
        self._audio_sent = asyncio.Event()
        self._last_user_text = ""
        self._assistant_text = ""
        self._deciding = False
        self._tasks: set[asyncio.Task[Any]] = set()

    # -- public properties -------------------------------------------------

    @property
    def ended(self) -> bool:
        return self._ended

    @property
    def end_reason(self) -> str:
        return self._end_reason

    @property
    def turns(self) -> int:
        return self._turns

    @property
    def duration_s(self) -> float:
        return time.time() - self._started_at

    @property
    def playing(self) -> bool:
        """Whether Twilio still holds audio we sent that has not played yet."""
        return self._last_mark != self._last_mark_played

    # -- lifecycle ---------------------------------------------------------

    def call_brief(self) -> str:
        """What the model has to know about this call; joins its instructions."""
        lines = [
            "PHONE CALL. You are talking on an ordinary telephone line. Keep every "
            "reply short and spoken; never read out lists, links, code or formatting. "
            "Nothing you put on a screen reaches the person on the line.",
            f"The call's language is {self.language_code} unless the person speaks "
            "another one.",
        ]
        decision = decision_calls.get(self.call_sid)
        if decision is not None:
            lines.append(
                "You called the owner about exactly one decision, stated in your "
                "opening line. The application itself reads the owner's answer (yes, "
                "no or later), applies it and tells them the result. Never say yourself "
                "that anything was approved, denied or done; if asked, say the answer "
                "is being applied."
            )
        elif self.direction == "outbound":
            lines.append(
                "You placed this call on the owner's behalf. The person on the line is "
                "not the owner: never share the owner's private information (messages, "
                "calendar, memory, files, other people's details) and never use tools "
                "or take actions on their request. Stay on the purpose of the call, "
                "answer their questions about it, and end the call politely when it "
                "is done."
            )
            if self.opening:
                lines.append(f'You open the call with this line: "{self.opening}"')
        else:
            lines.append(
                "The owner called you from one of their own numbers. Treat the person "
                "on the line as the owner."
            )
        return "\n".join(lines)

    async def start(self) -> bool:
        """Build the session and start it; ``False`` when no session can hold the call.

        The provider handshake runs in the background so the media loop keeps
        draining Twilio's frames meanwhile.
        """
        try:
            self.session = self._build_session(
                send_binary=self._on_session_audio,
                send_json=self._on_session_message,
                call_brief=self.call_brief(),
            )
        except Exception:  # noqa: BLE001  # broad-except: an unbuildable session refuses the call below
            log.warning("telephony[%s] realtime session build failed", self.call_sid,
                        exc_info=True)
            self.session = None
        if self.session is None:
            log.warning(
                "telephony[%s] no realtime voice connection can hold a phone call "
                "(none is set up, or the selected one needs a browser); ending the call",
                self.call_sid,
            )
            await self.end(reason="realtime_unavailable", status=CALL_FAILED)
            return False
        self._spawn(self._open(), name=f"phone-open-{self.call_sid}")
        if self.max_call_seconds > 0:
            self._spawn(self._time_cap(), name=f"phone-cap-{self.call_sid}")
        return True

    async def _open(self) -> None:
        try:
            await self.session.handle_control(
                {"type": "audio_start", "sample_rate": TWILIO_SAMPLE_RATE}
            )
        except Exception as exc:  # noqa: BLE001  # broad-except: a failed start ends the call honestly
            log.warning("telephony[%s] realtime session could not start: %s",
                        self.call_sid, exc)
            await self.end(reason="realtime_start_failed", status=CALL_FAILED, hang_up=True)
            return
        if self._ended:
            return
        if bool(getattr(self.session, "failed", False)):
            log.warning("telephony[%s] realtime session failed while starting: %s",
                        self.call_sid, getattr(self.session, "failure_detail", "") or "")
            await self.end(reason="realtime_start_failed", status=CALL_FAILED, hang_up=True)
            return
        self._ready = True
        await self._say(self._first_line(), kind="call_opening", until_assistant_speaks=True)

    def _first_line(self) -> str:
        if self.direction == "outbound" and self.opening:
            return self.opening
        if self.greeting:
            return self.greeting
        lang = self._lang_short()
        from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME

        name = self.assistant_name
        if name and name != DEFAULT_ASSISTANT_NAME:
            return _NAMED_GREETINGS[lang].format(name=name)
        return _DEFAULT_GREETINGS[lang]

    async def _time_cap(self) -> None:
        await asyncio.sleep(self.max_call_seconds)
        log.info("telephony[%s] reached max_call_seconds=%s", self.call_sid,
                 self.max_call_seconds)
        await self.end(reason="max_call_seconds", status=CALL_COMPLETED, hang_up=True)

    def check_time_cap(self) -> bool:
        """Return ``True`` if the call exceeded ``max_call_seconds``."""
        return self.max_call_seconds > 0 and self.duration_s >= self.max_call_seconds

    async def end(
        self, *, reason: str = "", status: str = CALL_COMPLETED, hang_up: bool = False
    ) -> None:
        """End the call: stop the session, settle the status, publish the end.

        ``hang_up`` also closes the media socket — for an end the caller did
        not cause (the session ended, the cap fired, a decision was settled).
        """
        if self._ended:
            return
        self._ended = True
        self._end_reason = reason
        decision_calls.discard(self.call_sid)
        if status == CALL_COMPLETED and not self._any_audio:
            status = CALL_NO_AUDIO
        self.status = status
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current:
                task.cancel()
        if self.session is not None:
            session_reason = HANGUP_ERROR if status == CALL_FAILED else HANGUP_CLIENT_STOP
            try:
                await self.session.end(reason=session_reason)
            except Exception:  # noqa: BLE001  # broad-except: the phone line still closes below
                log.warning("telephony[%s] realtime session did not end cleanly",
                            self.call_sid, exc_info=True)
        self._publish_end()
        log.info(
            "telephony[%s] ended: status=%s reason=%s turns=%d dur=%.1fs",
            self.call_sid, self.status, reason, self._turns, self.duration_s,
        )
        if hang_up:
            try:
                await self._hang_up()
            except Exception:  # noqa: BLE001  # broad-except: the socket may already be gone
                log.debug("telephony[%s] media socket already closed", self.call_sid,
                          exc_info=True)

    # -- Twilio -> session -------------------------------------------------

    async def handle_media(self, payload_b64: str) -> None:
        """Forward one inbound Twilio ``media`` frame (base64 mu-law 8 kHz)."""
        if self._ended:
            return
        try:
            ulaw = base64.b64decode(payload_b64, validate=True)
        except (binascii.Error, ValueError):
            log.debug("telephony[%s] dropped a malformed media frame", self.call_sid)
            return
        if not ulaw:
            return
        self._any_audio = True
        if not self._ready or self.session is None:
            # The session drops audio before it is ready anyway; holding it
            # back here also keeps it off the provider's default input rate.
            return
        try:
            await asyncio.wait_for(
                self.session.handle_audio_frame(ulaw_to_pcm16(ulaw)),
                timeout=_AUDIO_SEND_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001  # broad-except: a dead session ends the call
            log.warning("telephony[%s] caller audio could not reach the session: %s",
                        self.call_sid, exc)
            await self.end(reason="realtime_failed", status=CALL_FAILED, hang_up=True)

    def handle_mark(self, name: str) -> None:
        """Twilio played everything sent before the mark ``name``."""
        if name:
            self._last_mark_played = name
            if not self.playing:
                self._played.set()

    # -- session -> Twilio -------------------------------------------------

    async def _on_session_audio(self, pcm: bytes) -> None:
        if self._ended or not pcm:
            return
        from dodaios.audio.gain import PeakLimiter, apply_output_gain_pcm16

        if self._out_limiter is None:
            self._out_limiter = PeakLimiter()
        pcm8 = self._out_resampler.process(pcm)
        pcm8 = apply_output_gain_pcm16(
            pcm8, self._volume, sample_rate=TWILIO_SAMPLE_RATE, limiter=self._out_limiter
        )
        ulaw = pcm16_to_ulaw(pcm8)
        if not ulaw:
            return
        self._audio_chunks += 1
        self._audio_sent.set()
        await self._send(
            {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(ulaw).decode("ascii")},
            }
        )
        self._marks_sent += 1
        self._last_mark = f"out-{self._marks_sent}"
        self._played.clear()
        await self._send(
            {"event": "mark", "streamSid": self.stream_sid, "mark": {"name": self._last_mark}}
        )

    async def _on_session_message(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type", "") or "")
        if kind == "audio_ready":
            rate = int(message.get("output_sample_rate") or _DEFAULT_OUTPUT_RATE)
            if rate != self._output_rate:
                self._output_rate = rate
                self._out_resampler = Resampler(rate, TWILIO_SAMPLE_RATE)
        elif kind in _CLEAR_MESSAGES:
            await self._clear_playback()
        elif kind == "transcript":
            await self._on_transcript(message)
        elif kind == "turn_complete":
            self._turns += 1
            self._publish_turn()
        elif kind in _CLOSED_MESSAGES:
            if not self._ended:
                self._spawn(self._end_after_playback(), name=f"phone-end-{self.call_sid}")
        elif kind in _FAILED_MESSAGES:
            log.warning(
                "telephony[%s] realtime session reported a failure: %s",
                self.call_sid, message.get("error") or message.get("detail") or kind,
            )
            if bool(getattr(self.session, "failed", False)) and not self._ended:
                self._spawn(
                    self.end(reason="realtime_failed", status=CALL_FAILED, hang_up=True),
                    name=f"phone-fail-{self.call_sid}",
                )
        elif kind == "error_spoken":
            # A line the session wanted spoken by a surface's own speech output.
            # A phone line has none: the call carries only the model's voice.
            log.warning("telephony[%s] the session asked for a line the phone cannot "
                        "speak: %s", self.call_sid, str(message.get("text", ""))[:200])

    async def _clear_playback(self) -> None:
        """Barge-in: Twilio drops the audio it still holds of the old answer."""
        try:
            await self._send({"event": "clear", "streamSid": self.stream_sid})
        except Exception:  # noqa: BLE001  # broad-except: the next answer plays regardless
            log.debug("telephony[%s] clear was not delivered", self.call_sid, exc_info=True)
        self._out_resampler.reset()
        if self._out_limiter is not None:
            self._out_limiter.reset()

    async def _on_transcript(self, message: dict[str, Any]) -> None:
        role = str(message.get("role", "") or "")
        text = str(message.get("text", "") or "").strip()
        if role == "assistant":
            if message.get("is_final") and text:
                self._assistant_text = text
            return
        if role != "user" or not message.get("is_final") or not text:
            return
        self._last_user_text = text
        decision = decision_calls.get(self.call_sid)
        if decision is not None and not self._deciding:
            await self._answer_decision(decision, text)

    # -- one-decision calls --------------------------------------------------

    async def _answer_decision(self, call: decision_calls.DecisionCall, text: str) -> None:
        """Yes / no / later for the one decision this call carries, then hang up."""
        answer = decision_calls.classify_answer(text)
        if answer is None and not call.asked_again:
            call.asked_again = True
            if call.reprompt:
                self._spawn(self._say(call.reprompt, kind="call_decision"),
                            name=f"phone-reprompt-{self.call_sid}")
                return
        if answer is None or (answer == decision_calls.YES and not call.accepts_yes):
            answer = decision_calls.LATER
        self._deciding = True
        self._spawn(self._settle_decision(call, answer), name=f"phone-decide-{self.call_sid}")

    async def _settle_decision(self, call: decision_calls.DecisionCall, answer: str) -> None:
        if answer == decision_calls.LATER:
            reply = call.later_reply
        else:
            try:
                reply = await call.resolve(answer)
            except Exception:  # noqa: BLE001  # broad-except: the card stays open; say so, never claim it ran
                log.warning("telephony[%s] decision not applied", self.call_sid, exc_info=True)
                reply = call.later_reply
        if reply:
            from dodaios.brain.output_filter import scrub_for_voice

            spoken = scrub_for_voice(reply, language=self._lang_short()).cleaned
            chunks_before = self._audio_chunks
            if await self._say(spoken, kind="call_decision"):
                await self._wait_for_reply_played(chunks_before)
        await self.end(reason=f"decision_{answer}", status=CALL_COMPLETED, hang_up=True)

    async def _end_after_playback(self) -> None:
        """The session ended the call: let Twilio play the goodbye, then hang up.

        Closing the stream at once would cut off whatever Twilio still holds
        of the last answer (bounded, so a lost mark never keeps the line open).
        """
        try:
            async with asyncio.timeout(_REPLY_PLAYBACK_TIMEOUT_S):
                await self._until_played()
        except TimeoutError:
            log.info("telephony[%s] goodbye did not finish playing in time", self.call_sid)
        await self.end(reason="session_ended", status=CALL_COMPLETED, hang_up=True)

    async def _wait_for_reply_played(self, chunks_before: int) -> None:
        """Until the reply's audio started and Twilio played all of it (bounded)."""
        try:
            async with asyncio.timeout(_REPLY_PLAYBACK_TIMEOUT_S):
                if self._audio_chunks == chunks_before:
                    self._audio_sent.clear()
                    await self._audio_sent.wait()
                await self._until_played()
        except TimeoutError:
            log.info("telephony[%s] decision reply did not finish playing in time",
                     self.call_sid)

    async def _until_played(self) -> None:
        """Until Twilio played everything and no new audio followed for a moment.

        A model streams one answer in chunks; Twilio can catch up between two
        of them, so the answer counts as over only after a short quiet spell.
        Callers bound the wait.
        """
        while True:
            await self._played.wait()
            self._audio_sent.clear()
            try:
                await asyncio.wait_for(self._audio_sent.wait(), _ANSWER_QUIET_S)
            except TimeoutError:  # the quiet spell is the answer being over
                return

    # -- helpers -------------------------------------------------------------

    async def _say(self, text: str, *, kind: str, until_assistant_speaks: bool = False) -> bool:
        """Offer one trusted line to the model until it takes it; ``True`` when taken.

        ``until_assistant_speaks`` gives up as soon as the model already spoke
        on its own (the opening is moot once the conversation runs).
        """
        speak = getattr(self.session, "speak_line", None)
        line = (text or "").strip()
        if not line or not callable(speak):
            return False
        for _ in range(_LINE_ATTEMPTS):
            if self._ended:
                return False
            if until_assistant_speaks and self._audio_chunks:
                return False
            try:
                if await speak(line, kind=kind):
                    return True
            except Exception:  # noqa: BLE001  # broad-except: the conversation goes on without the line
                log.warning("telephony[%s] the %s line was not delivered", self.call_sid,
                            kind, exc_info=True)
                return False
            await asyncio.sleep(_LINE_RETRY_S)
        log.info("telephony[%s] the model never took the %s line", self.call_sid, kind)
        return False

    def _spawn(self, coro: Awaitable[Any], *, name: str) -> asyncio.Task[Any]:
        task: asyncio.Task[Any] = asyncio.ensure_future(coro)
        task.set_name(name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("telephony[%s] call task %s failed", self.call_sid, task.get_name(),
                        exc_info=exc)

    def _lang_short(self) -> str:
        """Short language code of the call (de/en/es/pt); English for others."""
        short = self.language_code.lower().split("-")[0]
        return short if short in _DEFAULT_GREETINGS else "en"

    # -- bus events --------------------------------------------------------

    def _publish(self, event: Any) -> None:
        if self._bus is None:
            return
        try:
            self._spawn(self._bus.publish(event), name=f"phone-event-{self.call_sid}")
        except Exception:  # noqa: BLE001  # broad-except: bus errors never break a call
            log.debug("telephony[%s] bus publish failed", self.call_sid, exc_info=True)

    def _publish_turn(self) -> None:
        from .events import TelephonyCallTurn

        self._publish(
            TelephonyCallTurn(
                call_sid=self.call_sid,
                transcript=self._last_user_text,
                response_text=self._assistant_text,
                outbound_frames=self._audio_chunks,
            )
        )

    def _publish_end(self) -> None:
        if self._bus is None:
            return
        from .events import TelephonyCallEnded

        event = TelephonyCallEnded(
            call_sid=self.call_sid,
            status=self.status,
            duration_s=self.duration_s,
            turns=self._turns,
            reason=self._end_reason,
        )
        # Not a call task: end() cancels those, and the end event must still go out.
        try:
            task = asyncio.ensure_future(self._bus.publish(event))
        except Exception:  # noqa: BLE001  # broad-except: bus errors never break a call
            log.debug("telephony[%s] end event not published", self.call_sid, exc_info=True)
            return
        _END_EVENTS.add(task)
        task.add_done_callback(_END_EVENTS.discard)


# Strong references for the fire-and-forget end events (see _publish_end).
_END_EVENTS: set[asyncio.Task[Any]] = set()


__all__ = ["PhoneCall"]
