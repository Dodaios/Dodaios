"""Config loading with layers: TOML → YAML profiles → Env → Runtime.

Secrets never come from the config file: `get_secret()` is the single access point
(OS keyring, ENV, `.env`, then a local 0600 file on headless hosts without a keyring).

Hot-reload: watchdog monitors the config file and dispatches `ConfigReloaded`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
import threading
import tomllib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from .ack_brain_config import AckBrainConfig
from .branding import KEYRING_SERVICE_NAME, LEGACY_KEYRING_SERVICE_NAMES
from .env_prefix import accepted_names
from .identity_boot import resolve_config_file
from .instance import current_instance, data_dir_source, resolve_data_dir
from .live_config import LiveConfig
from .pet_defaults import DEFAULT_PET_ID
from .protocols import RiskTier

# Pure stdlib: the wake-engine enum + the default phrase (single source of truth).
from .wake_constants import DEFAULT_WAKE_PHRASE, WAKE_ENGINES

# Paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Resolved once, like every path constant, so reader and writers address the same file.
DEFAULT_CONFIG_FILE = resolve_config_file(PROJECT_ROOT)
PROFILES_DIR = PROJECT_ROOT / "profiles"


def _resolve_data_dir() -> Path:
    """The runtime data directory (``JARVIS_DATA_DIR`` wins; else ``data/`` or ``data-dev/`` per
    instance)."""
    return resolve_data_dir(PROJECT_ROOT)


DATA_DIR = _resolve_data_dir()
# Read in the same import as DATA_DIR, so the two always describe one decision.
DATA_DIR_SOURCE = data_dir_source()
_data_dir_logged = False


def memory_data_dir(cfg: Any) -> Path:
    """``cfg.memory.data_dir``, or :data:`DATA_DIR` when ``cfg`` carries none (never
    cwd-relative)."""
    raw = getattr(getattr(cfg, "memory", None), "data_dir", None)
    return Path(raw) if raw else DATA_DIR


def data_dir_info() -> dict[str, str]:
    """The active data directory and where it came from, for diagnostics."""
    return {"path": str(DATA_DIR), "source": DATA_DIR_SOURCE}


def log_data_dir_once(log: Any = None) -> bool:
    """Log ``Data directory: <path> (source: ...)`` once per process."""
    global _data_dir_logged
    if _data_dir_logged:
        return False
    _data_dir_logged = True
    (log or logging.getLogger(__name__)).info(
        "Data directory: %s (source: %s)", DATA_DIR, DATA_DIR_SOURCE
    )
    return True

ASSETS_DIR = PROJECT_ROOT / "assets"

# Guards _resolve_writable_data_dir()'s lazy probe (separate from config_writer's _WRITE_LOCK).
_data_dir_lock = threading.Lock()
_data_dir_cache: tuple[Path, Path] | None = None  # (DATA_DIR seen, resolved dir)


def _resolve_writable_data_dir() -> Path:
    """Directory for local credential-store persistence: ``JARVIS_DATA_DIR``, else :data:`DATA_DIR`,
    else per-user app data when not writable. Probed once, lazily; cached until ``DATA_DIR``
    changes."""
    global _data_dir_cache
    env_dir = os.environ.get("JARVIS_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip())
    with _data_dir_lock:
        if _data_dir_cache is not None and _data_dir_cache[0] == DATA_DIR:
            return _data_dir_cache[1]
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            probe = DATA_DIR / f".write_probe_{os.getpid()}"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            resolved = DATA_DIR
        except OSError:
            from dodaios.core.paths import user_data_dir

            resolved = user_data_dir()
            logging.getLogger(__name__).info(
                "project data directory %s is not writable — using %s for "
                "local credential storage instead",
                DATA_DIR,
                resolved,
            )
        _data_dir_cache = (DATA_DIR, resolved)
        return resolved


def resolve_config_path() -> Path:
    """Return the active config file path, honouring ``JARVIS_CONFIG`` (blank values are
    ignored)."""
    override = os.environ.get("JARVIS_CONFIG")
    if override and override.strip():
        return Path(override.strip())
    return DEFAULT_CONFIG_FILE


KEYRING_SERVICE = KEYRING_SERVICE_NAME
# Services earlier versions filed credentials under: read as a fallback, cleared on delete,
# refreshed on set so a downgrade sees the new value. Nothing else writes there.
LEGACY_KEYRING_SERVICES: tuple[str, ...] = tuple(
    service for service in LEGACY_KEYRING_SERVICE_NAMES if service != KEYRING_SERVICE_NAME
)

# Provider secrets stay out of TOML; one table of slots and ENV fallbacks keeps all readers in
# agreement.
PROVIDER_SECRET_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "claude-api": (("anthropic_api_key", "ANTHROPIC_API_KEY"),),
    # The trailing realtime slot is a last-resort cross-read for single-key installs.
    "openai": (
        ("openai_api_key", "OPENAI_API_KEY"),
        ("realtime_openai_api_key", "JARVIS_REALTIME_OPENAI_API_KEY"),
    ),
    "codex": (
        ("codex_openai_api_key", "OPENAI_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
    ),
    "openrouter": (("openrouter_api_key", "OPENROUTER_API_KEY"),),
    "deepseek": (("deepseek_api_key", "DEEPSEEK_API_KEY"),),
    # LiteLLM proxy (user-hosted gateway); a virtual key saved in the app wins over the proxy env
    # name.
    "litellm": (
        ("litellm_api_key", "LITELLM_API_KEY"),
        ("litellm_master_key", "LITELLM_MASTER_KEY"),
    ),
    # Groq stays a speech-to-text credential family though it is not a brain provider.
    "groq": (("groq_api_key", "GROQ_API_KEY"),),
    # NVIDIA NIM: only the build.nvidia.com key (nvapi-), not the legacy NGC key.
    "nvidia": (("nvidia_api_key", "NVIDIA_API_KEY"),),
    "gemini": (
        ("gemini_api_key", "GEMINI_API_KEY"),
        ("google_aistudio_api_key", "GOOGLE_AIStudio_API_KEY"),
        ("google_api_key", "GOOGLE_API_KEY"),
        ("realtime_gemini_api_key", "JARVIS_REALTIME_GEMINI_API_KEY"),
    ),
    # Vertex AI: its own family, NO cross-read to the ``gemini`` slots in either direction (an AI
    # Studio key sent to Vertex fails auth). Service-account installs store no key:
    # ``vertex_credential_configured``.
    "vertex": (
        ("vertex_api_key", "VERTEX_API_KEY"),
        ("google_vertex_api_key", "GOOGLE_VERTEX_API_KEY"),
        ("realtime_vertex_api_key", "JARVIS_REALTIME_VERTEX_API_KEY"),
    ),
    "grok": (
        ("grok_api_key", "GROK_API_KEY"),
        ("xai_api_key", "XAI_API_KEY"),
    ),
    # Realtime owns dedicated slots; generic family slots are trailing read-only fallbacks and the
    # reverse cross-read exists too, so a key saved only on the Realtime card still gives a working
    # Brain/Tool-Model.
    "openai-realtime": (
        ("realtime_openai_api_key", "JARVIS_REALTIME_OPENAI_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
    ),
    "openai-live": (
        ("openai_api_key", "OPENAI_API_KEY"),
        ("realtime_openai_api_key", "JARVIS_REALTIME_OPENAI_API_KEY"),
    ),
    "gemini-live": (
        ("realtime_gemini_api_key", "JARVIS_REALTIME_GEMINI_API_KEY"),
        ("gemini_api_key", "GEMINI_API_KEY"),
        ("google_aistudio_api_key", "GOOGLE_AIStudio_API_KEY"),
        ("google_api_key", "GOOGLE_API_KEY"),
    ),
    # Vertex Live: dedicated slot first; trailing fallbacks stay inside the Vertex family.
    "vertex-live": (
        ("realtime_vertex_api_key", "JARVIS_REALTIME_VERTEX_API_KEY"),
        ("vertex_api_key", "VERTEX_API_KEY"),
        ("google_vertex_api_key", "GOOGLE_VERTEX_API_KEY"),
    ),
    # No "grok-realtime" slot (deaf-session wedge); a stored realtime_grok_api_key stays unused.
}

# Agent API credentials are replaceable from the Agent tab; scoped Agent keys win and are never used
# by Brain or Realtime. Generic slots stay a last-resort fallback so single-key installs never
# brick.
JARVIS_AGENT_SECRET_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "claude-api": (
        ("jarvis_agent_anthropic_api_key", "JARVIS_AGENT_ANTHROPIC_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["claude-api"],
    ),
    "openai": (
        ("jarvis_agent_openai_api_key", "JARVIS_AGENT_OPENAI_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["openai"],
    ),
    "gemini": (
        ("jarvis_agent_gemini_api_key", "JARVIS_AGENT_GEMINI_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["gemini"],
    ),
    "openrouter": (
        ("jarvis_agent_openrouter_api_key", "JARVIS_AGENT_OPENROUTER_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["openrouter"],
    ),
    "litellm": (
        ("jarvis_agent_litellm_api_key", "JARVIS_AGENT_LITELLM_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["litellm"],
    ),
    "grok": (
        ("jarvis_agent_grok_api_key", "JARVIS_AGENT_GROK_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["grok"],
    ),
    "nvidia": (
        ("jarvis_agent_nvidia_api_key", "JARVIS_AGENT_NVIDIA_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["nvidia"],
    ),
    "vertex": (
        ("jarvis_agent_vertex_api_key", "JARVIS_AGENT_VERTEX_API_KEY"),
        *PROVIDER_SECRET_CANDIDATES["vertex"],
    ),
}

_PROVIDER_SECRET_OVERRIDES: ContextVar[Mapping[str, str | None] | None] = ContextVar(
    "provider_secret_overrides", default=None
)


# Sub-configs (Pydantic models per layer)


class ProfileConfig(BaseModel):
    name: str = "default"
    language: str = "auto"


class PersonaConfig(BaseModel):
    """Reserved ``[persona]`` table; the assistant name derives from the wake phrase."""

    model_config = ConfigDict(extra="ignore")


class WakeWordConfig(BaseModel):
    """User-editable ``[trigger.wake_word]``; ``phrase`` is the single source of truth."""

    # extra="allow": future or legacy sub-keys survive a self-mod round-trip (AP-16).
    model_config = ConfigDict(extra="allow")

    phrase: str = DEFAULT_WAKE_PHRASE
    # Detection engine; "auto" picks the best path for the phrase. Unknown values coerce to "auto"
    # (AP-16).
    engine: str = "auto"
    custom_model_path: str = ""
    # Language the wake word is SPOKEN in, independent of [ui].language; "auto" keeps the legacy
    # cascade. Resolved by dodaios/speech/wake_model_fetch.py::resolve_wake_language.
    language: str = "auto"
    # READ-COMPAT ONLY, ignored at runtime (the Sensitivity slider was removed); kept so old files
    # parse (AP-16).
    sensitivity: float = 0.5
    fuzzy_match_ratio: float = 0.8
    # Deprecated porcupine-era keys (never wired), kept so an old jarvis.toml still validates.
    provider: str = "openwakeword"
    keyword: str = "jarvis"
    custom_keyword_file: str = ""

    @field_validator("engine", mode="before")
    @classmethod
    def _coerce_engine(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in WAKE_ENGINES else "auto"

    @field_validator("language", mode="before")
    @classmethod
    def _coerce_language(cls, value: object) -> str:
        # Normalize only; unknown values fall through the cascade in resolve_wake_language (AP-16).
        text = str(value or "").strip().lower()
        return text or "auto"

    @field_validator("sensitivity", mode="before")
    @classmethod
    def _floor_sensitivity(cls, value: object) -> float:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5
        # Lift below-floor values instead of rejecting (AP-16); 0.5 restores a working wake.
        return min(1.0, max(0.5, number))


class TriggerConfig(BaseModel):
    wake_word_enabled: bool = False
    # Deprecated push-to-talk key, still accepted from old configs but no longer registered.
    hotkey: str = ""
    hotkey_call: str = "f3+f4"
    hotkey_hangup: str = "f1+f2"
    # Push-to-talk dictation key: HOLD to speak, release to insert. Ships BOUND to curated combos
    # that pass ``validate_hotkey`` on every OS and do not collide with Call/Hangup. An empty value
    # is valid (dictation also starts from the bar, the UI and ``jarvis api dictation start``).
    hotkey_dictate: str = "ctrl+right_alt+j"
    # Hands-free dictation key (press to start, again to stop); armed independently of
    # ``[dictation].mode``.
    hotkey_dictate_toggle: str = "ctrl+right_alt+space"
    # Re-insert the last dictation: recovery for a paste that landed nowhere (a successful paste
    # restores the clipboard). Ships bound; the hotkey backend polls and does not swallow keys.
    # Empty is valid; also `jarvis api dictation paste-last`.
    hotkey_paste_last: str = "ctrl+alt+v"
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)
    # False (default): conversation mode, the mic stays open after the reply and hangs up only via
    # HANGUP_RE, the idle timeout or a hotkey. True: every turn ends after the reply and needs a
    # fresh wake.
    single_turn_mode: bool = False
    # Silence window (seconds) after which a conversation-mode session auto-hangs-up; <= 0 disables
    # it (user mandate). No effect in single-turn mode. Wired into
    # ``SpeechPipeline(idle_timeout_s=...)``.
    session_idle_timeout_s: float = 30.0
    push_to_talk: bool = False

    def resolve_hotkeys(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return the active call hotkey and an empty legacy PTT slot."""
        return (tuple(h for h in (self.hotkey_call,) if h.strip()), ())

    # False (default): lightweight local wake (openWakeWord only, CPU, no faster-whisper). True adds
    # the heavy RollingWhisperWake backstop + VAD probe (see
    # docs/local-wakeword/RESEARCH-AND-DESIGN.md).
    heavy_local_whisper: bool = False
    # True (default): an OpenWakeWord hit is only a candidate, confirmed by cloud STT against a
    # strict "hey/hi/hallo + jarv" pattern to remove bare-"Jarvis" false fires. False restores
    # raw-OWW behaviour.
    require_hey_prefix: bool = True


class STTConfig(BaseModel):
    provider: str = "groq-api"
    # Set by every user-facing provider switch: the persisted provider then beats a stale
    # JARVIS__STT__PROVIDER from an older process.
    provider_user_selected: bool = False
    # Fallback when ``provider`` keeps failing at runtime (401/402, surviving rate limits): ``auto``
    # picks a provider in a DIFFERENT family the user holds a key for (same family dies with the
    # same key, AP-22); a concrete id pins it; empty disables crossing. Used by
    # ``dodaios.plugins.stt``.
    fallback: str = "auto"
    # Local FasterWhisperProvider utterance model; must be multilingual (``distil-large-v3`` is
    # English-only and mangles German/Spanish; ``large-v3-turbo`` is the fast choice).
    model: str = "large-v3-turbo"
    # Cloud-first default "cpu"; set "cuda" on a CUDA box (falls back at runtime without CUDA).
    device: str = "cpu"
    compute_type: str = "int8_float16"
    # The LOCAL wake-match / live-preview Whisper (distinct from ``model``): small and on CPU by
    # default, since GPU kernel JIT at load costs ~71 s vs ~0.45 s for ``base`` on CPU.
    wake_model: str = "base"
    wake_device: str = "cpu"
    wake_compute_type: str = "int8"
    # Opt-in GPU wake: a custom phrase (``stt_match``) runs ``large-v3-turbo`` on the GPU instead of
    # ``base`` on the CPU, only after an out-of-process inference probe passed
    # (``dodaios.plugins.stt._wake_gpu_inference_verified``); a live backstop drops back to base/cpu
    # and persists the bad verdict if the GPU model wedges (AP-25). Default CPU: this flag is the
    # complete CPU<->GPU switch (plain, custom-phrase and hot-swap paths), because sticky GPU caches
    # once latched one transient failure across every restart.
    wake_high_accuracy: bool = False
    language: str = "auto"
    # Vocabulary biasing sent as Whisper's ``prompt``; empty = none. Cloud plugins only: the local
    # provider ignores it (an initial prompt on silent audio hallucinated as the transcript).
    bias_prompt: str = ""
    # Model per CLOUD recognizer keyed by provider id; separate from ``model`` (a faster-whisper
    # checkpoint name, meaningless to hosted APIs). Unset = the plugin default.
    models: dict[str, str] = Field(default_factory=dict)
    # Sampling temperature; 0.0 because transcription is a measurement. Sent only to models that
    # accept it.
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


class TTSConfig(BaseModel):
    # extra="allow" keeps per-provider sub-tables like [tts.cartesia] through the round-trip
    # (AP-16).
    model_config = {"extra": "allow"}

    provider: str = "gemini-flash-tts"
    model: str | None = None
    voice_de: str = "Charon"
    voice_en: str = "Charon"
    language_code: str = "de-DE"
    style_prompt: str | None = None
    voice_auto_switch: bool = True
    speed: float = 1.0
    # Master output volume 0.0-1.0, scaled by dodaios.audio.gain to makeup boost + soft limiter;
    # applied to every sink (speaker, browser voice, telephony).
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    streaming: bool = True
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    # SAPI5 (Windows robotic TTS) is an emergency brake: default false means no silent fallback to
    # the Windows voice when a cloud voice fails.
    allow_sapi5_fallback: bool = False
    # Voice-consistency knobs for generative TTS (Gemini only): one generation per utterance, pinned
    # RNG seed, lower prosody variance.
    chunk_by_sentence: bool = True
    seed: int | None = None
    temperature: float | None = None
    # Vertex AI path: ``use_vertex=True`` builds ``genai.Client(vertexai=True, ...)`` instead of
    # using an AI Studio key (avoids the preview-model daily cap). Auth is a service-account JSON
    # via ``GOOGLE_APPLICATION_CREDENTIALS``; ``service_account_path`` is exported into the env
    # first.
    use_vertex: bool = False
    vertex_project: str | None = None
    vertex_location: str = "us-central1"
    service_account_path: str | None = None


#: Closed vocabulary of per-model Ollama options under ``[brain.providers.ollama.models."<tag>"]``;
#: a parity test pins config_writer and the route body to it (AP-4). All are request options except
#: ``keep_alive`` and ``think``.
OLLAMA_MODEL_OPTION_KEYS: tuple[str, ...] = (
    "num_ctx",
    "num_gpu",
    "num_thread",
    "num_predict",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "seed",
    "stop",
    "keep_alive",
    "think",
)

#: Graded thinking levels Ollama's ``think`` field accepts besides a bool.
OLLAMA_THINK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "max")

#: Go duration as Ollama parses ``keep_alive`` ("5m", "2h", "1h30m", "-1").
_GO_DURATION_RE = re.compile(r"^-?(?:\d+(?:\.\d+)?(?:ns|us|µs|ms|s|m|h))+$")


def _clamped_optional_int(value: object, *, low: int, high: int) -> int | None:
    """Clamp a hand-edited integer into range; ``None`` or garbage stays unset (AP-16)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return max(low, min(high, number))


def _clamped_optional_float(value: object, *, low: float, high: float) -> float | None:
    """The float twin of :func:`_clamped_optional_int`."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / ±inf
        return None
    return max(low, min(high, number))


