"""Nodes: the typed things the assistant makes for a person and keeps current.

A node is something the person keeps and looks at: a document, a deck of
slides, a sheet, a designed page, a dashboard, a whiteboard, a short film.
Seven types (:data:`~dodaios.nodes.types.NODE_TYPES`), one idea:

* The CONTENT is a ``spec``: plain JSON in the type's own grammar, written by
  the assistant through the ``node`` tool (``dodaios.plugins.tool.node``).
* The LOOK is the renderer's (:mod:`dodaios.nodes.kinds`): one deterministic
  function per type turns a spec into one self-contained page. The assistant
  never writes markup for a typed node, so every node of a type is laid out
  to the same standard, and a better renderer improves every node at once.
* A REVISION edits the spec (:mod:`dodaios.nodes.patch`) and the page is
  drawn again; earlier versions are kept, so a change can be taken back.
* UPKEEP (:mod:`dodaios.nodes.refresh`) is a lead routine that reads the
  node's sources on a schedule and updates its content.

Nodes live in the run archive (:mod:`dodaios.nodes.store`), one run directory
each, so the stage, sharing, the Downloads mirror and the cleanup sweep see
them like any other run. The library the app shows
(:mod:`dodaios.nodes.library`) lists them together with what older runs left
behind: worker-built pages, reports, living pages, pictures.
"""

from __future__ import annotations

from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES, NodeError, node_type

__all__ = ["NODE_TYPES", "Node", "NodeError", "NodeStore", "node_type"]
