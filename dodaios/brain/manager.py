"""BrainManager: Intent-Router + Smart-Fallback + Pipeline-Adapter.

Architecture:

1. **Router** (`dodaios/brain/router.py`) classifies user intent:
   - `fast` → fast model (Haiku) for tool actions, smalltalk
   - `deep` → reasoning model (Opus) for analysis, planning, explanation
   - `code` → Jarvis-Agent-backed heavy worker

2. **Model-Cache**: `(provider_name, model) → Brain-Instance` — multiple
   models of the same family coexist without re-instantiation.

3. **Fallback-Chain**: On error (429, 500, auth, …) the manager tries in order:
   - same provider, deep_model (if fast is rate-limited, try deeper)
   - `claude-api` (OAuth Max plan)
   - `claude-api` (separate quota)
   - `gemini`, `openrouter`, `openai` (when keys are present)
   - Ollama was completely removed from the project on 2026-04-21.

4. **Pipeline-Adapter**: `__call__(text) -> str` for `speech/pipeline.py`.

5. **Voice-Commands**: "wechsel auf gemini", "denk gründlich", "denk schnell".
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
import time
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Sequence,
)
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

# Real turn outcomes feed the passive health record behind the status dots.
from dodaios.brain import provider_health_ledger as _health_ledger
from dodaios.brain import seat_health as _seat_health
from dodaios.brain.local_context import LOCAL_CONTEXT_MARKER

# ONE canonical billing/budget/quota marker list, shared with the test-badge
# classifier (provider_test.classify_provider_error) so the live fallback chain and
# the API-Keys badge can never disagree on "out of credits / over budget" (AP-22).
from dodaios.brain.provider_test import BILLING_LIMIT_MARKERS
from dodaios.brain.spawn_gate import effort_warrants_delegation  # noqa: F401  (re-exported)
from dodaios.brain.tool_shortlist import (
    plan_surface,
    tool_tokens,
)
from dodaios.brain.turn_override import TurnOverride
from dodaios.core.bus import EventBus
from dodaios.core.config import (
    BrainTierConfig,
    JarvisConfig,
)
from dodaios.core.events import (
    AnnouncementRequested,
    BrainProviderSwitched,
    VisionInjected,
)
from dodaios.core.protocols import (
    Brain,
    BrainMessage,
    BrainRequest,
    ImageBlock,
    ReasoningEffort,
    Tool,
)
from dodaios.core.redact import safe_preview
from dodaios.core.response_style import CHART_GUIDANCE, CONVERSATIONAL_RESPONSE_STYLE, LINK_GUIDANCE
from dodaios.core.turn_language import (
    DEFAULT_LOCALE,
    TURN_LANGUAGE,
    detect_text_language,
    resolve_output_language,
)
from dodaios.i18n import catalog as i18n_catalog
from dodaios.i18n.locales import (
    SUPPORTED_LANGUAGE_NAMES,
    SUPPORTED_LOCALES,
    is_known_language,
    phrase_locale,
)
from dodaios.memory import CoreMemory, PersonStore, RecallStore, Soul, UserProfile
from dodaios.memory.curator import Curator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.voice.action_phrases import (
    action_phrase,
)
from dodaios.voice.contextual_readback import render_readback

from . import proactivity as _proactivity
from .dispatcher import BrainDispatcher
from .evidence_gate import live_surface_covers
from .intent_router import RoutingDecision, classify
from .local_action_gate import match_local_action  # noqa: F401  (patched here, read via _m)
from .local_action_gate import (
    _looks_like_desktop_control,
    external_integration_terms,
    is_open_app_intent,
    requires_external_integration,
)
from .local_action_gate import _normalize as _gate_normalize
from .provider_registry import BrainProviderRegistry
from .rate_limit_tracker import RateLimitTracker
from .streaming import aggregate
from .tool_call_recovery import extract_leaked_tool_calls
from .tool_surface import stamp_tool_surface
from .turn_planner import plan_turn
from .voice_command_gate import match_voice_command

if TYPE_CHECKING:
    from dodaios.brain.evidence_gate import EvidenceVerdict
    from dodaios.control.cost import CostMeter as CostMeterLike
    from dodaios.voice.contextual_readback import ReadbackComposer

log = logging.getLogger(__name__)

_PUBLISH_RESPONSE_EVENT: ContextVar[bool] = ContextVar(
    "dodaios.brain.manager.publish_response_event",
    default=True,
)
_TURN_HISTORY_OVERRIDE: ContextVar[tuple[BrainMessage, ...] | None] = ContextVar(
    "dodaios.brain.manager.turn_history_override",
    default=None,
)
#: The typed chat's per-turn pick (dodaios/brain/turn_override.py): read where
#: the chain, the tool surface and the dispatcher are built; never persisted on
#: the manager, so a concurrent voice turn keeps its own brain.
_TURN_OVERRIDE: ContextVar[TurnOverride | None] = ContextVar(
    "dodaios.brain.manager.turn_override",
    default=None,
)


class _SkillTurnState:
    """Task-local mutable state for one manager skill-routing turn."""

    __slots__ = ("content", "injected_inline", "match", "owner", "source")

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.match: Any | None = None
        self.content = ""
        self.source = "match"
        self.injected_inline = False


_SKILL_TURN_STATE: ContextVar[_SkillTurnState | None] = ContextVar(
    "dodaios.brain.manager.skill_turn_state",
    default=None,
)


class _BrainTurnState:
    """Task-local prompt inputs of ONE ``generate`` call.

    The evidence directive, the memory-recall suffix and the answering
    provider's identity used to live on the manager, so a voice turn and a
    typed, society or routine turn running at the same time read each other's
    values into their system prompt. A turn now owns them through a ContextVar
    (the same pattern as ``_SkillTurnState``); a prompt built outside any turn
    (``render_surface_prompt``) installs an empty one.
    """

    __slots__ = (
        "active_turn_identity",
        "evidence_directive",
        "memory_context_suffix",
        "owner",
        "values",
    )

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        #: Values of the ``_TurnField`` attributes (gate state, voice signals).
        self.values: dict[str, Any] = {}
        self.evidence_directive = ""
        self.memory_context_suffix = ""
        self.active_turn_identity: tuple[str, str | None] | None = None


_BRAIN_TURN_STATE: ContextVar[_BrainTurnState | None] = ContextVar(
    "dodaios.brain.manager.brain_turn_state",
    default=None,
)

#: The per-turn values of the turn that finished last IN THIS TASK (owner,
#: values). A voice caller reads ``_last_turn_all_failed`` right after its own
#: ``generate`` returns; the value must be its own turn's, not whichever
#: concurrent turn of another session finished last.
_LAST_TURN_VALUES: ContextVar[tuple[Any, dict[str, Any]] | None] = ContextVar(
    "dodaios.brain.manager.last_turn_values",
    default=None,
)


class _TurnField:
    """A manager attribute whose value belongs to ONE ``generate`` call.

    Inside a turn it lives on that turn's ``_BrainTurnState``, so brain turns of
    different sessions that run concurrently never see each other's gate
    state or voice signals. Outside a turn it reads what this task's last turn
    left (``_LAST_TURN_VALUES``), then the manager-wide last value, so voice
    code that reads a signal after ``generate`` returned keeps working.
    """

    __slots__ = ("default", "name")

    def __init__(self, default: Any) -> None:
        self.default = default
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        state = _BRAIN_TURN_STATE.get()
        if state is not None and state.owner is obj:
            return state.values.get(self.name, self.default)
        last = _LAST_TURN_VALUES.get()
        if last is not None and last[0] is obj and self.name in last[1]:
            return last[1][self.name]
        return obj.__dict__.get("_turn_last_" + self.name, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        state = _BRAIN_TURN_STATE.get()
        if state is not None and state.owner is obj:
            state.values[self.name] = value
            return
        last = _LAST_TURN_VALUES.get()
        if last is not None and last[0] is obj:
            _LAST_TURN_VALUES.set(None)
        obj.__dict__["_turn_last_" + self.name] = value

#: Bounds for the conversation-context block appended to a Computer-Use goal.
#: The deterministic gate ships the RAW current utterance as the mission goal;
#: a correction / follow-up turn ("that is the wrong server", "do it with
#: Computer-Use") carries no task of its own, so the goal must inherit the
#: recent turns that defined it. Kept small: the CU step prompt repeats the
#: goal on every screenshot cycle.
_CU_CONTEXT_MAX_MESSAGES = 40
_CU_CONTEXT_MAX_MESSAGE_CHARS = 2_000

# Plugin-paired skill capture (2026-08-18): whether a catalog plugin holds a
# usable credential is a keyring read, remembered per plugin for this long so
# the turn path pays for it once per window, not once per matched turn.
_PAIRED_CONNECTION_TTL_S = 15.0
_PAIRED_CONNECTION_CACHE: dict[str, tuple[float, bool]] = {}

#: Hard bound on the per-turn vision capture (Wave-3 latency fix). ``vision.
#: current()`` can stall (mss BitBlt hang, paused-state miss, slow disk); without
#: a cap it blocks the whole brain turn on the hot path. On timeout the turn
#: proceeds text-only.
_VISION_COLLECT_TIMEOUT_S: float = 2.5


def _estimate_usd_from_usage(
    meter: Any,
    model: str,
    usage: dict[str, int],
) -> float:
    """Maps `agg.usage` to the CostMeter price table.

    Returns 0.0 when the model is not in the price table — tracking still
    occurs but the budget gate does not trigger. This is intentional:
    prefer no gate over a wrong gate (see BudgetConfig.estimate_usd).
    """
    config = getattr(meter, "_config", None)
    if config is None:
        return 0.0
    prices = getattr(config, "prices", None) or {}
    from dodaios.control.cost import BudgetConfig as _BC
    return _BC.estimate_usd(
        prices, model,
        tokens_in=int(usage.get("input_tokens", 0)),
        tokens_out=int(usage.get("output_tokens", 0)),
        tokens_cache_hit=int(usage.get("cache_hit_tokens", 0)),
    )


PROVIDER_ALIASES = {
    "claude": "claude-api",
    "anthropic": "claude-api",
    "opus": "claude-api",
    "haiku": "claude-api",
    "sonnet": "claude-api",
    "gpt": "openai",
    "chatgpt": "openai",
    "openai": "openai",
    "gemini": "gemini",
    "flash": "gemini",
    "pro": "gemini",
    "openrouter": "openrouter",
    "litellm": "litellm",
    "deepseek": "deepseek",
    "grok": "grok",
    "nvidia": "nvidia",
    "nim": "nvidia",
    "nemotron": "nvidia",
}

SUBAGENT_ONLY_BRAIN_PROVIDERS: frozenset[str] = frozenset(
    {"antigravity", "codex", "openai-codex", "grok-build", "grok-cli", "grokbuild"}
)

_MAIN_BRAIN_FALLBACK_PROVIDER_ORDER: tuple[str, ...] = (
    "gemini",
    "claude-api",
    "openai",
    "openrouter",
    "grok",
    "nvidia",
    "litellm",
)

# Human-readable display names for each brain provider id. Used to tell the
# answering LLM which provider/model it is embodying this turn (the system
# prompt never carried this before, so a "which model are you?" question got a
# guessed answer that defaulted to "Gemini" — forensic 2026-06-20, voice session
# 15:15: Grok was live and answering, yet Jarvis claimed to be Gemini). Kept
# self-contained in the brain layer (no UI-catalog import — that would invert the
# layer dependency) and defensive: an unmapped id degrades to a readable label.
_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "claude-api": "Anthropic Claude",
    "openai": "OpenAI GPT",
    # Both the CLI brain id ("codex") and the sub-agent value ("openai-codex")
    # map to the same readable label, so whichever surfaces as a turn prov_name
    # is named correctly (the user explicitly wants "Codex / GPT-5.5" recognised).
    "codex": "OpenAI Codex (GPT-5.5)",
    "openai-codex": "OpenAI Codex (GPT-5.5)",
    "openrouter": "OpenRouter",
    "litellm": "LiteLLM",
    "deepseek": "DeepSeek",
    "grok": "xAI Grok",
    "nvidia": "NVIDIA NIM",
    "gemini": "Google Gemini",
    "antigravity": "Google Antigravity (Gemini)",
    "grok-build": "Grok Build (xAI subscription)",
    "opencode": "OpenCode",
}


def _provider_display_name(provider: str) -> str:
    """A readable label for a brain provider id (never crashes on unknown ids)."""
    pid = (provider or "").strip()
    mapped = _PROVIDER_DISPLAY_NAMES.get(pid)
    if mapped:
        return mapped
    # Unknown id → readable fallback: "some-new_provider" → "Some New Provider".
    return pid.replace("-", " ").replace("_", " ").title() or "the configured provider"


def _provider_identity_directive(provider: str, model: str | None, name: str) -> str:
    """Authoritative, anti-guessing self-identity line for the system prompt.

    Names the *actual* provider/model answering this turn (set per fallback-chain
    attempt in ``generate()``). ``name`` is kept for callers; the assistant's name
    is already stated by the identity block.
    """
    label = _provider_display_name(provider)
    model_str = (model or "").strip() or "the provider's default"
    return (
        f"Runtime fact: this turn you are running on the brain provider {label} "
        f"(model: {model_str}). If asked which model or provider powers you, say exactly "
        "this; never guess."
    )


# Mapping of Credential-Manager slot -> Brain provider ID. Brain slots only;
# TTS/STT providers have their own lifecycles outside BrainManager.
# Used by the SecretConfigured subscriber to remove the corresponding provider
# from _dead_providers after the user sets a key, so it is retried on the next
# turn without requiring an app restart.
_SECRET_KEY_TO_BRAIN: dict[str, str] = {
    "gemini_api_key": "gemini",
    "google_aistudio_api_key": "gemini",
    "google_api_key": "gemini",
    "anthropic_api_key": "claude-api",
    "openai_api_key": "openai",
    "openrouter_api_key": "openrouter",
    "deepseek_api_key": "deepseek",
    "litellm_api_key": "litellm",
    "litellm_master_key": "litellm",
    "grok_api_key": "grok",
    "xai_api_key": "grok",
    "nvidia_api_key": "nvidia",
}

# ──────────────────────────────────────────────────────────────────
# Tier defaults per provider (source of truth for fast/frontier mapping)
# ──────────────────────────────────────────────────────────────────
#
# As of 2026-04. Update when providers release new models or deprecate old
# ones. Structure: tier → provider → model-id.
#
# "router" = fast tier (<1s first token, tool use, cheap).
# "deep"   = frontier tier (reasoning, long context, more expensive).
#
# Wave-4 migration: the second key was previously named ``"sub_jarvis"``
# because the frontier model drove the Sub-Jarvis tier. The Sub-Jarvis tier
# was removed with the Jarvis-Agent-Bridge migration, but the frontier mapping
# itself is retained as the deep-brain source — hence simply ``"deep"``.
#
# Aliases like "haiku"/"opus" are NOT mapped here — PROVIDER_ALIASES
# resolves them to the canonical provider name first, then
# _resolve_tier_model() looks up here.

# Tool names whose successful execution means a real on-screen DESKTOP ACTION
# happened (open an app, click, type, scroll, …). When the router brain runs
# one of these and then produces NO narration text — a known Gemini behaviour
# after a function call — the turn is NOT empty/confused: a confirmation must be
# spoken, never a clarifying question (live bug 2026-06-09, AP-19-adjacent: a
# successful computer_use run that opened Chrome was answered with "Wie meinst
# du das genau?"). ``computer_use`` + ``open_app`` are the router-reachable
# desktop tools; the rest are the in-loop GUI primitives, listed for robustness
# so a future router-exposed action stays covered.
_DESKTOP_ACTION_TOOL_NAMES: frozenset[str] = frozenset({
    "computer_use",
    "open_app",
    "click",
    "click_element",
    "type_text",
    "hotkey",
    "scroll",
    "move_mouse",
    "switch_window",
})


TIER_DEFAULTS_BY_PROVIDER: dict[str, dict[str, str]] = {
    "router": {
        # Frontier 2026-Q2 — main Jarvis tier (latency-first, pure dispatcher).
        # 2026-04-29: gemini-3-flash is only available as -preview (Google API
        # returns 404 NOT_FOUND without -preview).
        "claude-api": "claude-haiku-4-5-20251001",
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.5",
        "deepseek": "deepseek-flash",
        # Gateway: a model-less OpenRouter user must NEVER default to a paid
        # Anthropic id (that billed Opus/Haiku on a free key — §3/AP-22). A free
        # general-purpose model degrades with a clean 404 if ever retired, instead
        # of silently billing the most expensive model in the catalog.
        "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
        # Proxy aliases belong to the user's config. Empty means the plugin
        # asks the proxy which model to use.
        "litellm": "",
        # Grok 4.3 is available across regions and supports local tool use.
        "grok": "grok-4.3",
        # NVIDIA NIM router pick: a widely-hosted, tool-capable, low-latency model
        # (the reasoning Nemotron flagships are the deep tier). The user's own pick
        # from the live catalog wins over this. 2026-08-09: moved off Meta's
        # Llama 3.3 70B (dense, late 2024) to NVIDIA's own current sparse
        # generation — 12B of 120B activate per token, so it answers faster than
        # the dense model it replaces. Verified against integrate.api.nvidia.com.
        "nvidia": "nvidia/nemotron-3-super-120b-a12b",
        "mistral": "mistral-small-3.1",
        # Local providers: no server-side catalog is knowable ahead of time —
        # empty means "the plugin discovers the first installed model".
        "ollama": "",
        "local-openai": "",
    },
    "deep": {
        # Frontier 2026-Q2 — deep brain (user mandate 2026-04-29:
        # frontier everywhere). 2026-06-14: switched from claude-fable-5 to
        # claude-opus-4-8 — fable-5 is approved-access-only and the Claude Max
        # subscription cannot reach it ("Claude Fable 5 is currently
        # unavailable"); this deep tier calls the Brain API directly and has no
        # model-unavailable retry, so the pinned model must be one we can reach.
        "claude-api": "claude-opus-4-8",
        "gemini": "gemini-3.1-pro-preview",
        "openai": "gpt-5.5-pro",
        "deepseek": "deepseek-v4-pro",
        # Gateway: never a paid Anthropic default for a model-less OpenRouter
        # user (§3/AP-22) — see the router-tier note above.
        "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "litellm": "",
        "grok": "grok-4.3",
        # NVIDIA NIM deep pick: NVIDIA's own reasoning flagship. 2026-08-09:
        # the Llama-3.1-based Nemotron Ultra gives way to the current
        # Nemotron 3 Ultra (verified against integrate.api.nvidia.com), which
        # the OpenRouter tiers above already name.
        "nvidia": "nvidia/nemotron-3-ultra-550b-a55b",
        "mistral": "mistral-large-3",
        # Local providers: empty = plugin-side discovery (see router tier).
        "ollama": "",
        "local-openai": "",
    },
}

def _mirror_tier_defaults(source: str, target: str) -> None:
    """Give ``target`` the same per-tier default models as ``source``.

    For provider families that are the same catalogue on a different endpoint.
    Re-typing the ids instead would create a second literal list that drifts on
    the next model rotation — the BUG-008 shape — and it would drift on exactly
    the tier a production project cares about most.
    """
    for tier in TIER_DEFAULTS_BY_PROVIDER.values():
        if source in tier:
            tier[target] = tier[source]


# Vertex AI serves the SAME Gemini model ids as AI Studio; the endpoint and the
# billing account differ, the catalogue does not.
_mirror_tier_defaults("gemini", "vertex")


# Hard loop bounds for DELEGATED realtime voice turns (prefer_tool_model).
# Classic chat turns keep the dispatcher defaults (15 rounds, no deadline).
#
# These are CEILINGS for a runaway turn, not a target for a working one. The
# 2026-07-14 incident (an unbounded delegate at 14 rounds / 66 s) was answered
# with 6 rounds / 20 s, and that cut the churn — but it also guillotined every
# honest multi-step task at about five steps, which the user then heard as
# "so far I got to …" (GT-11). Round count and wall clock are not the same
# risk: a round only ever happens because the model asked for another tool, so
# 12 rounds cost nothing on a turn that finishes in three. The wall clock is
# the real latency, and 45 s is what a genuinely progressing ~8-round turn
# needs at Flash speed with reasoning off (≈2 s model + ≈3 s tool per round).
#
# Both paths still end the turn gracefully rather than hard-breaking:
# ToolUseLoop forces ONE final tool-less synthesis round over the evidence
# already gathered (_BUDGET_FINAL_DIRECTIVE / _DEADLINE_FINAL_DIRECTIVE).
#
# KNOWN COST of the flat 45 s, and the follow-up it asks for: a turn that is
# CHURNING (re-issuing near-identical lookups) now burns 45 s before it is cut
# off, where it used to burn 20. The correct shape is a deadline that starts
# short and is EXTENDED by each successful tool call — progress buys time,
# churn does not — but ``deadline_s`` is a single float fixed at ToolUseLoop
# construction, so that fix lives in dodaios/brain/tool_use_loop.py (+ the
# dispatcher pass-through), not here.
_DELEGATE_MAX_TURNS: int = 12
_DELEGATE_DEADLINE_S: float = 45.0
# Delegated rounds ask the provider to skip internal "thinking" entirely.
# Live 2026-07-17 (FlightRecorder p50 15-18 s, worst 33 s): the hoisted Tool
# Model (Gemini Flash) ran every one of its 3-6 sequential rounds with the
# SDK-default dynamic thinking over a ~53k-token context, so plain questions
# ran the 20 s deadline out. The router-tier factory caps thinking only on
# the tier's OWN provider entry — a live provider switch (e.g. router →
# openrouter) parks that cap on the wrong entry and the hoisted Tool Model
# escapes it. Passing the per-request hint here covers the delegated turn
# deterministically, independent of which provider entry carries the cap.
# Same doctrine as the router thinking cap (BUG-LATENCY 2026-05-24) and the
# Computer-Use calls (dodaios/cu/brain_call.py); providers without a
# reasoning knob ignore the hint (AP-21: capability hint, no provider pin).
_DELEGATE_REASONING_EFFORT: Literal["none"] = "none"
# Appended to the system prompt of DELEGATED voice turns only. Live 2026-07-17
# (turn af736681): the tool loop spent 5 sequential rounds on one question —
# three near-identical wiki-recall calls, then wiki-list, then wiki-page-read —
# and ran the 20 s deadline out. Every round is a full provider round-trip, so
# round count IS the latency. Static text (byte-stable across turns) so the
# delegated prefix keeps its own provider prompt-cache entry.
_DELEGATE_VOICE_DIRECTIVE = (
    "DELEGATED VOICE TURN: the user is waiting on a live call and every model round costs "
    "seconds. Batch independent lookups into one round (search_web takes several "
    "`queries`), never repeat a call whose result you have, and answer as soon as the "
    "evidence suffices."
)


def _resolve_tier_model(
    tier: str,
    provider: str,
    explicit_model: str | None,
) -> str:
    """Returns the model for (tier, provider).

    1. If `explicit_model` is set (from [brain.router] in jarvis.toml),
       that value is used — user override takes precedence.
    2. Otherwise look up in TIER_DEFAULTS_BY_PROVIDER.
    3. Otherwise return an empty string (the Brain constructor then uses its
       hardcoded DEFAULT_MODEL as a fallback).

    Unknown providers do NOT raise — every brain plugin has its own
    DEFAULT_MODEL as an emergency anchor.
    """
    if explicit_model:
        return explicit_model
    return TIER_DEFAULTS_BY_PROVIDER.get(tier, {}).get(provider, "")


def get_tier_default_model(tier: str, provider: str) -> str | None:
    """Public API for the setup wizard / UI / voice_command_gate.

    Returns the default model for (tier, provider) or None if no default
    exists. The caller can use this to decide whether the provider is
    supported at all.
    """
    return TIER_DEFAULTS_BY_PROVIDER.get(tier, {}).get(provider)


def _coerce_main_brain_provider(provider: str | None, *fallbacks: str | None) -> str:
    """Return a main-brain-capable provider.

    Some provider integrations exist only for the heavy subagent worker. They
    must remain present in the codebase for that path, but an old persisted
    ``brain.primary`` must not make the main router run through them.
    """
    candidate = (provider or "").strip()
    if candidate and candidate not in SUBAGENT_ONLY_BRAIN_PROVIDERS:
        return candidate
    for fallback in (*fallbacks, *_MAIN_BRAIN_FALLBACK_PROVIDER_ORDER):
        value = (fallback or "").strip()
        if value and value not in SUBAGENT_ONLY_BRAIN_PROVIDERS:
            return value
    return _MAIN_BRAIN_FALLBACK_PROVIDER_ORDER[0]


# ──────────────────────────────────────────────────────────────────
# Force-spawn pattern builder (persona mandate phase 3)
# ──────────────────────────────────────────────────────────────────
#
# The three lists in ``BrainRoutingConfig`` are compiled into three regex
# patterns here. ``BrainManager._should_force_spawn`` evaluates them in
# order: smalltalk allowlist wins (no spawn), otherwise verb match → spawn,
# otherwise marker match → spawn.
#
# Pattern matches ``\bnichts\b`` as a "negative-lookahead-no-match" sentinel
# for empty lists — prevents an empty verb list from degenerating into a
# greedy match-everything regex.

_NEVER_MATCH_RE: re.Pattern[str] = re.compile(r"(?!.*)", re.IGNORECASE)


# ``MessageSent.source_layer`` values for CONVERSATIONAL turns that must NEVER
# force-spawn a mission, whatever their text contains. A drag-dropped mission
# recap (``ui.web.ws.mission_inject``) embeds the dropped card's OWN text
# verbatim, so a title carrying a spawn trigger ("sub-agent") or an action verb
# ("Write …") would otherwise leak that trigger into the directive and spawn a
# NEW mission whose only deliverable is a conversational recap (no file) ->
# empty diff -> critic_loop_exhausted. The doom-loop fixed 2026-06-16: every
# failed mission the user dragged in to discuss spawned another failed mission.
# Keep in sync with ``dodaios.ui.web.mission_inject.MISSION_INJECT_SOURCE_LAYER``
# and ``dodaios.brain.drop_context.DROP_SOURCE_LAYER`` (parity tests in
# tests/unit/brain/test_routing.py). ``ui.drop`` = a dragged-and-dropped file /
# image / text: reacted to inline, never auto-dispatched as a worker.
_NON_SPAWN_SOURCE_LAYERS: frozenset[str] = frozenset(
    {"ui.web.ws.mission_inject", "ui.drop"}
)


# Two-turn voice/chat confirmation for a consequential ``ask``-tier tool. Turn N
# defers the action (the executor returns ``VOICE_CONFIRM_SENTINEL``) and speaks a
# question; this holds what turn N+1 needs to resolve the user's "ja"/"nein".
# Bounded re-asks avoid a soft-lock on a persistently ambiguous answer.
_MAX_CONFIRM_REASKS = 2
_SCREEN_CONFIRM_TTL_S = 20.0


class _PendingVoiceConfirm:
    """A deferred consequential action awaiting the user's next yes/no."""

    __slots__ = ("trace_id", "lang", "tool_name", "reasks")

    def __init__(self, trace_id: UUID, lang: str, tool_name: str, reasks: int = 0) -> None:
        self.trace_id = trace_id
        self.lang = lang
        self.tool_name = tool_name
        self.reasks = reasks


class _PendingScreenConfirm:
    """A short-lived, conversation-scoped proposal to inspect the screen."""

    __slots__ = ("expires_at", "lang")

    def __init__(self, lang: str, expires_at: float) -> None:
        self.lang = lang
        self.expires_at = expires_at


# Option A (2026-06-15): a heavy-research request whose deliverable is an ANSWER
# (comparison / overview / recommendation / summary) is answered INLINE via the
# router's search_web tool; only research that BUILDS a verifiable ARTIFACT (a
# file / report / document) offloads to a sub-agent mission, because the
# Worker->Critic pipeline grades artifacts via git diff and is hostile to an
# answer-only research turn (empty-diff veto -> critic_loop_exhausted, live
# mission 019ecb56, 2026-06-15). These three regexes decide "wants an artifact".
#
# A build/produce VERB (write/create/build/generate/export/save + DE forms).
# Deliberately disjoint from the research/analysis verbs in
# ``heavy_research_verbs`` (recherchier/analysier/compar/...) so a pure research
# answer never matches.
_BUILD_VERB_RE: re.Pattern[str] = re.compile(
    r"\b(writ|wrote|creat|build|buil|generat|produc|draft|compil|render|"
    r"export|saved?|"
    r"schreib|geschrieben|erstell|baue|bau|generier|verfass|speicher|exportier)"
    r"\w*",
    re.IGNORECASE,
)
# A document / artefact NOUN — the thing being built is a file-shaped deliverable.
_DOC_NOUN_RE: re.Pattern[str] = re.compile(
    r"\b(report|document|deck|slides?|spreadsheet|presentation|"
    # build-a-deliverable nouns (a file-shaped result the Worker->Critic
    # pipeline can verify via git diff): web/app/doc artefacts, DE + EN. A
    # build VERB is still required by _research_wants_artifact, so a bare
    # question ("what is an html file") never matches. "summary" is
    # deliberately EXCLUDED — it is an ANSWER, not a file (discriminator test).
    r"website|web ?page|webseite|html|app|application|anwendung|"
    r"dashboard|landing ?page|visuali\w+|script|skript|"
    r"bericht|dokument|tabelle|praesentation|präsentation)\b",  # i18n-allow: DE artefact nouns
    re.IGNORECASE,
)
# A named file / real extension, or an explicit "into a file" instruction — an
# artefact deliverable on its own, no build verb required ("... into ai_news.md").
_NAMED_FILE_RE: re.Pattern[str] = re.compile(
    r"\.(md|txt|html?|json|csv|pdf|docx?|xlsx?|pptx?|ya?ml|toml)\b"
    r"|\bfile\s+named\b|\bnamed\s+\S+\.\w+"
    r"|\bdatei\s+namens\b|\bin\s+eine\s+datei\b|\bin\s+die\s+datei\b"  # i18n-allow: DE file phrasing
    r"|\binto\s+a\s+file\b",
    re.IGNORECASE,
)


# BUG-LIVE-04 (Recon-Agent 3, 2026-05-16): Whisper transcribes silence,
# background TV, music, jingles into a small set of well-known sentinel
# strings. Empirical sample from data/jarvis_desktop.log (~75% mission
# fail rate on 2026-05-16 — half driven by these phrases).
#
# 2026-05-17 (H2 from audit-team 10): the original single-set + startswith
# match was too greedy for short Single-Token seeds. "you" filtered every
# English utterance starting with "You" (e.g. "You there?"), "musik"
# filtered "Musik lauter machen", "applaus" filtered "Applaus für die
# Band". Real user voice queries were silently dropped from the
# force-spawn path. The fix splits the seeds into two buckets:
#
#   _WHISPER_FP_EXACT_ONLY     -- short tokens that also appear in
#                                 legitimate speech; only the *whole*
#                                 utterance must equal the seed (after
#                                 punctuation strip).
#   _WHISPER_FP_PREFIX_OK      -- multi-word phrases distinctive enough
#                                 that any utterance starting with them
#                                 is almost certainly a Whisper artefact;
#                                 startswith match still allowed.
#
# An entry must appear in exactly ONE bucket. The combined frozenset
# WHISPER_FALSE_POSITIVE_SEEDS below is kept as a backwards-compatible
# alias for any external caller (tests, telemetry) that wants the
# complete catalogue.
_WHISPER_FP_EXACT_ONLY: frozenset[str] = frozenset({
    # Short tokens / single words that legit user speech also starts with.
    "you",
    "musik",
    "[musik]",
    "applaus",
    "[applaus]",
    "subscribe",
    "tschüss",
    "untertitel",
    "untertitelung",
    "thank you",
    "thank you.",
})

_WHISPER_FP_PREFIX_OK: frozenset[str] = frozenset({
    # Multi-word phrases distinctive enough that startswith is safe.
    "untertitelung des zdf für funk, 2017",
    "untertitelung des zdf für funk",
    "vielen dank",
    "vielen dank fürs zuschauen",
    "vielen dank für ihre aufmerksamkeit",
    "bis zum nächsten mal",
    "bis zum nächsten mal!",
    "thanks for watching",
    "thank you for watching",
    "see you next time",
    "ich verstehe es nicht",
})

# Backwards-compatible alias — equals the union of both buckets so any
# external introspection (telemetry, eval harness) still sees the full
# catalogue. Disjoint by construction; assertion at import time catches
# accidental duplication when the lists are edited.
_WHISPER_FALSE_POSITIVE_SEEDS: frozenset[str] = (
    _WHISPER_FP_EXACT_ONLY | _WHISPER_FP_PREFIX_OK
)
assert not (_WHISPER_FP_EXACT_ONLY & _WHISPER_FP_PREFIX_OK), (
    "Whisper FP seed lists must be disjoint"
)
_PC_CONTROL_RE: re.Pattern[str] = re.compile(
    r"\b("
    r"klick|click|tippe|tipp|type|schreib|schreibe|reinschreib|prompt|prompten|"
    r"absenden|sende|send|drueck|druecke|drück|drücke|press|taste|hotkey|"
    r"browser|fenster|feld|eingabefeld|chatgpt|tab|button|pc|desktop|"
    # The live SURFACE the user names to act ON — screen / Bildschirm. A request
    # that points at the screen is computer-use (a worker has no desktop), so
    # naming it must register here: it keeps the turn OFF the sub-agent path and
    # marks it an action turn so a tool-incapable talker delegates it to a
    # tool-capable provider that picks computer_use (user pain 2026-06-21:
    # "mach es am Bildschirm" / "do it on screen" was not recognized at all).
    r"bildschirm|screen|"
    r"maus|mouse|cursor"
    r")\w*\b",
    re.IGNORECASE,
)

_INSTRUCTIONAL_QUESTION_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:"
    # "wie <verb> ich/man …" — a HOW-TO question, never a build request. The
    # build/create verbs are listed too so "wie erstelle/baue/schreibe ich eine
    # HTML-Datei" stays an inline answer and is not mistaken for "build me a file"
    # (live bug 2026-06-21). The English how-to is already caught by "how do/can …".
    r"wie\s+(?:kann|koennte|könnte|muss|soll|mach|mache|macht|geht|funktioniert"
    r"|erstell|erstelle|erstellt|baue|bau|baut|schreib|schreibe|schreibt"
    r"|programmier|programmiere|generier|generiere|implementier|implementiere)\s+"
    r"|was\s+(?:ist|bedeutet|heisst|heißt)\s+"
    r"|woran\s+erkenne\s+"
    r"|warum\s+"
    r"|how\s+(?:do|can|could|should|would)\s+"
    r"|what\s+(?:is|does|are)\s+"
    r"|why\s+"
    r")",
    re.IGNORECASE,
)


def _build_verb_pattern(terms: list[str]) -> re.Pattern[str]:
    """``\\b<term>\\w*\\b`` regex for action verbs including conjugated forms."""
    if not terms:
        return _NEVER_MATCH_RE
    parts = [re.escape(t) + r"\w*" for t in terms]
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


def _build_marker_pattern(markers: list[str]) -> re.Pattern[str]:
    """``\\b<marker>\\b`` regex for external-system markers (PR/Repo/...)."""
    if not markers:
        return _NEVER_MATCH_RE
    parts = [re.escape(m) for m in markers]
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


def _build_smalltalk_pattern(allowlist: list[str]) -> re.Pattern[str]:
    """Smalltalk allowlist as a case-insensitive substring match."""
    if not allowlist:
        return _NEVER_MATCH_RE
    parts = [re.escape(p) for p in allowlist]
    return re.compile(r"(?:^|\b)(?:" + "|".join(parts) + r")(?:\b|$)", re.IGNORECASE)


