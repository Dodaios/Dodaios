"""Provider surface for the dictation polish pass: two adapters, six families.

Nothing branches on ``family.id``, only on ``transport`` (a wire format; AP-21).
The chain is credential-derived, one family per key, primary first (AP-22); no
key gives an empty chain and the raw transcript is delivered (AP-23). With an
on-device recognizer only on-device families are offered. httpx, google-genai
and the config model are imported lazily (AP-26).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: The wire formats an adapter exists for; the only thing code may branch on.
POLISH_TRANSPORTS: Final[tuple[str, ...]] = ("openai_chat", "gemini")

#: Hostnames that mean "this machine": the words never cross a network.
_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1"}
)

#: How long an unanswering on-device endpoint is left alone (below the
#: breaker's 120 s cooldown).
_LOCAL_REFUSAL_TTL_S: Final[float] = 60.0

#: How long a FAILED credential read is left alone, per slot (a locked keyring
#: is fixed by hand; one dictation must not pay it twice).
_SECRET_FAILURE_TTL_S: Final[float] = 10.0


@dataclass(frozen=True, slots=True)
class PolishFamily:
    """One credential family; empty ``secret_candidates`` marks a keyless local one."""

    id: str
    label: str
    transport: Literal["openai_chat", "gemini"]
    base_url: str
    secret_candidates: tuple[str, ...]
    default_model: str
    default_timeout_ms: int
    #: Model for the translating pass, or ``""`` for ``default_model``. A user
    #: ``polish_model`` pin still wins (see :func:`resolve_model`).
    translate_model: str = ""
    #: Provider card this family inherits its address from, or None.
    endpoint_provider: str | None = None

    @property
    def needs_key(self) -> bool:
        """Whether this family is reachable only with a credential."""
        return bool(self.secret_candidates)

    @property
    def effective_base_url(self) -> str:
        """The address this family is reached at now (follows its provider card)."""
        if not self.endpoint_provider:
            return self.base_url
        try:
            from dodaios.core import config as cfg  # noqa: PLC0415 — lazy (AP-26)
            from dodaios.plugins.brain.ollama import (  # noqa: PLC0415 — pure helpers
                default_server_root,
                normalize_server_root,
            )

            endpoint = cfg.resolve_provider_endpoint(
                self.endpoint_provider, vendor_default_base_url=default_server_root()
            )
            root = normalize_server_root(endpoint.base_url or default_server_root())
            return f"{root}/v1"
        except Exception:  # noqa: BLE001 — an unreadable config keeps the default
            log.debug(
                "polish: could not resolve the %s endpoint; using %s",
                self.endpoint_provider,
                self.base_url,
            )
            return self.base_url

    @property
    def runs_on_device(self) -> bool:
        """Whether this family's endpoint is on THIS machine (the EFFECTIVE address)."""
        host = (urlsplit(self.effective_base_url).hostname or "").strip().lower()
        return host in _LOOPBACK_HOSTS


#: Auto-selection order: time-to-first-token, cost, then likelihood the key is
#: already present. Ollama is keyless and never in the auto cloud order; it is
#: used when pinned or when the recognizer is on-device.
POLISH_FAMILIES: Final[tuple[PolishFamily, ...]] = (
    PolishFamily(
        id="groq",
        label="Groq",
        transport="openai_chat",
        base_url="https://api.groq.com/openai/v1",
        secret_candidates=("groq_api_key",),
        default_model="openai/gpt-oss-20b",
        # 120b keeps clauses that 20b drops in translation.
        translate_model="openai/gpt-oss-120b",
        default_timeout_ms=1200,
    ),
    PolishFamily(
        id="cerebras",
        label="Cerebras",
        transport="openai_chat",
        base_url="https://api.cerebras.ai/v1",
        secret_candidates=("cerebras_api_key",),
        # The only production model Cerebras lists.
        default_model="gpt-oss-120b",
        default_timeout_ms=1200,
    ),
    PolishFamily(
        id="gemini",
        label="Google Gemini",
        transport="gemini",
        base_url="https://generativelanguage.googleapis.com",
        secret_candidates=(
            "gemini_api_key",
            "google_aistudio_api_key",
            "google_api_key",
        ),
        default_model="gemini-3.5-flash-lite",
        translate_model="gemini-3.7-flash",
        default_timeout_ms=1500,
    ),
    PolishFamily(
        id="openai",
        label="OpenAI",
        transport="openai_chat",
        base_url="https://api.openai.com/v1",
        secret_candidates=("openai_api_key",),
        # Ids match ``dodaios.brain.model_catalog``.
        default_model="gpt-5.4-nano",
        translate_model="gpt-5.4-mini",
        default_timeout_ms=1500,
    ),
    PolishFamily(
        id="openrouter",
        label="OpenRouter",
        transport="openai_chat",
        base_url="https://openrouter.ai/api/v1",
        secret_candidates=("openrouter_api_key",),
        default_model="qwen/qwen3.7-flash",
        # One key reaches every family, so the tier is not vendor-bound.
        translate_model="google/gemini-3.7-flash",
        default_timeout_ms=1500,
    ),
    PolishFamily(
        id="ollama",
        label="Ollama (local)",
        transport="openai_chat",
        base_url="http://localhost:11434/v1",
        secret_candidates=(),
        default_model="qwen3.5:4b",
        default_timeout_ms=3000,
        endpoint_provider="ollama",
    ),
)