class OllamaModelOptions(BaseModel):
    """Per-model knobs for one Ollama tag. Every field is optional (``None`` = Ollama default);
    values are CLAMPED, never rejected (AP-16); unknown keys are kept.

    Bakeable knobs are baked into a derived model via ``/api/create``
    (``dodaios.brain.ollama_profiles``); ``temperature``/``num_predict`` ride the ``/v1`` request;
    ``think`` rides as ``reasoning_effort``; ``keep_alive`` rides the warm ping."""

    model_config = ConfigDict(extra="allow")

    num_ctx: int | None = None
    num_gpu: int | None = None
    num_thread: int | None = None
    num_predict: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    repeat_penalty: float | None = None
    seed: int | None = None
    stop: list[str] | None = None
    keep_alive: str | int | None = None
    think: bool | str | None = None

    @field_validator("num_ctx", mode="before")
    @classmethod
    def _clamp_num_ctx(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=512, high=1_048_576)

    @field_validator("num_gpu", mode="before")
    @classmethod
    def _clamp_num_gpu(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=-1, high=999)

    @field_validator("num_thread", mode="before")
    @classmethod
    def _clamp_num_thread(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=0, high=512)

    @field_validator("num_predict", mode="before")
    @classmethod
    def _clamp_num_predict(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=-2, high=1_048_576)

    @field_validator("temperature", mode="before")
    @classmethod
    def _clamp_temperature(cls, value: object) -> float | None:
        return _clamped_optional_float(value, low=0.0, high=2.0)

    @field_validator("top_p", "min_p", mode="before")
    @classmethod
    def _clamp_unit_interval(cls, value: object) -> float | None:
        return _clamped_optional_float(value, low=0.0, high=1.0)

    @field_validator("top_k", mode="before")
    @classmethod
    def _clamp_top_k(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=0, high=1000)

    @field_validator("repeat_penalty", mode="before")
    @classmethod
    def _clamp_repeat_penalty(cls, value: object) -> float | None:
        return _clamped_optional_float(value, low=0.0, high=3.0)

    @field_validator("seed", mode="before")
    @classmethod
    def _clamp_seed(cls, value: object) -> int | None:
        return _clamped_optional_int(value, low=0, high=2**31 - 1)

    @field_validator("stop", mode="before")
    @classmethod
    def _coerce_stop(cls, value: object) -> list[str] | None:
        """A single string becomes a one-element list; junk becomes unset."""
        if value is None:
            return None
        if isinstance(value, str):
            return [value] if value else None
        if isinstance(value, (list, tuple)):
            cleaned = [str(item) for item in value if isinstance(item, str) and item]
            return cleaned or None
        return None

    @field_validator("keep_alive", mode="before")
    @classmethod
    def _coerce_keep_alive(cls, value: object) -> str | int | None:
        """Go duration string, integer seconds, or ``-1`` (forever); else unset."""
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return max(-1, int(value))
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.lstrip("-").isdigit():
                return max(-1, int(text))
            return text if _GO_DURATION_RE.match(text) else None
        return None

    @field_validator("think", mode="before")
    @classmethod
    def _coerce_think(cls, value: object) -> bool | str | None:
        """``bool`` or one of :data:`OLLAMA_THINK_LEVELS`; else unset."""
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("true", "on", "yes"):
                return True
            if text in ("false", "off", "no"):
                return False
            return text if text in OLLAMA_THINK_LEVELS else None
        return None


class BrainProviderConfig(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    model: str | None = None
    deep_model: str | None = None  # Optional: stronger reasoning model
    # Canonical model for tool-bearing turns; ``cu_model`` is the pre-rename compatibility alias.
    tool_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_model", "cu_model"),
    )
    # Realtime voice pick (model + voice); "" = the adapter default voice.
    voice: str = ""
    auth_mode: str | None = None  # "oauth" | "api_key"
    base_url: str | None = None
    # Self-hosted cards: command that starts the server behind ``base_url``; empty = never spawn.
    launch_command: str = ""
    # Gemini thinking budget, forwarded to ``ThinkingConfig.thinking_budget`` (GeminiBrain only):
    # None = SDK default, 0 = off, -1 = dynamic, > 0 = fixed token cap.
    thinking_budget: int | None = None
    # Per-model Ollama options keyed by tag; TOML-only by design (see
    # config_writer.set_ollama_model_options).
    models: dict[str, OllamaModelOptions] = Field(default_factory=dict)
    # Hugging Face GGUF browsing for the Ollama card; OFF by default (no outbound traffic).
    hf_enabled: bool = False
    # Cadence in hours of the local-models self-check (badge only).
    health_check_hours: float = 6.0
    # Start the local server with the app while local models are in use; ON by default.
    autostart: bool = True

    @field_validator("models", mode="before")
    @classmethod
    def _drop_non_table_models(cls, value: object) -> dict[str, Any]:
        """A hand-edited ``models`` that is not a table of tables is ignored
        rather than rejected (AP-16) — a typo here must not cost a boot."""
        if not isinstance(value, dict):
            return {}
        return {
            str(tag): opts
            for tag, opts in value.items()
            if isinstance(opts, (dict, OllamaModelOptions))
        }

    @property
    def cu_model(self) -> str | None:
        """Compatibility alias for callers that still use the old field name."""
        return self.tool_model

    @cu_model.setter
    def cu_model(self, value: str | None) -> None:
        self.tool_model = value


class BrainPolicyConfig(BaseModel):
    use_routing_model_for_intent: bool = True
    prompt_cache_heartbeat_seconds: int = 240
    voice_switch_patterns: list[str] = Field(
        default_factory=lambda: ["wechsel auf", "switch to", "wechsle zu"]
    )


class BrainRouterPolicyConfig(BaseModel):
    """Policy switches for the tier router (Phase 5)."""

    escalate_on_uncertainty: bool = True
    default_intent_on_low_confidence: str = "spawn_worker"

    model_config = {"extra": "allow"}


class BrainPlausibilityConfig(BaseModel):
    """Plausibility thresholds for the tool-execution guard (Phase 4).

    ask/monitor-tier tools with a low-confidence transcript or a stale wake need voice
    confirmation (ask) or are only logged (monitor). Plausibility is not a risk tier; ``safe``
    tools skip it."""

    model_config = {"extra": "allow"}

    confidence_threshold: float = 0.5
    stale_wake_seconds: float = 30.0


#: Force-spawn modes: ``permissive`` (legacy verb/marker heuristic, over-eager), ``balanced``
#: (default: explicit delegation or a multi-step artefact brief) and ``strict`` (explicit-only). One
#: definition shared by the manager and the LLM spawn gate.
FORCE_SPAWN_MODE_STRICT = "strict"
FORCE_SPAWN_MODE_BALANCED = "balanced"
FORCE_SPAWN_MODE_PERMISSIVE = "permissive"
FORCE_SPAWN_MODES: tuple[str, ...] = (
    FORCE_SPAWN_MODE_STRICT,
    FORCE_SPAWN_MODE_BALANCED,
    FORCE_SPAWN_MODE_PERMISSIVE,
)
DEFAULT_FORCE_SPAWN_MODE = FORCE_SPAWN_MODE_BALANCED


def normalize_force_spawn_mode(value: object) -> str:
    """Return a known force-spawn mode for ``value``; empty or unknown values give
    :data:`DEFAULT_FORCE_SPAWN_MODE`."""
    mode = str(value or "").strip().lower()
    return mode if mode in FORCE_SPAWN_MODES else DEFAULT_FORCE_SPAWN_MODE


#: The SHAPE of a pet id: a built-in slug, ``u`` + 16 hex digits, or ``none`` (docs/pets.md).
_PET_ID_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


#: The voice orb itself, the default "look" (docs/looks.md).
ORB_LOOK_ID = "orb"

#: The SHAPE of a look id (``dodaios.ui.looks.manifest.LOOK_ID_RE``) or "orb".
_LOOK_ID_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")


def normalize_look_id(value: object) -> str | None:
    """Lower-cased, trimmed look id, or ``None`` when it cannot be one (shape only; no separator,
    dot or drive letter)."""
    if not isinstance(value, str):
        return None
    look_id = value.strip().lower()
    return look_id if _LOOK_ID_SHAPE.fullmatch(look_id) else None


def normalize_pet_id(value: object) -> str | None:
    """Lower-cased, trimmed pet id, or ``None``. Shape only; also the path-traversal guard for
    id-to-folder routes."""
    if not isinstance(value, str):
        return None
    pet_id = value.strip().lower()
    return pet_id if _PET_ID_SHAPE.fullmatch(pet_id) else None


class BrainRoutingConfig(BaseModel):
    """Heuristic rules for the deterministic force-spawn classification.

    A hit calls ``spawn_worker`` without an LLM tool choice. Smalltalk never triggers; action verbs
    plus external-system markers always do. Compiled in
    ``dodaios.brain.manager._build_force_spawn_re``."""

    model_config = {"extra": "allow"}

    # Action verbs (DE + EN), matched with ``\b...\w*\b`` so conjugations are caught.
    spawn_verbs: list[str] = Field(
        default_factory=lambda: [
            "umsetz",
            "reparier",
            "fix",
            "behebe",
            "korrigier",
            "implementier",
            "entwickel",
            "refactor",
            "debug",
            "repair",
            # Analysis/investigation
            "analysier",
            "analyz",
            "untersuche",
            "untersuch",
            "pruefe",
            "prüfe",
            "investigate",
            "examine",
            "inspect",
            # File/system action (persona mandate Phase 3)
            "lies",
            "lese",
            "liest",
            "schreib",
            "schreibe",
            "schreibt",
            "bau",
            "baue",
            "baut",
            "oeffne",
            "öffne",
            "oeffnet",
            "öffnet",
            "installier",
            "deinstallier",
            "deploy",
            "zeig",
            "zeige",
            "zeigt",
            "mach",
            "mache",
            "macht",
            "machen",
            # English
            "read",
            "write",
            "build",
            "open",
            "install",
            "show",
            "make",
            # Spawn imperatives ("Spawn sub-agents."): list "spawn" and conjugations explicitly.
            "spawn",
            "starte",
            "start",
            "starten",
            "startet",
            "delegier",
        ]
    )

    # External system markers: a repo/PR/issue mention spawns without an action verb.
    external_system_markers: list[str] = Field(
        default_factory=lambda: [
            "pr",
            "prs",
            "issue",
            "issues",
            "repo",
            "repository",
            "github",
            "gitlab",
            "branch",
            # Agent/worker mentions.
            "subagent",
            "subagenten",
            "sub-agent",
            "sub-agents",
            "openclaw",
            "open-claw",
        ]
    )

    # Trigger phrases for `force_spawn_mode = "strict"`: explicit agent mentions plus deep-research
    # markers.
    force_spawn_phrases: list[str] = Field(
        default_factory=lambda: [
            # Explicit agent / sub-agent mentions; "openclaw" is a retired codename kept as a legacy
            # trigger.
            "openclaw",
            "open claw",
            "open-claw",
            "subagent",
            "subagenten",
            "sub-agent",
            "sub-agenten",
            "sub agent",
            "spawne",
            "spawn",
            "spawnen",
            "spawnt",
            "gespawnt",
            "delegier",
            "delegiere",
            "delegierst",
            "delegiert",
            "delegieren",
            "delegate",
            "delegates",
            # Deep-work markers, with declined forms ("umfassenden Bericht") since \b ignores German
            # case endings.
            "deep dive",
            "deep-dive",
            "deepdive",
            "deep research",
            "deep-research",
            "deepresearch",
            "tiefenrecherche",
            "tiefen-recherche",
            "gruendliche",
            "gruendlicher",
            "gruendlichen",
            "gruendliches",
            "gründliche",
            "gründlicher",
            "gründlichen",
            "gründliches",
            "gruendlich",
            "gründlich",
            "ausfuehrliche",
            "ausfuehrlicher",
            "ausfuehrlichen",
            "ausfuehrliches",
            "ausführliche",
            "ausführlicher",
            "ausführlichen",
            "ausführliches",
            "ausfuehrlich",
            "ausführlich",
            "umfassende",
            "umfassender",
            "umfassenden",
            "umfassendes",
            "umfassend",
            "kompletter deep",
            "kompletten deep",
            "komplette analyse",
            "vollstaendige analyse",
            "vollständige analyse",
        ]
    )

    # Force-spawn mode (values: FORCE_SPAWN_MODES above), read by `BrainManager.force_spawn_mode`.
    # "strict": only `force_spawn_phrases` spawn. "balanced" (default): also the effort test in
    # `dodaios.brain.spawn_gate`; every doubt means no spawn. "permissive": legacy spawn_verbs +
    # external-marker heuristic.
    force_spawn_mode: str = DEFAULT_FORCE_SPAWN_MODE

    @field_validator("force_spawn_mode", mode="before")
    @classmethod
    def _normalize_force_spawn_mode(cls, v: object) -> str:
        return normalize_force_spawn_mode(v)

    # Intelligent router: when the ACTIVE talker cannot emit tool_calls (subscription-CLI brains), a
    # tool-capable provider leads each substantive turn and picks the tool; no tool means fall
    # through to the chosen talker. False restores the narrower action-intent delegation
    # (manager._build_fallback_chain).
    intelligent_router: bool = True

    # Per-mission MCP relevance filter: a worker runs with bypassPermissions, so an off-topic
    # exported server causes long stalls. True exports only task-relevant servers
    # (plugin_relevance.plugin_is_relevant); a fault degrades to exporting all
    # (dodaios.missions.init._assemble_worker_mcp_servers).
    worker_mcp_relevance_filter: bool = True

    # Heavy-research classifier: retired from the spawn decision (strict is explicit-only); fields
    # stay for config compatibility and telemetry/tests. See ADR-0011.
    heavy_research_enabled: bool = True
    heavy_research_verbs: list[str] = Field(
        default_factory=lambda: [
            "recherchier",
            "analysier",
            "untersuch",  # i18n-allow: DE routing verb stems
            "vergleich",
            "evaluier",
            "bewert",  # i18n-allow: DE routing verb stems
            "research",
            "analyz",
            "analys",
            "investigat",
            "compar",
            "evaluat",
            "assess",
            "summari",
        ]
    )
    heavy_research_markers: list[str] = Field(
        default_factory=lambda: [
            "nächsten",
            "naechsten",
            "kommenden",  # i18n-allow: DE routing markers
            "mehrere",
            "verschiedene",
            "schritt für schritt",  # i18n-allow: DE routing markers
            "brauche",
            "benötige",
            "benoetige",
            "checkliste",  # i18n-allow: DE routing markers
            "next two weeks",
            "over the next",
            "step by step",
            "checklist",
        ]
    )
    heavy_research_min_chars: int = 120
    heavy_research_min_verbs_multiclause: int = 2

    # Smalltalk allowlist: a match NEVER spawns, even if the verb or marker heuristic fires.
    smalltalk_allowlist: list[str] = Field(
        default_factory=lambda: [
            # Greetings / Hangup
            "hallo",
            "hi",
            "hey",
            "moin",
            "guten morgen",
            "guten abend",
            "auf wiedersehen",
            "tschuess",
            "tschüss",
            "bye",
            "goodbye",
            "good morning",
            "good evening",
            # Smalltalk
            "wie geht",
            "how are you",
            "how's it going",
            "was machst du",
            "was machen wir",  # neutralise "mach" as a verb trigger
            "danke",
            "thank you",
            "thanks",
            # Casual openers fresh installs misrouted to the action path.
            "was geht",
            "es geht ab",
            "geht ab",
            "alles gut",
            "alles fit",
            "alles klar",
            "passt schon",
            "what's up",
            "whats up",
            "sup",
            # Factual question from memory
            "wie spaet",
            "wie spät",
            "what time",
            "welcher tag",
            "what day",
            "hauptstadt",
            "capital",
        ]
    )


class RouterVisionConfig(BaseModel):
    """Permanent vision in main Jarvis (RouterBrain): the continuous screenshot feed given as
    context.

    Default off: per-turn screenshots roughly doubled think-time. Computer-Use keeps its own
    on-demand capture."""

    enabled: bool = False
    refresh_interval_s: float = 2.0
    max_staleness_s: float = 2.0
    capture_mode: str = "screenshot"  # "screenshot" | "composite"
    max_image_kb: int = 500
    pause_on_idle: bool = True
    voice_pause_phrase_de: str = "privacy"
    voice_pause_phrase_en: str = "privacy mode"
    voice_resume_phrase_de: str = "du darfst wieder sehen"
    voice_resume_phrase_en: str = "vision back on"

    model_config = {"extra": "allow"}


class BrainTierConfig(BaseModel):
    """Tier-specific brain config; empty ``model`` / ``fallback_model`` resolve from
    ``TIER_DEFAULTS_BY_PROVIDER`` via ``dodaios.brain.manager._resolve_tier_model``."""

    model_config = ConfigDict(extra="allow")

    provider: str
    model: str | None = None  # CHANGED — war: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    fallback_provider_2: str | None = None
    fallback_model_2: str | None = None
    policy: BrainRouterPolicyConfig | None = None
    vision: RouterVisionConfig = Field(default_factory=RouterVisionConfig)


class EvidenceDomainsConfig(BaseModel):
    """Evidence-required domains: questions here are never answered from the model's head.

    Either a capability covers the domain (the gate injects a mandatory-tool directive) or the gate
    refuses honestly. Keywords are DE+EN, lowercase, word-boundary, umlaut-normalised
    (dodaios/brain/evidence_gate.py). TOML shape:

        [brain.evidence_domains]
        enabled = true
        [brain.evidence_domains.domains]
        calendar = ["kalender", "termin", ...]
    """

    enabled: bool = True
    domains: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "calendar": [
                "kalender",
                "termin",
                "termine",
                "steht heute",
                "steht morgen",
                "steht diese woche",
                "calendar",
                "appointment",
                "appointments",
            ],
            "email": [
                "mail",
                "mails",
                "e-mail",
                "e-mails",
                "email",
                "emails",
                "posteingang",
                "postfach",
                "inbox",
                "ungelesene",
            ],
            "tasks": [
                "aufgaben",
                "todo",
                "todos",
                "to-do",
                "task",
                "tasks",
            ],
            "repos": [
                "pull request",
                "pull requests",
                "pull-request",
                "pr",
                "prs",
                "issue",
                "issues",
                "repo",
                "repos",
                "repository",
            ],
            "deployments": [
                "deployment",
                "deployments",
                "deploy-status",
                "build-status",
                "build status",
            ],
            # Cloud cost / billing, mapped to the gcloud CLI so a billing question forces a real
            # cli_gcloud call. No bare "kosten"/"cost"/"budget" keywords (a travel budget must not
            # force a billing call).
            "cloud": [
                "google cloud",
                "gcp",
                "gcloud",
                "cloud-cli",
                "cloud cli",
                "google-kosten",
                "google kosten",
                "cloud-kosten",
                "cloud kosten",
                "cloud-rechnung",
                "cloud rechnung",
                "cloud billing",
                "billing account",
                "cloud budget",
                "cloud-budget",
                "gcp budget",
                "gcloud budget",
                "abrechnung",
                "abrechnungen",
                "guthaben",
                "billing",
            ],
            # Local screen / window-activity history: no tool serves it, so the gate answers
            # honestly. Keywords are phrase-specific, never a bare "offen"/"open".
            "activity": [
                "offen hatte",
                "offen gehabt",
                "heute offen",
                "was war offen",
                "was hatte ich auf",
                "geoeffnet hatte",
                "geoeffnete fenster",
                "geoeffneten fenster",
                "offene fenster",
                "offene programme",
                "welche fenster",
                "welche programme",
                "welche anwendungen",
                "welche apps",
                "geoeffnete anwendungen",
                "geoeffneten anwendungen",
                "am rechner gemacht",
                "am rechner offen",
                "am pc gemacht",
                "am computer gemacht",
                "heute gemacht",
                "heute am rechner",
                "woran hab ich gearbeitet",
                "woran habe ich gearbeitet",
                "what did i have open",
                "what was open",
                "what did i do today",
                "what have i been working on",
                "what was i working on",
                "which windows",
                "which apps",
                "windows were open",
                "apps were open",
                "my activity today",
                "earlier today",
            ],
        }
    )


class BrainConfig(BaseModel):
    # populate_by_name=True lets old and new TOML keys populate the aliased fields.
    model_config = ConfigDict(populate_by_name=True)

    primary: str = "claude-api"
    # For deep/code intents an API-key provider can be preferred.
    deep_brain: str | None = None
    routing_provider: str = "claude-api"
    routing_model: str = "claude-sonnet-4-6"
    local_fallback: str = "claude-api"
    local_fallback_model: str = "claude-haiku-4-5-20251001"
    providers: dict[str, BrainProviderConfig] = Field(default_factory=dict)
    policy: BrainPolicyConfig = Field(default_factory=BrainPolicyConfig)
    # Per-response output ceiling (tokens): a safety ceiling, not a target; without it a long spoken
    # answer is read aloud truncated mid-sentence.
    max_tokens: int = Field(default=32_768, ge=256, le=32_768)
    # Only ``router`` remains as a tier; the heavy worker runs as a subprocess via Mission Manager
    # (docs/jarvis-agents-bridge.md §11). ``worker`` also accepts the old ``[brain.sub_jarvis]``
    # key.
    router: BrainTierConfig | None = None
    worker: BrainTierConfig | None = Field(
        default=None,
        validation_alias=AliasChoices("worker", "sub_jarvis"),
    )
    # Realtime-tier provider + cross-family fallback chain (AP-22); None until the user opts in.
    realtime: BrainTierConfig | None = None
    # Canonical provider for tool-bearing turns; ``computer_use`` below is the compatibility alias.
    tool_model: BrainTierConfig | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_model", "computer_use"),
    )
    # Reply language pin: "auto" mirrors the input language, a code forces it for every reply
    # (``BrainManager._reply_language_directive``, ``config_writer.set_reply_language``).
    reply_language: str = "auto"
    # Initiative level: "off" answers only what was asked, "balanced" at most one grounded idea,
    # "high" up to two plus heads-ups on close dated plans. Never authorises an action
    # (``dodaios.brain.proactivity``).
    proactivity: Literal["off", "balanced", "high"] = "balanced"
    routing: BrainRoutingConfig = Field(default_factory=BrainRoutingConfig)
    plausibility: BrainPlausibilityConfig = Field(
        default_factory=BrainPlausibilityConfig,
    )
    evidence_domains: EvidenceDomainsConfig = Field(
        default_factory=EvidenceDomainsConfig,
    )
    healthcheck_on_start: bool = True
    # Frontier model auto-switch: True lets the boot hook rewrite ``[brain.providers.<p>].model`` to
    # a newer model on every start. Default False: a newer model is adopted only by an explicit user
    # pick.
    frontier_auto_apply: bool = False
    # Two-turn spoken confirmation: a consequential ``ask``-tier tool on a conversational turn is
    # deferred into a spoken "yes" instead of a UI approval a voice user cannot give. False uses UI
    # approval.
    voice_confirm: bool = True
    # Show the model a small frozen core of tools; the rest sit behind ``find_tools``. Better choice
    # and a stable prompt-cache prefix with hundreds of tools. Small-window models always defer.
    defer_tools: bool = True

    @field_validator("proactivity", mode="before")
    @classmethod
    def _known_proactivity(cls, value: object) -> str:
        # A hand-typed value must not leave the backend unbootable: clear "off" values are off, any
        # other unknown level falls back to the default with a warning.
        if value is False:
            return "off"
        level = value.strip().casefold() if isinstance(value, str) else ""
        if level in ("off", "balanced", "high"):
            return level
        if level in ("false", "none", "no", "0", "disabled"):
            return "off"
        logging.getLogger(__name__).warning(
            "[brain] proactivity = %r is not off/balanced/high; using balanced", value
        )
        return "balanced"

    @property
    def computer_use(self) -> BrainTierConfig | None:
        """Compatibility alias for the old ``[brain.computer_use]`` tier."""
        return self.tool_model

    @computer_use.setter
    def computer_use(self, value: BrainTierConfig | None) -> None:
        self.tool_model = value


