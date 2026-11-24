"""STT provider plugins and the factories that build them from ``STTConfig``."""
from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterable
from functools import lru_cache
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from loguru import logger

ENTRY_POINT_GROUP = "jarvis.stt"

# Credential (keyring_key, env_var) candidates per cloud STT provider; others are never gated.
_STT_SECRET_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "groq-api": (("groq_api_key", "GROQ_API_KEY"),),
    # Dedicated key: nothing else reads it, so its presence means STT was set up on purpose.
    "deepgram-api": (("deepgram_api_key", "DEEPGRAM_API_KEY"),),
    # Shares the OpenRouter brain key slot; the id differs from the brain's (catalog collisions).
    "openrouter-stt": (("openrouter_api_key", "OPENROUTER_API_KEY"),),
    # Shares the OpenAI brain slot; the realtime slot is a last-resort cross-read.
    "openai-api": (
        ("openai_api_key", "OPENAI_API_KEY"),
        ("realtime_openai_api_key", "JARVIS_REALTIME_OPENAI_API_KEY"),
    ),
    # Shares the Gemini brain/TTS key slots.
    "gemini-api": (
        ("gemini_api_key", "GEMINI_API_KEY"),
        ("google_aistudio_api_key", "GOOGLE_AIStudio_API_KEY"),
        ("google_api_key", "GOOGLE_API_KEY"),
        ("realtime_gemini_api_key", "JARVIS_REALTIME_GEMINI_API_KEY"),
    ),
    # Shared Vertex credential; never the Gemini slots (an AI Studio key fails at Vertex).
    "vertex-stt": (
        ("vertex_api_key", "VERTEX_API_KEY"),
        ("google_vertex_api_key", "GOOGLE_VERTEX_API_KEY"),
    ),
}

#: Families that can authenticate with no key (Vertex: ADC). Lazy probes keep boot clean (AP-26).
_STT_KEYLESS_CREDENTIAL_PROBES: dict[str, str] = {
    "vertex-stt": "vertex_credential_configured",
}


def _stt_keyless_credential(provider_name: str) -> bool:
    """Whether *provider_name* authenticates without a stored key. Never raises."""
    probe_name = _STT_KEYLESS_CREDENTIAL_PROBES.get(provider_name)
    if not probe_name:
        return False
    try:
        from dodaios.core import config as _cfg

        return bool(getattr(_cfg, probe_name)())
    except Exception as exc:  # noqa: BLE001 — a probe must never break the STT build
        logger.debug("STT keyless credential probe for {} failed ({}).", provider_name, exc)
        return False

# Cross-family takeover order when the configured cloud STT has no key. Groq is last (worse
# German quality); only keyed, registered families are chosen; local is the floor.
_STT_CROSS_FAMILY_ORDER: tuple[str, ...] = (
    # Deepgram first: its key is the only one that unambiguously means "chose a recognizer".
    "deepgram-api",
    "openrouter-stt", "openai-api", "vertex-stt", "gemini-api", "groq-api",
)

# Optional kwargs: on TypeError the build retries without all of them (language/proxy stay).
_OPTIONAL_PROVIDER_KWARGS: tuple[str, ...] = (
    "prompt", "timeout_s", "model", "temperature",
)


def resolve_stt_model(stt_cfg: Any, provider_name: str) -> str:
    """The model id to hand ``provider_name``; ``""`` for the plugin's own default.

    Only the per-provider pin ``[stt].models.<id>`` counts: ``[stt].model`` is a local
    checkpoint name and must not leak to hosted APIs. Never raises.
    """
    name = (provider_name or "").strip()
    if not name:
        return ""
    try:
        pins = getattr(stt_cfg, "models", None) or {}
        pinned = str(pins.get(name, "") or "").strip() if hasattr(pins, "get") else ""
    except Exception as exc:  # noqa: BLE001 — a malformed pin is not worth a build
        logger.debug("STT per-provider model pin unreadable ({}); using defaults.", exc)
        pinned = ""
    return pinned


def _stt_has_credential(provider_name: str, kwargs: dict[str, Any]) -> bool:
    """Whether the configured cloud STT has a usable key; unknown providers count as keyed."""
    if kwargs.get("api_key"):
        return True
    candidates = _STT_SECRET_CANDIDATES.get(provider_name)
    if candidates is None:
        return True
    from dodaios.core import config as _cfg

    if _cfg.get_secret_any(candidates) is not None:
        return True
    return _stt_keyless_credential(provider_name)


