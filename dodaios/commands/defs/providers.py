"""Command definitions: providers.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    AppCommand,
    _all_provider_ids,
    _provider_switch_params,
    _str_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="brain-switch",
            title="Switch brain provider",
            description=(
                "Switch the ACTIVE main brain (LLM) provider, e.g. from openai "
                "to claude-api. Reversible; validated against the provider "
                "catalog and stored credentials."
            ),
            method="POST",
            path="/api/brain/switch",
            params=_provider_switch_params("brain", brain_switchable_only=True),
            ui_section="apikeys",
            voice_aliases={
                "de": ("wechsle den brain-provider zu claude",),  # i18n-allow: input vocab
                "en": ("switch the brain provider to claude",),
                "es": ("cambia el proveedor del cerebro a claude",),  # i18n-allow: input vocab
                "pt": ("muda o fornecedor do cérebro para claude",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="tts-switch",
            title="Switch voice (TTS) provider",
            description="Switch the active text-to-speech provider (live, no restart).",
            method="POST",
            path="/api/tts/switch",
            params=_provider_switch_params("tts"),
            ui_section="apikeys",
            voice_aliases={
                "de": ("wechsle die stimme zu elevenlabs",),  # i18n-allow: input vocab
                "en": ("switch the voice to elevenlabs",),
                "es": ("cambia la voz a elevenlabs",),  # i18n-allow: input vocab
                "pt": ("muda a voz para elevenlabs",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="stt-switch",
            title="Switch speech-recognition (STT) provider",
            description=(
                "Switch the speech-to-text provider used for dictation. Takes "
                "effect on the next dictation."
            ),
            method="POST",
            path="/api/stt/switch",
            params=_provider_switch_params("stt"),
            ui_section="apikeys",
            voice_aliases={
                "de": ("wechsle die spracherkennung zu deepgram",),  # i18n-allow: input vocab
                "en": ("switch speech recognition to deepgram",),
                "es": ("cambia el reconocimiento de voz a deepgram",),  # i18n-allow: input vocab
                "pt": ("muda o reconhecimento de voz para deepgram",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="realtime-switch",
            title="Switch realtime voice provider",
            description=(
                "Switch which realtime voice engine (speech-to-speech) is "
                "active, including subscription- and API-backed providers. "
                "Experimental transports require explicit acknowledgement."
            ),
            method="POST",
            path="/api/realtime/switch",
            params=_provider_switch_params(
                "realtime",
                allow_experimental_ack=True,
            ),
            ui_section="apikeys",
            voice_aliases={
                "de": ("wechsle das realtime-modell zu gemini",),  # i18n-allow: input vocab
                "en": ("switch the realtime model to gemini",),
                "es": ("cambia el modelo en tiempo real a gemini",),  # i18n-allow: input vocab
                "pt": ("muda o modelo em tempo real para gemini",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="local-realtime-models-set",
            title="Configure local realtime models",
            description=(
                "Select the Ollama brain and speech model for the managed local "
                "realtime server, then activate them only after a voice test."
            ),
            method="POST",
            path="/api/providers/local-realtime/managed-server/setup",
            params={
                "type": "object",
                "properties": {
                    "brain_model": _str_param(
                        "Exact Ollama model tag.", min_length=1, max_length=201
                    ),
                    "voice_model": _str_param(
                        "Managed speech-model profile id.",
                        enum=["qwen3-tts-1.7b", "qwen3-tts-0.6b"],
                    ),
                },
                "required": ["brain_model", "voice_model"],
            },
            dangerous=True,
            ui_section="apikeys",
            voice_aliases={
                "de": ("stelle die lokalen sprachmodelle um",),  # i18n-allow: input vocab
                "en": ("change the local realtime models",),
                "es": ("cambia los modelos de voz locales",),  # i18n-allow: input vocab
                "pt": ("muda os modelos de voz locais",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="computer-use-switch",
            title="Switch Computer-Use provider",
            description=(
                "Switch the dedicated Computer-Use planner provider (screen "
                "control), decoupled from the main brain."
            ),
            method="POST",
            path="/api/computer-use/switch",
            params=_provider_switch_params("brain"),
            ui_section="apikeys",
            voice_aliases={
                "de": ("wechsle den computer-use-provider zu gemini",),  # i18n-allow: input vocab
                "en": ("switch the computer use provider to gemini",),
                "es": ("cambia el proveedor de computer use a gemini",),  # i18n-allow: input vocab
                "pt": ("muda o fornecedor de computer use para gemini",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="jarvis-agent-switch",
            title="Switch mission-worker provider",
            description=(
                "Switch the provider used for new missions (e.g. codex to "
                "openai). The next mission uses the new provider."
            ),
            method="POST",
            path="/api/jarvis-agent/switch",
            params=_provider_switch_params("brain"),
            ui_section="agents",
            voice_aliases={
                "de": ("wechsle den agent-provider zu openai",),  # i18n-allow: input vocab
                "en": ("switch the agent provider to openai",),
                "es": ("cambia el proveedor del agente a openai",),  # i18n-allow: input vocab
                "pt": ("muda o fornecedor do agente para openai",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="providers-list",
            title="List providers",
            description="List all configured providers and which ones are active.",
            method="GET",
            path="/api/providers",
            worker_allowed=True,
            ui_section="apikeys",
            voice_aliases={
                "de": ("welche provider sind konfiguriert",),  # i18n-allow: input vocab
                "en": ("which providers are configured",),
                "es": ("qué proveedores están configurados",),  # i18n-allow: input vocab
                "pt": ("que fornecedores estão configurados",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="provider-test",
            title="Test a provider",
            description="Test connectivity and authentication for one provider.",
            method="POST",
            path="/api/providers/{provider_id}/test",
            params={
                "type": "object",
                "properties": {
                    "provider_id": _str_param(
                        "Provider id to test.", enum=_all_provider_ids() or None,
                        min_length=1,
                    ),
                },
                "required": ["provider_id"],
            },
            path_params=("provider_id",),
            worker_allowed=True,
            ui_section="apikeys",
            voice_aliases={
                "de": ("teste den openai-provider",),  # i18n-allow: input vocab
                "en": ("test the openai provider",),
                "es": ("prueba el proveedor de openai",),  # i18n-allow: input vocab
                "pt": ("testa o fornecedor openai",),  # i18n-allow: input vocab
            },
        ),
    )
