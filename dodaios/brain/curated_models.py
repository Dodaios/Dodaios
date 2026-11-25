"""Curated per-provider model rosters and :class:`ModelInfo` metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """One selectable model: the wire ``id`` plus a human ``label``.

    ``output_modalities`` carries the provider's declared output kinds (e.g.
    ``("text",)`` or ``("text", "image")``) when available — OpenRouter returns
    it under ``architecture.output_modalities``; direct provider ``/v1/models``
    endpoints do not, so it stays ``None`` there. A tuple (not a list) keeps the
    dataclass frozen/hashable. Used by :func:`filter_brain_models` to exclude
    image/audio/video GENERATION models that a name-substring blocklist misses
    (e.g. ``openrouter/auto``)."""

    id: str
    label: str
    output_modalities: tuple[str, ...] | None = None
    # H4/H5: per-model capability hints from OpenRouter's /v1/models
    # (``architecture.input_modalities`` + ``supported_parameters``). ``None`` when
    # the provider endpoint doesn't expose them → callers default to "capable" (no
    # regression). ``"image" in input_modalities`` ⇒ vision; ``"tools" in
    # supported_parameters`` ⇒ tool-calling.
    input_modalities: tuple[str, ...] | None = None
    supported_parameters: tuple[str, ...] | None = None
    # (input, output) in USD per 1M tokens, straight from the provider's own
    # feed (OpenRouter publishes ``pricing.prompt`` / ``pricing.completion``
    # per token). ``None`` when the endpoint has no price data. This is what
    # lets cost tracking price a model the static table in
    # ``dodaios/brain/cost.py`` has never heard of — the table used to be the
    # only source, and every new model generation shipped as "$0.00" until
    # someone noticed (2026-07-28 and 2026-08-18 audits).
    pricing: tuple[float, float] | None = None
    # Declared token limits from provider catalogs or Ollama's /api/show.
    # Unknown limits remain None; runtime adapters use conservative defaults.
    # Native context also caps the local model option sheet's num_ctx chips.
    context_length: int | None = None
    max_output_tokens: int | None = None
    quantization_level: str | None = None
    parameter_size: str | None = None
    # Release time (Unix seconds) where the catalog publishes one — OpenRouter
    # and OpenAI send ``created``. Public discovery (``discovered_from_feed``)
    # uses it to admit only models released within the last year.
    created: float | None = None


def _curated(pairs: list[tuple[str, str]]) -> list[ModelInfo]:
    return [ModelInfo(id=i, label=lbl) for i, lbl in pairs]


# Curated current model families per provider — the picker's fallback when the
# live ``/v1/models`` catalog is unreachable (no/invalid key, network down). This
# is what makes the dropdown useful for providers the user drives WITHOUT an API
# key: Claude in particular runs via the Max subscription (OAuth), so its live
# fetch always 401s — the user still expects to pick Fable / Opus / Sonnet /
# Haiku. Keep these to the *current* frontier families (maintainer mandate: never
# offer a years-old model); when a valid key exists the live catalog supersedes
# this entirely, so a new release still shows up automatically there.
CURATED_MODELS: dict[str, list[ModelInfo]] = {
    "claude-api": _curated(
        [
            ("claude-fable-5-2", "Claude Fable 5.2"),
            ("claude-opus-5-5", "Claude Opus 5.5"),
            ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
            ("claude-haiku-5-5", "Claude Haiku 5.5"),
            ("claude-fable-5-1", "Claude Fable 5.1"),
            ("claude-fable-5", "Claude Fable 5"),
            ("claude-opus-5", "Claude Opus 5"),
            ("claude-opus-4-8", "Claude Opus 4.8"),
            ("claude-sonnet-5", "Claude Sonnet 5"),
            ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ]
    ),
    "openai": _curated(
        [
            ("gpt-6.2-sol", "GPT-6.2 Sol"),
            ("gpt-6.2-astra", "GPT-6.2 Astra"),
            ("gpt-6.2-sol-pro", "GPT-6.2 Sol Pro"),
            ("gpt-6.2-astra-pro", "GPT-6.2 Astra Pro"),
            ("gpt-6.1-terra", "GPT-6.1 Terra"),
            ("gpt-6.1-sol", "GPT-6.1 Sol"),
            ("gpt-6.1-terra-pro", "GPT-6.1 Terra Pro"),
            ("gpt-6.1-sol-pro", "GPT-6.1 Sol Pro"),
            ("gpt-6-sol", "GPT-6 Sol"),
            ("gpt-6-astra", "GPT-6 Astra"),
            ("gpt-6-luna", "GPT-6 Luna"),
            ("gpt-6-sol-pro", "GPT-6 Sol Pro"),
            ("gpt-6-astra-pro", "GPT-6 Astra Pro"),
            ("gpt-6-luna-pro", "GPT-6 Luna Pro"),
            ("gpt-5.6-sol", "GPT-5.6 Sol (preview)"),
            ("gpt-5.6-terra", "GPT-5.6 Terra (preview)"),
            ("gpt-5.6-luna", "GPT-5.6 Luna (preview)"),
            ("gpt-5.6", "GPT-5.6 (Sol alias, preview)"),
            ("gpt-5.5", "GPT-5.5"),
            ("gpt-5.5-pro", "GPT-5.5 Pro"),
            ("gpt-5.4", "GPT-5.4"),
            ("gpt-5.4-pro", "GPT-5.4 Pro"),
            ("gpt-5.4-mini", "GPT-5.4 Mini"),
            ("gpt-5.4-nano", "GPT-5.4 Nano"),
        ]
    ),
    "gemini": _curated(
        [
            ("gemini-4-neon", "Gemini 4 Neon"),
            ("gemini-4-hydrogen", "Gemini 4 Hydrogen"),
            ("gemini-4-carbon", "Gemini 4 Carbon"),
            ("gemini-4-argon", "Gemini 4 Argon"),
            ("gemini-3.8-flash", "Gemini 3.8 Flash"),
            ("gemini-3.7-flash", "Gemini 3.7 Flash"),
            ("gemini-3.6-flash", "Gemini 3.6 Flash"),
            ("gemini-3.5-flash", "Gemini 3.5 Flash"),
            ("gemini-3.1-pro-preview", "Gemini 3.1 Pro"),
            ("gemini-3-flash-preview", "Gemini 3 Flash"),
            ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("gemini-flash-lite-latest", "Gemini Flash Lite"),
        ]
    ),
    "openrouter": _curated(
        [
            ("anthropic/claude-fable-5.2", "Claude Fable 5.2"),
            ("anthropic/claude-opus-5.5", "Claude Opus 5.5"),
            ("anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5"),
            ("anthropic/claude-haiku-5.5", "Claude Haiku 5.5"),
            ("anthropic/claude-fable-5.1", "Claude Fable 5.1"),
            ("anthropic/claude-fable-5", "Claude Fable 5"),
            ("anthropic/claude-opus-4.8", "Claude Opus 4.8"),
            ("anthropic/claude-sonnet-5", "Claude Sonnet 5"),
            ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5"),
            ("openai/gpt-6.2-sol-pro", "GPT-6.2 Sol Pro"),
            ("openai/gpt-6.2-sol", "GPT-6.2 Sol"),
            ("openai/gpt-6.2-astra-pro", "GPT-6.2 Astra Pro"),
            ("openai/gpt-6.2-astra", "GPT-6.2 Astra"),
            ("openai/gpt-6.1-terra-pro", "GPT-6.1 Terra Pro"),
            ("openai/gpt-6.1-terra", "GPT-6.1 Terra"),
            ("openai/gpt-6.1-sol-pro", "GPT-6.1 Sol Pro"),
            ("openai/gpt-6.1-sol", "GPT-6.1 Sol"),
            ("openai/gpt-6-sol", "GPT-6 Sol"),
            ("openai/gpt-6-astra", "GPT-6 Astra"),
            ("openai/gpt-6-luna", "GPT-6 Luna"),
            ("openai/gpt-5.6-sol-pro", "GPT-5.6 Sol Pro"),
            ("openai/gpt-5.6-sol", "GPT-5.6 Sol"),
            ("openai/gpt-5.6-terra-pro", "GPT-5.6 Terra Pro"),
            ("openai/gpt-5.6-terra", "GPT-5.6 Terra"),
            ("openai/gpt-5.6-luna-pro", "GPT-5.6 Luna Pro"),
            ("openai/gpt-5.6-luna", "GPT-5.6 Luna"),
            ("google/gemini-4-neon", "Gemini 4 Neon"),
            ("google/gemini-4-hydrogen", "Gemini 4 Hydrogen"),
            ("google/gemini-4-carbon", "Gemini 4 Carbon"),
            ("google/gemini-4-argon", "Gemini 4 Argon"),
            ("google/gemini-3.8-flash", "Gemini 3.8 Flash"),
            ("google/gemini-3.5-flash", "Gemini 3.5 Flash"),
            ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro"),
            ("x-ai/grok-4.7", "Grok 4.7"),
            ("x-ai/grok-4.20", "Grok 4.20"),
            ("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
            ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro"),
        ]
    ),
    # Grok 4.3 leads because it is the universal default — the newer families
    # are not available in every region, and this list is only the OFFLINE
    # fallback, so its head is what a downloader with no live catalog gets.
    # It must stay in step with ``dodaios.plugins.brain.grok.DEFAULT_MODEL``
    # (pinned by test_grok_has_authenticated_live_model_catalog): 4.6 was
    # inserted at the head without moving the default, which offered a model
    # as the pre-selected one that the client would not actually have used.
    # Grok 4.7 (2026-09-21) is in the list, not at its head, for that reason.
    # The authenticated live catalog replaces this fallback entirely.
    # Grok Build does not use this order: ``GROK_BUILD_MODELS`` leads with 4.7.
    "grok": _curated(
        [
            ("grok-4.3", "Grok 4.3"),
            ("grok-4.7", "Grok 4.7"),
            ("grok-4.6", "Grok 4.6"),
            ("grok-4.5", "Grok 4.5"),
        ]
    ),
    # NVIDIA NIM — the offline fallback when the live /v1/models catalog is
    # unreachable. NVIDIA-hosted current families (Nemotron leads: it is NVIDIA's
    # own). A valid key supersedes this with the live list, so a newly hosted
    # model still shows up automatically.
    "deepseek": [
        ModelInfo(id="deepseek-flash", label="DeepSeek Flash", input_modalities=("text",)),
        ModelInfo(id="deepseek-v4-pro", label="DeepSeek V4 Pro", input_modalities=("text",)),
    ],
    "nvidia": _curated(
        [
            ("nvidia/llama-3.1-nemotron-ultra-253b-v1", "Nemotron Ultra 253B"),
            ("nvidia/llama-3.3-nemotron-super-49b-v1.5", "Nemotron Super 49B v1.5"),
            ("deepseek-ai/deepseek-v4-pro", "DeepSeek V4 Pro"),
            ("deepseek-ai/deepseek-v4-flash", "DeepSeek V4 Flash"),
            ("moonshotai/kimi-k2.6", "Kimi K2.6"),
            ("z-ai/glm-5.2", "GLM-5.2"),
            ("qwen/qwen3.5-397b-a17b", "Qwen3.5 397B A17B"),
            ("meta/llama-4-maverick-17b-128e-instruct", "Llama 4 Maverick"),
            ("mistralai/mistral-large-3-675b-instruct-2512", "Mistral Large 3"),
        ]
    ),
}


#: Grok Build's picker. The subscription login has no /v1/models, so this
#: list is what the create-agent dialog and the IDE pane offer. grok-4.7
#: leads: it is the current default of the Grok Build CLI (xAI, 2026-09-21).
#: The API fallback in ``CURATED_MODELS["grok"]`` must not copy this order —
#: its head is the client default, ``grok-4.3``.
GROK_BUILD_MODELS: tuple[tuple[str, str], ...] = (
    ("grok-4.7", "Grok 4.7"),
    ("grok-4.7-build-fast", "Grok 4.7 Fast"),
    ("grok-4.6", "Grok 4.6"),
    ("grok-4.5", "Grok 4.5"),
    ("grok-4.3", "Grok 4.3"),
)