def _stt_family_has_key(provider_name: str) -> bool:
    """Like :func:`_stt_has_credential` without kwargs; honours the team proxy for groq-api."""
    from dodaios.core import config as _cfg

    if provider_name == "groq-api":
        try:
            ep = _cfg.resolve_provider_endpoint("groq-api")
            if getattr(ep, "via_proxy", False) and getattr(ep, "credential", None):
                return True
        except Exception as exc:  # noqa: BLE001 — a proxy probe must never break STT build
            logger.debug("STT groq proxy probe failed ({}); using key candidates.", exc)
    candidates = _STT_SECRET_CANDIDATES.get(provider_name)
    if candidates is None:
        return True
    if _cfg.get_secret_any(candidates) is not None:
        return True
    return _stt_keyless_credential(provider_name)


def _resolve_keyed_stt_provider(primary_name: str, *, quiet: bool = False) -> str:
    """Pick a cloud STT the host can run: the configured one if keyed, else the first keyed family.

    With no keyed family the configured name is returned (the caller drops to local).
    ``quiet`` suppresses the log line (the health panel polls this).
    """
    if _stt_family_has_key(primary_name):
        return primary_name
    for cand in _STT_CROSS_FAMILY_ORDER:
        if cand == primary_name:
            continue
        if _stt_family_has_key(cand) and _load_provider_class(cand) is not None:
            if not quiet:
                logger.warning(
                    "STT provider {!r} has no usable API key; crossing to {!r} — the "
                    "cloud STT family the user actually has a key for — so voice input "
                    "still works for a single-key user (open-source AP-22). Set "
                    "[stt].provider to silence this.",
                    primary_name,
                    cand,
                )
            return cand
    return primary_name


def local_stt_unavailable_reason() -> str:
    """Why the on-device recognizer cannot run in this interpreter, or ``""``.

    Availability is per Python process, so the message names the interpreter.
    """
    if _faster_whisper_installed():
        return ""
    return (
        "the local speech engine (faster-whisper) is not installed in the Python "
        f"running Dodaios ({sys.executable})"
    )


def _resolve_effective_stt(provider_name: str) -> tuple[str, str]:
    """``(recognizer that will really run, reason it is not the configured one)``.

    Single source for the health panel and the pipeline build. Silent; the builder logs.
    """
    name = (provider_name or "").strip()
    if not name:
        return name, ""
    # Missing on-device engine in this interpreter: cross to a keyed cloud family (AP-22).
    if name == "faster-whisper":
        reason = local_stt_unavailable_reason()
        if not reason:
            return name, ""
        alternatives = [
            cand for cand in available_stt_provider_names() if cand != "faster-whisper"
        ]
        if not alternatives:
            return name, ""
        return alternatives[0], reason
    # Cloud STT without a key: cross to a keyed family before the local floor (AP-22).
    crossed = _resolve_keyed_stt_provider(name, quiet=True)
    if crossed == name:
        return name, ""
    return crossed, f"{name!r} has no usable API key on this host"


def resolve_effective_stt_provider(provider_name: str) -> str:
    """The recognizer that will really transcribe; see :func:`_resolve_effective_stt`."""
    return _resolve_effective_stt(provider_name)[0]


#: Class attribute a plugin sets to declare it transcribes on this machine (AP-21; privacy floor).
_ON_DEVICE_ATTR = "runs_on_device"

#: Shipped on-device engines, used when the class declares nothing; never to judge third parties.
_SHIPPED_ON_DEVICE_PROVIDERS: frozenset[str] = frozenset(
    {"faster-whisper", "nemotron-local", "parakeet-local"}
)


@lru_cache(maxsize=32)
def provider_runs_on_device(provider_name: str) -> bool:
    """Whether ``provider_name`` transcribes on THIS machine (the privacy question).

    Cloud key slot -> False; shipped on-device name -> True; otherwise the plugin's
    ``runs_on_device`` attribute. Undeclared third-party plugins answer False. Cached per name.
    """
    name = (provider_name or "").strip()
    if not name:
        return False
    if name in _STT_SECRET_CANDIDATES:
        return False
    if name in _SHIPPED_ON_DEVICE_PROVIDERS:
        return True
    return bool(getattr(_load_provider_class(name), _ON_DEVICE_ATTR, False))


def stt_family_id(provider_name: str) -> str:
    """The credential family of a provider id (by key slot, never by name; AP-21).

    Ids sharing a primary secret are one family; on-device engines are ``local``; unknown
    ids are each their own family.
    """
    name = (provider_name or "").strip()
    if not name:
        return ""
    candidates = _STT_SECRET_CANDIDATES.get(name)
    if candidates:
        return candidates[0][0]
    if provider_runs_on_device(name):
        return "local"
    return name


