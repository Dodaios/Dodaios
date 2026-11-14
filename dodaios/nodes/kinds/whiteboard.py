"""The ``whiteboard`` node: an infinite canvas to draw on, with the assistant.

The person draws on it in the app, in the embedded open-source editor
``@excalidraw/excalidraw``; the assistant draws on the same board through the
``whiteboard`` tool, whose actions are high level (a box with a label, an
arrow between two things, a diagram, a Mermaid flowchart, a layout). Both
write one spec: the editor's scene (:mod:`dodaios.nodes.board.scene`). Several
boards are several nodes.

Why the spec is the editor's own scene and not a grammar of our own: the
person edits every detail by hand, and a second grammar would lose whatever it
cannot express on the next save. The assistant does not write raw elements;
the tool builds them (:mod:`dodaios.nodes.board.ops`).

The older board grammar (``items``/``links``/``layout``) is still accepted:
an existing node and a model that still sends it get a scene laid out by the
auto layout (:func:`dodaios.nodes.board.convert.legacy_to_scene`). The store
converts a stored node the next time it reads it, keeping its pictures as
board files (:mod:`dodaios.nodes.store`).

The page (:mod:`dodaios.nodes.board.render`) is a read-only drawing of the
scene for the library card, the chat card and a shared file.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.board import render as board_render
from dodaios.nodes.board.scene import (
    MAX_ELEMENTS,
    empty_scene,
    is_scene,
    live_elements,
    normalize_scene,
)
from dodaios.nodes.types import NodeError

PREVIEW_NOTES: Final[int] = 4
PREVIEW_CHARS: Final[int] = 40

#: The colours the library card draws notes in (``WhiteboardColor`` in the
#: frontend's ``nodeModel.ts``).
PREVIEW_COLORS: Final[tuple[str, ...]] = (
    "yellow",
    "pink",
    "blue",
    "green",
    "violet",
    "orange",
    "gray",
)

_WHAT_TO_SEND: Final[str] = (
    "A whiteboard is edited with the whiteboard tool (operation 'guide' explains its actions). "
    'Its spec is the editor\'s scene: {"format": "scene", "elements": [...], "appState": '
    '{...}, "files": {...}}; the older {"items": [...], "links": [...]} is accepted too.'
)

#: A board in the older grammar, as a model may still send it to ``node``.
EXAMPLE: Final[dict[str, Any]] = {
    "layout": "auto",
    "items": [
        {"id": "a", "text": "Interview five customers", "group": "Now"},
        {"id": "b", "text": "Draft the pricing page", "group": "Now", "color": "blue"},
        {"id": "c", "text": "Open the beta", "group": "Next", "color": "green"},
    ],
    "links": [{"from": "b", "to": "c", "label": "unblocks"}],
}

GUIDE: Final[str] = (
    "Whiteboard: an infinite canvas the person draws on in the app. Several boards are "
    "several nodes (create another one for a new board).\n"
    "Edit a board with the whiteboard tool, not by writing its spec: its actions add boxes, "
    "notes, text, arrows between things, frames, a whole diagram or a Mermaid flowchart, "
    "and lay things out. Read a board with that tool's 'read' first.\n"
    'The spec is the editor\'s scene: {"format": "scene", "elements": [element, ...], '
    '"appState": {"viewBackgroundColor": "#ffffff", "gridModeEnabled": false}, '
    '"files": {fileId: {"id", "mimeType", "created"}}}. Element types: rectangle, ellipse, '
    f"diamond, text, arrow, line, freedraw, image, frame; at most {MAX_ELEMENTS} elements. "
    "Every change raises an element's 'version'; a deleted element stays as "
    '"isDeleted": true.\n'
    "The node tool's create still accepts the older grammar and lays it out by itself:\n"
    + json.dumps(EXAMPLE, ensure_ascii=False, separators=(", ", ": "))
)


def normalize(spec: Any) -> dict[str, Any]:
    """The scene, validated and bounded; the older grammar becomes a scene first.

    A picture of the older grammar becomes a labelled box here (there is no
    node folder to keep its bytes in); the store converts with the folder.
    """
    if is_scene(spec):
        return normalize_scene(spec)
    if isinstance(spec, dict) and "items" in spec:
        from dodaios.nodes.board.convert import legacy_to_scene

        return normalize_scene(legacy_to_scene(spec))
    raise NodeError(_WHAT_TO_SEND)


def render(node: Any) -> str:
    """The board as one self-contained page (pictures drawn as boxes)."""
    return board_render.render(node)


def render_in_run(node: Any, run_dir: Path) -> str:
    """The board as one self-contained page, with its pictures from ``run_dir``."""
    return board_render.render(node, run_dir=run_dir)


# --- the library card --------------------------------------------------------------


def _hue_color(value: Any) -> str | None:
    """The card colour nearest to a hex colour, or ``None`` for no colour
    (transparent, white, black, grey)."""
    if not isinstance(value, str) or not value.startswith("#"):
        return None
    digits = value[1:]
    if len(digits) in (3, 4):
        digits = "".join(char * 2 for char in digits[:3])
    try:
        red, green, blue = (int(digits[at : at + 2], 16) / 255 for at in (0, 2, 4))
    except ValueError:  # not a hex colour after all
        return None
    high, low = max(red, green, blue), min(red, green, blue)
    if high - low < 0.08:
        return None
    if high == red:
        hue = ((green - blue) / (high - low)) % 6
    elif high == green:
        hue = (blue - red) / (high - low) + 2
    else:
        hue = (red - green) / (high - low) + 4
    degrees = hue * 60
    for limit, name in (
        (15, "pink"),
        (40, "orange"),
        (70, "yellow"),
        (170, "green"),
        (250, "blue"),
        (290, "violet"),
        (345, "pink"),
    ):
        if degrees < limit:
            return name
    return "pink"


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on the card: the first texts as notes, and the
    number of things on the board.

    A label inside a shape takes the shape's fill as its note colour; a free
    text is grey. Texts come in reading order (top to bottom, then left to
    right), so the card shows the board's beginning, not its oldest stroke.
    """
    try:
        elements = live_elements(normalize(spec))
    except (NodeError, ImportError):  # a card must still draw
        elements = []
    by_id = {element["id"]: element for element in elements}
    found: list[tuple[float, float, dict[str, str]]] = []
    for element in elements:
        if element["type"] != "text":
            continue
        text = shell.clean(element.get("text", ""), PREVIEW_CHARS).strip()
        if not text:
            continue
        container = by_id.get(element.get("containerId") or "")
        anchor = container or element
        if container is not None and container["type"] in ("rectangle", "ellipse", "diamond"):
            fill = container.get("backgroundColor")
            name = _hue_color(fill) or ("gray" if fill not in (None, "transparent") else "yellow")
        else:
            name = _hue_color(element.get("strokeColor")) or "gray"
        found.append((math.floor(anchor["y"] / 40), anchor["x"], {"text": text, "color": name}))
    found.sort(key=lambda entry: (entry[0], entry[1]))
    notes = [entry[2] for entry in found[:PREVIEW_NOTES]]
    # A label belongs to its shape or arrow: the card counts things, not words.
    count = sum(
        1 for element in elements if not (element["type"] == "text" and element.get("containerId"))
    )
    return {"notes": notes, "count": count}


def starter(title: str, language: str) -> dict[str, Any]:
    """An empty board: the person starts drawing, or asks the assistant to."""
    return empty_scene()


__all__ = [
    "EXAMPLE",
    "GUIDE",
    "PREVIEW_COLORS",
    "normalize",
    "preview",
    "render",
    "render_in_run",
    "starter",
]
