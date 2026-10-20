"""Runtime STT fallback — cross to another provider family when one fails.

``build_stt_from_config`` already picks a different provider when the configured
one has no usable credential. That is a BUILD-time decision, and it was the only
one there was: once a provider was chosen, a failure at CALL time ended the
transcription. So a Groq rate limit in the middle of a dictation deleted the
user's words even though three other keyed providers were sitting there unused
(live bug 2026-07-29: a 137 s dictation returned 367 characters, the log full of
``429 Too Many Requests``).

That is exactly what AP-22 forbids — "a missing / depleted / 429 / 402 /
unreachable one degrades or crosses to a **different family** with an honest
message, never bricking a core path". This module supplies the missing half.

What it does NOT do, on purpose:

* **It never retries a rejection the audio itself caused.** A 400 means this
  provider understood the request and refused it; sending the same bytes to
  another provider would just burn a second quota for the same answer. Only
  failures another provider could plausibly survive cross over — the quota,
  availability and transport ones enumerated in :func:`_is_crossable`.
* **It never builds an alternate on the boot path** (AP-26). The chain is a
  list of provider NAMES; an instance is constructed the first time it is
  actually needed and then kept.
* **It never reorders the user's choice.** The configured provider is always
  tried first, except while it is in the cooldown a rate limit put it in —
  which is the whole point: hammering a 429 keeps it locked.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

log = logging.getLogger(__name__)

#: How long a provider stays skipped after it reported a quota failure. Long
#: enough that a per-minute limit has actually rolled over, short enough that a
#: user who fixed their billing is not stuck on the fallback all session.
RATE_LIMIT_COOLDOWN_S = 60.0

#: Cooldown for the failures that are not about quota (5xx, transport). Shorter:
#: these clear on their own and the user's configured provider should come back
#: as soon as it can.
TRANSIENT_COOLDOWN_S = 15.0

#: Reasons whose cooldown is the LONG one. A quota window and a rejected key
#: both need real time to change; a 5xx or a dropped connection does not.
_LONG_COOLDOWN_REASONS = frozenset({"rate_limited", "no_credit", "bad_key"})

#: Per-provider deadline, as a multiple of the audio sent. Matches the dictation
#: lane's own per-call ceiling, so a call that used to succeed on the provider in
#: front still does; only one that used to run out the WHOLE ceiling now crosses.
PROVIDER_DEADLINE_PER_AUDIO_S = 2.0


class ProviderDeadlineExceeded(RuntimeError):
    """A provider with another one behind it did not answer within its deadline.

    Live bug 2026-10-20 17:35: the on-device final pass hung on 1.9 s of audio,
    the dictation lane's single 8 s ceiling around the WHOLE chain ran out while
    the chain was still waiting on it, and the cloud provider behind it never
    got the audio — 0 characters, although a working fallback was keyed. The
    chain now bounds every provider that is not the last one, so a wedge costs
    its own deadline and then crosses.

    Carries ``status = 503`` so :func:`dodaios.speech.stt_failure.classify_stt_failure`
    reads it as ``unavailable`` — crossable, and transient to the dictation
    retry ladder. It is deliberately NOT a ``TimeoutError``: that type means the
    lane's own outer ceiling ran out (a wedge of the LAST provider), which the
    ladder refuses to retry; this one means "the next provider has not been
    asked yet".
    """

    status = 503


def audio_seconds(pcm: object, sample_rate: object = 16_000) -> float:
    """Duration of int16 mono PCM ``pcm``; ``0.0`` for anything that is not bytes."""
    if not isinstance(pcm, (bytes, bytearray, memoryview)):
        return 0.0
    try:
        rate = int(sample_rate or 16_000)
    except (TypeError, ValueError):  # an unusable rate means the 16 kHz default
        rate = 16_000
    return len(pcm) / float(max(1, rate) * 2)


def provider_deadline_s(audio_s: float, floor_s: float) -> float:
    """How long ONE provider in front of another gets for ``audio_s`` of audio."""
    return max(float(floor_s), max(0.0, float(audio_s)) * PROVIDER_DEADLINE_PER_AUDIO_S)


def _classify(exc: BaseException) -> str:
    """The failure reason when another provider deserves a shot, else ``""``.

    Delegates to :func:`dodaios.speech.stt_failure.classify_stt_failure` rather
    than keeping a second marker table. The same judgement is what the dictation
    history stores and what the UI translates, and two tables that must agree
    are two tables that will not (AP-4).

    A ``rejected`` (400-class) answer deliberately returns ``""``: the provider
    understood the request and refused it, so another one would refuse the same
    bytes and only burn a second quota to say so.
    """
    from dodaios.speech.stt_failure import classify_stt_failure, is_crossable_failure

    reason = classify_stt_failure(exc)
    return reason if is_crossable_failure(reason) else ""


def _is_crossable(exc: BaseException) -> bool:
    """Whether another provider deserves a shot at this same audio."""
    return bool(_classify(exc))


class FallbackSTT:
    """One STT handle that crosses to another provider on a runtime failure.

    Transparent decorator, same shape as ``DictionaryCorrectingSTT``: every
    attribute that is not a transcribe method delegates to whichever provider is
    currently in front, so duck-typed callers (``recover()``, ``is_warm``, model
    fields) keep working.

    ``alternates`` are provider NAMES, not instances — see the module docstring
    on why nothing here is built until it is needed.
    """

    def __init__(
        self,
        primary: Any,
        alternates: Sequence[str],
        build: Any,
        *,
        primary_name: str = "",
        provider_deadline_floor_s: float | None = None,
    ) -> None:
        self._primary = primary
        self._primary_name = primary_name or type(primary).__name__
        # ``None`` keeps the historical behaviour (the caller's own ceiling is
        # the only bound). A number arms per-provider deadlines on
        # ``transcribe_pcm`` for every provider that has another one behind it.
        self._deadline_floor_s = (
            None
            if provider_deadline_floor_s is None
            else max(0.1, float(provider_deadline_floor_s))
        )
        self._alternate_names = list(alternates)
        self._build = build
        # name -> instance, built on first use and kept for the process.
        self._instances: dict[str, Any] = {}
        # name -> monotonic deadline before which we do not try it again.
        self._cooldown: dict[str, float] = {}
        # The alternate that last worked, tried first among the alternates so a
        # long dictation does not re-walk the whole chain on every segment.
        self._preferred: str | None = None
        # One lock per provider that cannot take concurrent calls. The chain is
        # handed concurrent requests by the dictation lane when its PRIMARY
        # allows them; a crossover to a native engine (faster-whisper raises
        # ``TranscribeBusy`` on a second caller, AP-24) must then serialise
        # those calls here rather than turn each of them into an ``engine_busy``
        # failure — which is exactly what the live 2026-08-15 history shows.
        self._serial_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)

    def __repr__(self) -> str:  # pragma: no cover — logging nicety
        return f"FallbackSTT({self._primary_name} -> {self._alternate_names})"

    @property
    def provider_label(self) -> str:
        return self._primary_name

    @property
    def supports_concurrent_requests(self) -> bool:
        """Whether callers may run several transcriptions at once.

        Answered by the PRIMARY, because that is the provider those concurrent
        calls normally land on. A crossover mid-flight to a provider that
        cannot take them is serialised inside :meth:`_call`, so a caller that
        read ``True`` here stays safe either way.
        """
        return bool(getattr(self._primary, "supports_concurrent_requests", False))

    def crossing_reserve_s(self, audio_s: float) -> float:
        """Extra wall-clock time a caller's ceiling must allow for crossing.

        Each provider in front of another may use up to its own deadline before
        the chain moves on, so a caller that bounds the whole call with ONE
        provider's worth of time cuts the chain off exactly where it was about
        to cross — the 2026-10-20 lost dictation. The caller adds this to its
        own per-call ceiling; the last provider keeps that ceiling for itself.
        ``0.0`` when the chain does not arm deadlines or has nowhere to cross.
        """
        if self._deadline_floor_s is None or not self._alternate_names:
            return 0.0
        return provider_deadline_s(audio_s, self._deadline_floor_s) * len(
            self._alternate_names
        )

    @property
    def last_used_provider(self) -> str:
        """Which provider produced the most recent transcript."""
        return self._last_used

    @property
    def last_used_model(self) -> str:
        """Model exposed by the provider that produced the latest transcript.

        Alternates are constructed lazily, so an unused one has no model to
        report. The common attribute spellings cover the cloud plugins and the
        local faster-whisper provider without making a provider id load-bearing.
        """
        name = self._last_used
        if not name:
            return ""
        provider = (
            self._primary
            if name == self._primary_name
            else self._instances.get(name)
        )
        if provider is None:
            return ""
        for attribute in ("last_used_model", "_model", "_model_name"):
            value = getattr(provider, attribute, "")
            if value:
                return str(value)
        return ""

    _last_used = ""
    _last_failure: str | None = None

    @property
    def last_failure(self) -> str | None:
        """What the primary failed with when a fallback produced the latest
        transcript, else ``None``. In memory only; the speech meter hands it to
        the provider-health record, which keeps just its classification."""
        return self._last_failure

    # ------------------------------------------------------------------
    # Cooldown bookkeeping
    # ------------------------------------------------------------------
    def _available(self, name: str) -> bool:
        until = self._cooldown.get(name, 0.0)
        return time.monotonic() >= until

    def _penalize(self, name: str, kind: str) -> None:
        seconds = (
            RATE_LIMIT_COOLDOWN_S
            if kind in _LONG_COOLDOWN_REASONS
            else TRANSIENT_COOLDOWN_S
        )
        self._cooldown[name] = time.monotonic() + seconds

    def _instance(self, name: str) -> Any:
        inst = self._instances.get(name)
        if inst is None:
            inst = self._build(name)
            self._instances[name] = inst
        return inst

    def _order(self) -> list[tuple[str, Any]]:
        """(name, provider) pairs to try, best first.

        The configured provider leads unless it is cooling down, in which case
        it moves to the BACK rather than being dropped: if every alternate is
        also exhausted it still gets the last word, which beats returning
        nothing at all.
        """
        alternates = [n for n in self._alternate_names]
        if self._preferred in alternates:
            alternates.remove(self._preferred)
            alternates.insert(0, self._preferred)
        head: list[tuple[str, Any]] = []
        tail: list[tuple[str, Any]] = []
        entry = (self._primary_name, self._primary)
        (head if self._available(self._primary_name) else tail).append(entry)
        for name in alternates:
            (head if self._available(name) else tail).append((name, None))
        return head + tail

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------
    async def _invoke(self, name: str, provider: Any, fn: Any, args: Any, kwargs: Any) -> Any:
        if getattr(provider, "supports_concurrent_requests", False):
            return await fn(*args, **kwargs)
        lock = self._serial_locks.setdefault(name, asyncio.Lock())
        async with lock:
            return await fn(*args, **kwargs)

    async def _invoke_bounded(
        self,
        name: str,
        provider: Any,
        fn: Any,
        args: Any,
        kwargs: Any,
        deadline_s: float,
        audio_s: float,
    ) -> Any:
        """``_invoke`` with a deadline that ends in a CROSSABLE failure.

        The wait for a serial provider's lock is inside the deadline on
        purpose: queueing behind a wedged call is the same wedge. A provider's
        OWN timeout exception (aiohttp raises ``TimeoutError``) still reaches
        the classifier unchanged — only this chain's deadline becomes
        :class:`ProviderDeadlineExceeded`.
        """
        task = asyncio.ensure_future(self._invoke(name, provider, fn, args, kwargs))
        try:
            done, _pending = await asyncio.wait({task}, timeout=deadline_s)
        except asyncio.CancelledError:
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            raise
        if task in done:
            return task.result()
        # Cancelling is what lets an on-device worker replace itself (AP-24:
        # a wedged native engine is recovered by killing it, never by waiting).
        task.cancel()
        try:
            late = await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
        except Exception as exc:  # noqa: BLE001 — the late failure is moot now
            log.debug("STT fallback: %s ended after its deadline (%s)", name, exc)
        else:
            # It finished in the instant between the deadline and the cancel:
            # a real transcript is never thrown away to make a point.
            return late
        raise ProviderDeadlineExceeded(
            f"{name} did not answer within {deadline_s:.0f}s for "
            f"{audio_s:.1f}s of audio; the next provider takes it"
        )

    async def _call(
        self,
        method: str,
        *args: Any,
        _deadline_audio_s: float | None = None,
        **kwargs: Any,
    ) -> Any:
        first_error: BaseException | None = None
        self._last_failure = None
        order = self._order()
        for index, (name, preloaded) in enumerate(order):
            try:
                provider = preloaded if preloaded is not None else self._instance(name)
            except Exception as exc:  # noqa: BLE001 — an unbuildable alternate is skipped
                log.debug("STT fallback: %s could not be built (%s)", name, exc)
                self._penalize(name, "transient")
                continue
            fn = getattr(provider, method, None)
            if fn is None:
                continue
            # Only a provider with another one BEHIND it is bounded here. The
            # last one keeps the caller's ceiling for itself: there is nowhere
            # left to cross, and cutting it short would only lose the words.
            floor_s = self._deadline_floor_s
            try:
                if (
                    floor_s is not None
                    and _deadline_audio_s is not None
                    and index < len(order) - 1
                ):
                    result = await self._invoke_bounded(
                        name,
                        provider,
                        fn,
                        args,
                        kwargs,
                        provider_deadline_s(_deadline_audio_s, floor_s),
                        _deadline_audio_s,
                    )
                else:
                    result = await self._invoke(name, provider, fn, args, kwargs)
            except Exception as exc:  # noqa: BLE001 — classified below
                kind = _classify(exc)
                if not kind:
                    # The provider understood us and refused. Another one would
                    # refuse the same bytes; surface it instead of burning quota.
                    raise
                if first_error is None:
                    first_error = exc
                if name == self._primary_name and self._last_failure is None:
                    self._last_failure = f"{type(exc).__name__}: {exc}"
                self._penalize(name, kind)
                log.warning(
                    "STT provider %s failed (%s: %s) — crossing to the next "
                    "provider so the transcription is not lost.",
                    name,
                    kind,
                    exc,
                )
                continue
            if name != self._primary_name:
                self._preferred = name
                log.info("STT transcribed by fallback provider %s.", name)
            self._last_used = name
            return result
        if first_error is not None:
            raise first_error
        raise RuntimeError("No speech-to-text provider was able to transcribe.")

    async def transcribe_pcm(self, *args: Any, **kwargs: Any) -> Any:
        audio_s: float | None = None
        if self._deadline_floor_s is not None and args:
            rate = args[1] if len(args) > 1 else kwargs.get("sample_rate", 16_000)
            audio_s = audio_seconds(args[0], rate)
        return await self._call(
            "transcribe_pcm", *args, _deadline_audio_s=audio_s, **kwargs
        )

    async def transcribe(self, *args: Any, **kwargs: Any) -> Any:
        return await self._call("transcribe", *args, **kwargs)

    async def stream_transcribe(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        # Streaming is NOT re-routed mid-stream: a consumer has already received
        # part of the transcript, and restarting on another provider would
        # duplicate it. The chain protects the one-shot calls, which is where
        # dictation and the final utterance transcription live.
        async for item in self._primary.stream_transcribe(*args, **kwargs):
            yield item


def alternate_provider_names(configured: str, available: Sequence[str]) -> list[str]:
    """The provider names to fall back to, in order, minus ``configured``.

    Ordered by what a failing provider most likely needs: another CLOUD family
    first (fast, and the user demonstrably has a key for it), then the key-free
    local engine as the floor. Local goes last because it is absent on a base /
    headless install and slow on a machine without a GPU — but when it IS there
    it is the one option no quota can take away.
    """
    ordered = [n for n in available if n != configured and n != "faster-whisper"]
    if "faster-whisper" in available and configured != "faster-whisper":
        ordered.append("faster-whisper")
    return ordered


def configured_fallback_names(
    stt_cfg: Any,
    configured: str,
    automatic: Sequence[str],
) -> tuple[str, ...]:
    """Apply the user's ``[stt].fallback`` setting to an automatic chain.

    An empty setting disables crossover, a concrete provider pins exactly that
    provider, and ``auto`` keeps the key-aware chain supplied by the caller.
    The selected provider is never repeated as its own fallback.
    """
    setting = str(getattr(stt_cfg, "fallback", "auto") or "").strip()
    if not setting:
        return ()
    if setting.lower() != "auto":
        return () if setting == configured else (setting,)
    return tuple(name for name in automatic if name != configured)


def wrap_stt_with_fallback(provider: Any, stt_cfg: Any) -> Any:
    """Wrap ``provider`` in a :class:`FallbackSTT` over the user's other keys.

    Returns ``provider`` unchanged when there is nothing to fall back to (no
    other keyed provider) or it is already wrapped — so a single-key install
    pays nothing for this.
    """
    if provider is None or isinstance(provider, FallbackSTT):
        return provider
    try:
        from dodaios.plugins.stt import (
            available_stt_provider_names,
            build_named_stt_provider,
        )

        configured = (getattr(stt_cfg, "provider", "") or "").strip()
        alternates = configured_fallback_names(
            stt_cfg,
            configured,
            alternate_provider_names(configured, available_stt_provider_names()),
        )
        if not alternates:
            return provider

        def _build(name: str) -> Any:
            return build_named_stt_provider(name, stt_cfg)

        log.info(
            "STT fallback chain armed: %s -> %s",
            configured or type(provider).__name__,
            ", ".join(alternates),
        )
        return FallbackSTT(
            provider, alternates, _build, primary_name=configured
        )
    except Exception as exc:  # noqa: BLE001 — a chain that cannot be built is not fatal
        log.warning("STT fallback chain unavailable (%s); using one provider.", exc)
        return provider


__all__ = [
    "FallbackSTT",
    "PROVIDER_DEADLINE_PER_AUDIO_S",
    "ProviderDeadlineExceeded",
    "RATE_LIMIT_COOLDOWN_S",
    "TRANSIENT_COOLDOWN_S",
    "alternate_provider_names",
    "audio_seconds",
    "provider_deadline_s",
    "configured_fallback_names",
    "wrap_stt_with_fallback",
]
