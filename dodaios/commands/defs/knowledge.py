"""Command definitions: knowledge.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    AppCommand,
    _str_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="session-latest-turn",
            title="Show latest voice turn",
            description=(
                "Return the latest persisted user transcript and its complete "
                "voice turn, optionally restricted to one session."
            ),
            method="GET",
            path="/api/sessions/latest-turn",
            worker_allowed=True,
            params={
                "type": "object",
                "properties": {
                    "session_id": _str_param(
                        "Optional voice-session id.", min_length=1, max_length=128
                    ),
                },
            },
            ui_section="sessions",
            voice_aliases={
                "de": ("lies die letzte transkription",),  # i18n-allow: input vocab
                "en": ("read the latest transcript",),
                "es": ("lee la última transcripción",),  # i18n-allow: input vocab
                "pt": ("lê a última transcrição",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="tools-list",
            title="List effective tools",
            description=(
                "Return the effective live Brain tool surface, including native, "
                "connected CLI, Marketplace, and MCP tools."
            ),
            method="GET",
            # The brief listing, deliberately not /api/tools: the full route
            # serializes every schema (50-200k chars) and the tool-result cap
            # slices that mid-JSON (2026-07-28 cost audit).
            path="/api/tools/brief",
            worker_allowed=True,
            params={"type": "object", "properties": {}},
            ui_section="settings",
            voice_aliases={
                "de": ("welche tools mcps und clis sind verbunden",),  # i18n-allow: input vocab
                "en": ("list the connected tools mcps and clis",),
                "es": ("lista las herramientas mcps y clis conectadas",),  # i18n-allow: input vocab
                "pt": ("lista as ferramentas mcps e clis ligadas",),  # i18n-allow: input vocab
            },
        ),
    )
