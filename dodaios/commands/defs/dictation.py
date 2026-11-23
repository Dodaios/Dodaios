"""Command definitions: dictation.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    AppCommand,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="dictation-start",
            title="Start dictation",
            description=(
                "Start dictation: speak, and the transcribed text is inserted "
                "into whatever text field currently has focus. Stops with "
                "dictation-stop or the dictation shortcut."
            ),
            method="POST",
            path="/api/dictation/start",
            params={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["insert", "chat"],
                        "description": (
                            "insert = paste into the app in front; "
                            "chat = fill the chat input only"
                        ),
                    }
                },
            },
            ui_section="dictation",
            voice_aliases={
                "de": ("starte das diktat", "diktier-modus an"),  # i18n-allow: input vocab
                "en": ("start dictation", "turn on dictation mode"),
                "es": ("inicia el dictado", "activa el modo dictado"),  # i18n-allow: input vocab
                "pt": ("começa o ditado", "ativa o modo de ditado"),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="dictation-stop",
            title="Stop dictation",
            description="Finish the running dictation and deliver the text.",
            method="POST",
            path="/api/dictation/stop",
            ui_section="dictation",
            voice_aliases={
                "de": ("stopp das diktat", "diktier-modus aus"),  # i18n-allow: input vocab
                "en": ("stop dictation", "turn off dictation mode"),
                "es": ("detén el dictado", "desactiva el modo dictado"),  # i18n-allow: input vocab
                "pt": ("para o ditado", "desativa o modo de ditado"),  # i18n-allow: input vocab
            },
        ),
    )