def resolve_keyed_stt_fallback(
    current_id: str,
    *,
    exclude_family: str | Iterable[str] = (),
) -> tuple[str, ...]:
    """Cloud STT provider ids to cross to when ``current_id`` fails at call time (AP-22).

    Returns ids in cross-family order from a family different from ``current_id`` and
    ``exclude_family`` (ids or family ids), one per family, each keyed and registered.
    Empty means no alternative; the local floor is deliberately not in this chain.
    Names only, nothing built (AP-26).
    """
    excluded = {stt_family_id(current_id)}
    if isinstance(exclude_family, str):
        exclude_family = (exclude_family,)
    for name in exclude_family:
        family = stt_family_id(str(name))
        if family:
            excluded.add(family)
    excluded.discard("")

    chain: list[str] = []
    seen: set[str] = set()
    for cand in _STT_CROSS_FAMILY_ORDER:
        family = stt_family_id(cand)
        if family in excluded or family in seen:
            continue
        if not _stt_family_has_key(cand) or _load_provider_class(cand) is None:
            continue
        seen.add(family)
        chain.append(cand)
    logger.debug(
        "STT runtime fallback for {!r} (excluding {}): {}",
        current_id,
        sorted(excluded),
        ", ".join(chain) or "<none — this host has one keyed STT family>",
    )
    return tuple(chain)


def _load_provider_class(name: str) -> type | None:
    """Resolve an STT provider class by entry-point name (cached catalogue; hot path)."""
    from dodaios.core.entry_points import entry_points_for

    selected = entry_points_for(ENTRY_POINT_GROUP)
    for ep in selected:
        if ep.name == name:
            try:
                return ep.load()
            except Exception as exc:  # noqa: BLE001 — broad-except: module boundary — stt plugin
                # Not only a missing dependency: a plugin whose import raises
                # anything must leave the other providers, and the local
                # fallback, usable.
                from dodaios.core import module_health

                logger.warning(
                    "STT entry-point {!r} failed to load: {}", name, exc
                )
                module_health.report_failure(f"plugin:stt:{name}", exc)
                return None
    return None