class LegacyCuratorConfig(BaseModel):
    """Soft-disable gate for the legacy :class:`dodaios.memory.curator.Curator` (superseded by the
    WikiCurator).

    Stops the legacy writer without deleting the package; pinned in ``scripts/config-soll.json``
    against drift."""

    enabled: bool = False


class JarvisLearningConfig(BaseModel):
    """``[memory.learning]``: background review of finished conversations into two bounded notebooks
    (USER.md, MEMORY.md) that reach the brain and realtime prompts. Every key is read by
    ``dodaios.memory.learning`` (AP-31)."""

    model_config = {"extra": "allow"}

    #: Master switch: off stops reviews and removes the notebooks from prompts.
    enabled: bool = True
    #: A conversation is reviewed once, after a call ends or it has been quiet this long, and only
    #: if a deterministic filter found a personal fact, preference, correction or plan in it.
    idle_review_seconds: float = Field(default=300.0, ge=10.0, le=86_400.0)
    #: Safety net for very long conversations: also review after this many turns.
    review_every_turns: int = Field(default=30, ge=1, le=200)
    #: Prompt budget per notebook (rides on every turn); at 125 % new entries are refused until
    #: merged.
    user_budget_chars: int = Field(default=1_500, ge=300, le=40_000)
    memory_budget_chars: int = Field(default=1_000, ge=300, le=40_000)
    #: Reviewer override: provider id and optionally its model. Empty = the lead chat's own seat
    #: (``society.seat_brain``); no other provider is ever asked.
    provider: str = ""
    model: str = ""
    timeout_s: float = Field(default=90.0, ge=5.0, le=600.0)


class MemoryVaultConfig(BaseModel):
    """``[memory.vault]``: the personal memory vault (ADR-0044); every key is read by
    ``dodaios.memory.vault.runtime`` (AP-31)."""

    #: Off keeps the vault closed; the learned notebooks stay in charge.
    enabled: bool = True
    #: Vault file; empty = ``<data dir>/memory/vault.db``.
    path: str = ""
    #: Budget of the always-on memory block in every prompt (voice gets half).
    profile_max_chars: int = Field(default=2_400, ge=400, le=20_000)


class MemoryConfig(BaseModel):
    # No chroma backend exists any more; default to the sqlite store.
    archival_store: str = "sqlite"
    retention_days_recall: int = 90
    data_dir: str = "./data"
    legacy_curator: LegacyCuratorConfig = Field(default_factory=LegacyCuratorConfig)
    learning: JarvisLearningConfig = Field(default_factory=JarvisLearningConfig)
    vault: MemoryVaultConfig = Field(default_factory=MemoryVaultConfig)


class SafetyWhitelistConfig(BaseModel):
    commands: list[str] = Field(default_factory=list)


class SafetyBlacklistConfig(BaseModel):
    commands: list[str] = Field(default_factory=list)


class SafetyConfig(BaseModel):
    # App-owned executions run without permission prompts unless the person selects Ask.
    approval_mode: Literal["bypass", "ask"] = "bypass"
    #: Permission mode a NEW Society agent starts with; a child agent is never looser than its
    #: creator.
    agent_approval_mode: Literal["bypass", "ask", "always_ask"] = "bypass"
    default_tier: RiskTier = "safe"
    always_confirm_tiers: list[RiskTier] = Field(default_factory=lambda: ["ask"])
    always_block_tiers: list[RiskTier] = Field(default_factory=lambda: ["block"])
    whitelist: SafetyWhitelistConfig = Field(default_factory=SafetyWhitelistConfig)
    blacklist: SafetyBlacklistConfig = Field(default_factory=SafetyBlacklistConfig)
    # How long an armed approval gate waits before the default deny. Short on purpose: an unattended
    # ask-tier call should fail fast so the worker sees the denial and adapts (ADR-0031/W3).
    tool_approval_timeout_s: float = Field(default=60.0, ge=5.0, le=600.0)


class SkillsConfig(BaseModel):
    """Deterministic skill matching; author-written voice triggers are unaffected by these knobs."""

    #: Master switch for the relevance layer. Off = author regex + the LLM listing only.
    relevance_enabled: bool = True

    #: While true, a FIRE-band match is only RECORDED (shadow mode; ``GET /api/skills/match-log``).
    #: Shipped false; the guards (dispatching-class veto, margin, definitional-question guard,
    #: min-band floor) stay armed.
    relevance_shadow: bool = False

    #: Weakest band allowed to capture a turn; anything below stays a suggestion.
    auto_fire_min_band: Literal["fire", "narrow"] = "fire"

    #: Optional threshold overrides; ``None`` keeps the calibrated defaults from
    #: dodaios/skills/relevance.py. Set only from scripts/skill_relevance_calibrate.py, never to
    #: hide one over-fire (AP-27).
    fire_threshold: float | None = None
    hint_threshold: float | None = None

    #: How many narrowed candidates ride the per-turn context on a NARROW turn.
    narrow_candidates: int = 3


class JarvisAgentNotificationConfig(BaseModel):
    """Notification behaviour of the worker harness (bridge docs §4.2): voice readback only while
    listening, toast always (``_on_announcement`` bus, pipeline.py:647)."""

    model_config = ConfigDict(extra="forbid")

    # Default is the bus bypass — see pipeline._on_announcement.
    via: str = "announcement_bus"
    toast: bool = True
    voice_when_active: bool = True


class JarvisAgentHarnessConfig(BaseModel):
    """Top-level ``[harness.jarvis_agent]`` config (also the legacy ``[harness.openclaw]`` alias).

    INERT: no ``jarvis_agent`` harness is registered, so ``enabled = true`` has no effect and boot
    warns (``warn_if_phantom_worker_harness``). Heavy sub-agent work runs through the
    Mission-Manager. Schema: ``docs/jarvis-agents-bridge.md §4.2``. An empty ``model`` resolves the
    active provider's frontier-pro (AD-6); ``version`` is required whenever the block exists
    (AD-21), else the bridge is inactive."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # AD-21: pinned upstream version, NO default (an empty one means "whatever npm installs").
    version: str
    binary_path: str = "openclaw"
    # Empty = bridge resolves frontier-pro from cfg.brain.primary (AD-6); set to pin a model.
    model: str | None = None
    # Time-cap fixed per AD-19; per-mission override deliberately not allowed.
    time_cap_min: int = Field(default=30, ge=1, le=240)
    # Up to N Jarvis-Agent missions in parallel; the fourth lands in the queue (AD-13).
    concurrency: int = Field(default=3, ge=1, le=10)
    # AD-20 reserved for v2 cost-cap retrofit. v1 None = no cap.
    cost_cap_eur: float | None = Field(default=None, ge=0.0)
    # AD-23: per-mission workspace isolation. The bridge creates ``<mission_id>/openclaw_state/``
    # and sets MISSION_STATE_DIR so cross-mission state cannot leak (AP-OC15).
    state_dir_root: str = "data/openclaw_state"

    notification: JarvisAgentNotificationConfig = Field(
        default_factory=JarvisAgentNotificationConfig,
    )


class HarnessConfig(BaseModel):
    """Config for the harness dispatcher (Phase 4)."""

    # populate_by_name=True accepts the Python field name next to the renamed alias.
    model_config = ConfigDict(populate_by_name=True)

    enabled: list[str] = Field(default_factory=lambda: ["python-script"])
    default_timeout_s: int = 600
    default_risk_tier: RiskTier = "monitor"
    # Output limit per harness turn, so large build logs cannot blow the context window.
    max_output_chars: int = 4000
    # Per-harness overrides: e.g. {"jarvis_agent": {"model": "opus", "max_turns": 10}}
    per_harness: dict[str, dict[str, object]] = Field(default_factory=dict)
    # Jarvis-Agent worker harness; None = block missing, bridge inactive (``version`` required if
    # present). ``validation_alias`` accepts the old [harness.openclaw] key.
    jarvis_agent: JarvisAgentHarnessConfig | None = Field(
        default=None,
        validation_alias=AliasChoices("jarvis_agent", "openclaw"),
    )


class MCPServerConfig(BaseModel):
    """Config for Jarvis-as-MCP-server (Phase 4)."""

    enabled: bool = True
    transport: str = "stdio"  # "stdio" | "http"
    http_host: str = "127.0.0.1"
    http_port: int = 47822
    auth_token_env: str = "JARVIS_MCP_TOKEN"  # noqa: S105 — env var NAME, not a secret


class AudioConfig(BaseModel):
    input_device: str = "auto-headset"
    output_device: str = "auto-headset"
    # Optional device-name priority for the "auto-headset" resolver: case-insensitive substrings,
    # earlier wins, matched BEFORE the built-in list; ignored when input_device/output_device is
    # explicit.
    output_device_priority: list[str] = Field(
        default_factory=list,
        description=(
            "Preferred output-device name substrings (highest priority first); "
            "consulted before the generic headset auto-detection."
        ),
    )
    input_device_priority: list[str] = Field(
        default_factory=list,
        description=(
            "Preferred input (microphone) device name substrings (highest "
            "priority first); consulted before the generic auto-detection."
        ),
    )
    echo_cancellation: bool = True
    sample_rate: int = 16000
    frame_ms: int = 10


class UIConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    tray_enabled: bool = True
    admin_api_port: int = 47821
    startup_chime: bool = True
    # Master switch for synthesized UI earcons; spoken TTS is unaffected.
    sound_effects: bool = True
    # Interface language of the whole app; stored in the backend so a voice command or the Control
    # API can switch the open UI live. Distinct from brain.reply_language.
    language: Literal["en", "de", "es", "pt", "zh"] = "en"
    # Colour theme: "dark" (default), "light" or "system". Persisted here so the choice survives a
    # cleared web store and the native window frame is painted before the web view loads
    # (dodaios/ui/shell/window.py).
    theme: Literal["dark", "light", "system"] = "dark"
    # Dev mode: load the frontend from a Vite dev server (ENV JARVIS_DEV=1 or --dev).
    dev_mode: bool = False
    vite_dev_url: str = "http://localhost:5173"
    # ENV variable carrying the process-scoped UI bootstrap token (exchanged for an HttpOnly cookie
    # by AuthGate).
    auth_token_env: str = "JARVIS_UI_TOKEN"  # noqa: S105 — env var NAME, not a secret
    # Browser lock: True asks for the Control Key even on loopback. A headerless L4 tunnel on the
    # same machine looks local, so whoever forwards the port must turn this ON
    # (surface_security.open_access_granted).
    require_browser_login: bool = False
    # Overlay style: "jarvis_bar" (default), "voice_orb" or "none"; old pet styles load as the bar.
    orb_style: str = "jarvis_bar"
    bar_persistent: bool = True
    # Hex accent the bar lights up with during activity (gold on-brand).
    bar_accent: str = "#e7c46e"
    # Bar size multiplier (0.5-2.0, mirrors renderer.USER_SIZE_MIN/MAX); this validator only
    # sanitizes corruption.
    bar_size_scale: float = 1.0
    # Follow the mouse across monitors, keeping the SAME relative spot; hosts without per-monitor
    # geometry stay single-monitor (dodaios/ui/dodaiosbar/interaction.py).
    bar_follow_cursor_monitor: bool = True
    # Active pet (docs/pets.md): built-in or user-created ``u...`` id. A missing id falls back where
    # it is resolved; the validator sanitizes only the SHAPE. Old desktop-pet keys are ignored
    # extras.
    pet_id: str = DEFAULT_PET_ID
    # In-app look where the voice orb sits (docs/looks.md): "orb" or a look id; a missing look falls
    # back to the orb.
    look_id: str = ORB_LOOK_ID
    # Remembered "open with" choice for Outputs artifacts ("default", "browser" or an editor key);
    # empty = ask.
    preferred_opener: str = ""

    @field_validator("orb_style", mode="before")
    @classmethod
    def _normalize_orb_style(cls, v: object) -> object:
        # Legacy values map onto today's styles (dodaios.ui.overlay_styles.LEGACY_STYLE_ALIASES).
        from dodaios.ui.overlay_styles import LEGACY_STYLE_ALIASES  # noqa: PLC0415

        if isinstance(v, str):
            return LEGACY_STYLE_ALIASES.get(v.strip().lower(), v)
        return v

    @field_validator("bar_size_scale", mode="before")
    @classmethod
    def _clamp_bar_size_scale(cls, v: object) -> object:
        # Clamp a persisted bar size into 0.5-2.0; non-numeric/non-finite falls back to 1.0.
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        if f != f or f in (float("inf"), float("-inf")):  # NaN / ±inf
            return 1.0
        return max(0.5, min(2.0, f))

    @field_validator("look_id", mode="before")
    @classmethod
    def _sanitize_look_id(cls, v: object) -> object:
        # A hand-edited value that is not id-shaped falls back to the orb.
        return normalize_look_id(v) or ORB_LOOK_ID

    @field_validator("pet_id", mode="before")
    @classmethod
    def _sanitize_pet_id(cls, v: object) -> object:
        # Lower-case and trim; a non-id-shaped value falls back to the default pet so a corrupt toml
        # cannot brick load.
        return normalize_pet_id(v) or DEFAULT_PET_ID


class DuckingConfig(BaseModel):
    """Audio ducking ("Mute music while dictating"), default off: lowers every OTHER app's audio for
    a voice session and restores it after. Windows: per-app mute via pycaw (not our own PID). macOS:
    AppleScript
    duck of known players plus an opt-in master fallback."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    # Grace before restoring other apps' volume (lets the TTS tail finish).
    restore_delay_ms: int = 400
    # App names never to mute (Windows process names or plain names); empty = mute all others.
    never_mute: list[str] = Field(default_factory=list)
    # Volume other apps are ducked to (0 = full duck/mute of the app volume).
    duck_volume_percent: int = Field(default=0, ge=0, le=100)
    # macOS only: if no known player was ducked, lower the MASTER output volume (also lowers our own
    # TTS).
    macos_master_fallback: bool = False


class MusicConfig(BaseModel):
    """Music connectors: two services, one domain.

    ``preferred_service`` picks the connector for a request naming no service when Spotify AND
    YouTube Music are connected. ``playback`` says where YouTube Music plays: hidden in-app player
    (``background``) or system browser (``browser``, also the fallback). Vocabulary:
    ``dodaios/core/music_constants.py``."""

    model_config = ConfigDict(extra="allow")

    preferred_service: Literal["auto", "spotify", "youtube_music"] = "auto"
    playback: Literal["background", "browser"] = "background"

    @field_validator("preferred_service", mode="before")
    @classmethod
    def _sanitize_preferred_service(cls, v: object) -> object:
        # An unknown persisted value falls back to "auto" instead of bricking the load.
        from dodaios.core.music_constants import MUSIC_SERVICE_AUTO, MUSIC_SERVICES

        if isinstance(v, str) and v.strip().lower() in MUSIC_SERVICES:
            return v.strip().lower()
        return MUSIC_SERVICE_AUTO

    @field_validator("playback", mode="before")
    @classmethod
    def _sanitize_playback(cls, v: object) -> object:
        from dodaios.core.music_constants import (
            MUSIC_PLAYBACK_BACKGROUND,
            MUSIC_PLAYBACK_MODES,
        )

        if isinstance(v, str) and v.strip().lower() in MUSIC_PLAYBACK_MODES:
            return v.strip().lower()
        return MUSIC_PLAYBACK_BACKGROUND


def _assert_music_literals_match_constants() -> None:
    """The Literals on ``MusicConfig`` must spell exactly the tuples in ``music_constants``."""
    from dodaios.core.music_constants import MUSIC_PLAYBACK_MODES, MUSIC_SERVICES

    fields = MusicConfig.model_fields
    if set(get_args(fields["preferred_service"].annotation)) != set(MUSIC_SERVICES):
        raise RuntimeError("MusicConfig.preferred_service drifted from MUSIC_SERVICES")
    if set(get_args(fields["playback"].annotation)) != set(MUSIC_PLAYBACK_MODES):
        raise RuntimeError("MusicConfig.playback drifted from MUSIC_PLAYBACK_MODES")


_assert_music_literals_match_constants()