_FAMILY_BY_ID: Final[dict[str, PolishFamily]] = {f.id: f for f in POLISH_FAMILIES}


class PolishProviderError(RuntimeError):
    """A provider call failed in a way the caller may cross a family for."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class PolishClient(Protocol):
    """What the orchestrator needs from a provider: one bounded completion."""

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> str | None:
        """Return the model's text, or ``None`` when it produced nothing."""
        ...


def family_by_id(family_id: object) -> PolishFamily | None:
    """Look a family up by its id; ``None`` for anything unknown."""
    return _FAMILY_BY_ID.get(str(family_id or "").strip().lower())


def family_has_key(family: PolishFamily) -> bool:
    """Whether this host holds a usable credential for *family* (keyless: ``True``)."""
    if not family.needs_key:
        return True
    return _first_secret(family.secret_candidates) is not None


#: One resolved credential per keyring slot, tagged with the slot's revision.
_SECRET_MEMO: dict[str, tuple[int, str | None]] = {}

#: Slots whose lookup RAISED: ``slot -> (revision, deadline)``; expires.
_SECRET_FAILURES: dict[str, tuple[int, float]] = {}


def reset_credential_cache() -> None:
    """Forget every memoised credential, resolved or failed."""
    _SECRET_MEMO.clear()
    _SECRET_FAILURES.clear()


def _lookup_failed_recently(slot: str, revision: int) -> bool:
    """Whether reading *slot* raised so recently that retrying is pointless.

    A revision change invalidates at once.
    """
    entry = _SECRET_FAILURES.get(slot)
    if entry is None:
        return False
    failed_revision, deadline = entry
    if failed_revision != revision or time.monotonic() >= deadline:
        _SECRET_FAILURES.pop(slot, None)
        return False
    return True


def _first_secret(candidates: Sequence[str]) -> str | None:
    """First non-empty credential among *candidates*, or ``None``.

    Memoised (asked twice per dictation); config is imported here (AP-26).
    """
    from dodaios.core import config as _cfg

    for slot in candidates:
        revision = _cfg.secret_revision(slot)
        cached = _SECRET_MEMO.get(slot)
        if cached is not None and cached[0] == revision:
            value = cached[1]
        elif _lookup_failed_recently(slot, revision):
            # Raised moments ago; do not pay a blocking keyring twice.
            continue
        else:
            try:
                value = _cfg.get_secret(slot)
            except Exception as exc:  # noqa: BLE001 — a locked keyring must not break dictation
                _SECRET_FAILURES[slot] = (
                    revision,
                    time.monotonic() + _SECRET_FAILURE_TTL_S,
                )
                log.debug("polish credential lookup failed for %r: %s", slot, exc)
                continue
            # No lock: dict assignment is atomic; a race costs one extra read.
            _SECRET_MEMO[slot] = (revision, value)
        if value:
            return value
    return None


#: On-device endpoints that did not answer: ``family id -> deadline``.
_LOCAL_REFUSALS: dict[str, float] = {}


def reset_reachability_cache() -> None:
    """Forget which on-device endpoints were unreachable."""
    _LOCAL_REFUSALS.clear()


def note_family_failure(family: PolishFamily, exc: BaseException) -> None:
    """Remember an ON-DEVICE endpoint that did not answer (not one that refused)."""
    if not family.runs_on_device:
        return
    if isinstance(exc, PolishProviderError) and exc.status is not None:
        return
    _LOCAL_REFUSALS[family.id] = time.monotonic() + _LOCAL_REFUSAL_TTL_S
    log.debug(
        "polish family %r is on this machine and did not answer (%s); it will "
        "be skipped for %.0f s rather than dialled on every dictation.",
        family.id,
        exc,
        _LOCAL_REFUSAL_TTL_S,
    )