def build_stt_from_config(stt_cfg: Any, *, dictionary_bias: bool = True) -> Any:
    """Return an STTProvider for ``stt_cfg.provider``, falling back to local faster-whisper.

    ``dictionary_bias=False`` keeps the dictionary out of the decoder prompt (dictation lane):
    a prompt-capable Whisper recites the primed words on near-silence. Post-STT correction
    still applies.
    """
    configured_name = (getattr(stt_cfg, "provider", "") or "").strip()
    # One resolver for both crossings so the health panel reports the provider actually built.
    provider_name, crossed_reason = _resolve_effective_stt(configured_name)
    if crossed_reason:
        logger.warning(
            "Speech-to-text falls back from {!r} to {!r}: {}. Install the local "
            "engine from the API-Keys view, or start Dodaios with the Python that "
            "has it, to switch back.",
            configured_name,
            provider_name,
            crossed_reason,
        )
    language = getattr(stt_cfg, "language", "auto")
    language = language if language and language != "auto" else None
    bias_prompt = (getattr(stt_cfg, "bias_prompt", "") or "").strip()
    # Merge dictionary words into the decoder bias (the local utterance whisper gets none).
    vocab: list[str] = []
    if dictionary_bias:
        try:
            from dodaios.speech.stt_dictionary import dictionary_bias_words

            vocab = dictionary_bias_words()
        except Exception as exc:  # noqa: BLE001 — the dictionary must never break STT build
            logger.debug("STT dictionary bias words unavailable: {}", exc)
    if vocab:
        joined = ", ".join(vocab)
        bias_prompt = f"{bias_prompt}, {joined}" if bias_prompt else joined

    cls = _load_provider_class(provider_name) if provider_name else None
    if cls is not None and provider_name != "faster-whisper":
        kwargs: dict[str, Any] = {}
        if language:
            kwargs["language"] = language
        if bias_prompt:
            kwargs["prompt"] = bias_prompt
        # The model the user picked (AP-31).
        chosen_model = resolve_stt_model(stt_cfg, provider_name)
        if chosen_model:
            kwargs["model"] = chosen_model
        # Reproducibility; providers whose model rejects the field drop it themselves.
        temperature = getattr(stt_cfg, "temperature", None)
        try:
            if temperature is not None:
                kwargs["temperature"] = float(temperature)
        except (TypeError, ValueError):
            logger.debug(
                "STT temperature {!r} is not a number; using the provider default.",
                temperature,
            )
        # Gemini's client has no default timeout and runs in an uncancellable thread: only bound.
        timeout_s = getattr(stt_cfg, "timeout_s", None)
        try:
            if timeout_s is not None and float(timeout_s) > 0:
                kwargs["timeout_s"] = float(timeout_s)
        except (TypeError, ValueError):
            logger.debug(
                "STT timeout_s {!r} is not a number; using the provider default.",
                timeout_s,
            )
        # Team-proxy mode: only groq-api is proxy-capable; direct mode injects nothing.
        if provider_name == "groq-api":
            from dodaios.core import config as _cfg

            ep = _cfg.resolve_provider_endpoint("groq-api")
            if ep.via_proxy and ep.base_url:
                kwargs["endpoint"] = ep.base_url.rstrip("/") + "/audio/transcriptions"
                if ep.credential:
                    kwargs["api_key"] = ep.credential
        # On-device recognizers get no cloud-only options (they would trip the retry warning).
        if provider_runs_on_device(provider_name):
            # Same for temperature; an explicit model pin stays.
            for cloud_only in ("prompt", "timeout_s", "temperature"):
                kwargs.pop(cloud_only, None)
        if not _stt_has_credential(provider_name, kwargs):
            logger.warning(
                "STT provider {!r} has no usable credential; falling back to the "
                "key-free local faster-whisper so voice input still works for a "
                "single-key user (AP-22).",
                provider_name,
            )
            return _build_local_fallback(stt_cfg, language)
        try:
            instance = cls(**kwargs) if kwargs else cls()
            logger.info(
                "STT provider resolved via entry-point: {} (class {}, model={}, "
                "temperature={}, bias_prompt={} chars)",
                provider_name,
                cls.__name__,
                kwargs.get("model") or "<provider default>",
                kwargs.get("temperature", "<provider default>"),
                len(bias_prompt),
            )
            return instance
        except TypeError as exc:
            # The provider class refused one of our OPTIONAL kwargs — most
            # likely a third-party plugin that predates ``prompt`` or
            # ``timeout_s``. Retry with all of them dropped (we cannot tell from
            # a TypeError WHICH one offended) so a stale plugin still loads;
            # only ``language`` and the proxy pair are load-bearing.
            # (faster-whisper local path is handled below as the explicit
            # fallback.)
            refused = [k for k in _OPTIONAL_PROVIDER_KWARGS if k in kwargs]
            if refused:
                for key in refused:
                    kwargs.pop(key, None)
                logger.warning(
                    "STT provider {!r} does not accept {} yet ({}); retrying "
                    "without those.",
                    provider_name,
                    " / ".join(refused),
                    exc,
                )
                try:
                    return cls(**kwargs) if kwargs else cls()
                except Exception as inner_exc:  # noqa: BLE001
                    logger.warning(
                        "STT provider {!r} init still failed ({}); falling back to faster-whisper",
                        provider_name,
                        inner_exc,
                    )
            else:
                logger.warning(
                    "STT provider {!r} init failed ({}); falling back to faster-whisper",
                    provider_name,
                    exc,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "STT provider {!r} init failed ({}); falling back to faster-whisper",
                provider_name,
                exc,
            )

    # Local fallback (also the explicit "faster-whisper" path).
    return _build_local_fallback(stt_cfg, language)


def available_stt_provider_names() -> list[str]:
    """Providers this host could transcribe with now: keyed and registered, then local."""
    names: list[str] = []
    for name in _STT_CROSS_FAMILY_ORDER:
        if _stt_family_has_key(name) and _load_provider_class(name) is not None:
            names.append(name)
    if _faster_whisper_installed():
        names.append("faster-whisper")
    return names


def build_named_stt_provider(
    name: str, stt_cfg: Any, *, dictionary_bias: bool = True
) -> Any:
    """Build provider ``name`` with ``stt_cfg`` otherwise, so a fallback keeps bias and proxy."""
    try:
        patched = stt_cfg.model_copy(update={"provider": name})
    except AttributeError:
        # Not a pydantic model (test doubles); a tiny view is enough.
        patched = _StttConfigView(stt_cfg, name)
    return build_stt_from_config(patched, dictionary_bias=dictionary_bias)


class _StttConfigView:
    """Read-only ``stt_cfg`` with ``provider`` swapped — for non-pydantic doubles."""

    def __init__(self, inner: Any, provider: str) -> None:
        self._inner = inner
        self.provider = provider

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


