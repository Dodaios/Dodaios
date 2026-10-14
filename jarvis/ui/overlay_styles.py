"""The on-screen overlay's style vocabulary — ONE definition, imported everywhere.

A display style answers "what does Jarvis look like on the desktop while it is
listening?". It is a value that crosses Python, the REST payload, TypeScript and
four user-visible surfaces (Settings, onboarding, the config file, the CLI), so
it is exactly the five-layer enum this repo has been bitten by four times
(AP-4 / BUG-008). Same remedy as ``jarvis.ui.jarvisbar.modes``: the tuple lives
in a module with NO imports at all, every layer imports these names instead of
restating them, and ``tests/unit/ui/test_overlay_style_parity.py`` fails the
build when a layer drifts — including the TypeScript union and the i18n labels.

Adding a style = add it here, teach the surface factory
(``DesktopApp._build_overlay_surface``) how to build it, add the label to every
locale, and give it a preview graphic. Nothing else needs touching.
"""
from __future__ import annotations

#: The slim always-available bar (the default).
BAR_STYLE = "jarvis_bar"

#: Styles drawn by the floating orb window (``ui.orb.overlay.OrbOverlay``):
#: ``mascot`` is the hooded figure of the logo, ``voice_orb`` the procedural
#: weather sphere — the desktop twin of the in-app orb — and ``pet`` an
#: animated pixel-art companion with its own control strip
#: (``jarvis.ui.pets``). All three live in the SAME frameless, always-on-top
#: window, so all can be dragged onto any monitor and swapped live without a
#: restart.
ORB_STYLES: tuple[str, ...] = ("mascot", "voice_orb", "pet")

#: The built-in pet the ``mascot`` style shows: the mascot is that pet, with
#: the pet's animations, control strip and cards, whatever pet is chosen under
#: My Pets for the ``pet`` style.
MASCOT_PET_ID = "dodaios"

#: Orb-window styles that stay on screen while Jarvis is idle. The others pop
#: up only for a conversation.
PERSISTENT_ORB_STYLES: tuple[str, ...] = ("mascot", "pet")


def stays_while_idle(style: str, *, mascot_image: str = "") -> bool:
    """True for an orb-window style that stays on screen while Jarvis is idle.

    A configured mascot image (``[ui] orb_mascot_path``) is shown as the still
    picture it is, which pops up only for a conversation.
    """
    if style == "mascot" and mascot_image.strip():
        return False
    return style in PERSISTENT_ORB_STYLES

#: No on-screen overlay at all.
HIDDEN_STYLE = "none"

#: Every style the settings axis offers, in the order the pickers show them.
OVERLAY_STYLES: tuple[str, ...] = (BAR_STYLE, *ORB_STYLES, HIDDEN_STYLE)

#: Values older installs may still carry in ``jarvis.toml`` (or an old frontend
#: bundle may still PUT), mapped onto what they mean today. ``whisper_bar`` was
#: renamed to drop a trademarked word; ``orb`` was the removed procedural
#: renderer, whose selection the mascot inherited.
LEGACY_STYLE_ALIASES: dict[str, str] = {
    "whisper_bar": BAR_STYLE,
    "orb": "mascot",
}


def normalize_overlay_style(style: object) -> str | None:
    """Map any inbound value onto a known style, or ``None`` if there is none.

    Callers decide what an unknown style means: the REST layer rejects it, the
    boot path falls back to a default. Returning ``None`` keeps that decision
    out of here.
    """
    if not isinstance(style, str):
        return None
    candidate = style.strip().lower()
    candidate = LEGACY_STYLE_ALIASES.get(candidate, candidate)
    return candidate if candidate in OVERLAY_STYLES else None