# Leading greeting / wake-word / politeness run, stripped before the smalltalk
# re-check in ``BrainManager._is_smalltalk``. Anchored at ^, repeats so several
# leading tokens collapse ("Hey Jarvis, hallo, öffne ..."), and swallows the i18n-allow
# trailing separators (comma / period / …). Longer tokens ("hey jarvis") precede
# their prefix ("hey") so the longest run is consumed. Live bug 2026-06-07
# (data/jarvis_desktop.log 18:19:07): "Hallo, öffne ihn für mich" was silenced i18n-allow
# as smalltalk because the allowlist substring-matched the leading "Hallo".
_GREETING_PREFIX_RE = re.compile(
    r"^(?:\s*(?:"
    r"hey\s+jarvis|hi\s+jarvis|hallo\s+jarvis|ok(?:ay)?\s+jarvis|jarvis|"
    r"guten\s+morgen|guten\s+abend|guten\s+tag|good\s+morning|good\s+evening|"
    r"hey|hi|hallo|hello|moin|servus|"
    r"ok|okay|bitte|danke|thanks|thank\s+you"
    r")\b[\s,.!?:;-]*)+",
    re.IGNORECASE,
)


# A clear ACTION / request signal inside an utterance that ALSO matched the
# smalltalk allowlist. A continuation-recombine (or a polite preamble) can glue
# an answered chit-chat turn onto a real command (a smalltalk greeting followed
# by "open the oldest Bill-Gates post for me") or trail one ("open Chrome,
# thanks"). The smalltalk allowlist then matches the conversational part and
# (without this signal) the WHOLE turn is demoted to a tool-less smalltalk turn,
# hiding computer_use / spawn_worker (live bug 2026-06-19 11:43, the Bill-Gates
# turn: the deep brain answered a no-op "saved your note" reply and never opened
# the browser). When this signal is present the turn is a COMMAND, not
# chit-chat, so ``_is_smalltalk`` keeps the action tools visible. Pure regex, no
# LLM (AP-11). Intentionally NARROW (high-signal tokens + explicit request
# framing only) so a long but signal-less friendly remark carries no match and
# stays smalltalk, preserving the anti-fake-spawn tool-hiding.
_ACTION_REQUEST_RE = re.compile(
    r"(?:"
    # open / launch an app, file, page, browser
    r"\b(?:oeffn\w*|öffn\w*|aufmach\w*|aufzumach\w*|start\w*|open\w*|launch\w*)\b|"  # i18n-allow
    # research / analysis / search
    r"\b(?:recherchier\w*|research\w*|analys\w*|analyz\w*|untersuch\w*|"  # i18n-allow
    r"vergleich\w*|such\w*|search\w*|google\w*)\b|"  # i18n-allow
    # explicit action verbs
    r"\b(?:zeig\w*|lies|lese|liest|schreib\w*|install\w*|deinstallier\w*|"  # i18n-allow
    r"deploy\w*|spawn\w*|delegier\w*)\b|"
    # request framing (DE)
    r"\bich\s+(?:möchte|will|brauche|hätte\s+gern)\b|"  # i18n-allow
    r"\b(?:kannst|könntest|würdest)\s+du\b|"  # i18n-allow
    r"\b(?:mach|zeig|gib|hol|such|lies|öffne|bau)\s+(?:mir|mal|uns)\b|"  # i18n-allow
    # request framing (EN)
    r"\b(?:can|could|would)\s+you\b|\bi\s+(?:want|need)\b|\bi'?d\s+like\b|"
    r"\b(?:show|give|help)\s+me\b"
    r")",
    re.IGNORECASE,
)


def _looks_like_pc_control(user_text: str) -> bool:
    """Detects local screen/PC control requests intended for the computer-use harness."""
    return bool(_PC_CONTROL_RE.search(user_text or ""))


# Subset of ``force_spawn_phrases`` that NAMES the execution vehicle (a worker),
# as opposed to merely describing how THOROUGH the work should be. This is a
# PARTITION of the existing trigger phrases, not a new detection list: it only
# decides which matched trigger keeps absolute priority over the computer-use
# stand-down. Naming the vehicle ("subagent" / "spawn" / "openclaw" / "delegate")
# is an UNAMBIGUOUS spawn request (mandate 2026-06-15) and wins over everything.
# A DEPTH marker ("deep dive" / "gründlich" / "umfassend" / …) is ambiguous — it
# overlaps with computer-use requests ("Mach einen Deep Dive mit Computer Use in
# meinem Chrome Browser …") — so it must NOT override an explicit on-screen
# request; that computer-use-vs-spawn call is the LLM router's. Matched as a
# substring of the trigger the regex returned, so conjugations are covered
# ("spawne"/"gespawnt" -> "spawn", "delegiert" -> "delegier"). No depth phrase
# contains any of these stems, so the partition is clean.
_VEHICLE_NAME_TRIGGER_STEMS: frozenset[str] = frozenset({
    "openclaw", "open claw", "open-claw",
    "subagent", "sub-agent", "sub agent",
    "spawn", "delegier", "delegate",
})


def _trigger_names_vehicle(matched_trigger: str) -> bool:
    """True iff the matched force-spawn trigger NAMES a worker vehicle (vs. a
    thoroughness/depth descriptor). Only a vehicle name keeps absolute priority
    over the computer-use stand-down — a depth marker yields to it."""
    m = (matched_trigger or "").strip().lower()
    return any(stem in m for stem in _VEHICLE_NAME_TRIGGER_STEMS)


def _is_instructional_question(user_text: str) -> bool:
    """True for how-to / explanatory questions that should be answered directly.

    A question opener does NOT make the whole turn a question. "Warum ist
    Spotify nicht offen, mach es auf" asks and then commands, and reading it as
    instructional suppresses the command — the same blind spot the tool loop's
    copy of this rule carried until commit 163b2808. That copy owns the
    imperative test; this one calls it rather than growing a second version
    that can drift.
    """
    text = user_text or ""
    if not _INSTRUCTIONAL_QUESTION_RE.search(text):
        return False
    from dodaios.brain.tool_use_loop import (  # noqa: PLC0415 — cycle-safe here
        _has_trailing_imperative,
    )

    return not _has_trailing_imperative(text)


# Spawn-tool names hidden from a plain knowledge question's tool surface — the
# vehicles that delegate to a background worker. A read/search/desktop tool is
# NEVER in here (the question must stay answerable inline).
_SPAWN_TOOL_NAMES: frozenset[str] = frozenset({"spawn_worker", "multi_spawn"})

# Agentic-IDE pane tools that only make sense RELATIVE TO AN OPEN WORKSPACE.
# With none open, every one of them can only fail — while their schemas cost
# ~10 KB of input on every tool-loop iteration (2026-07-28 cost audit).
# Deliberately NOT listed: ``agentic-ide-status`` (answers "nothing is open"
# honestly) and ``agentic-ide-resume`` (the command that OPENS a workspace
# by voice — hiding it would strand the feature).
# The on-demand artifact tool. Offered ONLY on a turn that explicitly asks for
# a page/picture (see _hide_artifact_tool_without_request): the maintainer's
# rule is that an artifact is something the user asks for, never something the
# assistant decides an answer deserves.
_ARTIFACT_TOOL_NAME: str = "create_artifact"

# Agentic-IDE pane tools that only make sense RELATIVE TO AN OPEN WORKSPACE.
_AGENTIC_IDE_WORKSPACE_TOOL_NAMES: frozenset[str] = frozenset({
    "agentic-ide-terminal-report",
    "agentic-ide-prompt",
    "agentic-ide-fanout",
    "agentic-ide-spawn-terminals",
    "agentic-ide-move-terminal",
    "agentic-ide-close-agent-terminals",
    "agentic-ide-focus",
})

# Consequential action tools a signalless turn must never INHERIT from the
# conversation context. Forensic 2026-06-27: the German smalltalk "Was geht ab?"
# was mis-transcribed as "Lask it up!" [en] conf 0.509, missed every smalltalk /
# whisper-junk list, and the router-LLM (reading a 30k-token context full of the
# prior "open Discord, bridge-mine channel" command) re-ran that exact CU plan on
# a turn that asked for nothing. ``computer_use`` + the spawn vehicles are the
# heavy, irreversible-looking actions hidden here. Deliberately NOT hidden: the
# read-only ``screenshot`` tool (so "Was siehst du auf dem Bildschirm?" still
# works) and ``open_app`` (lighter; naming an app already reads as action-intent).
# INHERITANCE NEEDS SOMETHING TO INHERIT (2026-08-17): the hide applies only
# while a desktop episode is live or just ended — see
# ``_hide_action_tools_on_signalless_turn``. Outside one there is no prior plan
# in the context, and hiding the vehicle then only costs the turn its ability
# to act.
_INHERITABLE_ACTION_TOOL_NAMES: frozenset[str] = _SPAWN_TOOL_NAMES | {"computer_use"}

# The only tools a SMALLTALK turn may not see. The 2026-05-01 incident was ONE
# tool class, not the whole surface: the LLM hallucinated a ``spawn_worker`` on
# chit-chat and then reported test work it had never started. Nothing else in the
# surface caused that. The historical full-hide additionally removed every action
# vehicle from a turn the substring allowlist merely READ as chit-chat, which is
# its own bug — the model then has nothing to act with, whatever the user asked
# for. See ``_smalltalk_tool_override``.
_SMALLTALK_HIDDEN_TOOL_NAMES: frozenset[str] = _SPAWN_TOOL_NAMES

# Deterministic write/record tools that create user-visible state (a contact, a
# profile field, a wiki note, a calendar event, a phone call). On a turn with NO
# action signal of its own these must NOT sit in the LLM surface, or the model
# can pick one on a plain conversational question (deep-dive 2026-06-30: a
# "does my budget fit?" turn had google_calendar/contact-upsert/wiki-ingest/
# update-profile ungated). Hidden by the signalless guard, with a hard exemption
# for any tool the deterministic layer ALREADY mandated this turn (a real "merk
# dir, dass…" keeps wiki-ingest via resolve_save_mandate; a calendar READ keeps
# google_calendar via the evidence gate) so the say-do write feature and calendar
# reads never regress. The background wiki (VoiceFactBridge) is untouched — it is
# not a model-callable tool (AP-9).
_DETERMINISTIC_WRITE_TOOL_NAMES: frozenset[str] = frozenset({
    # Keys are the tools' .name attributes (what the turn dict is keyed by) —
    # NOT the hyphenated entry-point names. "update-profile" (the ep name)
    # sat here since introduction, so the signalless gate never actually
    # stripped update_profile (found in the 2026-07-06 pipeline audit).
    "contact-upsert", "update_profile", "remember", "google_calendar",
    "call-contact",
})

# Tools withheld on a turn that carries a CAPTURED SCREEN image. Screen pixels
# and UI text are untrusted evidence (docs/screen-context.md §4.2), so injected
# on-screen text must not be able to start something expensive and unattended:
# a background worker, or a silent record write (a contact, a calendar entry, a
# wiki note, an outbound call). Everything else stays — including
# ``computer_use``, whose "looking is not operating" boundary (maintainer mandate
# 2026-08-02) is enforced per call by ``cu_gate.llm_computer_use_allowed`` in
# ``tool_use_loop``/``realtime.tools``. That gate reads the USER's utterance, so
# a look request is refused there even inside a live desktop episode, and text
# rendered on screen can never unlock it. See ``_image_turn_tool_override``.
_SCREEN_TURN_HIDDEN_TOOL_NAMES: frozenset[str] = (
    _SPAWN_TOOL_NAMES | _DETERMINISTIC_WRITE_TOOL_NAMES
)

# The user literally names a skill ("nutz den Skill cloud-debug", "run the
# skill …"). An explicit skill request is its own vehicle and always keeps
# ``run-skill`` visible — the pc-control run-skill hide below must never veto
# it. Same word in DE/EN; matched with word boundaries so unrelated words
# ("skillful") don't trip it.
_EXPLICIT_SKILL_REQUEST_RE = re.compile(r"\bskills?\b", re.IGNORECASE)

# Interrogative opener (DE / EN / ES) — the leading question word of a plain
# "what/which/who/how/…"-style factual question. Anchored at the start after an
# optional wake/greeting/politeness run so "Jarvis, welche Firmen …" still
# matches. A trailing "?" is accepted as an independent signal (STT often drops
# the question word's leading capital but keeps the rising-intonation "?"), but
# the real anchor is the opener — STT frequently strips terminal punctuation.
_QUESTION_OPENER_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:(?:hey|hallo|hi|hello|ok(?:ay)?|bitte|please|jarvis)[\s,]+){0,3}"
    r"(?:"
    # DE interrogatives
    r"was|welche[rsnm]?|wer|wen|wem|wessen|wie ?viele?|wie|wieso|warum|weshalb|"
    r"wann|woher|wohin|wo|wof[üu]r|womit|wodurch|"
    # EN interrogatives
    r"what|which|who|whom|whose|how|when|where|why|"
    # ES interrogatives
    r"qu[ée]|cu[áa]les?|qui[ée]nes?|c[óo]mo|cu[áa]ndo|d[óo]nde|cu[áa]nt[oa]s?"
    r")\b",
    re.IGNORECASE,
)


def _is_plain_knowledge_question(user_text: str) -> bool:
    """True iff the utterance is shaped like a plain factual/knowledge question.

    Pure form check (interrogative opener OR a trailing "?") — it does NOT judge
    action intent or artifact-build; the caller combines this with the existing
    deterministic detectors. Pure regex (AP-11 safe), DE/EN/ES.
    """
    t = (user_text or "").strip()
    if not t:
        return False
    return bool(_QUESTION_OPENER_RE.search(t) or t.endswith("?"))


# Definitional "what IS X" guard for the deterministic skill match. A plugin
# skill's voice trigger is an un-anchored bare-name pattern (e.g. ``(github|…)``)
# that fires on ANY mention — including when the app is merely the SUBJECT of a
# knowledge question ("was ist GitHub?", "what is Stripe?"). Such a turn must be
# ANSWERED, not captured by the skill (live skill-routing eval 2026-06-24: both
# negative controls over-fired here). Precision over recall: suppress ONLY when
# the matched trigger token is the predicate of a copula in a definitional
# opener — so a real data request that merely starts with "was ist" ("was ist
# in meinem Posteingang?", token "posteingang") is NOT suppressed, because there
# the token does not sit directly after the copula (the "in"/"mein" data context
# breaks the predicate run).
_DEFINITIONAL_OPENER_RE = re.compile(
    r"^\s*(?:was\s+(?:ist|sind|bedeutet|war|waren)"
    r"|wof[üu]r\s+(?:ist|steht|braucht|nutzt|benutzt|verwendet)"
    r"|erkl[äa]r(?:e|st|en)?\b"
    r"|what(?:'s|\s+is|\s+are|\s+does)\b"
    r"|tell\s+me\s+(?:about|what)\b"
    r")",
    re.IGNORECASE,
)
# Copula → (optional adverb, but NOT a data-context word) → optional article →
# the matched token. ``%s`` is filled with the re.escape'd trigger token.
_DEFINITIONAL_PREDICATE_TMPL = (
    r"\b(?:ist|sind|war|waren|is|are|was|were|bedeutet|means)\s+"
    r"(?:(?!\b(?:in|auf|an|aus|von|mein|meine|meinem|meinen|my|on|from|of)\b)"
    r"\w+\s+){0,2}"
    r"(?:ein(?:e|er|en)?\s+|a\s+|an\s+|the\s+)?%s\b"
)


def _is_definitional_question_about(user_text: str, token: str) -> bool:
    """True when ``user_text`` is a definitional question whose subject IS the
    matched trigger ``token`` — so firing that skill would be wrong."""
    if not user_text or not token:
        return False
    if not _DEFINITIONAL_OPENER_RE.match(user_text):
        return False
    pat = re.compile(_DEFINITIONAL_PREDICATE_TMPL % re.escape(token), re.IGNORECASE)
    return bool(pat.search(user_text))


# Opinion / advice / recommendation / decision questions, and casual
# question-openers ("ich hab da mal eine Frage"). These are CONVERSATION, not
# work: the brain answers them inline — they must NEVER force-spawn a worker,
# even when they contain an everyday word that collides with an action verb in
# the universal catalogue ("Frage" -> "frag"/"frage", the filler particle
# "halt" -> "halt"). A live relocation-comparison turn once force-spawned:
# "ich hab ne Frage ... was würdest du mir empfehlen?"
# force-spawned because has_action_intent matched "Frage"/"halt", so
# _is_generic_subagent_work classified a pure chat turn as generic sub-agent
# work; the answer then returned out-of-band via the MissionAnnouncer and never
# reached the session transcript. Precision over recall: matched only by clear
# opinion/advice/decision phrasings, not by every question. DE/EN/ES, with
# umlaut + ASCII variants (STT emits either). Pure regex (AP-11 safe).
_OPINION_ADVICE_QUESTION_RE = re.compile(
    r"(?:"
    # advice / recommendation (DE)
    r"was\s+(?:w[üu]rdest|wuerdest|w[üu]rde|wuerde)\s+du\b"
    r"|was\s+(?:empfiehlst|r[äa]tst|raetst|schl[äa]gst|schlaegst)\s+du\b"
    r"|(?:hast|h[äa]ttest|haettest)\s+du\s+(?:einen?\s+)?(?:tipp|rat|empfehlung|vorschlag)"
    # opinion (DE)
    r"|was\s+(?:h[äa]ltst|haeltst|meinst|denkst|sagst)\s+du\b"
    r"|wie\s+(?:siehst|findest|beurteilst)\s+du\b"
    r"|(?:deiner|aus\s+deiner)\s+(?:meinung|sicht)\b"
    r"|was\s+ist\s+deine\s+(?:meinung|empfehlung|einsch[äa]tzung|einschaetzung)"
    # decision help (DE)
    r"|soll(?:te)?\s+ich\b[^?]*\boder\b"
    r"|was\s+(?:ist|w[äa]re|waere)\s+(?:besser|kl[üu]ger|klueger|sinnvoller)\b"
    # conversational question opener (DE). Adjectives/intensifiers between the
    # article and "Frage" must not blind the guard: "ich hab mal eine GANZ
    # GENERELLE Frage, wie viel Geld hat Elon Musk?" slipped past the rigid
    # "eine frage" form and force-spawned a worker for a one-search knowledge
    # question (live bug 2026-07-16, voice session 11:49).
    r"|ich\s+(?:hab|habe|h[äa]tte|haette)\s+(?:da\s+)?(?:mal\s+)?(?:noch\s+)?(?:'?ne|eine)\s+(?:[\w-]+\s+){0,3}?frage"
    r"|kann\s+ich\s+dich\s+(?:mal\s+)?(?:was|etwas)\s+fragen"
    # advice / opinion (EN)
    r"|what\s+(?:would|do)\s+you\s+(?:recommend|suggest|advise|think)\b"
    r"|what\s+should\s+i\b"
    r"|should\s+i\b[^?]*\bor\b"
    r"|(?:what(?:'s|\s+is)\s+)?your\s+(?:opinion|advice|take|recommendation)\b"
    r"|do\s+you\s+think\b"
    r"|i\s+(?:have|'ve\s+got|got)\s+a\s+(?:[\w-]+\s+){0,3}?question\b"
    r"|can\s+i\s+ask\s+you\b"
    # advice / opinion (ES)
    r"|qu[ée]\s+(?:me\s+)?(?:recomiendas|aconsejas|sugieres)\b"
    r"|qu[ée]\s+(?:opinas|piensas|crees)\b"
    r"|tengo\s+una\s+(?:[\w-]+\s+){0,3}?pregunta\b"
    r"|deber[íi]a\s+"
    r")",
    re.IGNORECASE,
)


def _is_opinion_advice_question(user_text: str) -> bool:
    """True for opinion / advice / recommendation / decision questions (and
    casual question-openers) that must be answered inline, never force-spawned.

    See ``_OPINION_ADVICE_QUESTION_RE`` for the full rationale (live bug
    2026-06-19): a conversational turn must not be dispatched to a worker just
    because an everyday word collides with an action verb.
    """
    return bool(_OPINION_ADVICE_QUESTION_RE.search(user_text or ""))


def _conversational_turn_suppresses_read_mandate(user_text: str) -> bool:
    """True when an opinion/advice/conversational turn must stand the READ
    evidence gate down instead of forcing a tool.

    Live 2026-06-30 (Bora-Bora voice session): the user asked a plain travel
    question — "...bin jetzt bei meinem Budget bei so 25.000 Euro ... passt es?".
    The word "budget" matched the cloud-billing domain, the gate FORCED
    ``cli_gcloud``, the model answered the travel question without that
    (irrelevant) tool, and the honesty backstop then VOIDED the good answer
    (``executed=[]``). The very same classifier that already inlines such a turn
    (force-spawn skip, log "opinion/advice/conversational question — inline")
    suppresses the read mandate here, so a chat/advice turn is never dead-ended
    by an irrelevant tool it never needed. The tool stays in the surface, so the
    model keeps discretion to call it — it is just never *forced*, and the answer
    is never voided.

    Narrow on purpose (no confab regression): fires ONLY on an actual
    opinion/advice/conversational opener. A bare data lookup ("Was sind meine
    Abrechnungen?", live 2026-06-17) matches no opener and stays gated. Pure
    regex (AP-11). WRITE mandates (``resolve_save_mandate``) are intentional and
    handled separately — only the READ gate stands down here.
    """
    return _is_opinion_advice_question(user_text)


# A spawn / sub-agent / worker token in DE/EN/ES (declined forms included). Used
# by both the decline guard below and nowhere else — kept local on purpose.
_SPAWN_TOKEN = (
    r"(?:sub-?agent\w*|subagent\w*|subagente\w*|worker\w*|trabajador\w*|"
    r"spawn\w*|delegier\w*|delegate\w*|delega\w*)"
)

# Explicit spawn DECLINE: the user literally says "don't spawn a subagent" /
# "no sub-agent" / "talk to me directly". The explicit heavy-work trigger hoist
# in ``_should_force_spawn`` is NEGATION-BLIND — it substring-matches the
# trigger word ("Subagent"/"spawn") and force-spawns, doing the exact OPPOSITE
# of what the user asked. A decline must therefore HARD-stand-down BEFORE that
# hoist. Live bug 2026-06-19 (voice session 18:41, Turn 2): "Nee, ich möchte,
# dass du keinen Subagent dafür spawnst. Ich möchte, dass du direkt mit mir
# sprichst." force-spawned (trigger match='Subagent'). Recall over precision: a
# missed decline re-spawns against an explicit "no" (the user-hostile bug);
# a rare over-match only hands the choice back to the brain, which still sees
# spawn_worker and can spawn if it judges so. Pure regex (AP-11), DE/EN/ES,
# umlaut + ASCII variants. Char-window (not word-count) so commas between the
# negation and the token ("nicht, dass du das spawnst") still match.
_SPAWN_DECLINE_RE = re.compile(
    r"(?:"
    # negated spawn / subagent / worker (DE): kein* / nicht / ohne / niemals
    r"\bkein(?:e|en|er|es|s)?\b[^.?!]{0,20}" + _SPAWN_TOKEN
    + r"|\b(?:nicht|ohne|niemals)\b[^.?!]{0,20}" + _SPAWN_TOKEN
    # talk-to-me-directly (DE)
    + r"|\bdirekt\s+mit\s+mir\b"
    + r"|\b(?:sprich|red|rede|antwort|antworte|sag)\w*\b[^.?!]{0,15}\bdirekt\b"
    # negated spawn / subagent / worker (EN)
    + r"|\b(?:no|without|don'?t|do\s+not|dont|never|not)\b[^.?!]{0,22}" + _SPAWN_TOKEN
    # talk-to-me-directly (EN). NB: a bare "just talk/tell me" arm was
    # deliberately removed (review MAJOR-1) — without a directness/spawn token
    # it false-matched a compound command ("Just tell me, spawn a subagent to
    # analyse the logs"), swallowing a genuine spawn request. The directness
    # intent is already carried by the \bdirectly\b / \bdirekt mit mir\b arms.
    + r"|\b(?:talk|answer|respond|speak)\b[^.?!]{0,12}\bdirectly\b"
    # negated spawn / subagent + talk-directly (ES)
    + r"|\bno\b[^.?!]{0,22}" + _SPAWN_TOKEN
    + r"|\bh[áa]bla(?:me)?\b[^.?!]{0,15}\bdirectamente\b"
    + r")",
    re.IGNORECASE,
)


# A leading "No," answers the ASSISTANT'S last proposal; it does not negate the
# vehicle named after it. English collapses two German words into one — "kein"
# (negates the noun) and "nein" (contradicts the previous statement) are both
# "no" — and ``_SPAWN_DECLINE_RE``'s char-window arm reads either as the first.
# Live bug 2026-08-24 (voice session 10:24, Turn 4): Jarvis offered to do the
# job inline, the user corrected him with "No, no, a worker should do it." and
# the gate scored that explicit delegation ORDER as a decline — the exact
# opposite — so the third spawn request in a row was refused. The German arms
# were never affected because they key on "kein/nicht/ohne/niemals", never on
# "nein". Stripped only when the particle is punctuated off ("No, …"), which is
# what makes it a reply rather than a determiner: "No subagent please" has no
# comma, keeps its window, and still declines. Any real negation that follows
# ("No, do not spawn …", "No, no subagent!") matches on its own merits after
# the strip. Pure regex (AP-11).
_CONTRADICTION_LEAD_RE = re.compile(
    r"^(?:\s*(?:no|nope|nah|nein|nee|noe)\s*[,;:]+)+\s*",  # i18n-allow: spoken input
    re.IGNORECASE,
)


def _is_spawn_decline(user_text: str) -> bool:
    """True when the user explicitly declines a worker spawn — "don't spawn a
    subagent", "no sub-agent", "talk to me directly". Must override the
    negation-blind explicit-trigger hoist in ``_should_force_spawn``.

    See ``_SPAWN_DECLINE_RE`` for the full rationale (live bug 2026-06-19,
    Turn 2): an explicit decline that NAMES the vehicle ("Subagent"/"spawn")
    must never be read as a spawn request. A leading contradiction particle is
    dropped first — see ``_CONTRADICTION_LEAD_RE`` (live bug 2026-08-24).
    """
    return bool(
        _SPAWN_DECLINE_RE.search(_CONTRADICTION_LEAD_RE.sub("", user_text or ""))
    )


# The user NAMING the auto-spawn *feature* — talking about it, complaining about
# it, asking to fix it — as opposed to COMMANDING a spawn. "Auto-Spawn" /
# "automatic spawn(ing)" is a feature NAME, never a vehicle imperative: nobody
# dispatches a worker by saying "auto-spawn". The negation-blind vehicle hoist in
# ``_should_force_spawn`` would otherwise substring-match the "spawn" inside
# "auto-spawn" (the hyphen is a \b word boundary) and force-spawn the very thing
# the user is complaining about. Anchored on the "auto"/"automatic" qualifier so
# a bare imperative ("Spawne einen Subagenten …") is untouched — the 2026-06-15
# mandate ("when I say subagent it MUST spawn") stays intact.
_SPAWN_FEATURE_RE = re.compile(
    r"\bauto[-\s]?spawn\w*"                  # auto-spawn / autospawn / auto spawn(ing)
    r"|\bautomatic(?:ally)?[\s-]+spawn\w*"   # automatic spawn / automatically spawning
    r"|\bautomatisch\w*[\s-]+spawn\w*",      # automatisches spawnen
    re.IGNORECASE,
)


def _is_spawn_feature_reference(user_text: str) -> bool:
    """True when the user names the auto-spawn *feature* (talks about / complains
    about / asks to fix it) instead of commanding a worker spawn.

    Must override the negation-blind explicit-trigger hoist in
    ``_should_force_spawn`` — mirroring ``_is_spawn_decline`` — because that hoist
    substring-matches the "spawn" inside "Auto-Spawn" and would force-spawn the
    very feature the user is complaining about. Live bug 2026-07-01 (voice session
    21:26:44): "Auto-Spawn, das müssen wir erstmal fixen" spawned a full Opus
    mission whose "still on it" heartbeats then spoke out of nowhere for minutes.
    Anchored on "auto"/"automatic" so a bare imperative that NAMES the vehicle
    ("Spawne einen Subagenten …") is not matched and still force-spawns.
    """
    return bool(_SPAWN_FEATURE_RE.search(user_text or ""))


def _prompt_sent_line(terminal: str, files: list[str], lang: str) -> str:
    """Spoken confirmation that an Agentic-IDE terminal received the prompt.

    Deliberately short and pane-named: in a four-pane workspace the only thing
    the user needs to hear is WHICH agent got it. Naming the attached file when
    there is exactly one is worth the extra second — it is also the fastest way
    for the user to catch a wrong file before the agent acts on it.
    """

    if len(files) == 1:
        return action_phrase(
            "ide_prompt_sent_one_file", lang, terminal=terminal, file=files[0]
        )
    if files:
        return action_phrase(
            "ide_prompt_sent_files", lang, terminal=terminal, count=len(files)
        )
    return action_phrase("ide_prompt_sent", lang, terminal=terminal)


def _terminal_not_running_line(terminal: str, status: str, lang: str) -> str:
    """Honest readback when the addressed pane is not accepting input."""

    return action_phrase(
        "ide_terminal_not_running", lang, terminal=terminal, status=status
    )


def _join_names(names: Sequence[str], lang: str) -> str:
    """Call-signs as a speakable list ("Iris und Bruno", "Iris, Bruno and Casey")."""

    items = [n for n in names if n]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return action_phrase(
        "ide_names_pair", lang, head=", ".join(items[:-1]), last=items[-1]
    )


def _fanout_reply_line(result: Any, lang: str) -> str:
    """Spoken readback for a fan-out, naming who got it and who did not.

    The live 2026-07-26 lie came from a readback that could only describe
    success: one pane was briefed, the sentence named one pane, and the realtime
    provider filled the gap from the user's own question ("Iris and Bruno").
    Every branch here therefore names the panes it is talking about, and the
    partial case is its own sentence rather than an optional clause — an
    optional clause is what gets dropped when a model paraphrases.

    A single addressee keeps the exact wording the one-pane path always had:
    that is the common case, and it should not start sounding like a fleet
    operation because the plumbing underneath grew one.
    """

    deliveries = result.deliveries
    ok = [d.terminal for d in result.delivered]
    bad = [d.terminal for d in result.undelivered]

    if len(deliveries) == 1:
        only = deliveries[0]
        if only.delivered:
            line = _prompt_sent_line(only.terminal, list(only.files), lang)
        elif only.reason_code == "not_running":
            line = _terminal_not_running_line(only.terminal, only.status, lang)
        else:
            line = action_phrase(
                "ide_prompt_sent_nobody", lang, failed=only.terminal
            )
    elif not ok:
        line = action_phrase(
            "ide_prompt_sent_nobody", lang, failed=_join_names(bad, lang)
        )
    elif bad:
        line = action_phrase(
            "ide_prompt_sent_partial",
            lang,
            names=_join_names(ok, lang),
            failed=_join_names(bad, lang),
        )
    else:
        line = action_phrase(
            "ide_prompt_sent_many", lang, names=_join_names(ok, lang)
        )

    stuck = [d.terminal for d in result.typed_but_not_started]
    if stuck:
        line = f"{line} " + action_phrase(
            "ide_prompt_typed_not_started", lang, names=_join_names(stuck, lang)
        )
    return line


def _recent_agent(recent: Any) -> str:
    """The coding agent a remembered workspace mostly ran, defaulting to Claude.

    Reopening a project the user last worked in with Codex should not silently
    switch them to a different agent. ``agents`` is a name -> pane-count map, so
    the majority answer is the one that matches what they saw last time.
    """
    counts = getattr(recent, "agents", None) or {}
    if not counts:
        return "claude"
    return max(counts.items(), key=lambda kv: kv[1])[0]


@dataclass(slots=True)
class _PendingCliChoice:
    """A "did you mean Claude Code or Codex?" waiting for its answer.

    Kept on the manager rather than inside the detector for the same reason the
    pane-name question is: the detector answers "is this clear?", and only the
    turn loop knows what to do about it and when the answer arrives.

    The whole fleet is held, not just the unclear part. "Two Klaudi terminals
    and one Codex" is ONE request, and opening the Codex pane while asking about
    the other two would leave the user answering a question about a workspace
    that had already changed under them.
    """

    groups: tuple[Any, ...]
    """The parsed fleet. Every group with no CLI takes the answered one."""

    utterance: str
    candidates: tuple[str, ...]
    """CLI display names offered, best first. The answer names one of these."""

    asked_at: float
    """``time.monotonic()`` — the window is short on purpose (see TTL)."""


#: How long the CLI question stays answerable.
#:
#: Two minutes, the same bound as the pane-name question and the delegation
#: offer: long enough for "uh… Codex", short enough that a forgotten question
#: cannot open panes in the middle of an unrelated turn later on.
_CLI_QUESTION_TTL_S = 120.0

#: A short reply is an ANSWER; a sentence is the user moving on.
_CLI_ANSWER_MAX_WORDS = 6


def _available_terminal_kinds() -> str:
    """The coding CLIs this workspace can open, as a spoken list.

    Read from the registry rather than written out here: a list kept in a
    sentence drifts from the one the workspace actually has, and the whole
    reason this sentence exists is to tell the user something true when they
    named a CLI that is not on it.
    """
    try:
        from dodaios.workspace import agents as workspace_agents

        names = [agent.display_name for agent in workspace_agents.coding_agents()]
    except Exception:  # noqa: BLE001 - a phrase must never break a turn
        return ""
    return ", ".join(names)


def _terminals_spawned_line(
    names: list[str], *, requested: int, folder: str | None, lang: str
) -> str:
    """Spoken confirmation for "open N more terminals".

    Always names the new panes: they are how the user addresses them in the very
    next sentence ("Zara, mach mal ..."), and hearing three names after asking
    for five is the fastest possible way to notice the workspace was full.

    The names are joined with commas rather than a localized "and" — a list
    separator needs no translation, and a per-language conjunction would be one
    more thing to get wrong in a fourth locale.
    """

    listed = ", ".join(names)
    if folder is not None:
        # A workspace had to be opened first; naming the folder is what makes the
        # assumption auditable.
        return action_phrase(
            "ide_terminals_opened_workspace", lang, folder=folder, names=listed
        )
    if len(names) < requested:
        return action_phrase(
            "ide_terminals_spawned_capped", lang, count=len(names), names=listed
        )
    if len(names) == 1:
        return action_phrase("ide_terminals_spawned_one", lang, names=listed)
    return action_phrase(
        "ide_terminals_spawned", lang, count=len(names), names=listed
    )


# Conversational coaching: "help me [get better at a soft / cognitive /
# conversational skill]" — asking, thinking, phrasing, deciding, understanding,
# expressing, communicating. This is CONVERSATION (Jarvis answers inline and
# asks the user smart questions), never a heavy-worker spawn. It trips the
# action-verb catalogue when the coaching OBJECT is itself a verb ("intelligent
# zu fragen" -> "frag"/"frage"). Live bug 2026-06-19 (voice session 18:41,
# Turn 1): "Hilf mir aber dabei, intelligent zu fragen. Für mich ist Fragen
# einer der Schlüssel für Erfolg, verstehst du?" -> matched action verbs
# ['frag','frage'] -> has_action_intent -> _is_generic_subagent_work ->
# force-spawn. High precision: a help/teach framing AND a cognitive/
# conversational object verb must BOTH be present, so "Hilf mir, eine E-Mail zu
# schreiben und zu senden" (concrete artifact) does NOT match and stays
# spawnable. Pure regex (AP-11), DE/EN/ES, umlaut + ASCII variants (the runtime
# output-language doctrine mandates all three locales; the sibling guards cover
# es too).
_CONVERSATIONAL_COACHING_RE = re.compile(
    r"(?:"
    # DE: help / teach / show-me-how framing ...
    r"\b(?:hilf|hilfst|helfen|helf|bring\s+mir\s+bei|beibring\w*|lehr\w*|"
    r"zeig\s+mir,?\s+wie)\b"
    r"[^.?!]{0,50}"
    # ... + a cognitive / conversational skill object
    r"\b(?:frag\w*|denk\w*|nachdenk\w*|formulier\w*|verstehen|verstehe|"
    r"entscheid\w*|reflektier\w*|aus(?:zu)?dr[üu]ck\w*|kommunizier\w*|"
    r"argumentier\w*|[üu]berleg\w*|zuh[öo]r\w*|reden|sprechen)\b"
    # EN: help / teach / show me ... + a cognitive skill object
    r"|\b(?:help|teach|show)\s+me\b[^.?!]{0,50}"
    r"\b(?:ask|think|phrase|formulate|understand|decide|reflect|communicate|"
    r"express|reason|articulate|listen|converse)\b"
    # ES: ayúdame / enséñame / muéstrame cómo ... + a cognitive skill object
    r"|\b(?:ay[úu]dame|ens[eé][ñn]ame|mu[ée]strame\s+c[óo]mo)\b[^.?!]{0,50}"
    r"\b(?:pregunt\w*|pensar|formular|decidir|comunicar|reflexionar|"
    r"expresar|razonar|escuchar|hablar|conversar)\b"
    r")",
    re.IGNORECASE,
)


