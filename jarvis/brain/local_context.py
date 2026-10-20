"""Context-window honesty for local model servers.

A hosted model declares its window and refuses a request that exceeds it. A
local server does neither reliably: Ollama serves a small default window unless
one is baked into the model, LM Studio loads whatever context length the load
dialog holds, llama.cpp and vLLM take theirs from the command line — and several
of them cut an oversized prompt from the front without an error. The system
prompt and the first tool schemas are what goes missing, so the model answers
without ever having seen the tools it was offered.

Three layers keep that from happening silently:

1. **Know the window.** :func:`probe_server_window` asks an OpenAI-compatible
   server what it actually runs (never what the model could run). The Ollama
   brain sets its own and verifies it against ``/api/ps``.
2. **Refuse before sending.** :func:`ensure_fits` raises
   :class:`LocalContextError` when a request certainly exceeds a known window.
   The message names the size needed and where to change it.
3. **Notice afterwards.** A server that tells nothing is judged by what it
   reports having read (:func:`judge_reported_prompt`). That signal is a
   suspicion: it needs two responses in a row, it only tightens the next
   turn's budget, and it lapses by itself.

Only the two local brains call into this module. The brain manager imports the
marker constant to classify the error and nothing else, so no hosted provider
or subscription runs any of it.

Pure helpers plus one small process-level registry; no I/O at import time
(AP-26).
"""

from __future__ import annotations

import itertools
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

log = logging.getLogger(__name__)

__all__ = [
    "LOCAL_CONTEXT_MARKER",
    "LocalContextError",
    "ServerWindow",
    "certain_tokens",
    "ensure_fits",
    "fix_hint",
    "forget_window",
    "is_overflow_refusal",
    "judge_reported_prompt",
    "known_window",
    "known_window_for_model",
    "probe_server_window",
    "recommended_window",
    "refusal_error",
    "remember_window",
    "reported_prompt_tokens",
    "reset_registry",
    "truncation_suspected",
]

#: Stable wording the brain manager classifies on. Never reword without
#: updating ``_classify_provider_error`` in ``jarvis/brain/manager.py``.
LOCAL_CONTEXT_MARKER: Final[str] = "local context window too small"

# Token counts in these sentences are written WITHOUT thousands separators.
# Several classifiers in this app read a free-standing three-digit group as an
# HTTP status: "18,401 tokens" was recorded as a rejected key and "65,536" as an
# unreachable server. A run of digits has no such group.

#: Chars per token for the "certainly too large" check. Deliberately high:
#: real tokenizers land between 3 and 4.5 chars per token on this app's
#: prompts, so a request that exceeds the window even at 4 does not fit.
_CERTAIN_CHARS_PER_TOKEN: Final[int] = 4
#: Chars per token for the upper estimate, the same figure the brain manager
#: budgets tools with.
_BUDGET_CHARS_PER_TOKEN: Final[int] = 3
#: The least an image costs on any current vision model. A lower bound on
#: purpose: the certain check must never refuse a picture that would fit.
_IMAGE_TOKENS_MIN: Final[int] = 256
#: Keys under which a content block carries encoded bytes rather than text.
_BINARY_KEYS: Final[frozenset[str]] = frozenset({"data", "b64_json", "image_base64", "bytes"})

#: A response that reports less than this share of the upper estimate read a
#: shortened prompt. Honest tokenizers report 65 % or more of that estimate.
_TRUNCATION_RATIO: Final[float] = 0.5
#: Below this size the ratio is noise.
_TRUNCATION_MIN_ESTIMATE: Final[int] = 4_000
#: A truncated prompt still fills a real window; a small count is a server
#: that reports only the tokens it newly evaluated after a cache hit.
_TRUNCATION_MIN_REPORTED: Final[int] = 2_000
#: Suspicious responses in a row before the budget is tightened.
_SUSPICIONS_NEEDED: Final[int] = 2

#: Windows a person can actually select, smallest first.
_WINDOW_STEPS: Final[tuple[int, ...]] = (8_192, 16_384, 32_768, 65_536, 131_072, 262_144)
#: Headroom on top of the prompt for the answer and the next tool round.
_RECOMMEND_HEADROOM: Final[float] = 1.25

