"""Command definitions: pull requests.

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
            id="pull-requests-list",
            title="List the user's open pull requests",
            description=(
                "The user's open pull requests on GitHub across their repositories, and the "
                "ones that wait for their review, each with its checks (passing, failing, "
                "running), review state, draft, conflicts and merge queue. One read through "
                "the GitHub connection: use it, not the shell, for 'how are my pull requests'."
            ),
            method="GET", path="/api/agentic-ide/git/github/pull-requests",
            ui_section="agentic-ide",
            params={"type": "object", "properties": {
                "limit": {"type": "integer", "description": "At most this many per group (30)."},
            }},
            voice_aliases={
                "de": ("wie stehen meine pull requests",),  # i18n-allow: input vocab
                "en": ("how are my pull requests",),
                "es": ("cómo van mis pull requests",),  # i18n-allow: input vocab
                "pt": ("como estão os meus pull requests",),  # i18n-allow: input vocab
            },
        ),
    )
