"""Command definitions: rituals.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    _RITUAL_GUIDE,
    AppCommand,
    _ritual_properties,
    _ritual_ref_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="ritual-list",
            title="List the user's rituals",
            description=(
                _RITUAL_GUIDE + "Lists every ritual with phrases, steps, times and today's state. Read it "
                "before changing one."
            ),
            method="GET", path="/api/agent-chat/lead/rituals", ui_section="chats",
            voice_aliases={
                "de": ("welche rituale habe ich",),  # i18n-allow: input vocab
                "en": ("which rituals do i have",),
                "es": ("qué rituales tengo",),  # i18n-allow: input vocab
                "pt": ("que rituais tenho",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="ritual-create",
            title="Write a ritual for the user",
            description=(
                _RITUAL_GUIDE + "Write the steps as the user said them and sort them "
                "'ahead' or 'now'. Do not run the steps now. Tell the user the phrase that "
                "starts it; a refusal names what to change."
            ),
            # Not dangerous: the user ordered it, and it is switched off or
            # removed in one step in the assistant's panel.
            method="POST", path="/api/agent-chat/lead/rituals", ui_section="chats",
            params={"type": "object", "properties": _ritual_properties(),
                    "required": ["name", "phrases", "steps"]},
            voice_aliases={
                "de": ("leg ein ritual für guten morgen an",),  # i18n-allow: input vocab
                "en": ("set up a ritual for good morning",),
                "es": ("crea un ritual para buenos días",),  # i18n-allow: input vocab
                "pt": ("cria um ritual para bom dia",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="ritual-update",
            title="Change a ritual",
            description=(
                "Change a ritual: send only what changes. 'steps' replaces the whole list: read "
                "it with ritual-list first and keep each step's id that stays."
            ),
            method="PATCH", path="/api/agent-chat/lead/rituals/{ritual_id}",
            path_params=("ritual_id",), ui_section="chats",
            params={"type": "object", "properties": {
                "ritual_id": _ritual_ref_param(),
                **_ritual_properties(),
                "enabled": {"type": "boolean", "description": "Switch the ritual on or off."},
            }, "required": ["ritual_id"]},
            voice_aliases={
                "de": ("nimm die nachrichten aus meinem morgenritual",),  # i18n-allow: input vocab
                "en": ("take the news out of my morning ritual",),
                "es": ("quita las noticias de mi ritual de la mañana",),  # i18n-allow: input vocab
                "pt": ("tira as notícias do meu ritual da manhã",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="ritual-remove",
            title="Remove a ritual",
            description="Remove one ritual for good, on the user's request.",
            method="DELETE", path="/api/agent-chat/lead/rituals/{ritual_id}",
            path_params=("ritual_id",), ui_section="chats", dangerous=True,
            params={"type": "object", "properties": {"ritual_id": _ritual_ref_param()},
                    "required": ["ritual_id"]},
            voice_aliases={
                "de": ("lösch mein morgenritual",),  # i18n-allow: input vocab
                "en": ("delete my morning ritual",),
                "es": ("borra mi ritual de la mañana",),  # i18n-allow: input vocab
                "pt": ("apaga o meu ritual da manhã",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="ritual-run",
            title="Start a ritual now",
            description=(
                "Start a ritual now, when the user asks for it by name ('start my morning "
                "ritual'). If 'pending' is true, what it gathers follows shortly: do not "
                "gather it yourself."
            ),
            method="POST", path="/api/agent-chat/lead/rituals/{ritual_id}/run",
            path_params=("ritual_id",), ui_section="chats",
            params={"type": "object", "properties": {"ritual_id": _ritual_ref_param()},
                    "required": ["ritual_id"]},
            voice_aliases={
                "de": ("starte mein morgenritual",),  # i18n-allow: input vocab
                "en": ("start my morning ritual",),
                "es": ("empieza mi ritual de la mañana",),  # i18n-allow: input vocab
                "pt": ("começa o meu ritual da manhã",),  # i18n-allow: input vocab
            },
        ),
    )