class AutostartConfig(BaseModel):
    """Login autostart. Default ON; a headless host registers nothing."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    # Windows: maps to the fallback shortcut's WindowStyle (7 = tray, 1 = normal); the
    # logon scheduled task launches visibly regardless. macOS/Linux ignore it.
    start_minimized: bool = False
    # Start only the background agent service at login (``autostart.command.resolve_launch_spec``).
    background_only: bool = False


class BackgroundConfig(BaseModel):
    """What keeps running after the app closes (:mod:`dodaios.core.background_service`)."""

    model_config = ConfigDict(extra="allow")
    keep_agents_running: bool = True
    # Opt-in; a client never stops this server or inherits its provider credentials.
    persistent_server: bool = False
    server_url: str = ""

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: str) -> str:
        if not value.strip():
            return ""
        from dodaios.core.server_endpoint import server_endpoint

        return server_endpoint(value)


class TelemetryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    flight_recorder: bool = True
    # Days to keep screenshot blobs (data/flight_recorder/blobs/); 0 = keep forever.
    flight_recorder_retention_days: int = 10
    otel_endpoint: str = ""
    metrics_port: int = 9090
    log_level: str = "INFO"


class JarvisAgentsOutputConfig(BaseModel):
    """Config for Jarvis-Agent output management, GitHub push, and verification."""

    github_auto_push: bool = False
    github_repo_url: str = ""
    max_verification_iterations: int = 3
    output_dir_mirror_desktop: bool = True


class SecurityConfig(BaseModel):
    """Gate for sensitive UI actions; empty hash = locked (``core.admin_password`` sets it)."""

    admin_password_hash: str = ""


class TelegramConfig(BaseModel):
    """Telegram channel. Token: Credential Manager. Empty ``allowed_user_ids`` replies to nobody."""

    chat_id: str = ""
    parse_mode: str = "Markdown"

    enabled: bool = False
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_chat_ids: list[int] = Field(default_factory=list)
    group_policy: str = "allowlist"  # "open" | "allowlist" | "disabled"
    require_mention: bool = True
    polling_interval_s: float = 1.0
    auto_register_friends: bool = False
    # Marketplace connect cannot know the ID: the first private sender claims an empty list.
    pair_on_first_private_message: bool = True


class TwilioConfig(BaseModel):
    """Twilio telephony (Media Streams). Auth Token: Credential Manager. Empty ``allowed_callers``
    takes no inbound call; webhook ``{public_base_url}/api/telephony/voice``.
    """

    enabled: bool = False
    account_sid: str = ""  # AC... (account identifier, not a secret)
    phone_number: str = ""  # E.164, e.g. +49...
    allowed_callers: list[str] = Field(default_factory=list)  # E.164 numbers that may call in
    public_base_url: str = ""  # https://jarvis.example.com (no trailing slash)
    greeting: str = ""  # optional spoken welcome; empty = neutral name-based default
    language_code: str = "de-DE"  # default TTS/STT language hint
    fallback_mode: str = "media"  # reserved: "media" (v1) | "conversationrelay"
    max_call_seconds: int = 600  # safety cap to end runaway calls


class DiscordConfig(BaseModel):
    """Discord channel (needs the Message Content Intent). Token: Credential Manager.

    Empty ``allowed_user_ids`` replies to nobody; ``pair_on_first_dm`` lets the first DM claim it.
    """

    enabled: bool = False
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_channel_ids: list[int] = Field(default_factory=list)
    guild_policy: str = "allowlist"  # "open" | "allowlist" | "disabled"
    require_mention: bool = True
    auto_register_friends: bool = False
    pair_on_first_dm: bool = True


#: Slack Web API base. Only Slack or a local stand-in: the bot token travels with every call.
SLACK_API_BASE_URL = "https://slack.com/api"


class SlackChannelConfig(BaseModel):
    """Slack channel: the owner's own Slack app (not the plugin). Tokens: Credential Manager.

    Empty ``allowed_user_ids`` answers nobody; the first DM after connecting claims it
    (``pair_on_first_dm``) unless the sign-in already named the owner.
    """

    enabled: bool = False
    allowed_user_ids: list[str] = Field(default_factory=list)
    pair_on_first_dm: bool = True
    #: Off by default. On: a channel mention is answered in a thread, from the owner's
    #: private conversation, and every member of that channel can read it.
    answer_mentions: bool = False
    team_id: str = ""
    api_base_url: str = SLACK_API_BASE_URL


class IntegrationsConfig(BaseModel):
    """External service integrations (Telegram, Discord, Slack, Twilio, ...)."""

    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)
    twilio: TwilioConfig = Field(default_factory=TwilioConfig)


CHANNEL_SECRET_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "telegram": (("telegram_bot_token", "TELEGRAM_BOT_TOKEN"),),
    "discord": (("discord_bot_token", "DISCORD_BOT_TOKEN"),),
    "slack": (("slack_bot_token", "SLACK_BOT_TOKEN"), ("slack_app_token", "SLACK_APP_TOKEN")),
    "twilio": (("twilio_auth_token", "TWILIO_AUTH_TOKEN"),),
}


class BoardFederationConfig(BaseModel):
    """Board backend federation (``board-backend/README.md``); keys live in the vault."""

    enabled: bool = False
    backend_url: str = ""  # e.g. "https://board.example.com"
    sync_interval_s: int = 60
    display_name: str = ""  # empty → user_data_dir owner


class BoardBioConfig(BaseModel):
    """Profile generator knobs. No model default on purpose: ``board/bio_brain.py`` picks one."""

    model_config = {"extra": "allow"}

    temperature: float = Field(default=0.85, ge=0.0, le=2.0)
    max_tokens: int = Field(default=400, ge=80, le=2000)
    override_provider: str | None = None
    override_model: str | None = None


class BoardConfig(BaseModel):
    """Container for all board subsystems."""

    federation: BoardFederationConfig = Field(default_factory=BoardFederationConfig)
    bio: BoardBioConfig = Field(default_factory=BoardBioConfig)


class VisionContextConfig(BaseModel):
    """``[vision]``: active-window hint on ``spawn_worker``. OFF (UIA lookup adds 200-400 ms)."""

    model_config = {"extra": "allow"}

    context_hint_on_spawn: bool = False
    timeout_s: float = 0.25  # mandate: 250 ms latency cap per spawn


class ScreenContextConfig(BaseModel):
    """``[screen_context]``: one on-request capture, never continuous (docs/screen-context.md)."""

    model_config = {"extra": "allow"}

    enabled: bool = True

    #: App names or window-title fragments that are never captured at all.
    #: Case-insensitive substring match on app name and title (survives version bumps).
    #: Empty by default: the user states what is sensitive (§3).
    denylist: list[str] = Field(default_factory=list)

    #: Extra ``"label:regex"`` redaction rules on top of the shipped set; the label shows in the
    #: report.
    sensitive_patterns: list[str] = Field(default_factory=list)

    include_default_patterns: bool = True

    max_text_chars: int = 32_000

    #: Seconds an unconsumed capture stays in memory (also dropped on first use).
    ttl_s: float = 120.0

    #: Seconds the deck previews the last picture (separate in-memory copy,
    #: ``screen_context/last_frame.py``; served by ``GET /api/deck/frame``). 0 = off.
    deck_preview_s: float = 120.0

    #: OCR for windows with no accessibility text; needs a local OCR engine (base install stays
    #: torch-free, §3).
    ocr_enabled: bool = False


class AppshotConfig(BaseModel):
    """``[appshot]``: front-window capture; Screen Context privacy rules and master switch apply."""

    model_config = {"extra": "allow"}

    #: Global shortcut. ``alt+alt`` / ``shift+shift`` / ``ctrl+ctrl`` = both keys of
    #: the pair together (``appshot.gesture``); otherwise shared hotkey syntax; "" = off.
    hotkey: str = "alt+alt"

    #: Shortcut for an AREA appshot (drag a rectangle, ``appshot.region``). Same syntax
    #: as ``hotkey``; "" = off. Both-Shift pairs with both-Alt and collides with nothing.
    region_hotkey: str = "shift+shift"

    #: Off: releasing the drag captures at once. On: the area stays adjustable until
    #: Enter or double-click. The picker toolbar flips it.
    region_keep_area: bool = False

    recording_hotkey: str = "ctrl+shift+9"

    recording_resolution: Literal["720p", "1080p", "1440p", "2160p", "native"] = "1080p"
    recording_fps: Literal[30, 60, 120] = 60
    recording_bitrate_mbps: int = Field(default=12, ge=1, le=100, strict=True)
    recording_system_audio: bool = False

    #: ``auto``: the running voice call, else the next message; ``message``; ``voice``.
    target: Literal["auto", "message", "voice"] = "auto"

    #: Also gated by ``[ui].sound_effects``.
    sound: bool = True

    effect: bool = True

    card_seconds: int = Field(default=6, ge=0, le=600)

    library: bool = True

    keep_newest: int = Field(default=0, ge=0, le=500)

    #: Also copy shortcut/button appshots to the clipboard; looks the assistant takes never copy.
    copy_to_clipboard: bool = True


class JarvisXConfig(BaseModel):
    """``[jarvisx]``: the built-in screenshot and screen recorder (``dodaios/dodaiosx/``)."""

    model_config = {"extra": "allow"}

    enabled: bool = True

    #: Global shortcuts (shared hotkey syntax, "" = off). Ctrl+Shift+digit avoids the OS
    #: screenshot keys (Win+Shift+S, Cmd+Shift+3/4/5).
    hotkey_region: str = "ctrl+shift+2"
    hotkey_window: str = "ctrl+shift+3"
    hotkey_fullscreen: str = "ctrl+shift+1"
    hotkey_record_region: str = "ctrl+shift+5"
    hotkey_record_fullscreen: str = "ctrl+shift+6"
    hotkey_stop_recording: str = "ctrl+shift+4"

    thumbnail_persist: bool = False
    #: Clamped to 1..3600 where read, so a hand-edited value cannot break loading.
    thumbnail_dismiss_s: int = 30

    save_dir: str = ""

    copy_to_clipboard: bool = True

    #: Also gated by ``[ui].sound_effects``.
    sound: bool = True

    effect: bool = True

    #: Keep only the newest N screenshots and N recordings (files too); 0 = all. Clamped 0..1000.
    keep_newest: int = 0


class ComputerUseConfig(BaseModel):
    """``[computer_use]`` for ``harness/screenshot_only_loop.py``. ON by default; safe without
    the flag (empty whitelist keeps risky actions ask-tier; no vision/display = "not active").
    """

    model_config = {"extra": "allow"}

    enabled: bool = True
    # Border + "Esc to cancel" pill (dodaios/cu/indicator); Escape-to-cancel is armed regardless.
    screen_indicator: bool = True
    # "v2" = dodaios/cu/engine.py. Legacy values load but route to v2 (their loops lack the guards).
    engine: Literal["v2", "current", "june13", "stable"] = "v2"
    # Coordinate space of the model's clicks; "auto" = the brain's ``coordinate_convention``, else
    # the provider's (Gemini 0-1000 normalized; Claude/OpenAI pixels).
    coordinate_space: Literal["auto", "normalized_1000", "image_pixels"] = "auto"
    # "primary": move the window to the main monitor and follow it (an unmovable one is used
    # where it is); "foreground": follow unmoved; "all": virtual desktop. The primary is
    # identified natively, never by origin (0,0) (``vision.screenshot.cu_capture_strategy``).
    monitor: Literal["primary", "foreground", "all"] = "primary"
    # "primary" (OS), "largest", or an id (name substring / 1-based index); unknown -> OS primary.
    main_monitor: str = "primary"
    # "window" crops to the target window and clamps clicks into it; "monitor" = rollback.
    capture_scope: Literal["window", "monitor"] = "window"
    # Maximize the target on its own monitor first. OFF: it rearranges the layout uninvited and
    # window-scoped capture already gives a full view. Never crosses monitors (mixed-DPI trap).
    normalize_window: bool = False
    strict_verify: bool = True
    max_steps: int = Field(default=100, ge=1, le=1000)
    max_replans: int = Field(default=2, ge=0, le=40)
    per_step_timeout_s: float = Field(default=30.0, gt=0.0, le=300.0)
    # Wall-clock ceiling per mission (TimeoutError); at 6-15 s per step it must outlast
    # ``step_budget``. Read at brain build: restart to apply.
    mission_timeout_s: float = Field(default=600.0, ge=10.0, le=3600.0)
    think_timeout_cap_s: float = Field(default=10.0, gt=0.0, le=60.0)
    image_max_bytes: int = Field(default=300_000, ge=20_000, le=2_000_000)
    # Longest-side cap; models ground small controls better near XGA/WXGA than on 2K/4K. 0 = off.
    image_max_dimension: int = Field(default=1366, ge=0, le=8192)
    settle_scale: float = Field(default=1.0, ge=0.0, le=2.0)
    # Cheaper model for trivial steps; "" = normal model (routing not wired, TODO L9).
    fast_step_model: str = Field(default="")
    verify_after_each_step: bool = True
    # Zoom-refine BEFORE clicking. OFF: it added a model call and a failure path to every click;
    # the known-good pipeline refines only after a verified miss.
    zoom_before_click: bool = False
    # Snap a missed click to the nearest accessibility element. OFF: it snapped to large
    # containers' centers and skipped the LLM refine (BUG-CU-UIASNAP).
    uia_click_fallback: bool = False
    announce_progress: bool = False
    # No model-unavailable retry here, so the default must be reachable on a subscription.
    plan_model: str = "claude-opus-4-8"
    step_model: str = "claude-haiku-4-5-20251001"
    step_budget: int = Field(default=100, ge=1, le=1000)
    # Cursor glides with a halo + pulse. OFF: the fullscreen WS_EX_LAYERED overlay is fragile
    # on multi-monitor/new GPU drivers (``scripts/virtual_cursor_demo.py``). Glide 0 = instant.
    show_virtual_cursor: bool = False
    cursor_glide_ms: int = Field(default=0, ge=0, le=2000)
    # With Gemini, decide steps via its native ``computer_use`` tool; failure falls back per step.
    # OFF until live-verified (preview model). ADR-0023.
    prefer_native: bool = False
    native_model: str = "gemini-3-flash-preview"


class LocalActionConfig(BaseModel):
    """Low-latency local action fast path settings."""

    enabled: bool = True
    direct_timeout_s: float = Field(default=3.0, gt=0.0, le=30.0)
    harness_timeout_s: float = Field(default=30.0, gt=0.0, le=300.0)


class PerformanceConfig(BaseModel):
    """Latency optimisations with rollback switches; ``streaming_tts`` sends sentence chunks to TTS.
    The prompt/context caches (``cache_control`` / Gemini cache, 1 h TTL) default off.
    """

    model_config = {"extra": "allow"}

    streaming_tts: bool = True
    anthropic_prompt_cache: bool = False
    gemini_context_cache: bool = False
    # Sentences synthesized ahead of playback (``_brain_streaming``); 1 bounds barge-over waste.
    tts_lookahead_sentences: int = 1
    conditional_vision: bool = True
    # Per-turn context goes in the user message so the static prefix hits the cache.
    cache_optimized_prompt: bool = True

    @field_validator("tts_lookahead_sentences")
    @classmethod
    def _floor_lookahead(cls, v: int) -> int:
        return max(1, int(v))


class LatencyConfig(BaseModel):
    """Hot-path latency instrumentation; off makes ``LatencyTracker`` a near-zero no-op."""

    model_config = {"extra": "allow"}

    enabled: bool = True
    log_jsonl: bool = False
    log_path: str = "state/latency_log.jsonl"


class ReviewRubricConfig(BaseModel):
    """A review rubric: the criteria the reviewer works through for a task class."""

    items: list[str] = Field(default_factory=list, min_length=1)


def _default_rubrics() -> dict[str, ReviewRubricConfig]:
    """Default rubrics from plan §6.4."""
    return {
        "default": ReviewRubricConfig(
            items=[
                "task_completion",
                "tool_output_fidelity",
                "completeness",
                "voice_friendliness",
                "tool_use_efficiency",
            ]
        ),
        "code_generation": ReviewRubricConfig(
            items=[
                "task_completion",
                "no_stub_code",
                "tests_pass_locally",
                "no_secret_leakage",
                "voice_friendliness",
            ]
        ),
        "skill_authoring": ReviewRubricConfig(
            items=[
                "frontmatter_valid",
                "trigger_keywords_unique",
                "instructions_actionable",
                "no_malicious_bash",
            ]
        ),
        "research": ReviewRubricConfig(
            items=[
                "task_completion",
                "factual_accuracy",
                "source_citation",
                "voice_friendliness",
            ]
        ),
    }


class ReviewConfig(BaseModel):
    """``[review]`` quality-gate config. Not self-mod-writable (plan §AD-1): sets cost/latency."""

    enabled: bool = True
    max_iterations: int = Field(default=3, ge=1, le=5)
    hard_ceiling: int = Field(default=5, ge=1, le=5)
    worker_model: str = "sonnet"
    reviewer_model: str = "opus"
    reviewer_provider: str = "claude-subscription"
    output_dir: str = "data/review/runs"
    audit_log: str = "data/review.log"
    gc_after_days: int = Field(default=30, ge=1)
    default_rubric: str = "default"
    rubrics: dict[str, ReviewRubricConfig] = Field(default_factory=_default_rubrics)


class WikiIntegrationConfig(BaseModel):
    """``[wiki_integration]``: retired wiki vault path (ADR-0044), read by legacy import only."""

    model_config = ConfigDict(extra="allow")

    vault_root: Path = Path("wiki/obsidian-vault")


class VoiceConfig(BaseModel):
    """Voice-flow knobs outside STT/TTS/Trigger. ``extra="allow"`` is mandatory (AP-16)."""

    model_config = ConfigDict(extra="allow")

    completion_detection_enabled: bool = True
    # "realtime" (full-duplex) or "pipeline" (STT->brain->TTS); read once per session. Without
    # a realtime key it falls back silently unless the mode was EXPLICITLY set in the TOML.
    mode: str = "realtime"
    # Empty = the engine's normal brain. ``codex-subscription-voice`` swaps only text generation
    # for the Codex App Server; never implied by the Realtime provider.
    profile: str = ""
    # Realtime tool exposure (ADR-0035): "hybrid" = live model calls tools itself plus
    # ``jarvis_action`` for the rest; "delegate" = only jarvis_action; "direct" = whole catalog
    # (diagnostic, ~26k tokens per response, BUG-051). Unknown values fail closed to "delegate".
    realtime_tool_mode: str = "hybrid"
    # Token bound (chars / 4) for tool declarations; overflow is dropped by priority and logged
    # (still reachable via jarvis_action). A provider capability (AP-21) may lower it. 0 = off.
    realtime_tool_declaration_budget_tokens: int = 0
    # Idle minutes before the LOCAL voice stack releases the accelerator; 0 = never
    # (``realtime.local_server.supervisor.idle_release_s``).
    local_idle_release_minutes: int = Field(default=30, ge=0, le=1440)
    # ADR-0034: a NEW turn while a jarvis_action call is unanswered answers it with "still
    # executing"; the result is spoken later. False = the transport waits.
    realtime_unblock_pending_tool_calls: bool = True
    # Per-gap budget before a stale pending fragment is discarded; each continuation resets it.
    completion_wait_ms: int = 15000
    # Grace after a COMPLETE classification before dispatch, so "Hey Jarvis, ... [pause]
    # Ich wollte wissen ..." merges into ONE turn. 0 = immediate dispatch.
    complete_grace_ms: int = 1500
    completion_max_chain: int = 3
    # Clarifying question on a trailing-off fragment or empty brain turn. OFF: it fired on
    # every empty brain turn. The AD-OE6 acks are unaffected.
    clarify_incomplete_enabled: bool = False
    # Grace after an incomplete fragment before the clarifying question fires; a
    # continuation within it cancels the question and joins the turn.
    clarify_after_ms: int = 2500
    # --- Continuation recombine ---
    # When the user keeps talking after an utterance was dispatched, abort the half-formed
    # answer and re-think the COMBINED sentence instead of dropping the earlier half.
    continuation_interrupt_enabled: bool = True
    continuation_grace_ms: int = 2500
    # Max fragments coalesced into one turn; a low cap drops the earliest context.
    continuation_max_chain: int = 8
    # Floor (s) below which the "that took too long" phrase is suppressed as a stale-state
    # guard (AP-19): no real timeout path fires faster. Clamped to <= the stall window.
    min_timeout_phrase_s: float = 30.0
    # Floor for the NO-FIRST-FRAME path (shorter TTS ceiling). None = derived; clamped to <= it.
    no_first_frame_phrase_floor_s: float | None = None


class BrowserVoiceConfig(BaseModel):
    """``[browser_voice]``: the browser microphone streams to ``/ws/audio`` on mic-less hosts."""

    model_config = ConfigDict(extra="allow")

    # Classic bridge in PIPELINE mode only (realtime always serves the socket); read at connect
    # by ``browser_voice.route.browser_voice_enabled``.
    enabled: bool = True


class CompletenessConfig(BaseModel):
    """``[speech.completeness]``: is a transcript a complete instruction?"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    signal_mode: Literal["auto", "earcon", "spoken"] = "auto"
    pending_discard_s: float = 8.0
    max_pending_fragments: int = 2
    # Gray-zone LLM escalation: reserved; an LLM on the voice critical path violates AP-9/AP-11.
    llm_escalation_enabled: bool = False

    @field_validator("pending_discard_s")
    @classmethod
    def _pending_discard_s_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(
                f"pending_discard_s must be > 0, got {v!r}. "
                "Use a positive value such as 8.0 (seconds)."
            )
        return v


class SpeechConfig(BaseModel):
    """Top-level [speech] block (stt, tts, trigger stay at the root)."""

    model_config = ConfigDict(extra="allow")

    completeness: CompletenessConfig = Field(default_factory=CompletenessConfig)

    # Silence window before an utterance is finished (Settings > Voice). 0 = AUTOMATIC: factory
    # turn detection (classic 1.5 s; realtime sends NO override, since a fixed window on top
    # made sentences wait twice). 500-5000 ms overrides both engines. Live-applied via
    # /api/settings/silence-window.
    vad_silence_ms: int = Field(default=0, ge=0, le=5000)

    @field_validator("vad_silence_ms")
    @classmethod
    def _bound_silence_window(cls, value: int) -> int:
        """0 stays 0 (automatic); positive values clamp to 500-5000 ms."""
        if value <= 0:
            return 0
        return max(500, min(5000, int(value)))


#: Every language the recogniser can transcribe: ONE source for ``[stt]``, ``[dictation]``, the
#: REST routes and the frontend pickers (AP-4). Not limited to the product locales (those are
#: what Jarvis says back).
RECOGNITION_LANGUAGES: tuple[str, ...] = (
    "af",
    "am",
    "ar",
    "as",
    "az",
    "ba",
    "be",
    "bg",
    "bn",
    "bo",
    "br",
    "bs",
    "ca",
    "cs",
    "cy",
    "da",
    "de",
    "el",
    "en",
    "es",
    "et",
    "eu",
    "fa",
    "fi",
    "fo",
    "fr",
    "gl",
    "gu",
    "ha",
    "haw",
    "he",
    "hi",
    "hr",
    "ht",
    "hu",
    "hy",
    "id",
    "is",
    "it",
    "ja",
    "jw",
    "ka",
    "kk",
    "km",
    "kn",
    "ko",
    "la",
    "lb",
    "ln",
    "lo",
    "lt",
    "lv",
    "mg",
    "mi",
    "mk",
    "ml",
    "mn",
    "mr",
    "ms",
    "mt",
    "my",
    "ne",
    "nl",
    "nn",
    "no",
    "oc",
    "pa",
    "pl",
    "ps",
    "pt",
    "ro",
    "ru",
    "sa",
    "sd",
    "si",
    "sk",
    "sl",
    "sn",
    "so",
    "sq",
    "sr",
    "su",
    "sv",
    "sw",
    "ta",
    "te",
    "tg",
    "th",
    "tk",
    "tl",
    "tr",
    "tt",
    "uk",
    "ur",
    "uz",
    "vi",
    "yi",
    "yo",
    "yue",
    "zh",
)