def _is_conversational_coaching(user_text: str) -> bool:
    """True when the user asks for help getting better at a soft / cognitive /
    conversational skill (asking, thinking, phrasing, deciding, understanding).
    Answered inline, never force-spawned.

    See ``_CONVERSATIONAL_COACHING_RE`` for the full rationale (live bug
    2026-06-19, Turn 1): a coaching request must not be dispatched to a worker
    just because its skill object collides with an action verb ("fragen").
    """
    return bool(_CONVERSATIONAL_COACHING_RE.search(user_text or ""))


def _extract_leaked_spawn_call(text: str) -> dict[str, Any] | None:
    """Return the ``input`` dict of a leaked ``spawn_worker`` tool_use, else None.

    Some providers (notably Gemini) intermittently emit a ``tool_use`` block as
    the response *text* instead of invoking the tool — the brain reply becomes
    raw ``[{"type":"tool_use","name":"spawn_worker","input":{...}}]`` JSON,
    which would otherwise be spoken (scrubbed to "Es trat ein Fehler auf") and
    the delegated Jarvis-Agent would never run. This accepts only a whole JSON
    response (bare or strictly fenced); JSON quoted inside prose is never an
    executable instruction.
    """
    for call in extract_leaked_tool_calls(text):
        if call.get("name") == "spawn_worker":
            return dict(call.get("input") or {})
    return None


def _may_be_tool_use_leak(text: str) -> bool:
    """Cheap shape test: could ``text`` still turn out to be a leaked tool_use?

    Structured JSON at the very start (optionally inside a ```json fence) is the
    only cue available while a stream is still growing. It is a SUSPICION, never
    a verdict — a perfectly good answer may open with a markdown link
    (``[Doku](…)``) or a JSON example. Use it only to WITHHOLD a chunk until the
    buffer is complete; :func:`_looks_like_tool_use_leak` then decides for real.
    """
    if not text:
        return False
    s = text.lstrip()
    if s.startswith("```"):
        s = s.lstrip("`")
        if s[:4].lower() == "json":
            s = s[4:]
        s = s.lstrip()
    return s.startswith("[") or s.startswith("{")


def _is_whole_structured_document(text: str) -> bool:
    """True when ``text`` is ONE structured document and nothing else.

    ``[Doku](https://…) beschreibt das genau.`` opens with ``[`` but carries
    prose after the bracket — that is speech. ``{"exit_code": 0, …}`` and its
    Python-repr twin ``{'exit_code': 0, …}`` are blobs with no prose at all and
    must never reach TTS. Parsing decides; the first character does not.
    """
    s = text.strip()
    if s.startswith("```") and s.endswith("```") and len(s) > 6:
        s = s[3:-3].strip()
        if s[:4].lower() == "json":
            s = s[4:].strip()
    if not (s.startswith("[") or s.startswith("{")):
        return False
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        pass  # not JSON — the Python-repr shape is tried next
    # A Python repr is not JSON but is just as unspeakable. Literals only —
    # ``literal_eval`` never executes anything. Bounded so a long prose answer
    # that merely opens with a bracket cannot cost real parse time.
    if len(s) > 20_000:
        return False
    try:
        ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return False  # not a Python literal either — this is prose, not a blob
    return True


def _looks_like_tool_use_leak(text: str) -> bool:
    """True if ``text`` IS a provider's tool_use block emitted as TEXT.

    The authoritative verdict, for a COMPLETE buffer. The old test — "the text
    starts with ``[`` or ``{``" — was a suspicion promoted to a verdict: an
    answer opening with a markdown link or a JSON example was classed as a leak
    and, on the streaming path, silently dropped in full. So the shape test only
    gates the real check now: either the strict recovery parser finds an actual
    tool call, or the whole text is a structured document with no prose in it.
    """
    if not _may_be_tool_use_leak(text):
        return False
    if extract_leaked_tool_calls(text):
        return True
    return _is_whole_structured_document(text)


_CLI_TOOL_PREFIX = "cli_"
# Lines a CLI prints when it wants interactive confirmation — never spoken.
_CLI_PROMPT_NOISE_RE = re.compile(
    r"\(y/n\)|\[y/n\]|would you like to|do you want to continue|press any key",
    re.IGNORECASE,
)


def _extract_cli_error_line(stderr: str) -> str:
    """Pick the most informative, speakable line out of a CLI's stderr.

    Prefers an ``ERROR:``-prefixed line (the actionable cause), strips the
    ``ERROR: (gcloud.x.y)`` command-path prefix, and skips interactive-prompt
    noise such as ``Would you like to enable and retry (y/N)?``. Returns ``""``
    when nothing speakable remains. Pure string work — no LLM (AP-11).
    """
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    speakable = [ln for ln in lines if not _CLI_PROMPT_NOISE_RE.search(ln)]
    error_lines = [ln for ln in speakable if ln.upper().startswith("ERROR")]
    chosen = (error_lines or speakable or [""])[0]
    # Drop a leading "ERROR: (gcloud.billing.budgets.list) " command-path prefix.
    chosen = re.sub(r"^ERROR:\s*(\([^)]*\)\s*)?", "", chosen, flags=re.IGNORECASE)
    return chosen.strip()[:200]


# Spoken CLI-failure readbacks; placeholders {cause} / {code}.
_CLI_FAILURE_PHRASES: dict[str, dict[str, str]] = i18n_catalog.locale_maps("brain.cli_failure")

# Spoken reply when a recovered tool ran but produced nothing speakable.
_NOTHING_FOUND_PHRASE: dict[str, str] = i18n_catalog.table("brain.nothing_found")

# Navigation fast-path acknowledgement; placeholder {label}.
_NAVIGATION_ACK: dict[str, str] = i18n_catalog.table("brain.navigation_ack")


def _cli_failure_reason(output: Any, error: str | None, *, language: str) -> str:
    """Honest spoken readback for a FAILED ``cli_<name>`` call.

    The user must never hear a bare ``exit 1`` (the CLI tool's ``error`` field)
    nor "Dazu habe ich nichts gefunden". Surface the stderr cause if present,
    else name the exit code. Static, no LLM (AP-11); mirrors
    :func:`dodaios.voice.action_phrases.cu_failure_readback` (live repro
    2026-06-17, ``gcloud billing budgets list`` → exit 1 narrated as "nothing
    found").
    """
    stderr = ""
    exit_code: int | None = None
    if isinstance(output, dict):
        stderr = str(output.get("stderr") or "")
        ec = output.get("exit_code")
        if isinstance(ec, int):
            exit_code = ec
    phrases = _CLI_FAILURE_PHRASES.get(language, _CLI_FAILURE_PHRASES["en"])
    cause = _extract_cli_error_line(stderr)
    if cause:
        return phrases["cause"].format(cause=cause)
    if exit_code is None and error:
        m = re.search(r"exit\s+(-?\d+)", error)
        if m:
            exit_code = int(m.group(1))
    if exit_code is not None:
        return phrases["code"].format(code=exit_code)
    return phrases["bare"]


def _evidence_answer_is_unverified(
    required_tool: str, executed: set[str], response_text: str, *, suppressed: bool
) -> bool:
    """True when a mandated-tool turn produced an answer WITHOUT calling the tool.

    The evidence gate's ``require_tool`` directive tells the model to answer ONLY
    from the tool's result. If the model returns a non-empty answer but the
    mandated tool never ran (``executed_tool_names``), that answer is necessarily
    unverified — at worst a confabulation (live repro 2026-06-17, session
    296abc82: the model invented "the gcloud tool blocked execution because it
    classified the request as an explanatory question"). Empty answers and
    fire-and-forget ``suppress_response`` turns are handled elsewhere, so they
    are excluded here.
    """
    if not required_tool or suppressed:
        return False
    if required_tool in (executed or set()):
        return False
    return bool((response_text or "").strip())


# A concrete particular — something the answer could only have if it had the
# data in front of it: a clock time, a calendar date, any figure, a named
# weekday or month, an address or link, a list of items, or a bare statement
# that there are none. Explanations and general knowledge carry none of these.
# Deliberately broad on the "specific" side: over-detecting costs one honest
# fallback, under-detecting speaks a confabulation.
_CONCRETE_DATUM_RE = re.compile(
    r"\d"                                    # any figure at all
    r"|\bhttps?://|\bwww\.|@[\w.-]+\.\w{2,}"  # a link or an address
    r"|^\s*[-*•]\s+.+$"                      # a bullet item
    r"|\b(?:"
    # Named days and months. DE / EN / ES — the answer surface is localized.
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|"  # i18n-allow
    r"sonntag|"  # i18n-allow
    r"januar|februar|m[äa]rz|dezember|oktober|"  # i18n-allow: DE months that differ from EN
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|"
    r"lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo|"
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|"
    r"octubre|noviembre|diciembre"
    r")\b"
    # "you have none" is as much a claim about the data as naming an item. The
    # subject is required — a bare "kein"/"no" belongs to ordinary prose
    # ("not by a spark plug") and must not count.
    r"|\b(?:du\s+hast|es\s+(?:gibt|sind|ist))(?:\s+\w+){0,3}\s+"  # i18n-allow: DE existence claim
    r"(?:keine?|nichts)\b"  # i18n-allow: DE existence claim
    r"|\b(?:you\s+have|there\s+(?:is|are))(?:\s+\w+){0,3}\s+"
    r"(?:no|none|nothing)\b"
    r"|\b(?:tienes|hay)(?:\s+\w+){0,3}\s+(?:ning[úu]n\w*|nada)\b",
    re.IGNORECASE | re.MULTILINE,
)

# The answer attributes the fact to what was already said in this conversation.
# Repeating something the user themselves stated is not a fabrication, and no
# tool could have grounded it — the honest fallback would be the wrong answer.
_CONVERSATION_ATTRIBUTION_RE = re.compile(
    r"\b(?:"
    r"du\s+hattest\s+\w*\s?gesagt|du\s+sagtest|hattest\s+du\s+gesagt|"  # i18n-allow
    r"wie\s+(?:du\s+)?(?:gesagt|erw[äa]hnt|besprochen)|"  # i18n-allow: DE history reference
    r"vorhin\s+(?:gesagt|erw[äa]hnt)|laut\s+deiner\s+angabe|"  # i18n-allow: DE history reference
    r"you\s+(?:said|told\s+me|mentioned)|as\s+you\s+(?:said|mentioned)|"
    r"earlier\s+you\s+(?:said|mentioned)|from\s+what\s+you\s+told\s+me|"
    r"(?:me\s+)?dijiste|seg[úu]n\s+me\s+dijiste|como\s+mencionaste"
    r")\b",
    re.IGNORECASE,
)


# A claim about the mandated tool ITSELF — that it ran, refused, failed, or
# returned something. The 2026-06-17 confabulation was exactly this shape ("the
# gcloud tool blocked execution because it classified the request as an
# explanatory question"): no figure, no date, and entirely invented. Nothing the
# user said can excuse it, so it is never exempted by attribution.
_TOOL_NOUN_RE = re.compile(
    r"\b(?:tool|werkzeug|befehl|kommando|cli|api|abfrage|query|command|"  # i18n-allow: DE tool noun
    r"skript|script|herramienta|comando|consulta)\w*",
    re.IGNORECASE,
)
_EXECUTION_VERB_RE = re.compile(
    r"\b(?:blockier\w*|verweiger\w*|abgelehnt|fehlgeschlagen|"  # i18n-allow: DE execution verb
    r"zur[üu]ckgegeben|ausgef[üu]hrt|gelaufen|geliefert|aufgerufen|"  # i18n-allow
    r"gestartet|"  # i18n-allow
    r"block\w*|refus\w*|denied|deny|return\w*|fail\w*|ran|run|executed|"
    r"invoked|called|"
    r"bloque\w*|rechaz\w*|devolv\w*|fall\w*|ejecut\w*|llam\w*)\b",
    re.IGNORECASE,
)


def _answer_claims_tool_behaviour(response_text: str) -> bool:
    """True when the answer says what the mandated tool did — it did nothing."""
    text = response_text or ""
    return bool(_TOOL_NOUN_RE.search(text) and _EXECUTION_VERB_RE.search(text))


def _answer_claims_unverified_data(response_text: str) -> bool:
    """True when the answer reports a PARTICULAR the mandated tool never supplied.

    The evidence backstop used to replace *every* answer of a turn whose
    mandated tool did not run. That deleted correct answers: the model explains
    how something works, or repeats what the user said two turns ago, and the
    user hears "Ich konnte das gerade nicht abrufen" instead — the guard
    fabricating a failure to prevent a fabrication.

    So the backstop now needs an actual claim, of one of two kinds: a statement
    about what the mandated tool did (:func:`_answer_claims_tool_behaviour`), or
    a concrete particular (:data:`_CONCRETE_DATUM_RE`) that is not attributed to
    the conversation itself. An answer made of explanation alone claims nothing
    and stays.

    Pure regex, no LLM (AP-11). This judges DATA claims only — a false *action*
    claim ("I checked your calendar") carries no particular and is caught by
    :func:`replace_unbacked_action_claim` right after this guard.
    """
    text = (response_text or "").strip()
    if not text:
        return False
    if _answer_claims_tool_behaviour(text):
        return True
    if not _CONCRETE_DATUM_RE.search(text):
        return False
    return not _CONVERSATION_ATTRIBUTION_RE.search(text)


_EVIDENCE_UNFULFILLED_PHRASES: dict[str, str] = i18n_catalog.table("brain.evidence_unfulfilled")


# Spoken domain labels for the honest "couldn't reach X" fallback. Mirrors the
# capability vocabulary already used by evidence_gate's refusal tables, so a
# mandated-but-unrun READ names the real domain ("…deine Cloud-Abrechnung…")
# instead of the generic "the tool" — which also seeds the conversation history
# so a follow-up "welches Werkzeug?" is answerable. Localized for every
# supported language; an unknown domain falls back to the generic phrase.
_EVIDENCE_DOMAIN_LABELS: dict[str, dict[str, str]] = i18n_catalog.locale_maps(
    "brain.evidence_domain_labels"
)

# Domain-aware variant of the unfulfilled phrase — same honesty contract (never
# claims a "block"/invents a reason), just names the capability via {label}.
_EVIDENCE_UNFULFILLED_DOMAIN_PHRASES: dict[str, str] = i18n_catalog.table(
    "brain.evidence_unfulfilled_domain"
)


def _evidence_unfulfilled_answer(*, lang: str, domain: str = "") -> str:
    """Honest spoken fallback for a mandated-tool turn whose tool never ran.

    Static, no LLM (AP-11). Never claims the tool "blocked" or invents a reason.
    When ``domain`` is a known external-data domain the phrase NAMES the
    capability ("…deine Cloud-Abrechnung…"); otherwise it degrades to the generic
    wording. Localized for every supported language (de/en/es/pt); an unrecognised
    code degrades to the default locale so the spoken turn never crashes (Runtime
    Output Language doctrine).
    """
    if lang not in _EVIDENCE_UNFULFILLED_PHRASES:
        lang = DEFAULT_LOCALE
    label = _EVIDENCE_DOMAIN_LABELS.get(lang, {}).get(domain, "")
    if label:
        return _EVIDENCE_UNFULFILLED_DOMAIN_PHRASES[lang].format(label=label)
    return _EVIDENCE_UNFULFILLED_PHRASES[lang]


# Honest spoken fallback for a mandated WRITE (e.g. contact-upsert) that never
# ran — the say-do gap (live voice session 2026-06-30: "Okay, sehr gut" spoken
# while no contact was saved). Distinct from the READ fallback above: it speaks
# to a write ("not saved yet"), not a failed lookup. Static, no LLM (AP-11);
# localized for every supported language, unknown code → default locale.
_ACTION_UNFULFILLED_PHRASES: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "brain.action_unfulfilled"
)
# A write tool with no bespoke table reuses the contact wording's shape.
_ACTION_UNFULFILLED_DEFAULT = _ACTION_UNFULFILLED_PHRASES["contact-upsert"]


def _action_unfulfilled_answer(required_tool: str, *, lang: str) -> str:
    """Honest spoken fallback for a mandated WRITE tool that never ran.

    Mirrors :func:`_evidence_unfulfilled_answer` but for a write/create action:
    it must never claim the save happened. Unknown tool or language degrades to
    the contact wording / default locale so the spoken turn never crashes.
    """
    table = _ACTION_UNFULFILLED_PHRASES.get(required_tool, _ACTION_UNFULFILLED_DEFAULT)
    return i18n_catalog.pick(table, lang)


def _unfulfilled_replacement(
    *,
    required_tool: str,
    executed: set[str],
    response_text: str,
    suppressed: bool,
    is_write: bool,
    lang: str,
    domain: str = "",
) -> str | None:
    """Decide whether a mandated-tool turn's answer must be replaced for honesty.

    Returns the honest replacement text, or ``None`` to keep the answer as-is.
    Shared by the read evidence gate and the write (contact) say-do guard.

    A WRITE mandate additionally LEAVES A CLARIFYING QUESTION intact: asking the
    user to repeat a missing/broken field (e.g. the '@'-less email) is the
    desired behavior, not a fake claim — only a flat confirmation with no
    question is corrected.

    A READ mandate leaves an answer that CLAIMS NOTHING intact: an explanation,
    or a fact the user themselves supplied earlier, is not a confabulation and
    must not be traded for "I couldn't retrieve that" (see
    :func:`_answer_claims_unverified_data`).
    """
    if not _evidence_answer_is_unverified(
        required_tool, executed, response_text, suppressed=suppressed
    ):
        return None
    if is_write:
        if "?" in (response_text or ""):
            return None  # honest clarifying question — keep it
        return _action_unfulfilled_answer(required_tool, lang=lang)
    if not _answer_claims_unverified_data(response_text):
        return None  # nothing was claimed — nothing to correct
    return _evidence_unfulfilled_answer(lang=lang, domain=domain)


def _safe_recovered_text(value: Any) -> str:
    """Redact, cap, and reject tool-envelope text before it reaches speech."""
    text = safe_preview(value, max_chars=600)[:600].strip()
    return "" if _looks_like_tool_use_leak(text) else text


def _render_recovered_tool_output(output: Any) -> str:
    """Speakable plain-text rendering of a recovered tool's output.

    Why this exists (live repro 2026-06-14, voice "Was hältst du von exp.com?"):
    a *read* tool such as ``search_web`` returns STRUCTURED data
    (``{"query": …, "results": [{"title", "snippet", …}]}``), not a spoken
    sentence. A properly-invoked tool call re-injects that data for a follow-up
    brain turn that phrases it; the leaked-recovery shortcut
    (:meth:`BrainManager._recover_leaked_tool`) has no such turn, so it used to
    return ``str(result.output)`` — a ``{``-prefixed Python repr. The streaming
    guard :func:`_looks_like_tool_use_leak` then mistook that ANSWER for ANOTHER
    leaked tool_use block, dropped it, and the user heard the canned
    "Ich habe die Aktion erkannt, konnte sie aber nicht ausführen." even though
    the search had succeeded.

    This renders structured output to readable text that never begins with
    ``{``/``[``. An empty return means "nothing speakable" — the caller then
    supplies a localized 'nothing found' fallback (never a repr, never the
    failure phrase).
    """
    if output is None:
        return ""
    if isinstance(output, str):
        return _safe_recovered_text(output)
    if isinstance(output, dict):
        results = output.get("results")
        if isinstance(results, list):
            parts: list[str] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                title = _safe_recovered_text(item.get("title") or "")
                snippet = _safe_recovered_text(item.get("snippet") or "")
                if snippet and title and title.lower() not in snippet.lower():
                    parts.append(f"{title}: {snippet}")
                else:
                    parts.append(snippet or title)
            joined = " ".join(p for p in parts if p).strip()
            return _safe_recovered_text(joined)
        # CLI tools (cli_<name>) return {exit_code, stdout, stderr, duration_ms}.
        # This renderer is reached only after the caller verified success, so a
        # non-empty stdout IS the answer — surface it instead of dead-ending in
        # "" (which made the caller speak "Dazu habe ich nichts gefunden" even
        # though gcloud returned real project data; live repro 2026-06-17).
        if "exit_code" in output and ("stdout" in output or "stderr" in output):
            return _safe_recovered_text(output.get("stdout") or "")
        # Connected tools use many result schemas. Preserve a bounded set of
        # human-facing scalar fields while omitting technical identifiers,
        # raw bodies, URLs, tokens, and headers. The normal ToolUseLoop gives
        # structured results back to the model for synthesis; this branch is a
        # defense-in-depth fallback when a provider leaked the call as text.
        parts: list[str] = []
        for key in (
            "sender", "from", "subject", "title", "date", "time", "status",
            "summary", "description",
        ):
            val = output.get(key)
            if isinstance(val, str) and val.strip():
                rendered = _safe_recovered_text(val)
                if rendered:
                    parts.append(rendered)
            elif isinstance(val, (list, tuple)):
                rendered = _render_recovered_tool_output(val)
                if rendered:
                    parts.append(rendered)
        if parts:
            return _safe_recovered_text(" — ".join(parts))
        normalized_keys = {
            re.sub(r"[^a-z0-9]", "", str(key).lower()) for key in output
        }
        has_private_or_technical_key = any(
            key.endswith(("id", "token"))
            or any(
                marker in key
                for marker in (
                    "body", "secret", "authorization", "header", "raw",
                    "html", "attachment", "payload", "apikey",
                )
            )
            for key in normalized_keys
        )
        if not has_private_or_technical_key:
            # Preserve the established fallback contract for compact explicit
            # answer/status mappings. ``content`` remains excluded because
            # connector schemas routinely use it for full private bodies.
            for key in ("text", "answer", "message", "result"):
                val = output.get(key)
                if isinstance(val, str) and val.strip():
                    return _safe_recovered_text(val)
        # Fail closed for unknown mappings. Connector schemas commonly store
        # full private bodies under content/message/result and use camelCase
        # identifiers/tokens, so a generic scalar fallback can disclose data.
        return ""
    if isinstance(output, (list, tuple)):
        rendered_items = (
            _render_recovered_tool_output(item).strip() for item in output
        )
        joined = " ".join(item for item in rendered_items if item).strip()
        return _safe_recovered_text(joined)
    return _safe_recovered_text(output)


