"""Command definitions: marketplace.

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
            id="marketplace-browse",
            title="Browse the marketplace",
            description=(
                "List everything the community marketplace publishes — skills "
                "and plugins — with the exact name of each entry and "
                "whether it is already installed. Use this to find the name "
                "before installing, and to answer 'what is there to install'."
            ),
            method="GET",
            path="/api/marketplace/community",
            params={"type": "object", "properties": {}},
            ui_section="plugins",
            voice_aliases={
                "de": (  # i18n-allow: input vocab
                    "was gibt es im marktplatz",
                    "welche skills kann ich installieren",  # i18n-allow: input vocab
                ),
                "en": (
                    "what is in the marketplace",
                    "which skills can i install",
                ),
                "es": (  # i18n-allow: input vocab
                    "qué hay en el mercado",
                    "qué skills puedo instalar",
                ),
                "pt": (  # i18n-allow: input vocab
                    "o que há no mercado",
                    "que skills posso instalar",
                ),
            },
        ),
        AppCommand(
            id="marketplace-install",
            title="Install from the marketplace",
            description=(
                "Install ONE published marketplace entry by its exact name. The "
                "kind is resolved by the app, so the same command installs a "
                "skill or a plugin. What the user gets differs and the answer "
                "must say so: a skill is usable right away, a plugin only lands "
                "on the plugin list and stays powerless until the user connects "
                "their account. Look the name up with marketplace-browse first "
                "rather than guessing it; report the result the tool returns."
            ),
            method="POST",
            path="/api/marketplace/community/install/{item_id}",
            # Installing pulls somebody else's published content onto this
            # machine — a plugin brings an outside MCP server with it. That is
            # never something a spoken sentence should do unconfirmed, so the
            # tier is `ask` even though the CLI path heuristic sees nothing
            # destructive here.
            dangerous=True,
            params={
                "type": "object",
                "properties": {
                    "item_id": _str_param(
                        "Exact published name of the entry to install, as shown "
                        "by marketplace-browse (e.g. three-bullet-brief).",
                        min_length=1,
                        max_length=128,
                    ),
                },
                "required": ["item_id"],
            },
            path_params=("item_id",),
            ui_section="plugins",
            voice_aliases={
                "de": (  # i18n-allow: input vocab
                    "installier den skill",
                    "installier das plugin aus dem marktplatz",  # i18n-allow: input vocab
                ),
                "en": (
                    "install that skill",
                    "install that plugin from the marketplace",
                ),
                "es": (  # i18n-allow: input vocab
                    "instala ese skill",
                    "instala ese complemento del mercado",
                ),
                "pt": (  # i18n-allow: input vocab
                    "instala essa skill",
                    "instala esse plugin do mercado",
                ),
            },
        ),
        AppCommand(
            id="marketplace-remove",
            title="Remove a marketplace entry",
            description=(
                "Remove ONE installed marketplace entry by its exact name. The "
                "kind is resolved by the app: a plugin is disconnected and "
                "leaves the plugin list, a skill is deleted from the skills. "
                "An agent is not removed this way; the answer says so. Only "
                "what was installed from the marketplace can be removed here."
            ),
            method="DELETE",
            path="/api/marketplace/community/install/{item_id}",
            dangerous=True,
            params={
                "type": "object",
                "properties": {
                    "item_id": _str_param(
                        "Exact name of the installed entry to remove, as shown "
                        "by marketplace-browse (e.g. three-bullet-brief).",
                        min_length=1,
                        max_length=128,
                    ),
                },
                "required": ["item_id"],
            },
            path_params=("item_id",),
            ui_section="plugins",
            voice_aliases={
                "de": (  # i18n-allow: input vocab
                    "entferne den skill aus dem marktplatz",  # i18n-allow: input vocab
                    "deinstalliere das marktplatz plugin",  # i18n-allow: input vocab
                ),
                "en": (
                    "remove that marketplace skill",
                    "uninstall that marketplace plugin",
                ),
                "es": (  # i18n-allow: input vocab
                    "quita ese skill del mercado",
                    "desinstala ese complemento del mercado",
                ),
                "pt": (  # i18n-allow: input vocab
                    "remove essa skill do mercado",
                    "desinstala esse plugin do mercado",
                ),
            },
        ),
    )