#: How long a server's answer about its own window is trusted. Short, because
#: the fix for a too-small window is to reload the model and ask again.
_SERVER_TTL_S: Final[float] = 30.0
#: How long "this server tells nothing" is trusted.
_SILENT_TTL_S: Final[float] = 300.0
#: How long a window inferred from reported usage tightens the budget. It is a
#: suspicion, so it lapses by itself and has to be observed again.
_OBSERVED_TTL_S: Final[float] = 600.0

# Four small GETs against the user's own server; a dead port must not hold a
# turn, and a live one answers a status route at once.
_PROBE_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(connect=1.0, read=2.0, write=2.0, pool=2.0)

_FIX_HINTS: Final[dict[str, str]] = {
    "ollama": (
        "Open Local Models, choose Tune for this model and set the context "
        "length to at least {tokens} tokens."
    ),
    "lm-studio": (
        "In LM Studio, open this model's load settings, raise Context Length "
        "to at least {tokens} and reload the model."
    ),
    "llama.cpp": "Restart llama-server with --ctx-size {tokens} (short form: -c {tokens}).",
    "vllm": (
        "Restart vLLM with --max-model-len {tokens}, or serve a model whose own "
        "limit is at least that large."
    ),
    "tgi": "Restart the server with --max-total-tokens {tokens} or more.",
    "unknown": (
        "Raise the context length of the loaded model in your local server to "
        "at least {tokens} tokens (LM Studio: model load settings, Context "
        "Length; llama.cpp: --ctx-size; vLLM: --max-model-len), then ask again."
    ),
}

#: Wordings with which a local server refuses an oversized request.
_OVERFLOW_REFUSALS: Final[tuple[str, ...]] = (
    "exceeds the available context size",
    "exceed_context_size",
    "context_length_exceeded",
    "maximum context length",
    "context length exceeded",
    "prompt is too long",
)


