"""The node types' renderers, one module per type.

Every module in this package describes ONE type and exports the same five
names, so the store, the tool and the library treat all types alike:

``normalize(spec) -> dict``
    Validate and bound the content. Returns a clean spec the renderer accepts
    as is (unknown keys dropped, texts clipped, lists capped). Raises
    :class:`~dodaios.nodes.types.NodeError` with one sentence that tells the
    model what to send instead. Idempotent: ``normalize(normalize(x))`` equals
    ``normalize(x)``.

``render(node) -> str``
    The node as one self-contained HTML document
    (:func:`dodaios.nodes.shell.document`). Deterministic for a given node; no
    network, no storage, both themes.

``preview(spec) -> dict``
    The few values the library draws on the node's card (see
    ``frontend/src/components/nodes/covers``). Small and bounded.

``starter(title, language) -> dict``
    The spec of a fresh node of this type made from the library's "new" row:
    a handful of placeholder parts that show what the type can hold.

``GUIDE``
    The grammar of the spec as text for the model, with one compact example.
    Handed out by the ``node`` tool's ``guide`` operation.

``RENDER_REVISION`` below goes up whenever a renderer's output changes; the
store rewrites the pages of older nodes when they are next read, so every
node gets the current look without being rebuilt by hand.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from dodaios.nodes.types import NODE_TYPES, node_type

#: Raise by one when any renderer's output changes.
RENDER_REVISION: Final[int] = 4


@dataclass(frozen=True)
class NodeKind:
    """One node type's five functions."""

    type: str
    normalize: Callable[[Any], dict[str, Any]]
    render: Callable[[Any], str]
    preview: Callable[[dict[str, Any]], dict[str, Any]]
    starter: Callable[[str, str], dict[str, Any]]
    guide: str


_KINDS: dict[str, NodeKind] = {}


def kind_of(type_name: str) -> NodeKind:
    """The renderer of ``type_name`` (aliases accepted). Raises ``NodeError``."""
    name = node_type(type_name)
    known = _KINDS.get(name)
    if known is not None:
        return known
    module = importlib.import_module(f"{__name__}.{name}")
    kind = NodeKind(
        type=name,
        normalize=module.normalize,
        render=module.render,
        preview=module.preview,
        starter=module.starter,
        guide=str(module.GUIDE),
    )
    _KINDS[name] = kind
    return kind


def all_kinds() -> tuple[NodeKind, ...]:
    """Every type's renderer, in library order."""
    return tuple(kind_of(name) for name in NODE_TYPES)


__all__ = ["RENDER_REVISION", "NodeKind", "all_kinds", "kind_of"]
