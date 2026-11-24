"""Universal any-word wake detector via Vosk grammar keyword spotting.

A small per-language Vosk model streams microphone audio through a GRAMMAR-constrained
recognizer that knows only the configured wake phrase(s) plus ``[unk]``; any word is pure
configuration (no training, cloud or GPU). Design: docs/decisions/wake-vosk-kws-confirm.md.

Two stages, AP-27-safe. Stage 1 (streaming grammar) fires on partials but alone false-accepts
ambient speech, so it never fires unconfirmed. Stage 2 is a free-decode confirm: a real wake
prefix plus a sound-close core, or the word-agnostic SHAPE of what was heard, which must also
win an acoustic competition against "<prefix> [unk]". A raw-energy gate rejects near-silent
candidates. The detector never emits transcript text: user speech must never double-enter the
pipeline through the wake path.

The early candidate-prefix verify runs the same checks on the audio heard so far and shows the
bar ~0.1-0.25 s after the partial; a positive is authoritative. It fails CLOSED, the full-window
confirm fails OPEN (never eats a real wake). The confirm decode is streamed during the tail
(``_StreamingVerify``), and stage 1 demotes the last secondary model when it cannot keep up.
Every native vosk call goes through ``vosk_native`` (one process-wide lock).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from dodaios.core.protocols import AudioChunk
from dodaios.core.wake_constants import (
    WAKE_PREFIXES,
    normalize_phrase_for_match,
    phrase_core_for_match,
    sound_fold,
)
from dodaios.plugins.wake.vosk_native import build_recognizer, import_vosk, native_call

log = logging.getLogger("jarvis.wake.vosk")

# One-shot latch: log a malformed native JSON payload once, not on every call.
_MALFORMED_RESULT_LOGGED = False


def _parse_recognizer_json(raw: str, *, where: str) -> dict:
    """Parse a KaldiRecognizer JSON payload; malformed native output is a no-hit (AD-6)."""
    global _MALFORMED_RESULT_LOGGED
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        if not _MALFORMED_RESULT_LOGGED:
            _MALFORMED_RESULT_LOGGED = True
            log.warning(
                "vosk-kws: recognizer returned malformed JSON at %s (%s); "
                "treating as no-hit. Raw payload: %r",
                where,
                exc,
                raw[:400] if isinstance(raw, str) else raw,
            )
        else:
            log.debug("vosk-kws: malformed recognizer JSON at %s (%s)", where, exc)
        return {}
    return parsed if isinstance(parsed, dict) else {}

# Minimum per-word grammar confidence for the verify re-score (the precision anchor; genuine
# wakes re-score ~1.0). Paired with the structured prefix/core confirm, since room speech can
# also re-score at 1.0.
_MIN_FINAL_CONF = 0.9

# Legacy whole-phrase sound-similarity floor; the structured confirm applies stronger
# prefix/core floors on top.
_CONFIRM_RATIO = 0.55

# A configured prefix is an independent anchor, so the core may stay tolerant (ASR token split
# "Jarvis" -> "joe avis"); a phrase without a prefix needs the stricter bare-core floor.
_PREFIXED_CORE_RATIO = 2.0 / 3.0
_UNPREFIXED_CORE_RATIO = 0.80

# Ratio floors say how SIMILAR the core is, not how much was heard: two matching letters
# ("na" vs "nova") must not spell a name. A spelled core needs three matching letters (all
# but one on a shorter core). Failing this is no rejection: the shape gate and the acoustic
# competition decide, as for every call the free ear could not spell.
_MIN_SPELLED_LETTERS = 3


def _spells_core(target: str, heard: str, floor: float) -> bool:
    """Is *heard* a spelling of the folded core *target* at *floor*?"""
    matcher = SequenceMatcher(None, target, heard)
    if matcher.ratio() < floor:
        return False
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched >= min(_MIN_SPELLED_LETTERS, len(target) - 1)


# The free decoder may garble the prefix ("age avis"): accept exactly one prefix-shaped token
# plus a core above this stronger floor.
_GARBLED_PREFIX_CORE_RATIO = 0.80
_GARBLED_PREFIX_PHRASE_RATIO = 0.62

# Merged-phrase rescue ("herum"): needs independent prefix, core and phrase similarity.
_MERGED_PREFIX_RATIO = 0.40
_MERGED_CORE_RATIO = 0.40
_MERGED_PHRASE_RATIO = 0.53
_MERGED_MIN_LENGTH_RATIO = 0.55
_MERGED_MAX_LENGTH_RATIO = 1.20

# Word-agnostic energy floor (AP-27: silence is gated on raw energy, never on transcript).
_MATCH_MIN_RMS = 0.006

# --- word-agnostic candidate shape (AP-27) ---
# An offline model cannot SPELL an arbitrary wake word, and no spelling threshold separates genuine
# calls from chatter. The SHAPE of what the free ear heard at the span does (a call is short and
# stands alone); bounds derive from the configured phrase, never its spelling. ``sound_confirm``
# stays accept-only, so this cannot make the detector deaf.
_SHAPE_MAX_VOICED_S_PER_TOKEN = 0.65
_SHAPE_MAX_OTHER_WORD_CONF = 0.98

# A bare interjection ("hey ho") is also short and isolated, and no similarity floor rejects it.
# Ask instead whether anything NAME-SIZED (>= one syllable) was voiced once prefixes are stripped.
_SHAPE_MIN_CORE_BODY_S = 0.20
# No slack: the free ear may not hear more words than the phrase has (slack let room speech in).
_SHAPE_TOKEN_SLACK = 0

# --- three-way shape verdict (AP-27) ---
# Token count and the confidence veto assume spelling behaviour (accent re-tokenisation, names
# that are ordinary words), so they only mark a candidate UNDECIDED for the acoustic competition.
# The two duration questions stay HARD rejections: they measure how much sound, never what.
SHAPE_WAKE = "wake"            # looks like a call — competition confirms as before
SHAPE_UNDECIDED = "undecided"  # tokenisation/confidence contradicts — competition decides
SHAPE_SPEECH = "speech"        # too much sound, or no name-sized body: never a wake

# The former "leading isolation" gate was REMOVED by maintainer mandate: the wake word must fire
# mid- or end-of-sentence; precision comes from the span-trimmed competition instead.

# --- acoustic competition for the SHAPE path ---
# Every "<prefix> <other name>" call has the shape of a wake call, and no spelling rule may reject
# it (AP-27). A shape-only acceptance must beat a "<prefix> [unk]" alternative; the spelling path
# stays accept-only. Gating the whole verify on it cost 13 % of genuine recall.
_COMPETITION_KIND = "competition"


def _grammar_json(alternatives: list[str]) -> str:
    """JSON grammar list for libvosk, non-ASCII kept literal (no u-escape decoding)."""
    return json.dumps(alternatives, ensure_ascii=False)


# Ring buffer length for the confirm pass (phrase plus lead-in).
_RING_SECONDS = 3.0

# Trailing cut for the second re-score (embedded wakes); runs only when the full-ring one failed.
_RESCORE_TAIL_S = 1.8

# Refractory period after a fired wake.
_COOLDOWN_S = 5.0

# Reject-only backoff bounding verify work (a 99-verify storm starved the desktop); stage one
# keeps listening and latches one retry, so an immediate second call is not lost.
_REJECTED_CANDIDATE_BACKOFF_S = 2.0
_INFERENCE_SHUTDOWN_BUDGET_S = 0.02

# Audio to let land after a PARTIAL before the confirm (a truncated utterance halved recall).
_CONFIRM_TAIL_S = 0.6

# --- stage-1 CPU budget ---
# When ``_STAGE1_SLOW_CALLS`` of the last ``_STAGE1_RT_WINDOW`` stage-1 calls decode slower than
# ``_STAGE1_SLOW_RT`` x the audio they covered, the LAST secondary model is demoted from stage 1
# (still loaded for verify/rescue). 2.0 separates keeping up (~0.8x) from overloaded (2.3x+).
_STAGE1_SLOW_RT = 2.0
_STAGE1_SLOW_CALLS = 4
_STAGE1_RT_WINDOW = 8

def _folded(text: str) -> str:
    return " ".join(sound_fold(t) for t in normalize_phrase_for_match(text))


def sound_confirm(free_text: str, phrase: str, *, ratio: float = _CONFIRM_RATIO) -> bool:
    """True when the free transcript supports the phrase.

    A known prefix at the candidate position plus a sound-close core (stricter without a prefix);
    the core may use one extra/fewer token. Empty text rejects.
    """
    if not free_text:
        return False
    phrase_tokens = normalize_phrase_for_match(phrase)
    core_tokens = phrase_core_for_match(phrase)
    if not phrase_tokens or not core_tokens:
        return False

    words = [sound_fold(t) for t in normalize_phrase_for_match(free_text)]
    target_core = "".join(sound_fold(t) for t in core_tokens)
    if not words or not target_core:
        return False

    prefix_count = len(phrase_tokens) - len(core_tokens)
    has_prefix = prefix_count > 0
    known_prefixes = {sound_fold(token) for token in WAKE_PREFIXES}
    core_token_count = max(1, len(core_tokens))
    core_sizes = range(max(1, core_token_count - 1), core_token_count + 2)
    core_floor = max(
        float(ratio),
        _PREFIXED_CORE_RATIO if has_prefix else _UNPREFIXED_CORE_RATIO,
    )

    for start in range(len(words)):
        if has_prefix:
            heard_prefix = words[start]
            if heard_prefix not in known_prefixes:
                continue
            core_start = start + 1
        else:
            core_start = start

        for size in core_sizes:
            core_end = core_start + size
            if core_end > len(words):
                continue
            heard_core = "".join(words[core_start:core_end])
            if _spells_core(target_core, heard_core, core_floor):
                return True

    # Recall rescue for an ASR-garbled prefix; exact local token coverage keeps a mere mention out.
    if has_prefix:
        target_phrase = " ".join(sound_fold(token) for token in phrase_tokens)
        for size in core_sizes:
            if len(words) != 1 + size:
                continue
            heard_core = "".join(words[1:])
            core_score = SequenceMatcher(None, target_core, heard_core).ratio()
            heard_phrase = " ".join(words)
            phrase_score = SequenceMatcher(
                None, target_phrase, heard_phrase
            ).ratio()
            if (
                core_score >= max(float(ratio), _GARBLED_PREFIX_CORE_RATIO)
                and phrase_score >= _GARBLED_PREFIX_PHRASE_RATIO
            ):
                return True

        # One token may hold the merged phrase; require separate prefix AND core evidence.
        if len(words) == 1:
            heard = words[0]
            target_prefix = "".join(
                sound_fold(token) for token in phrase_tokens[:prefix_count]
            )
            target_merged = "".join(sound_fold(token) for token in phrase_tokens)
            length_ratio = len(heard) / max(1, len(target_merged))
            if (
                _MERGED_MIN_LENGTH_RATIO
                <= length_ratio
                <= _MERGED_MAX_LENGTH_RATIO
                and SequenceMatcher(None, target_prefix, heard).ratio()
                >= _MERGED_PREFIX_RATIO
                and SequenceMatcher(None, target_core, heard).ratio()
                >= _MERGED_CORE_RATIO
                and SequenceMatcher(None, target_merged, heard).ratio()
                >= _MERGED_PHRASE_RATIO
            ):
                return True
    return False


def candidate_shape_verdict(
    local_words: Sequence[dict],
    phrase: str,
    *,
    max_voiced_s_per_token: float = _SHAPE_MAX_VOICED_S_PER_TOKEN,
    max_other_word_conf: float = _SHAPE_MAX_OTHER_WORD_CONF,
    min_core_body_s: float = _SHAPE_MIN_CORE_BODY_S,
    span: tuple[float, float] | None = None,
) -> str:
    """Does the free ear's output AT the candidate span look like a wake call? Word-agnostic.

    Returns ``SHAPE_SPEECH`` (HARD reject), ``SHAPE_UNDECIDED`` (token count or confidence
    contradict; the acoustic competition decides) or ``SHAPE_WAKE``. ``span`` clips durations to
    the phrase's own audio so an embedded wake is not charged for its neighbours.
    """
    if not local_words:
        return SHAPE_SPEECH

    def _voiced(w: dict) -> float:
        start = float(w.get("start", 0.0))
        end = float(w.get("end", 0.0))
        if span is not None:
            start = max(start, span[0])
            end = min(end, span[1])
        return max(0.0, end - start)

    n_tokens = max(1, len(normalize_phrase_for_match(phrase)))
    voiced_s = sum(_voiced(w) for w in local_words)
    if voiced_s > max_voiced_s_per_token * n_tokens:
        return SHAPE_SPEECH
    # A confident known prefix is expected evidence; apply the confidence check to the core only.
    known_prefixes = {sound_fold(p) for p in WAKE_PREFIXES}
    phrase_tokens = normalize_phrase_for_match(phrase)
    phrase_is_all_prefix = all(
        sound_fold(t) in known_prefixes for t in phrase_tokens
    )
    core_words = [
        w
        for w in local_words
        if sound_fold(str(w.get("word", ""))) not in known_prefixes
    ]
    confidence_words = local_words if phrase_is_all_prefix else core_words
    if not confidence_words:
        return SHAPE_SPEECH
    # A phrase that is only prefixes has no core to demand.
    if not phrase_is_all_prefix:
        core_body_s = sum(_voiced(w) for w in core_words)
        if core_body_s < min_core_body_s:
            return SHAPE_SPEECH
    contested = len(local_words) > n_tokens + _SHAPE_TOKEN_SLACK
    top_conf = max(float(w.get("conf", 0.0)) for w in confidence_words)
    if top_conf > max_other_word_conf:
        contested = True
    return SHAPE_UNDECIDED if contested else SHAPE_WAKE


def candidate_shape_ok(
    local_words: Sequence[dict],
    phrase: str,
    *,
    max_voiced_s_per_token: float = _SHAPE_MAX_VOICED_S_PER_TOKEN,
    max_other_word_conf: float = _SHAPE_MAX_OTHER_WORD_CONF,
    min_core_body_s: float = _SHAPE_MIN_CORE_BODY_S,
    span: tuple[float, float] | None = None,
) -> bool:
    """True only for an UNCONTESTED wake shape (see ``candidate_shape_verdict``)."""
    return candidate_shape_verdict(
        local_words,
        phrase,
        max_voiced_s_per_token=max_voiced_s_per_token,
        max_other_word_conf=max_other_word_conf,
        min_core_body_s=min_core_body_s,
        span=span,
    ) == SHAPE_WAKE


class _StreamingVerify:
    """The authoritative confirm's decode, paid DURING the confirm tail.

    Both one-shot recognizers start on the ring at partial time and eat each tail chunk, so only
    ``FinalResult`` remains at tail end. One single-worker executor per recognizer (AP-24).
    """

    def __init__(
        self,
        model_path: str | None,
        grammar_rec: Any,
        free_rec: Any,
        ring: np.ndarray,
        *,
        target_peak: float,
        max_gain: float,
    ) -> None:
        self.model_path = model_path
        self._grammar = grammar_rec
        self._free = free_rec
        peak = float(np.max(np.abs(ring))) if len(ring) else 0.0
        self._gain = min(target_peak / peak, max_gain) if peak > 1e-6 else 1.0
        self._parts: list[np.ndarray] = []
        self._pcm_parts: list[bytes] = []
        self._g_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vosk-verify-grammar"
        )
        self._f_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vosk-verify-free"
        )
        self._pending: list[Any] = []
        self._closed = False
        self.feed(ring)

    def _normalise(self, audio: np.ndarray) -> tuple[np.ndarray, bytes]:
        window = np.clip(audio * self._gain, -1.0, 1.0)
        return window, (window * 32767.0).astype(np.int16).tobytes()

    def feed(self, audio: np.ndarray) -> None:
        """Queue more audio (float32 [-1, 1]) for both recognizers, in order."""
        if not len(audio):
            return
        window, pcm = self._normalise(audio)
        self._parts.append(window)
        self._pcm_parts.append(pcm)
        # A failed feed surfaces in finish() via the stored futures.
        self._pending.append(self._g_pool.submit(self._grammar.AcceptWaveform, pcm))
        self._pending.append(self._f_pool.submit(self._free.AcceptWaveform, pcm))

    def finish(self) -> tuple[np.ndarray, bytes, dict, dict]:
        """Finalize both decodes: (window, pcm, grammar_json, free_json). Blocking; may raise."""
        try:
            for fut in self._pending:
                fut.result()
            self._g_pool.shutdown(wait=True)
            self._f_pool.shutdown(wait=True)
            gres = _parse_recognizer_json(
                self._grammar.FinalResult(), where="verify.grammar_final"
            )
            fres = _parse_recognizer_json(
                self._free.FinalResult(), where="verify.free_final"
            )
        finally:
            self.close()
        window = np.concatenate(self._parts) if self._parts else np.zeros(0, np.float32)
        return window, b"".join(self._pcm_parts), gres, fres

    def close(self, *, wait: bool = False) -> None:
        """Discard (early fire, superseded candidate, teardown)."""
        self._closed = True
        self._g_pool.shutdown(wait=wait, cancel_futures=True)
        self._f_pool.shutdown(wait=wait, cancel_futures=True)

    @property
    def ready_to_reap(self) -> bool:
        """A closed decoder with no running feeds can be joined off-loop."""
        return self._closed and all(future.done() for future in self._pending)


class VoskKwsProvider:
    """Any-word wake detector, structurally compatible with `WakeWordProvider`."""

    name = "vosk_kws"

    # Catch-up contract with the pipeline fanout: a lagging detector may be fed a coalesced chunk
    # of up to this many seconds (a time budget, not a chunk count).
    coalesce_catchup_s = 1.0
    # How far behind live audio the fanout may let this detector fall before dropping the OLDEST
    # frames (a hole in the ring is heard as ''); honoured only with the catch-up above.
    intake_backlog_s = _RING_SECONDS

    def __init__(
        self,
        phrase: str,
        model_path: str,
        *,
        # All model dirs to listen on (primary first); each streams its own grammar.
        model_paths: Sequence[str] | None = None,
        keyword: str | None = None,
        sample_rate: int = 16_000,
        min_final_conf: float = _MIN_FINAL_CONF,
        confirm_ratio: float = _CONFIRM_RATIO,
        match_min_rms: float = _MATCH_MIN_RMS,
        cooldown_s: float = _COOLDOWN_S,
        rejected_candidate_backoff_s: float = _REJECTED_CANDIDATE_BACKOFF_S,
        confirm_tail_s: float = _CONFIRM_TAIL_S,
        # Peak-normalize the confirm window like the other wake paths (-3 dBFS, gain cap 40 dB).
        target_peak: float = 0.7079,
        max_gain: float = 100.0,
        # Early-verify visual side effect: True on a strict pass, False on retraction. No text.
        early_candidate_listener: Callable[[bool], Awaitable[None]] | None = None,
    ) -> None:
        self._phrase = phrase.strip()
        self._keyword = keyword or "_".join(normalize_phrase_for_match(phrase)) or "wake"
        self._model_path = model_path
        paths = [p for p in (model_paths or ()) if p]
        if model_path and model_path not in paths:
            paths.insert(0, model_path)
        self._model_paths: list[str] = paths or [model_path]
        self._sample_rate = sample_rate
        self._min_final_conf = float(min_final_conf)
        phrase_tokens = normalize_phrase_for_match(self._phrase)
        core_tokens = phrase_core_for_match(self._phrase)
        has_prefix = len(core_tokens) < len(phrase_tokens)
        structural_floor = (
            _PREFIXED_CORE_RATIO if has_prefix else _UNPREFIXED_CORE_RATIO
        )
        self._confirm_ratio = max(float(confirm_ratio), structural_floor)
        # Competition grammar for shape-only acceptances (None without a prefix).
        raw_tokens = [t for t in self._phrase.lower().split() if t]
        self._competition_grammar: str | None = None
        if has_prefix and raw_tokens:
            self._competition_grammar = _grammar_json(
                [self._phrase.lower(), f"{raw_tokens[0]} [unk]", "[unk]"]
            )
        # One-shot flag for the static-competition warning in ``_shape_competition_ok``.
        self._warned_static_competition = False
        # Set once ``SetGrammar`` raised: the competition then builds a recognizer per candidate.
        self._grammar_swap_broken = False
        self._match_min_rms = float(match_min_rms)
        self._cooldown_s = float(cooldown_s)
        self._rejected_candidate_backoff_s = max(
            0.0, float(rejected_candidate_backoff_s)
        )
        self._confirm_tail_bytes = int(float(confirm_tail_s) * sample_rate) * 2
        self._target_peak = float(target_peak)
        self._max_gain = float(max_gain)
        self._models: dict[str, Any] = {}
        # Guards the model CACHE only (never an inference); avoids double-loading a sibling model.
        self._model_load_lock = threading.Lock()
        # Set once ``start()`` has attempted every model load.
        self._load_attempted = False
        # Pre-warmed ONE-SHOT verify recognizers keyed (model_path, kind); each is used once, never
        # shared or reused (adaptation survives Reset(), AP-24). Empty stock means a cold build.
        self._rec_stock: dict[tuple[str, str], list[Any]] = {}
        self._stock_lock = threading.Lock()
        self._stock_target = 2
        self._replenish_task: asyncio.Task[None] | None = None
        self._grammar_words = [w for w in self._phrase.lower().split() if w]
        # Duck-typing parity with OpenWakeWordProvider (the pipeline's ready log reads these).
        self._keywords = (self._keyword,)
        self._threshold = self._confirm_ratio
        # Ring buffer of raw int16 PCM bytes for the confirm pass.
        self._ring: deque[bytes] = deque()
        self._ring_len = 0
        self._ring_max = int(_RING_SECONDS * sample_rate) * 2  # bytes
        # Early-candidate state; the generation counter drops late completions.
        self._early_listener = early_candidate_listener
        self._early_active = False
        self._early_task: asyncio.Task[bool] | None = None
        self._pending_gen = 0
        self._detect_guard = threading.Lock()
        self._inference_reaper: threading.Thread | None = None
        self._inference_cleanup: asyncio.Task[None] | None = None
        # Instance-local clock hook keeps backpressure tests deterministic.
        self._monotonic = time.monotonic
        # Session stats (parity with OpenWakeWordProvider.stats()).
        self._stat_chunks = 0
        self._stat_candidates = 0
        self._stat_gated_rms = 0
        self._stat_suppressed_confirm = 0
        self._stat_suppressed_cooldown = 0
        self._stat_backpressure_windows = 0
        self._stat_backpressure_chunks = 0
        self._stat_fired = 0
        self._stat_early_shown = 0
        self._stat_early_retracted = 0
        self._stat_suppressed_shape_competition = 0
        # Verify path accounting (streamed vs from-scratch).
        self._stat_verify_streamed = 0
        self._stat_verify_scratch = 0
        self._stat_verify_stream_fallback = 0
        # Stage-1 CPU budget: active model paths and recent realtime factors; reset per detect().
        self._stage1_paths: list[str] = list(self._model_paths)
        self._stage1_rt: deque[float] = deque(maxlen=_STAGE1_RT_WINDOW)
        self._last_stage1_cost: tuple[float, float] = (0.0, 0.0)
        self._stat_stage1_demoted = 0
        # Rate limiter for verify-suppression logs: the first few, then every Nth.
        self._suppress_log_count = 0
        self._reported_unusable: set[tuple[str, str]] = set()

    # -- lifecycle -----------------------------------------------------------

    def _ensure_model(self, path: str | None = None) -> Any:
        key = path or self._model_path
        model = self._models.get(key)
        if model is not None:
            return model
        # Double-checked: the fast path stays lock-free; only the actual load serialises.
        with self._model_load_lock:
            model = self._models.get(key)
            if model is not None:
                return model
            vosk = import_vosk()  # lazy: keep base import light

            vosk.SetLogLevel(-1)
            t0 = time.perf_counter()
            model = vosk.Model(key)
            self._models[key] = model
            log.info(
                "vosk-kws: model loaded in %.1f s (%s)",
                time.perf_counter() - t0,
                key,
            )
        return model

    def _new_grammar_rec(self, path: str | None = None) -> Any:
        grammar = _grammar_json([self._phrase.lower(), "[unk]"])
        return build_recognizer(
            self._ensure_model(path), self._sample_rate, grammar
        )

    def _build_verify_rec(self, path: str | None, kind: str, *, prewarm: bool) -> Any:
        """A fresh one-shot verify recognizer, optionally silence-prewarmed."""
        if kind == "grammar":
            rec = self._new_grammar_rec(path)
        elif kind == _COMPETITION_KIND:
            if self._competition_grammar is None:  # unprefixed phrase
                rec = self._new_grammar_rec(path)
            else:
                rec = build_recognizer(
                    self._ensure_model(path),
                    self._sample_rate,
                    self._competition_grammar,
                )
        else:
            rec = build_recognizer(self._ensure_model(path), self._sample_rate)
        if prewarm:
            try:
                silence = np.zeros(
                    int(0.3 * self._sample_rate), dtype=np.int16
                ).tobytes()
                rec.AcceptWaveform(silence)
                rec.FinalResult()
                rec.Reset()
            except Exception as exc:  # noqa: BLE001 — cold rec still works
                log.debug("vosk-kws: prewarm skipped (%s/%s): %s", path, kind, exc)
        return rec

    def _take_verify_rec(self, path: str | None, kind: str) -> Any:
        """Pop a prewarmed one-shot recognizer, or build cold; the taker uses it ONCE (AP-24)."""
        key = (path or self._model_path, kind)
        with self._stock_lock:
            stack = self._rec_stock.get(key)
            if stack:
                return stack.pop()
        return self._build_verify_rec(path, kind, prewarm=False)

    def _replenish_stock(self, target: int | None = None) -> None:
        """Top the prewarmed stock up to target (worker thread only); boot uses depth 1."""
        limit = self._stock_target if target is None else target
        # Every phrase stocks the competition kind (unprefixed phrases compete too).
        kinds = ("grammar", "free", _COMPETITION_KIND)
        for path in self._model_paths:
            for kind in kinds:
                key = (path, kind)
                while True:
                    with self._stock_lock:
                        if len(self._rec_stock.setdefault(key, [])) >= limit:
                            break
                    try:
                        rec = self._build_verify_rec(path, kind, prewarm=True)
                    except Exception as exc:  # noqa: BLE001 — broken model:
                        # takers fall back to cold builds which fail the same
                        # way and are handled at the verify layer.
                        log.debug(
                            "vosk-kws: stock replenish failed (%s/%s): %s",
                            path, kind, exc,
                        )
                        break
                    with self._stock_lock:
                        self._rec_stock[key].append(rec)

    def _kick_replenish(self) -> None:
        """Fire-and-forget stock top-up off the hot path (needs a loop)."""
        if self._replenish_task is not None and not self._replenish_task.done():
            return
        with contextlib.suppress(RuntimeError):  # no running loop (sync tests)
            asyncio.get_running_loop()
            self._replenish_task = asyncio.create_task(
                asyncio.to_thread(self._replenish_stock)
            )

    def _fresh_recs(self) -> dict[str, Any]:
        """One streaming grammar recognizer per ACTIVE stage-1 model path (prewarmed)."""
        recs: dict[str, Any] = {}
        for path in self._stage1_paths:
            try:
                recs[path] = self._take_verify_rec(path, "grammar")
            except Exception as exc:  # noqa: BLE001 — isolate a broken model
                # Called after every candidate reset: report each distinct
                # failure once instead of flooding the log (#1045).
                failure = (path, str(exc))
                if failure not in self._reported_unusable:
                    self._reported_unusable.add(failure)
                    log.warning("vosk-kws: model %s unusable (%s) — skipped.", path, exc)
        self._kick_replenish()
        return recs

    @property
    def is_warm(self) -> bool:
        """True once every model directory has finished loading (or the load was tried)."""
        if self._load_attempted:
            return True
        return all(path in self._models for path in self._model_paths)

    async def start(self) -> None:
        """Pre-load every model concurrently and fill the prewarmed stock; never breaks boot."""
        async def _load_one(path: str) -> None:
            try:
                await asyncio.to_thread(self._ensure_model, path)
            except Exception as exc:  # noqa: BLE001 — a broken model must not
                # brick the working ones; _fresh_recs skips it too.
                log.warning("vosk-kws: model %s failed to load (%s).", path, exc)

        await asyncio.gather(*(_load_one(path) for path in self._model_paths))
        self._load_attempted = True
        # Await depth ONE per (model, kind) so the first verify runs warm; the rest tops up later.
        await asyncio.to_thread(self._replenish_stock, 1)
        self._kick_replenish()

    async def stop(self) -> None:
        # Invalidate any in-flight early check and retract a shown candidate.
        self._pending_gen += 1
        if self._early_task is not None:
            self._early_task.cancel()
            self._early_task = None
        await self._notify_early(False)
        if self._replenish_task is not None:
            self._replenish_task.cancel()
            self._replenish_task = None
        with self._stock_lock:
            self._rec_stock.clear()
        self._models.clear()
        self._load_attempted = False
        self._ring.clear()
        self._ring_len = 0

    def stats(self) -> dict[str, int]:
        return {
            "chunks": self._stat_chunks,
            "candidates": self._stat_candidates,
            "gated_rms": self._stat_gated_rms,
            "suppressed_confirm": self._stat_suppressed_confirm,
            "suppressed_cooldown": self._stat_suppressed_cooldown,
            "backpressure_windows": self._stat_backpressure_windows,
            "backpressure_chunks": self._stat_backpressure_chunks,
            "fired": self._stat_fired,
            "early_shown": self._stat_early_shown,
            "early_retracted": self._stat_early_retracted,
            "suppressed_shape_competition": (
                self._stat_suppressed_shape_competition
            ),
            "verify_streamed": self._stat_verify_streamed,
            "verify_scratch": self._stat_verify_scratch,
            "verify_stream_fallback": self._stat_verify_stream_fallback,
            "stage1_models": len(self._stage1_paths),
            "stage1_demoted": self._stat_stage1_demoted,
        }

    # -- stage-1 CPU budget ----------------------------------------------------

    def _note_stage1_cost(self, decode_s: float, audio_s: float) -> bool:
        """Record one stage-1 call's realtime factor; True when a model was demoted.

        Demotes the LAST active secondary, never the primary. Reset per ``detect()`` session.
        """
        if audio_s <= 0.0:
            return False
        self._stage1_rt.append(decode_s / audio_s)
        if len(self._stage1_paths) <= 1:
            return False
        if len(self._stage1_rt) < _STAGE1_RT_WINDOW:
            return False
        slow = sum(1 for rt in self._stage1_rt if rt > _STAGE1_SLOW_RT)
        if slow < _STAGE1_SLOW_CALLS:
            return False
        demoted = self._stage1_paths.pop()
        self._stage1_rt.clear()
        self._stat_stage1_demoted += 1
        log.warning(
            "vosk-kws: stage-1 cannot keep up on this CPU (%d of the last %d "
            "decodes ran slower than %.1fx realtime) — demoting %s from the "
            "streaming stage; %d model(s) keep listening, the demoted one "
            "stays available for verify. Restored on the next wake session.",
            slow,
            _STAGE1_RT_WINDOW,
            _STAGE1_SLOW_RT,
            demoted,
            len(self._stage1_paths),
        )
        return True

    # -- early candidate (visual-only) ----------------------------------------

    def set_early_candidate_listener(
        self, listener: Callable[[bool], Awaitable[None]] | None
    ) -> None:
        """Wire/unwire the visual candidate listener after construction."""
        self._early_listener = listener

    @property
    def early_candidate_active(self) -> bool:
        """Whether a shown early candidate is currently outstanding."""
        return self._early_active

    def consume_early_candidate(self) -> bool:
        """Hand the shown-candidate state to the pipeline (reset, no event)."""
        was_shown = self._early_active
        self._early_active = False
        return was_shown

    async def _notify_early(self, active: bool) -> None:
        if self._early_listener is None or active == self._early_active:
            return
        self._early_active = active
        if active:
            self._stat_early_shown += 1
        else:
            self._stat_early_retracted += 1
        try:
            await self._early_listener(active)
        except Exception as exc:  # noqa: BLE001 — a UI listener error must
            # never break wake detection.
            log.debug("early-candidate listener failed: %s", exc)

    async def _run_early_check(
        self, window: np.ndarray, gen: int, model_path: str | None,
        run_verify: Callable[..., Awaitable[Any]],
    ) -> bool:
        """Strictly verify the candidate prefix and optionally show the bar; True is final."""
        try:
            ok = await run_verify(self._early_check, window, model_path)
        except Exception as exc:  # noqa: BLE001 — fallback verify remains
            log.debug("early-candidate check errored: %s", exc)
            return False
        if not ok or gen != self._pending_gen:
            return False
        log.info("vosk-kws: candidate prefix verified for %r", self._phrase)
        await self._notify_early(True)
        return True

    # -- internals -----------------------------------------------------------

    def _ring_push(self, pcm: bytes) -> None:
        self._ring.append(pcm)
        self._ring_len += len(pcm)
        while self._ring_len > self._ring_max and self._ring:
            dropped = self._ring.popleft()
            self._ring_len -= len(dropped)

    def _ring_window(self) -> np.ndarray:
        if not self._ring:
            return np.empty(0, dtype=np.float32)
        raw = b"".join(self._ring)
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    def _grammar_hit(self, rec: Any, pcm: bytes) -> tuple[bool, float] | None:
        """Feed one chunk; return (is_final, min_conf) on a phrase hit else None."""
        if rec.AcceptWaveform(pcm):
            res = _parse_recognizer_json(rec.Result(), where="grammar_hit.Result")
            text = res.get("text", "")
            if self._phrase.lower() in text:
                words = [
                    w for w in res.get("result", [])
                    if w.get("word") in self._grammar_words
                ]
                conf = min((w.get("conf", 0.0) for w in words), default=0.0)
                return (True, conf)
            return None
        partial = _parse_recognizer_json(
            rec.PartialResult(), where="grammar_hit.PartialResult"
        ).get("partial", "")
        if partial and self._phrase.lower() in partial:
            return (False, 1.0)  # partials carry no conf; the confirm decides
        return None

    def _log_suppression(self, reason: str, *args: Any) -> None:
        """Report a verify rejection at INFO for the first few, then every 20th."""
        self._suppress_log_count += 1
        n = self._suppress_log_count
        if n <= 5 or n % 20 == 0:
            log.info("vosk-kws: verify SUPPRESSED (#%d) — " + reason, n, *args)
        else:
            log.debug("vosk-kws: verify SUPPRESSED — " + reason, *args)

    def _grammar_hit_all(
        self, recs: dict[str, Any], pcm: bytes
    ) -> tuple[bool, float, str] | None:
        """Feed one chunk to EVERY model's grammar in one thread hop; the first hit wins."""
        t0 = time.perf_counter()
        hit: tuple[bool, float] | None = None
        hit_path = ""
        for path, rec in recs.items():
            found = self._grammar_hit(rec, pcm)
            if found is not None and hit is None:
                hit, hit_path = found, path
        self._last_stage1_cost = (
            time.perf_counter() - t0,
            len(pcm) / (2.0 * self._sample_rate),
        )
        if hit is None:
            return None
        return (hit[0], hit[1], hit_path)

    async def _stage1(
        self,
        recs: dict[str, Any],
        pcm: bytes,
        _in_pool: Callable[..., Awaitable[Any]],
    ) -> tuple[tuple[bool, float, str] | None, dict[str, Any]]:
        """Feed one chunk to stage 1 off the loop and apply the CPU budget.

        Surviving recognizers are KEPT, never rebuilt (that lost the "Hey" already decoded).
        """
        self._last_stage1_cost = (0.0, 0.0)
        found = await _in_pool(self._grammar_hit_all, recs, pcm)
        if self._note_stage1_cost(*self._last_stage1_cost):
            active = set(self._stage1_paths)
            recs = {path: rec for path, rec in recs.items() if path in active}
        return found, recs

    def _verify_candidate(
        self, window: np.ndarray, model_path: str | None = None
    ) -> bool:
        """Authoritative confirm, fails OPEN; ``model_path`` is the model that HEARD the hit."""
        self._stat_verify_scratch += 1
        return self._verify_window(window, fail_open=True, model_path=model_path)

    def _early_check(
        self, window: np.ndarray, model_path: str | None = None
    ) -> bool:
        """Strict prefix verify on the truncated ring, fails CLOSED."""
        try:
            return self._verify_window(
                window, fail_open=False, model_path=model_path
            )
        except Exception:  # noqa: BLE001 — belt and braces for the UI path
            return False

    def _start_streaming_verify(
        self, ring: np.ndarray, model_path: str | None
    ) -> _StreamingVerify | None:
        """Begin the authoritative confirm's decode at PARTIAL time; None if it cannot be built."""
        try:
            grammar = self._take_verify_rec(model_path, "grammar")
            free = self._take_verify_rec(model_path, "free")
            return _StreamingVerify(
                model_path,
                grammar,
                free,
                ring,
                target_peak=self._target_peak,
                max_gain=self._max_gain,
            )
        except Exception as exc:  # noqa: BLE001 — fall back to from-scratch
            log.debug("vosk-kws: streaming verify unavailable (%s)", exc)
            return None

    def _finish_streaming_verify(
        self, streaming: _StreamingVerify, fallback_window: np.ndarray
    ) -> bool:
        """Authoritative confirm over the streamed decode, fails OPEN (errors re-run it)."""
        try:
            decoded = streaming.finish()
        except Exception as exc:  # noqa: BLE001 — degrade to from-scratch
            self._stat_verify_stream_fallback += 1
            log.warning(
                "vosk-kws: streamed confirm failed (%s) — re-running the "
                "from-scratch confirm.",
                exc,
            )
            return self._verify_candidate(fallback_window, streaming.model_path)
        self._stat_verify_streamed += 1
        return self._judge_decoded(
            decoded, fail_open=True, model_path=streaming.model_path
        )

    def _verify_window(
        self,
        window: np.ndarray,
        *,
        fail_open: bool,
        model_path: str | None = None,
    ) -> bool:
        """Four checks over the window; ALL must pass before a fire.

        1. Grammar re-score re-hears the phrase as a FINAL (conf gate) and yields its time span.
        2. Word-agnostic RMS floor over that span (AP-27).
        3. Localised sound confirm over free-decode words overlapping the span (+-0.3 s).
        4. Span-trimmed acoustic competition (shape/undecided acceptances only).

        On infrastructure errors ``fail_open`` decides: the confirm accepts, the early check
        rejects. Grammar and free decodes run concurrently, each with its own recognizer (AP-24).
        """
        try:
            decoded = self._decode_window(window, model_path)
        except Exception as exc:  # noqa: BLE001 — polarity via fail_open
            log.warning(
                "vosk-kws: verify failed (%s) — %s.",
                exc,
                "accepting" if fail_open else "rejecting (visual-only)",
            )
            return fail_open
        return self._judge_decoded(decoded, fail_open=fail_open, model_path=model_path)

    def _decode_window(
        self, window: np.ndarray, model_path: str | None
    ) -> tuple[np.ndarray, bytes, dict, dict]:
        """Peak-normalise ``window`` and run grammar + free passes; raises on infra errors."""
        peak = float(np.max(np.abs(window))) if len(window) else 0.0
        if peak > 1e-6:
            window = np.clip(
                window * min(self._target_peak / peak, self._max_gain), -1.0, 1.0
            )
        pcm = (window * 32767.0).astype(np.int16).tobytes()

        # Grammar re-score (real confidence + time span) and free decode run concurrently.
        def _grammar_pass() -> dict:
            g = self._take_verify_rec(model_path, "grammar")
            g.AcceptWaveform(pcm)
            return _parse_recognizer_json(
                g.FinalResult(), where="verify.grammar_final"
            )

        def _free_pass() -> dict:
            f = self._take_verify_rec(model_path, "free")
            f.AcceptWaveform(pcm)
            return _parse_recognizer_json(
                f.FinalResult(), where="verify.free_final"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            grammar_future = pool.submit(_grammar_pass)
            free_future = pool.submit(_free_pass)
            gres = grammar_future.result()
            fres = free_future.result()
        return window, pcm, gres, fres

    def _judge_decoded(
        self,
        decoded: tuple[np.ndarray, bytes, dict, dict],
        *,
        fail_open: bool,
        model_path: str | None,
    ) -> bool:
        """Checks 1-4 of ``_verify_window`` over an already-decoded window."""
        window, pcm, gres, fres = decoded
        try:
            def _rescored(res: dict, offset_s: float) -> tuple[list[dict], float] | None:
                """The best CONSECUTIVE phrase-token run in a grammar decode (in order)."""
                tokens = self._grammar_words
                result = [w for w in res.get("result", []) if isinstance(w, dict)]
                best: tuple[list[dict], float] | None = None
                for i in range(len(result) - len(tokens) + 1):
                    run = result[i : i + len(tokens)]
                    if [w.get("word") for w in run] != tokens:
                        continue
                    run_conf = min(float(w.get("conf", 0.0)) for w in run)
                    if run_conf < self._min_final_conf:
                        continue
                    if best is None or run_conf > best[1]:
                        best = (run, run_conf)
                if best is None:
                    return None
                words, min_conf = best
                if offset_s:
                    words = [
                        {
                            **w,
                            "start": float(w.get("start", 0.0)) + offset_s,
                            "end": float(w.get("end", 0.0)) + offset_s,
                        }
                        for w in words
                    ]
                return words, min_conf

            scored = _rescored(gres, 0.0)
            if scored is None:
                # Embedded-wake retry: a mid-/end-of-sentence wake is absorbed into "[unk]"s over
                # the full ring, so re-score the trailing cut (extra candidates die downstream).
                tail_samples = int(_RESCORE_TAIL_S * self._sample_rate)
                if len(window) > tail_samples:
                    offset_s = (len(window) - tail_samples) / self._sample_rate
                    pcm_tail = pcm[2 * (len(window) - tail_samples):]

                    def _tail_pass() -> dict:
                        g = self._take_verify_rec(model_path, "grammar")
                        g.AcceptWaveform(pcm_tail)
                        return _parse_recognizer_json(
                            g.FinalResult(), where="verify.grammar_tail"
                        )

                    scored = _rescored(_tail_pass(), offset_s)
            if scored is None:
                self._log_suppression(
                    "re-score did not re-hear %r reliably (heard %r)",
                    self._phrase, gres.get("text", "")[:60],
                )
                return False
            gwords, conf = scored
            start_s = min(w.get("start", 0.0) for w in gwords)
            end_s = max(w.get("end", 0.0) for w in gwords)
            span_a = start_s - 0.3
            span_b = end_s + 0.3

            # 2) word-agnostic energy over the phrase span
            a = max(0, int(span_a * self._sample_rate))
            b = min(len(window), int(span_b * self._sample_rate))
            segment = window[a:b] if b > a else window
            rms = float(np.sqrt(np.mean(segment * segment) + 1e-12)) if len(segment) else 0.0
            if rms < self._match_min_rms:
                self._stat_gated_rms += 1
                self._log_suppression(
                    "span rms %.4f < %.4f (silence can never fire)",
                    rms, self._match_min_rms,
                )
                return False

            # Localise the free words to the phrase span (the spelling path keeps +-0.3 s slack).
            local_words = [
                w for w in fres.get("result", [])
                if w.get("end", 0.0) >= span_a and w.get("start", 0.0) <= span_b
            ]
            free_local = " ".join(w.get("word", "") for w in local_words)

            # Span-trimmed audio (+-0.3 s) so surrounding speech cannot help the alignment fake.
            pcm_span = pcm[2 * a : 2 * b] if b > a else pcm
            # OPEN: a wake spoken in one breath with the command fires less often (a command word in
            # the trailing slack breaks the token bound). Narrowing the window costs precision, so
            # calibrate on the recorded corpora before changing it.
        except Exception as exc:  # noqa: BLE001 — polarity via fail_open
            log.warning(
                "vosk-kws: verify failed (%s) — %s.",
                exc,
                "accepting" if fail_open else "rejecting (visual-only)",
            )
            return fail_open
        # Two independent confirms: (a) the free ear spelled the phrase; (b) it could not, but the
        # SHAPE is a wake call. (a) alone ate 38 % of real wakes (OOV names); (b) alone accepts a
        # different name's call, so shape-only acceptances must also win the acoustic competition.
        ok = sound_confirm(free_local, self._phrase, ratio=self._confirm_ratio)
        shape = (
            ""
            if ok
            else candidate_shape_verdict(
                local_words, self._phrase, span=(start_s, end_s)
            )
        )
        if not ok and shape in (SHAPE_WAKE, SHAPE_UNDECIDED):
            ok = self._shape_competition_ok(
                pcm_span,
                model_path,
                free_hypothesis=free_local,
                fail_open=fail_open,
            )
            if not ok:
                self._stat_suppressed_shape_competition += 1
        if ok:
            log.info(
                "vosk-kws: verify OK (%s) — free ear heard %r at the candidate "
                "span (conf=%.2f) vs phrase %r",
                "spelled" if not shape else shape,
                free_local[:60],
                conf,
                self._phrase,
            )
        elif fail_open:
            # The authoritative confirm reports its rejections; the early check rejects by design.
            self._log_suppression(
                "free ear heard %r at the span (re-score conf %.2f, shape=%s) — "
                "neither spelled nor sounded like a call of %r",
                free_local[:60],
                conf,
                shape or "n/a",
                self._phrase,
            )
        else:
            log.debug(
                "vosk-kws: early check rejected — free ear heard %r (shape=%s) "
                "vs phrase %r",
                free_local[:60],
                shape or "n/a",
                self._phrase,
            )
        return ok

    def _competition_rec(self, model_path: str | None, grammar: str) -> Any:
        """A one-shot recognizer that judges exactly *grammar* (JSON list).

        If ``SetGrammar`` raises (some macOS wheels lack the native export), build the recognizer
        with the alternatives: a fail-open there would confirm every candidate.
        """
        if not self._grammar_swap_broken:
            rec = self._take_verify_rec(model_path, _COMPETITION_KIND)
            set_grammar = getattr(rec, "SetGrammar", None)
            if not callable(set_grammar):
                if not getattr(self, "_warned_static_competition", False):
                    # Warn once: the static grammar is a measurably weaker judge.
                    self._warned_static_competition = True
                    log.warning(
                        "vosk-kws: this recognizer offers no SetGrammar — the "
                        "acoustic competition runs on its static grammar only "
                        "(weaker precision; vosk >= 0.3.32 restores it)."
                    )
                return rec
            try:
                set_grammar(grammar)
            except Exception as exc:  # noqa: BLE001 — any failed swap rebuilds
                self._grammar_swap_broken = True
                log.warning(
                    "vosk-kws: this vosk build cannot swap a recognizer's "
                    "grammar (%s) — the acoustic competition builds its "
                    "recognizer per candidate instead.",
                    exc,
                )
            else:
                return rec
        return self._build_competition_rec(model_path, grammar)

    def _build_competition_rec(self, model_path: str | None, grammar: str) -> Any:
        """A cold recognizer constructed WITH the per-candidate grammar."""
        return build_recognizer(
            self._ensure_model(model_path), self._sample_rate, grammar
        )

    def _shape_competition_ok(
        self,
        pcm: bytes,
        model_path: str | None,
        free_hypothesis: str = "",
        *,
        fail_open: bool = True,
    ) -> bool:
        """Must the shape-only acceptance stand? Purely acoustic.

        Re-scores the SPAN-TRIMMED ``pcm`` against the phrase, "<prefix> [unk]", the free ear's own
        hypothesis and "[unk]". Errors answer ``fail_open`` (confirm accepts, early check rejects).
        """
        alternatives = [self._phrase.lower()]
        raw_tokens = [t for t in self._phrase.lower().split() if t]
        if self._competition_grammar is not None and raw_tokens:
            alternatives.append(f"{raw_tokens[0]} [unk]")
        hypothesis = " ".join(free_hypothesis.lower().split())
        if hypothesis and hypothesis != self._phrase.lower():
            alternatives.append(hypothesis)
        alternatives.append("[unk]")
        try:
            rec = self._competition_rec(model_path, _grammar_json(alternatives))
            rec.AcceptWaveform(pcm)
            res = json.loads(rec.FinalResult())
            if self._phrase.lower() not in res.get("text", ""):
                log.debug(
                    "vosk-kws: shape acceptance lost the acoustic competition "
                    "— competitor grammar heard %r, not %r",
                    res.get("text", "")[:60],
                    self._phrase,
                )
                return False
            words = [
                w for w in res.get("result", [])
                if w.get("word") in self._grammar_words
            ]
            conf = min((w.get("conf", 0.0) for w in words), default=0.0)
            if conf < self._min_final_conf:
                log.debug(
                    "vosk-kws: shape acceptance lost the acoustic competition "
                    "— re-heard %r only at conf %.2f",
                    self._phrase,
                    conf,
                )
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — polarity via fail_open
            log.warning(
                "vosk-kws: shape competition errored (%s) — %s.",
                exc,
                "accepting" if fail_open else "rejecting (visual-only)",
            )
            return fail_open

    # -- detection loop --------------------------------------------------------

    async def detect(self, chunks: AsyncIterator[AudioChunk]) -> AsyncIterator[str]:
        """Consume audio chunks, yield the keyword on a confirmed hit (after the full verify)."""
        # Reserved pool for the always-on ear (the shared default executor can starve it). Size 2,
        # never 1: a wedged native inference would deafen it permanently (AP-24).
        if not self._detect_guard.acquire(blocking=False):
            raise RuntimeError("The previous wake detector is still running or retiring")
        infer_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="vosk-wake-infer"
        )
        # Verification gets its own pool so it never queues behind app workers.
        verify_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="vosk-wake-confirm"
        )
        loop = asyncio.get_running_loop()
        streams: set[_StreamingVerify] = set()
        stream_lock = threading.Lock()

        def invoke(fn: Callable[..., Any], args: tuple[Any, ...]) -> Any:
            # Release finished decoder pairs on a worker, never joining native work on the loop.
            with stream_lock:
                finished = [stream for stream in streams if stream.ready_to_reap]
                streams.difference_update(finished)
            for stream in finished:
                stream.close(wait=True)
            result = fn(*args)
            if isinstance(result, _StreamingVerify):
                # Register before the future publishes so cancellation cannot hide a decoder pair.
                with stream_lock:
                    streams.add(result)
            return result

        async def _run(pool: ThreadPoolExecutor, fn: Callable[..., Any], *args: Any) -> Any:
            future = pool.submit(invoke, fn, args)
            wrapped = asyncio.wrap_future(future)
            try:
                return await wrapped
            except asyncio.CancelledError:
                # Pending obsolete work must never occupy a verifier slot.
                # Running native work remains owned by the retirement thread.
                future.cancel()

                def consume_late(done: Any) -> None:
                    if done.cancelled():
                        return
                    exc = done.exception()
                    if exc is not None:
                        log.debug("Cancelled wake inference finished with %s", type(exc).__name__)
                future.add_done_callback(consume_late)
                raise

        async def _in_pool(fn: Callable[..., Any], *args: Any) -> Any:
            return await _run(infer_pool, fn, *args)

        async def _verify_pool(fn: Callable[..., Any], *args: Any) -> Any:
            return await _run(verify_pool, fn, *args)

        inner = self._detect_inner(chunks, _in_pool, _verify_pool)
        try:
            async for keyword in inner:
                yield keyword
        finally:
            try:
                await inner.aclose()
            finally:
                self._pending_gen += 1
                early, self._early_task = self._early_task, None
                if early is not None:
                    early.cancel()
                retired = loop.create_future()

                def notify_retired() -> None:
                    if not retired.done():
                        retired.set_result(None)

                def reap() -> None:
                    try:
                        infer_pool.shutdown(wait=True, cancel_futures=True)
                        verify_pool.shutdown(wait=True, cancel_futures=True)
                        # Both owning pools have joined; no constructor can add a stream now.
                        for streaming in streams:
                            streaming.close(wait=True)
                    except Exception:
                        # Retain the guard when retirement cannot be confirmed.
                        log.exception("Wake inference retirement failed")
                    else:
                        self._detect_guard.release()
                    finally:
                        try:
                            loop.call_soon_threadsafe(notify_retired)
                        except RuntimeError:
                            # The loop may close first; this thread still joined
                            # the native workers and owns their last references.
                            pass

                async def retire() -> None:
                    # Finish coroutine cancellation before joining workers (shield survives).
                    try:
                        if early is not None:
                            await asyncio.gather(early, return_exceptions=True)
                    finally:
                        reaper = threading.Thread(
                            target=reap, name="vosk-wake-retire", daemon=True,
                        )
                        self._inference_reaper = reaper
                        reaper.start()
                    await retired

                cleanup = asyncio.create_task(retire(), name="vosk-wake-retirement")
                self._inference_cleanup = cleanup
                try:
                    await asyncio.wait_for(
                        asyncio.shield(cleanup), timeout=_INFERENCE_SHUTDOWN_BUDGET_S,
                    )
                except TimeoutError:
                    log.warning("Wake inference is still retiring; detector re-entry is blocked")

    async def _detect_inner(
        self,
        chunks: AsyncIterator[AudioChunk],
        _in_pool: Callable[..., Awaitable[Any]],
        _verify_pool: Callable[..., Awaitable[Any]],
    ) -> AsyncIterator[str]:
        """The detection loop proper; ``_in_pool`` runs native decode work."""
        for path in self._model_paths:
            try:
                await _in_pool(self._ensure_model, path)
            except Exception as exc:  # noqa: BLE001 — skip a broken model
                log.warning("vosk-kws: model %s failed to load (%s).", path, exc)
        # One streaming grammar per installed model (phrase language may differ from the speaker).
        self._stage1_paths = list(self._model_paths)
        self._stage1_rt.clear()
        recs = self._fresh_recs()
        # Start each session with an EMPTY ring: after a fire it still held the wake call, so the
        # next session's first candidate re-heard the phrase and fired again.
        self._ring.clear()
        self._ring_len = 0
        last_fire_t = 0.0
        verify_not_before = 0.0
        # Pending candidate: a PARTIAL waits ``confirm_tail_s`` more audio; ``hit_path`` = model.
        pending: tuple[bool, float, str] | None = None
        pending_tail = 0
        # Confirm of the pending PARTIAL, decoding during the tail; None for finals/latched ones.
        streaming: _StreamingVerify | None = None

        def _drop_streaming() -> None:
            nonlocal streaming
            if streaming is not None:
                streaming.close()
                streaming = None

        try:
            async for chunk in chunks:
                self._stat_chunks += 1
                pcm = chunk.pcm
                self._ring_push(pcm)
                # After a clean rejection full verification is rate-limited but stage one keeps
                # listening: one candidate is latched and verified at the deadline.
                now_mono = self._monotonic()
                backpressure_active = now_mono < verify_not_before
                if backpressure_active:
                    self._stat_backpressure_chunks += 1
                if not recs:
                    recs = self._fresh_recs()
                if pending is not None:
                    pending_tail += len(pcm)
                    if streaming is not None:
                        # The tail belongs to the candidate's confirm: feed the streaming decoders.
                        streaming.feed(
                            np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                            / 32768.0
                        )
                    # Keep every model's stream fed during the wait so decode state stays aligned.
                    found, recs = await self._stage1(recs, pcm, _in_pool)
                    if backpressure_active:
                        if found is not None:
                            # A NEWER hit refreshes the latch (the old one used to hold the slot
                            # while the real wake went unheard); still ONE verify at the deadline.
                            is_final_new, _conf_new, _path_new = found
                            pending = found
                            pending_tail = (
                                self._confirm_tail_bytes if is_final_new else 0
                            )
                            _drop_streaming()  # belonged to the superseded one
                        continue
                    # A positive early check is authoritative: fire as soon as it lands, else the
                    # tail wait and full-window verify decide.
                    early_positive = (
                        self._early_task is not None
                        and self._early_task.done()
                        and not self._early_task.cancelled()
                        and self._early_task.exception() is None
                        and self._early_task.result() is True
                    )
                    if pending_tail < self._confirm_tail_bytes and not early_positive:
                        continue
                    is_final, conf, hit_path = pending
                    pending = None
                else:
                    # Feed every active model; the first hit wins the slot (one thread hop).
                    found, recs = await self._stage1(recs, pcm, _in_pool)
                    if found is None:
                        continue
                    is_final, conf, hit_path = found
                    now = time.time()
                    if now - last_fire_t < self._cooldown_s:
                        self._stat_suppressed_cooldown += 1
                        recs = self._fresh_recs()
                        continue
                    self._stat_candidates += 1
                    if backpressure_active:
                        # Retain one candidate without launching a decode.
                        pending = (is_final, conf, hit_path)
                        pending_tail = self._confirm_tail_bytes if is_final else 0
                        continue
                    if is_final and conf < self._min_final_conf:
                        self._stat_backpressure_windows += 1
                        verify_not_before = (
                            self._monotonic() + self._rejected_candidate_backoff_s
                        )
                        recs = self._fresh_recs()
                        continue
                    if not is_final and self._confirm_tail_bytes > 0:
                        pending = (is_final, conf, hit_path)
                        pending_tail = 0
                        ring_now = self._ring_window()
                        # Start the confirm's decode now (before the early check) so the deciding
                        # path has warm recognizers; built off the loop (a cold one costs ~0.3 s).
                        streaming = await _in_pool(
                            self._start_streaming_verify, ring_now, hit_path
                        )
                        # Verify the audio so far during the tail; a negative falls through.
                        self._pending_gen += 1
                        self._early_task = asyncio.create_task(
                            self._run_early_check(
                                ring_now, self._pending_gen, hit_path, _verify_pool,
                            )
                        )
                        continue
                # One decoder pair at a time on a weak CPU; a positive prefix verdict is monotonic.
                early_confirmed = False
                if self._early_task is not None:
                    try:
                        early_confirmed = bool(await self._early_task)
                    except Exception as exc:  # noqa: BLE001 — fallback verify remains
                        log.debug(
                            "candidate-prefix task failed; using full-window fallback: %s",
                            exc,
                        )
                    finally:
                        self._early_task = None
                now = time.time()
                window = self._ring_window()
                fired_path = hit_path
                if early_confirmed:
                    confirmed = True
                    _drop_streaming()
                    log.info(
                        "vosk-kws: retaining verified candidate prefix for %r; "
                        "following audio belongs to the voice session",
                        self._phrase,
                    )
                elif streaming is not None:
                    # The decode already ran during the tail; this is finalize + judgement.
                    finishing, streaming = streaming, None
                    confirmed = await _verify_pool(
                        self._finish_streaming_verify, finishing, window
                    )
                else:
                    confirmed = await _verify_pool(
                        self._verify_candidate, window, hit_path
                    )
                if not confirmed:
                    # Sibling rescue: every other loaded model (even a demoted one) tries the window
                    # concurrently; the first in configured order wins. Fail-CLOSED via _early_check
                    # so a broken sibling never fires a wake.
                    others = [
                        other
                        for other in self._model_paths
                        if other != hit_path and other in self._models
                    ]
                    if others:
                        rescues = await asyncio.gather(
                            *(
                                _verify_pool(self._early_check, window, other)
                                for other in others
                            )
                        )
                        for other, rescued in zip(others, rescues, strict=True):
                            if rescued:
                                confirmed = True
                                fired_path = other
                                break
                if not confirmed:
                    self._stat_suppressed_confirm += 1
                    # Invalidate this generation and retract stale visual state.
                    self._pending_gen += 1
                    await self._notify_early(False)
                    self._stat_backpressure_windows += 1
                    verify_not_before = (
                        self._monotonic() + self._rejected_candidate_backoff_s
                    )
                    if (
                        self._stat_backpressure_windows == 1
                        or self._stat_backpressure_windows % 25 == 0
                    ):
                        log.warning(
                            "vosk-kws: rejected-candidate backpressure active "
                            "(pause %.1fs, windows=%d, skipped_chunks=%d) — "
                            "protecting desktop responsiveness.",
                            self._rejected_candidate_backoff_s,
                            self._stat_backpressure_windows,
                            self._stat_backpressure_chunks,
                        )
                    # Re-arm one cheap streaming set; at most one retry latches before the deadline.
                    recs = self._fresh_recs()
                    continue
                # The shown flag stays set so the pipeline can retract the bar if it drops the wake.
                self._pending_gen += 1
                self._stat_fired += 1
                last_fire_t = now
                log.info(
                    "vosk-kws: WAKE fired for %r (%s candidate, model %s)",
                    self._phrase,
                    "final" if is_final else "partial",
                    fired_path,
                )
                yield self._keyword
                recs = self._fresh_recs()
        finally:
            # A confirm still decoding at teardown must not keep its workers or recognizers alive.
            _drop_streaming()