class LocalContextError(RuntimeError):
    """A request does not fit the window a local server really runs.

    ``truncated``: the server had already cut the prompt when this was
    noticed. ``refused``: the server rejected the request itself; its own
    count includes the reply allowance, so the sentence then does not claim a
    prompt size that might be below the window.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        needed_tokens: int,
        window_tokens: int,
        how_to_fix: str,
        truncated: bool = False,
        refused: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.needed_tokens = needed_tokens
        self.window_tokens = window_tokens
        self.how_to_fix = how_to_fix
        self.truncated = truncated
        self.refused = refused
        name = model or "the model"
        runs = f"with {window_tokens} tokens" if window_tokens > 0 else "with too little context"
        if refused:
            body = (
                f"{provider} runs {name} {runs} and refused this request as too large "
                f"(a prompt of about {needed_tokens} tokens plus room for the reply)."
            )
        else:
            lead = "the server cut this request short" if truncated else "this request was not sent"
            body = (
                f"{provider} runs {name} {runs} and the request needs about "
                f"{needed_tokens}, so {lead}."
            )
        super().__init__(f"{LOCAL_CONTEXT_MARKER.capitalize()}: {body} {how_to_fix}")


@dataclass(frozen=True, slots=True)
class ServerWindow:
    """What a server said about the context it runs ``model`` with."""

    tokens: int
    #: ``lm-studio`` | ``llama.cpp`` | ``vllm`` | ``tgi``.
    kind: str


@dataclass(slots=True)
class _Entry:
    tokens: int
    #: ``server`` (the server said so) | ``plan`` (what this app asked the
    #: server to run) | ``observed`` (inferred from reported usage).
    source: str
    kind: str
    at: float
    #: Insertion order; the clock is too coarse to order two records.
    seq: int = 0


_REGISTRY: dict[tuple[str, str, str], _Entry] = {}
_SILENT_ROOTS: dict[str, float] = {}
_SUSPICIONS: dict[tuple[str, str, str], int] = {}
_SEQUENCE = itertools.count(1)


# ── Request size ─────────────────────────────────────────────────────────


def _text_chars(value: Any) -> int:
    """Characters of TEXT in a content block, encoded bytes left out.

    A block may carry a screenshot as base64; counting that as prose would
    refuse an image turn outright.
    """
    if isinstance(value, str):
        return 0 if value.startswith("data:") else len(value)
    if isinstance(value, dict):
        return sum(
            _text_chars(item)
            for key, item in value.items()
            if not (key in _BINARY_KEYS and isinstance(item, str))
        )
    if isinstance(value, (list, tuple)):
        return sum(_text_chars(item) for item in value)
    return len(str(value)) if value is not None else 0


def _request_chars(req: Any) -> tuple[int, int]:
    """``(characters, images)`` a request puts on the wire."""
    chars = len(getattr(req, "system", None) or "")
    tools = getattr(req, "tools", None) or ()
    if tools:
        try:
            chars += len(json.dumps(list(tools), ensure_ascii=False, default=str))
        except (TypeError, ValueError):  # unserialisable schema: size its repr instead
            chars += len(str(tools))
    images = 0
    for message in getattr(req, "messages", None) or ():
        chars += _text_chars(getattr(message, "content", ""))
        images += len(getattr(message, "images", ()) or ())
    return chars, images


def certain_tokens(req: Any) -> int:
    """A LOWER estimate of the prompt: a request above it surely does not fit."""
    chars, images = _request_chars(req)
    return chars // _CERTAIN_CHARS_PER_TOKEN + images * _IMAGE_TOKENS_MIN


def _budget_tokens(req: Any) -> int:
    chars, images = _request_chars(req)
    return chars // _BUDGET_CHARS_PER_TOKEN + images * _IMAGE_TOKENS_MIN


def recommended_window(needed_tokens: int) -> int:
    """The smallest selectable window that holds ``needed_tokens`` with headroom."""
    target = int(needed_tokens * _RECOMMEND_HEADROOM)
    for step in _WINDOW_STEPS:
        if step >= target:
            return step
    return _WINDOW_STEPS[-1]


def fix_hint(kind: str, needed_tokens: int, *, ceiling: int | None = None) -> str:
    """One sentence that says where to raise the window, for this server kind.

    ``ceiling`` is the model's own window when known: a size above it cannot
    be set anywhere, so the sentence then says to pick another model.
    """
    wanted = recommended_window(needed_tokens)
    if ceiling and wanted > ceiling:
        return (
            f"This model's own window is {ceiling} tokens, which the request "
            "exceeds; choose a model with a larger context window."
        )
    template = _FIX_HINTS.get(kind) or _FIX_HINTS["unknown"]
    return template.format(tokens=wanted)


def ensure_fits(
    req: Any,
    window_tokens: int,
    *,
    provider: str,
    model: str,
    kind: str,
    ceiling: int | None = None,
    truncated: bool = False,
) -> None:
    """Raise :class:`LocalContextError` when ``req`` certainly exceeds the window.

    A window of ``0`` or less means "unknown" and never raises. The check uses
    the lower estimate on purpose: a borderline request is left to the server,
    which is the only party that can count it exactly.
    """
    if window_tokens <= 0:
        return
    needed = certain_tokens(req)
    if needed <= window_tokens:
        return
    raise LocalContextError(
        provider=provider,
        model=model,
        needed_tokens=needed,
        window_tokens=window_tokens,
        how_to_fix=fix_hint(kind, needed, ceiling=ceiling),
        truncated=truncated,
    )


def refusal_error(
    req: Any, *, provider: str, model: str, kind: str, window_tokens: int = 0
) -> LocalContextError:
    """The error for a request the SERVER rejected as too large."""
    needed = certain_tokens(req)
    return LocalContextError(
        provider=provider,
        model=model,
        needed_tokens=needed,
        window_tokens=window_tokens,
        # The server counted prompt plus reply, so the next window up from
        # the larger of the two figures is the one that helps.
        how_to_fix=fix_hint(kind, max(needed, window_tokens)),
        refused=True,
    )


def is_overflow_refusal(message: str) -> bool:
    """Whether a server's error text says the request was too large."""
    low = (message or "").lower()
    return any(marker in low for marker in _OVERFLOW_REFUSALS)


# ── What the server reported ─────────────────────────────────────────────