def family_recently_unreachable(family: PolishFamily) -> bool:
    """Whether *family* refused so recently that dialling it again is waste."""
    deadline = _LOCAL_REFUSALS.get(family.id)
    if deadline is None:
        return False
    if time.monotonic() >= deadline:
        _LOCAL_REFUSALS.pop(family.id, None)
        return False
    return True


def stt_runs_on_device() -> bool:
    """Whether the CONFIGURED recognizer transcribes on this machine.

    Fails closed: an unreadable config counts as on-device, since guessing
    "cloud" would upload words from someone who chose a local recognizer.
    """
    from dodaios.core import config as _cfg
    from dodaios.plugins.stt import provider_runs_on_device

    try:
        provider = str(getattr(_cfg.load_config().stt, "provider", "") or "")
    except Exception as exc:  # noqa: BLE001 — see the fail-closed note above
        log.warning(
            "dictation polish could not read the configured recognizer (%s); "
            "treating it as on-device and keeping the polish pass local.",
            exc,
        )
        return True
    return provider_runs_on_device(provider)


def polish_chain_fingerprint(cfg: Any) -> tuple[Any, ...]:
    """A cheap value that changes whenever :func:`resolve_polish_chain` could."""
    from dodaios.core import config as _cfg

    pin = str(getattr(cfg, "polish_provider", "auto") or "auto").strip().lower()
    revisions = tuple(
        _cfg.secret_revision(slot)
        for family in POLISH_FAMILIES
        for slot in family.secret_candidates
    )
    identity: tuple[int, int] | None = None
    try:
        info = _cfg.resolve_config_path().stat()
        identity = (info.st_mtime_ns, info.st_size)
    except OSError as exc:
        # A fresh clone has no config file at all, and an unreadable one is
        # somebody else's error to report. Either way the only consequence is
        # that the sweep runs again — slow, never wrong.
        log.debug("polish chain fingerprint has no config identity: %s", exc)
    return (pin, revisions, identity)


def resolve_polish_chain(cfg: Any) -> tuple[PolishFamily, ...]:
    """Key-aware, family-crossing provider order (AP-22); empty means raw text (AP-23).

    An on-device recognizer keeps the chain on-device (a usable cloud pin
    overrides). Otherwise the pin moves to the front and keyed families follow;
    an unknown pin is ignored. Keyless local families enter only by pin or under
    the on-device rule.
    """
    pin = str(getattr(cfg, "polish_provider", "auto") or "auto").strip().lower()
    pinned = family_by_id(pin) if pin not in ("", "auto") else None
    if pinned is None and pin not in ("", "auto"):
        log.debug(
            "polish provider pin %r is not a known family; using the auto order.", pin
        )

    if stt_runs_on_device():
        opted_in = (
            pinned is not None
            and not pinned.runs_on_device
            and family_has_key(pinned)
        )
        if not opted_in:
            local = tuple(f for f in POLISH_FAMILIES if f.runs_on_device)
            log.debug(
                "the configured recognizer transcribes on this machine, so the "
                "polish chain stays on it too: %s.",
                ", ".join(f.id for f in local) or "<no on-device family>",
            )
            return local

    chain: list[PolishFamily] = []
    if pinned is not None and family_has_key(pinned):
        chain.append(pinned)
    for family in POLISH_FAMILIES:
        if family in chain:
            continue
        # Keyless local families are reachable only as an explicit pin.
        if not family.needs_key:
            continue
        if family_has_key(family):
            chain.append(family)
    return tuple(chain)


def resolve_model(
    family: PolishFamily, cfg: Any, *, primary_id: str, translating: bool = False
) -> str:
    """The model id to use for *family* on this call.

    ``polish_model`` applies to the PRIMARY family only (model ids are
    family-specific). ``translating`` picks the family's translate tier, below
    the user's pin so their own setting is never silently overridden (AP-31).
    """
    if family.id == primary_id:
        pinned = str(getattr(cfg, "polish_model", "") or "").strip()
        if pinned:
            return pinned
    if translating and family.translate_model:
        return family.translate_model
    return family.default_model


# Transport adapters