def _extract_leaked_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(tool_name, input_dict)`` of ANY leaked tool_use block, else None.

    Generalises :func:`_extract_leaked_spawn_call` (spawn-only) to EVERY router
    tool — ``cli_*``, ``open_app``, ``dispatch_to_harness``, ``screenshot`` …
    Gemini intermittently emits the ``tool_use`` block as response *text*
    instead of invoking it; in the streaming voice path that JSON would be
    spoken (scrubbed to silence) and the action would never run. This recovers
    the call so it can be executed deterministically (see
    :meth:`BrainManager._recover_leaked_tool`).
    """
    calls = extract_leaked_tool_calls(text)
    if calls:
        call = calls[0]
        return str(call["name"]), dict(call.get("input") or {})
    return None


# Single source of truth for the reply-language vocabulary (Python ↔ REST ↔ TS).
# "auto" = mirror the user's input language; the rest hard-pin that language.
SUPPORTED_REPLY_LANGUAGES: tuple[str, ...] = ("auto", *SUPPORTED_LOCALES)
# French speech can be pinned in configuration without adding a translated UI.
_REPLY_LANGS: frozenset[str] = frozenset((*SUPPORTED_REPLY_LANGUAGES, "fr"))
_REPLY_LANG_NAMES: dict[str, str] = {**SUPPORTED_LANGUAGE_NAMES, "fr": "French"}

# Spoken confirmation for a deterministic reply-language switch (the
# voice_command_gate "language_switch" path). Keyed by target code and phrased
# IN that language so — because set_reply_language() runs first — the TTS voice
# resolves to the new language and the switch is audible. "auto" has no single
# language, so it confirms in the conversation's phrase language
# (``brain.lang_switch_confirm_auto``; English for an unsupported one).
_LANG_SWITCH_CONFIRM: dict[str, str] = i18n_catalog.table("brain.lang_switch_confirm")

# Spoken when the live reply-language switch applied but PERSIST failed (read-only
# / locked jarvis.toml). Honest: scoped to this session, not "from now on", because
# it reverts on restart (audit 2026-06-27). de/en/es/pt.
_LANG_SWITCH_CONFIRM_SESSION: dict[str, str] = i18n_catalog.table(
    "brain.lang_switch_confirm_session"
)

# Sub-agent (Heavy-Task worker) provider switch — the voice_command_gate
# "subagent_switch" path. The gate returns the spoken provider word; this maps
# it to a CANONICAL [brain.sub_jarvis].provider slug (the values are the only
# accepted ones — this map IS the validation). Persisted via the 3-layer
# config_writer.set_sub_jarvis_provider so the drift-guard cannot revert it; the
# running worker re-resolves it per mission (_live_subagent_provider), so the
# switch applies to the NEXT mission without a restart.
_SUBAGENT_VOICE_TO_CANONICAL: dict[str, str] = {
    "openai": "openai", "gpt": "openai",
    "codex": "openai-codex", "chatgpt": "openai-codex", "openai-codex": "openai-codex",
    "claude": "claude-api", "anthropic": "claude-api",
    "gemini": "gemini",
    "openrouter": "openrouter",
    "litellm": "litellm",
    "grok": "grok",
    "nvidia": "nvidia", "nim": "nvidia", "nemotron": "nvidia",
    "antigravity": "antigravity",
    "grok-build": "grok-build",
    "grok build": "grok-build",
    "grokbuild": "grok-build",
    "grok-cli": "grok-build",
}
_SUBAGENT_DISPLAY: dict[str, str] = {
    "openai": "OpenAI", "openai-codex": "Codex", "claude-api": "Claude",
    "gemini": "Gemini", "openrouter": "OpenRouter", "litellm": "LiteLLM", "grok": "xAI Grok",
    "nvidia": "NVIDIA NIM",
    "antigravity": "Antigravity",
    "grok-build": "Grok Build",
}
_SUBAGENT_SWITCH_CONFIRM: dict[str, str] = i18n_catalog.table("brain.subagent_switch_confirm")
# Honest spoken failure phrases for a deterministic subagent switch that the
# validated apply_provider_switch refused (missing credential / unknown). Never
# a false "done"; always names what failed. de/en/es/pt (Runtime Output Language).
_SUBAGENT_SWITCH_FAIL: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "brain.subagent_switch_fail"
)


def _subagent_switch_failure_phrase(result: dict, display: str, lang: str) -> str:
    kind = str(result.get("error_kind") or "other")
    table = _SUBAGENT_SWITCH_FAIL.get(kind, _SUBAGENT_SWITCH_FAIL["other"])
    return i18n_catalog.pick(table, lang).format(p=display)


# Main-brain provider switch — the voice_command_gate "provider_switch" path.
# Mirrors the subagent tables: routed through the validated apply_provider_switch
# so the spoken readback is HONEST (audit 2026-06-27: the old path returned ""
# silently, even when the switch was refused). de/en/es/pt (Runtime Output Language).
_PROVIDER_SWITCH_CONFIRM: dict[str, str] = i18n_catalog.table("brain.provider_switch_confirm")
_PROVIDER_SWITCH_FAIL: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "brain.provider_switch_fail"
)


def _provider_switch_failure_phrase(result: dict, display: str, lang: str) -> str:
    kind = str(result.get("error_kind") or "other")
    table = _PROVIDER_SWITCH_FAIL.get(kind, _PROVIDER_SWITCH_FAIL["other"])
    return i18n_catalog.pick(table, lang).format(p=display)


# Background-task cancel — the voice_command_gate "cancel" path. Honest readback:
# names the count when something was stopped, says so plainly when nothing ran
# (audit 2026-06-27: the old path was silent either way). de/en/es/pt.
_CANCEL_CONFIRM: dict[str, str] = i18n_catalog.table("brain.cancel_confirm")
_CANCEL_NONE: dict[str, str] = i18n_catalog.table("brain.cancel_none")

# Thinking-depth override — the voice_command_gate "depth_deep"/"depth_fast"
# path. Confirms the new depth instead of staying silent (audit 2026-06-27).
_DEPTH_CONFIRM: dict[str, dict[str, str]] = i18n_catalog.nested_table("brain.depth_confirm")

# The one standing contract every substantive prompt carries: the honesty rule
# (said once in the whole prompt; the unbacked-claim backstop enforces it), the
# research-versus-action routing difference, and the self-control facts the
# model cannot know. Every attached tool already reaches the model as a full
# function definition, so the prompt carries no tool-name list. Static, so the
# cached system prefix stays byte-stable.
_CORE_CONTRACT = (
    "Never claim an action or result unless a tool call in this turn returned it; "
    "otherwise say it has not happened. A denied or failed call returned nothing: "
    "never supply its answer yourself; say what was blocked and why.\n"
    "Research and fresh facts (news, prices, weather): search_web, never cli_*; cli_* "
    "and plugin tools act on the user's own accounts; evergreen knowledge needs no tool. "
    "Work for one of your agents: delegate_to_agent; spawn_worker only for heavy "
    "background work the user asked for.\n"
    "Dodaios's own settings (wake phrase, voice, providers, language, restart) are yours "
    "to change: its command tools such as `brain-switch` or `wake-word-set`, "
    "`set_config_value` for a plain key, `cli_jarvisctl` as the fallback."
)

# Conversational style for typed (written) turns: the shared system prompt
# carries the voice persona's spoken-output rules, which must not govern an
# answer that is read on screen.
_WRITTEN_CHAT_STYLE = (
    "WRITTEN CHAT STYLE: this turn is typed and read on screen, so the SPOKEN OUTPUT "
    "rules do not apply; Markdown and digits are fine where they help. No emojis. The "
    "short line before your first tool call (below) is wanted here: write it and call the "
    "tool in the same step."
)

# The written-only rules, for a prompt that already carries the shared policy
# (a society agent's briefing has it under "How to reply to the person").
_WRITTEN_CHAT_RULES = _WRITTEN_CHAT_STYLE

# Keep the API chat and the main brain's written delivery equally conversational.
_WRITTEN_CHAT_STYLE += "\n" + CONVERSATIONAL_RESPONSE_STYLE
# The chat that shows a written answer draws its chart blocks (response_style.CHART_GUIDANCE).
_WRITTEN_CHAT_STYLE += "\n" + CHART_GUIDANCE
# ... and its web links as a logo and a short name (response_style.LINK_GUIDANCE).
_WRITTEN_CHAT_STYLE += "\n" + LINK_GUIDANCE

#: Upper bound for the legacy core-memory block in the system prompt.
_CORE_MEMORY_MAX_CHARS = 20_000


def _is_written_turn() -> bool:
    """True when the current turn is a typed (written) turn, not voice.

    Reads the per-turn override's tool context (``{"delivery": "written"}``,
    set by the agent-chat brain runner for every typed chat turn). Defensive:
    any missing piece means a voice-style turn, so the spoken-output rules
    keep applying.
    """
    try:
        override = _TURN_OVERRIDE.get()
    except Exception:  # noqa: BLE001 — no override context: voice-style turn
        return False
    if override is None:
        return False
    context = getattr(override, "tool_context", None)
    if not isinstance(context, dict):
        try:
            context = dict(context or {})
        except Exception:  # noqa: BLE001 — unexpected mapping shape
            return False
    return context.get("delivery") == "written"


def normalize_reply_language(value: object) -> str:
    """Coerce a raw reply-language value to a known code, else ``"auto"``.

    Accepts case-insensitive, whitespace-padded input. Unknown / empty / None
    fall back to ``"auto"`` (mirror the user's input language) so a typo in
    jarvis.toml never silently breaks the voice/chat path.
    """
    if not isinstance(value, str):
        return "auto"
    code = value.strip().lower()
    return code if code in _REPLY_LANGS else "auto"


# Spoken fallback when the ENTIRE provider chain fails (no key, depleted
# credits, all rate-limited). The detailed provider/billing diagnostic
# (``_format_provider_chain_error``) is developer-facing and must NEVER reach
# the voice path — a concierge does not read "Account-Problem bei grok …
# console.x.ai/team/billing" aloud (live complaint 2026-06-01). Instead we
# speak a short, provider-agnostic apology in the user's SELECTED reply
# language (de/en/es/pt; "auto" → German, the default locale). Three variants
# per language so repeated failures in one session don't sound robotic
# (mirrors the ACK-variant approach). The full diagnostic stays in the logs.
_PROVIDER_DOWN_PHRASES: dict[str, tuple[str, ...]] = i18n_catalog.variant_table(
    "brain.provider_down"
)


# Cause-aware variants of the total-failure apology (maintainer directive
# 2026-07-21: "when such an error happens, SAY what it was about"). One
# spoken sentence per root-cause CATEGORY — still voice-safe (no provider
# names, no URLs, no billing pages; ADR-0010) but honest about WHY, with the
# in-app recovery step. Keys mirror the ``kind`` values classified by the
# provider chain (``_format_provider_chain_error``); an unknown/unlisted kind
# falls back to the generic rotation above.
_PROVIDER_DOWN_CAUSE_PHRASES: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "brain.provider_down_cause"
)

# Priority when several providers failed for different reasons — the FIRST
# matching kind names the spoken cause. Mirrors the root-cause ordering of
# ``_format_provider_chain_error`` (missing key beats rate limit, etc.);
# ``skipped_cooldown`` collapses onto rate_limit and network/other onto
# ``unreachable``.
_PROVIDER_DOWN_CAUSE_PRIORITY: tuple[str, ...] = (
    "missing_key",
    "bad_key",
    "account_blocked",
    "vision_unsupported",
    "invalid_model",
    "local_context",
    "context_overflow",
    "rate_limit",
    "unreachable",
)


def _primary_provider_down_cause(
    errors: list[tuple[str, str, str, str]] | None,
) -> str | None:
    """Map a provider-error list onto the single spoken cause category."""
    if not errors:
        return None
    kinds = {kind for _prov, _model, kind, _detail in errors}
    if "skipped_cooldown" in kinds:
        kinds.add("rate_limit")
    if kinds - {
        "missing_key",
        "bad_key",
        "account_blocked",
        "vision_unsupported",
        "invalid_model",
        "local_context",
        "context_overflow",
        "rate_limit",
        "skipped_cooldown",
        "empty_response",
    }:
        # Any unclassified failure (network, timeout, 5xx) reads as
        # unreachable — the honest generic cause.
        kinds.add("unreachable")
    for cause in _PROVIDER_DOWN_CAUSE_PRIORITY:
        if cause in kinds:
            return cause
    return None


def _provider_down_phrase(lang: str, idx: int, cause: str | None = None) -> str:
    """Localized apology for a total brain-chain failure, cause-aware.

    ``lang`` is a reply-language code (de/en/es/pt); anything else — notably
    "auto" or a language without translations — falls back to English
    (``DEFAULT_LOCALE``). When ``cause`` names
    a known failure category, the phrase states WHY and the in-app recovery
    step (maintainer directive 2026-07-21) — still without provider names,
    URLs, or jargon (ADR-0010). Otherwise ``idx`` rotates deterministically
    through the generic variants so repeated failures in one session don't
    repeat the identical sentence.
    """
    lang_key = (lang or "").strip().lower()
    if cause:
        cause_table = _PROVIDER_DOWN_CAUSE_PHRASES.get(cause)
        if cause_table:
            return i18n_catalog.pick(cause_table, lang_key)
    variants = i18n_catalog.pick(_PROVIDER_DOWN_PHRASES, lang_key)
    return variants[idx % len(variants)]


# AD-OE6: a model round that dies AFTER tools already ran must end in an honest
# spoken notice, never silence. Forensic 2026-07-05 (session 3e27dd8e): the
# provider sent finish_reason="error" on a ~224k-token round following 10+
# executed tools; the empty-response guard is (correctly) skipped when tool
# calls exist, so the turn counted as success with empty text — the user heard
# NOTHING. Voice-safe: no provider names, no jargon (ADR-0010).
_MID_ANSWER_ERROR_PHRASES: dict[str, str] = i18n_catalog.table("brain.mid_answer_error")


#: Source layers that run without a person waiting on the reply. An appshot
#: parked for "the next message" belongs to the user's next message, never to
#: a scheduled task or a background worker that happens to run first.
_AUTOMATED_LAYER_PREFIXES = (
    "tasks",
    "workflows",
    "skills",
    "missions",
    "society",
    "supervisor",
    "tool.",
)


def _takes_pending_appshot(source_layer: str | None) -> bool:
    layer = (source_layer or "").strip().lower()
    return not layer.startswith(_AUTOMATED_LAYER_PREFIXES)


def _current_turn_language(owner: object) -> str:
    """This turn's language: the context's own, else the last one set."""
    return TURN_LANGUAGE.get() or getattr(owner, "_turn_detected_lang", "")


def _turn_phrase_language(owner: object, user_text: str) -> str:
    """The de/en/es/pt language of a system phrase for *user_text*.

    One resolver for every canned phrase: the pin, else the language
    ``generate()`` resolved for this turn (which already applied stickiness,
    the chat's own history and ``language_text`` — so an internal English
    "continue" prompt does not make the error phrases English), else the text
    within the running conversation, else English. ``generate()`` only
    receives text (the pipeline resolves the STT tag separately), hence
    ``"unknown"`` as the tag. Reads the manager's fields with ``getattr`` so
    lightweight stand-ins work too.
    """
    pin = getattr(owner, "_reply_language", "")
    if pin in _REPLY_LANG_NAMES:
        return pin
    turn = TURN_LANGUAGE.get()
    if turn:
        return phrase_locale(turn) if is_known_language(turn) else DEFAULT_LOCALE
    return resolve_output_language(
        pin,
        "unknown",
        user_text,
        conversation_language=getattr(owner, "_conversation_language", ""),
    )


def _is_local_provider(provider: str | None) -> bool:
    """True for an on-device provider (no key, no price list)."""
    try:
        from dodaios.brain.app_control import LOCAL_PROVIDERS
    except Exception:  # noqa: BLE001 — pricing must never break a turn
        return False
    return bool(provider) and provider in LOCAL_PROVIDERS


async def _turn_cost_usd(
    provider: str | None,
    model: str | None,
    tokens_in: int,
    tokens_out: int,
    tokens_cached: int,
) -> float:
    """USD cost of one completed brain turn; never raises."""
    # On-device models are free and absent from every price list; pricing
    # them warned on every turn and refreshed a remote catalogue for nothing.
    if _is_local_provider(provider):
        return 0.0
    try:
        from dodaios.brain import cost

        # A model the static table has never heard of is priced
        # from the provider feed — ONE refresh per model per
        # process (capped at 3 s), so a new generation stops
        # shipping as "$0.00" until someone edits the table.
        if tokens_in > 0 or tokens_out > 0 or tokens_cached > 0:
            await cost.ensure_pricing_for(model)
        usd = cost.calculate_cost_usd(model, tokens_in, tokens_out, tokens_cached)
        if usd == 0.0 and tokens_in > 0:
            # An unknown model prices as $0.00 and every surface
            # then renders the turn as free — that silence is how
            # 1.87M deepseek tokens went unbilled for a month
            # (2026-07-28 cost audit). Say it once per turn.
            log.warning(
                "No pricing for model %r (static table and "
                "provider feed) — %d in / %d out tokens recorded "
                "as $0.00; add it to dodaios/brain/cost.py "
                "PRICING_USD_PER_MTOK",
                model, tokens_in, tokens_out,
            )
        return usd
    except Exception:  # noqa: BLE001
        log.warning(
            "Cost calculation failed for model %r — recording $0.00",
            model, exc_info=True,
        )
        return 0.0


from dodaios.brain.manager_parts.agentic_ide import _AgenticIdeMixin  # noqa: E402
from dodaios.brain.manager_parts.local_action import _LocalActionMixin  # noqa: E402
from dodaios.brain.manager_parts.prompt import _PromptMixin  # noqa: E402
from dodaios.brain.manager_parts.skills import _SkillsMixin  # noqa: E402
from dodaios.brain.manager_parts.spawn import _SpawnMixin  # noqa: E402
from dodaios.brain.manager_parts.tool_surface import _ToolSurfaceMixin  # noqa: E402
from dodaios.brain.manager_parts.turn_loop import _TurnLoopMixin  # noqa: E402


class BrainManager(_SkillsMixin, _ToolSurfaceMixin, _AgenticIdeMixin, _SpawnMixin, _LocalActionMixin, _TurnLoopMixin, _PromptMixin):
    """Top-level orchestrator with intent router and smart fallback."""

    def __init__(
        self,
        config: JarvisConfig,
        bus: EventBus,
        *,
        core_memory: CoreMemory | None = None,
        recall: RecallStore | None = None,
        tools: dict[str, Tool] | None = None,
        local_action_tools: dict[str, Tool] | None = None,
        tool_executor: ToolExecutor | None = None,
        system_prompt_extra: str = "",
        user_profile: UserProfile | None = None,
        soul: Soul | None = None,
        people: PersonStore | None = None,
        curator: Curator | None = None,
        cost_meter: "CostMeterLike | None" = None,  # noqa: UP037
        contacts: Any = None,
        readback_composer: "ReadbackComposer | None" = None,  # noqa: UP037
    ) -> None:
        self._config = config
        self._bus = bus
        # User-facing reply-language pin. "auto" mirrors the user's input
        # language (DE/EN/ES); a pinned code forces that language for every
        # reply (desktop "Languages" view). Consumed by
        # _reply_language_directive(); mutated live via set_reply_language().
        self._reply_language: str = normalize_reply_language(
            getattr(getattr(config, "brain", None), "reply_language", None)
        )
        self._core_memory = core_memory
        self._recall = recall
        # The message recorder the factory attached to the bus for this brain,
        # detached again by aclose() (see own_message_recorder).
        self._message_recorder: tuple[Any, Any] | None = None
        self._tools = tools or {}
        self._local_action_tools = dict(local_action_tools or {})
        self._tool_executor = tool_executor
        # Two-turn voice/chat confirmation (forensic 2026-06-18): an ask-tier tool
        # on a conversational turn is deferred + spoken-confirmed instead of
        # blocking on a UI approval no voice user can give. Enabled by config,
        # opted into per-turn only by conversational callers (``allow_voice_confirm``).
        self._voice_confirm_enabled: bool = bool(
            getattr(getattr(config, "brain", None), "voice_confirm", True)
        )
        self._pending_voice_confirm: _PendingVoiceConfirm | None = None
        # Ambiguous visual requests use a separate, read-only yes/no proposal.
        # Keying by source keeps a web-chat answer from authorizing a voice
        # capture (and vice versa); entries expire quickly and never persist.
        self._pending_screen_confirms: dict[
            tuple[str, str], _PendingScreenConfirm
        ] = {}
        self._system_prompt_extra = system_prompt_extra
        self._user_profile = user_profile
        self._soul = soul
        self._people = people
        # Chunk B (contacts): optional ContactStore (Contract 1, owned by Chunk
        # A). When set, _build_system_prompt() appends its compact name-index
        # (names + relationship only; details on demand via contact-lookup).
        # None until Chunk A is merged — the block is simply omitted (graceful).
        self._contacts = contacts
        # Context-aware spoken readbacks (maintainer mandate: no fixed stock
        # phrases). When wired (router tier, via factory.build_readback_composer)
        # the deterministic action-path readbacks — CU outcome/dispatch, budget,
        # tool-failed — are phrased fresh for the situation by a bounded flash
        # call, with the EXISTING canned line as the instant fallback. None on the
        # bare/CLI managers and in tests => unchanged canned behavior (risk-free).
        self._readback_composer = readback_composer
        # Phase 5 / ADR-0006: optional budget hook. Fed with aggregated usage
        # post-call; pre-call blocks when in cooldown or when the task/daily
        # budget is exceeded. When None, the feature is completely inactive —
        # no effect on the dispatch path.
        self._cost_meter = cost_meter
        self._curator = curator
        self._vision_provider = None
        # Drag-drop: ad-hoc images attached to ONE upcoming turn, keyed by that
        # turn's trace_id (see dodaios/brain/drop_context.py). Popped + cleared in
        # _collect_vision_images, bypassing the screen-vision gate so a dropped
        # picture reaches the multimodal brain even with screen-vision off.
        self._pending_turn_images: dict[UUID, tuple[ImageBlock, ...]] = {}
        # Drag-drop SILENT context: pictures dropped onto the bar/mascot, parked
        # for the NEXT real turn (a drop never triggers a turn). See
        # add_dropped_context / generate. Dropped TEXT goes into _history.
        self._pending_drop_images: tuple[ImageBlock, ...] = ()
        # Per-turn memory recall (ADR-0044): set in generate(), consumed by the
        # prompt builders, reset at the end of every turn.
        self._memory_context_suffix: str = ""
        # Per-turn detected language (de/en/es/pt or "" when ambiguous/pinned),
        # set at the top of generate(); consumed by _reply_language_directive()
        # in auto mode to hard-pin the turn's language so a tool-synthesis turn
        # cannot drift back to German (live bug 2026-06-14).
        self._turn_detected_lang: str = ""
        # Sticky conversation language (de/en/es/pt, "" until established). Updated
        # only on a SUBSTANTIVE turn so a thin interjection ("Now", "Stop") never
        # flips an established conversation; consumed by _update_turn_language and
        # exposed to the speech pipeline / deterministic tool readbacks so the
        # whole turn stays in one language (natural-flow forensic 2026-06-18).
        self._conversation_language: str = ""
        # AD-OE6 zero-silent-drop signal. True for exactly one turn after the
        # whole provider fallback chain failed (no key / depleted credits /
        # rate-limited everywhere). The voice pipeline reads this to decide
        # whether to speak a spoken "all providers are down" fallback instead
        # of returning silently to LISTENING. A legitimate empty turn
        # (suppress_response fire-and-forget) leaves this False.
        self._last_turn_all_failed = False
        # AD-OE6 companion signal. True for exactly one turn when the winning
        # provider finished with ``suppress_response`` (a fire-and-forget
        # ``spawn_worker`` background mission that reports back over the bus).
        # The voice pipeline reads this to tell a LEGIT silent turn (spawn —
        # stay silent) from a turn that produced no speech for any other reason
        # (function_call/CU without speech, empty content). The latter must NOT
        # drop the user into silence — it gets a spoken clarifying question
        # (live "Jarvis antwortet nie" cause 2026-06-08: conversational turns
        # returned a function_call and the turn ended mute).
        self._last_turn_suppressed = False
        # AD-OE6 companion signal #2. True for exactly one turn when the winning
        # provider executed a DESKTOP-ACTION tool (computer_use / open_app /
        # click / type / …) but produced no narration text. A wordless desktop
        # action is a SUCCESS the user must hear confirmed — NOT a clarifying
        # question. Live bug 2026-06-09 (data/jarvis_desktop.log 16:27): the
        # router brain called computer_use, the CU loop opened Chrome ([cu] step
        # 1.1 open_app → step 2 done), Gemini emitted no text, and the pipeline
        # spoke "Wie meinst du das genau?" — so a successful action looked like
        # incomprehension. The pipeline reads this to speak a confirmation
        # instead. Reset to False each turn; only the winning provider sets it.
        self._last_turn_executed_action_tool = False
        # Rotation cursor for the localized "brain unreachable" spoken fallback
        # (_provider_down_phrase). Advances once per total-failure turn so the
        # phrase varies instead of repeating verbatim.
        self._provider_down_idx: int = 0

        self._registry = BrainProviderRegistry()
        raw_primary = getattr(config.brain, "primary", None)
        router_cfg = getattr(config.brain, "router", None)
        coerced_primary = _coerce_main_brain_provider(
            raw_primary,
            getattr(router_cfg, "provider", None),
            getattr(config.brain, "deep_brain", None),
        )
        if coerced_primary != (raw_primary or "").strip():
            log.warning(
                "Brain provider %r is subagent-only; using %r as main brain.",
                raw_primary,
                coerced_primary,
            )
            config.brain.primary = coerced_primary
        self._active_name: str = coerced_primary
        # The (provider, model) actually answering the CURRENT turn. Set per
        # fallback-chain attempt in generate() right before the dispatcher is
        # built, consumed by _build_system_prompt to inject the authoritative
        # self-identity line (forensic 2026-06-20: the answering LLM never knew
        # which provider it was, so a provider question got a guessed "Gemini").
        # None outside a turn → no identity block on helper prompt builds.
        self._active_turn_identity: tuple[str, str | None] | None = None
        # Last persist-to-disk outcome of ``switch(..., persist=True)``.
        # ``None`` = no persisting switch attempted yet. The provider route
        # reads this to report the ACTUAL disk result instead of echoing the
        # request flag (anti-silent-drop, AD-OE6).
        self.last_persist_ok: bool | None = None
        # Cache: (provider-name, model-name-or-None) → Brain-Instance
        self._brain_cache: dict[tuple[str, str | None], Brain] = {}

        # Latency sprint 2: provider caching is communicated to the brain plugins
        # via environment variables (they are stateless API adapters, not DI).
        # Always set rather than only-when-true so that a subsequent
        # reconfiguration via hot-reload works in both directions (true→false
        # disables it).
        import os as _os
        perf = getattr(config, "performance", None)
        if perf is not None:
            _os.environ["JARVIS_ANTHROPIC_PROMPT_CACHE"] = (
                "1" if getattr(perf, "anthropic_prompt_cache", False) else "0"
            )
            _os.environ["JARVIS_GEMINI_CONTEXT_CACHE"] = (
                "1" if getattr(perf, "gemini_context_cache", False) else "0"
            )
        self._history: list[BrainMessage] = []
        self._lock = asyncio.Lock()
        # Sticky override: "denk gründlich" sets _force_level="deep"
        # until the user says "denk schnell".
        self._force_level: str | None = None
        # Circuit breaker for 429-limited providers (skip for 30s)
        self._rate_tracker = RateLimitTracker(cooldown_s=30.0)
        # Session dead-list: providers that definitely have no key/auth in
        # THIS session. Filtered from the chain until session end or until the
        # next provider switch (user sets a key in the UI → switch triggers
        # reset). Prevents each voice turn from running through 8 sequential
        # "no API key" failures.
        self._dead_providers: set[str] = set()
        # The provider a person switched to at runtime ("switch to openai").
        # A deliberate pick keeps answering even on the realtime voice key.
        self._switched_to: str | None = None
        # Model-scoped twin of `_dead_providers`: a billing-style rejection
        # (account_blocked, e.g. HTTP 402) on ONE model must not dead-list a
        # provider that has other, untried models still in this turn's chain
        # (e.g. a paid model capped out while a free model on the same
        # provider is still funded). Populated/consulted only for
        # account_blocked; missing_key/bad_key stay provider-wide since a
        # dead credential blocks every model on that provider.
        self._dead_provider_models: set[tuple[str, str | None]] = set()
        # Populated by from_tier_config(). Tier fallbacks are runtime
        # priorities, not just healthcheck metadata.
        self._configured_fallbacks: list[tuple[str, str | None]] = []
        # Persona mandate phase 3: deterministic force-spawn heuristic.
        # Lazily compiled from self._config.brain.routing.
        self._routing_patterns: tuple[
            re.Pattern[str], re.Pattern[str], re.Pattern[str]
        ] | None = None
        # Heavy-research force-spawn patterns (verb + heaviness-marker), lazily
        # compiled from brain.routing.heavy_research_*. Live bug 2026-06-14.
        self._heavy_research_patterns: tuple[
            re.Pattern[str], re.Pattern[str]
        ] | None = None
        # User-Mandate 2026-05-14: strict-mode trigger-phrase regex
        # (compiled from `brain.routing.force_spawn_phrases`). Cached so
        # the hot path stays cheap.
        self._force_spawn_pattern: re.Pattern[str] | None = None
        # AD-12 / AP-OC5 (wave-4 router): optional handlers for Jarvis-Agent
        # mission status/cancel. Injected via ``set_mission_command_handlers``
        # after bootstrap so the BrainManager constructor has no hard
        # dependency on MissionManager.
        self._jarvis_agent_status_fn: (
            Callable[[str | None], Awaitable[str]] | None
        ) = None
        self._jarvis_agent_cancel_fn: (
            Callable[[str | None], Awaitable[str]] | None
        ) = None

    # ------------------------------------------------------------------
    # Tiered-Routing-Factory (Phase 5)
    # ------------------------------------------------------------------

    @classmethod
    def from_tier_config(
        cls,
        tier: Literal["router"],
        config: JarvisConfig,
        bus: EventBus,
        *,
        provider_override: str | None = None,
        tools: dict[str, Tool] | None = None,
        local_action_tools: dict[str, Tool] | None = None,
        tool_executor: ToolExecutor | None = None,
        core_memory: CoreMemory | None = None,
        recall: RecallStore | None = None,
        user_profile: UserProfile | None = None,
        soul: Soul | None = None,
        people: PersonStore | None = None,
        contacts: Any = None,
    ) -> BrainManager:
        """Builds a BrainManager from the tier-specific config.

        Wave-4 migration: previously there were two tiers, ``router`` and
        ``sub_jarvis``. The Sub-Jarvis tier was replaced by the Jarvis-Agent
        bridge (see docs/jarvis-agents-bridge.md §11); only ``router`` remains.

        Reads `config.brain.router` and writes into a deep copy of JarvisConfig:
          - `brain.primary = tier_cfg.provider` (or `provider_override`)
          - `brain.deep_brain = tier_cfg.fallback_provider`, UNLESS a
            `provider_override` collapses a non-split tier (fallback in
            {None, provider}) — then deep_brain follows the override so a
            user-chosen frontier provider leads deep/code too (see below).

        The global `config` instance is left unchanged.

        Args:
            provider_override: When set, `tier_cfg.provider` is ignored and
                the override is used. This is the hook for the live provider
                switch: when the user says "wechsel auf gemini" via voice.
                The associated `tier_cfg.model` is then NOT used (it was
                intended for the original provider) — instead the default
                from TIER_DEFAULTS_BY_PROVIDER applies for the new provider.
        """
        tier_cfg = getattr(config.brain, tier, None)
        if tier_cfg is None:
            # A fresh install ships NO [brain.router] block: dodaios.toml.example
            # has a [brain] table but no [brain.router] sub-table, and neither
            # the wizard, the installer, nor onboarding ever writes one. Raising
            # here left ``app.state.brain = None``, which bricked BOTH the
            # voice/chat brain AND the provider-switch route — the latter then
            # surfaced the misleading "headless mode" 503 on every "Set active"
            # click. This only ever hit downloaders: the maintainer's own
            # jarvis.toml HAS the block (textbook AP-23 "works on my machine").
            # Instead of failing, synthesize the tier from the user's REAL
            # selection. BrainTierConfig only requires ``provider``; the model is
            # filled per-provider by ``_resolve_tier_model``. Provider-agnostic —
            # it honours whatever main provider the fresh user configured, and an
            # explicit [brain.router] block still overrides this untouched.
            default_provider = (
                (config.brain.primary or "").strip()
                or (config.brain.routing_provider or "").strip()
                or "claude-api"
            )
            log.info(
                "No [brain.%s] block in config — synthesizing a default tier from "
                "brain.primary=%r so a fresh install boots a working brain.",
                tier,
                default_provider,
            )
            tier_cfg = BrainTierConfig(provider=default_provider)

        local_config = config.model_copy(deep=True)
        requested_provider = provider_override or tier_cfg.provider
        effective_provider = _coerce_main_brain_provider(
            requested_provider,
            tier_cfg.provider,
            tier_cfg.fallback_provider,
            getattr(config.brain, "deep_brain", None),
        )
        if effective_provider != (requested_provider or "").strip():
            log.warning(
                "Brain provider %r is subagent-only; using %r as router brain.",
                requested_provider,
                effective_provider,
            )
        local_config.brain.primary = effective_provider
        # deep_brain normally mirrors the tier's fallback provider. But when an
        # explicit override redirected the active provider away from the tier
        # default AND there is no deliberate cross-provider deep split
        # (fallback_provider == provider), the deep brain must FOLLOW the override
        # — otherwise a user-chosen frontier provider (grok/codex) still delegates
        # every deep/code turn to the orphaned tier default. Forensic 2026-06-20:
        # primary=grok left deep_brain=gemini, so reasoning turns ran on Gemini
        # despite the user picking Grok ("Grok for everything" mandate). An
        # explicit split (fallback_provider != provider) is preserved.
        deep_provider = tier_cfg.fallback_provider
        if (
            provider_override
            and effective_provider != tier_cfg.provider
            and (
                # No fallback configured at all (None/"") is even less of a
                # deliberate split than a symmetric one — follow the override
                # rather than strand deep_brain at None for the whole session.
                not tier_cfg.fallback_provider
                or tier_cfg.fallback_provider == tier_cfg.provider
            )
        ):
            deep_provider = effective_provider
        local_config.brain.deep_brain = deep_provider

        # Tier model resolver:
        # - If a live override is active: ignore tier_cfg.model (it belonged to
        #   the ORIGINAL tier provider, e.g. [brain.router].model="gemini-3.5-flash").
        #   BUT the override provider's OWN picked model
        #   ([brain.providers.<override>].model) IS the user's selection and MUST
        #   win over the hardcoded TIER default. Without this, an OpenRouter user
        #   who picked a free model silently ran — and was billed for — the
        #   hardcoded paid anthropic/claude default (router=haiku-4.5, deep=opus-4.8)
        #   on EVERY boot, because this very assignment clobbered the picked model
        #   in the in-memory config before _fast_model/_deep_model could read it
        #   (live forensic 2026-06-29: ~5€ OpenRouter key drained on Opus + Haiku).
        #   AP-21/AP-22, open-source single-key §3.
        # - If no override: respect tier_cfg.model, then the provider pick, then
        #   fall back to the default. Fresh installs have no [brain.router]
        #   block, so ignoring providers.<name>.model here would overwrite the
        #   model selected in the UI on every boot.
        if provider_override:
            override_pc = (local_config.brain.providers or {}).get(effective_provider)
            explicit_model = getattr(override_pc, "model", None) or None
        else:
            provider_pc = (local_config.brain.providers or {}).get(effective_provider)
            explicit_model = (
                tier_cfg.model
                or getattr(provider_pc, "model", None)
                or None
            )
        resolved_model = _resolve_tier_model(tier, effective_provider, explicit_model)
        if resolved_model and effective_provider in (local_config.brain.providers or {}):
            local_config.brain.providers[effective_provider].model = resolved_model

        # BUG-LATENCY (2026-05-24): the router is a pure dispatcher — it must not
        # burn seconds on "extended thinking". Cap the thinking budget on the
        # router provider config. ``local_config`` is a deep copy, so this affects
        # ONLY the router brain — workers/critic (separate config load) keep full
        # frontier reasoning (user mandate). Gemini honours thinking_budget=0 as
        # "no thinking"; providers without the field ignore it harmlessly.
        router_prov_cfg = local_config.brain.providers.get(effective_provider)
        if router_prov_cfg is not None:
            try:
                router_prov_cfg.thinking_budget = 0
            except (AttributeError, TypeError):
                pass

        configured_fallbacks: list[tuple[str, str | None]] = []

        if tier_cfg.fallback_provider:
            resolved_fallback = _resolve_tier_model(
                tier, tier_cfg.fallback_provider, tier_cfg.fallback_model
            )
            configured_fallbacks.append((tier_cfg.fallback_provider, resolved_fallback))
        # BUG-LATENCY (2026-05-24): only mutate the fallback provider's `model`
        # when it is a DIFFERENT provider than the primary. When primary ==
        # fallback (e.g. [brain.router] provider="gemini" + fallback_provider=
        # "gemini"), both share the same providers["gemini"] entry, so this
        # write used to clobber the primary's fast model (flash) with the deep
        # fallback model (pro) — the router then ran every turn on the slow
        # reasoning model (~9 s thinking). The same-provider fallback model is
        # still carried in `configured_fallbacks` for the chain below.
        if (
            tier_cfg.fallback_provider
            and tier_cfg.fallback_provider != effective_provider
            and tier_cfg.fallback_provider in (local_config.brain.providers or {})
        ):
            resolved_fallback = _resolve_tier_model(
                tier, tier_cfg.fallback_provider, tier_cfg.fallback_model
            )
            if resolved_fallback:
                local_config.brain.providers[tier_cfg.fallback_provider].model = resolved_fallback

        if tier_cfg.fallback_provider_2:
            resolved_fallback_2 = _resolve_tier_model(
                tier, tier_cfg.fallback_provider_2, tier_cfg.fallback_model_2
            )
            configured_fallbacks.append((tier_cfg.fallback_provider_2, resolved_fallback_2))
            if (
                resolved_fallback_2
                and tier_cfg.fallback_provider_2 != effective_provider
                and tier_cfg.fallback_provider_2 in (local_config.brain.providers or {})
            ):
                local_config.brain.providers[tier_cfg.fallback_provider_2].model = (
                    resolved_fallback_2
                )

        manager = cls(
            config=local_config,
            bus=bus,
            core_memory=core_memory,
            recall=recall,
            tools=tools,
            local_action_tools=local_action_tools,
            tool_executor=tool_executor,
            user_profile=user_profile,
            soul=soul,
            people=people,
            contacts=contacts,
        )
        manager._configured_fallbacks = configured_fallbacks

        # Bug E fix (2026-04-29) — pre-boot key check.
        # Push providers without an API key directly into _dead_providers,
        # otherwise they produce BrainTurnStarted hallucination tags in the DB
        # before _ensure_client() crashes. Example: user only has Anthropic +
        # Gemini + xAI keys → openai/openrouter are not tried at all.
        from dodaios.core import config as _cfg_mod
        from dodaios.core.config import PROVIDER_SECRET_CANDIDATES
        provider_to_slots: dict[str, list[str]] = {}
        for secret_key, provider_name in _SECRET_KEY_TO_BRAIN.items():
            provider_to_slots.setdefault(provider_name, []).append(secret_key)
        for provider_name, secret_specs in PROVIDER_SECRET_CANDIDATES.items():
            try:
                key_value = _cfg_mod.get_secret_any(secret_specs)
            except Exception:  # noqa: BLE001
                key_value = None
            if not key_value:
                # A keyless-but-credentialed provider — an OAuth login on disk
                # (codex via ChatGPT) or a Google Cloud project signing with
                # Application Default Credentials (vertex) — is NOT dead-listed
                # (open-source AP-22).
                if _keyless_provider_is_rescued_by_oauth(provider_name):
                    log.info(
                        "Pre-boot key check: '%s' has no API key but a login / "
                        "Cloud project credential -> kept active.",
                        provider_name,
                    )
                    continue
                manager._dead_providers.add(provider_name)
                log.info(
                    "Pre-boot key check: no key in %s -> provider '%s' disabled.",
                    provider_to_slots.get(provider_name, [provider_name]),
                    provider_name,
                )
        return manager

    # ------------------------------------------------------------------
    # Provider instance cache
    # ------------------------------------------------------------------

    def available_providers(self) -> list[str]:
        return self._registry.available()

    def failed_providers(self) -> dict[str, str]:
        return self._registry.failed()

    def _provider_cfg(self, name: str):
        return self._config.brain.providers.get(name)

    def _fast_model(self, name: str) -> str | None:
        cfg = self._provider_cfg(name)
        if cfg is None:
            return get_tier_default_model("router", name)
        return cfg.model or get_tier_default_model("router", name)

    def _deep_model(self, name: str) -> str | None:
        cfg = self._provider_cfg(name)
        if cfg is None:
            return get_tier_default_model("deep", name)
        # Precedence: explicit deep_model → the user's CHOSEN model → hardcoded
        # tier default. The chosen model MUST outrank the hardcoded default:
        # otherwise a provider with a `model` set but no `deep_model` (e.g.
        # openrouter = "nvidia/nemotron-...:free") silently runs the deep slot on
        # a foreign-family default (anthropic/claude-opus-4.8). Live forensic
        # 2026-06-29: that default is a PAID model 403-blocked by the user's
        # OpenRouter key spend-limit, while the chosen FREE model answered fine —
        # so the turn bricked despite a healthy, user-selected brain. Respect the
        # selected model; never hijack a turn onto the most expensive Anthropic
        # model the user never picked (AP-21/AP-22, open-source single-key §3).
        return (
            getattr(cfg, "deep_model", None)
            or getattr(cfg, "model", None)
            or get_tier_default_model("deep", name)
        )

    def _cu_model(self, name: str) -> str | None:
        """Resolve the Tool Model for ``name``, including the legacy CU key."""
        return self._tool_model_model(name)

    def _tool_model_model(
        self, name: str, fallback: str | None = None
    ) -> str | None:
        """Resolve an explicit Tool Model pin before a caller's model choice."""
        from dodaios.core.model_selection import operation_model, worker_selection

        selection = operation_model.get() or worker_selection(self._config)
        if selection is not None and selection.provider == name:
            return selection.model or fallback or get_tier_default_model("worker", name)
        cfg = self._provider_cfg(name)
        if cfg is None:
            return fallback or get_tier_default_model("router", name)
        return (
            getattr(cfg, "tool_model", None)
            or getattr(cfg, "cu_model", None)
            or fallback
            or getattr(cfg, "model", None)
            or get_tier_default_model("router", name)
        )

    def _tool_model_provider(self) -> str:
        """Return the canonical Tool Model provider or its legacy fallback."""
        from dodaios.core.model_selection import operation_model, worker_selection

        selection = operation_model.get() or worker_selection(self._config)
        if selection is not None:
            return selection.provider
        try:
            brain_cfg = self._config.brain
            canonical = getattr(brain_cfg, "tool_model", None)
            provider = (getattr(canonical, "provider", None) or "").strip()
            if provider:
                return provider
            legacy = getattr(brain_cfg, "computer_use", None)
            return (getattr(legacy, "provider", None) or "").strip()
        except Exception:  # noqa: BLE001 -- config failure must not block dispatch
            return ""

    def _tool_model_source(self) -> str:
        """Identify whether the selection came from canonical or legacy config."""
        try:
            fields_set = getattr(self._config.brain, "model_fields_set", set())
            if "tool_model" in fields_set:
                return "tool_model"
            if "computer_use" in fields_set:
                return "computer_use"
        except Exception:  # noqa: BLE001, S110 -- status must never raise
            pass
        return "auto" if self._tool_model_provider() in ("", "auto") else "tool_model"

    @staticmethod
    def _tool_model_family(provider: str) -> str:
        """Credential/quota family used to avoid same-family fallback bricks."""
        return {
            "codex": "openai",
            "openai-api": "openai",
            "antigravity": "gemini",
        }.get(provider, provider)

    def _tool_model_credential_ready(self, provider: str) -> bool:
        """Whether ``provider`` has a portable usable credential."""
        try:
            from dodaios.brain.app_control import get_spec, is_credential_present

            spec = get_spec(provider)
            if spec is not None:
                return bool(is_credential_present(spec))
            from dodaios.core import config as cfg_mod

            return bool(cfg_mod.get_provider_secret(provider))
        except Exception:  # noqa: BLE001 -- a failed probe is not readiness
            return False

    def tool_model_candidate_status(
        self, provider: str, model: str | None = None
    ) -> dict[str, Any]:
        """Return a secret-free runtime capability verdict for one candidate."""
        provider = (provider or "").strip()
        model = model or self._cu_model(provider)
        result: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "ready": False,
            "reason": "unknown",
            "tools": None,
            "vision": None,
        }
        if not provider or provider == "auto":
            result["reason"] = "automatic_selection"
            return result
        if provider not in set(self._registry.available()):
            result["reason"] = "provider_unavailable"
            return result
        if provider in self._dead_providers:
            result["reason"] = "provider_dead"
            return result
        if (provider, model) in self._dead_provider_models:
            result["reason"] = "model_dead"
            return result
        if not self._rate_tracker.is_available(provider, model):
            result["reason"] = "rate_limited"
            return result
        if not self._tool_model_credential_ready(provider):
            result["reason"] = "missing_credential"
            return result
        try:
            brain = self._get_brain(provider, model)
        except Exception:  # noqa: BLE001 -- status must remain secret-free
            result["reason"] = "provider_initialization_failed"
            return result

        result["vision"] = getattr(brain, "supports_vision", None)
        try:
            can_call = getattr(brain, "can_call_tools", None)
            tools = (
                bool(can_call())
                if callable(can_call)
                else bool(getattr(brain, "supports_tools", True))
            )
        except Exception:  # noqa: BLE001 -- fail closed for action routing
            result["reason"] = "capability_probe_failed"
            return result
        result["tools"] = tools
        if not tools:
            result["reason"] = "tools_unsupported"
            return result
        result["ready"] = True
        result["reason"] = "ready"
        return result

    def _tool_model_base_chain(self) -> list[tuple[str, str | None]]:
        """Build the stable cross-provider chain used by automatic selection."""
        brain_cfg = self._config.brain
        names = [
            getattr(brain_cfg, "primary", None),
            getattr(brain_cfg, "deep_brain", None),
            getattr(getattr(brain_cfg, "router", None), "provider", None),
            "gemini",
            "claude-api",
            "openai",
            "openrouter",
            "grok",
            "nvidia",
            "litellm",
            *self._registry.available(),
        ]
        seen: set[str] = set()
        chain: list[tuple[str, str | None]] = []
        for name in names:
            if not name or name in seen:
                continue
            seen.add(name)
            chain.append((name, self._cu_model(name)))
        return chain

    def resolve_tool_model(
        self, chain: list[tuple[str, str | None]] | None = None
    ) -> dict[str, Any]:
        """Resolve a key-ready, tool-capable provider across quota families."""
        configured = self._tool_model_provider()
        configured_model = (
            self._cu_model(configured)
            if configured and configured != "auto"
            else None
        )
        candidates = list(chain) if chain is not None else self._tool_model_base_chain()
        if configured and configured != "auto":
            candidates.insert(0, (configured, configured_model))

        seen_families: set[str] = set()
        first_failure = "no_tool_capable_provider"
        configured_failure: str | None = None
        for index, (provider, model) in enumerate(candidates):
            family = self._tool_model_family(provider)
            if family in seen_families:
                continue
            seen_families.add(family)
            verdict = self.tool_model_candidate_status(
                provider, self._tool_model_model(provider, model)
            )
            if verdict["ready"]:
                selected_configured = (
                    configured not in ("", "auto") and provider == configured
                )
                return {
                    "configured_provider": configured or "auto",
                    "configured_model": configured_model,
                    "effective_provider": provider,
                    "effective_model": verdict["model"],
                    "state": (
                        "ready"
                        if selected_configured or configured in ("", "auto")
                        else "fallback"
                    ),
                    "reason": (
                        "configured_selection"
                        if selected_configured
                        else (
                            f"configured_{configured_failure}"
                            if configured_failure is not None
                            else "automatic_selection"
                        )
                    ),
                    "source": self._tool_model_source(),
                    "tools": verdict["tools"],
                    "vision": verdict["vision"],
                }
            if index == 0:
                first_failure = str(verdict["reason"])
            if configured not in ("", "auto") and provider == configured:
                configured_failure = str(verdict["reason"])

        return {
            "configured_provider": configured or "auto",
            "configured_model": configured_model,
            "effective_provider": None,
            "effective_model": None,
            "state": "blocked",
            "reason": first_failure,
            "source": self._tool_model_source(),
            "tools": False,
            "vision": None,
        }

    def _cu_provider(self) -> str:
        """Compatibility accessor for the canonical global Tool Model provider."""
        provider = self._tool_model_provider()
        return "" if provider == "auto" else provider

    def _hoist_tool_model(
        self, chain: list[tuple[str, str | None]]
    ) -> list[tuple[str, str | None]]:
        """Filter a delegated turn to tool-capable cross-family candidates."""
        from dodaios.core.model_selection import operation_model, worker_selection

        selection = operation_model.get() or worker_selection(self._config)
        if selection is not None:
            # A selected subscription must not silently turn into metered API usage.
            return [(selection.provider, selection.model)]
        configured = self._tool_model_provider()
        candidates = list(chain)
        if configured and configured != "auto":
            candidates.insert(0, (configured, self._cu_model(configured)))

        ready: list[tuple[str, str | None]] = []
        seen_families: set[str] = set()
        for provider, model in candidates:
            family = self._tool_model_family(provider)
            if family in seen_families:
                continue
            seen_families.add(family)
            verdict = self.tool_model_candidate_status(
                provider, self._tool_model_model(provider, model)
            )
            if verdict["ready"]:
                ready.append((provider, verdict["model"]))
        if not ready:
            log.warning("No credential-ready, tool-capable Tool Model is available.")
        return ready

    def _lead_vision_chain(
        self, chain: list[tuple[str, str | None]]
    ) -> list[tuple[str, str | None]]:
        """On an image turn, put the router vision FAST model first.

        Live 2026-08-31 17:06: a realtime screenshot delegated through
        ``prefer_tool_model`` led with Vertex ``gemini-3.7-flash`` (the Tool
        Model). Five providers then failed and grok-4.6 answered after 20 s.

        Live 2026-08-31 19:38: the first cut ranked by ``_active_name``
        (chat primary ``openrouter``). OpenRouter 402'd in 0.3 s, then
        Vertex ``gemini-3-flash-preview`` sat 20.5 s. Grok never ran. The
        router already names the look model (``[brain.router]``). Rank by
        that config, not the chat primary — AP-21: never hardcode a
        provider name, never treat a broke primary as a vision ranking
        signal.
        """
        if not chain:
            return chain
        router = getattr(getattr(self._config, "brain", None), "router", None)
        router_provider = (
            getattr(router, "provider", None) if router is not None else None
        )
        vision: list[tuple[str, str | None]] = []
        rest: list[tuple[str, str | None]] = []
        seen: set[str] = set()

        def _consider(provider: str, model: str | None) -> None:
            if provider in seen or provider in self._dead_providers:
                return
            seen.add(provider)
            pick_model = self._vision_look_model(provider) or model
            if self._provider_advertises_vision(provider, pick_model):
                vision.append((provider, pick_model))
            else:
                rest.append((provider, model))

        # Router first (from config), then the rest of the chain. The chat
        # primary is not a ranking signal — it may be a billed-out slot.
        if isinstance(router_provider, str) and router_provider:
            _consider(router_provider, None)
        for provider, model in chain:
            _consider(provider, model)
        if not vision:
            return chain
        led = vision + rest
        log.info(
            "screen-turn vision lead: %s(%s) — %d vision-capable, %d others",
            led[0][0],
            led[0][1],
            len(vision),
            len(rest),
        )
        return led

    def _vision_look_model(self, provider: str) -> str | None:
        """The fast look-at-screen model for ``provider``, never the CU/tool slot.

        Computer-Use and the Tool Model pick heavy siblings (grok-4.6). A
        screenshot narration wants the router-tier fast id when this is the
        routing provider.
        """
        router = getattr(getattr(self._config, "brain", None), "router", None)
        if (
            router is not None
            and getattr(router, "provider", None) == provider
            and getattr(router, "model", None)
        ):
            return str(router.model)
        return self._fast_model(provider)

    def _provider_advertises_vision(
        self, provider: str, model: str | None
    ) -> bool:
        try:
            brain = self._get_brain(provider, model)
        except Exception:  # noqa: BLE001 — unready provider stays in the tail
            return False
        return getattr(brain, "supports_vision", False) is True

    def _get_brain(
        self, name: str, model: str | None = None, *, scope: str | None = None
    ) -> Brain:
        """Retrieves a Brain instance from the cache, or builds a new one.

        ``scope`` namespaces the cache entry (``"<name>@<scope>"``): a turn
        under a ``TurnOverride`` gets its own instance, so its client — and
        the credential that client resolved — is never the voice brain's.
        """
        from dodaios.core.model_selection import operation_model

        selected = operation_model.get()
        if selected is not None and selected.brain_override is not None:
            if name != selected.provider or (model and model != selected.model):
                raise RuntimeError(
                    "This operation cannot switch its selected model or billing account."
                )
            return selected.brain_override
        key = (name if scope is None else f"{name}@{scope}", model)
        if key in self._brain_cache:
            return self._brain_cache[key]

        kwargs: dict[str, Any] = {}
        if model:
            kwargs["model"] = model
        cfg = self._provider_cfg(name)
        if cfg is not None and cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        # Latency sprint 1: pass through thinking budget — currently only Gemini
        # accepts this parameter. Other providers raise TypeError, then the
        # second attempt below retries without kwargs.
        if (
            name == "gemini"
            and cfg is not None
            and getattr(cfg, "thinking_budget", None) is not None
        ):
            tb = cfg.thinking_budget
            # Gemini Pro models REQUIRE thinking mode and reject budget=0 with
            # 400 "Budget 0 is invalid. This model only works in thinking mode."
            # The router caps budget to 0 for its fast (flash) model, but the
            # SAME gemini provider config is reused for the deep/pro fallback —
            # forwarding 0 there 400s the call and silently drops the turn.
            # Only forward budget=0 to non-pro models; let pro fall back to the
            # SDK default (auto thinking).
            eff_model = (model or getattr(cfg, "model", "") or "")
            if not (tb == 0 and "pro" in eff_model.lower()):
                kwargs["thinking_budget"] = tb

        try:
            inst = self._registry.instantiate(name, **kwargs)
        except TypeError:
            # A plugin __init__ rejected an OPTIONAL kwarg (base_url /
            # thinking_budget — not every brain accepts them). Retry, but NEVER
            # drop ``model``: the old fallback re-instantiated with NO kwargs at
            # all, so the brain fell back to its hardcoded DEFAULT_MODEL. For the
            # OpenRouter gateway that default is anthropic/claude-opus-4.8 — the
            # exact PAID model a spend-limited key 403s on, while the user's
            # chosen FREE model would have answered (live forensic 2026-06-29:
            # the wire carried opus though the chain logged nemotron:free). The
            # endpoint/budget are re-resolved from config inside the plugin's
            # _ensure_client, so dropping them here is safe; the model is
            # essential and must survive (AP-21/AP-22, open-source single-key §3).
            retry_kwargs: dict[str, Any] = {"model": model} if model else {}
            try:
                inst = self._registry.instantiate(name, **retry_kwargs)
            except TypeError:
                inst = self._registry.instantiate(name)
        # Anti-drift guarantee (user mandate 2026-06-29): the model on the wire
        # MUST be the SELECTED model. A brain silently running its hardcoded
        # DEFAULT_MODEL — user picks GPT-5.5 but Opus runs, while the UI still
        # shows GPT-5.5 — is the exact "wrong model used, shown right" defect.
        # Every brain plugin stores its resolved model as ``self._model``; if a
        # requested model did NOT survive construction, log it LOUDLY so the drift
        # is visible instead of silent. Provider-agnostic (no provider/model
        # special-case); the chosen-model contract tests lock this in.
        if model:
            actual = getattr(inst, "_model", None)
            if actual is not None and actual != model:
                log.error(
                    "MODEL DRIFT %s: requested model %r but the constructed brain "
                    "runs %r — the SELECTED model is not the one being used. This "
                    "is a bug (a silent DEFAULT_MODEL fallback), not expected.",
                    name, model, actual,
                )
        self._brain_cache[key] = inst
        return inst

    @property
    def active_provider(self) -> str:
        return self._active_name

    # ------------------------------------------------------------------
    # Dispatcher builder
    # ------------------------------------------------------------------

    def _build_dispatcher(
        self,
        brain: Brain,
        *,
        tools_override: dict[str, Tool] | None = None,
        max_turns: int | None = None,
        deadline_s: float | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        delegated_voice: bool = False,
        tool_context: dict[str, Any] | None = None,
        loop_control: Any = None,
        own_tools: Iterable[str] = (),
        direct_tools: frozenset[str] | None = None,
    ) -> BrainDispatcher:
        """Builds the dispatcher with an optional tool override.

        Bug fix 2026-05-01 (voice session 2026-04-30 22:38): when smalltalk is
        clearly identified, ``tools_override={}`` is set — the LLM then has no
        tools in its toolbox and cannot be tempted to hallucinate
        ``spawn_worker``. ``None`` (default) = full tool visibility.

        ``max_turns`` / ``deadline_s`` (2026-07-14): per-turn loop bounds for
        delegated realtime voice turns — see ``_DELEGATE_MAX_TURNS`` /
        ``_DELEGATE_DEADLINE_S``. ``None`` keeps the dispatcher defaults.

        ``reasoning_effort`` (2026-07-17): forwarded onto every BrainRequest
        of the turn. Delegated realtime voice turns pass ``"none"`` so a
        thinking-by-default model never burns seconds of internal reasoning
        per tool-loop round — see ``_DELEGATE_REASONING_EFFORT``.

        ``tool_context`` (2026-08-24): extra keys merged into every tool's
        ``ExecutionContext.config`` for this dispatcher's turns — scheduled
        task turns pass ``{"delivery": "written"}`` so search results stop
        asking for a spoken two-liner. ``None`` = no extra keys.

        ``delegated_voice`` (2026-07-17): appends the static speed contract
        (``_DELEGATE_VOICE_DIRECTIVE``) — batch lookups, no repeats, answer
        as soon as evidence suffices — to the system prompt of delegated
        voice turns only, so classic chat prompts stay byte-identical.

        The tool surface is then split into what the model is shown and
        what stays callable behind ``find_tools`` (``_shortlist_tools``);
        the turn's message log counts toward the budget — a delegated turn's
        from ``_TURN_HISTORY_OVERRIDE``, a classic turn's from the live
        ``self._history`` (the same two sources ``_cu_context_lines`` reads).

        ``own_tools`` / ``direct_tools``: the caller's own hands, always
        shown, and — for a caller whose role names the tools it works with —
        the only others that are (``TurnOverride.tools_direct``).
        """
        tools = tools_override if tools_override is not None else self._tools
        system_prompt = self._build_system_prompt()
        history = _TURN_HISTORY_OVERRIDE.get()
        if history is None:
            history = tuple(getattr(self, "_history", None) or ())
        tools, deferred = self._shortlist_tools(
            tools,
            brain,
            system_prompt=system_prompt,
            history=history,
            own_tools=own_tools,
            direct_tools=direct_tools,
        )
        # Per-plugin usage guidance for whichever plugins are active this turn
        # (the "MCP + thin skill" reliability layer). Appended last so it sits
        # closest to the turn; only present when a plugin tool is in scope.
        # Cards only for the tools the model is shown: guidance for a tool it
        # cannot see spends the window on nothing.
        cards = self._plugin_usage_cards_block(
            {name: tool for name, tool in tools.items() if name not in deferred}
            if deferred
            else tools
        )
        if cards:
            system_prompt = f"{system_prompt}\n\n{cards}"
        if delegated_voice:
            system_prompt = f"{system_prompt}\n\n{_DELEGATE_VOICE_DIRECTIVE}"
        kwargs: dict[str, Any] = {}
        if max_turns is not None:
            kwargs["max_turns"] = max_turns
        return BrainDispatcher(
            brain,
            tools=tools,
            executor=self._tool_executor,
            system_prompt=system_prompt,
            max_tokens=self._config.brain.max_tokens,
            deadline_s=deadline_s,
            reasoning_effort=reasoning_effort,
            tool_context=tool_context,
            loop_control=loop_control,
            deferred_tools=deferred,
            **kwargs,
        )

    def _apply_turn_override_tools(
        self, tools: dict[str, Tool] | None, override: TurnOverride
    ) -> dict[str, Tool]:
        """The turn's tool surface plus the override's extra hands, then its filter."""
        base: dict[str, Tool] = dict(tools) if tools is not None else dict(self._tools)
        base.update(override.tools_extra)
        if override.tool_filter is not None:
            base = override.tool_filter(base)
        return base

    @staticmethod
    def _override_dispatch_kwargs(override: TurnOverride | None) -> dict[str, Any]:
        """Dispatcher kwargs for a caller-picked turn; ``{}`` for a classic one."""
        if override is None:
            return {}
        kwargs: dict[str, Any] = {}
        if override.reasoning_effort is not None:
            kwargs["reasoning_effort"] = override.reasoning_effort
        if override.tool_context:
            kwargs["tool_context"] = dict(override.tool_context)
        if override.max_turns is not None:
            kwargs["max_turns"] = override.max_turns
        if override.loop_control is not None:
            kwargs["loop_control"] = override.loop_control
        if override.tools_extra:
            kwargs["own_tools"] = tuple(override.tools_extra)
        if override.tools_direct is not None:
            kwargs["direct_tools"] = override.tools_direct
        return kwargs

    async def render_surface_prompt(
        self, *, user_text: str, lead: bool = False
    ) -> tuple[str, str]:
        """(system prompt, turn context) for an external agent that should BE Jarvis.

        A subscription CLI seat on the typed chat runs its own loop, but the
        head it runs with is this one (``lead``: the lead conversation, which also gets
        the lead doctrine and the ecosystem map): the same layers ``_build_system_prompt``
        stacks for a voice turn (name, soul, persona, the assistant file, the
        user's profile, people, contacts, the identity card, core memory, the
        skills section, the tool-routing rules), the wiki context this turn's
        text pulls in, and the per-turn context (date). Read-only:
        nothing is stored on the manager, so a voice turn running alongside
        sees no trace of it.
        """
        # An empty turn state: this prompt never carries a voice turn's
        # evidence directive, recall or provider identity.
        from dodaios.brain.lead_doctrine import LEAD_TURN

        empty_token = _BRAIN_TURN_STATE.set(_BrainTurnState(self))
        lead_token = LEAD_TURN.set(lead)
        try:
            base = self._build_system_prompt()
        finally:
            LEAD_TURN.reset(lead_token)
            _BRAIN_TURN_STATE.reset(empty_token)
        prompt = base
        recalled = await self._vault_recall(user_text)
        if recalled:
            prompt = f"{base}\n\n{recalled}"
        try:
            turn_context = self._build_turn_context()
        except Exception:  # noqa: BLE001 — the context block is a nicety
            log.debug("render_surface_prompt: turn context skipped", exc_info=True)
            turn_context = ""
        return prompt, turn_context

    def _build_tool_ack_emitter(
        self, user_text: str
    ) -> Callable[[str, dict[str, Any]], Awaitable[None]] | None:
        """Grounded per-tool ack emitter for the voice turn (perceived latency).

        Returns an async callback the tool-use loop awaits ONCE, the moment the
        router brain has actually SELECTED a tool call — so the otherwise-silent
        tool-execution + readback window speaks a short interim line. This
        bridges the wait on slow turns (e.g. a cold email/calendar fetch, a
        multi-tool research) where the persona forbids any spoken preamble
        before the tool and round-2 has not started yet.

        Contextual Interim Voice (2026-07-06 v2 spec): when the manager's
        ``ReadbackComposer`` has a live flash provider, the spoken text is
        COMPOSED for this exact turn (user request + concrete action) instead
        of drawn from a phrase pool — the pool line remains only as the
        instant deterministic fallback (keyless install, breaker open,
        timeout, rejected output). Composition + publish run fire-and-forget
        so the tool-use loop is never delayed; ``[ack_brain].contextual_interim
        = false`` is the kill switch back to pools-only.

        Returns ``None`` when there is no bus, the feature is off
        (``[ack_brain].grounded_tool_ack = false``), or the utterance is a
        Voice-Control command (the action itself is the confirmation).

        GROUNDED, not speculative: unlike the retired Flash-Brain preamble it
        fires only after a real tool decision, never on suspicion. The fallback
        words are rendered by ``generate_ack`` (skip-list-aware, so passive
        reads / low-latency UI events stay silent) and the language is
        re-resolved and re-scrubbed authoritatively at the speech layer, so the
        reply-language pin and conversation stickiness still win there.
        Publishing with ``source_layer="brain.router.ack"`` keeps every
        pipeline gate on this source: the necessity commit-grace (speak only if
        the brain is STILL busy), duplicate-wording dedup, the rate-limit
        backstop, and the legacy one-ack-per-turn drop while the Flash-Brain
        preamble is active.
        """
        if self._bus is None:
            return None
        ack_cfg = getattr(self._config, "ack_brain", None) if self._config else None
        if not getattr(ack_cfg, "grounded_tool_ack", True):
            return None
        from .ack_generator import (
            describe_tool_action,
            generate_ack,
            is_voice_control_utterance,
        )

        if is_voice_control_utterance(user_text):
            return None
        bus = self._bus
        language = _turn_phrase_language(self, user_text)
        # Fire at most once per turn even if the provider chain retries the
        # tool-use loop (a provider that emits tool_calls then errors would
        # otherwise re-announce on the fallback provider's re-run).
        fired = False
        # Cross-utterance cooldown (2026-07-06 interim-ack redesign): the
        # per-turn guard above cannot stop the NEXT utterance from acking
        # again seconds later — forensically that produced the same spoken
        # ack three times in one session. Checked at emit time (tool
        # selection can lag turn start by seconds) against the manager-wide
        # timestamp of the last PUBLISHED grounded ack.
        min_gap_s = float(getattr(ack_cfg, "grounded_ack_min_gap_s", 20) or 0)

        async def emit(tool_name: str, tool_args: dict[str, Any]) -> None:
            nonlocal fired
            if fired:
                return
            if min_gap_s > 0:
                last = getattr(self, "_last_grounded_ack_monotonic", None)
                if last is not None and (time.monotonic() - last) < min_gap_s:
                    log.debug(
                        "Grounded tool-ack suppressed — last ack %.1fs ago "
                        "(min gap %.0fs)", time.monotonic() - last, min_gap_s,
                    )
                    return
            canned_text = generate_ack(tool_name, tool_args, language=language)
            if canned_text is None:  # skip-list tool (passive read / UI micro-event)
                return
            fired = True
            self._last_grounded_ack_monotonic = time.monotonic()

            async def _publish(text: str) -> None:
                await bus.publish(
                    AnnouncementRequested(
                        text=text,
                        priority="normal",
                        language=language,
                        kind="preamble",
                        source_layer="brain.router.ack",
                    )
                )

            composer = getattr(self, "_readback_composer", None)
            contextual = bool(getattr(ack_cfg, "contextual_interim", True))
            if not (contextual and bool(getattr(composer, "has_llm", False))):
                # Deterministic path (keyless install / kill switch): publish
                # inline — sub-millisecond, the historical contract.
                await _publish(canned_text)
                return

            action = describe_tool_action(tool_name, tool_args)

            async def _compose_and_publish() -> None:
                # Runs detached: composition must never delay tool execution
                # (the loop already moved on) and must never raise. The
                # pipeline's commit-grace re-checks necessity AFTER this
                # composition lands, so the flash latency costs nothing.
                text = canned_text
                try:
                    from dodaios.voice.contextual_readback import (  # noqa: PLC0415
                        render_readback,
                    )
                    text = await render_readback(
                        composer,
                        instruction=(
                            f"You have JUST started {action} to answer the "
                            "user's request and it is taking a moment. In one "
                            "short sentence, tell the user what you are doing "
                            "RIGHT NOW, tied to their actual topic — an "
                            "in-progress bridge line, never a result."
                        ),
                        language=language,
                        canned=lambda: canned_text,
                        facts={
                            "user_request": user_text[:200],
                            "current_action": action,
                        },
                        in_progress=True,
                        latency_budget_ms=1200,
                    )
                except Exception as exc:  # noqa: BLE001 — fall back to the pool line
                    log.debug("Contextual interim compose failed: %s", exc)
                try:
                    await _publish(text)
                except Exception as exc:  # noqa: BLE001 — a publish fault must die here
                    log.warning("Interim ack publish failed: %s", exc)

            tasks = getattr(self, "_interim_ack_tasks", None)
            if tasks is None:
                tasks = set()
                self._interim_ack_tasks = tasks
            task = asyncio.create_task(_compose_and_publish())
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        return emit


    # ------------------------------------------------------------------
    # Explicit switching
    # ------------------------------------------------------------------

    async def switch(self, provider_name: str, *, persist: bool = False) -> None:
        """Switches the active provider.

        Even switching to the ALREADY active provider has an effect: it acts
        as the reset button for session caches (dead-list, brain-cache,
        rate-tracker). Users typically click "Set as active" in the UI
        immediately after setting an API key — this should bring the fresh key
        into the chain right away rather than being a no-op.

        Args:
            provider_name: Provider ID (entry-point name) or voice alias.
            persist: If True, the selection is written to jarvis.toml [brain]
                primary and survives a restart.
        """
        canonical = PROVIDER_ALIASES.get(provider_name.lower().strip(), provider_name)
        async with self._lock:
            if canonical in SUBAGENT_ONLY_BRAIN_PROVIDERS:
                log.warning(
                    "Brain provider %r is subagent-only; ignoring main-brain switch.",
                    canonical,
                )
                self.last_persist_ok = False
                return
            if canonical == self._active_name:
                # Re-activation of the already active provider — reset caches
                # so a newly set key takes effect on the next turn (otherwise
                # the provider stays in _dead_providers).
                self._reset_provider_caches()
                self.last_persist_ok = (
                    self._persist_primary(canonical) if persist else False
                )
                return
            try:
                self._get_brain(canonical, self._fast_model(canonical))
            except KeyError:
                log.error("Unbekannter Provider: %s", canonical)
                self.last_persist_ok = False
                return
            previous = self._active_name
            self._active_name = canonical
            self._switched_to = canonical
            # Keep deep_brain following the active provider on a runtime switch
            # when there is no explicit cross-provider deep split (deep_brain
            # tracked the previous active, or was never configured) — so switching
            # to a frontier provider leads ALL intents, not just fast ones (mirror
            # of the from_tier_config override rule; "Grok for everything" mandate
            # 2026-06-20). A None/"" deep_brain must follow too, not stay stranded.
            if not self._config.brain.deep_brain or self._config.brain.deep_brain == previous:
                self._config.brain.deep_brain = canonical
            self._reset_provider_caches()
            self.last_persist_ok = (
                self._persist_primary(canonical) if persist else False
            )
            await self._bus.publish(
                BrainProviderSwitched(from_provider=previous, to_provider=canonical)
            )

    def _reset_provider_caches(self) -> None:
        """Clears session state that would block a freshly set key."""
        self._dead_providers.clear()
        self._dead_provider_models.clear()
        self._brain_cache.clear()
        self._rate_tracker.clear()

    def reactivate_provider(self, provider: str) -> None:
        """Lifts the session-level deactivation of a provider.

        Called by the ``SecretConfigured`` event handler when the user sets a
        key via Sidebar → API Keys. Effects:
          1. Provider leaves ``_dead_providers`` → returns to the chain.
          2. Its brain cache entry is discarded so the next ``_get_brain``
             call instantiates a fresh instance with the new key.
          3. Any active rate-limit cooldown is also cleared — the user reset
             clearly signals "I want to use this now".

        Idempotent: calling twice is allowed and is a no-op with a clean cache.
        """
        was_dead = provider in self._dead_providers
        self._dead_providers.discard(provider)
        self._dead_provider_models = {
            k for k in self._dead_provider_models if k[0] != provider
        }
        keys_to_drop = [k for k in self._brain_cache
                        if k[0] == provider or str(k[0]).startswith(provider + "@")]
        for k in keys_to_drop:
            self._brain_cache.pop(k, None)
        self._rate_tracker.clear(provider)
        if was_dead or keys_to_drop:
            log.info(
                "Provider '%s' reactivated (dead=%s, brain_cache_dropped=%d)",
                provider, was_dead, len(keys_to_drop),
            )

    def _active_has_usable_credential(self) -> bool:
        """Whether the currently active brain provider has a usable credential.

        True iff an API key is present in any of the active provider's secret
        slots, or a keyless provider is rescued by a connected OAuth login
        (mirrors the pre-boot key check in ``from_tier_config`` so the two stay
        consistent). Used by the ``SecretConfigured`` handler to decide whether a
        fresh-install ``brain.primary`` default — which the downloader has no key
        for — should yield to the provider the user just configured.
        """
        from dodaios.core import config as _cfg_mod
        from dodaios.core.config import PROVIDER_SECRET_CANDIDATES

        active = self._active_name
        specs = PROVIDER_SECRET_CANDIDATES.get(active)
        if specs:
            try:
                if _cfg_mod.get_secret_any(specs):
                    return True
            except Exception:  # noqa: BLE001 — an unreadable keyring counts as "no key"
                pass
        return _keyless_provider_is_rescued_by_oauth(active)

    def apply_provider_model(self, provider: str, model: str) -> bool:
        """Live-apply a model override for a brain provider (no restart).

        The model picker in the API-Keys view persists the choice to jarvis.toml
        AND calls this so the running brain uses the new model on the next turn.
        The manager builds its config independently of ``app.state.config``, so
        mutating that route-level config would NOT reach the brain — this method
        updates the manager's OWN ``self._config`` and drops cached brain
        instances for the provider so the next ``_get_brain`` rebuilds with the
        new model.

        An empty string resets the override to ``None`` (the provider then falls
        back to its frontier default via ``_fast_model``).

        Returns ``True`` iff ``provider`` is the currently active brain — i.e.
        the change takes effect immediately. For an inactive provider the
        override is stored and applies as soon as the user switches to it.
        """
        from dodaios.core.config import BrainProviderConfig

        canonical = PROVIDER_ALIASES.get(provider.lower().strip(), provider)
        new_model = model.strip() or None
        providers = self._config.brain.providers
        pc = providers.get(canonical)
        if pc is None:
            providers[canonical] = BrainProviderConfig(model=new_model)
        else:
            try:
                pc.model = new_model
            except Exception:  # noqa: BLE001 — frozen/validation: rebuild the block.
                data = pc.model_dump() if hasattr(pc, "model_dump") else {}
                data["model"] = new_model
                providers[canonical] = BrainProviderConfig(**data)

        # Drop cached instances for this provider so the new model is used; lift
        # any session-level deactivation (mirrors ``reactivate_provider``). The
        # scoped instances of a per-turn override ("<name>@<scope>") go too.
        for key in [
            k
            for k in self._brain_cache
            if k[0] == canonical or str(k[0]).startswith(canonical + "@")
        ]:
            self._brain_cache.pop(key, None)
        self._dead_providers.discard(canonical)
        self._dead_provider_models = {
            k for k in self._dead_provider_models if k[0] != canonical
        }
        return canonical == self._active_name

    @staticmethod
    def _persist_primary(name: str) -> bool:
        """Persist ``brain.primary`` to disk (all three layers via config_writer).

        Returns ``True`` iff the write actually succeeded, ``False`` otherwise.
        A failure is logged loudly (anti-silent-drop) so the caller can report
        the real disk outcome up to the UI instead of echoing the request flag.
        """
        # Lazy import: config_writer needs tomlkit (optional dep in the wizard path).
        try:
            from dodaios.core import config_writer

            config_writer.set_brain_primary(name)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to persist brain.primary=%r: %s", name, exc)
            return False

    def _detect_switch_intent(self, text: str) -> str | None:
        """Strict gate-based detector — no more substring matching.

        Delegates to `voice_command_gate.match_voice_command`, which only
        returns a match for unambiguous patterns like "wechsel auf gemini".
        Harmless sentences like "ich gehe auf meinem Weg" no longer match.
        """
        match = match_voice_command(text)
        if match is None or match.kind != "provider_switch":
            return None
        return match.target

    def _detect_language_switch_intent(self, text: str) -> str | None:
        """Strict gate-based reply-language switch detector.

        Delegates to ``voice_command_gate.match_voice_command`` and returns the
        target code (de/en/es/auto) ONLY for an unambiguous language command
        like "stell auf Englisch um". A harmless mention ("wie heißt das auf
        Englisch?") returns None and reaches the brain normally.
        """
        match = match_voice_command(text)
        if match is None or match.kind != "language_switch":
            return None
        return match.target

    def _apply_reply_language_switch(self, code: str) -> str:
        """Execute a recognised reply-language switch deterministically.

        Mirrors the canonical ``PUT /api/settings/reply-language`` path (live
        set + persist) but is reached in ``generate()`` BEFORE the force-spawn
        heuristic, so a trivial config change never becomes a worker mission
        (2026-06-22 forensic: "stell auf Englisch um" was dispatched as a worker
        and failed, harness down). It runs without the LLM, so it works no
        matter the active provider's tool-calling capability. Returns the spoken
        confirmation, or "" for an unknown code (caller falls through).
        """
        try:
            self.set_reply_language(code)  # live; ValueError on unknown code
        except ValueError:
            return ""
        lang = self._reply_language
        # Best-effort in-memory cfg agreement (a frozen model is not an error).
        try:
            self._config.brain.reply_language = lang  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log.debug("in-memory cfg.brain.reply_language update skipped: %s", exc)
        # Persist as boot default — best-effort: a read-only / locked jarvis.toml
        # must not break the live switch that already applied.
        persisted = True
        try:
            from dodaios.core import config_writer

            config_writer.set_reply_language(lang)
        except Exception as exc:  # noqa: BLE001
            persisted = False
            log.warning(
                "reply-language persist failed (live switch still applied): %s", exc
            )
        log.info(
            "reply-language switched to %r via deterministic voice gate (persisted=%s)",
            lang, persisted,
        )
        if persisted:
            if lang == "auto":
                return i18n_catalog.t("brain.lang_switch_confirm_auto", self._resolve_turn_lang())
            return i18n_catalog.pick(_LANG_SWITCH_CONFIRM, lang)
        return i18n_catalog.pick(_LANG_SWITCH_CONFIRM_SESSION, lang)

    def _detect_subagent_switch_intent(self, text: str) -> str | None:
        """Strict gate-based sub-agent (Heavy-Task worker) provider switch.

        Delegates to ``voice_command_gate.match_voice_command``; returns the
        spoken provider word ONLY for a sub-agent-qualified command like
        "wechsle den Sub-Agent-Provider auf OpenAI". A bare "switch to gemini"
        is a main-brain switch (kind=provider_switch) and returns None here.
        """
        match = match_voice_command(text)
        if match is None or match.kind != "subagent_switch":
            return None
        return match.target

    async def _apply_subagent_provider_switch(self, word: str) -> str:
        """Execute a recognised sub-agent provider switch through the ONE
        validated path (app_control.apply_provider_switch) instead of persisting
        blindly. Maps the spoken word to a canonical slug, runs the same
        credential validation the REST endpoint uses (Codex/Antigravity OAuth,
        key presence), persists across all 3 layers (TOML + config-soll pin + ENV)
        so the drift-guard cannot revert it, and renders an HONEST readback: the
        real target on success, a named reason on failure, never a false "done".
        Returns "" for an unknown word (caller falls through to the brain).
        Forensic 2026-06-27: the old blind-persist path said "Erledigt" for an
        unconnected provider and even when the persist threw.
        """
        canonical = _SUBAGENT_VOICE_TO_CANONICAL.get(word.strip().lower())
        if canonical is None:
            return ""
        from dodaios.brain.app_control import apply_provider_switch, resolve_running_cfg

        try:
            result = await apply_provider_switch(
                "subagent", canonical, cfg=resolve_running_cfg()
            )
        except Exception as exc:  # noqa: BLE001 — never crash the turn
            log.warning("sub-agent voice switch failed: %s", exc)
            result = {"ok": False, "error_kind": "other", "error": str(exc)}

        lang = self._resolve_turn_lang()
        if result.get("ok"):
            new = str(result.get("new_provider") or canonical)
            display = _SUBAGENT_DISPLAY.get(new, new)
            log.info("sub-agent provider switched to %r via deterministic voice gate", new)
            template = i18n_catalog.pick(_SUBAGENT_SWITCH_CONFIRM, lang)
            return template.format(p=display)
        display = _SUBAGENT_DISPLAY.get(canonical, canonical)
        return _subagent_switch_failure_phrase(result, display, lang)

    async def _apply_main_provider_switch(self, word: str) -> str:
        """Deterministic main-brain provider switch with an HONEST readback.

        Mirrors ``_apply_subagent_provider_switch``: routes through the one
        validated ``apply_provider_switch("brain", …)`` (credential / catalog /
        subagent-only checks + live-apply) and speaks the CHECKED result. The
        old path (``await self.switch(word); return ""``) was silent even on a
        refused switch (audit 2026-06-27). Returns ``""`` for an unmappable word
        so the caller falls through to the brain.
        """
        canonical = PROVIDER_ALIASES.get(word.strip().lower())
        if canonical is None:
            return ""
        from dodaios.brain.app_control import (
            apply_provider_switch,
            get_spec,
            resolve_running_cfg,
        )
        try:
            result = await apply_provider_switch("brain", canonical, cfg=resolve_running_cfg())
        except Exception as exc:  # noqa: BLE001
            log.warning("main-brain voice switch failed: %s", exc)
            result = {"ok": False, "error_kind": "other", "error": str(exc)}
        lang = self._resolve_turn_lang()
        spec = get_spec(str(result.get("new_provider") or canonical))
        display = getattr(spec, "label", None) or canonical
        if result.get("ok"):
            log.info("main-brain provider switched to %r via deterministic voice gate", canonical)
            template = i18n_catalog.pick(_PROVIDER_SWITCH_CONFIRM, lang)
            return template.format(p=display)
        return _provider_switch_failure_phrase(result, display, lang)

    def _detect_cancel_intent(self, text: str) -> bool:
        """True when the user wants to cancel a running Jarvis-Agent task."""
        match = match_voice_command(text)
        return match is not None and match.kind == "cancel"

    def _detect_depth_override(self, text: str) -> str | None:
        """Detects 'denk gründlich/schnell' → sticky override to deep/fast.

        Uses the VoiceCommandGate for consistent pattern lists.
        """
        match = match_voice_command(text)
        if match is None:
            return None
        if match.kind == "depth_deep":
            return "deep"
        if match.kind == "depth_fast":
            return "fast"
        return None

    # ------------------------------------------------------------------
    # Force-Spawn-Heuristik (Persona-Mandat Phase 3)
    # ------------------------------------------------------------------

    def _get_routing_patterns(
        self,
    ) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
        """Lazily compiles the three force-spawn regexes from BrainRoutingConfig."""
        if self._routing_patterns is None:
            cfg = self._config.brain.routing
            self._routing_patterns = (
                _build_verb_pattern(list(cfg.spawn_verbs)),
                _build_marker_pattern(list(cfg.external_system_markers)),
                _build_smalltalk_pattern(list(cfg.smalltalk_allowlist)),
            )
        return self._routing_patterns

    def _get_heavy_research_patterns(
        self,
    ) -> tuple[re.Pattern[str], re.Pattern[str]]:
        """Lazily compile the (verb, heaviness-marker) regexes for heavy-research
        force-spawn from BrainRoutingConfig. Verbs use ``\\b<stem>\\w*\\b`` so
        conjugations match; markers are word/phrase boundaries."""
        if self._heavy_research_patterns is None:
            cfg = self._config.brain.routing
            verbs = list(getattr(cfg, "heavy_research_verbs", []) or [])
            markers = list(getattr(cfg, "heavy_research_markers", []) or [])
            self._heavy_research_patterns = (
                _build_verb_pattern(verbs),
                _build_marker_pattern(markers),
            )
        return self._heavy_research_patterns

    def _is_heavy_research(self, user_text: str) -> bool:
        """True iff the utterance is HEAVY multi-step research/analysis that must
        be OFFLOADED to a background mission, not answered inline on the deep
        brain (where it blows the ~20 s voice budget and is beheaded — live bug
        2026-06-14, a long-haul trip-research turn).

        Conjunctive gate (precision over recall): a research/analysis VERB must
        be present AND a heaviness signal — a horizon/multi-step/requirements
        marker, OR >= ``heavy_research_min_verbs_multiclause`` verb matches
        (multi-clause), OR length >= ``heavy_research_min_chars`` with a verb.
        Length alone never spawns, so a quick "recherchier das mal kurz" stays
        inline. Pure regex (AP-11 safe, cross-platform).

        RETIRED from the spawn decision 2026-07-21 (strict mode is
        explicit-only — ``_should_force_spawn`` no longer consults this
        detector). Kept as a classifier for telemetry/tests and a possible
        future opt-in.
        """
        cfg = self._config.brain.routing
        if not getattr(cfg, "heavy_research_enabled", True):
            return False
        t = (user_text or "").strip()
        if not t:
            return False
        verb_re, marker_re = self._get_heavy_research_patterns()
        verbs_found = verb_re.findall(t)
        if not verbs_found:
            return False  # (A) no research/analysis verb → never heavy research
        min_verbs = max(
            2, int(getattr(cfg, "heavy_research_min_verbs_multiclause", 2))
        )
        if len(verbs_found) >= min_verbs:
            return True  # multi-clause "recherchier X und analysier Y"
        if marker_re.search(t):
            return True  # verb + horizon / multi-step / requirements marker
        min_chars = int(getattr(cfg, "heavy_research_min_chars", 120))
        return len(t) >= min_chars  # verb + sheer length

    def _get_force_spawn_pattern(self) -> re.Pattern[str]:
        """Compile the strict-mode trigger-phrase regex (User-Mandate 2026-05-14).

        Multi-word phrases are matched literal-substring, single-word
        markers with `\\b` boundaries so 'spawn' matches 'spawn' /
        'spawne' / 'spawnen' but not arbitrary substrings.
        """
        if self._force_spawn_pattern is None:
            phrases = list(self._config.brain.routing.force_spawn_phrases)
            if not phrases:
                self._force_spawn_pattern = _NEVER_MATCH_RE
            else:
                parts = [re.escape(p) for p in phrases]
                # Each part is a literal substring; boundary handling
                # mirrors `_build_smalltalk_pattern` so multi-word
                # phrases like "deep dive" match without requiring word
                # boundaries inside.
                self._force_spawn_pattern = re.compile(
                    r"(?:^|\b)(?:" + "|".join(parts) + r")(?:\b|$)",
                    re.IGNORECASE,
                )
        return self._force_spawn_pattern

    def set_mission_command_handlers(
        self,
        *,
        status_fn: Callable[[str | None], Awaitable[str]] | None,
        cancel_fn: Callable[[str | None], Awaitable[str]] | None,
    ) -> None:
        """Wires the status/cancel handlers for Jarvis-Agent mission reads.

        Called by bootstrap (e.g. ``dodaios/missions/init.py`` or server
        startup) once the MissionManager is ready.

        AD-12 (status read via voice without spawn): when ``status_fn`` is
        set, the ``generate()`` path deterministically calls
        ``status_fn(mission_id)`` on a detected status phrase instead of
        asking the LLM or triggering a new Jarvis-Agent spawn.

        AP-OC5: pattern-match-first discipline — when no handlers are
        registered (e.g. tests, headless mode), the code falls back to the
        normal force-spawn/tool-use path (no crash).

        Args:
            status_fn: ``async (mission_id: str | None) -> str`` — returns a
                TTS-safe status announcement. ``mission_id=None`` means
                "summarise all active missions".
            cancel_fn: ``async (mission_id: str | None) -> str`` — cancels
                mission(s) and returns a confirmation. ``mission_id=None``
                means "cancel all active Jarvis-Agent missions".
        """
        self._jarvis_agent_status_fn = status_fn
        self._jarvis_agent_cancel_fn = cancel_fn

    def own_message_recorder(self, recorder: Any, bus: Any) -> None:
        """Take ownership of the recorder the factory attached to ``bus``."""
        self._message_recorder = (recorder, bus)

    async def aclose(self) -> None:
        """Release what this brain owns: its message recorder and its store.

        A brain built for one browser voice session used to keep both forever:
        the recorder stayed on the shared bus (every later answer was recorded
        once more per past session) and the store's aiosqlite connection, which
        runs on a non-daemon thread, kept the process from exiting at shutdown.
        Idempotent; never raises.
        """
        owned = getattr(self, "_message_recorder", None)
        self._message_recorder = None
        if owned is not None:
            recorder, bus = owned
            try:
                recorder.detach(bus)
            except Exception:  # noqa: BLE001 — closing must never raise
                log.debug("message recorder detach failed", exc_info=True)
        recall = getattr(self, "_recall", None)
        if recall is not None and callable(getattr(recall, "close", None)):
            try:
                await recall.close()
            except Exception:  # noqa: BLE001 — closing must never raise
                log.debug("recall store close failed", exc_info=True)

    def _live_tool_names(self) -> tuple[str, ...]:
        """Names of every tool attached RIGHT NOW — the honest-refusal evidence.

        Read fresh on every call and never cached: ``refresh_tools()`` replaces
        ``self._tools`` wholesale each time a CLI or MCP server connects, so a
        snapshot taken earlier in the turn would be exactly the stale picture
        the refusals are being fixed for (GT-16). ``_local_action_tools`` is
        included because the deterministic fast path can serve a request just
        as well as the brain surface can. The ``getattr`` guards tolerate
        __init__-bypassing tests, like the other readers of ``_tools``.
        """
        tools = dict(getattr(self, "_tools", None) or {})
        tools.update(getattr(self, "_local_action_tools", None) or {})
        override = _TURN_OVERRIDE.get()
        if override is not None:
            tools = self._apply_turn_override_tools(tools, override)
        return tuple(sorted(tools))

    def _check_unsupported_intent(self, user_text: str) -> str | None:
        """Agent-C capability gate: return a deterministic refusal when the
        utterance has an action intent that no registered capability covers.

        Returns ``None`` when:
        - The CapabilityRegistry module is not yet deployed (graceful no-op).
        - The utterance is smalltalk / Q&A (no action intent detected).
        - A registered capability resolves the intent.

        Returns a short, TTS-safe refusal string when:
        - ``registry.has_action_intent(text)`` is True AND
        - ``registry.resolve_intent(text)`` is None AND
        - ``_is_smalltalk(text)`` is False.

        No LLM call is made here — pure regex + registry lookup (AP-11).
        """
        try:
            from dodaios.core.capabilities import get_registry  # type: ignore[import]
        except Exception:  # noqa: BLE001 — module not yet deployed
            return None

        try:
            reg = get_registry()
            t = (user_text or "").strip()
            if not t:
                return None
            if self._is_smalltalk(t):
                return None
            # Empty/unseeded registry → step aside (fail-safe). has_action_intent
            # matches the STATIC universal verb catalogue (seed-independent), so
            # without this guard an unseeded registry refuses EVERY action
            # utterance (resolve_intent is always None when nothing is
            # registered) and pre-empts the force-spawn path. Mirrors the
            # populated-guard in local_action_gate.match_local_action. Defense in
            # depth behind the boot seed in brain/factory.build_default_brain —
            # live bug 2026-05-25 ("Kannst du einen Subagent spawnen").
            if not getattr(reg, "all", lambda: ())():
                return None
            # Desktop-control commands (compound open-and-operate, GUI verbs)
            # are never "unsupported" — computer-use is the universal GUI
            # integration and the fast path routes them there. Defense in depth
            # so a sparse/older registry can't pre-empt that with the canned
            # refusal (live bug 2026-05-25: "oeffne WhatsApp und schreib").
            if _looks_like_desktop_control(_gate_normalize(t)):
                return None
            # 2026-06-01: the sub-agent is the universal capability for generic
            # work (analyse/build/fix/code/research/git). Only a SPECIFIC
            # external integration the worker cannot satisfy (mail/calendar/
            # Spotify/social/delivery) is genuinely "unsupported". Everything
            # else falls through to the force-spawn path so a sub-agent task is
            # delegated natively instead of refused with "kann ich noch nicht"  # i18n-allow
            # (live forensic 2026-06-01: a sub-agent task was refused, then only
            # spawned once the user said "Subagent" explicitly).
            if not requires_external_integration(t):
                return None
            if reg.has_action_intent(t) and reg.resolve_intent(t) is None:
                # GT-16: `resolve_intent` speaks for the registry, and the
                # registry lags the tool surface — a plugin/CLI/MCP server
                # connected mid-session is callable while the registry still
                # knows nothing. Ask the LIVE tools before speaking a refusal;
                # a tool named after the requested system means the capability
                # is there and the turn must proceed. A wrong tool call is
                # recoverable, a false "I can't do that" is the bug.
                wanted = external_integration_terms(t)
                if live_surface_covers(wanted, self._live_tool_names()):
                    log.info(
                        "Unsupported-intent refusal stood down: a tool on the "
                        "live surface covers %s — proceeding instead of "
                        "refusing (registry had not caught up).",
                        ", ".join(wanted) or "the request",
                    )
                    return None
                # Detect user language from text heuristic (simple: if latin
                # chars + german umlaut present → DE, else EN).
                _de_markers = re.search(r"[äöüÄÖÜß]|(?:bitte|kannst|schick|trag|sende)", t, re.I)
                if _de_markers:
                    return (
                        "Das kann ich noch nicht. Mir fehlt dafür ein Werkzeug — "
                        "wenn du mir verrätst welches MCP oder welche Integration "
                        "zuständig wäre, kann ich's lernen."
                    )
                return (
                    "I can't do that yet. I don't have a registered tool for it. "
                    "Tell me which MCP or integration should handle it and I can learn."
                )
        except Exception:  # noqa: BLE001 — registry error must not crash generate()
            log.debug("_check_unsupported_intent: registry error", exc_info=True)
        return None

    def _run_evidence_gate(self, user_text: str) -> EvidenceVerdict:
        """Defensive wrapper around ``check_evidence_domain`` (AD-CLI4..8).

        Any infrastructure fault (missing config field, no shared CLI
        registry, capabilities module error) degrades to PASS — the gate adds
        behaviour, it must never block the voice path.
        """
        from dodaios.brain.evidence_gate import EvidenceVerdict, check_evidence_domain

        # AD-S3 (a matched skill IS the capability): a deterministically
        # skill-matched turn already proves an installed integration owns this
        # request — the gate must never overrule it. Live 2026-07-18 (voice
        # session 18:31): the paired-capability sync had not reached this
        # process' CapabilityRegistry, so a CONNECTED Google Calendar plugin
        # turn — freshly matched to plugin-google_calendar — still got the
        # deterministic "Ich habe aktuell keinen Kalenderzugriff" refusal  # i18n-allow: quoted live refusal under discussion
        # plus a CLI-setup detour. With the skill match as evidence the turn
        # proceeds; a genuinely dead plugin still fails honestly through its
        # tool's own "not connected" result.
        if getattr(self, "_skill_turn_match", None) is not None:
            log.info(
                "Evidence gate stood down: turn is owned by matched skill %s "
                "(AD-S3: a matched skill IS the capability)",
                getattr(self._skill_turn_match, "name", "?"),
            )
            return EvidenceVerdict(kind="pass")
        # A skill AUTHORING request names calendar / mail / music only as the
        # content of the skill to be written; the capability that serves the
        # turn is the create-skill tool, not those domains' connectors.
        if getattr(self, "_skill_meta_turn", ""):
            log.info(
                "Evidence gate stood down: skill %s request — the skill tools "
                "are the capability",
                self._skill_meta_turn,
            )
            return EvidenceVerdict(kind="pass")

        try:
            cfg = self._config.brain.evidence_domains
            if not cfg.enabled:
                return EvidenceVerdict(kind="pass")
            from dodaios.clis.capability_provider import (
                connected_domain_tool_map,
                merged_evidence_domains,
                refusal_hint,
            )
            from dodaios.clis.shared import get_active_registry
            from dodaios.core.capabilities import get_registry

            cli_reg = get_active_registry()
            domain_map = dict(
                connected_domain_tool_map(cli_reg) if cli_reg is not None else {}
            )

            def _hint(domain: str, lang: str) -> str:
                if cli_reg is None:
                    return ""
                return refusal_hint(domain, cli_reg, lang)

            return check_evidence_domain(
                user_text,
                enabled=cfg.enabled,
                domains=merged_evidence_domains(cli_reg, cfg.domains)
                if cli_reg is not None
                else cfg.domains,
                capability_registry=get_registry(),
                domain_tool_map=domain_map,
                refusal_hint_fn=_hint,
                # Read HERE, at decision time (GT-16): refresh_tools() swaps
                # self._tools out wholesale on every CLI/MCP connect, so any
                # earlier snapshot is the stale picture that made the gate
                # refuse a domain it could actually serve.
                live_tool_names=self._live_tool_names(),
                # The gate used to pick its refusal language by sniffing the
                # utterance, which ignored the user's pin and knew only two
                # languages — a Spanish user was told in English that there is
                # no calendar access (OF-15). Resolved here with the same
                # arguments the honesty phrase later uses, so one turn cannot
                # speak two languages.
                language=_turn_phrase_language(self, user_text),
            )
        except Exception:  # noqa: BLE001
            log.debug("evidence gate degraded to PASS", exc_info=True)
            return EvidenceVerdict(kind="pass")

    def _is_smalltalk(self, user_text: str) -> bool:
        """Pure smalltalk allowlist check — independent of spawn-verb logic.

        Bug fix 2026-05-01 (voice session 2026-04-30 22:38): the user said
        "es geht ab", the smalltalk allowlist did not match (phrase was
        missing), force-spawn did nothing, the LLM had full tool visibility
        and hallucinated a Jarvis-Agent spawn. Result: main Jarvis claimed to have
        started tests that it never started.

        Used in ``generate()`` to hide the spawn vehicles on clear smalltalk
        turns (``_smalltalk_tool_override``), so the LLM can no longer spawn.

        Greeting-prefix guard (live bug 2026-06-07, data/jarvis_desktop.log
        18:19:07): the user said "Hallo, öffne ihn für mich". The allowlist i18n-allow
        substring-matched the leading "Hallo", the turn was treated as
        smalltalk, the action tools were hidden, and the brain spoke the
        anti-silence refusal "Das kann ich gerade nicht ausführen — mir fehlt i18n-allow
        dafür das passende Werkzeug." A greeting/politeness prefix in front of a i18n-allow
        REAL command is NOT smalltalk: strip the leading greeting run and, if
        what remains is itself a non-smalltalk action request, classify the turn
        as a command (return False) so the tools stay visible and force-spawn
        can fire. Standalone smalltalk ("Hallo", "Hallo, wie geht's?") and
        greeting-less chit-chat ("was machst du") are unaffected.

        2026-06-10 23:13 recurrence (same log): "Hey, what's the weather like
        today?" — the original guard additionally required an ACTION verb in
        the remainder, so a greeting-prefixed information QUESTION stayed
        smalltalk, search_web was hidden, and the brain refused with the
        anti-silence fallback. The greeting prefix must never change the
        classification of the remainder: a non-smalltalk remainder keeps the
        turn a real request, action verb or not (exactly as the same words
        without the greeting would classify).
        """
        t = (user_text or "").strip()
        if not t:
            return False
        _, _, smalltalk_re = self._get_routing_patterns()
        if not smalltalk_re.search(t):
            return False
        stripped = _GREETING_PREFIX_RE.sub("", t).strip()
        if (
            stripped                                # something survives the greeting
            and stripped != t                       # a greeting prefix was removed
            and not smalltalk_re.search(stripped)   # the remainder isn't smalltalk too
        ):
            return False
        # Smalltalk-head/tail guard (live bug 2026-06-19, the Bill-Gates turn):
        # a continuation-recombine glued the answered "Was geht ab?" turn onto a
        # real command ("… mach mir den ältesten Bill-Gates-Post auf"). The
        # allowlist matched the chit-chat part, so the WHOLE turn was demoted to
        # a tool-less smalltalk turn — computer_use/spawn hidden, the deep brain
        # spoke the no-op "Notiert …" and never opened the browser. When the
        # utterance ALSO carries a clear action/request signal it is a COMMAND,
        # not chit-chat: keep the action tools visible. See _ACTION_REQUEST_RE.
        if _ACTION_REQUEST_RE.search(t):
            return False
        return True

    # Back-compat alias for the read-only tool the smalltalk path used to keep
    # by allowlist. The override is a HIDE-list now
    # (``_SMALLTALK_HIDDEN_TOOL_NAMES``), so screenshot survives like every
    # other non-spawn tool; the name is kept because external introspection
    # (telemetry, eval harness) reads it. NOTE: `_gate_screen_tool` still runs
    # AFTER the override and removes `screenshot` unless the utterance carries a
    # visual-reference marker (2026-06-14 screen-narration guard) — the
    # 2026-05-31 "Hallo, lies mir vor was oben links steht" case survives
    # because "lies" / "oben links" / "steht" are markers.
    _SMALLTALK_SAFE_TOOLS: frozenset[str] = frozenset({"screenshot"})

    # Skill-aware routing guard (AD-S3, 2026-06-09 rebuild): the Skill matched
    # for the CURRENT turn, set early in generate() and overwritten on every
    # turn. While set, force-spawn and the local-action fast path stand down
    # and run-skill stays visible even on smalltalk turns.
    _skill_turn_match_fallback: Any | None = None
    # Direct-trigger handoff (AD-S4): the speech pipeline / chat hook notes a
    # trigger match here instead of macro-running it; generate() consumes it
    # on the next call and injects the skill instructions into the turn.
    _pending_forced_skill: tuple[str, str, str] | None = None
    _skill_turn_content_fallback: str = ""
    _skill_turn_source_fallback: str = "match"
    _skill_injected_inline_fallback: bool = False
    # Skill META turn (2026-08-18): the user talks ABOUT a skill — asks for a
    # new one ("authoring": skill / routine / automation / workflow …) or wants
    # one switched off, deleted, listed ("lifecycle"). Set by
    # ``_match_skill_for_turn`` on every probe (``""`` otherwise); while set,
    # the force-spawn guard and the evidence gate stand down and no domain
    # skill may capture — the create-skill router tool / the skill
    # app-commands are the capability that owns such a turn, whether or not
    # the skill-creator builtin captured it. See dodaios/skills/authoring_request.py.
    _skill_meta_turn: str = ""
    # AD-S6: warn exactly once per manager lifetime when the AVAILABLE
    # SKILLS section cannot be rendered (RC2 used to be silent).
    _skills_omit_warned: bool = False
    # Evidence gate (CLI first-class capabilities, 2026-06-10): per-turn
    # mandatory-tool directive + the tool that must stay visible even on a
    # smalltalk-classified turn ("was steht heute an" matches the smalltalk
    # allowlist forms). Reset at the start of every generate() turn.
    _evidence_required_tool = _TurnField("")
    # True when the mandated tool this turn is a WRITE/create action (e.g.
    # contact-upsert) rather than a read lookup — switches the honest backstop
    # to write wording and lets a clarifying question stand. Reset per turn.
    _evidence_required_is_write = _TurnField(False)
    # The external-data domain (calendar/email/cloud/…) a READ mandate targets,
    # so an unmet mandate's spoken fallback can NAME the capability instead of
    # the generic "the tool" (B3, 2026-06-30). Reset per turn.
    _evidence_required_domain = _TurnField("")
    # Per-turn gate and voice signals (see ``_TurnField``): concurrent brain
    # turns of different sessions never share them.
    _public_fact_prefetched = _TurnField(False)
    _last_turn_all_failed = _TurnField(False)
    _last_turn_suppressed = _TurnField(False)
    _last_turn_executed_action_tool = _TurnField(False)
    _turn_substantive = _TurnField(False)
    _turn_needs_tools = _TurnField(False)

    def _local_brain_turn_state(self) -> _BrainTurnState | None:
        state = _BRAIN_TURN_STATE.get()
        return state if state is not None and state.owner is self else None

    @property
    def _evidence_directive(self) -> str:
        state = self._local_brain_turn_state()
        if state is not None:
            return state.evidence_directive
        return self.__dict__.get("_evidence_directive_last", "")

    @_evidence_directive.setter
    def _evidence_directive(self, value: str) -> None:
        state = self._local_brain_turn_state()
        if state is not None:
            state.evidence_directive = value
        else:
            self.__dict__["_evidence_directive_last"] = value

    @property
    def _memory_context_suffix(self) -> str:
        state = self._local_brain_turn_state()
        if state is not None:
            return state.memory_context_suffix
        return self.__dict__.get("_memory_context_suffix_last", "")

    @_memory_context_suffix.setter
    def _memory_context_suffix(self, value: str) -> None:
        state = self._local_brain_turn_state()
        if state is not None:
            state.memory_context_suffix = value
        else:
            self.__dict__["_memory_context_suffix_last"] = value

    @property
    def _active_turn_identity(self) -> tuple[str, str | None] | None:
        state = self._local_brain_turn_state()
        if state is not None:
            return state.active_turn_identity
        return self.__dict__.get("_active_turn_identity_last")

    @_active_turn_identity.setter
    def _active_turn_identity(self, value: tuple[str, str | None] | None) -> None:
        state = self._local_brain_turn_state()
        if state is not None:
            state.active_turn_identity = value
        else:
            self.__dict__["_active_turn_identity_last"] = value

    def _local_skill_turn_state(self) -> _SkillTurnState | None:
        state = _SKILL_TURN_STATE.get()
        return state if state is not None and state.owner is self else None

    @property
    def _skill_turn_match(self) -> Any | None:
        state = self._local_skill_turn_state()
        if state is not None:
            return state.match
        return self.__dict__.get(
            "_skill_turn_match_fallback",
            type(self)._skill_turn_match_fallback,
        )

    @_skill_turn_match.setter
    def _skill_turn_match(self, value: Any | None) -> None:
        state = self._local_skill_turn_state()
        if state is not None:
            state.match = value
        else:
            self._skill_turn_match_fallback = value

    @property
    def _skill_turn_content(self) -> str:
        state = self._local_skill_turn_state()
        if state is not None:
            return state.content
        return self.__dict__.get(
            "_skill_turn_content_fallback",
            type(self)._skill_turn_content_fallback,
        )

    @_skill_turn_content.setter
    def _skill_turn_content(self, value: str) -> None:
        state = self._local_skill_turn_state()
        if state is not None:
            state.content = value
        else:
            self._skill_turn_content_fallback = value

    @property
    def _skill_turn_source(self) -> str:
        state = self._local_skill_turn_state()
        if state is not None:
            return state.source
        return self.__dict__.get(
            "_skill_turn_source_fallback",
            type(self)._skill_turn_source_fallback,
        )

    @_skill_turn_source.setter
    def _skill_turn_source(self, value: str) -> None:
        state = self._local_skill_turn_state()
        if state is not None:
            state.source = value
        else:
            self._skill_turn_source_fallback = value

    @property
    def _skill_injected_inline(self) -> bool:
        state = self._local_skill_turn_state()
        if state is not None:
            return state.injected_inline
        return self.__dict__.get(
            "_skill_injected_inline_fallback",
            type(self)._skill_injected_inline_fallback,
        )

    @_skill_injected_inline.setter
    def _skill_injected_inline(self, value: bool) -> None:
        state = self._local_skill_turn_state()
        if state is not None:
            state.injected_inline = bool(value)
        else:
            self._skill_injected_inline_fallback = bool(value)







    def _cancel_readback(self, count: int) -> str:
        """Honest spoken readback for a deterministic cancel: name the count, or
        say plainly that nothing was running. Never silent (audit 2026-06-27)."""
        lang = self._resolve_turn_lang()
        if count > 0:
            return i18n_catalog.pick(_CANCEL_CONFIRM, lang).format(n=count)
        return i18n_catalog.pick(_CANCEL_NONE, lang)

    def _depth_readback(self, level: str) -> str:
        """Honest spoken confirmation of a depth override. Never silent."""
        lang = self._resolve_turn_lang()
        table = _DEPTH_CONFIRM.get(level, _DEPTH_CONFIRM["deep"])
        return i18n_catalog.pick(table, lang)

    # ------------------------------------------------------------------
    # Intent-Router → (provider, model) chain
    # ------------------------------------------------------------------

    def _picked_level(self, user_text: str) -> RoutingDecision:
        if self._force_level == "deep":
            return RoutingDecision(level="deep", reason="sticky-deep")
        if self._force_level == "fast":
            return RoutingDecision(level="fast", reason="sticky-fast")
        return classify(user_text)

    def _brain_can_call_tools(self, provider: str, model: str | None) -> bool:
        """Runtime tool-calling capability of a provider, capability-driven.

        A brain may expose ``can_call_tools()`` to report it cannot emit
        tool_calls right now (the subscription-CLI brains — Codex over the ChatGPT
        login, Antigravity over the Google login — drop ALL tools). Falls back to
        the static ``supports_tools`` ceiling, then True. Any error → True so the
        chain is never blocked by a capability probe."""
        try:
            brain = self._get_brain(provider, model)
        except Exception:  # noqa: BLE001
            return True
        fn = getattr(brain, "can_call_tools", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:  # noqa: BLE001
                return True
        return bool(getattr(brain, "supports_tools", True))

    def _active_can_call_tools(self) -> bool:
        """Whether the ACTIVE talker can emit tool_calls this turn."""
        return self._brain_can_call_tools(
            self._active_name, self._fast_model(self._active_name)
        )

    def _first_tool_capable_provider(
        self, level: str, *, exclude: str | None = None
    ) -> tuple[str, str | None] | None:
        """First AVAILABLE provider that can emit tool_calls — used to lead a
        tool/action turn when the active talker cannot. deep_brain first, then a
        stable cross-provider order. Returns (name, model) or None when no
        tool-capable provider is reachable (then the chain stays unchanged).
        ``exclude`` names the talker being led (the active brain by default;
        a per-turn pick under an override)."""
        skip = exclude if exclude is not None else self._active_name
        available = set(self._registry.available())
        order: list[str] = []
        db = self._config.brain.deep_brain
        if db:
            order.append(db)
        order += ["gemini", "claude-api", "openai", "openrouter", "grok", "nvidia", "litellm"]
        from dodaios.brain.voice_key import bills_voice_key

        # The realtime voice key leads a turn only when no other provider can
        # call tools (mandate 2026-09-29: that key pays for the voice call).
        on_voice_key: tuple[str, str | None] | None = None
        seen: set[str] = set()
        for name in order:
            if name in seen or name == skip or name not in available:
                continue
            seen.add(name)
            # Skip providers dead-listed or rate-limited THIS session — the
            # chain walk (see the dead_providers/rate_tracker checks at the
            # top of the provider-chain loop below) already excludes them
            # from actually answering, so picking one here as the "lead"
            # left _router_lead_key pointing at an entry the chain would
            # never reach: _is_router_lead misfired for the real lead and
            # the toolless fall-through gate accepted a tool-incapable
            # provider's answer as final.
            if name in self._dead_providers:
                continue
            model = (
                self._deep_model(name) if level in ("deep", "code")
                else self._fast_model(name)
            ) or self._fast_model(name)
            if not self._rate_tracker.is_available(name, model):
                continue
            if self._brain_can_call_tools(name, model):
                if bills_voice_key(self._config, name):
                    on_voice_key = on_voice_key or (name, model)
                    continue
                return (name, model)
        return on_voice_key

    def _turn_has_action_intent(self, user_text: str) -> bool:
        """Best-effort, provider-agnostic 'this turn wants a tool/desktop action'
        using the EXISTING deterministic detectors (no new signal-word list).
        Used only to decide whether a tool-incapable active talker should delegate
        this turn — a pure conversation/knowledge turn returns False and stays on
        the chosen provider."""
        t = user_text or ""
        if is_open_app_intent(t) or _looks_like_pc_control(t):
            return True
        try:
            from dodaios.core.capabilities import get_registry  # noqa: PLC0415

            reg = get_registry()
            if getattr(reg, "all", lambda: ())() and reg.has_action_intent(t):
                return True
        except Exception:  # noqa: BLE001 — registry must never block routing
            pass
        return False

    def _override_chain(
        self, override: TurnOverride, level: str
    ) -> list[tuple[str, str | None]]:
        """The chain for a caller-picked turn: exactly the pick, no stand-in.

        A person who chose a model in the chat gets that model or an honest
        error — never a silent cross-provider fallback. A tool-incapable pick
        does not authorize another provider to lead or bill this turn.
        """
        pick: tuple[str, str | None] = (override.provider, override.model)
        return [pick]

    def _build_fallback_chain(self, level: str) -> list[tuple[str, str | None]]:
        """Returns a prioritised list of (provider, model) attempts."""
        active = self._active_name
        chain: list[tuple[str, str | None]] = []
        # Reset the per-turn router-lead marker every build (a stale value would
        # make the loop wrongly fall through). Set below only when we prepend an
        # intelligent-router lead.
        self._router_lead_key: tuple[str, str | None] | None = None
        tool_lead: tuple[str, str | None] | None = None

        override = _TURN_OVERRIDE.get()
        if override is not None:
            return self._override_chain(override, level)

        # Capability-driven tool delegation (NOT a per-provider hardcode): the
        # subscription-CLI brains (Codex over the ChatGPT login, Antigravity over
        # the Google login) cannot emit tool_calls — can_call_tools() == False —
        # so a tool turn reaching them is dropped/confabulated. We hand tool
        # selection to a tool-capable provider; any future CLI brain inherits this.
        if not self._active_can_call_tools():
            intelligent = bool(
                getattr(self._config.brain.routing, "intelligent_router", True)
            )
            if intelligent and getattr(self, "_turn_substantive", False):
                # INTELLIGENT ROUTER (2026-06-21 mandate): a tool-capable provider
                # LEADS every substantive turn and the LLM itself picks the tool
                # via its tool-use loop + the router system prompt — no signal-word
                # list decides the tool. If it picks NO tool (pure conversation),
                # generate()'s chain loop FALLS THROUGH to the chosen talker (see
                # ``_router_lead_key``), so the user keeps their selected brain's
                # voice. The deterministic gates stay as high-precision guardrails.
                helper = self._first_tool_capable_provider(level)
                if helper is not None and helper[0] != active:
                    log.info(
                        "Intelligent router: %s cannot call tools — %s leads this "
                        "turn and picks the tool (falls through to %s if none).",
                        active, helper[0], active,
                    )
                    self._router_lead_key = helper
                    tool_lead = helper
                    chain.append(helper)
            elif getattr(self, "_turn_needs_tools", False):
                # Flag OFF (kill switch): the narrower action-intent delegation —
                # delegate ONLY when a deterministic action signal fired, and let
                # the tool-capable provider answer the whole turn (no fall-through).
                helper = self._first_tool_capable_provider(level)
                if helper is not None and helper[0] != active:
                    log.info(
                        "Tool delegation (legacy): %s cannot call tools — leading "
                        "this action turn with %s.", active, helper[0],
                    )
                    tool_lead = helper
                    chain.append(helper)

        # 0. Deep/code intents: dedicated deep_brain first (e.g. gemini via
        #    subscription — bypasses /v1/messages API quota). Bug fix 2026-04-29:
        #    at level=deep the deep_model of the brain MUST be used (previously:
        #    _fast_model → gemini-3-flash for a deep request instead of
        #    gemini-3.1-pro-preview).
        deep_brain = self._config.brain.deep_brain
        # When the user has explicitly made a frontier SUBSCRIPTION brain the
        # active one (codex via ChatGPT),
        # it leads ALL turns — the deep_brain (e.g. gemini) must NOT jump ahead for
        # deep/code intents, or the chosen brain would never actually answer a hard
        # question despite being selected (it would silently fall through to the
        # deep_brain). Other active brains keep the deep_brain routing unchanged.
        if (
            level in ("deep", "code")
            and deep_brain
            and deep_brain != active
            and active != "codex"
            and deep_brain in self._registry.available()
        ):
            preferred_deep = self._deep_model(deep_brain) or self._fast_model(deep_brain)
            chain.append((deep_brain, preferred_deep))

        # 1. Active provider with the appropriate model for the level
        fast = self._fast_model(active)
        deep = self._deep_model(active)

        if level == "fast":
            if fast:
                chain.append((active, fast))
            if deep:  # on Haiku rate-limit → try Opus in the same provider
                chain.append((active, deep))
        elif level in ("deep", "code"):
            if deep:
                chain.append((active, deep))
            if fast:  # if Opus fails, use Haiku (better than nothing)
                chain.append((active, fast))
        else:
            if fast:
                chain.append((active, fast))

        # A registered provider may own its default model (local discovery or
        # a subscription CLI's account default). Keep that choice on the chain.
        if not fast and not deep and active in self._registry.available():
            chain.append((active, None))

        # 2. Explicit tier fallbacks from jarvis.toml. These must run before
        # generic cross-provider probing so runtime matches healthcheck order.
        available = set(self._registry.available())
        for name, configured_model in self._configured_fallbacks:
            if name not in available:
                continue
            m_fast = self._fast_model(name)
            m_deep = self._deep_model(name)
            preferred = configured_model or (m_deep if level in ("deep", "code") else m_fast)
            chain.append((name, preferred or m_fast or m_deep))

        # 3. Cross-provider fallbacks (same provider family first).
        # Ollama completely removed (2026-04-21) — user decision, pure
        # cloud/API provider chain.
        cross_order = [
            "claude-api",           # separate Anthropic-Quota
            "gemini",               # Google AI Studio
            "openrouter",           # universal gateway
            "openai",
            "grok",                 # xAI Grok
            "nvidia",               # NVIDIA NIM (free dev tier)
            "litellm",              # user-hosted LiteLLM proxy
        ]
        for name in cross_order:
            if name == active:
                continue
            if name not in available:
                continue
            m_fast = self._fast_model(name)
            m_deep = self._deep_model(name)
            preferred = m_deep if level in ("deep", "code") else m_fast
            chain.append((name, preferred or m_fast or m_deep))

        # Deduplicate (first instance wins) + filter dead providers.
        # Dead = provider already failed with "no API key" in this session.
        # Skip it so the voice turn does not run 8x sequentially against
        # missing keys. Reset on provider switch or manager restart.
        seen: set[tuple[str, str | None]] = set()
        deduped: list[tuple[str, str | None]] = []
        for item in chain:
            if item in seen:
                continue
            if item[0] in self._dead_providers:
                continue
            seen.add(item)
            deduped.append(item)
        # A tool lead no other family could take, and a provider the person
        # switched to themselves, stay on the chain.
        keep = [entry for entry in deduped if entry[0] == self._switched_to == active]
        if tool_lead is not None:
            keep.append(tool_lead)
        return self._keep_off_voice_key(
            deduped,
            keep=keep,
            needs_tools=bool(getattr(self, "_turn_needs_tools", False)),
        )

    def _keep_off_voice_key(
        self,
        chain: list[tuple[str, str | None]],
        *,
        keep: Iterable[tuple[str, str | None]] = (),
        needs_tools: bool = False,
    ) -> list[tuple[str, str | None]]:
        """Drop the realtime voice key's family while another provider remains.

        Text turns, Telegram and scheduled routines never spend the key that
        pays for the live voice call (mandate 2026-09-29). A single-key install
        keeps it, and so do the ``keep`` entries (a tool lead no other family
        could take, a provider the person switched to). Only a
        provider that can take the turn right now counts as the alternative:
        not rate-limited, and able to call tools when the turn needs them.
        """
        from dodaios.brain.voice_key import without_voice_key

        models: dict[str, str | None] = {}
        for name, model in chain:
            models.setdefault(name, model)

        def can_answer(name: str) -> bool:
            model = models.get(name)
            if not self._rate_tracker.is_available(name, model):
                return False
            return not needs_tools or self._brain_can_call_tools(name, model)

        kept = without_voice_key(self._config, chain, is_alternative=can_answer, keep=keep)
        if len(kept) < len(chain):
            log.debug(
                "Voice key reserved for the live call — left out of this chain: %s",
                sorted({name for name, _ in chain} - {name for name, _ in kept}),
            )
        return kept

    # ------------------------------------------------------------------
    # Generate — Haupt-Entrypoint
    # ------------------------------------------------------------------

    async def generate(
        self,
        user_text: str,
        *,
        use_history: bool = True,
        trace_id: UUID | None = None,
        text_consumer: Callable[[str], None] | None = None,
        on_progress: Callable[[], None] | None = None,
        source_layer: str | None = None,
        conversation_id: str | None = None,
        allow_voice_confirm: bool = False,
        prefer_tool_model: bool = False,
        emit_tool_ack: bool = True,
        publish_response: bool = True,
        history_override: Iterable[BrainMessage] | None = None,
        force_output_language: str | None = None,
        consume_pending_voice_attachments: bool = False,
        turn_override: TurnOverride | None = None,
        language_text: str | None = None,
    ) -> str:
        """Generate a turn, optionally leaving its public response event to the caller.

        ``publish_response=False`` suppresses only ``ResponseGenerated``. History,
        curator work, tool execution, and every other turn side effect remain intact.
        The context-local policy keeps concurrent classic and delegated calls isolated.
        ``history_override`` supplies caller-owned context for this turn without
        mutating the manager's shared conversation buffer; combine it with
        ``use_history=False`` when the caller owns history persistence too.
        ``turn_override`` runs the turn on a caller-picked provider / model /
        effort with extra tools and tool context (the typed chat's pick) —
        the live brain, its config and its dead-lists are left untouched.
        ``language_text`` is what the conversation language is read from when
        ``user_text`` is not the person's own words (an internal "continue"
        prompt): ``""`` keeps the conversation's language unchanged.
        """
        token = _PUBLISH_RESPONSE_EVENT.set(bool(publish_response))
        history_token = _TURN_HISTORY_OVERRIDE.set(
            tuple(history_override) if history_override is not None else None
        )
        override_token = _TURN_OVERRIDE.set(turn_override)
        # Armed ("" = no language yet); _update_turn_language fills it in.
        language_token = TURN_LANGUAGE.set("")
        from dodaios.core.image_references import active_scope

        image_scope_token = active_scope.set(
            "conversation:" + conversation_id if conversation_id else
            "brain:" + str(id(self)) if use_history else "turn:" + str(trace_id or uuid4())
        )
        skill_state = _SkillTurnState(self)
        skill_token = _SKILL_TURN_STATE.set(skill_state)
        brain_state = _BrainTurnState(self)
        brain_state_token = _BRAIN_TURN_STATE.set(brain_state)
        try:
            return await self._generate(
                user_text,
                use_history=use_history,
                trace_id=trace_id,
                text_consumer=text_consumer,
                on_progress=on_progress,
                source_layer=source_layer,
                conversation_id=conversation_id,
                allow_voice_confirm=allow_voice_confirm,
                prefer_tool_model=prefer_tool_model,
                emit_tool_ack=emit_tool_ack,
                force_output_language=force_output_language,
                consume_pending_voice_attachments=(
                    consume_pending_voice_attachments
                ),
                language_text=language_text,
            )
        finally:
            # Keep the last completed turn inspectable for diagnostics/tests,
            # while active concurrent turns continue reading their own
            # ContextVar-backed state.
            self._skill_turn_match_fallback = skill_state.match
            self._skill_turn_content_fallback = skill_state.content
            self._skill_turn_source_fallback = skill_state.source
            self._skill_injected_inline_fallback = skill_state.injected_inline
            # Same for the last turn's directive and answering identity: only
            # inspectable once the turn is over, never read by a concurrent one.
            self._evidence_directive_last = brain_state.evidence_directive
            self._active_turn_identity_last = brain_state.active_turn_identity
            self.__dict__.update(
                {"_turn_last_" + k: v for k, v in brain_state.values.items()}
            )
            _LAST_TURN_VALUES.set((self, dict(brain_state.values)))
            _BRAIN_TURN_STATE.reset(brain_state_token)
            _SKILL_TURN_STATE.reset(skill_token)
            _TURN_OVERRIDE.reset(override_token)
            TURN_LANGUAGE.reset(language_token)
            active_scope.reset(image_scope_token)
            _TURN_HISTORY_OVERRIDE.reset(history_token)
            _PUBLISH_RESPONSE_EVENT.reset(token)

    async def _generate(self, user_text: str, *args: Any, **kwargs: Any) -> str:
        """A voice turn. Its spend is published on ``BrainTurnCompleted`` with
        the realtime/tool/pipeline split, so the ledger row the metered
        provider writes underneath is tagged and not counted a second time."""
        from dodaios.costs.ledger import usage_context

        # Voice turns are "voice-turn"; a typed chat, society or routine turn
        # (it carries a per-turn override) is tagged by its own surface.
        caller = "voice-turn" if _TURN_OVERRIDE.get() is None else "agent-chat"
        with usage_context(caller):
            return await self._generate_untagged(user_text, *args, **kwargs)


    def inject_images_for_turn(
        self, trace_id: UUID, images: tuple[ImageBlock, ...]
    ) -> None:
        """Attach ad-hoc ``images`` to the upcoming turn identified by ``trace_id``.

        Used by the drag-drop intake (``dodaios/brain/drop_context.py``) so a
        dropped picture reaches the multimodal brain. The images are consumed by
        ``_collect_vision_images`` on that turn and never carry over. A no-op for
        an empty tuple. ``trace_id`` is unique per turn → race-free.
        """
        if not images:
            return
        # Defensive: tolerate a manager built via __new__ (some unit tests bypass
        # __init__), mirroring how _vision_provider is accessed via getattr.
        if getattr(self, "_pending_turn_images", None) is None:
            self._pending_turn_images = {}
        self._pending_turn_images[trace_id] = tuple(images)

    def add_dropped_context(
        self, text: str, images: tuple[ImageBlock, ...] = ()
    ) -> None:
        """Stash drag-and-dropped content as SILENT conversation context.

        A drop must NOT trigger a brain turn — the user keeps the normal speaking
        flow, and the dropped content is simply remembered and used on the NEXT
        real turn (a drop while idle is kept for next time; a drop mid-flow joins
        the running context). The text is appended to history as a user-context
        message so it is naturally in the next turn's context (and persists for
        follow-ups); images are parked and consumed once by the next
        ``generate`` call. getattr-guarded for managers built via ``__new__``.
        """
        if text and text.strip():
            if getattr(self, "_history", None) is None:
                self._history = []
            self._history.append(BrainMessage(role="user", content=text.strip()))
            if len(self._history) > 40:
                self._history = self._history[-40:]
        log.info(
            "📎 DROP CONTEXT stashed: %d text chars, %d images "
            "(history now %d msgs, pending drop images %d)",
            len(text or ""), len(images),
            len(getattr(self, "_history", []) or []),
            len(getattr(self, "_pending_drop_images", ()) or ()) + len(images),
        )
        if images:
            cur = getattr(self, "_pending_drop_images", ()) or ()
            self._pending_drop_images = tuple(cur) + tuple(images)

    async def _collect_vision_images(
        self,
        *,
        trace_id: UUID,
        user_text: str = "",
        is_smalltalk: bool = False,
    ) -> tuple[ImageBlock, ...]:
        """Returns the current screen as an ImageBlock for the brain turn.

        Factory/voice start the VisionContextProvider on the BrainManager.
        Without this bridge, blobs were captured but the actual brain call
        remained text-only.
        """
        # Drag-drop: ad-hoc images injected for THIS turn win over (and bypass)
        # the screen-vision path — a dropped picture matters, not the current
        # screen, and it must arrive even with screen-vision off. Pop so it is
        # used exactly once. getattr-guarded for managers built via __new__.
        pending = getattr(self, "_pending_turn_images", None)
        if pending:
            injected = pending.pop(trace_id, None)
            if injected:
                return injected

        # A turn under a WRITE mandate is an ACTION turn, not a vision turn
        # (shell-consistency rework 2026-08-08): an attached image narrows the
        # tool surface downstream (_image_turn_tool_override), and the mandated
        # write tool is the one it must not lose. "erstell einen Ordner
        # hier auf dem Desktop" carries the visual marker "hier auf" yet wants
        # a shell action, not a screen answer — same for a mandated contact/
        # wiki write. Read mandates are untouched (they never attach anyway:
        # their data comes from the mandated tool, not the screen).
        if getattr(self, "_evidence_required_is_write", False):
            log.info("Vision-Inject skipped: write-mandate action turn")
            return ()

        vision = getattr(self, "_vision_provider", None)
        vision_none = vision is None
        paused = (
            bool(getattr(vision, "is_paused", False))
            if vision is not None
            else None
        )
        log.info(
            "Vision-Inject Diagnose: path=BrainManager vision_none=%s "
            "is_paused=%s brain_provider=%s",
            vision_none,
            paused,
            self._active_name,
        )
        if vision is None or paused:
            return ()

        # Wave 1 (omni-latency): conditional vision — skip the screenshot on
        # confidently text-only turns (skip-when-safe). Keep the per-turn image
        # tax only where the screen might actually matter. Anti-regression vs.
        # 2026-04-28: when in doubt, the gate keeps the image.
        perf = getattr(self._config, "performance", None)
        if getattr(perf, "conditional_vision", False):
            from dodaios.brain.vision_gate import should_attach_screenshot

            if not should_attach_screenshot(user_text, is_smalltalk=is_smalltalk):
                log.info("Vision-Inject skipped: text-only turn (%r)", user_text[:60])
                return ()

        try:
            from dodaios.brain.router import _read_observation_image_b64

            obs = await asyncio.wait_for(
                vision.current(), timeout=_VISION_COLLECT_TIMEOUT_S
            )
            hash_prefix = (obs.screenshot_hash or "")[:16]
            geometry = tuple(
                getattr(obs, "monitor_geom", (0, 0, 0, 0))
                or (0, 0, 0, 0)
            )
            width, height = (
                (int(geometry[2]), int(geometry[3]))
                if len(geometry) >= 4
                else (0, 0)
            )
            capture_age_ms = max(
                0, int((time.time_ns() - obs.timestamp_ns) / 1_000_000)
            )
            log.info(
                "Vision-Inject Observation: screenshot_hash=%s "
                "dimensions=%dx%d capture_age_ms=%d",
                hash_prefix,
                width,
                height,
                capture_age_ms,
            )
            mime, image_b64 = await _read_observation_image_b64(obs)
            # Wave 1 (omni-latency): enforce max_image_kb (was dead config) —
            # cap the per-turn payload before it ships; no-op if already small.
            from dodaios.vision.image_budget import cap_image_b64

            vcfg = getattr(getattr(self._config.brain, "router", None), "vision", None)
            max_kb = int(getattr(vcfg, "max_image_kb", 0) or 0)
            if max_kb > 0:
                mime, image_b64 = cap_image_b64(mime, image_b64, max_kb * 1024)
            log.info(
                "Vision-Inject encoded: brain_provider=%s mime=%s "
                "screenshot_hash=%s len_image_b64=%d",
                self._active_name,
                mime,
                hash_prefix,
                len(image_b64),
            )
            if self._bus is not None:
                bytes_size = len(image_b64) * 3 // 4
                age_ms = int((time.time_ns() - obs.timestamp_ns) / 1_000_000)
                await self._bus.publish(VisionInjected(
                    trace_id=trace_id,
                    screenshot_hash=obs.screenshot_hash,
                    bytes_size=bytes_size,
                    capture_age_ms=age_ms,
                ))
            return (
                ImageBlock(
                    mime=mime,
                    data_b64=image_b64,
                    source_hash=obs.screenshot_hash,
                ),
            )
        except TimeoutError:
            log.warning(
                "Vision-Inject skipped: capture exceeded %.1fs — proceeding "
                "text-only (no hot-path hang). brain_provider=%s",
                _VISION_COLLECT_TIMEOUT_S,
                self._active_name,
            )
            return ()
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Vision-Inject fehlgeschlagen: path=BrainManager "
                "brain_provider=%s exc=%r",
                self._active_name,
                exc,
                exc_info=True,
            )
            return ()

    # Pipeline-Adapter
    async def __call__(self, text: str) -> str:
        return await self.generate(text)

    async def generate_stream(
        self,
        user_text: str,
        *,
        use_history: bool = True,
        trace_id: UUID | None = None,
        on_progress: Callable[[], None] | None = None,
        allow_voice_confirm: bool = False,
        conversation_id: str | None = None,
        consume_pending_voice_attachments: bool = False,
    ) -> AsyncIterator[str]:
        """Latency sprint 1: streaming variant of ``generate``.

        Yields each brain text chunk in real time. Tool-use loops run as
        usual; pre-tool-use text is also streamed (the persona prompt forbids
        fillers, so this is uncritical). Evidence-gated turns are buffered
        until ``generate`` returns its authoritative final text, because the
        post-call evidence or action-honesty enforcement may replace an
        unverified stream.

        ``on_progress`` (stall-timeout signal): forwarded to the tool-use loop,
        which pings it at every model-round + tool boundary. The speech pipeline
        passes its ``_mark_brain_progress`` here so its *no-progress* deadline
        resets while a vision/tool turn is genuinely working but streaming no
        text (live bug 2026-06-01). ``None`` (default) is a no-op.

        Consumed via an ``asyncio.Queue`` between the producer task
        (``generate``) and the caller (``async for``). If the caller cancels
        the generator, the producer is also cancelled.

        Callers can reassemble the final aggregated text from the yielded
        chunks themselves — a helper may be added later if needed.
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        sentinel: str | None = None
        # generate() returns the FINAL text — recovery-corrected when a leaked
        # tool_use was executed (see _recover_leaked_tool). Streaming previously
        # discarded this (BUG-028 pattern), so a leaked action-tool reached TTS
        # as raw JSON and the action was lost. We capture it here.
        holder: dict[str, str | None] = {"final": None}
        context = tuple(
            str(message.content or "")
            for message in (
                (getattr(self, "_history", ()) or ())[-8:]
                if use_history
                else ()
            )
        )
        action_buffered = plan_turn(user_text, context=context).requires_orchestrator

        def _consumer(chunk: str) -> None:
            # ``put_nowait`` because the consumer is called on the sync
            # aggregator path (no await possible). Queue is unbounded.
            try:
                queue.put_nowait(chunk)
            except Exception:  # noqa: BLE001
                pass

        async def _producer() -> None:
            try:
                holder["final"] = await self.generate(
                    user_text,
                    use_history=use_history,
                    trace_id=trace_id,
                    text_consumer=_consumer,
                    on_progress=on_progress,
                    allow_voice_confirm=allow_voice_confirm,
                    conversation_id=conversation_id,
                    consume_pending_voice_attachments=(
                        consume_pending_voice_attachments
                    ),
                )
            finally:
                # Sentinel signals "brain is done (or crashed)".
                queue.put_nowait(sentinel)

        task = asyncio.create_task(_producer(), name="brain-stream-producer")
        accumulated = ""
        holding = False
        held = ""
        leaked = False
        yielded = False
        evidence_buffered = False
        try:
            while True:
                chunk = await queue.get()
                if chunk is sentinel:
                    break
                accumulated += chunk
                # A provider sometimes streams a tool_use block as TEXT instead
                # of invoking it ("oeffne den Editor" -> open_app/dispatch JSON).
                # Withhold those chunks so the raw JSON is never spoken (it would
                # scrub to silence and the action would be lost). generate()
                # recovers + executes the leaked tool and returns a speakable
                # result, which we yield once the stream ends.
                #
                # A growing buffer cannot tell a leak from an answer that merely
                # OPENS with a bracket — "[Doku](…)", a JSON example. So the
                # shape test only HOLDS the chunks; the verdict is taken once,
                # after the sentinel, on the finished buffer. Held prose is
                # released there instead of being dropped for the rest of the
                # turn, which is what used to swallow such answers whole.
                if not holding and _may_be_tool_use_leak(accumulated):
                    holding = True
                evidence_now = bool(getattr(self, "_evidence_required_tool", ""))
                if evidence_now:
                    evidence_buffered = True
                if holding:
                    held += chunk
                    continue
                if evidence_now:
                    continue
                if action_buffered:
                    continue
                yield chunk
                yielded = True
            if holding:
                leaked = _looks_like_tool_use_leak(accumulated)
                if (
                    not leaked
                    and not evidence_buffered
                    and not action_buffered
                    and held.strip()
                ):
                    # Never a tool call — ordinary speech that happened to open
                    # with "[" or "{". The user gets the whole answer.
                    yield held
                    yielded = True
            # Surface generate()'s authoritative final text whenever NOTHING was
            # streamed to TTS — either because a leaked tool_use JSON was
            # withheld, OR because the brain produced a STRUCTURED / suppress
            # tool-call with no text chunks at all (dispatch_to_harness result,
            # spawn_worker ACK, recovered tool). Without this the user hears
            # silence on exactly those action turns — live repro 2026-05-25
            # "oeffne mir Chrome" returned empty while plain chat worked. The
            # old code only surfaced the final on the leaked-JSON path.
            if leaked or not yielded or evidence_buffered or action_buffered:
                final = (holder.get("final") or "").strip()
                if final and not _looks_like_tool_use_leak(final):
                    yield final
                elif leaked:
                    yield await render_readback(
                        getattr(self, "_readback_composer", None),
                        instruction=(
                            "A tool action was recognized but could not be "
                            "carried out; tell the user plainly."
                        ),
                        language=self._direct_ack_language(user_text),
                        canned=lambda: self._action_failed_phrase(user_text),
                    )
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------
    # Summarize — for Jarvis-Agent-Announcements (Phase 5, Wave-4 rebrand)
    # ------------------------------------------------------------------

    async def summarize(self, text: str, *, max_tokens: int = 120) -> str:
        """Compresses text via the fast model of the active provider.

        Purpose: TTS announcements in 1-2 sentences, suitable for speech output.
        The stream is fully aggregated and capped at ~max_tokens * 4 characters
        (rough UTF-8 token heuristic).
        """
        if not text.strip():
            return ""

        brain = self._get_brain(self._active_name, self._fast_model(self._active_name))
        system_prompt = (
            "Du fasst Texte in 1-2 Saetzen zusammen, klar und praezise fuer "
            "Sprachausgabe. Antworte ausschliesslich mit der Zusammenfassung."
        )
        req = BrainRequest(
            messages=(
                BrainMessage(
                    role="user",
                    content=f"Fasse in 1-2 Saetzen zusammen, klar und praezise fuer Sprachausgabe: {text}",
                ),
            ),
            system=system_prompt,
            temperature=0.3,
            max_tokens=max_tokens,
            stream=True,
        )

        agg = await aggregate(brain.complete(req))
        summary = (agg.text or "").strip()

        char_cap = max_tokens * 4
        if len(summary) > char_cap:
            summary = summary[:char_cap].rstrip()
        return summary

    # ------------------------------------------------------------------
    # Tool-Registry
    # ------------------------------------------------------------------

    def set_tools(self, tools: dict[str, Tool]) -> None:
        self._tools = dict(tools)

    def add_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def clear_history(self) -> None:
        self._history = []
        self.__dict__.pop("_voice_history_seed", None)

    def drop_last_turn(self, expected_user_text: str) -> bool:
        """Remove the most recent (user, assistant) pair when its user message
        matches ``expected_user_text`` (whitespace-insensitive).

        Used by the voice continuation-recombine path: when a combined turn
        supersedes the immediately-preceding committed turn, the truncated half
        must not be duplicated in history. Safe no-op when fewer than two
        messages are buffered, when the tail is not a user/assistant pair, or
        when the tail user text does not match — so it does nothing when the
        prior turn was aborted before commit (the common interrupt case).
        Returns ``True`` iff a pair was removed.
        """
        if len(self._history) < 2:
            return False
        last = self._history[-1]
        prev = self._history[-2]
        if last.role != "assistant" or prev.role != "user":
            return False
        if (prev.content or "").strip() != (expected_user_text or "").strip():
            return False
        del self._history[-2:]
        return True

    # Roles the brain conversation buffer accepts for seeding. ``tool``
    # messages need a tool_call_id pairing and are never seeded standalone;
    # UI-only roles (e.g. ``preamble`` pre-ack bubbles) are not conversation.
    _SEEDABLE_ROLES: frozenset[str] = frozenset({"user", "assistant", "system"})
    # Same window the auto-append paths enforce (see the ``self._history =
    # self._history[-40:]`` trims throughout generate()/force-spawn).
    # Maintainer mandate 2026-08-24: full call memory, not a cost window.
    _HISTORY_MAX: int = 400

    def seed_history(self, turns: Iterable[Any]) -> None:
        """Preseed the conversation buffer with prior turns.

        Replaces ``_history`` so a re-opened chat (text continuation via
        ``POST /api/chats/{kind}/{id}/resume``) or a "Speak in this
        conversation" voice session (``.../speak``) continues coherently.
        This is the single primitive behind both Chats-manager paths.

        Pure in-memory, no LLM call and no I/O — safe to call before a voice
        session is armed without touching the voice critical path (AP-9/AP-11).

        Accepts an iterable of :class:`BrainMessage`, ``(role, text)`` tuples,
        or ``{"role": ..., "content"|"text": ...}`` dicts. Entries whose role
        is outside :attr:`_SEEDABLE_ROLES` (e.g. the UI-only ``preamble``
        bubble) and entries with empty text are dropped. The result is capped
        to :attr:`_HISTORY_MAX`, keeping the most recent turns — an empty
        input therefore behaves like :meth:`clear_history`.
        """
        self._history = self._seedable(turns)
        # Explicit archive selection also seeds the next duplex call. Ordinary
        # generated turns never fill this slot: unrelated calls must stay fresh.
        self._voice_history_seed = tuple(self._history)

    def _seedable(self, turns: Iterable[Any]) -> list[BrainMessage]:
        """``turns`` reduced to seedable messages, newest :attr:`_HISTORY_MAX` kept."""
        seeded: list[BrainMessage] = []
        for item in turns:
            if isinstance(item, BrainMessage):
                role: Any = item.role
                content: Any = item.content
            elif isinstance(item, dict):
                role = item.get("role")
                content = item.get("content", item.get("text"))
            else:
                try:
                    role, content = item
                except (TypeError, ValueError):
                    continue
            if role not in self._SEEDABLE_ROLES:
                continue
            if isinstance(content, str):
                if not content.strip():
                    continue
            elif not content:
                continue
            seeded.append(
                item
                if isinstance(item, BrainMessage)
                else BrainMessage(role=role, content=content)
            )
        return seeded[-self._HISTORY_MAX :]

    def set_voice_history_source(self, source: Callable[[], Iterable[Any]] | None) -> None:
        """Where a call without an explicit seed gets its starting history.

        The front page's chat binds the chat a call continues
        (``AgentChatService.bind_voice_chat``); the source answers with that
        chat's turns at call start, so a second call in the same chat still
        knows the first one. ``None`` returns to fresh calls.
        """
        if source is None:
            self.__dict__.pop("_voice_history_source", None)
        else:
            self._voice_history_source = source

    def drop_voice_history_seed(self) -> None:
        """Forget an explicit seed nobody consumed, so the source answers instead."""
        self.__dict__.pop("_voice_history_seed", None)

    def take_voice_history_seed(self) -> tuple[BrainMessage, ...]:
        """Consume an explicit resume once, retaining the text brain's history.

        A single dict pop transfers ownership even when desktop session setup
        runs on a worker thread. Reconnects reuse the receiving call's copy.
        Without an explicit seed the bound chat's history answers
        (:meth:`set_voice_history_source`); an explicit empty seed — "new
        voice chat" — still wins and starts the call fresh.
        """
        if "_voice_history_seed" in self.__dict__:
            history: tuple[BrainMessage, ...] = self.__dict__.pop("_voice_history_seed", ())
            return history
        source = self.__dict__.get("_voice_history_source")
        if source is None:
            return ()
        try:
            return tuple(self._seedable(source()))
        except Exception:  # noqa: BLE001 — a call without history beats no call
            log.warning("voice history source failed; the call starts fresh", exc_info=True)
            return ()

    # ------------------------------------------------------------------
    # Live reload for the CLI tool registry (CLI integration, task 2)
    # ------------------------------------------------------------------

    def refresh_tools(self) -> None:
        """Synchronous refresh for callers outside the running event loop."""
        snapshot = self._build_tool_snapshot()
        if snapshot is not None:
            self._apply_tool_snapshot(snapshot)

    async def refresh_tools_async(self) -> None:
        """Coalesce registry events and build snapshots without blocking the loop."""
        self._tool_refresh_pending = True
        task = getattr(self, "_tool_refresh_task", None)
        if task is None or task.done():
            async def refresh() -> None:
                from dodaios.brain.tool_surface import live_tool_surface_fingerprint

                while self._tool_refresh_pending:
                    self._tool_refresh_pending = False
                    before = live_tool_surface_fingerprint()
                    snapshot = await asyncio.to_thread(self._build_tool_snapshot)
                    if snapshot is not None:
                        self._apply_tool_snapshot(snapshot)
                        if live_tool_surface_fingerprint() != before:
                            self._tool_refresh_pending = True

            task = asyncio.create_task(refresh(), name="brain-tool-refresh")
            self._tool_refresh_task = task
        # A cancelled subscriber/turn must not abandon a registry refresh that
        # other subscribers are awaiting, or cause another concurrent build.
        await asyncio.shield(task)

    def _build_tool_snapshot(self):
        """Build replacement dictionaries while preserving the boot-time DI.

        Plugin imports and entry-point scans can block for seconds on cold
        storage. Running-loop callers execute this on a worker and publish
        the complete result back on the loop. No tier means no replacement.
        """
        tier = getattr(self, "_tier", None)
        if not tier:
            log.debug("refresh_tools: no tier set; skipping")
            return
        try:
            # Lazy import: the factory may pull in heavy modules depending on
            # config (vision, harness). The import happens only on refresh,
            # not during BrainManager setup.
            from dodaios.brain.factory import (
                _load_local_action_tools,
                _load_tools_for_tier,
                _resolve_mission_manager,
            )
            from dodaios.harness.manager import HarnessManager
            from dodaios.safety import (
                ApprovalWorkflow,
                RiskTierEvaluator,
                ToolExecutor,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("refresh_tools: factory modules could not be imported: %s", exc)
            return

        try:
            # Minimally invasive re-init for the tool load: the existing
            # ToolExecutor is retained (risk policy + approval are session-stable);
            # only the tool instances are re-instantiated.
            executor = self._tool_executor
            if executor is None:
                # Fallback: build an executor so tools can still be loaded —
                # in practice the manager always has one.
                from dodaios.clis.risk_integration import make_cli_patterns_fn
                evaluator = RiskTierEvaluator(
                    self._config.safety,
                    extra_patterns_fn=make_cli_patterns_fn(),
                )
                approval = ApprovalWorkflow(self._bus)
                executor = ToolExecutor(
                    self._bus, evaluator, approval,
                    default_timeout_s=self._config.safety.tool_approval_timeout_s,
                )

            harness_manager = HarnessManager(bus=self._bus)

            # This rebuild runs on EVERY CLI/MCP connect at boot ("Tool-Registry
            # refreshed: 29 -> 107"). It must mirror the shared DI references
            # the boot path passes, or the rebuilt tools lose their managers
            # (live 2026-06-18: contact/spawn_worker went dark after the first
            # CLI connected).
            new_tools = _load_tools_for_tier(
                tier,
                bus=self._bus,
                executor=executor,
                harness_manager=harness_manager,
                user_profile=self._user_profile,
                people=self._people,
                config=self._config,
                mission_manager=_resolve_mission_manager(),
                contacts=self._contacts,
            )
            new_local_action_tools = _load_local_action_tools(
                bus=self._bus,
                harness_manager=harness_manager,
                config=self._config,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("refresh_tools: factory call failed: %s", exc)
            return

        return new_tools, new_local_action_tools

    def _apply_tool_snapshot(self, snapshot) -> None:
        new_tools, new_local_action_tools = snapshot
        old_count = len(self._tools)
        self._tools = new_tools
        self._local_action_tools = new_local_action_tools
        # Record what the sources looked like at THIS load, so the per-turn
        # reconcile (tool_surface.maybe_reconcile_tool_surface) only fires on
        # genuine drift after a missed BrainToolsChanged.
        stamp_tool_surface(self)
        log.info(
            "Tool-Registry refreshed: %d -> %d tools",
            old_count, len(new_tools),
        )

    def attach_to_bus(self, bus: EventBus | None = None) -> None:
        """Registers live-reload subscriptions on the event bus.

        Called after the factory build (``factory.py``). Currently:
        - ``BrainToolsChanged`` → ``refresh_tools()``
        - ``SecretConfigured`` → ``reactivate_provider()`` for the brain
          provider whose key was just set. Prevents a provider that already
          failed with "no API key" from being excluded from the fallback chain
          until the app is restarted.
        - ``AnnouncementRequested`` (CU-tool-tagged) → mirror the router-tier
          ``computer_use`` outcome into the live history (subsystem-confusion fix).

        Called separately rather than in ``__init__`` so BrainManager can be
        constructed for tests without a bus subscription.
        """
        from dodaios.core.events import (
            AnnouncementRequested,
            BrainToolsChanged,
            SecretConfigured,
        )

        target_bus = bus or self._bus
        if target_bus is None:
            return

        async def _on_tools_changed(ev: BrainToolsChanged) -> None:
            log.info("BrainToolsChanged received (reason=%s); refreshing tools", ev.reason)
            await self.refresh_tools_async()

        target_bus.subscribe(BrainToolsChanged, _on_tools_changed)
        target_bus.subscribe(AnnouncementRequested, self._on_cu_tool_completion)

        async def _on_secret_configured(ev: SecretConfigured) -> None:
            if ev.action != "set":
                return
            provider = _SECRET_KEY_TO_BRAIN.get(ev.key)
            if not provider:
                return
            self.reactivate_provider(provider)
            # Fresh-install heal (open-source AP-22/AP-23): on a first run there
            # is no jarvis.toml, so brain.primary is the packaged code-default
            # (e.g. claude-api) that the downloader has NO key for. Setting a key
            # for a DIFFERENT provider used to leave that dead default active, so
            # the brain kept reporting "not configured" even though a usable key
            # was now present — the #1 fresh-laptop symptom. If the currently
            # active provider has no usable credential, promote the provider the
            # user just keyed to active and persist it. This is NOT the autonomous
            # self-switch the USER-ONLY / provider_lock mandate forbids: it fires
            # only in direct response to the user's OWN key-set action (the same
            # path as a manual "Set as active" click, via config_writer — never
            # the locked self-mod writer), and it never overrides a provider the
            # user deliberately selected (one that already has a working key or
            # OAuth login is left untouched).
            if provider == self._active_name:
                return  # reactivate_provider already re-armed the active one
            if self._active_has_usable_credential():
                return
            previous_active = self._active_name
            try:
                await self.switch(provider, persist=True)
                log.info(
                    "Fresh-install heal: active brain %r had no usable "
                    "credential; promoted just-keyed provider %r to active and "
                    "persisted brain.primary.",
                    previous_active, provider,
                )
            except Exception:  # noqa: BLE001 — a subscriber must never kill the bus (AP-18)
                log.warning(
                    "auto-activate on key-set failed for provider %r",
                    provider, exc_info=True,
                )

        target_bus.subscribe(SecretConfigured, _on_secret_configured)

        from dodaios.core.events import ConfigReloaded

        async def _on_config_reloaded(ev: ConfigReloaded) -> None:
            # Hot-reload the reply-language pin so a Self-Mod / Control-API write
            # to ``brain.reply_language`` (SAFE, needs_restart=False) takes effect
            # on the NEXT turn without an app restart. The event carries only the
            # changed keys, so re-read the persisted value from disk. Never let a
            # bad value (ValueError) escape — that would kill the bus (AP-18).
            if "brain.reply_language" not in ev.changed_keys:
                return
            try:
                import asyncio as _asyncio

                from dodaios.core.config import load_config

                # Off the event loop — load_config() is a blocking disk read and
                # this subscriber fires on every SAFE-tier config write.
                cfg = await _asyncio.to_thread(load_config)
                raw = getattr(cfg.brain, "reply_language", "auto")
                self.set_reply_language(normalize_reply_language(raw))
            except Exception:  # noqa: BLE001 — survive without a live switch
                log.warning("reply-language hot-reload failed", exc_info=True)

        target_bus.subscribe(ConfigReloaded, _on_config_reloaded)

        async def _on_proactivity_reloaded(ev: ConfigReloaded) -> None:
            # A voice "be less proactive" goes through Self-Mod (SAFE, no
            # restart): re-read the persisted level and make it live for every
            # surface on the next turn. Never raise into the bus (AP-18).
            if "brain.proactivity" not in ev.changed_keys:
                return
            try:
                import asyncio as _asyncio

                from dodaios.core.config import load_config

                cfg = await _asyncio.to_thread(load_config)
                level = _proactivity.apply_level(getattr(cfg.brain, "proactivity", None))
                self._config.brain.proactivity = level
            except Exception:  # noqa: BLE001 — survive without a live switch
                log.warning("initiative hot-reload failed", exc_info=True)

        target_bus.subscribe(ConfigReloaded, _on_proactivity_reloaded)

    # ------------------------------------------------------------------
    # Back-compat aliases (for existing tests)
    # ------------------------------------------------------------------

    @property
    def _providers(self) -> dict[str, Brain]:
        """Back-compat: exposes the cache as {provider_name: active_instance}."""
        out: dict[str, Brain] = {}
        for (name, _model), inst in self._brain_cache.items():
            out.setdefault(name, inst)
        return out

    @property
    def _tool_executor_ref(self) -> ToolExecutor | None:
        return self._tool_executor

    def _get_or_create(self, name: str) -> Brain:
        """Back-compat wrapper — uses the config model when available."""
        return self._get_brain(name, self._fast_model(name))

    async def use_deep_model(self) -> bool:
        deep = self._deep_model(self._active_name)
        if not deep:
            return False
        self._force_level = "deep"
        return True

    async def use_fast_model(self) -> bool:
        fast = self._fast_model(self._active_name)
        if not fast:
            return False
        self._force_level = "fast"
        return True

    @property
    def dispatcher(self) -> BrainDispatcher:
        """Back-compat: builds a dispatcher with the fast model of the active provider."""
        brain = self._get_brain(self._active_name, self._fast_model(self._active_name))
        return self._build_dispatcher(brain)

    def _select_task_tools(self, allowed_tools: tuple[str, ...]) -> dict[str, Tool]:
        """Filter the live tool set down to a per-task allowlist.

        Unknown grants (e.g. a plugin that isn't connected) are silently
        skipped — the task runs with whatever of its allowlist is live.

        A grant is matched by :func:`dodaios.tasks.grants.grant_matches`:
        exact name, or the plugin prefix of a bridged MCP tool — the grant
        ``github`` covers every ``github/<tool>``. (Exact matching alone left
        a routine with a ``github`` grant running with ZERO tools.)

        A grant naming one of :data:`_TASK_ONLY_TOOLS` that is NOT in the live
        (router) set is loaded from its entry point on demand: ``remember`` is
        deliberately outside ``ROUTER_TOOLS`` (ADR-0011), yet a scheduled
        task that was granted it must be able to store what it found. The
        instance is cached per manager and only ever reaches the task's own
        dispatcher — never the router surface.
        """
        from dodaios.clis.capability_provider import equivalent_grants  # noqa: PLC0415
        from dodaios.tasks.grants import grant_matches  # noqa: PLC0415

        if not allowed_tools:
            return {}
        grants = equivalent_grants(allowed_tools)
        selected = {
            name: tool for name, tool in self._tools.items()
            if any(grant_matches(grant, name) for grant in grants)
        }
        for grant in grants:
            if grant in selected or grant not in _TASK_ONLY_TOOLS:
                continue
            tool = self._load_task_only_tool(grant)
            if tool is not None:
                selected[grant] = tool
        return selected

    def _load_task_only_tool(self, name: str) -> Tool | None:
        """Instantiate (once) an entry-point tool that only scheduled tasks
        may use. Returns ``None`` — and logs why — when it cannot be built,
        so the task runs with the rest of its allowlist."""
        cache: dict[str, Tool | None] = self.__dict__.setdefault("_task_only_tool_cache", {})
        if name in cache:
            return cache[name]
        from dodaios.core.entry_points import entry_points  # noqa: PLC0415

        tool: Tool | None = None
        for ep in entry_points(group="jarvis.tool"):
            if ep.name != name:
                continue
            try:
                tool = ep.load()()
            except Exception as exc:  # noqa: BLE001 — a broken tool must not kill the task
                log.warning("task-only tool %r failed to load: %s", name, exc)
                tool = None
            break
        else:
            log.warning("task-only tool %r has no entry point", name)
        cache[name] = tool
        return tool

    async def run_task(
        self,
        *,
        prompt: str,
        allowed_tools: tuple[str, ...] = (),
        model_tier: str = "auto",
        trace_id: UUID | None = None,
        prefer_api: bool = False,
    ) -> str:
        """Keep the selected agent and billing account for the entire scheduled turn."""
        from dodaios.core.model_selection import (
            operation_model,
            use_operation_model,
            worker_selection,
        )

        selected = operation_model.get() or worker_selection(self._config)
        with use_operation_model(selected):
            return await self._run_task_with_selection(
                prompt=prompt,
                allowed_tools=allowed_tools,
                model_tier=model_tier,
                trace_id=trace_id,
                prefer_api=prefer_api,
            )

    async def _run_task_with_selection(
        self,
        *,
        prompt: str,
        allowed_tools: tuple[str, ...] = (),
        model_tier: str = "auto",
        trace_id: UUID | None = None,
        prefer_api: bool = False,
    ) -> str:
        """Run one isolated agentic turn for a scheduled task.

        The turn sees ONLY the allowlisted tools and runs with an EMPTY
        history, so it never pollutes the live voice session's ``_history``
        or sticky model level (a scheduled task fires off the chat path).
        Tool calls still flow through the shared ``ToolExecutor`` — so
        read-only (monitor-tier) plugins pass unattended while ask-tier
        actions still hit the approval gate (which, with no human present,
        means they block until the unattended-approval wave wires Option B).

        An explicit agent selection stays fixed, including subscription tasks.
        Until migration selects an agent, the legacy credential-ready provider
        chain remains available — see :meth:`_task_provider_chain`.
        A credential / credit / rate-limit
        error (401/402/403/429 — the same classes the chat path dead-lists
        or cools down) moves the SAME turn on to the next candidate; any
        other error propagates so the runner records it in ``last_error``.
        The persistent active provider is never switched.

        ``prefer_api`` is accepted so a routine whose owner seat already
        failed (a CLI without Jarvis tools) can retry here without a
        TypeError. This path is already the API provider chain.

        Returns the final assistant text.
        """
        del prefer_api
        intent = "deep" if model_tier == "deep" else "fast"
        # A routine whose prompt asks for its result as an artifact is granted
        # the builder for that turn — the same explicit-word rule the chat gate
        # applies, so "every morning at 8, my briefing as an artifact" works
        # without the person knowing the tool has a grant of its own.
        from dodaios.brain.artifact_gate import wants_artifact  # noqa: PLC0415

        if wants_artifact(prompt) and _ARTIFACT_TOOL_NAME not in allowed_tools:
            allowed_tools = (*allowed_tools, _ARTIFACT_TOOL_NAME)
        tools = self._select_task_tools(allowed_tools)
        from dodaios.core.model_selection import operation_model, worker_selection
        from dodaios.core.task_agent import (
            dual_seat_subscription,
            run_selected,
            subscription_seat_off_loop,
        )

        selected = operation_model.get() or worker_selection(self._config)
        if (
            selected is not None
            and await subscription_seat_off_loop(selected.provider) is not None
        ):
            subscription = dual_seat_subscription(selected.provider)
            if subscription is not None:
                # A dual slot only gets its seat while that login answers. The
                # sighting is what later keeps an unattended turn off the
                # slot's per-token row when the login stops answering.
                from dodaios.brain.background_policy import note_connected

                await asyncio.to_thread(note_connected, subscription)
            return await run_selected(
                selection=selected, prompt=prompt, tool_names=tuple(tools), trace_id=trace_id
            )
        # The per-turn context (date/time, wiki) rides on the user
        # message in cache-optimized mode; without it a scheduled turn did not
        # know what day it was (BUG-212 — the morning brief prompts say "the
        # date is in your context" and it was not). Legacy mode carries it in
        # the system prompt and this stays empty.
        try:
            turn_context = self._build_turn_context()
        except Exception:  # noqa: BLE001 — the context block is a nicety
            log.debug("run_task: turn context skipped", exc_info=True)
            turn_context = ""
        attempts = self._task_provider_chain(intent)
        from dodaios.core.protocols import current_started_by_user

        if not current_started_by_user.get():
            # Nobody started this turn (a schedule, a trigger, a background
            # start): it may only bill what background work may bill — a
            # subscription or a local model, never a per-token key on its own.
            attempts = await self._unattended_task_chain(attempts, selected)
        failures: list[str] = []
        original: Exception | None = None
        for index, (name, model) in enumerate(attempts):
            try:
                brain = self._get_brain(name, model)
                await _settle_context_window(brain)
                dispatcher = self._build_dispatcher(
                    brain, tools_override=tools,
                    # ``unattended``: the tool-use loop feeds an unknown tool
                    # name back and continues instead of ending the turn on
                    # the spoken "missing tool" phrase (BUG-212).
                    tool_context={"delivery": "written", "unattended": True},
                )
                agg = await dispatcher.dispatch(
                    prompt, history=[], intent_level=intent, trace_id=trace_id,
                    turn_context=_scheduled_turn_context(turn_context, tools),
                )
                # This chain leads with the Tool Model, so its outcomes are the
                # Tool Model tab's evidence.
                _health_ledger.record_success(name, _health_ledger.MODALITY_TOOL, model=model)
                return agg.text or ""
            except Exception as exc:
                kind = _classify_provider_error(str(exc), default="call_fail")
                if kind not in _TASK_FALLBACK_KINDS:
                    raise
                _health_ledger.record_failure(
                    name, _health_ledger.MODALITY_TOOL, exc, model=model
                )
                original = original or exc
                failures.append(f"{name}: {_short_provider_error(exc)}")
                remaining = attempts[index + 1:]
                if remaining:
                    log.warning(
                        "run_task: %s rejected the turn (%s) — trying %s next",
                        name, kind, remaining[0][0],
                    )
                    continue
                log.warning(
                    "run_task: %s rejected the turn (%s) and no further "
                    "credential-ready tool-capable provider is usable", name, kind,
                )
        if len(failures) == 1 and original is not None:
            raise original
        raise RuntimeError("all brain providers failed: " + "; ".join(failures))

    async def _unattended_task_chain(
        self,
        attempts: list[tuple[str, str | None]],
        selected: Any,
    ) -> list[tuple[str, str | None]]:
        """Hold an unattended turn's chain to the background policy.

        - An explicit agent selection is the person's own choice and stays —
          except a dual slot (one that is a subscription seat while its login
          is ready and a per-token row otherwise). Its login is not ready here
          (a ready one ran on the subscription above), so the row it fell back
          to was never picked and follows the same policy as the automatic
          chain.
        - The automatic chain keeps only subscriptions and local models once a
          subscription is connected; an install without one keeps its chain,
          so a single-key download still works.

        Nothing usable raises :class:`BackgroundDeferred` instead of billing a
        key; the runner records the skipped run.
        """
        from dodaios.brain.background_policy import BackgroundDeferred, background_providers
        from dodaios.core.task_agent import dual_seat_subscription

        attempts = _seat_health.wait_out_cooling_seats(attempts)
        if selected is not None:
            provider = str(getattr(selected, "provider", "") or "")
            if dual_seat_subscription(provider) is None:
                return attempts
        policy = await asyncio.to_thread(
            background_providers, [name for name, _model in attempts]
        )
        if not policy.subscription_mode:
            return attempts
        kept = [(name, model) for name, model in attempts if policy.permits(name)]
        dropped = [name for name, _model in attempts if not policy.permits(name)]
        if kept:
            if dropped:
                log.info(
                    "run_task (unattended): skipping per-token providers %s; "
                    "background work stays on %s",
                    dropped, [name for name, _model in kept],
                )
            return kept
        log.warning(
            "run_task (unattended): no subscription or local model can run this "
            "turn (%s); deferring instead of billing %s",
            policy.reason, dropped,
        )
        raise BackgroundDeferred(
            "No subscription or local model is available for this unattended run; "
            "a paid API key is not used without your approval."
        )

    def _task_provider_chain(self, intent: str) -> list[tuple[str, str | None]]:
        """The providers a scheduled turn tries, in order.

        The Tool Model leads (the provider and key the user set for tool
        calls — ``[brain.tool_model]``, the "API Keys" section), then every
        other credential-ready, tool-capable provider of a different family
        (:meth:`_hoist_tool_model` over the automatic chain). The chat's
        active provider is just one candidate in that chain, never the
        anchor: it used to be the only one, and with OpenRouter at 0 credits
        every automation died at its action step while a ready Vertex Tool
        Model sat unused (BUG-212). Without any ready candidate the active
        provider is tried alone so the caller sees its real error.

        ``deep`` turns swap in the provider's deep model; ``fast``/``auto``
        run on the Tool Model's own model — the cheapest correct default for
        an unattended background turn. Capped so an unattended run cannot
        walk a long chain for minutes.
        """
        from dodaios.core.model_selection import operation_model, worker_selection

        selected = operation_model.get() or worker_selection(self._config)
        if selected is not None:
            return [(selected.provider, selected.model)]
        try:
            ready = self._hoist_tool_model(self._tool_model_base_chain())
        except Exception:  # noqa: BLE001 — a broken probe must not kill the task
            log.debug("run_task: tool-model chain unavailable", exc_info=True)
            ready = []
        # A scheduled routine runs unattended; it spends the realtime voice key
        # only when no other ready provider exists (mandate 2026-09-29).
        ready = self._keep_off_voice_key(ready)
        chain: list[tuple[str, str | None]] = []
        for name, model in ready[:_TASK_MAX_ATTEMPTS]:
            if intent == "deep":
                model = self._deep_model(name) or model
            chain.append((name, model))
        if chain:
            return chain
        name = self._active_name
        model = (
            (self._deep_model(name) or self._fast_model(name))
            if intent == "deep" else self._fast_model(name)
        )
        return [(name, model)]

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_provider": self._active_name,
            "force_level": self._force_level,
            "history_size": len(self._history),
            "tools_available": sorted(self._tools.keys()),
            "providers_available": self.available_providers(),
            "providers_failed": self.failed_providers(),
            "fast_model": self._fast_model(self._active_name),
            "deep_model": self._deep_model(self._active_name),
        }


#: Entry-point tools a scheduled task may be granted although they are NOT
#: router tools (ADR-0011 keeps the router a pure dispatcher). Loaded lazily
#: by ``_select_task_tools`` for the task's own dispatcher only. Never a
#: spawn tool (AP-5/AP-14).
_TASK_ONLY_TOOLS: frozenset[str] = frozenset({"remember"})

#: Error classes that make a scheduled task move on to the next provider
#: family: the dead-list kinds (missing/bad key, 402 credits) plus a rate limit.
_TASK_FALLBACK_KINDS: frozenset[str] = frozenset(
    {"missing_key", "account_blocked", "bad_key", "rate_limit"}
)

#: Most providers one scheduled turn walks before it gives up (BUG-212).
_TASK_MAX_ATTEMPTS: int = 4

def _scheduled_turn_context(turn_context: str, tools: dict[str, Any]) -> str:
    """The per-turn context of an unattended scheduled turn.

    The cached system prompt advertises skills, CLIs and the full tool
    surface of a live conversation; a scheduled turn sees only its allowlist
    and has nobody to ask. Say so ON the turn (never in the cached prefix),
    naming the tools that exist, so the model neither reaches for ``run-skill``
    nor ends with a question (BUG-212: the briefing tried the morning-routine
    skill the prompt had advertised and died on "missing tool").
    """
    names = ", ".join(sorted(tools)) or "none"
    block = (
        "[Scheduled run — unattended] This turn runs on a schedule with no one "
        f"listening. The only tools that exist in this turn are: {names}. Do not "
        "call any other tool. If more than one listed tool can do the job, use "
        "whichever is connected and returns data — do not stop because the first "
        "name you tried is missing. Do not ask questions or request permission; "
        "work with the tools listed and answer with the finished result."
    )
    return f"{turn_context}\n\n{block}" if turn_context else block


def _short_provider_error(exc: Exception) -> str:
    """One readable line for ``last_error`` / the fallback summary — the
    exception class and the first 160 characters of its message."""
    from dodaios.tasks.runner import readable_error

    # The same code + human-message extraction the Runs tab uses, so a
    # two-provider failure reads "openrouter: 402 — Insufficient credits…;
    # gemini: 429 — You exceeded your current quota…" and not two dumped
    # JSON bodies of which only the first survives the length cap.
    return readable_error(exc)[:160]


def _is_rate_limit_exc(exc: Exception) -> bool:
    """Heuristic: 429 / rate_limit_error / status_code=429."""
    msg = str(exc).lower()
    if "429" in msg or "rate_limit" in msg or "rate-limit" in msg:
        return True
    if "rate limit" in msg or "too many requests" in msg:
        return True
    # Anthropic-SDK-RateLimitError
    if type(exc).__name__ == "RateLimitError":
        return True
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    return False


# Leak-recovery fallback variants — see BrainManager._action_failed_phrase.
_ACTION_FAILED_PHRASES: dict[str, str] = i18n_catalog.table("brain.action_failed")

# DIRECT local-action acknowledgement — see BrainManager._localize_direct_ack.
# open_app hardcodes a German launch acknowledgement that the DIRECT fast path
# surfaces VERBATIM (no LLM re-render), so its leading verb is translated to the
# turn language here (live bug 2026-06-15: an English "open my explorer" turn was
# acknowledged in German even with the English pin set). Only the verb prefix is
# swapped — the suffix (the actual app / URL the tool reported) is preserved
# untouched. The "de" entry MUST match open_app's literal prefix in
# dodaios/plugins/tool/open_app.py; a mismatch degrades safely to passthrough
# (the historical German string), never a crash.
_OPEN_APP_ACK_PREFIX: dict[str, str] = {
    "de": "Gestartet:",  # i18n-allow: spoken German TTS acknowledgement
    "en": "Opened:",
    "es": "Abierto:",
    "pt": "Aberto:",
}


def _looks_german(text: str) -> bool:
    """True when *text* is clearly German.

    Delegates to the canonical ``detect_text_language`` (the single source of
    truth the pipeline uses for the turn language) instead of a private
    stop-word list. The old heuristic compared two tiny hint lists with
    ``score_de >= score_en``, so any text with no recognised stop-word in
    either list scored 0-0 and was declared German. A clean English sentence
    ("Could you please tell me which city ... in Australia?") therefore tied to
    German and was acknowledged / labelled German (live bug 2026-06-14). The
    canonical detector returns ``"unknown"`` on ambiguity, so English, Spanish
    and zero-signal text are now correctly NOT German.
    """
    return detect_text_language(text) == "de"


def _is_missing_key_exc(msg: str) -> bool:
    """Heuristic: provider reports a missing API key or invalid auth state."""
    m = msg.lower()
    return any(k in m for k in (
        "kein grok-api-key", "kein gemini-api-key", "kein openai-api-key",
        "kein anthropic-api-key", "kein claude-credential",
        "kein openrouter-api-key", "kein xai-api-key",
        "api_key not set", "api key not found",
        "api_key is not set", "api key is not set",
        "anthropic_api_key is not set", "openai_api_key is not set",
        "gemini_api_key is not set", "xai_api_key is not set",
        "api-key gefunden", "missing api key", "no api key",
        "not configured",
        "api-key nicht gesetzt", "apikey missing",
        "not logged in", "please run /login", "credentials.json",
        # Vertex AI's Google Cloud project path signs with Application Default
        # Credentials; a host without a gcloud login or service account raises
        # google-auth's DefaultCredentialsError ("Your default credentials were
        # not found"). Live 2026-08-22 18:40/18:42: classified as call_fail,
        # the keyless Tool Model led the chain on EVERY delegated voice turn and
        # paid 7-10 s for the same miss before a working provider was tried.
        "default credentials were not found", "defaultcredentialserror",
        "application default credentials were not found",
    ))


def _is_account_blocked_exc(msg: str) -> bool:
    """Heuristic: provider account has a terminal auth/quota/billing problem.
    Examples observed live (all 2026-04-29):

      - Anthropic 400: ``Your credit balance is too low to access the
        Anthropic API. Please go to Plans & Billing.``
      - xAI 404: ``The model grok-4.1-fast does not exist or your team
        e6d8f57e-... does not have access to it.``
      - OpenAI 403: ``The model `o1-pro` is not available on your tier.``
      - Gemini 403: ``Quota exceeded for ...`` (unlike 429 — terminal).

      - OpenRouter 403: ``Key limit exceeded (total limit).`` (a funded account
        whose per-key spend cap is used up — live probe 2026-06-30, AP-22).

    These providers are dead for the session (a simple retry won't help).
    BrainManager pushes them immediately into _dead_providers and emits a
    user-actionable setup message instead of "provider unreachable".
    """
    m = msg.lower()
    # Billing / budget / quota wording is the SHARED canonical list (one source of
    # truth with the test-badge classifier) — covers credit-balance, spend/key/total
    # limit, insufficient_quota, depleted prepayment, out-of-credits, etc.
    if any(k in m for k in BILLING_LIMIT_MARKERS):
        return True
    # Access / tier / subscription gates — terminal too, but not strictly "money".
    return any(k in m for k in _ACCOUNT_ACCESS_MARKERS)


# Terminal access/tier/subscription wordings (NOT money — kept beside the shared
# billing markers so both flavours of "account blocked" live in one classifier).
_ACCOUNT_ACCESS_MARKERS: tuple[str, ...] = (
    "your team",                   # xAI "your team ... does not have access"
    "team does not have access",
    "team_does_not_have_access",
    "not available on your tier",  # OpenAI tier gate
    "subscription required",
    "upgrade plan",
    "upgrade your plan",
    "billing required",
    "billing not active",
    "account is suspended",
    # Gemini CLI refuses personal accounts since the move to Antigravity: a
    # terminal account state, not a network fault (issue #1871).
    "ineligibletiererror",
    "no longer supported for gemini code assist",
)


def _http_status_code(msg: str) -> int | None:
    """First 4xx/5xx HTTP status embedded in a provider error string, else None.

    The SDK serializes the numeric code into ``str(exc)`` ("Error code: 403 - …"
    for the OpenAI/Anthropic families; "403 … PERMISSION_DENIED" for Gemini), so a
    code-first decision works uniformly without importing any provider SDK — the
    same approach the test-badge classifier uses.
    """
    match = re.search(r"\b([45]\d\d)\b", msg)
    return int(match.group(1)) if match else None


# The chain loop dead-lists exactly these kinds: a terminal credential/account state
# (no key stored, blocked/over-budget account, invalid key) must cross to another
# available provider family for the rest of the session. A transient ``rate_limit``
# is deliberately NOT here — it takes the 30s cooldown path and keeps the provider.
_DEAD_LIST_KINDS: frozenset[str] = frozenset({"missing_key", "account_blocked", "bad_key"})


# User-friendly labels per provider — what the user needs to do.
def _is_invalid_model_exc(msg: str) -> bool:
    """Heuristic: provider reports an unknown/invalid model ID.

    Do NOT use when the error is more likely an account problem
    (see `_is_account_blocked_exc`) — otherwise an account 404 would
    incorrectly land as "config bug, fix jarvis.toml".
    """
    if _is_account_blocked_exc(msg):
        return False
    m = msg.lower()
    return any(k in m for k in (
        "model_not_found", "model not found", "model does not exist",
        "unknown model", "invalid model", "invalid_model",
        "not a valid model", "unsupported model",
        # OpenAI's 404 for a Responses-API-only model called over
        # Chat-Completions ("This is not a chat model and thus not supported
        # in the v1/chat/completions endpoint"). Live 2026-08-06: spoken as
        # "network or provider issue", which sent the user hunting API keys.
        "not a chat model",
    ))


#: How long a brain may take to say which context window it really has before
#: the turn goes ahead with the figure it already published.
_CONTEXT_SETTLE_TIMEOUT_S = 3.0


async def _settle_context_window(brain: Any) -> None:
    """Let a brain that has to ASK for its window do so before tools are fitted.

    A hosted model's window is a constant on its class. A local server's is
    whatever that server was started or loaded with, so the two local brains
    expose ``prepare_context_window`` and learn it with one or two cached
    round-trips. Without this the first turn is budgeted for a figure the
    server may not run, and is then refused whole instead of having its tool
    surface trimmed. Gated on the capability, never a provider name (AP-21);
    a brain without the method is untouched. Bounded and never raises: a slow
    or failing probe costs nothing but the better budget.
    """
    prepare = getattr(brain, "prepare_context_window", None)
    if not callable(prepare):
        return
    try:
        await asyncio.wait_for(prepare(), timeout=_CONTEXT_SETTLE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — the turn runs on the published figure
        log.debug(
            "Context window of %s not settled before the turn: %s",
            getattr(brain, "name", type(brain).__name__),
            exc,
        )


#: Tokens held back from a brain's context window before its tool surface is
#: sized: the user's turn text, the per-turn context block, the plugin usage
#: cards and the first answer or tool round. Only a local brain has a window
#: small enough for this to matter — see ``_fit_tools_to_context_window``.
_CONTEXT_FIT_RESERVE_TOKENS = 4096

#: A declared window at or below this is a small model: it is shown a short
#: list of tools even when a longer one would fit (see ``_shortlist_tools``).
_SMALL_WINDOW_TOKENS = 32_768
#: How many tools such a model is shown besides the ones a turn pins.
_SMALL_MODEL_DIRECT_TOOLS = 24
#: Room held back for the definitions ``find_tools`` adds during a turn whose
#: window is already full, and for the finder itself with its index of names.
_REVEAL_RESERVE_TOKENS = 2_000
_FINDER_TOKENS = 700

#: Chars per token for the size estimate. Deliberately low: tool schemas are
#: JSON, which tokenizes denser than prose, and over-estimating costs a few
#: tools on a 32k window while under-estimating costs the whole turn.
_CONTEXT_FIT_CHARS_PER_TOKEN = 3


def _approx_tokens(text: str) -> int:
    """A conservative token estimate for ``text`` — no tokenizer needed."""
    return len(text) // _CONTEXT_FIT_CHARS_PER_TOKEN + 1


def _approx_history_tokens(history: Sequence[BrainMessage] | None) -> int:
    """What the message log costs on the wire, by the same estimate."""
    if not history:
        return 0
    total = 0
    for msg in history:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total += _approx_tokens(content)
            continue
        try:
            total += _approx_tokens(json.dumps(content, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            total += _approx_tokens(str(content))
    return total


def _tool_surface_tokens(name: str, tool: Any) -> int:
    """What ONE tool costs on the wire: name, description and schema."""
    return tool_tokens(name, tool)


def _fit_tools_to_context_window(
    tools: dict[str, Tool],
    *,
    context_window: int,
    used_tokens: int,
    keep: Iterable[str] = (),
    max_tools: int = 0,
) -> tuple[dict[str, Tool], list[str]]:
    """The tools that fit ``context_window`` and ``max_tools``, and the rest.

    Returns ``(tools that fit, names passed over)``. A window or a tool cap
    of ``0`` or less means the brain declared none. ``used_tokens`` is
    everything else the request carries (system prompt, history, reserve);
    what remains is the budget for tools.

    The choice is made by ``plan_surface``: the everyday tools first, then
    the rest in registry order, connected-server tools last — they are
    additions to the app's own surface, each one a full JSON schema (live
    2026-08-27: 131 of 221 tools came from three MCP servers). A tool that
    does not fit is passed over and the next one tried. Names in ``keep``
    always fit. When even the prompt alone exceeds the window nothing but
    ``keep`` is left.
    """
    if (context_window <= 0 and max_tools <= 0) or not tools:
        return tools, []
    plan = plan_surface(
        tools,
        keep=keep,
        budget_tokens=max(context_window - used_tokens, 0) if context_window > 0 else None,
        max_direct=max(max_tools, 0),
    )
    if not plan.deferred:
        return tools, []
    passed = set(plan.deferred)
    return {name: tool for name, tool in tools.items() if name not in passed}, list(plan.deferred)


#: Wordings with which providers refuse a request larger than the model's
#: context window. Per request, never per credential — so NOT in
#: ``_DEAD_LIST_KINDS`` and never a cooldown.
_CONTEXT_OVERFLOW_MARKERS: tuple[str, ...] = (
    "exceeds the available context size",  # llama.cpp / Ollama (live 2026-08-27)
    "exceed_context_size",  # the same server's error type
    "context_length_exceeded",  # OpenAI-compatible error code
    "maximum context length",  # OpenAI / OpenRouter wording
    "prompt is too long",  # Anthropic
    "exceeds the maximum number of tokens",  # Gemini ("input token count …")
)


def _is_context_overflow_exc(msg: str) -> bool:
    """True when the provider refused the request for its SIZE.

    Until 2026-08-27 this fell through to the generic ``call_fail`` and the
    user read "I can't reach my provider — check the network" for a request
    the server had answered perfectly well, with a 400 that named the cause.
    """
    m = msg.lower()
    return any(marker in m for marker in _CONTEXT_OVERFLOW_MARKERS)


def _classify_provider_error(msg: str, *, default: str) -> str:
    """Central classifier for provider error strings.

    Order is intentional:
      1. missing_key (auth/config — important for the dead-list).
      2. account_blocked (credit/quota/tier/budget — also dead-list, by wording).
      3. invalid_model (config bug — different action: fix jarvis.toml).
      0. local_context (a local server runs the model with a window too small
         for this request — our own guard's wording, so it is checked first;
         per request, never a dead-list or cooldown).
      3b. context_overflow (the request is larger than the model's window —
          per request, so neither dead-list nor cooldown; the spoken cause
          names the size, not the network).
      4. code-first terminal: a bare 401 -> bad_key, a bare 402 -> account_blocked
         (dead-list; catches a live invalid key / Payment-Required that carries the
         numeric code but no known wording).
      5. rate_limit (transient — handled by its own cooldown path).
      6. default (init_fail or call_fail — caller decides).

    bad_key / account_blocked / missing_key all dead-list (``_DEAD_LIST_KINDS``)
    so a terminal provider stops leading the chain; only rate_limit takes the
    transient cooldown.

    missing_key is checked before rate_limit so an auth error that happens to
    contain "limit" (e.g. "exceeded the rate limit for this resource") is not
    incorrectly classified as a 429 cooldown.
    """
    # A local server's window is named by our own guard with a fixed wording;
    # checked first so no other heuristic can read the sentence differently.
    if LOCAL_CONTEXT_MARKER in msg.lower():
        return "local_context"
    if _is_missing_key_exc(msg):
        return "missing_key"
    if _is_account_blocked_exc(msg):
        return "account_blocked"
    if _is_invalid_model_exc(msg):
        return "invalid_model"
    if _is_context_overflow_exc(msg):
        return "context_overflow"
    m = msg.lower()
    # Code-first terminal fallback for a 401/402 that carries the numeric HTTP code
    # but NONE of the known wordings (a bare live "Error code: 401 - invalid x-api-key"
    # / "Error code: 402 - Payment Required"). A 401 = invalid/expired/wrong-account
    # key, a 402 = Payment-Required — both terminal, so the provider is dead-listed and
    # stops leading the chain every turn (live log 2026-06-30: claude-api 401 with no
    # Anthropic account was retried on every turn). 403/429 stay word-driven on purpose:
    # a transient Gemini 403 "CachedContent not found" must NOT dead-list (BUG-019).
    code = _http_status_code(m)
    if code == 401:
        return "bad_key"
    if code == 402:
        return "account_blocked"
    if any(s in m for s in ("429", "rate_limit", "rate-limit",
                             "rate limit", "too many requests")):
        return "rate_limit"
    return default


def _keyless_provider_is_rescued_by_oauth(provider_name: str) -> bool:
    """True when a keyless provider must NOT be dead-listed at the pre-boot key
    check because it authenticates via an OAuth login ON DISK, not an API key.

    The subscription-CLI brains (codex over the ChatGPT login at ``~/.codex/auth.json``)
    carry no entry in ``PROVIDER_SECRET_CANDIDATES``, so a ChatGPT-only user would
    otherwise see ``codex`` pushed into ``_dead_providers`` → empty chain → every
    chat AND voice turn bricks with the provider-down apology. The OAuth login IS a
    usable credential. Open-source single-provider mandate (AP-22). Any import/probe
    failure is treated as "not rescued" (fail-safe → dead-list).

    Vertex AI is the second shape: its Google Cloud project path signs with
    Application Default Credentials (a ``gcloud`` login, a service account,
    workload identity), so a fully configured install stores no key in any of
    the family's slots. The declarative ``KEYLESS_CREDENTIAL_PROBES`` table in
    ``app_control`` is the ONE place that names the probe, and it is the same
    answer every provider card and every switch already gives — so this check
    can never dead-list a family the UI shows as configured. Live 2026-08-17:
    the check knew only key slots, pushed ``vertex`` into ``_dead_providers``
    at every boot, and the router silently ran on the AI Studio account (whose
    prepaid credit was empty) while the user's Vertex project sat idle.
    """
    if provider_name == "codex":
        try:
            from dodaios.plugins.brain.codex import _codex_oauth_connected
            return bool(_codex_oauth_connected())
        except Exception:  # noqa: BLE001
            return False
    try:
        from dodaios.brain.app_control import _keyless_credential_present

        return bool(_keyless_credential_present(provider_name))
    except Exception as exc:  # noqa: BLE001 — a failed probe is not a credential
        log.debug("Keyless-credential rescue probe failed for %s: %s", provider_name, exc)
        return False


_PROVIDER_SETUP_HINTS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY setzen (Key via https://aistudio.google.com/apikey)",
    "claude-api": "ANTHROPIC_API_KEY setzen",
    "openai": "OPENAI_API_KEY setzen",
    "openrouter": "OPENROUTER_API_KEY setzen",
    "litellm": "Set LITELLM_API_KEY and the proxy server URL",
    "deepseek": "Set DEEPSEEK_API_KEY (key from platform.deepseek.com)",
    "grok": "Set XAI_API_KEY (key from console.x.ai)",
    "nvidia": "Set NVIDIA_API_KEY (nvapi- key from build.nvidia.com)",
    "ollama-local": "Ollama-Server starten (localhost:11434)",
    "ollama-cloud": "Ollama-Cloud-Token setzen",
}


def _format_provider_chain_error(
    errors: list[tuple[str, str, str, str]],
) -> str:
    """Builds a meaningful user message from the per-provider error list.

    Prioritises root causes: when the **primary** provider has no key,
    THAT is the main message. Rate limits are listed as secondary.
    """
    if not errors:
        return ("Keine Brain-Provider konfiguriert. "
                "Setze mindestens GEMINI_API_KEY oder ANTHROPIC_API_KEY.")

    missing_keys: list[str] = []
    invalid_keys: list[str] = []
    account_blocked: list[str] = []
    vision_unsupported: list[str] = []
    invalid_models: list[str] = []
    context_overflow: list[str] = []
    local_context: list[str] = []
    rate_limited: list[str] = []
    empty_responses: list[str] = []
    other_fails: list[str] = []
    for prov_name, _model, kind, _detail in errors:
        if kind == "missing_key":
            missing_keys.append(prov_name)
        elif kind == "bad_key":
            invalid_keys.append(prov_name)
        elif kind == "account_blocked":
            account_blocked.append(prov_name)
        elif kind == "vision_unsupported":
            vision_unsupported.append(prov_name)
        elif kind == "invalid_model":
            invalid_models.append(prov_name)
        elif kind == "context_overflow":
            context_overflow.append(prov_name)
        elif kind == "local_context":
            # The guard's own sentence carries the sizes and the setting.
            local_context.append(_detail or prov_name)
        elif kind in ("rate_limit", "skipped_cooldown"):
            rate_limited.append(prov_name)
        elif kind == "empty_response":
            empty_responses.append(prov_name)
        else:
            other_fails.append(prov_name)

    # Deduplicate while preserving order (first-listed priority).
    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    missing_keys = _uniq(missing_keys)
    invalid_keys = _uniq(invalid_keys)
    account_blocked = _uniq(account_blocked)
    vision_unsupported = _uniq(vision_unsupported)
    invalid_models = _uniq(invalid_models)
    context_overflow = _uniq(context_overflow)
    rate_limited = _uniq(rate_limited)
    empty_responses = _uniq(empty_responses)
    other_fails = _uniq(other_fails)

    parts: list[str] = []
    # 1. Setup hint for the most important missing keys (max 2).
    # Priority: Sidebar → API Keys is the easiest setup path for non-coders.
    # Specific ENV/CLI hints for power users come after.
    if missing_keys:
        hints = [
            _PROVIDER_SETUP_HINTS.get(p, f"{p}: Setup pruefen")
            for p in missing_keys[:2]
        ]
        parts.append(
            "Kein Brain-Key gefunden. Sidebar -> API-Keys oeffnen und "
            f"einen Key setzen ({' oder '.join(hints)})."
        )
    # 1b. Invalid/expired key (a 401 — the stored key is rejected, not absent).
    if invalid_keys:
        parts.append(
            f"Key abgelehnt bei {', '.join(invalid_keys)} (ungueltig oder abgelaufen). "
            "Sidebar -> API-Keys: Key ersetzen."
        )
    # 2. Account block (credit/quota/tier) — user must take action
    if account_blocked:
        parts.append(
            f"Account-Problem bei {', '.join(account_blocked)}: "
            "Credit aufladen, Plan upgraden oder Modell-Tier freischalten. "
            "Bei Anthropic: console.anthropic.com/settings/billing. "
            "Bei xAI: console.x.ai/team/billing."
        )
    if vision_unsupported:
        parts.append(
            f"Kein Bildverstehen bei {', '.join(vision_unsupported)} — "  # i18n-allow
            "der Key ist da, aber das Modell sieht keine Bilder. "  # i18n-allow
            "Unter API-Keys einen Anbieter mit Bildverarbeitung aktivieren."  # i18n-allow
        )
    if invalid_models:
        parts.append(
            f"Ungueltige Model-ID bei {', '.join(invalid_models)}. "
            "jarvis.toml und TIER_DEFAULTS_BY_PROVIDER pruefen."
        )
    # 1c. The request was larger than the model's context window — a size
    # problem of THIS request, not a network one (live 2026-08-27: a 32k
    # local model, 221 tools, "check the network").
    if context_overflow:
        parts.append(
            f"Anfrage zu gross fuer das Kontextfenster von {', '.join(context_overflow)}. "
            "Modell mit groesserem Kontext waehlen, verbundene MCP-Server "
            "reduzieren oder einen neuen Chat starten."
        )
    if local_context:
        parts.append(" ".join(_uniq(local_context)))
    # 2. Rate limits are listed as supplementary info
    if rate_limited:
        prefix = "Ausserdem rate" if parts else "Rate"
        parts.append(
            f"{prefix}-limited: {', '.join(rate_limited)}. "
            "Einen Moment abwarten oder auf anderen Provider wechseln."
        )
    # 3. Empty responses (safety block) — separate user-actionable case
    if empty_responses and not missing_keys and not invalid_models:
        parts.append(
            f"Provider {', '.join(empty_responses)} hat leer geantwortet "
            "(vermutlich Safety-Filter). Anders formulieren oder anderen "
            "Provider per UI aktivieren."
        )
    # 4. Other failures only mentioned when there is no clear root cause
    if (not missing_keys and not invalid_models and not context_overflow
            and not local_context
            and not rate_limited and not empty_responses and other_fails):
        parts.append(
            f"Provider {', '.join(other_fails)} unerreichbar. "
            "Netzwerk pruefen."
        )
    return " ".join(parts)