def reported_prompt_tokens(usage: dict[str, int] | None) -> int | None:
    """The whole prompt the server says it read, cached share included."""
    if not usage:
        return None
    try:
        total = int(usage.get("input_tokens", 0) or 0) + int(usage.get("cache_hit_tokens", 0) or 0)
    except (TypeError, ValueError):  # a malformed usage block reports nothing
        return None
    return total if total > 0 else None


def truncation_suspected(req: Any, reported: int | None) -> bool:
    """Whether the server read far less than was sent.

    A suspicion, not a proof: a server that reports only the tokens it newly
    evaluated after a prompt-cache hit looks the same. Callers therefore use
    this to tighten a budget, never to fail a turn.
    """
    if reported is None or reported < _TRUNCATION_MIN_REPORTED:
        return False
    estimate = _budget_tokens(req)
    if estimate < _TRUNCATION_MIN_ESTIMATE:
        return False
    return reported < estimate * _TRUNCATION_RATIO


def judge_reported_prompt(
    provider: str, root: str, model: str, req: Any, reported: int | None
) -> tuple[str, int]:
    """Decide what a response from a server that states no window means.

    Returns ``("tighten", tokens)`` when the server has now twice in a row
    read far less than it was sent — the next turn is then planned for what
    it demonstrably holds; ``("restore", 0)`` when a response disproves an
    earlier suspicion; ``("keep", 0)`` otherwise. One odd response changes
    nothing, and a recorded suspicion lapses after :data:`_OBSERVED_TTL_S`.
    """
    key = _key(provider, root, model)
    if reported is not None and truncation_suspected(req, reported):
        count = _SUSPICIONS.get(key, 0) + 1
        _SUSPICIONS[key] = count
        if count < _SUSPICIONS_NEEDED:
            return "keep", 0
        remember_window(provider, root, model, reported, source="observed")
        return "tighten", reported
    _SUSPICIONS.pop(key, None)
    known = known_window(provider, root, model)
    if known is not None and known[1] == "observed" and (reported or 0) > known[0]:
        forget_window(provider, root, model)
        return "restore", 0
    return "keep", 0


# ── Registry ─────────────────────────────────────────────────────────────


def _key(provider: str, root: str, model: str) -> tuple[str, str, str]:
    return provider, (root or "").rstrip("/"), (model or "").removesuffix(":latest")


def remember_window(
    provider: str, root: str, model: str, tokens: int, *, source: str, kind: str = "unknown"
) -> None:
    """Record the window ``model`` runs with on ``root``."""
    if tokens <= 0 or not model:
        return
    _REGISTRY[_key(provider, root, model)] = _Entry(
        tokens=int(tokens), source=source, kind=kind, at=time.monotonic(), seq=next(_SEQUENCE)
    )


def forget_window(provider: str, root: str, model: str) -> None:
    _REGISTRY.pop(_key(provider, root, model), None)


def _lapsed(entry: _Entry) -> bool:
    return entry.source == "observed" and time.monotonic() - entry.at > _OBSERVED_TTL_S


def known_window(provider: str, root: str, model: str) -> tuple[int, str, str] | None:
    """``(tokens, source, kind)`` recorded for this model, or ``None``."""
    key = _key(provider, root, model)
    entry = _REGISTRY.get(key)
    if entry is None:
        return None
    if _lapsed(entry):
        del _REGISTRY[key]
        return None
    return entry.tokens, entry.source, entry.kind


def known_window_for_model(provider: str, model: str) -> int | None:
    """The most recently recorded window of ``model`` on any server root.

    For a brain's constructor, which must publish a budget before it may touch
    the network or resolve an endpoint. A brain without a model has no record
    of its own, so an empty name answers ``None`` rather than some other
    model's window.
    """
    wanted = (model or "").removesuffix(":latest")
    if not wanted:
        return None
    best: _Entry | None = None
    for (prov, _root, name), entry in _REGISTRY.items():
        if prov != provider or name != wanted or _lapsed(entry):
            continue
        if best is None or entry.seq > best.seq:
            best = entry
    return best.tokens if best is not None else None


