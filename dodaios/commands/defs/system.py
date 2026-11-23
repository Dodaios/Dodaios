"""Command definitions: system.

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
            id="app-restart",
            title="Restart Dodaios",
            description="Restart the Dodaios desktop app (voice + UI restart too).",
            method="POST",
            path="/api/settings/restart-app",
            dangerous=True,
            ui_section="settings",
            voice_aliases={
                "de": ("starte jarvis neu",),  # i18n-allow: input vocab
                "en": ("restart jarvis",),
                "es": ("reinicia jarvis",),  # i18n-allow: input vocab
                "pt": ("reinicia o jarvis",),  # i18n-allow: input vocab
            },
        ),
    )