#: Asks for per-utterance DETECTION. Passed to the provider verbatim: an absent
#: argument inherits the configured pin.
AUTO_LANGUAGE = "auto"

RECOGNITION_LANGUAGE_CHOICES: tuple[str, ...] = (AUTO_LANGUAGE, *RECOGNITION_LANGUAGES)

#: Values ``[dictation].language`` accepts (same set as the voice recogniser).
DICTATION_LANGUAGES: tuple[str, ...] = RECOGNITION_LANGUAGE_CHOICES

#: Values ``[dictation].translate_target`` accepts: the recognition list without
#: ``auto`` (it names no output language, AP-31). One derivation (AP-4).
TRANSLATION_TARGETS: tuple[str, ...] = RECOGNITION_LANGUAGES

#: Registers the polish pass may write in. Mirrors the ``polish_style`` ``Literal``
#: below; a parity test pins the two together (AP-4).
POLISH_STYLES: tuple[str, ...] = ("neutral", "messaging", "email")


def _clamped_polish_int(value: object, *, default: int, low: int, high: int) -> int:
    """Clamp a hand-edited integer into range instead of rejecting it (AP-16).

    Non-numbers (typo, ``None``, NaN, ``inf``) fall back to the shipped default.
    """
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, number))


def _clamped_polish_float(value: object, *, default: float, low: float, high: float) -> float:
    """The float twin of :func:`_clamped_polish_int` — same AP-16 contract."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / ±inf
        return default
    return max(low, min(high, number))


class DictationConfig(BaseModel):
    """``[dictation]``: speak into the focused text field (key: ``[trigger].hotkey_dictate``)."""

    model_config = ConfigDict(extra="allow")

    #: ``hold``: record while the key is down; ``toggle``: press to start, press to stop.
    mode: Literal["hold", "toggle"] = "hold"

    #: ``auto``: front app's field, except Jarvis itself; ``insert`` always; ``chat`` never.
    target: Literal["auto", "insert", "chat"] = "auto"

    #: ``clipboard``: paste chord. ``type``: per character (~40 ms each), for no-paste controls.
    insert_method: Literal["clipboard", "type"] = "clipboard"

    #: ``auto`` = Cmd+V on macOS, else Ctrl+V; others in ``dictation.insert.PASTE_CHORDS`` or a
    #: ``+`` combination (hence ``str``; invalid -> ``auto``, AP-16). Custom reports ``paste_sent``.
    paste_chord: str = "auto"

    #: Too short and the app pastes the PREVIOUS clipboard.
    paste_delay_ms: int = Field(default=120, ge=0, le=2000)

    #: Too short and the app has not read the clipboard yet.
    paste_delay_after_ms: int = Field(default=120, ge=0, le=2000)

    restore_clipboard: bool = True

    #: Remove fillers with the deterministic rules in ``dodaios.dictation.cleanup``; no model call.
    remove_fillers: bool = True

    #: Rule-based paragraphing (``dictation.paragraphs``); under ~50 words stays one paragraph.
    auto_paragraphs: bool = True

    filler_max_removed_fraction: float = Field(default=0.25, ge=0.0, le=1.0)

    #: Ceiling on ONE dictation (s); 0 = none. Not a provider limit; costs ~1.9 MB/min of buffer.
    max_seconds: float = Field(default=1800.0, ge=0.0, le=86_400.0)

    #: Local Whisper worker; refuses calls it cannot take and the next recognizer reads.
    local_engine: bool = True

    local_model: str = "large-v3-turbo"

    local_min_free_gb: float = Field(default=1.5, ge=0.0, le=64.0)

    local_idle_minutes: float = Field(default=10.0, ge=0.0, le=1440.0)

    #: Local history (raw + cleaned); dictated text is sensitive: local-only, capped, purgeable.
    history_enabled: bool = True
    history_max_entries: int = Field(default=200, ge=0, le=5000)
    history_retention_days: int = Field(default=30, ge=0, le=3650)

    #: ``auto`` detects per utterance; pinning an untrained language makes recognition WORSE.
    #: Independent of ``[stt].language`` and ``[wake].language`` on purpose.
    language: str = "auto"

    #: Keep raw audio of a ``failed``/``cancelled``/``empty`` dictation so Restore can retry;
    #: NEVER for a success (most sensitive data). Local-only, capped, deleted with its entry.
    keep_failed_audio: bool = True
    audio_retention_days: int = Field(default=7, ge=0, le=365)
    #: Keep at most this many audio files; 0 disables the count cap (not "delete all").
    audio_max_files: int = Field(default=20, ge=0, le=1000)

    # --- Polish pass: a small text model reads the FINISHED transcript once. On timeout,
    # error, missing key or failed drift guard the raw transcript is delivered.

    #: Master switch, ON. Safe without credentials: the key-aware ``auto`` chain is empty,
    #: so the pass reports ``unavailable`` and delivers raw text (AP-23).
    polish: bool = True

    #: ``auto``: the user's own keys, best latency first, crossing families when one fails
    #: (AP-22); a concrete id pins it. Transport follows wire format (AP-21).
    polish_provider: str = "auto"

    polish_model: str = ""

    #: Hard ceiling (ms); felt as delay, since it runs AFTER transcription. On expiry: raw text.
    polish_timeout_ms: int = Field(default=1200, ge=200, le=5000)

    #: Cap (ms) of a per-word ramp beyond ~25 words (a fixed ceiling starved long dictations).
    polish_timeout_max_ms: int = Field(default=2000, ge=200, le=20_000)

    #: Skip above this many characters; 0 = no cap (a cap silently skipped long dictations).
    polish_max_input_chars: int = Field(default=0, ge=0, le=1_000_000)

    polish_min_words: int = Field(default=4, ge=0, le=100)

    #: Output ceiling; a truncated answer fails the drift guards and the raw text is delivered.
    polish_max_output_tokens: int = Field(default=1200, ge=64, le=8192)

    polish_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    #: Word-count band vs the raw text; outside it the raw text wins. Asymmetric: growth looks
    #: like an answer or translation.
    polish_drift_max_shrink: float = Field(default=0.55, ge=0.0, le=1.0)
    polish_drift_max_growth: float = Field(default=1.20, ge=1.0, le=3.0)

    polish_style: Literal["neutral", "messaging", "email"] = "neutral"

    #: Sharpen WORD CHOICE. OFF: it drops the rare-token drift check (``precision_drift_reason``).
    polish_precision: bool = False

    #: Also polish VOICE TURN transcripts (same pass, AP-4). Never delays a turn
    #: (``TranscriptPolished`` arrives later); OFF for cost; requires ``polish``; never translates.
    polish_conversation: bool = False

    # --- Translate pass: in the SAME model call as polish, fail-open (delivered as spoken).

    #: OFF: unlike polish it changes which words come out, so it must be deliberate.
    translate: bool = False

    #: Delivery language. Read from THIS BLOCK only (``resolve_translate_target``), never the
    #: recognizer's unreliable tag; pinning ``language`` to it means no translation.
    translate_target: str = "en"

    translate_drift_max_shrink: float = Field(default=0.40, ge=0.0, le=1.0)
    translate_drift_max_growth: float = Field(default=2.50, ge=1.0, le=10.0)

    # --- Prompt Mode: a dictation comes out as the prompt for a coding agent.

    #: Turn a dictation into a finished prompt on the polish chain (``dictation/prompt_mode.py``).
    #: Outranks polish and translate (falls through on timeout). OFF: it changes WHAT is said.
    prompt_mode: bool = False

    #: Ceiling for one call (typical answer 2-6 s); a truncated prompt is rejected. Clamped (AP-16).
    prompt_mode_timeout_ms: int = Field(default=12_000, ge=4_000, le=20_000)

    @field_validator("paste_chord", mode="before")
    @classmethod
    def _coerce_paste_chord(cls, value: object) -> str:
        """Normalize only; unusable -> ``auto`` (AP-16). REST uses ``normalize_paste_chord``."""
        from dodaios.dictation.insert import normalize_paste_chord

        return normalize_paste_chord(str(value or ""))[0]

    @field_validator("language", mode="before")
    @classmethod
    def _coerce_dictation_language(cls, value: object) -> str:
        """Normalize only; an unknown value falls back to ``auto`` (AP-16)."""
        text = str(value or "").strip().lower()
        return text if text in DICTATION_LANGUAGES else "auto"

    @field_validator("translate_target", mode="before")
    @classmethod
    def _coerce_translate_target(cls, value: object) -> str:
        """Normalize only; unusable -> ``en`` (``auto`` names no output language)."""
        text = str(value or "").strip().lower()
        return text if text in TRANSLATION_TARGETS else "en"

    @field_validator("polish_provider", mode="before")
    @classmethod
    def _coerce_polish_provider(cls, value: object) -> str:
        """Normalize only; empty -> ``auto``. Not checked against the family list (AP-26, AP-4)."""
        text = str(value or "").strip().lower()
        return text or "auto"

    @field_validator("polish_model", mode="before")
    @classmethod
    def _coerce_polish_model(cls, value: object) -> str:
        """Normalize only; case is preserved (model ids are case-sensitive), whitespace stripped."""
        return str(value or "").strip()

    @field_validator("polish_style", mode="before")
    @classmethod
    def _coerce_polish_style(cls, value: object) -> str:
        """Normalize only; an unknown style falls back to ``neutral`` (AP-16)."""
        text = str(value or "").strip().lower()
        return text if text in POLISH_STYLES else "neutral"

    # The numeric knobs below are CLAMPED, not rejected (AP-16).

    @field_validator("polish_timeout_ms", mode="before")
    @classmethod
    def _clamp_polish_timeout_ms(cls, value: object) -> int:
        return _clamped_polish_int(value, default=1200, low=200, high=5000)

    @field_validator("polish_timeout_max_ms", mode="before")
    @classmethod
    def _clamp_polish_timeout_max_ms(cls, value: object) -> int:
        return _clamped_polish_int(value, default=2000, low=200, high=20_000)

    @field_validator("polish_max_input_chars", mode="before")
    @classmethod
    def _clamp_polish_max_input_chars(cls, value: object) -> int:
        return _clamped_polish_int(value, default=0, low=0, high=1_000_000)

    @field_validator("polish_min_words", mode="before")
    @classmethod
    def _clamp_polish_min_words(cls, value: object) -> int:
        return _clamped_polish_int(value, default=4, low=0, high=100)

    @field_validator("polish_max_output_tokens", mode="before")
    @classmethod
    def _clamp_polish_max_output_tokens(cls, value: object) -> int:
        return _clamped_polish_int(value, default=1200, low=64, high=8192)

    @field_validator("polish_temperature", mode="before")
    @classmethod
    def _clamp_polish_temperature(cls, value: object) -> float:
        return _clamped_polish_float(value, default=0.0, low=0.0, high=2.0)

    @field_validator("polish_drift_max_shrink", mode="before")
    @classmethod
    def _clamp_polish_drift_max_shrink(cls, value: object) -> float:
        return _clamped_polish_float(value, default=0.55, low=0.0, high=1.0)

    @field_validator("polish_drift_max_growth", mode="before")
    @classmethod
    def _clamp_polish_drift_max_growth(cls, value: object) -> float:
        return _clamped_polish_float(value, default=1.20, low=1.0, high=3.0)

    @field_validator("translate_drift_max_shrink", mode="before")
    @classmethod
    def _clamp_translate_drift_max_shrink(cls, value: object) -> float:
        return _clamped_polish_float(value, default=0.40, low=0.0, high=1.0)

    @field_validator("translate_drift_max_growth", mode="before")
    @classmethod
    def _clamp_translate_drift_max_growth(cls, value: object) -> float:
        return _clamped_polish_float(value, default=2.50, low=1.0, high=10.0)

    @field_validator("prompt_mode_timeout_ms", mode="before")
    @classmethod
    def _clamp_prompt_mode_timeout_ms(cls, value: object) -> int:
        return _clamped_polish_int(value, default=12_000, low=4_000, high=20_000)


class MarketplaceConfig(BaseModel):
    """Marketplace OAuth: a hosted callback base (headless VPS); empty = loopback."""

    public_callback_base_url: str = ""
    # Community index (public registry by default); empty disables the community section.
    community_index_url: str = "https://dodaios.github.io/marketplace/index.json"
    # Publish endpoint; empty hides Publish (the hosted endpoint was retired).
    publish_endpoint: str = ""
    # Registry repo for Publish without an endpoint: an issue opened as the signed-in user
    # (docs/marketplace/agent-templates.md).
    publish_registry_repo: str = "Dodaios/marketplace"
    publish_github_client_id: str = "Iv23li1YcX62KJO67whO"
    model_config = ConfigDict(extra="allow")


class PointerConfig(BaseModel):
    """[pointer]: resolves the element under the cursor when the utterance points at it."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    # Budget for the off-hot-path resolution (AP-9); on timeout the turn has no pointer context.
    timeout_s: float = 0.12
    crop_radius: int = 110


class CodexConfig(BaseModel):
    """``[codex]``: ``binary_path`` overrides the PATH lookup (``codex_auth.CodexAuthService``)."""

    binary_path: str = ""


class TeamProxyConfig(BaseModel):
    """Team proxy mode: providers not in ``local_providers`` go via ``{url}/p/{provider_id}``
    with the per-user token (``team_proxy_token``) instead of a vendor key.
    """

    enabled: bool = False
    url: str | None = None
    local_providers: list[str] = Field(default_factory=list)
    model_config = {"extra": "allow"}


class Phase6SafetyConfig(BaseModel):
    """``[phase6.safety]``: mission-worker safety knobs (ADR-0031). ``extra="allow"`` (AP-16)."""

    model_config = ConfigDict(extra="allow")

    injection_scanner_enabled: bool = True
    destructive_confirm_enabled: bool = True
    extra_blocked_globs: list[str] = Field(default_factory=list)
    # ADR-0031: tools in the mission's broker grant AND listed below are auto-approved for THAT
    # mission only (answered on the bus, never bypassed). False = every ask-tier call waits.
    worker_tool_auto_approve: bool = True
    # Exact names or ``server/`` families; prefer EXACT (a prefix authorizes future destructive
    # tools). Messaging/mail/social-send stay OUT by default.
    auto_approve_tool_families: list[str] = Field(
        default_factory=lambda: [
            "search_web",
            "session-latest-turn",
        ]
    )


class Phase6Config(BaseModel):
    """``[phase6]`` root; only ``safety`` is typed, other tables stay raw TOML."""

    model_config = ConfigDict(extra="allow")

    safety: Phase6SafetyConfig = Field(default_factory=Phase6SafetyConfig)


class MissionsConfig(BaseModel):
    """``[missions]``: ``paid_api_fallback`` (OFF) lets a mission use the user's API key within the
    ``missions/capacity.py`` caps. Settings-only, never an agent (``self_mod/forbidden.py``).
    """

    model_config = ConfigDict(extra="allow")

    paid_api_fallback: bool = False


class GlmCodingPlanConfig(BaseModel):
    """GLM pane endpoint: the ordinary Claude Code binary pointed elsewhere.

    ``base_url`` differs for mainland-China accounts; empty model ids send no override.
    The API key is NOT here: credential store ``zai_api_key`` (AP-12).
    """

    model_config = ConfigDict(extra="allow")

    base_url: str = Field(
        default="https://api.z.ai/api/anthropic",
        description=(
            "Anthropic-compatible endpoint a GLM pane talks to. Use "
            "https://open.bigmodel.cn/api/anthropic for a mainland-China account."
        ),
    )
    opus_model: str = Field(
        default="",
        description="Model id for the CLI's 'opus' tier. Empty = let the endpoint decide.",
    )
    sonnet_model: str = Field(
        default="",
        description="Model id for the CLI's 'sonnet' tier. Empty = let the endpoint decide.",
    )
    haiku_model: str = Field(
        default="",
        description="Model id for the CLI's 'haiku' tier. Empty = let the endpoint decide.",
    )
    request_timeout_ms: int = Field(
        default=3_000_000,
        ge=60_000,
        description=(
            "Per-request timeout handed to the CLI. The stock value is far too "
            "short for this backend's long agentic runs and expires mid-answer."
        ),
    )


class AgenticIdeConfig(BaseModel):
    """Agentic IDE behaviour that is not per-workspace state."""

    # AP-16: a key written by a NEWER install must not fail this one's boot.
    model_config = ConfigDict(extra="allow")

    glm: GlmCodingPlanConfig = Field(default_factory=GlmCodingPlanConfig)

    prompt_writer: str = Field(
        default="auto",
        description=(
            "Who writes Agentic IDE task briefs: 'auto' (the writer that answers "
            "soonest — your Tool Model if one is pinned, else the API-billed "
            "quality tier, else a connected coding subscription), 'tool_model', "
            "'subscription', 'api', or a specific brain provider id."
        ),
    )

    smart_recaps: bool = Field(
        default=False,
        description=(
            "Let a model write and refresh a pane's header recap when its coding "
            "CLI has not named the session itself. Off (the default) uses the "
            "CLI's own title (Claude Code, Codex); a session the CLI left unnamed "
            "gets one title from its opening request, written by a connected "
            "subscription, and otherwise shows the pane's first or last prompt. "
            "On spends background model requests."
        ),
    )

    follow_main: bool = Field(
        default=False,
        description=(
            "Keep a desktop app that runs from a git checkout on the newest main: "
            "fetch origin every minute, fast-forward, rebuild the frontend and restart "
            "for new Python code once nothing would be lost (no mission, no live call). "
            "Never merges, rebases, resets or stashes; local edits that would be "
            "overwritten stop the update and are reported."
        ),
    )

    pane_notifications: bool = Field(
        default=True,
        description=(
            "Collect a notification whenever a terminal stops working, asks a "
            "question, or its agent exits — the bell in the Agentic IDE header. "
            "Off stops the background sweep entirely; the bell then only shows "
            "what was already collected."
        ),
    )

    model_fallback: bool = Field(
        default=True,
        description=(
            "When a coding thread's model hits its usage or rate limit, switch that "
            "same thread to the next model of its CLI's fallback chain and continue "
            "the conversation (a notice in the thread says so). Off leaves the thread "
            "stopped with the limit error, as before."
        ),
    )

    model_fallback_chains: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Per-CLI fallback chains, most preferred model first, keyed by runner "
            "('claude-cli', 'codex-cli', ...). A CLI not listed uses the built-in "
            "chain (Claude Code: Fable 5.2, Opus 5.5, Sonnet 5.5); an empty list "
            "switches fallback off for that CLI."
        ),
    )

    @field_validator("model_fallback_chains", mode="before")
    @classmethod
    def _usable_chains(cls, value: object) -> dict[str, list[str]]:
        """Anything that is not a table of model lists becomes "no override"."""
        if not isinstance(value, dict):
            return {}
        out: dict[str, list[str]] = {}
        for runner, models in value.items():
            if isinstance(models, str):
                models = models.split(",")
            if isinstance(models, list | tuple):
                out[str(runner)] = [str(m).strip() for m in models if str(m).strip()]
        return out

    @field_validator("prompt_writer", mode="before")
    @classmethod
    def _usable_writer(cls, value: object) -> str:
        """Anything unusable becomes 'auto'; existence is decided at resolve time."""
        text = str(value or "").strip()
        # A provider id starts with a letter; a bare number is a mis-typed value.
        if not text or not text[0].isalpha():
            return "auto"
        return text if text.replace("-", "").replace("_", "").isalnum() else "auto"


class GoogleAuthConfig(BaseModel):
    """Google credential routing: AI Studio vs Vertex express mode (``core.google_genai``).

    Newer AI Studio keys also start with ``AQ.``, so ``auto`` probes an ambiguous key once per
    process; ``always``/``never`` force the route. The ``vertex_*`` fields are the FULL Vertex
    path (a Cloud project, ADC); it excludes express mode (``genai.Client`` refuses ``api_key``
    with ``project``), so a ``vertex_project`` selects it and empty keeps the express key.
    """

    model_config = ConfigDict(extra="allow")

    vertex_mode: Literal["auto", "always", "never"] = "auto"
    vertex_project: str | None = None
    vertex_location: str = "global"
    #: Region for the Live socket (``global`` opens none). Empty = ``vertex_location`` if a region.
    vertex_realtime_location: str | None = None
    #: Service-account JSON (exported as ``GOOGLE_APPLICATION_CREDENTIALS``); None = ambient ADC.
    service_account_path: str | None = None


#: Voices the local voice engine can load today (ADR-0037). Pocket TTS is the
#: natural default; Piper is the floor every machine can run. Qwen3-TTS stays
#: out of the switchable set until its premium phase (plan section 6, P4).
VOICE_ENGINE_VOICES: tuple[str, ...] = ("pocket", "piper")


