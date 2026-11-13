"""The node types, and the one error every node operation raises.

A node is a thing the person keeps and looks at: a document, a deck, a sheet,
a designed page, a dashboard, a whiteboard, a short animation. Each type has
its own content grammar (its ``spec``) and its own renderer in
:mod:`dodaios.nodes.kinds`; this module only names them, so every other module
can agree on the list without importing a renderer.
"""

from __future__ import annotations

from typing import Final

#: Every node type, in the order the library offers them.
NODE_TYPES: Final[tuple[str, ...]] = (
    "docs",
    "slides",
    "sheets",
    "design",
    "data",
    "whiteboard",
    "motion",
)

#: What the app calls each type on its shelf. Three differ from the type's own
#: name: a person says "Analytics", "Visuals" and "Clips", and the model has to
#: know which type that is.
DISPLAY_NAMES: Final[dict[str, str]] = {
    "docs": "Docs",
    "slides": "Slides",
    "sheets": "Sheets",
    "design": "Visuals",
    "data": "Analytics",
    "whiteboard": "Whiteboard",
    "motion": "Clips",
}

#: What a person may call a type; the tool and the routes accept these too.
_ALIASES: Final[dict[str, str]] = {
    "doc": "docs",
    "document": "docs",
    "documents": "docs",
    "report": "docs",
    "slide": "slides",
    "deck": "slides",
    "presentation": "slides",
    "sheet": "sheets",
    "spreadsheet": "sheets",
    "table": "sheets",
    "designs": "design",
    "page": "design",
    "poster": "design",
    "visual": "design",
    "visuals": "design",
    "dashboard": "data",
    "analytics": "data",
    "analysis": "data",
    "chart": "data",
    "charts": "data",
    "board": "whiteboard",
    "whiteboards": "whiteboard",
    "canvas": "whiteboard",
    "animation": "motion",
    "clip": "motion",
    "clips": "motion",
    "video": "motion",
}

MAX_TITLE_CHARS: Final[int] = 120
#: A spec is content a person reads, not a data dump: one megabyte of JSON is
#: far beyond any deck or sheet the renderers lay out well.
MAX_SPEC_BYTES: Final[int] = 1_000_000


class NodeError(ValueError):
    """A request the node store refuses, with a sentence the model can act on."""


def node_type(value: object) -> str:
    """The canonical type for ``value``, or :class:`NodeError` naming the choices."""
    name = str(value or "").strip().lower()
    name = _ALIASES.get(name, name)
    if name not in NODE_TYPES:
        raise NodeError(f"'type' must be one of: {', '.join(NODE_TYPES)}.")
    return name


__all__ = [
    "DISPLAY_NAMES",
    "MAX_SPEC_BYTES",
    "MAX_TITLE_CHARS",
    "NODE_TYPES",
    "NodeError",
    "node_type",
]
