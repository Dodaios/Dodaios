"""Command definitions: designs.

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
            id="design-list",
            title="List designs",
            description=(
                "List the app's designs (colours plus an optional animated "
                "background): the built-in ones, the person's own, which one "
                "is on screen ('standard' = the app's own look), and every "
                "colour key and background style a design may use."
            ),
            method="GET",
            path="/api/designs",
            ui_section="designs",
            voice_aliases={
                "de": ("welche designs habe ich",),  # i18n-allow: input vocab
                "en": ("which designs do i have",),
                "es": ("qué diseños tengo",),  # i18n-allow: input vocab
                "pt": ("que designs tenho",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="design-save",
            title="Make or change a design",
            description=(
                "Make a new design for the whole app from what the person describes, or "
                "change one of theirs by id (send only what changes); it is switched on at "
                "once (apply=false only saves it). Keep text readable: contrast of at least "
                "7:1. Give both a `dark` and a `light` palette, each with background, "
                "foreground and accent as #rrggbb; optional overrides: sidebar, card, "
                "popover, surface, border, muted, primary, user_bubble, bubble_out, "
                "bubble_in, success, warning, destructive. `background` is animated: style "
                "glow, waves, stars, gradient or none; colors 1 to 5 #rrggbb; speed slow, "
                "medium or fast; strength 0 to 1. The person can switch designs in "
                "Settings > Designs."
            ),
            method="POST",
            path="/api/designs",
            params={
                "type": "object",
                "properties": {
                    "id": _str_param(
                        "Id of one of the person's own designs to change; "
                        "leave out to make a new design.",
                        max_length=64,
                    ),
                    "name": _str_param(
                        "Short name of the design, in the person's language.",
                        min_length=1, max_length=40,
                    ),
                    "description": _str_param(
                        "What the person asked for, in one sentence.",
                        max_length=300,
                    ),
                    "dark": {
                        "type": "object",
                        "description": (
                            "Colours for the dark appearance, for example "
                            '{"background": "#0b1020", "foreground": "#e8ecf8", '
                            '"accent": "#7c9cff"}.'
                        ),
                    },
                    "light": {
                        "type": "object",
                        "description": (
                            "Colours for the light appearance, for example "
                            '{"background": "#f6f7fb", "foreground": "#141a2e", '
                            '"accent": "#3a5bd9"}.'
                        ),
                    },
                    "background": {
                        "type": "object",
                        "description": (
                            'Animated background, for example {"style": "glow", '
                            '"colors": ["#1d3b8f", "#5a2a8a"], "speed": "slow", '
                            '"strength": 0.5}.'
                        ),
                    },
                    "apply": {
                        "type": "boolean", "default": True,
                        "description": "Switch to the design right away.",
                    },
                },
                "required": [],
            },
            ui_section="designs",
            voice_aliases={
                "de": (  # i18n-allow: input vocab
                    "mach mir ein dunkelblaues design",  # i18n-allow: input vocab
                    "gestalte die app in grün",  # i18n-allow: input vocab
                ),
                "en": ("make me a dark blue design", "make the app green"),
                "es": ("hazme un diseño azul oscuro",),  # i18n-allow: input vocab
                "pt": ("faz-me um design azul escuro",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="design-apply",
            title="Switch design",
            description=(
                "Switch the app to one of its designs by id (see design-list); "
                "'standard' goes back to the app's own look."
            ),
            method="PUT",
            path="/api/designs/active",
            params={
                "type": "object",
                "properties": {
                    "id": _str_param(
                        "Design id, or 'standard' for the app's own look.",
                        min_length=1, max_length=64,
                    ),
                },
                "required": ["id"],
            },
            ui_section="designs",
            voice_aliases={
                "de": ("nimm das design tiefsee",),  # i18n-allow: input vocab
                "en": ("switch to the deep sea design",),
                "es": ("cambia al diseño mar profundo",),  # i18n-allow: input vocab
                "pt": ("muda para o design mar profundo",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="design-reset",
            title="Back to the standard look",
            description=(
                "Switch designs off and go back to the app's standard colours. "
                "The person's designs stay saved."
            ),
            method="POST",
            path="/api/designs/reset",
            ui_section="designs",
            voice_aliases={
                "de": ("setz das design zurück",),  # i18n-allow: input vocab
                "en": ("reset the design",),
                "es": ("restablece el diseño",),  # i18n-allow: input vocab
                "pt": ("repõe o design",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="design-delete",
            title="Delete a design",
            description=(
                "Delete one of the person's own designs by id; built-in designs "
                "cannot be deleted. If it was on screen, the standard look "
                "takes over."
            ),
            method="DELETE",
            path="/api/designs/{design_id}",
            params={
                "type": "object",
                "properties": {
                    "design_id": _str_param(
                        "Id of the design to delete.", min_length=1, max_length=64
                    ),
                },
                "required": ["design_id"],
            },
            path_params=("design_id",),
            dangerous=True,
            ui_section="designs",
            voice_aliases={
                "de": ("lösche mein design",),  # i18n-allow: input vocab
                "en": ("delete my design",),
                "es": ("borra mi diseño",),  # i18n-allow: input vocab
                "pt": ("apaga o meu design",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="audio-devices-list",
            title="List audio devices",
            description="List available speaker and microphone devices.",
            method="GET",
            path="/api/settings/audio-devices",
            worker_allowed=True,
            ui_section="settings",
            voice_aliases={
                "de": ("welche audiogeräte gibt es",),  # i18n-allow: input vocab
                "en": ("list my audio devices",),
                "es": ("qué dispositivos de audio hay",),  # i18n-allow: input vocab
                "pt": ("que dispositivos de áudio há",),  # i18n-allow: input vocab
            },
        ),
    )