class VoiceEngineConfig(BaseModel):
    """``[voice_engine]``: the local voice engine (``config_writer.set_voice_engine_settings``)."""

    model_config = ConfigDict(extra="allow")

    #: Voice backend: ``pocket`` (natural, CPU) or ``piper`` (floor). An
    #: unknown value falls back to ``pocket`` instead of failing the config.
    tts: str = "pocket"
    #: Ollama tag the engine answers with. Empty = automatic: the model setup
    #: picked (installed models first), else the machine-class default.
    llm_model: str = ""
    #: Languages the engine loads a voice for; the first is the fallback voice.
    languages: list[str] = Field(default_factory=lambda: ["de", "en"])

    @field_validator("tts", mode="before")
    @classmethod
    def _known_voice(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in VOICE_ENGINE_VOICES else "pocket"

    @field_validator("llm_model", mode="before")
    @classmethod
    def _strip_model(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("languages", mode="before")
    @classmethod
    def _clean_languages(cls, value: object) -> list[str]:
        items = value if isinstance(value, list | tuple) else []
        cleaned = [str(x).strip().lower() for x in items if str(x).strip()]
        return cleaned or ["de", "en"]


class SelfBuildConfig(BaseModel):
    """``[self_build]`` — the self-building loop's limits (docs/self-build.md).

<<<<<<< HEAD
    Per need kind: ``off``, ``suggest``, ``trial`` (live with undo) or ``full``.
||||||| 030bbb15a5
    Dodaios notices what the person keeps doing and builds what would take it
    off them: a memory, a skill, a routine, an agent or a code change. Each
    kind has its own autonomy level: ``off``, ``suggest`` (a card, nothing is
    built before the person accepts), ``trial`` (built, checked and live with
    one-click undo) or ``full`` (as trial, and the trial ends by measure).
    Every key is read by ``dodaios.self_build.policy`` (AP-31).
=======
    Dodaios notices what the person keeps doing and builds what would take it
    off them: a memory, a skill, a routine, an agent or a code change. It never
    asks for approval: a build goes live on trial when it can be undone, and a
    finished trial is kept or archived from the person's own use. How far each
    kind goes is fixed in ``dodaios.self_build.policy.autonomy``, not set here;
    the person's controls are the pause switch and undo on "Built for you".
    The keys below are the hard caps and trial lengths the policy reads.

    ``enabled`` and the per-kind stages (``memory``, ``skill``, ``routine``,
    ``agent``, ``code``) are no longer read. They stay so that a config file
    that sets them still loads; their values are ignored.
>>>>>>> origin/main
    """

    model_config = {"extra": "allow"}

    #: Ignored. The loop always runs; the pause switch stops it (kept so old
    #: config files load).
    enabled: bool = True
    #: The first days after the loop first ran only record build cases.
    silent_days: int = Field(default=7, ge=0, le=90)
    #: Ignored, like the four stages below: autonomy per kind is fixed in
    #: ``policy.autonomy`` (kept so old config files load).
    memory: Literal["off", "suggest", "trial", "full"] = "trial"
    skill: Literal["off", "suggest", "trial", "full"] = "suggest"
    routine: Literal["off", "suggest", "trial", "full"] = "suggest"
    agent: Literal["off", "suggest", "trial", "full"] = "suggest"
    code: Literal["off", "suggest", "trial", "full"] = "suggest"
    #: A trial ends after this many days or this many uses, whichever is first.
    trial_days: int = Field(default=14, ge=1, le=90)
    trial_uses: int = Field(default=10, ge=1, le=1_000)
    max_builds_per_day: int = Field(default=3, ge=0, le=50)
    max_agents_per_week: int = Field(default=1, ge=0, le=10)
    max_open_trials: int = Field(default=5, ge=0, le=50)
    max_code_runs_per_day: int = Field(default=1, ge=0, le=20)
    #: A need whose builds the person undid this often is not built again.
    max_rejections: int = Field(default=2, ge=1, le=20)
    #: Repositories (``owner/name``) whose loop pull requests are merged once CI is
    #: green ("land it"). Empty: every loop pull request is a draft the person merges.
    code_land_repos: list[str] = Field(default_factory=list)


class RsiConfig(BaseModel):
    """``[rsi]`` — recording and judging orders given to coding threads.

    Runs on every install (``dodaios.orchestrator.verification``); it holds a run
    only if the coding policy says so. ``enabled`` and ``verify`` are ignored.
    """

    model_config = {"extra": "allow"}

    #: Ignored. Recording and judging always run (kept so old config files load).
    enabled: bool = False
    #: Ignored. Every run is judged; holding is the run's policy's question.
    verify: Literal["off", "observe", "enforce"] = "off"
    #: For a held run, ``triggered`` has one model review an output when a fixed
    #: trigger asks (``dodaios.orchestrator.verification.review``).
    review: Literal["off", "triggered"] = "off"
    #: A review may use an API key (and so cost money); otherwise only a
    #: subscription that is signed in.
    review_paid: bool = False
    #: Give every coding thread its own git worktree and branch. Off by default:
    #: the worktree starts from the remote default branch, so unpushed work and
    #: dependencies are absent. Shared-checkout runs use start/end snapshots.
    worktree_per_run: bool = False
    #: Repositories whose threads keep running in the project folder, by the
    #: id the run report shows (``github.com/owner/name``).
    shared_checkout_repos: list[str] = Field(default_factory=list)
    #: Hand the lead a compact index of the repositories in play with its
    #: messages (``dodaios.rsi.repo_index``). Independent of ``enabled``.
    repo_index: bool = False


class BriefsConfig(BaseModel):
    """``[briefs]`` — the pipeline every coding-agent brief passes (``docs/agent-briefs.md``)."""

    model_config = {"extra": "allow"}

    #: ``revise``: a faulty brief goes back to its writer once. ``note``: checked
    #: and recorded, never sent back. ``off``: briefs go out as written.
    check: Literal["revise", "note", "off"] = "revise"
    #: Pick the effort from the size of the job when none was named.
    auto_effort: bool = True
    #: A thread an agent opened gets the standing rules for work orders once.
    standing_rules: bool = True
    #: The lead may answer a coding thread's question from the person's own words.
    lead_answers_questions: bool = True
    #: Hold a finished order's done-when points against what the run left behind.
    acceptance: bool = True
    #: Keep every order and its outcome in ``briefs.db``.
    record: bool = True


class JarvisConfig(BaseModel):
    """Root config model."""

    # populate_by_name: Python field names work alongside the sub_agents alias.
    model_config = ConfigDict(populate_by_name=True)

    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)
    # [voice_engine] — the Jarvis-owned local voice engine (ADR-0037).
    voice_engine: VoiceEngineConfig = Field(default_factory=VoiceEngineConfig)
    # Google key routing (AI Studio vs Vertex express) — see GoogleAuthConfig.
    google: GoogleAuthConfig = Field(default_factory=GoogleAuthConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    self_build: SelfBuildConfig = Field(default_factory=SelfBuildConfig)
    rsi: RsiConfig = Field(default_factory=RsiConfig)
    briefs: BriefsConfig = Field(default_factory=BriefsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    agentic_ide: AgenticIdeConfig = Field(default_factory=AgenticIdeConfig)
    mcp_server: MCPServerConfig = Field(default_factory=MCPServerConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    # Audio ducking — "Mute music while dictating" (Taskbar section).
    ducking: DuckingConfig = Field(default_factory=DuckingConfig)
    # Music connectors: preferred service + where YouTube Music plays.
    music: MusicConfig = Field(default_factory=MusicConfig)
    # Login autostart (Windows .lnk / macOS LaunchAgent / Linux .desktop); default on.
    autostart: AutostartConfig = Field(default_factory=AutostartConfig)
    # Background agent service after the window closes (routines, channels).
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    # Old installs use [sub_agents], new ones [jarvis_agents]; both fill this field.
    jarvis_agents: JarvisAgentsOutputConfig = Field(
        default_factory=JarvisAgentsOutputConfig,
        validation_alias=AliasChoices("jarvis_agents", "sub_agents"),
    )
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    # Plugin-marketplace OAuth connect (hosted vs loopback callback).
    marketplace: MarketplaceConfig = Field(default_factory=MarketplaceConfig)
    board: BoardConfig = Field(default_factory=BoardConfig)
    # Persona mandate, Phase 5: top-level ``[vision]`` section.
    vision: VisionContextConfig = Field(default_factory=VisionContextConfig)
    # One-shot screen look (dodaios/screen_context/); ``[vision]`` is the always-on path.
    screen_context: ScreenContextConfig = Field(default_factory=ScreenContextConfig)
    # Appshots: the front window as context (dodaios/appshot/), via Screen Context.
    appshot: AppshotConfig = Field(default_factory=AppshotConfig)
    # Jarvis X: built-in screenshot / screen-recording tool (dodaios/dodaiosx/).
    jarvisx: JarvisXConfig = Field(default_factory=JarvisXConfig)
    # Phase 5/6 — Computer-Use-POAV-Harness (ADR-0008).
    computer_use: ComputerUseConfig = Field(default_factory=ComputerUseConfig)
    # Low-latency local-action gate. Hidden tools only; never exposed in the
    # router LLM schema.
    local_action: LocalActionConfig = Field(default_factory=LocalActionConfig)
    # Phase 8.4 — review pipeline configuration.
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    # Phase 6 — mission subsystem ([phase6.safety] typed; rest raw, AP-16).
    phase6: Phase6Config = Field(default_factory=Phase6Config)
    # [missions] — paid API fallback switch for missions (capacity policy).
    missions: MissionsConfig = Field(default_factory=MissionsConfig)
    # Latency sprint 1 (2026-04-30) — master switches for performance levers.
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    # Wave 0 (omni-latency) — hot-path latency span instrumentation toggle.
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    # The retired wiki vault's location, read once by the legacy import (ADR-0044).
    wiki_integration: WikiIntegrationConfig = Field(default_factory=WikiIntegrationConfig)
    # Flash-Brain acknowledgment LLM, opt-in via [ack_brain].enabled; late import at
    # the bottom of this module avoids the brain<->core.config cycle.
    ack_brain: AckBrainConfig = Field(
        default_factory=lambda: AckBrainConfig()
    )
    # Speech pipeline sub-configs: [speech] / [speech.completeness].
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    # Dictation mode (hold to speak, transcript lands in the focused field).
    dictation: DictationConfig = Field(default_factory=DictationConfig)
    # Voice-flow knobs (incomplete-prompt completion buffer).
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    # [browser_voice] — browser-microphone bridge for hosts without a microphone.
    browser_voice: BrowserVoiceConfig = Field(default_factory=BrowserVoiceConfig)
    # AI Pointer — "what is under the mouse cursor" context (docs/plans/ai-pointer/DESIGN.md).
    pointer: PointerConfig = Field(default_factory=PointerConfig)
    # [codex] — OpenAI Codex CLI integration (binary path override).
    codex: CodexConfig = Field(default_factory=CodexConfig)
    # [team_proxy] — route providers through a shared key proxy via a per-user token.
    team_proxy: TeamProxyConfig = Field(default_factory=TeamProxyConfig)


# Loading logic

#: Parsed ``jarvis.toml`` payloads, keyed by path -> (identity, data).
#: ``load_config`` runs from many sites, some on the event loop; re-parsing a
#: large TOML there can stall the loop for seconds when GC pressure is high.
_TOML_CACHE: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
_TOML_CACHE_LOCK = threading.Lock()


def _copy_toml_data(value: Any) -> Any:
    """Structural copy of a parsed TOML payload; callers mutate it, so the cache cannot share it."""
    if type(value) is dict:
        return {key: _copy_toml_data(item) for key, item in value.items()}
    if type(value) is list:
        return [_copy_toml_data(item) for item in value]
    return value


def clear_config_cache() -> None:
    """Forget everything derived from the config file, including the route cache."""
    with _TOML_CACHE_LOCK:
        _TOML_CACHE.clear()
        _ENDPOINT_ROUTE_CACHE.clear()


def _load_toml(path: Path) -> dict[str, Any]:
    # mtime AND size: either alone misses some edits. An unstat-able file is
    # not cached; the read below reports the real error.
    identity: tuple[int, int] | None = None
    try:
        info = path.stat()
        identity = (info.st_mtime_ns, info.st_size)
    except OSError:
        identity = None

    if identity is not None:
        with _TOML_CACHE_LOCK:
            cached = _TOML_CACHE.get(path)
        if cached is not None and cached[0] == identity:
            return _copy_toml_data(cached[1])

    # tomllib rejects a UTF-8 BOM, which Windows editors write on Save-As.
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    data = tomllib.loads(raw.decode("utf-8"))

    if identity is not None:
        with _TOML_CACHE_LOCK:
            _TOML_CACHE[path] = (identity, data)
        # The cache keeps the pristine parse; the caller gets a copy.
        return _copy_toml_data(data)
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge: overlay overrides base, lists are replaced."""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# Selections the config-drift-guard syncs across jarvis.toml, config-soll.json and
# the User registry; healed at boot because stale inherited env beats the toml.
_PERSISTED_PROVIDER_ENV_KEYS: tuple[str, ...] = (
    "JARVIS__BRAIN__PRIMARY",
    "JARVIS__BRAIN__TOOL_MODEL__PROVIDER",
    # Canonical key; config_writer writes here.
    "JARVIS__BRAIN__WORKER__PROVIDER",
    # Legacy key still present in pre-rename registries.
    "JARVIS__BRAIN__SUB_JARVIS__PROVIDER",
    "JARVIS__TTS__PROVIDER",
    "JARVIS__STT__PROVIDER",
    # ack_brain master + provider selection.
    "JARVIS__ACK_BRAIN__ENABLED",
    "JARVIS__ACK_BRAIN__PROVIDER",
    "JARVIS__ACK_BRAIN__FALLBACK_PROVIDER",
    # TTS engine selection beyond the provider tier.
    "JARVIS__TTS__MODEL",
    "JARVIS__TTS__USE_VERTEX",
    "JARVIS__TTS__VOICE_DE",
    "JARVIS__TTS__VOICE_EN",
    # Google endpoint routing: decides which account every tier bills.
    "JARVIS__GOOGLE__VERTEX_MODE",
    "JARVIS__GOOGLE__VERTEX_PROJECT",
    "JARVIS__GOOGLE__VERTEX_LOCATION",
    "JARVIS__GOOGLE__SERVICE_ACCOUNT_PATH",
    # GPT-Live profile.
    "JARVIS__LIVE__MODEL",
    "JARVIS__LIVE__VOICE",
    "JARVIS__LIVE__BACKEND_MODEL",
    "JARVIS__LIVE__REASONING_EFFORT",
    "JARVIS__LIVE__WEB_SEARCH",
    "JARVIS__LIVE__CONFIGURED",
)


def _read_user_env_var(name: str) -> str | None:
    """Read a User-scope env var from ``HKCU\\Environment`` (``None`` off Windows or absent)."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value)
    except (FileNotFoundError, OSError):
        return None


def refresh_persisted_env_from_user_registry(
    keys: tuple[str, ...] = _PERSISTED_PROVIDER_ENV_KEYS,
    *,
    read: Any = None,
) -> dict[str, str]:
    """Overwrite ``os.environ`` for the persistent provider keys from the User registry.

    Call once at boot before :func:`load_config`. ``read`` is a test seam. Returns the keys changed.
    """
    reader = read if read is not None else _read_user_env_var
    changed: dict[str, str] = {}
    for name in keys:
        value = reader(name)
        if value is not None and os.environ.get(name) != value:
            os.environ[name] = value
            changed[name] = value
    return changed


def _base_model_type(annotation: Any) -> type[BaseModel] | None:
    """Return the BaseModel carried by an annotation, including unions."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for candidate in get_args(annotation):
        model_type = _base_model_type(candidate)
        if model_type is not None:
            return model_type
    return None


def _container_type(annotation: Any) -> type[dict] | type[list] | None:
    """Return the mapping/list shape carried by a field annotation."""
    origin = get_origin(annotation)
    candidate = origin or annotation
    if isinstance(candidate, type) and issubclass(candidate, Mapping):
        return dict
    if candidate is list:
        return list
    for nested in get_args(annotation):
        container_type = _container_type(nested)
        if container_type is not None:
            return container_type
    return None


@lru_cache(maxsize=256)
def _expected_env_container(path: tuple[str, ...]) -> type[dict] | type[list] | None:
    """Resolve a structured ENV target from the Pydantic config schema."""
    model_type: type[BaseModel] = JarvisConfig
    for index, segment in enumerate(path):
        field = model_type.model_fields.get(segment)
        if field is None:
            return None
        if index == len(path) - 1:
            return _container_type(field.annotation)
        nested_model = _base_model_type(field.annotation)
        if nested_model is None:
            return None
        model_type = nested_model
    return None


def _apply_env_overrides(data: dict[str, Any], prefix: str = "JARVIS__") -> dict[str, Any]:
    """Override config with env variables JARVIS__SECTION__KEY=value."""
    stt_section = data.get("stt")
    stt_provider_user_selected = bool(
        isinstance(stt_section, dict) and stt_section.get("provider_user_selected") is True
    )
    for env_key, env_val in tuple(os.environ.items()):
        if not env_key.startswith(prefix):
            continue
        path = env_key[len(prefix) :].lower().split("__")
        if path == ["stt", "provider"] and stt_provider_user_selected:
            logging.getLogger(__name__).debug(
                "Ignoring %s because the persisted STT provider was user-selected",
                env_key,
            )
            continue
        cursor = data
        blocked = False
        for segment in path[:-1]:
            existing_segment = cursor.get(segment)
            if existing_segment is None:
                existing_segment = {}
                cursor[segment] = existing_segment
            if not isinstance(existing_segment, dict):
                blocked = True
                break
            cursor = existing_segment
        if blocked:
            os.environ.pop(env_key, None)
            logging.getLogger(__name__).warning(
                "Ignoring config override %s because its path crosses a scalar",
                env_key,
            )
            continue
        value = _coerce_env_value(env_val)
        existing_value = cursor.get(path[-1])
        expected_container = _expected_env_container(tuple(path))
        mapping_conflict = (
            expected_container is dict or isinstance(existing_value, dict)
        ) and not isinstance(value, dict)
        list_conflict = (
            expected_container is list or isinstance(existing_value, list)
        ) and not isinstance(value, list)
        if mapping_conflict or list_conflict:
            # An old drift-guard wrote structured JSON as a PowerShell string;
            # replacing a table with it would break validation at startup.
            os.environ.pop(env_key, None)
            logging.getLogger(__name__).warning(
                "Ignoring scalar config override %s for a structured value",
                env_key,
            )
            continue
        cursor[path[-1]] = value
    return data


def _coerce_env_value(v: str) -> Any:
    """Coerce an environment string to JSON containers or a scalar."""
    lv = v.strip().lower()
    if lv.startswith(("{", "[")):
        try:
            parsed = json.loads(v)
        except (TypeError, ValueError):
            # Invalid JSON-shaped input intentionally falls through to scalar coercion.
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return parsed
    if lv in ("true", "yes", "1"):
        return True
    if lv in ("false", "no", "0"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _dedupe_worker_tier_tables(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve the [brain.worker] vs legacy [brain.sub_jarvis] conflict.

    The canonical table wins, the legacy one is dropped with one warning. A
    legacy-only file is untouched; the on-disk heal is ``config_writer``'s.
    """
    brain = data.get("brain")
    if not isinstance(brain, dict):
        return data
    worker = brain.get("worker")
    legacy = brain.get("sub_jarvis")
    if isinstance(worker, dict) and isinstance(legacy, dict):
        logging.getLogger(__name__).warning(
            "config: both [brain.worker] (provider=%r) and legacy "
            "[brain.sub_jarvis] (provider=%r) are present — [brain.worker] "
            "wins; the legacy table is ignored and will be merged away at "
            "the next boot heal.",
            worker.get("provider"),
            legacy.get("provider"),
        )
        brain.pop("sub_jarvis", None)
    return data


def _migrate_worker_env_vars() -> None:
    """Copy old ``JARVIS__BRAIN__SUB_JARVIS__*`` env vars to ``WORKER`` names if only set."""
    for old_name, new_name in (
        ("JARVIS__BRAIN__SUB_JARVIS__PROVIDER", "JARVIS__BRAIN__WORKER__PROVIDER"),
        ("JARVIS__BRAIN__SUB_JARVIS__MODEL", "JARVIS__BRAIN__WORKER__MODEL"),
    ):
        old_val = os.environ.get(old_name)
        if old_val and not os.environ.get(new_name):
            os.environ[new_name] = old_val  # process-local only, no setx


#: Paths whose dictation-shortcut backfill has already been attempted in THIS
#: process. The on-disk marker is the durable guard; this only keeps a hot
#: ``load_config`` loop from re-reading the file for a migration that is done.
_DICTATION_HOTKEY_HEALED: set[Path] = set()
_LEGACY_CODEX_REALTIME_HEALED: set[Path] = set()


def _heal_legacy_codex_realtime_once(path: Path) -> None:
    """Route a removed Codex Realtime selection onto the stable composition."""
    if path in _LEGACY_CODEX_REALTIME_HEALED:
        return
    _LEGACY_CODEX_REALTIME_HEALED.add(path)
    try:
        from dodaios.core.config_writer import migrate_removed_codex_realtime_provider

        migrated = migrate_removed_codex_realtime_provider(path=path)
    except Exception:  # noqa: BLE001 - a boot migration must not block startup
        logging.getLogger(__name__).warning(
            "Could not migrate the removed Codex Realtime voice selection.",
            exc_info=True,
        )
        return
    if migrated:
        logging.getLogger(__name__).warning(
            "Migrated the removed codex-subscription-realtime selection to "
            "the stable ChatGPT subscription voice profile (Pipeline mode)."
        )


_LIVE_VOICE_PROFILE_HEALED: set[Path] = set()


def _heal_live_voice_profile_once(path: Path) -> None:
    """Free a saved GPT-Live setup from a leftover classic voice profile."""
    if path in _LIVE_VOICE_PROFILE_HEALED:
        return
    _LIVE_VOICE_PROFILE_HEALED.add(path)
    try:
        from dodaios.core.config_writer import retire_voice_profile_under_live

        healed = retire_voice_profile_under_live(path=path)
    except Exception:  # noqa: BLE001 - a boot repair must not block startup
        logging.getLogger(__name__).warning(
            "Could not repair the voice profile of the saved GPT-Live setup.",
            exc_info=True,
        )
        return
    if healed:
        logging.getLogger(__name__).warning(
            "Retired a classic voice profile that blocked the saved GPT-Live setup."
        )


def _heal_dictation_hotkeys_once(path: Path) -> None:
    """Run the one-time dictation-shortcut backfill. Never raises, never blocks."""
    if path in _DICTATION_HOTKEY_HEALED:
        return
    _DICTATION_HOTKEY_HEALED.add(path)
    try:
        from dodaios.core.config_writer import migrate_dictation_hotkey_defaults

        migrate_dictation_hotkey_defaults(path=path)
    except Exception:  # noqa: BLE001, S110 — a boot heal must never block a load
        pass


def load_config(
    config_file: Path | None = None,
    profile: str | None = None,
) -> JarvisConfig:
    """Load config from TOML + optional YAML profile + env overrides.

    Precedence, lowest to highest: jarvis.toml, profiles/<active>.yaml, ``JARVIS__*``
    env. ``config_file=None`` uses :func:`resolve_config_path`; an explicit path wins.
    """
    if config_file is None:
        config_file = resolve_config_path()
        # The codex-subscription-realtime adapter was removed 2026-08-10. A
        # config still pinning it is routed onto the stable subscription
        # profile before the first parse so the UI and runtime see one state.
        _heal_legacy_codex_realtime_once(config_file)
        # A GPT-Live setup saved over a classic voice profile could not start
        # a call (issue #828). Repair that pairing before the first parse.
        _heal_live_voice_profile_once(config_file)
        # One-time dictation-shortcut backfill before the file is read; only for
        # the resolved path (an explicit file is read, never rewritten).
        _heal_dictation_hotkeys_once(config_file)
    if not config_file.exists():
        # No config file → pure defaults (useful for tests)
        data: dict[str, Any] = {}
    else:
        data = _load_toml(config_file)

    if profile is None:
        profile = os.environ.get("JARVIS_PROFILE") or data.get("profile", {}).get("name")

    if profile and profile != "default":
        profile_file = PROFILES_DIR / f"{profile}.yaml"
        if profile_file.exists():
            data = _deep_merge(data, _load_yaml(profile_file))

    # Worker-tier conflict is resolved before env overrides land.
    data = _dedupe_worker_tier_tables(data)
    # Back-compat: copy old JARVIS__BRAIN__SUB_JARVIS__* env names to WORKER.
    _migrate_worker_env_vars()
    data = _apply_env_overrides(data)
    data = _apply_instance_overrides(data)
    return JarvisConfig(**data)


# (section, field, default) ports the dev instance shifts by
# ``InstanceIdentity.port_offset``; the admin port is also the fast-boot bind.
_INSTANCE_PORT_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("ui", "admin_api_port", 47821),
    ("mcp_server", "http_port", 47822),
    ("telemetry", "metrics_port", 9090),
)


def _apply_instance_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Pin a non-default instance's ports and data directory after every user layer."""
    identity = current_instance()
    if identity.is_default:
        return data
    for section, field, default in _INSTANCE_PORT_FIELDS:
        table = data.get(section)
        if not isinstance(table, dict):
            table = {}
            data[section] = table
        base = table.get(field, default)
        if not isinstance(base, int) or isinstance(base, bool):
            base = default
        table[field] = identity.port(base)
    memory = data.get("memory")
    if not isinstance(memory, dict):
        memory = {}
        data["memory"] = memory
    memory["data_dir"] = str(DATA_DIR)
    return data


# Secrets: OS keyring, with a headless fallback.
# Without a Secret Service the keyring is ``fail.Keyring``, so a local 0600 JSON
# file stands in; the OS keyring stays the secure path when it works.
_KEYRING_BACKEND_READY: bool = False
_FILE_BACKEND_ACTIVE: bool = False
# Platform backend active before a runtime failure forced the file backend;
# kept so credentials still readable from the OS store stay visible and
# recovery probes do not mistake the file backend for a recovered one.
_PLATFORM_KEYRING_BACKEND: Any | None = None
# Slot whose OS-keyring read failed last (e.g. a denied macOS Keychain prompt);
# the credential_store permission request replays it on a user-initiated retry,
# since a probe on a brand-new item would succeed without re-prompting.
_LAST_KEYRING_FAILED_SLOT: str | None = None
_SECRET_REVISION_LOCK = threading.Lock()
_SECRET_REVISIONS: dict[str, int] = {}
# Bumped by every in-process credential write or delete, whatever the slot, so
# caches keyed on "which keys exist" need no per-path invalidation.
_SECRET_GENERATION: int = 0
# Called with the slot name after every successful write or delete; all save
# paths go through ``set_secret`` / ``delete_secret``.
_SECRET_CHANGE_LISTENERS: list[Any] = []


def secret_revision(key: str) -> int:
    """In-process revision of one credential slot (bumped by in-app writes only)."""
    with _SECRET_REVISION_LOCK:
        return _SECRET_REVISIONS.get(key, 0)


def secret_generation() -> int:
    """How many credential writes/deletes this process has seen (any slot)."""
    with _SECRET_REVISION_LOCK:
        return _SECRET_GENERATION


def add_secret_change_listener(listener: Any) -> None:
    """Call ``listener(slot)`` after every secret write or delete; it must be cheap, not raise."""
    with _SECRET_REVISION_LOCK:
        if listener not in _SECRET_CHANGE_LISTENERS:
            _SECRET_CHANGE_LISTENERS.append(listener)


def _mark_secret_changed(key: str) -> None:
    global _SECRET_GENERATION
    with _SECRET_REVISION_LOCK:
        _SECRET_REVISIONS[key] = _SECRET_REVISIONS.get(key, 0) + 1
        _SECRET_GENERATION += 1
        listeners = list(_SECRET_CHANGE_LISTENERS)
    for listener in listeners:
        try:
            listener(key)
        except Exception:  # noqa: BLE001 — the credential IS saved; a follower failing must not undo that
            logging.getLogger(__name__).warning(
                "secret-change listener %r failed for slot %s",
                getattr(listener, "__qualname__", listener),
                key,
                exc_info=True,
            )


# Serializes _FileCredStore load-mutate-save across in-process writers; there
# is no cross-process lock.
_FILE_CRED_STORE_LOCK = threading.Lock()


class _FileCredStore:
    """Minimal 0600 JSON credential store keyed by ``(service, username)``."""

    def __init__(self, path: Path | None = None) -> None:
        self._explicit = path

    def _file(self) -> Path:
        p = (
            self._explicit
            if self._explicit is not None
            else (_resolve_writable_data_dir() / "credentials.json")
        )
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load(self) -> dict[str, str]:
        try:
            f = self._file()
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except Exception:  # noqa: BLE001 — a corrupt store must never crash a read
            return {}

    def _save(self, data: dict[str, str]) -> None:
        f = self._file()
        # Per-process temp name so racing processes do not clobber each other.
        tmp = f.with_name(f"{f.name}.tmp.{os.getpid()}")
        try:
            # Born 0600 (write_text + chmod would expose the key briefly on a
            # multi-user machine). A stale same-pid tmp is removed so O_EXCL works.
            tmp.unlink(missing_ok=True)
            descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(json.dumps(data))
            os.replace(tmp, f)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"failed to write credential store {f}: {exc}") from exc

    @staticmethod
    def _k(service: str, username: str) -> str:
        return f"{service}\x00{username}"

    def get(self, service: str, username: str) -> str | None:
        return self._load().get(self._k(service, username))

    def set(self, service: str, username: str, password: str) -> None:
        with _FILE_CRED_STORE_LOCK:
            data = self._load()
            data[self._k(service, username)] = password
            self._save(data)

    def delete(self, service: str, username: str) -> None:
        with _FILE_CRED_STORE_LOCK:
            data = self._load()
            data.pop(self._k(service, username), None)
            self._save(data)

    def usernames(self, service: str) -> tuple[str, ...]:
        """Every entry name stored under ``service`` (this store, unlike an OS one, can list)."""
        prefix = self._k(service, "")
        return tuple(name[len(prefix) :] for name in self._load() if name.startswith(prefix))


def _is_platform_keyring_backend(backend: Any) -> bool:
    """Return whether *backend* is a real platform credential-store candidate."""
    if backend is None or getattr(backend, "_jarvis_file_backend", False):
        return False
    if getattr(backend, "_jarvis_platform_wrapper", False):
        # DarwinBundleKeyringBackend wraps the real backend; check the wrapped
        # instance instead of class/module names (AP-28).
        return _is_platform_keyring_backend(getattr(backend, "_inner", None))
    try:
        # ``fail.Keyring`` advertises zero priority; rely on that, not isinstance.
        priority = getattr(backend, "priority", None)
        return priority is None or priority > 0
    except Exception:  # noqa: BLE001
        return False


def _install_file_cred_backend(reason: str, *, retain_platform_backend: bool = True) -> bool:
    """Force the 0600 file store as the keyring backend. Idempotent; True iff it is now active."""
    global _FILE_BACKEND_ACTIVE, _PLATFORM_KEYRING_BACKEND
    try:
        import keyring
        import keyring.backend

        current_backend = keyring.get_keyring()
        if not retain_platform_backend:
            _PLATFORM_KEYRING_BACKEND = None
        elif _is_platform_keyring_backend(current_backend):
            _PLATFORM_KEYRING_BACKEND = current_backend

        _store = _FileCredStore()

        class _FileKeyringBackend(keyring.backend.KeyringBackend):
            priority = 0.1  # type: ignore[assignment]  # below any real OS backend
            _jarvis_file_backend = True

            def get_password(self, service: str, username: str) -> str | None:
                return _store.get(service, username)

            def set_password(self, service: str, username: str, password: str) -> None:
                _store.set(service, username, password)

            def delete_password(self, service: str, username: str) -> None:
                _store.delete(service, username)

        keyring.set_keyring(_FileKeyringBackend())
        if not _FILE_BACKEND_ACTIVE:
            # No platform vault is expected on a headless host; only warn when a
            # previously usable one failed.
            logging.getLogger(__name__).log(
                logging.WARNING if retain_platform_backend else logging.INFO,
                "OS credential store unusable (%s) — API keys are stored in a local "
                "0600 file under %s. Configure a Secret Service / Keychain for "
                "OS-encrypted storage.",
                reason,
                DATA_DIR / "credentials.json",
            )
        _FILE_BACKEND_ACTIVE = True
        return True
    except Exception:  # noqa: BLE001
        return False


def _ensure_keyring_backend() -> None:
    """Install the file credential store if the OS keyring is non-functional (runs once)."""
    global _KEYRING_BACKEND_READY
    if _KEYRING_BACKEND_READY:
        return
    _KEYRING_BACKEND_READY = True
    try:
        import keyring

        current_backend = keyring.get_keyring()
        if not _is_platform_keyring_backend(current_backend):
            _install_file_cred_backend(
                "no OS credential store available (headless host)",
                retain_platform_backend=False,
            )
        elif sys.platform == "darwin" and not getattr(
            current_backend, "_jarvis_platform_wrapper", False
        ):
            from .keychain_bundle import (
                DarwinBundleKeyringBackend,
                darwin_security_cli_vault,
            )

            keyring.set_keyring(
                DarwinBundleKeyringBackend(current_backend, cli=darwin_security_cli_vault())
            )
    except Exception:  # noqa: BLE001, S110 -- a missing keyring must never break boot
        pass


def _try_restore_platform_keyring_backend() -> bool:
    """Restore a recovered OS keyring before an explicit credential save.

    Probes with a disposable slot; never runs on boot or a read. True when platform is active.
    """
    global _FILE_BACKEND_ACTIVE, _PLATFORM_KEYRING_BACKEND
    if not _FILE_BACKEND_ACTIVE:
        return True

    keyring_mod = None
    previous_backend = None
    candidate = None
    try:
        import keyring as keyring_mod
        from keyring.core import init_backend

        previous_backend = keyring_mod.get_keyring()
        init_backend()
        candidate = keyring_mod.get_keyring()
        if not _is_platform_keyring_backend(candidate):
            raise RuntimeError("platform backend discovery found no usable backend")

        # ``init_backend()`` installs the raw backend; re-wrap on macOS so the
        # probe exercises the bundle lifecycle.
        if sys.platform == "darwin" and not getattr(candidate, "_jarvis_platform_wrapper", False):
            from .keychain_bundle import (
                DarwinBundleKeyringBackend,
                darwin_security_cli_vault,
            )

            candidate = DarwinBundleKeyringBackend(candidate, cli=darwin_security_cli_vault())
            keyring_mod.set_keyring(candidate)

        # Probe the full write/read/delete lifecycle on a disposable entry: on
        # Windows a read-only probe passed while every write failed (error 1312).
        probe_key = f"__jarvis_backend_probe__{secrets.token_hex(8)}"
        probe_value = secrets.token_urlsafe(24)
        try:
            candidate.set_password(KEYRING_SERVICE, probe_key, probe_value)
            if candidate.get_password(KEYRING_SERVICE, probe_key) != probe_value:
                raise RuntimeError("platform credential-store probe read mismatch")
            candidate.delete_password(KEYRING_SERVICE, probe_key)
            if candidate.get_password(KEYRING_SERVICE, probe_key) is not None:
                raise RuntimeError("platform credential-store probe delete failed")
        except Exception:
            # A backend may write and then raise, so cleanup is unconditional.
            try:
                candidate.delete_password(KEYRING_SERVICE, probe_key)
            except Exception:  # noqa: BLE001, S110 -- best-effort probe cleanup
                pass
            _PLATFORM_KEYRING_BACKEND = candidate
            raise
    except Exception:  # noqa: BLE001 -- unavailable OS keyring is expected headlessly
        if keyring_mod is not None and previous_backend is not None:
            try:
                keyring_mod.set_keyring(previous_backend)
            except Exception:  # noqa: BLE001, S110 -- keep best-effort fallback active
                pass
        return False

    _PLATFORM_KEYRING_BACKEND = candidate
    _FILE_BACKEND_ACTIVE = False
    logging.getLogger(__name__).info(
        "OS credential store recovered; future credential saves use the platform keyring."
    )
    return True


def credential_store_backend() -> str:
    """Report which credential store is live: ``platform`` | ``file`` | ``unavailable``."""
    _ensure_keyring_backend()
    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001 -- no keyring module on this install
        return "unavailable"
    if _is_platform_keyring_backend(backend):
        return "platform"
    if getattr(backend, "_jarvis_file_backend", False):
        return "file"
    return "unavailable"


def try_recover_platform_credential_store() -> bool:
    """User-initiated retry of the OS credential store: restore, then replay the failed read."""
    global _LAST_KEYRING_FAILED_SLOT
    if not _try_restore_platform_keyring_backend():
        return False
    slot = _LAST_KEYRING_FAILED_SLOT
    if slot is None:
        return True
    try:
        import keyring

        keyring.get_password(KEYRING_SERVICE, slot)
    except Exception:  # noqa: BLE001 -- the user declined the prompt again
        _install_file_cred_backend("credential-store access declined again")
        return False
    _LAST_KEYRING_FAILED_SLOT = None
    return True


def _peek_password(backend: Any, service: str, key: str) -> str | None:
    """Read one entry without letting the backend write (``peek_password`` where offered)."""
    peek = getattr(backend, "peek_password", None)
    if callable(peek):
        return peek(service, key)
    return backend.get_password(service, key)


def _read_legacy_secret(key: str) -> tuple[str | None, str | None]:
    """``(platform value, file value)`` of ``key`` under the first legacy service holding it."""
    for service in LEGACY_KEYRING_SERVICES:
        file_val: str | None = None
        try:
            file_val = _FileCredStore().get(service, key)
        except Exception:  # noqa: BLE001, S110 — unreadable fallback is absent
            pass
        platform_val: str | None = None
        try:
            import keyring

            active_backend = keyring.get_keyring()
            if getattr(active_backend, "_jarvis_file_backend", False):
                # The active backend IS the file store read above; the platform
                # copy, if any, lives in the retained backend.
                platform_backend = _PLATFORM_KEYRING_BACKEND
                if platform_backend is not None and _is_platform_keyring_backend(
                    platform_backend
                ):
                    platform_val = _peek_password(platform_backend, service, key)
            elif _is_platform_keyring_backend(active_backend):
                # Through the module, like the current-service read above, so
                # whatever the process routes ``keyring`` to is what answers.
                peek = getattr(active_backend, "peek_password", None)
                platform_val = (
                    peek(service, key) if callable(peek) else keyring.get_password(service, key)
                )
        except Exception as exc:  # noqa: BLE001 — a legacy entry that cannot be read is absent
            logging.getLogger(__name__).debug(
                "legacy credential read for %s under %s failed (%s)",
                key,
                service,
                type(exc).__name__,
            )
        if platform_val or file_val:
            return platform_val, file_val
    return None, None


def _refresh_legacy_copies(key: str, value: str) -> None:
    """Rewrite ``key`` under a legacy service where an entry exists; never raises."""
    log = logging.getLogger(__name__)
    for service in LEGACY_KEYRING_SERVICES:
        try:
            import keyring

            backend = keyring.get_keyring()
            if getattr(backend, "_jarvis_file_backend", False):
                pass  # the file store is refreshed below
            else:
                peek = getattr(backend, "peek_password", None)
                existing = (
                    peek(service, key) if callable(peek) else keyring.get_password(service, key)
                )
                if existing is not None:
                    keyring.set_password(service, key, value)
        except Exception as exc:  # noqa: BLE001 — best effort, see the docstring
            log.warning(
                "legacy credential copy of %s under %s not refreshed (%s)",
                key,
                service,
                type(exc).__name__,
            )
        try:
            store = _FileCredStore()
            if store.get(service, key) is not None:
                store.set(service, key, value)
        except Exception as exc:  # noqa: BLE001 — best effort, see the docstring
            log.warning(
                "legacy file credential copy of %s under %s not refreshed (%s)",
                key,
                service,
                type(exc).__name__,
            )


def get_secret(key: str, env_fallback: str | None = None) -> str | None:
    """Retrieve a secret from every portable credential source.

    Priority: OS keyring, ENV, ``.env``, file fallback; a fallback copy beats
    only a stale OS copy. Legacy services (``LEGACY_KEYRING_SERVICES``) are tried
    when the current one is empty.

    Args:
        key: Secret name in the Credential Manager (e.g. "anthropic_api_key").
        env_fallback: ENV variable checked when keyring is empty (e.g. "ANTHROPIC_API_KEY").
    """
    _ensure_keyring_backend()
    # Derive the ENV name from the slot (``groq_api_key`` -> ``GROQ_API_KEY``) so
    # the keyring -> ENV -> .env order holds for every slot (headless hosts).
    if env_fallback is None:
        env_fallback = key.upper()

    # A file value marks a later save whose platform write failed; read it first
    # so an older OS value cannot shadow it after a restart.
    file_val: str | None = None
    try:
        file_val = _FileCredStore().get(KEYRING_SERVICE, key)
    except Exception:  # noqa: BLE001, S110 — unreadable fallback is absent
        pass

    platform_val: str | None = None
    # Lazy import — keyring requires pywin32 on Windows
    try:
        import keyring

        active_val = keyring.get_password(KEYRING_SERVICE, key)
        active_backend = keyring.get_keyring()
        if _FILE_BACKEND_ACTIVE and getattr(active_backend, "_jarvis_file_backend", False):
            # The global keyring is the file backend; keep reading the retained
            # platform backend for slots that never needed a fallback.
            file_val = active_val or file_val
            platform_backend = _PLATFORM_KEYRING_BACKEND
            if platform_backend is not None and _is_platform_keyring_backend(platform_backend):
                try:
                    platform_val = platform_backend.get_password(KEYRING_SERVICE, key)
                except Exception:  # noqa: BLE001 — locked platform stays fallback-only
                    platform_val = None
        else:
            platform_val = active_val
    except Exception:  # noqa: BLE001
        # A reachable-but-locked OS keyring raises here even though
        # _ensure_keyring_backend saw a viable backend. Degrade to the 0600 file
        # store and retry once, so a key saved to the file fallback in a prior run
        # is still visible instead of dead-ending on the locked keyring.
        global _LAST_KEYRING_FAILED_SLOT
        _LAST_KEYRING_FAILED_SLOT = key
        if _install_file_cred_backend("keyring read failed"):
            try:
                import keyring

                file_val = keyring.get_password(KEYRING_SERVICE, key) or file_val
            except Exception:  # noqa: BLE001, S110
                pass

    # Nothing under the current service: try the legacy service names (read-only)
    # so a legacy OS-keyring value still beats ENV.
    if not platform_val and not file_val:
        platform_val, file_val = _read_legacy_secret(key)

    # OS keyring beats ENV unless a newer fallback copy exists; the fallback then
    # beats only the stale OS copy.
    if platform_val and not file_val:
        return platform_val

    if env_fallback and (val := os.environ.get(env_fallback)):
        return val

    # Development fallback: .env file; the DODAIOS_ spelling wins over JARVIS_.
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists() and env_fallback:
        names = accepted_names(env_fallback)
        found: dict[str, str] = {}
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in names:
                found.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        for name in names:
            if name in found:
                return found[name]

    if file_val:
        return file_val

    return None


def get_secret_any(candidates: tuple[tuple[str, str | None], ...]) -> str | None:
    """Return the first configured secret from ``(keyring_key, env_var)`` pairs."""
    for key, env_fallback in candidates:
        val = get_secret(key, env_fallback=env_fallback)
        if val:
            return val
    return None


def get_provider_secret(provider: str) -> str | None:
    """Return the API key for a Brain provider, including accepted aliases."""
    overrides = _PROVIDER_SECRET_OVERRIDES.get()
    if overrides is not None and provider in overrides:
        return overrides[provider]
    return get_secret_any(PROVIDER_SECRET_CANDIDATES.get(provider, ()))


def vertex_credential_configured(config: JarvisConfig | None = None) -> bool:
    """Whether Vertex AI can authenticate on this host (it may use ADC instead of a key).

    A set ``[google].vertex_project`` is the signal. ``config`` is a test seam.
    """
    if get_provider_secret("vertex"):
        return True
    try:
        cfg = config if config is not None else load_config()
        return bool(str(getattr(cfg.google, "vertex_project", "") or "").strip())
    except Exception as exc:  # noqa: BLE001 — an unreadable config is an unset one
        logging.getLogger(__name__).debug(
            "Vertex project lookup failed (%s: %s) — treating Vertex as unconfigured.",
            type(exc).__name__,
            exc,
        )
        return False


def get_jarvis_agent_secret(provider: str) -> str | None:
    """Effective API key for one Jarvis-Agent provider: dedicated slot, then the provider chain."""
    candidates = JARVIS_AGENT_SECRET_CANDIDATES.get(provider, ())
    if not candidates:
        return None
    dedicated = get_secret_any((candidates[0],))
    if dedicated:
        return dedicated
    return get_provider_secret(provider)


def jarvis_agent_secret_slot(provider: str) -> tuple[str, str] | None:
    """Return the dedicated ``(keyring slot, ENV name)`` for an Agent family."""
    candidates = JARVIS_AGENT_SECRET_CANDIDATES.get(provider, ())
    return candidates[0] if candidates else None


# One key per provider family.
# Surfaces read the family's primary slot; scoped slots (``realtime_*``,
# ``jarvis_agent_*``, ``codex_*``) exist for a second key. The first key saved
# becomes the family key; a different second key asks "here, or everywhere?".

# Families that own a primary slot; Realtime/Agent/Codex are scoped views.
_SECRET_BASE_FAMILIES: tuple[str, ...] = (
    "claude-api",
    "openai",
    "openrouter",
    "deepseek",
    "litellm",
    "groq",
    "nvidia",
    "gemini",
    "vertex",
    "grok",
)


@dataclass(frozen=True, slots=True)
class SecretSlotScope:
    """Where one keyring slot sits inside its provider family."""

    family: str
    primary_slot: str
    # True for a surface-scoped slot (realtime / agent / codex).
    dedicated: bool


def secret_family_primary_slot(family: str) -> str | None:
    """The slot every surface of ``family`` reads first (``gemini_api_key``…)."""
    if family not in _SECRET_BASE_FAMILIES:
        return None
    candidates = PROVIDER_SECRET_CANDIDATES.get(family, ())
    return candidates[0][0] if candidates else None


def secret_slot_scope(slot: str) -> SecretSlotScope | None:
    """Classify ``slot`` as a family primary, a scoped slot (chain ends in one), or neither."""
    for family in _SECRET_BASE_FAMILIES:
        primary = secret_family_primary_slot(family)
        if primary == slot:
            return SecretSlotScope(family=family, primary_slot=primary, dedicated=False)
    for chains in (PROVIDER_SECRET_CANDIDATES, JARVIS_AGENT_SECRET_CANDIDATES):
        for candidates in chains.values():
            if not candidates or candidates[0][0] != slot:
                continue
            # A chain reaching a primary from a different first slot is a scoped
            # view, including the Agent chains.
            tail = {candidate_slot for candidate_slot, _env in candidates[1:]}
            for family in _SECRET_BASE_FAMILIES:
                primary = secret_family_primary_slot(family)
                if primary in tail:
                    return SecretSlotScope(family=family, primary_slot=primary, dedicated=True)
    return None


def secret_family_scoped_slots(family: str) -> tuple[str, ...]:
    """Every surface-scoped slot that falls back to ``family``'s primary slot."""
    found: dict[str, None] = {}
    for chains in (PROVIDER_SECRET_CANDIDATES, JARVIS_AGENT_SECRET_CANDIDATES):
        for candidates in chains.values():
            if not candidates:
                continue
            scope = secret_slot_scope(candidates[0][0])
            if scope is not None and scope.dedicated and scope.family == family:
                found.setdefault(candidates[0][0])
    return tuple(found)


@dataclass(frozen=True, slots=True)
class SecretSavePlan:
    """What a save of one slot should write, or the question to ask (``choice_required``)."""

    writes: tuple[str, ...]
    deletes: tuple[str, ...] = ()
    choice_required: bool = False
    family: str | None = None
    primary_slot: str | None = None
    # "dedicated_vs_family": scoped save, family has a different key.
    # "family_vs_dedicated": family key replaced while surfaces hold their own.
    choice_kind: str | None = None
    # The scoped slots holding a different key from the one being saved.
    conflicting_slots: tuple[str, ...] = ()


def plan_secret_save(slot: str, value: str, scope: str | None = None) -> SecretSavePlan:
    """Decide where a key entered on one surface should be stored.

    * A slot outside any family is written as-is.
    * A scoped save with no family key (or the same key) writes the FAMILY key.
    * A different key on a scoped surface asks; ``"here"`` writes the scoped
      slot, ``"everywhere"`` the family slot and drops scoped copies of the old key.
    * Replacing the family key while surfaces hold a different key asks whether
      they keep it (``"here"``) or follow (``"everywhere"``). Copies equal to the
      old family key always follow.

    Pure planning. ``scope`` is ``None`` (ask if needed), ``"here"`` or ``"everywhere"``.
    """
    if scope not in (None, "here", "everywhere"):
        raise ValueError(f"unknown secret save scope: {scope!r}")
    info = secret_slot_scope(slot)
    if info is None:
        return SecretSavePlan(writes=(slot,))
    family, primary = info.family, info.primary_slot

    if info.dedicated:
        family_value = get_secret(primary)
        own_value = get_secret(slot)
        drop_own = (slot,) if own_value else ()
        if not family_value or family_value == value:
            return SecretSavePlan(
                writes=(primary,), deletes=drop_own, family=family, primary_slot=primary
            )
        if scope is None:
            return SecretSavePlan(
                writes=(),
                choice_required=True,
                family=family,
                primary_slot=primary,
                choice_kind="dedicated_vs_family",
                conflicting_slots=(primary,),
            )
        if scope == "here":
            return SecretSavePlan(writes=(slot,), family=family, primary_slot=primary)
        # everywhere: scoped mirrors of the old key follow; a third key is deliberate.
        mirrors = tuple(
            s for s in secret_family_scoped_slots(family) if get_secret(s) == family_value
        )
        deletes = tuple(dict.fromkeys((*drop_own, *mirrors)))
        return SecretSavePlan(
            writes=(primary,), deletes=deletes, family=family, primary_slot=primary
        )

    # The family primary itself.
    old_value = get_secret(primary)
    mirrors: list[str] = []
    distinct: list[str] = []
    for scoped in secret_family_scoped_slots(family):
        held = get_secret(scoped)
        if not held or held == value:
            if held:
                mirrors.append(scoped)
            continue
        if old_value and held == old_value:
            mirrors.append(scoped)
        else:
            distinct.append(scoped)
    if distinct and scope is None:
        return SecretSavePlan(
            writes=(),
            choice_required=True,
            family=family,
            primary_slot=primary,
            choice_kind="family_vs_dedicated",
            conflicting_slots=tuple(distinct),
        )
    deletes = tuple(mirrors) if scope != "everywhere" else tuple((*mirrors, *distinct))
    return SecretSavePlan(writes=(primary,), deletes=deletes, family=family, primary_slot=primary)


@contextmanager
def override_provider_secrets(
    overrides: Mapping[str, str | None],
) -> Iterator[None]:
    """Task-local provider credentials for an Agent or critic call (ContextVar, no env writes)."""
    token = _PROVIDER_SECRET_OVERRIDES.set(dict(overrides))
    try:
        yield
    finally:
        _PROVIDER_SECRET_OVERRIDES.reset(token)


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    """Effective endpoint + credential for a provider; ``base_url=None`` means the SDK default."""

    base_url: str | None
    credential: str | None
    via_proxy: bool


@dataclass(frozen=True)
class _EndpointRoute:
    """Where a provider's traffic goes — the part decided purely by config."""

    base_url: str | None
    via_proxy: bool


#: Config-derived routing per (config identity, provider, vendor default).
#: Rebuilding ``JarvisConfig`` per client build stalled the event loop, and the
#: model is mutated by many sites, so only this small decision is cached.
_ENDPOINT_ROUTE_CACHE: dict[tuple[tuple[int, int] | None, str, str | None], _EndpointRoute] = {}


def _endpoint_route(
    cfg_obj: JarvisConfig,
    provider_id: str,
    vendor_default_base_url: str | None,
) -> _EndpointRoute:
    """Pure routing decision for one provider — no secrets, no I/O."""
    team = cfg_obj.team_proxy
    if team.enabled and team.url and provider_id not in team.local_providers:
        return _EndpointRoute(base_url=f"{team.url.rstrip('/')}/p/{provider_id}", via_proxy=True)
    prov = cfg_obj.brain.providers.get(provider_id)
    override = prov.base_url if prov is not None and prov.base_url else None
    return _EndpointRoute(base_url=override or vendor_default_base_url, via_proxy=False)


def _endpoint_route_from_mapping(
    data: dict[str, Any],
    provider_id: str,
    vendor_default_base_url: str | None,
) -> _EndpointRoute:
    """Same decision as ``_endpoint_route``, from the TOML mapping, without ``JarvisConfig``."""
    team = data.get("team_proxy")
    team_map = team if isinstance(team, dict) else {}
    url = team_map.get("url")
    local = team_map.get("local_providers") or ()
    if team_map.get("enabled") and url and provider_id not in local:
        return _EndpointRoute(base_url=f"{str(url).rstrip('/')}/p/{provider_id}", via_proxy=True)
    brain = data.get("brain")
    providers = brain.get("providers") if isinstance(brain, dict) else None
    prov = providers.get(provider_id) if isinstance(providers, dict) else None
    override = prov.get("base_url") if isinstance(prov, dict) else None
    return _EndpointRoute(
        base_url=override or vendor_default_base_url, via_proxy=False
    )


def _cached_endpoint_route(
    provider_id: str,
    vendor_default_base_url: str | None,
) -> _EndpointRoute:
    """The routing decision, keyed on the config file identity (``clear_config_cache`` drops it)."""
    identity: tuple[int, int] | None = None
    path = resolve_config_path()
    try:
        info = path.stat()
        identity = (info.st_mtime_ns, info.st_size)
    except OSError:
        identity = None

    key = (identity, provider_id, vendor_default_base_url)
    if identity is not None:
        cached = _ENDPOINT_ROUTE_CACHE.get(key)
        if cached is not None:
            return cached

    if path.exists():
        data = _apply_env_overrides(_load_toml(path))
    else:
        data = _apply_env_overrides({})
    route = _endpoint_route_from_mapping(data, provider_id, vendor_default_base_url)
    if identity is not None:
        _ENDPOINT_ROUTE_CACHE[key] = route
    return route


def ollama_hf_enabled(config: JarvisConfig | None = None) -> bool:
    """Whether Hugging Face GGUF browsing is on for the Ollama card (the one reader, AP-31)."""
    conf = config or load_config()
    provider = conf.brain.providers.get("ollama")
    return bool(provider is not None and provider.hf_enabled)


def ollama_autostart(config: JarvisConfig | None = None) -> bool:
    """Whether the local server starts with the app (the one reader, AP-31); default on."""
    conf = config or load_config()
    provider = conf.brain.providers.get("ollama")
    return True if provider is None else bool(provider.autostart)


def resolve_provider_endpoint(
    provider_id: str,
    *,
    vendor_default_base_url: str | None = None,
    config: JarvisConfig | None = None,
) -> ResolvedEndpoint:
    """Resolve the effective endpoint + credential for a provider.

    A ``base_url`` override wins over the vendor default; team mode routes via
    ``{url}/p/{provider_id}`` with the team token.
    """
    if config is not None:
        route = _endpoint_route(config, provider_id, vendor_default_base_url)
    else:
        route = _cached_endpoint_route(provider_id, vendor_default_base_url)

    # The credential is not cached: it can be replaced or repaired while the app
    # runs, and a cached one would keep a provider dead after a key fix.
    if route.via_proxy:
        token = get_secret("team_proxy_token", "TEAM_PROXY_TOKEN")
        return ResolvedEndpoint(base_url=route.base_url, credential=token, via_proxy=True)
    credential = get_provider_secret(provider_id)
    return ResolvedEndpoint(base_url=route.base_url, credential=credential, via_proxy=False)


def set_secret(key: str, value: str) -> bool:
    """Store a secret in the OS keyring (or the headless 0600 file fallback). True on success."""
    _ensure_keyring_backend()
    # Re-detect the OS backend on an explicit save after a fallback swap, so a
    # stale platform entry cannot shadow the new value after restart.
    if _FILE_BACKEND_ACTIVE:
        _try_restore_platform_keyring_backend()
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, key, value)
        # A successful OS-keyring write supersedes a stale file fallback (unless
        # the file IS the active backend).
        if not _FILE_BACKEND_ACTIVE:
            store = _FileCredStore()
            try:
                fallback_exists = store.get(KEYRING_SERVICE, key) is not None
            except Exception:  # noqa: BLE001 -- incomplete save must be reported
                return False
            if fallback_exists:
                cleanup_succeeded = False
                try:
                    store.delete(KEYRING_SERVICE, key)
                    cleanup_succeeded = store.get(KEYRING_SERVICE, key) is None
                except Exception:  # noqa: BLE001 -- synchronize below
                    cleanup_succeeded = False
                if not cleanup_succeeded:
                    # A stale fallback outranks the platform copy in get_secret; make
                    # both agree before reporting success.
                    try:
                        store.set(KEYRING_SERVICE, key, value)
                        if store.get(KEYRING_SERVICE, key) != value:
                            return False
                    except Exception:  # noqa: BLE001
                        return False
        _refresh_legacy_copies(key, value)
        _mark_secret_changed(key)
        return True
    except Exception as exc:  # noqa: BLE001
        # A reachable-but-unusable OS keyring (e.g. a locked Linux Secret Service)
        # raises even though _ensure_keyring_backend saw a viable backend. Degrade
        # to the 0600 file store and retry once, so in-app key save never 500s and
        # the credential actually persists (recoverable in-app, AGENTS.md).
        if _install_file_cred_backend(f"keyring write failed: {exc!r}"):
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, key, value)
                _refresh_legacy_copies(key, value)
                _mark_secret_changed(key)
                return True
            except Exception:  # noqa: BLE001
                return False
        return False


