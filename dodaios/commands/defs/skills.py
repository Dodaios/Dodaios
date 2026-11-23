"""Command definitions: skills.

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
        # The lifecycle of an installed skill by voice — the sibling of the
        # create-skill router tool (which WRITES a skill). Live gap 2026-08-18:
        # a voice-authored skill lands as a draft, and "aktiviere den Skill
        # Morgenroutine" had no tool at all — the model could only discover
        # `jarvisctl skills enable` through help rounds. Every entry maps to
        # the same route the Skills view calls. Enabling a DRAFT is the human
        # promotion AP-15 requires and is asked for out loud, so it needs no
        # second confirmation; deleting a skill removes a file the user wrote
        # or authored — dangerous, echo-confirmed. None is worker_allowed: a
        # mission worker has no business switching the user's skills (AP-5).
        AppCommand(
            id="skills-list",
            title="List installed skills",
            description=(
                "List the installed skills with their state (active, draft, "
                "disabled) and what starts each one. Use this when the user asks "
                "which skills they have or which are drafts / switched off."
            ),
            method="GET",
            path="/api/skills/brief",
            params={"type": "object", "properties": {}},
            ui_section="skills",
            voice_aliases={
                "de": ("welche skills habe ich", "zeig mir meine skills"),  # i18n-allow: vocab
                "en": ("which skills do i have", "show me my skills"),
                "es": ("qué skills tengo", "muéstrame mis skills"),  # i18n-allow: vocab
                "pt": ("que skills tenho", "mostra-me as minhas skills"),  # i18n-allow: vocab
            },
        ),
        AppCommand(
            id="skill-enable",
            title="Enable a skill",
            description=(
                "Switch an installed skill ON by name — this is how a draft the "
                "assistant just wrote (create-skill) or a disabled skill starts "
                "firing on its trigger phrase and schedule. Use the exact skill "
                "name; list the skills first when unsure."
            ),
            method="POST",
            path="/api/skills/{name}/enable",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Exact name of the skill to switch on.", min_length=1, max_length=120
                    ),
                },
                "required": ["name"],
            },
            path_params=("name",),
            ui_section="skills",
            voice_aliases={
                "de": ("aktiviere den skill", "schalte den skill ein"),  # i18n-allow: input vocab
                "en": ("enable the skill", "switch the skill on"),
                "es": ("activa el skill",),  # i18n-allow: input vocab
                "pt": ("ativa a skill",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="skill-disable",
            title="Disable a skill",
            description=(
                "Switch an installed skill OFF by name — it stops firing on its "
                "trigger phrase and schedule but stays installed. Use the exact "
                "skill name; list the skills first when unsure."
            ),
            method="POST",
            path="/api/skills/{name}/disable",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Exact name of the skill to switch off.", min_length=1, max_length=120
                    ),
                },
                "required": ["name"],
            },
            path_params=("name",),
            ui_section="skills",
            voice_aliases={
                "de": ("deaktiviere den skill", "schalte den skill aus"),  # i18n-allow: input vocab
                "en": ("disable the skill", "switch the skill off"),
                "es": ("desactiva el skill",),  # i18n-allow: input vocab
                "pt": ("desativa a skill",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="skill-delete",
            title="Delete a skill",
            description=(
                "Delete an installed user skill by name — removes its folder for "
                "good (built-in skills cannot be deleted; disable them instead)."
            ),
            method="DELETE",
            path="/api/skills/{name}",
            params={
                "type": "object",
                "properties": {
                    "name": _str_param(
                        "Exact name of the skill to delete.", min_length=1, max_length=120
                    ),
                },
                "required": ["name"],
            },
            path_params=("name",),
            dangerous=True,
            ui_section="skills",
            voice_aliases={
                "de": ("lösch den skill",),  # i18n-allow: input vocab
                "en": ("delete the skill",),
                "es": ("elimina el skill",),  # i18n-allow: input vocab
                "pt": ("apaga a skill",),  # i18n-allow: input vocab
            },
        ),
    )