class _SharedHttpClient:
    """One keep-alive ``httpx.AsyncClient`` for every OpenAI-compatible family.

    Avoids a TCP+TLS handshake per dictation; rebound when the running event
    loop changes (a client must not be reused across loops).
    """

    __slots__ = ("_client", "_loop")

    def __init__(self) -> None:
        self._client: Any | None = None
        self._loop: Any | None = None

    def get(self) -> Any:
        import asyncio

        import httpx

        loop = asyncio.get_running_loop()
        client = self._client
        if client is None or self._loop is not loop or client.is_closed:
            client = httpx.AsyncClient()
            self._client = client
            self._loop = loop
        return client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._loop = None
        if client is not None and not client.is_closed:
            try:
                await client.aclose()
            except Exception as exc:  # noqa: BLE001 — teardown must never raise
                log.debug("polish HTTP client close failed: %s", exc)


_HTTP = _SharedHttpClient()


async def aclose_shared_client() -> None:
    """Release the pooled HTTP client. Safe to call repeatedly."""
    await _HTTP.aclose()


class OpenAIChatPolishClient:
    """Adapter for every family speaking the OpenAI chat-completions schema."""

    __slots__ = ("_family", "_model", "_api_key")

    def __init__(self, family: PolishFamily, *, model: str, api_key: str | None) -> None:
        self._family = family
        self._model = model
        self._api_key = api_key

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> str | None:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "stream": False,
            # Spend the budget on visible text, not hidden reasoning; an
            # optional hint, dropped by the retry if the server rejects it.
            "reasoning_effort": "low",
        }
        data = await self._post(payload, timeout_s=timeout_s)
        _record_openai_usage(self._family.id, self._model, data.get("usage"))
        choices = data.get("choices") or []
        if not choices:
            return None
        choice = choices[0] or {}
        if choice.get("finish_reason") not in (None, "stop"):
            raise PolishProviderError("Rewrite did not finish normally")
        message = choice.get("message") or {}
        text = str(message.get("content") or "").strip()
        return text or None

    async def _post(self, payload: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
        """POST the payload, retrying ONCE after a 400 naming a field.

        The retry is driven by what the server said, not a provider allowlist
        (AP-21).
        """
        import httpx

        url = f"{self._family.effective_base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        client = _HTTP.get()

        for attempt in (0, 1):
            try:
                response = await client.post(
                    url, json=payload, headers=headers, timeout=timeout_s
                )
            except httpx.HTTPError as exc:
                raise PolishProviderError(
                    f"{self._family.label} polish request failed: {type(exc).__name__}"
                ) from exc
            if response.status_code < 400:
                return response.json()
            body = _safe_body(response)
            if attempt == 0 and response.status_code == 400:
                adjusted = _relax_payload(payload, body)
                if adjusted is not None:
                    payload = adjusted
                    continue
            raise PolishProviderError(
                f"{self._family.label} polish request returned "
                f"HTTP {response.status_code}",
                status=response.status_code,
                retry_after=_retry_after(response),
            )
        # Unreachable: both attempts return or raise.
        raise PolishProviderError(f"{self._family.label} polish request failed")


def _safe_body(response: Any) -> str:
    try:
        return str(response.text or "")
    except Exception:  # noqa: BLE001 — a body we cannot read is not a new failure
        return ""


def _retry_after(response: Any) -> float | None:
    try:
        value = response.headers.get("retry-after")
    except Exception:  # noqa: BLE001
        return None
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def _relax_payload(payload: dict[str, Any], body: str) -> dict[str, Any] | None:
    """Rewrite the one field the server complained about, or ``None``.

    Returns a NEW dict so a retry never accumulates half-applied edits.
    """
    lowered = body.lower()
    adjusted = dict(payload)
    changed = False
    if "max_completion_tokens" in lowered and "max_tokens" in adjusted:
        adjusted["max_completion_tokens"] = adjusted.pop("max_tokens")
        changed = True
    if "temperature" in lowered and "temperature" in adjusted:
        adjusted.pop("temperature")
        changed = True
    if "reasoning_effort" in lowered and "reasoning_effort" in adjusted:
        adjusted.pop("reasoning_effort")
        changed = True
    return adjusted if changed else None


#: Shortest request deadline generate-content accepts; anything lower is
#: rejected with a 400 before the model runs.
_GEMINI_MIN_DEADLINE_S = 10.0


class GeminiPolishClient:
    """Adapter for Google's generate-content schema."""

    __slots__ = ("_family", "_model", "_api_key", "_client")

    def __init__(self, family: PolishFamily, *, model: str, api_key: str) -> None:
        self._family = family
        self._model = model
        self._api_key = api_key
        self._client: Any = None

    def _ensure_client(self, timeout_s: float) -> Any:
        if self._client is None:
            # Routed builder: AI Studio or Vertex express, per key.
            from dodaios.core.google_genai import build_genai_client

            # google-genai forces ``timeout=None``, so an explicit http_options
            # timeout is the only thing that stops a hung request holding a
            # connection after the caller's wait_for gave up. It must not be the
            # 1.5 s polish budget: the server rejects deadlines under 10 s, which
            # made every call fail (AP-31). wait_for still bounds the wait.
            self._client = build_genai_client(
                self._api_key,
                http_options={
                    "timeout": int(max(timeout_s, _GEMINI_MIN_DEADLINE_S) * 1000)
                },
            )
        return self._client

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int,
        temperature: float,
        timeout_s: float,
    ) -> str | None:
        try:
            # First use builds the client (SDK import, routing probe): off the loop.
            client = await asyncio.to_thread(self._ensure_client, timeout_s)
            from google.genai import types as genai_types

            response = await client.aio.models.generate_content(
                model=self._model,
                contents=[user],
                config=genai_types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001 — the SDK raises its own hierarchy
            raise PolishProviderError(
                f"{self._family.label} polish request failed: {type(exc).__name__}"
            ) from exc
        _record_gemini_usage(
            self._family.id, self._model, getattr(response, "usage_metadata", None)
        )
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
            reason = getattr(reason, "name", reason)
            if reason and str(reason).upper() not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                raise PolishProviderError("Rewrite did not finish normally")
        text = str(getattr(response, "text", "") or "").strip()
        return text or None


def _record_openai_usage(provider: str, model: str, usage: Any) -> None:
    """OpenAI-shaped usage: ``prompt_tokens`` INCLUDES the cached share."""
    if not isinstance(usage, dict):
        return
    from dodaios.costs.ledger import record_usage

    details = usage.get("prompt_tokens_details")
    cached = int((details or {}).get("cached_tokens") or 0) if isinstance(details, dict) else 0
    prompt = int(usage.get("prompt_tokens") or 0)
    record_usage(
        provider=provider,
        model=model,
        tokens_in=max(0, prompt - cached),
        tokens_out=int(usage.get("completion_tokens") or 0),
        tokens_cached=cached,
        caller="dictation",
    )


def _record_gemini_usage(provider: str, model: str, meta: Any) -> None:
    """google-genai ``usage_metadata``: prompt count includes cached content."""
    if meta is None:
        return
    from dodaios.costs.ledger import record_usage

    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    cached = int(getattr(meta, "cached_content_token_count", 0) or 0)
    out = int(getattr(meta, "candidates_token_count", 0) or 0) + int(
        getattr(meta, "thoughts_token_count", 0) or 0
    )
    record_usage(
        provider=provider,
        model=model,
        tokens_in=max(0, prompt - cached),
        tokens_out=out,
        tokens_cached=cached,
        caller="dictation",
    )


def build_polish_client(family: PolishFamily, *, model: str) -> PolishClient | None:
    """Construct the adapter for *family*, or ``None`` when it is unusable.

    ``None`` covers a missing credential or SDK; the caller tries the next family.
    """
    api_key = _first_secret(family.secret_candidates) if family.needs_key else None
    if family.needs_key and not api_key:
        return None
    try:
        if family.transport == "gemini":
            return GeminiPolishClient(family, model=model, api_key=str(api_key))
        return OpenAIChatPolishClient(family, model=model, api_key=api_key)
    except Exception as exc:  # noqa: BLE001 — an unbuildable family is just the next one
        log.warning(
            "polish client for %r not buildable (%s); trying the next family.",
            family.id,
            exc.__class__.__name__,
        )
        return None


__all__ = [
    "POLISH_FAMILIES",
    "POLISH_TRANSPORTS",
    "GeminiPolishClient",
    "OpenAIChatPolishClient",
    "PolishClient",
    "PolishFamily",
    "PolishProviderError",
    "aclose_shared_client",
    "build_polish_client",
    "family_by_id",
    "family_has_key",
    "family_recently_unreachable",
    "note_family_failure",
    "polish_chain_fingerprint",
    "reset_credential_cache",
    "reset_reachability_cache",
    "resolve_model",
    "resolve_polish_chain",
    "stt_runs_on_device",
]
