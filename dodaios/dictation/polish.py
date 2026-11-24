"""The dictation polish pass: a second, generative formatting stage.

Cleanup (:mod:`dodaios.dictation.cleanup`) cannot punctuate, repair capitals,
resolve self-corrections or lay out enumerations; this pass does, via a model
call. The same machinery runs the TRANSLATE pass (``translate_to``, see
:func:`resolve_translate_target`) in ONE call with its own prompt, guard set and
model tier. ``polish_precision`` licenses same-meaning word replacement and
pairs a prompt clause with ``precision_drift_reason``; it ships OFF because it
trades away a guard.

Contract: this pass can only be a no-op, never a loss. ``PolishOutcome.text`` is
the raw transcript until every guard in :mod:`dodaios.dictation.polish_guards`
passed. ``polish_transcript`` catches ``Exception`` but not ``BaseException``.

Bounds: (1) one ``asyncio.wait_for`` around the WHOLE pass, credential sweep
included; (2) a key-aware, family-crossing chain (AP-22), no key = status
``unavailable`` (AP-23); (3) a privacy floor: an on-device recognizer never
crosses to a cloud family unless the user pins one (``local_only``); (4) a
circuit breaker (3 failures, 120 s). The chain sweep runs in a worker thread
and is cached per fingerprint. AP-26: imported lazily by the speech pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

# The same async-safe breaker the Flash-Brain uses (one definition of "provider down").
from dodaios.brain.ack_brain.circuit_breaker import CircuitBreaker
from dodaios.dictation.cleanup import count_words
from dodaios.dictation.polish_client import (
    PolishFamily,
    aclose_shared_client,
    build_polish_client,
    family_recently_unreachable,
    note_family_failure,
    polish_chain_fingerprint,
    reset_credential_cache,
    reset_reachability_cache,
    resolve_model,
    resolve_polish_chain,
)
from dodaios.dictation.polish_guards import (
    drift_reason,
    normalize_for_compare,
    precision_drift_reason,
    translate_drift_reason,
)
from dodaios.dictation.polish_prompt import (
    build_polish_prompt,
    build_polish_user_message,
)
from dodaios.dictation.translate_prompt import build_translate_prompt

log = logging.getLogger(__name__)

#: Every status the pass may report (SSOT, mirrored in TypeScript and locale
#: files, pinned by a parity test). Only ``applied`` differs from the raw text.
POLISH_STATUSES: Final[tuple[str, ...]] = (
    "applied",        # the polished text was delivered
    "translated",     # the text was delivered in [dictation].translate_target
    "unchanged",      # the model returned text equal to raw after normalization
    "off",            # [dictation].polish = false
    "unavailable",    # no key in any family / client build failed / breaker open
    "local_only",     # on-device recognizer, and no on-device model answered
    "skipped_short",  # below polish_min_words
    "skipped_long",   # above polish_max_input_chars
    "timeout",        # exceeded polish_timeout_ms
    "provider_error",  # HTTP / SDK failure after the fallback chain
    "rejected_drift",  # a guard fired -> raw delivered
    "prompted",       # Prompt Mode: the text was rewritten into an agent prompt
)

#: Breaker threshold and cooldown; a safety floor, not config keys.
POLISH_BREAKER_THRESHOLD: Final[int] = 3
POLISH_BREAKER_COOLDOWN_S: Final[int] = 120

# Defaults for [dictation].polish_*, read via getattr() so older configs work.
_DEFAULT_TIMEOUT_MS = 1200
_DEFAULT_MAX_INPUT_CHARS = 0  # no cap; the clock and the drift guards bound it
_DEFAULT_MIN_WORDS = 4
_DEFAULT_MAX_OUTPUT_TOKENS = 1200
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_SHRINK = 0.55
_DEFAULT_MAX_GROWTH = 1.20

# The translate band is wider than polish's: translation changes length both ways.
_DEFAULT_TRANSLATE_MAX_SHRINK = 0.40
_DEFAULT_TRANSLATE_MAX_GROWTH = 2.50

# Precision band: substitution moves the count both ways, but growth is this
# mode's failure direction. Constants, not config: a dial would widen the one
# guard that is left (AP-31).
_DEFAULT_PRECISION_MAX_SHRINK = 0.45
_DEFAULT_PRECISION_MAX_GROWTH = 1.35

#: ``[dictation].translate_target`` value meaning "no fixed target".
_AUTO = "auto"

#: Smallest per-call timeout handed to a transport (0 s reads as a provider outage).
_MIN_CALL_TIMEOUT_S = 0.05

# Length ramp: the model must write the whole text out, so one ceiling would
# switch the feature off on long dictations (live: p90 992 ms at 25-49 words vs a
# 1200 ms ceiling). Each word past the free allowance buys _TIMEOUT_MS_PER_WORD,
# up to ``polish_timeout_max_ms``; the rate is ~3x the measured slope because the
# ceiling cuts off a DEAD provider rather than racing a slow one.
_TIMEOUT_FREE_WORDS = 25
_TIMEOUT_MS_PER_WORD = 15
_DEFAULT_TIMEOUT_MAX_MS = 2000


@dataclass(frozen=True, slots=True)
class PolishOutcome:
    """One polish attempt. ``text`` is the raw transcript on every status except
    ``applied``; ``reason`` is a machine-readable code, empty on success."""

    text: str
    status: str
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    reason: str = ""


@dataclass(slots=True)
class _Attempt:
    """Which family was in flight, so a timeout can name who it waited on."""

    provider: str = ""
    model: str = ""
    error: str = ""
    #: Every family offered keeps text on this machine: report ``local_only``.
    on_device_only: bool = False


_BREAKER: CircuitBreaker | None = None

#: Last resolved chain and its fingerprint; ``None`` until first use (AP-26).
_CHAIN_CACHE: tuple[tuple[Any, ...], tuple[PolishFamily, ...]] | None = None


def _breaker() -> CircuitBreaker:
    """The process-wide breaker, built on first use (never at import)."""
    global _BREAKER
    if _BREAKER is None:
        _BREAKER = CircuitBreaker(
            threshold=POLISH_BREAKER_THRESHOLD,
            cooldown_s=POLISH_BREAKER_COOLDOWN_S,
        )
    return _BREAKER


def reset_polish_state(*, now: Callable[[], float] | None = None) -> None:
    """Drop breaker, chain, credentials and unreachable-endpoint memory together."""
    global _BREAKER, _CHAIN_CACHE
    _CHAIN_CACHE = None
    reset_credential_cache()
    reset_reachability_cache()
    _BREAKER = CircuitBreaker(
        threshold=POLISH_BREAKER_THRESHOLD,
        cooldown_s=POLISH_BREAKER_COOLDOWN_S,
        now=now or time.monotonic,
    )


def polish_enabled(cfg: Any) -> bool:
    """Whether the polish pass is switched on (either wording switch). No I/O."""
    return bool(getattr(cfg, "polish", False)) or precision_enabled(cfg)


def precision_enabled(cfg: Any) -> bool:
    """Whether the pass may also sharpen WORD CHOICE. No I/O. Ships OFF (trades away a guard)."""
    return bool(getattr(cfg, "polish_precision", False))


def translate_enabled(cfg: Any) -> bool:
    """Whether dictation is set to come out in a fixed language. No I/O. Ships OFF."""
    return bool(getattr(cfg, "translate", False))


def resolve_translate_target(cfg: Any) -> str:
    """The language this dictation must be delivered in; ``""`` for no change.

    Reads the CONFIG only (the recognizer's language tag is unreliable). ``""``
    when off, no target or ``auto``, or the dictation language is PINNED to it.
    """
    if not translate_enabled(cfg):
        return ""
    target = str(getattr(cfg, "translate_target", "") or "").strip().lower()
    if not target or target == _AUTO:
        return ""
    # Primary subtag: a "de-DE" pin and a "de" target are one language.
    pinned = str(getattr(cfg, "language", _AUTO) or _AUTO).strip().lower()
    if pinned and pinned != _AUTO:
        if pinned.replace("_", "-").split("-", 1)[0] == target:
            return ""
    return target


async def aclose() -> None:
    """Release the pooled HTTP client. Safe to call repeatedly, and on a host
    that never ran a polish call at all."""
    await aclose_shared_client()


async def polish_transcript(
    raw: str,
    *,
    language: str,
    cfg: Any,
    protected_terms: Sequence[str] = (),
    style: str = "neutral",
    timeout_s: float | None = None,
    translate_to: str = "",
    preceding_text: str = "",
) -> PolishOutcome:
    """Format *raw* without changing what it says. Never raises, never loses text.

    ``preceding_text`` precedes *raw* in the same document and is passed as a
    style-only context block (ignored in translate mode); the guards judge *raw*
    alone. ``language`` is the already-resolved transcript language. Protected
    terms (STT dictionary, wake word, user name) may not be "corrected".
    ``timeout_s`` overrides the ceiling (tests, settings dry run).

    A non-empty ``translate_to`` (resolved target code) means TRANSLATE mode,
    status ``translated``, in the same ONE model call. The no-op contract holds
    in both modes, but a translate no-op is visible, so statuses matter.
    """
    started = time.perf_counter()
    source = str(raw or "")
    target = str(translate_to or "").strip().lower()
    translating = bool(target)

    def _result(
        status: str,
        *,
        provider: str = "",
        model: str = "",
        reason: str = "",
        text: str | None = None,
    ) -> PolishOutcome:
        return PolishOutcome(
            text=source if text is None else text,
            status=status,
            provider=provider,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            reason=reason,
        )

    try:
        if not polish_enabled(cfg) and not translating:
            return _result("off")
        if not source.strip():
            return _result("skipped_short", reason="empty_input")

        # ``polish_min_words`` does not apply to a translation (wrong language otherwise).
        if not translating and not precision_enabled(cfg):
            min_words = _cfg_int(
                cfg, "polish_min_words", _DEFAULT_MIN_WORDS, lo=0, hi=1000
            )
            if count_words(source) < min_words:
                return _result("skipped_short", reason="below_min_words")

        max_chars = _cfg_int(
            cfg, "polish_max_input_chars", _DEFAULT_MAX_INPUT_CHARS, lo=0, hi=200_000
        )
        if max_chars and len(source) > max_chars:
            return _result("skipped_long", reason="above_max_chars")

        breaker = _breaker()
        if await breaker.is_open():
            return _result("unavailable", reason="circuit_open")

        budget_s = _timeout_budget(cfg, timeout_s, words=count_words(source))
        attempt = _Attempt()
        # Resolved ONCE: the precision prompt and guard are a matched pair.
        precision = precision_enabled(cfg)
        if translating:
            system = build_translate_prompt(
                target_language=target,
                style=style,
                protected_terms=protected_terms,
                precision=precision,
            )
        else:
            prompt_kwargs: dict[str, Any] = {}
            if preceding_text.strip():
                prompt_kwargs["continuation"] = True
            system = build_polish_prompt(
                language=language,
                style=style,
                protected_terms=protected_terms,
                precision=precision,
                **prompt_kwargs,
            )
        if preceding_text.strip() and not translating:
            user = build_polish_user_message(source, preceding=preceding_text)
        else:
            user = build_polish_user_message(source)

        try:
            polished = await asyncio.wait_for(
                _resolve_and_run(
                    cfg,
                    system=system,
                    user=user,
                    attempt=attempt,
                    deadline=time.monotonic() + budget_s,
                    max_output_tokens=_cfg_int(
                        cfg,
                        "polish_max_output_tokens",
                        _DEFAULT_MAX_OUTPUT_TOKENS,
                        lo=64,
                        hi=8192,
                    ),
                    temperature=_cfg_float(
                        cfg, "polish_temperature", _DEFAULT_TEMPERATURE, lo=0.0, hi=2.0
                    ),
                    translating=translating,
                ),
                budget_s,
            )
        except TimeoutError:
            # asyncio.wait_for has already cancelled the in-flight call.
            await breaker.record_failure()
            log.info(
                "dictation polish exceeded its %d ms ceiling on %r; delivering "
                "the unpolished transcript.",
                int(budget_s * 1000),
                attempt.provider,
            )
            return _result(
                "timeout",
                provider=attempt.provider,
                model=attempt.model,
                reason="deadline",
            )

        if polished is None:
            if attempt.error == "no_credential":
                # AP-23: nothing worth dialling; no breaker failure, no provider to blame.
                log.debug(
                    "dictation polish found no usable provider family; "
                    "delivering the unpolished transcript."
                )
                return _result("unavailable", reason="no_credential")

            await breaker.record_failure()

            if attempt.on_device_only:
                # Privacy floor: on-device recognizer, no local model answered (a setup fact).
                log.info(
                    "dictation polish stayed on this machine because the "
                    "recognizer does (%s); no local model answered, so the "
                    "unpolished transcript was delivered.",
                    attempt.error or "unreachable",
                )
                return _result(
                    "local_only",
                    provider=attempt.provider,
                    model=attempt.model,
                    reason=attempt.error or "local_unreachable",
                )

            return _result(
                "provider_error",
                provider=attempt.provider,
                model=attempt.model,
                reason=attempt.error or "no_provider",
            )

        await breaker.record_success()

        if normalize_for_compare(polished) == normalize_for_compare(source):
            if translating and not _already_in_target(source, target):
                # The same string back is a FAILURE for a translator, unless the text
                # was already in the target language.
                log.info(
                    "dictation translation to %r came back unchanged on %r; "
                    "delivering the original transcript.",
                    target,
                    attempt.provider,
                )
                return _result(
                    "rejected_drift",
                    provider=attempt.provider,
                    model=attempt.model,
                    reason="not_translated",
                )
            # Deliver the RAW string, not its normalized twin.
            return _result(
                "unchanged", provider=attempt.provider, model=attempt.model
            )

        if translating:
            reason = translate_drift_reason(
                source,
                polished,
                target_language=target,
                protected=protected_terms,
                max_shrink=_cfg_float(
                    cfg,
                    "translate_drift_max_shrink",
                    _DEFAULT_TRANSLATE_MAX_SHRINK,
                    lo=0.0,
                    hi=1.0,
                ),
                max_growth=_cfg_float(
                    cfg,
                    "translate_drift_max_growth",
                    _DEFAULT_TRANSLATE_MAX_GROWTH,
                    lo=1.0,
                    hi=10.0,
                ),
            )
        elif precision:
            # Matched guard for the precision prompt: no rare-token check, own band.
            reason = precision_drift_reason(
                source,
                polished,
                language=language,
                protected=protected_terms,
                max_shrink=_DEFAULT_PRECISION_MAX_SHRINK,
                max_growth=_DEFAULT_PRECISION_MAX_GROWTH,
            )
        else:
            reason = drift_reason(
                source,
                polished,
                language=language,
                protected=protected_terms,
                max_shrink=_cfg_float(
                    cfg, "polish_drift_max_shrink", _DEFAULT_MAX_SHRINK, lo=0.0, hi=1.0
                ),
                max_growth=_cfg_float(
                    cfg, "polish_drift_max_growth", _DEFAULT_MAX_GROWTH, lo=1.0, hi=5.0
                ),
            )
        if reason:
            log.info(
                "dictation %s rejected by the %s guard on %r; delivering the "
                "original transcript.",
                "translation" if translating else "polish",
                reason,
                attempt.provider,
            )
            return _result(
                "rejected_drift",
                provider=attempt.provider,
                model=attempt.model,
                reason=reason,
            )

        return _result(
            "translated" if translating else "applied",
            provider=attempt.provider,
            model=attempt.model,
            text=polished,
        )
    except Exception:
        # Deliberately ``Exception`` and not ``BaseException``. Everything that
        # is genuinely OUR bug — a guard that raised, a malformed response, a
        # transport that surprised us — arrives here and costs the user nothing
        # but a formatting pass. The non-``Exception`` cases are a different
        # kind of event entirely: ``CancelledError``, ``KeyboardInterrupt`` and
        # ``SystemExit`` mean the process is being told to stop, they belong to
        # whoever raised them, and converting one of them into a
        # "provider_error" would leave a task that refuses to die.
        log.warning(
            "dictation polish failed unexpectedly; delivering the unpolished "
            "transcript.",
            exc_info=True,
        )
        return _result("provider_error", reason="unexpected")


def _already_in_target(text: str, target: str) -> bool:
    """Whether *text* is confidently already in *target* (de/en/es only; never guesses)."""
    if not target:
        return False
    from dodaios.core.turn_language import detect_text_language

    return detect_text_language(text) == target


async def _resolve_chain(cfg: Any) -> tuple[PolishFamily, ...]:
    """The provider chain, swept OFF the event loop and cached per fingerprint.

    The sweep can block for seconds on a locked keyring; a cancelled worker writes nothing.
    """
    global _CHAIN_CACHE

    try:
        fingerprint: tuple[Any, ...] | None = polish_chain_fingerprint(cfg)
    except Exception as exc:  # noqa: BLE001 — an unfingerprintable host re-sweeps
        # Never fatal, and never a stale answer either: with no fingerprint we
        # decline to read OR write the cache and pay for a fresh sweep.
        log.debug("polish chain fingerprint failed (%s); resolving afresh.", exc)
        fingerprint = None

    cached = _CHAIN_CACHE
    if fingerprint is not None and cached is not None and cached[0] == fingerprint:
        return cached[1]

    chain = await asyncio.to_thread(resolve_polish_chain, cfg)
    if fingerprint is not None:
        _CHAIN_CACHE = (fingerprint, chain)
    return chain


async def _resolve_and_run(
    cfg: Any,
    *,
    system: str,
    user: str,
    attempt: _Attempt,
    deadline: float,
    max_output_tokens: int,
    temperature: float,
    translating: bool = False,
) -> str | None:
    """Resolve the chain and walk it inside the ceiling; ``None`` = nothing to deliver."""
    chain = await _resolve_chain(cfg)
    if not chain:
        attempt.error = "no_credential"
        return None

    # Derived from the chain so the privacy rule and the reported answer cannot disagree.
    attempt.on_device_only = all(family.runs_on_device for family in chain)
    primary = chain[0]
    attempt.provider = primary.id
    attempt.model = resolve_model(
        primary, cfg, primary_id=primary.id, translating=translating
    )

    return await _run_chain(
        chain,
        cfg,
        system=system,
        user=user,
        attempt=attempt,
        deadline=deadline,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        translating=translating,
    )


async def _run_chain(
    chain: Sequence[PolishFamily],
    cfg: Any,
    *,
    system: str,
    user: str,
    attempt: _Attempt,
    deadline: float,
    max_output_tokens: int,
    temperature: float,
    translating: bool = False,
) -> str | None:
    """Walk the chain until one family answers; ``None`` when none does.

    Each call gets the REMAINING budget; a recently unreachable local endpoint is skipped.
    """
    primary_id = chain[0].id
    for index, family in enumerate(chain):
        model = resolve_model(
            family, cfg, primary_id=primary_id, translating=translating
        )
        attempt.provider = family.id
        attempt.model = model

        if family_recently_unreachable(family):
            attempt.error = "local_unreachable"
            continue

        client = build_polish_client(family, model=model)
        if client is None:
            attempt.error = "no_client"
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        # Reserve part of the deadline for a later family.
        call_budget = remaining * 0.75 if index < len(chain) - 1 else remaining
        try:
            text = await asyncio.wait_for(
                client.complete(
                    system,
                    user,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    timeout_s=call_budget,
                ),
                timeout=call_budget,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — cross to the next FAMILY (AP-22)
            attempt.error = "provider_error"
            # Only an on-device endpoint that answered NOTHING is remembered;
            # the function decides that, so this site stays a plain report of
            # what happened.
            note_family_failure(family, exc)
            log.warning(
                "dictation polish provider %r failed (%s); crossing to the next "
                "family.",
                family.id,
                type(exc).__name__,
            )
            continue

        if text and text.strip():
            return text
        attempt.error = "empty_response"
    return None


def _timeout_budget(cfg: Any, override_s: float | None, *, words: int = 0) -> float:
    """The hard ceiling for one wording pass, in seconds.

    The base covers up to :data:`_TIMEOUT_FREE_WORDS`; longer transcripts earn more,
    up to ``polish_timeout_max_ms``. An explicit ``override_s`` wins, unramped.
    """
    if override_s is not None:
        try:
            return max(_MIN_CALL_TIMEOUT_S, float(override_s))
        except (TypeError, ValueError):
            pass
    base_ms = _cfg_int(cfg, "polish_timeout_ms", _DEFAULT_TIMEOUT_MS, lo=200, hi=5000)
    max_ms = _cfg_int(
        cfg, "polish_timeout_max_ms", _DEFAULT_TIMEOUT_MAX_MS, lo=200, hi=20_000
    )
    extra_words = max(0, int(words) - _TIMEOUT_FREE_WORDS)
    ramped_ms = base_ms + extra_words * _TIMEOUT_MS_PER_WORD
    return min(max(base_ms, ramped_ms), max(base_ms, max_ms)) / 1000.0


def _cfg_int(cfg: Any, name: str, default: int, *, lo: int, hi: int) -> int:
    """Read an int setting, clamped; the default on anything unusable (a bad value
    must cost a setting, never a dictation)."""
    try:
        value = int(getattr(cfg, name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _cfg_float(cfg: Any, name: str, default: float, *, lo: float, hi: float) -> float:
    """Read a float setting, clamped, with the default on anything unusable."""
    try:
        value = float(getattr(cfg, name, default))
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN compares unequal to itself and clamps to nothing.
        return default
    return max(lo, min(hi, value))


__all__ = [
    "POLISH_BREAKER_COOLDOWN_S",
    "POLISH_BREAKER_THRESHOLD",
    "POLISH_STATUSES",
    "PolishOutcome",
    "aclose",
    "polish_enabled",
    "polish_transcript",
    "precision_enabled",
    "reset_polish_state",
    "resolve_translate_target",
    "translate_enabled",
]