# Logs the "no working STT" hint at most once per process.
_NO_STT_HINT_EMITTED = False


def _faster_whisper_installed() -> bool:
    """True iff ``faster_whisper`` is importable (cheap spec probe; fwhisper imports it lazily)."""
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def _any_cloud_stt_key() -> bool:
    """True iff the host has a usable key for ANY known cloud STT family."""
    return any(_stt_family_has_key(name) for name in _STT_CROSS_FAMILY_ORDER)


def _maybe_hint_no_working_stt() -> None:
    """Log a one-time hint when there is no cloud key AND no local engine. Log-only."""
    global _NO_STT_HINT_EMITTED
    if _NO_STT_HINT_EMITTED:
        return
    try:
        if _any_cloud_stt_key() or _faster_whisper_installed():
            return
    except Exception as exc:  # noqa: BLE001 — a hint probe must never break STT build
        logger.debug("STT self-recovery hint probe failed ({}); skipping hint.", exc)
        return
    _NO_STT_HINT_EMITTED = True
    logger.warning(
        "No speech-to-text is available on this host: no cloud STT key is "
        "configured (Groq / OpenRouter / OpenAI / Gemini / Vertex AI) and the "
        "local faster-whisper engine is not installed, so voice input cannot "
        "work. To fix it in-app: add a Groq, OpenRouter, OpenAI, Gemini, or "
        "Vertex AI key in the API-Keys view. Or install the local engine via "
        "the '[full]' or '[local-voice]' extra "
        "(e.g. pip install 'personal-jarvis[full]')."
    )


def _build_local_fallback(stt_cfg: Any, language: str | None) -> Any:
    """Construct the key-free local faster-whisper provider (the universal floor)."""
    from dodaios.core.device import resolve_device
    from dodaios.plugins.stt.fwhisper import FasterWhisperProvider

    # Log-only hint when neither a cloud key nor the local engine exists.
    _maybe_hint_no_working_stt()

    # CPU-first device resolution (ADR-0024); only an explicit ``device = "cuda"`` opts in.
    device = resolve_device(
        getattr(stt_cfg, "device", "cpu"),
        cuda_usable=None,
        purpose="stt-utterance",
    ).device
    return FasterWhisperProvider(
        model=getattr(stt_cfg, "model", "distil-large-v3"),
        device=device,
        compute_type=getattr(stt_cfg, "compute_type", "int8"),
        language=language,
    )


def _probe_cache_dir() -> Path:
    """Directory of persisted wake probe results (memory data dir override, else runtime dir)."""
    base = os.environ.get("JARVIS__MEMORY__DATA_DIR")
    if base:
        return Path(base)
    from dodaios.core.paths import runtime_data_dir

    return runtime_data_dir()


def _wake_cuda_cache_path() -> Path:
    """Location of the persisted CUDA-availability probe result."""
    return _probe_cache_dir() / "wake_cuda_probe.json"


@lru_cache(maxsize=1)
def _wake_cuda_available() -> bool:
    """True iff a CUDA device is usable by CTranslate2 / faster-whisper.

    Cached in-process and on disk: the first CUDA call can cost ~30-60 s (Blackwell JIT) and
    must stay off the boot path. Delete ``wake_cuda_probe.json`` to re-probe. Errors mean no CUDA.
    """
    cache_path = _wake_cuda_cache_path()

    # Persisted result.
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and isinstance(cached.get("cuda"), bool):
            logger.info(
                "Wake-CUDA probe: cache HIT ({}) — probe skipped.",
                "available" if cached["cuda"] else "absent",
            )
            return cached["cuda"]
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 — a corrupt cache must never break boot
        logger.debug("Wake-CUDA probe cache unreadable ({}); re-probing.", exc)

    # Cold path: probe once, then persist.
    t0 = time.perf_counter()
    try:
        # Shield the ctranslate2 import from the transformers+torch converter stack.
        from dodaios.plugins.stt.fwhisper import inference_only_import_shield

        with inference_only_import_shield():
            import ctranslate2

        available = ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - any failure means "treat as no GPU"
        available = False
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "Wake-CUDA probe: cache MISS — probed in {:.0f} ms -> CUDA {}.",
        elapsed_ms,
        "available" if available else "absent",
    )
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"cuda": available}), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — caching is best-effort
        logger.debug("Wake-CUDA probe cache write failed ({}).", exc)
    return available