def vosk_model_supports_phrase(model_path: str, phrase: str) -> bool:
    """True when every core word of ``phrase`` is in the model lexicon (fail-open, never raises).

    Vosk silently drops out-of-vocabulary grammar words, warning only on stderr, so capture that
    at the OS fd level around a throwaway build. Off the boot path (loads the model, ~1.5 s).
    """
    core = phrase_core_for_match(phrase)
    if not core:
        return False
    import contextlib
    import os
    import tempfile

    try:
        vosk = import_vosk()
    except Exception:  # noqa: BLE001 — no vosk → cannot disprove support
        return True
    KaldiRecognizer, Model, SetLogLevel = (  # noqa: N806 — vosk API names
        vosk.KaldiRecognizer,
        vosk.Model,
        vosk.SetLogLevel,
    )
    tmp = None
    old = None
    try:
        SetLogLevel(0)  # surface the OOV warning the app normally hides
        tmp = tempfile.TemporaryFile(mode="w+")
        old = os.dup(2)
        os.dup2(tmp.fileno(), 2)
        native_call(
            KaldiRecognizer,
            Model(model_path),
            16_000,
            _grammar_json([phrase.lower(), "[unk]"]),
        )
    except Exception:  # noqa: BLE001 — probe failure must not reject a real word
        return True
    finally:
        if old is not None:
            with contextlib.suppress(Exception):
                os.dup2(old, 2)
                os.close(old)
        SetLogLevel(-1)  # restore the app's quiet default
    tmp.seek(0)
    return "missing in vocabulary" not in tmp.read().lower()


__all__ = [
    "SHAPE_SPEECH",
    "SHAPE_UNDECIDED",
    "SHAPE_WAKE",
    "VoskKwsProvider",
    "candidate_shape_ok",
    "candidate_shape_verdict",
    "sound_confirm",
    "vosk_model_supports_phrase",
]