def _delete_secret_in(service: str, key: str) -> tuple[bool, bool]:
    """Delete ``key`` under one service: ``(nothing is left there, a store confirmed it)``."""
    # The retained platform store is a second live copy after a fallback swap;
    # keep the newer file copy if its deletion cannot be confirmed.
    retained_backend = _PLATFORM_KEYRING_BACKEND
    if _FILE_BACKEND_ACTIVE and _is_platform_keyring_backend(retained_backend):
        try:
            from keyring.errors import PasswordDeleteError

            try:
                retained_backend.delete_password(service, key)
            except PasswordDeleteError:
                pass
            if retained_backend.get_password(service, key) is not None:
                return False, False
        except Exception:  # noqa: BLE001
            return False, False

    keyring_ok = False
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(service, key)
        except PasswordDeleteError:
            # Every backend we rely on raises this specifically when the
            # entry is already absent (e.g. the Windows Credential Manager
            # backend; the file-fallback backend's delete is idempotent and
            # never raises at all) — "nothing to delete" is itself a success.
            pass
        # Some backends report success without deleting; read back to confirm.
        keyring_ok = keyring.get_password(service, key) is None
    except Exception:  # noqa: BLE001
        # A genuine backend failure (locked Secret Service, transport
        # error, ...). Deliberately do not retry via
        # _install_file_cred_backend here: swapping the process-global
        # keyring backend just because one delete failed would silently
        # degrade every other credential read/write in this process while
        # the real OS-keyring entry survives untouched.
        keyring_ok = False

    if not keyring_ok and not _FILE_BACKEND_ACTIVE:
        # The fallback is authoritative when both copies exist; keep it until the
        # platform deletion is confirmed, or the stale credential resurfaces.
        return False, False

    file_ok = False
    try:
        store = _FileCredStore()
        if store.get(service, key) is not None:
            store.delete(service, key)
        file_ok = store.get(service, key) is None
    except Exception:  # noqa: BLE001, S110
        pass
    return keyring_ok and file_ok, keyring_ok or file_ok