def reset_registry() -> None:
    """Forget every recorded window (tests, or a changed endpoint)."""
    _REGISTRY.clear()
    _SILENT_ROOTS.clear()
    _SUSPICIONS.clear()


# ── Asking an OpenAI-compatible server ───────────────────────────────────


def _positive(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _same_id(row_id: Any, model: str) -> bool:
    return bool(model) and str(row_id or "").strip() == model


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    resp = await client.get(url)
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:  # an HTML error page on this path means "not this server kind"
        return None


def _from_openai_models(payload: Any, model: str) -> ServerWindow | None:
    """vLLM publishes the limit it was started with as ``max_model_len``."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    for row in rows or ():
        if isinstance(row, dict) and _same_id(row.get("id"), model):
            tokens = _positive(row.get("max_model_len"))
            if tokens:
                return ServerWindow(tokens, "vllm")
    return None


def _from_lm_studio(payload: Any, model: str) -> ServerWindow | None:
    """LM Studio reports the context a model is LOADED with, per model."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    for row in rows or ():
        if not isinstance(row, dict) or not _same_id(row.get("id"), model):
            continue
        if str(row.get("state") or "").lower() != "loaded":
            # Not loaded yet: the first request loads it with the stored
            # setting, which this endpoint does not reveal in advance.
            return None
        tokens = _positive(row.get("loaded_context_length"))
        if tokens:
            return ServerWindow(tokens, "lm-studio")
    return None


def _from_llama_cpp(payload: Any) -> ServerWindow | None:
    """llama-server reports the per-slot context under ``/props``."""
    if not isinstance(payload, dict):
        return None
    settings = payload.get("default_generation_settings")
    tokens = _positive(settings.get("n_ctx")) if isinstance(settings, dict) else None
    return ServerWindow(tokens, "llama.cpp") if tokens else None


def _from_tgi(payload: Any) -> ServerWindow | None:
    if not isinstance(payload, dict):
        return None
    tokens = _positive(payload.get("max_total_tokens"))
    return ServerWindow(tokens, "tgi") if tokens else None


async def probe_server_window(
    root: str,
    model: str,
    *,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    fresh: bool = False,
) -> ServerWindow | None:
    """Ask an OpenAI-compatible server which context it runs ``model`` with.

    Answers only from what the server states about the RUNNING model; a
    model's native or maximum window is never taken for the running one.
    ``None`` means the server does not say. Results are cached briefly;
    ``fresh`` skips that cache (after the first token, when a server that
    loads on demand has just loaded the model). A server that stayed silent
    even then is left alone for :data:`_SILENT_TTL_S`, fresh or not, so no
    turn waits on a probe that cannot answer. Never raises.

    ``transport`` exists for tests (``httpx.MockTransport``).
    """
    root = (root or "").rstrip("/")
    now = time.monotonic()
    silent_since = _SILENT_ROOTS.get(root)
    if silent_since is not None and now - silent_since < _SILENT_TTL_S:
        return None
    if not fresh:
        hit = _REGISTRY.get(_key("local-openai", root, model))
        if hit is not None and hit.source == "server" and now - hit.at < _SERVER_TTL_S:
            return ServerWindow(hit.tokens, hit.kind)
    found: ServerWindow | None = None
    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT, transport=transport, headers=headers or {}
        ) as client:
            found = _from_openai_models(await _get_json(client, f"{root}/v1/models"), model)
            if found is None:
                found = _from_lm_studio(await _get_json(client, f"{root}/api/v0/models"), model)
            if found is None:
                found = _from_llama_cpp(await _get_json(client, f"{root}/props"))
            if found is None:
                found = _from_tgi(await _get_json(client, f"{root}/info"))
    except Exception as exc:  # noqa: BLE001 — a probe must never fail the turn it serves
        # An unreachable server is reported by the request itself, with a
        # better message than a probe could give.
        log.debug("local context: window probe failed at %s: %s", root, exc)
        return None
    if found is None:
        if fresh:
            # Asked while the model was demonstrably loaded and still got no
            # answer: this server does not publish its window.
            _SILENT_ROOTS[root] = now
        return None
    remember_window("local-openai", root, model, found.tokens, source="server", kind=found.kind)
    return found
