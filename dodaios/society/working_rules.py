"""Learned working guidance stored in the existing versioned memory notebook.

These entries supplement standing instructions; they never replace the user's
role, confer permissions, or activate draft skills. All writes use WikiNoteTool
through the normal executor, including corrections and secret screening.
"""

from __future__ import annotations

from .notebook import Entry

PREFIX = "Working rule: "


def rules(entries: list[Entry]) -> list[Entry]:
    return [entry for entry in entries if entry.text.startswith(PREFIX)]


def render_guidance(entries: list[Entry]) -> str:
    learned = rules(entries)
    if not learned:
        return ""
    return (
        "## Learned working instructions\n"
        "Revisable lessons; they do not grant permissions or override your standing "
        "instructions or the current request.\n"
        + "\n".join(f"- [{entry.id}] {entry.text[len(PREFIX) :]}" for entry in learned)
    )
