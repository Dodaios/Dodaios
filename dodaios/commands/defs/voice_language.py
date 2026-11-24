"""Command definitions: voice language.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    REPLY_LANGUAGES,
    AppCommand,
    _str_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="reply-language-set",
            title="Set reply language",
            description=(
                "Pin the language Dodaios answers in (auto follows the spoken "
                "language)."
            ),
            method="PUT",
            path="/api/settings/reply-language",
            params={
                "type": "object",
                "properties": {
                    "language": _str_param(
                        "Reply language.", enum=list(REPLY_LANGUAGES)
                    ),
                    "persist": {
                        "type": "boolean", "default": True,
                        "description": "Persist as boot default.",
                    },
                },
                "required": ["language"],
            },
            ui_section="languages",
            voice_aliases={
                "de": ("antworte ab jetzt auf englisch",),  # i18n-allow: input vocab
                "en": ("answer in german from now on",),
                "es": ("responde en inglés a partir de ahora",),  # i18n-allow: input vocab
                "pt": (  # i18n-allow: input vocab
                    "responde em inglês a partir de agora",  # i18n-allow: input vocab
                    "responde em português",  # i18n-allow: input vocab
                    "fala português",  # i18n-allow: input vocab
                    "fala comigo em português",  # i18n-allow: input vocab
                ),
            },
        ),
        AppCommand(
            id="wake-word-get",
            title="Show wake word",
            description="Show the current wake word and wake-engine settings.",
            method="GET",
            path="/api/settings/wake-word",
            worker_allowed=True,
            ui_section="settings",
            voice_aliases={
                "de": ("wie lautet mein wake word",),  # i18n-allow: input vocab
                "en": ("what is my wake word",),
                "es": ("cuál es mi palabra de activación",),  # i18n-allow: input vocab
                "pt": ("qual é a minha palavra de ativação",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="wake-word-set",
            title="Change wake word",
            description="Set the phrase that wakes Dodaios up.",
            method="PUT",
            path="/api/settings/wake-word",
            params={
                "type": "object",
                "properties": {
                    "phrase": _str_param(
                        "The new wake phrase.", min_length=1, max_length=64
                    ),
                },
                "required": ["phrase"],
            },
            ui_section="settings",
            voice_aliases={
                "de": ("ändere mein wake word zu nova",),  # i18n-allow: input vocab
                "en": ("change my wake word to nova",),
                "es": ("cambia mi palabra de activación a nova",),  # i18n-allow: input vocab
                "pt": ("muda a minha palavra de ativação para nova",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="tts-volume-set",
            title="Set voice volume",
            description="Set the text-to-speech output volume (0.0 to 1.0).",
            method="PUT",
            path="/api/settings/tts-volume",
            params={
                "type": "object",
                "properties": {
                    "volume": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                        "description": "Output volume between 0.0 and 1.0.",
                    },
                    "persist": {
                        "type": "boolean", "default": True,
                        "description": "Persist as boot default.",
                    },
                },
                "required": ["volume"],
            },
            ui_section="settings",
            voice_aliases={
                "de": ("stell die lautstärke auf 50 prozent",),  # i18n-allow: input vocab
                "en": ("set the voice volume to 50 percent",),
                "es": ("pon el volumen de la voz al 50 por ciento",),  # i18n-allow: input vocab
                "pt": ("põe o volume da voz a 50 por cento",),  # i18n-allow: input vocab
            },
        ),
    )