def delete_secret(key: str) -> bool:
    """Remove a secret from the OS keyring, the file fallback and legacy services.

    True only if no backend still holds it. A failed OS delete does not swap the backend.
    """
    _ensure_keyring_backend()
    results = [
        _delete_secret_in(service, key) for service in (KEYRING_SERVICE, *LEGACY_KEYRING_SERVICES)
    ]
    if any(changed for _gone, changed in results):
        _mark_secret_changed(key)
    return all(gone for gone, _changed in results)


# ----------------------------------------------------------------------
# First-run check
# ----------------------------------------------------------------------


def ensure_project_root_cwd() -> Path:
    """Pin the working directory to the project root and put it on ``sys.path``. Returns the CWD.

    A manual start or restart inherits the user home and splits ``data/``. Call
    before ``load_config`` at every entry point; idempotent, never raises.
    """
    import logging

    root = str(PROJECT_ROOT)
    if root not in sys.path:
        # First, mirroring the `python -m` cwd seeding the working boots had.
        sys.path.insert(0, root)

    if Path.cwd() != PROJECT_ROOT:
        try:
            os.chdir(PROJECT_ROOT)
            logging.getLogger(__name__).info(
                "Pinned working directory to project root: %s", PROJECT_ROOT
            )
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "Could not pin CWD to project root %s: %s", PROJECT_ROOT, exc
            )
    return Path.cwd()


def is_first_run() -> bool:
    """True when the legacy ``.setup-complete`` marker is absent (not in-app onboarding)."""
    from dodaios.setup.state import setup_complete_marker_exists

    return not setup_complete_marker_exists()


def mark_setup_complete() -> None:
    # The marker lives in dodaios.setup.state so its location cannot desync.
    from dodaios.setup.state import write_setup_complete_marker

    write_setup_complete_marker(f"Setup completed on Python {sys.version.split()[0]}\n")