def _wake_gpu_probe_cache_path() -> Path:
    """Location of the persisted GPU wake-inference probe result (separate from CUDA presence)."""
    return _probe_cache_dir() / "wake_gpu_probe.json"


# The verdict is the stdout marker, never the exit code (CUDA can die in native teardown).
_WAKE_GPU_PROBE_MARKER = "WAKE_GPU_PROBE_OK"

# Ceiling for one probe run; a cold Blackwell JIT load takes ~71 s, longer is the AP-25 hang.
_WAKE_GPU_PROBE_TIMEOUT_S = 180.0

# Probe like the live hot-swap: torch first (registers the cublas DLL dir; AP-25 was OpenMP clash).
_WAKE_GPU_PROBE_SCRIPT = r"""
try:
    import torch  # noqa: F401 — mirror the live app: torch (Silero VAD) is loaded first
except Exception:
    pass
import numpy as np
from faster_whisper import WhisperModel
m = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8_float16")
pcm = (np.random.default_rng(0).standard_normal(19200) * 0.05).astype("float32")
for _ in range(2):
    segments, _info = m.transcribe(pcm, language="de", beam_size=1)
    list(segments)  # consume the generator — this is what runs the inference
print("WAKE_GPU_PROBE_OK", flush=True)
"""


def _ctranslate2_version() -> str:
    """Installed ctranslate2 version (metadata only — no heavy import)."""
    try:
        return importlib_metadata.version("ctranslate2")
    except Exception:  # noqa: BLE001 — absent/broken install means "unknown"
        return "unknown"


def _run_wake_gpu_probe_subprocess() -> bool:
    """Run one real turbo/cuda inference in a killable child process (AP-24). Blocking."""
    import subprocess
    import sys

    from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, our own interpreter
            [sys.executable, "-c", _WAKE_GPU_PROBE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=_WAKE_GPU_PROBE_TIMEOUT_S,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Wake-GPU probe: inference did not finish within {:.0f} s — the "
            "AP-25 hang signature. GPU wake upgrade stays OFF on this host.",
            _WAKE_GPU_PROBE_TIMEOUT_S,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — a probe must never break the caller
        logger.warning("Wake-GPU probe: could not launch ({}).", exc)
        return False
    ok = _WAKE_GPU_PROBE_MARKER in (proc.stdout or "")
    if not ok:
        tail = ((proc.stderr or proc.stdout or "").strip())[-300:]
        logger.warning(
            "Wake-GPU probe: no success marker (exit={}). Tail: {}",
            proc.returncode,
            tail or "<empty>",
        )
    return ok


@lru_cache(maxsize=1)
def _wake_gpu_inference_verified() -> bool:
    """True iff a real turbo/cuda wake inference verifiably completes here (AP-21, AP-25).

    Cached on disk keyed by ctranslate2 version. BLOCKING on a miss: hot-swap thread only (AP-26).
    """
    ct2_version = _ctranslate2_version()
    cache_path = _wake_gpu_probe_cache_path()
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and isinstance(cached.get("ok"), bool)
            and cached.get("ctranslate2") == ct2_version
        ):
            logger.info(
                "Wake-GPU probe: cache HIT ({}, ctranslate2 {}) — probe skipped.",
                "verified" if cached["ok"] else "unusable",
                ct2_version,
            )
            return cached["ok"]
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 — a corrupt cache must never break the swap
        logger.debug("Wake-GPU probe cache unreadable ({}); re-probing.", exc)

    t0 = time.perf_counter()
    ok = _run_wake_gpu_probe_subprocess()
    logger.info(
        "Wake-GPU probe: real turbo/cuda inference {} in {:.1f} s "
        "(ctranslate2 {}).",
        "VERIFIED" if ok else "FAILED",
        time.perf_counter() - t0,
        ct2_version,
    )
    _persist_wake_gpu_probe(ok, ct2_version)
    return ok


def wake_gpu_probe_cached() -> bool | None:
    """The persisted GPU-inference verdict for this ctranslate2 version, or ``None``.

    Pure file read; never launches the probe (AP-26).
    """
    ct2_version = _ctranslate2_version()
    try:
        cached = json.loads(_wake_gpu_probe_cache_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 — a corrupt cache must never break the caller
        logger.debug("Wake-GPU probe cache unreadable ({}); treating as unprobed.", exc)
        return None
    if (
        isinstance(cached, dict)
        and isinstance(cached.get("ok"), bool)
        and cached.get("ctranslate2") == ct2_version
    ):
        return cached["ok"]
    return None


def _persist_wake_gpu_probe(ok: bool, ct2_version: str | None = None) -> None:
    """Best-effort write of the probe verdict (shared by probe + bad-mark)."""
    cache_path = _wake_gpu_probe_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "ok": ok,
                    "ctranslate2": ct2_version or _ctranslate2_version(),
                    "model": "large-v3-turbo",
                }
            ),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — caching is best-effort
        logger.debug("Wake-GPU probe cache write failed ({}).", exc)


def forget_gpu_probe_results() -> None:
    """Drop both persisted GPU verdicts so the next build probes afresh (after GPU lib install)."""
    _wake_cuda_available.cache_clear()
    for path in (_wake_cuda_cache_path(), _wake_gpu_probe_cache_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001 — best-effort cache hygiene
            logger.debug("GPU probe cache {} not removed ({}).", path, exc)


def mark_wake_gpu_bad() -> None:
    """Record that the live GPU wake model wedged; builds stay on CPU until ctranslate2 changes."""
    _persist_wake_gpu_probe(False)
    _wake_gpu_inference_verified.cache_clear()
    logger.warning(
        "Wake-GPU probe: marked UNUSABLE after a live wedge — wake stays on "
        "the base/cpu model until the ctranslate2 runtime changes."
    )


def build_wake_whisper(
    stt_cfg: Any,
    *,
    language: str | None = None,
    wake_phrase: str | None = None,
    cuda_available: bool | None = None,
    fast_first: bool = False,
) -> Any:
    """Build the local wake-match / live-preview Whisper (small CPU model by default).

    ``wake_phrase`` seeds ``initial_prompt`` for custom wake words: the unbiased base/cpu model
    mis-hears proper nouns (2-13 % recall vs 83 % biased); false wakes are held off by the strict
    matcher plus no_speech_prob/RMS gates. Blank means no bias. Missing ``wake_*`` config fields
    fall back to base/cpu.
    """
    from dodaios.plugins.stt.fwhisper import FasterWhisperProvider, _bound_ct2_threads

    # Bound the CPU thread pool before ctranslate2 is first imported (AP-24/25).
    _bound_ct2_threads(default=2)

    model = getattr(stt_cfg, "wake_model", "base")
    device = getattr(stt_cfg, "wake_device", "cpu")
    compute = getattr(stt_cfg, "wake_compute_type", "int8")
    bias = wake_phrase.strip() if wake_phrase and wake_phrase.strip() else None

    # GPU upgrade (base/cpu defaults + CUDA + verified inference). Without a phrase the strong
    # model needs no bias, and the bias is what hallucinates onto silence. Explicit config wins.
    if cuda_available is None:
        cuda_available = _wake_cuda_available()
    # ``fast_first`` skips the GPU upgrade so a custom phrase is hear-ready in ~3 s; the caller
    # hot-swaps turbo/cuda in the background. Both CUDA branches need the one-time out-of-process
    # inference probe (AP-25); it blocks, safe only because fast_first (boot) builds never reach it.
    if (
        not fast_first
        and not bias
        and model == "base"
        and device == "cpu"
        and cuda_available
        and bool(getattr(stt_cfg, "wake_high_accuracy", False))
        and _wake_gpu_inference_verified()
    ):
        model, device, compute = "large-v3-turbo", "cuda", "int8_float16"
        bias = None  # strong model needs no bias; the bias is what hallucinates
        logger.info(
            "Wake-Whisper: CUDA inference verified -> GPU turbo "
            "(large-v3-turbo/cuda), bias OFF (fast + no silence hallucination)."
        )
    elif (
        not fast_first
        and bias
        and model == "base"
        and device == "cpu"
        and cuda_available
        and bool(getattr(stt_cfg, "wake_high_accuracy", False))
        and _wake_gpu_inference_verified()
    ):
        # Custom phrase on CUDA: turbo on GPU but KEEP the bias (a short phrase is mangled without
        # it); only windows past the rms/peak gates are transcribed, so silence never hallucinates.
        model, device, compute = "large-v3-turbo", "cuda", "int8_float16"
        logger.info(
            "Wake-Whisper: custom phrase, CUDA inference verified -> GPU turbo "
            "(large-v3-turbo/cuda) WITH bias — fast (~150 ms, no wedge) + "
            "accurate. Set [stt].wake_high_accuracy=false to force base/cpu."
        )
    elif fast_first and model == "base" and device == "cpu" and cuda_available:
        logger.info(
            "Wake-Whisper: fast-first base/cpu (bias ON) — turbo/cuda upgrade "
            "deferred to a background hot-swap so wake is hear-ready in ~3 s."
        )

    return FasterWhisperProvider(
        model=model,
        device=device,
        compute_type=compute,
        language=language,
        initial_prompt=bias,
        # Greedy: a short phrase on an always-on loop needs no beam search (3-5x faster).
        beam_size=1,
        # Fixed small thread count: auto deadlocks against PyTorch's OpenMP pool (AP-24/25); 2 was
        # 1.7-2.8x faster than 1 with zero hangs. num_workers stays 1.
        cpu_threads=2,
        # One greedy pass: no temperature fallback ladder (a window cost up to 7.7 s). Not setting
        # ``without_timestamps``: it would change the per-segment no_speech_prob check (AP-27).
        temperature=0.0,
    )


def wake_whisper_is_consumed(app_cfg: Any) -> tuple[bool, str]:
    """Whether this config will build a local wake Whisper at all, as ``(will_it, reason)``.

    Mirrors the build site (``desktop_app._start_speech_and_orb``); other engines never adopt
    the prefetched weights. Cheap and pure; any failure answers ``True``.
    """
    try:
        import importlib.util as _ilu

        from dodaios.speech.wake_model_fetch import resolve_wake_language
        from dodaios.speech.wake_phrase import resolve_wake_plan

        trigger = getattr(app_cfg, "trigger", None)
        if bool(getattr(trigger, "heavy_local_whisper", False)):
            return True, "trigger.heavy_local_whisper is on"
        plan = resolve_wake_plan(
            app_cfg.trigger.wake_word,
            local_whisper_available=_ilu.find_spec("faster_whisper") is not None,
            language=resolve_wake_language(app_cfg),
        )
        if plan.needs_local_whisper:
            return True, f"the {plan.engine} wake engine transcribes locally"
        return False, f"the {plan.engine} wake engine never builds one"
    except Exception as exc:  # noqa: BLE001 — an unreadable plan must not skip the prefetch
        return True, f"the wake plan could not be resolved ({exc}); prefetching anyway"


def start_wake_model_prefetch(
    stt_cfg: Any,
    *,
    language: str | None = None,
    wake_phrase: str | None = None,
    app_cfg: Any = None,
) -> Any:
    """Prefetch the fast-first wake Whisper weights in a daemon thread, off the boot path.

    Parameters come from a throwaway :func:`build_wake_whisper` (``fast_first=True``) so they
    cannot drift; the load touches no torch. ``app_cfg`` skips the load when nothing would
    adopt the weights. No-op when voice is disabled or on failure. Returns the thread or ``None``.
    """
    import threading
    import time

    from dodaios.speech.warmup_prefetch import _voice_disabled

    if _voice_disabled():
        return None

    def _load() -> None:
        try:
            if app_cfg is not None:
                consumed, why = wake_whisper_is_consumed(app_cfg)
                if not consumed:
                    logger.info(
                        "Wake-model prefetch skipped: {} — nothing would adopt "
                        "the weights, and loading them competes with the wake "
                        "model for a cold disk.",
                        why,
                    )
                    return
            from dodaios.plugins.stt.fwhisper import prefetch_model

            probe = build_wake_whisper(
                stt_cfg,
                language=language,
                wake_phrase=wake_phrase,
                fast_first=True,
            )
            started = time.perf_counter()
            prefetch_model(
                probe._model_name,  # noqa: SLF001 — resolved params, same module family
                probe._device,  # noqa: SLF001
                probe._compute_type,  # noqa: SLF001
                probe._cpu_threads,  # noqa: SLF001
            )
            # Timed because the load is otherwise invisible.
            logger.info(
                "Wake-model prefetch done in {:.0f} ms ({}/{}/{}).",
                (time.perf_counter() - started) * 1000.0,
                probe._model_name,  # noqa: SLF001
                probe._device,  # noqa: SLF001
                probe._compute_type,  # noqa: SLF001
            )
        except Exception as exc:  # noqa: BLE001 — a prefetch must never break boot
            logger.debug("Wake-model prefetch skipped: {}", exc)

    thread = threading.Thread(target=_load, name="wake-model-prefetch", daemon=True)
    thread.start()
    return thread


__all__ = [
    "available_stt_provider_names",
    "build_named_stt_provider",
    "build_stt_from_config",
    "build_wake_whisper",
    "mark_wake_gpu_bad",
    "provider_runs_on_device",
    "resolve_keyed_stt_fallback",
    "resolve_stt_model",
    "start_wake_model_prefetch",
    "stt_family_id",
    "wake_gpu_probe_cached",
    "wake_whisper_is_consumed",
]
