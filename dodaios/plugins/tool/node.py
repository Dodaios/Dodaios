"""``node`` — make, revise and keep current the things a person keeps.

A node is a typed thing the assistant makes for a person and looks after: a
document, a deck, a sheet, a designed page, a dashboard, a whiteboard, a short
animation (:mod:`dodaios.nodes`). The assistant sends CONTENT (a ``spec`` in the
type's grammar); the type's renderer lays out the page, so every node of a type
looks the same and no call carries markup. That is why this tool exists next to
``write_report`` and ``living_page``: one tool, seven types, and a revision that
names the place it changes (``changes``) instead of resending the whole thing.

The grammar of a type is long, so it is not in the description the model reads
on every turn: ``guide`` hands it out once, before the first node of that type.

Router-tier, risk ``monitor``: a call writes one page in the run archive, and
for a kept-current node adds or removes one routine of the assistant's own
(:mod:`dodaios.nodes.refresh`). It never sends anything, never spawns a worker
and never calls a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.nodes import refresh
from dodaios.nodes.kinds import kind_of
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES, NodeError, node_type
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.create_artifact import _called_in_background
from dodaios.plugins.tool.living_page import page_card, post_card, session_of

log = logging.getLogger(__name__)

_OPERATIONS: Final[tuple[str, ...]] = (
    "guide",
    "create",
    "update",
    "get",
    "list",
    "revert",
    "keep_current",
    "stop",
)
#: Operations that name one existing node.
_ON_ONE_NODE: Final[frozenset[str]] = frozenset(
    {"update", "get", "revert", "keep_current", "stop"}
)
#: How much of a node's JSON ``get`` hands back; more would crowd the turn.
MAX_GET_CHARS: Final[int] = 60_000

#: What each type is for, as ``guide`` without a type lists them.
TYPE_LINES: Final[dict[str, str]] = {
    "docs": "a written document: a report, a plan, a brief, notes",
    "slides": "a deck of slides to present",
    "sheets": "a sheet of rows and columns: a list or table to keep",
    "design": 'a freely designed page: a poster, a one-pager (the app says "Visuals")',
    "data": 'a dashboard: current figures and charts (the app says "Analytics")',
    "whiteboard": "a board of notes, shapes and arrows: a diagram, a map of ideas",
    "motion": 'a short animation (the app says "Clips")',
}


def _language(ctx: Any, args: dict[str, Any]) -> str:
    config = getattr(ctx, "config", None)
    stamped = str(config.get("output_language") or "") if isinstance(config, dict) else ""
    return (stamped or str(args.get("language") or "") or "en").strip().lower()[:8]


def _json_value(value: Any) -> Any:
    """``value``, parsed when a caller sent an object or a list as JSON text."""
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:  # not JSON after all: the store says what it needs instead
            return value
    return value


def _text(value: Any) -> str | None:
    """A given, non-empty string argument, or ``None`` for "not given"."""
    text = str(value).strip() if value is not None else ""
    return text or None


def _summary(node: Node, refreshing: bool) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "version": node.version,
        "updated_at": datetime.fromtimestamp(node.updated_at)
        .astimezone()
        .isoformat(timespec="seconds"),
        "kept_current": bool(node.track),
        "refreshing": refreshing,
        "every_minutes": node.every_minutes,
    }


def _overview() -> str:
    lines = [f"- {name}: {TYPE_LINES[name]}" for name in NODE_TYPES]
    return (
        "The node types:\n"
        + "\n".join(lines)
        + "\nBefore your first create of a type in a conversation, call this tool with "
        "operation 'guide' and that type: the answer is the grammar its 'spec' must follow."
    )


class NodeTool:
    """Create, revise, read, list, revert and keep current a person's nodes."""

    name: str = "node"
    risk_tier: str = "monitor"
    description: str = (
        "Make and look after a NODE: something the person keeps and looks at, shown in "
        "the Nodes section and as a card in the chat. Types: docs (a written document), "
        "slides (a deck), sheets (rows and columns), design (a free-form page; the app "
        "says Visuals), data (a dashboard of figures and charts; Analytics), whiteboard "
        "(notes, shapes, arrows), motion (a short animation; Clips). Call 'guide' with the "
        "type before your first create of that type; the spec must follow that grammar. "
        "To change a node, use "
        "'update' with 'changes' (small edits by path) rather than resending everything. "
        "To keep one current from the person's apps, give 'track' (on create, or with "
        "'keep_current'); 'stop' ends that. 'get' reads a node, 'list' shows all, 'revert' "
        "undoes the last change. The renderer does the design: send content, never HTML "
        "(except type design). A long answer to a question stays a report (write_report)."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(_OPERATIONS)},
            "type": {
                "type": "string",
                "enum": list(NODE_TYPES),
                "description": "guide, create: the node type.",
            },
            "node": {
                "type": "string",
                "description": (
                    "update, get, revert, keep_current, stop: the node's id, or its "
                    "exact title."
                ),
            },
            "title": {
                "type": "string",
                "description": "create: a few words. update: a new title.",
            },
            "spec": {
                "type": "object",
                "description": (
                    "create, update: the node's complete content in the type's grammar "
                    "(see guide)."
                ),
            },
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": ["set", "insert", "remove", "move", "replace", "append"],
                            "description": (
                                "set (default): put value at the path. insert: put value "
                                "into the list before the index. remove: take it away. "
                                "move: the list item ends up at index 'to'. replace: in "
                                "the text at the path, put value where 'find' stands. "
                                "append: add value to the end of the text or list there."
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "Where in the spec, e.g. /slides/2/title (the third "
                                "slide: indices count from 0); '-' as the last part "
                                "appends to a list."
                            ),
                        },
                        "value": {
                            "description": (
                                "set, insert, append: the new value. replace: the new text."
                            ),
                        },
                        "find": {
                            "type": "string",
                            "description": (
                                "replace: the exact passage to replace; it must occur "
                                "once (make it longer if it does not)."
                            ),
                        },
                        "to": {"type": "integer", "description": "move: the new index."},
                    },
                    "required": ["path"],
                },
                "description": (
                    "update: edits to the current spec, applied in order; use these "
                    "instead of 'spec' when only a few places change."
                ),
            },
            "track": {
                "type": "string",
                "description": (
                    "create, keep_current: what the node keeps current and where to "
                    "read it, self-contained (the refresh run sees only this)."
                ),
            },
            "every_minutes": {
                "type": "integer",
                "description": "With track: refresh interval, 15 to 10080 (default 180).",
            },
            "note": {
                "type": "string",
                "description": (
                    "update, on a refresh run: one short line saying why no source "
                    "could be read."
                ),
            },
            "language": {"type": "string", "description": "The person's language code."},
        },
        "required": ["operation"],
    }

    def __init__(self, store: NodeStore | None = None) -> None:
        self._store = store

    def _nodes(self) -> NodeStore:
        if self._store is None:
            self._store = NodeStore()
        return self._store

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        operation = str(args.get("operation") or "").strip().lower()
        if operation not in _OPERATIONS:
            return ToolResult(
                False, "", f"'operation' must be one of {', '.join(_OPERATIONS)}."
            )
        store = self._nodes()
        try:
            if operation == "guide":
                return self._guide(args)
            if operation == "create":
                return await self._create(store, args, ctx)
            if operation == "list":
                return await self._list(store)
            node = await self._find(store, args, operation)
            if operation == "update":
                return await self._update(store, node, args, ctx)
            if operation == "get":
                return await self._get(node)
            if operation == "revert":
                return await self._revert(store, node, ctx)
            if operation == "keep_current":
                return await self._keep_current(store, node, args)
            return await self._stop(store, node)
        except NodeError as exc:  # the model's call to fix; the error says how
            return ToolResult(False, "", str(exc))
        except RuntimeError as exc:  # scheduler down: said to the model, not swallowed
            return ToolResult(
                False,
                "",
                f"The refresh could not be scheduled ({exc}). The node itself is unchanged "
                "and paused; tell the person, and try 'keep_current' again later.",
            )
        except OSError as exc:
            log.warning("node %s: archive not writable", operation, exc_info=True)
            return ToolResult(False, "", f"The node could not be saved: {exc}")

    # ---------------------------------------------------------- operations

    def _guide(self, args: dict[str, Any]) -> ToolResult:
        wanted = _text(args.get("type"))
        if wanted is None:
            return ToolResult(True, _overview())
        return ToolResult(True, kind_of(wanted).guide)

    async def _find(self, store: NodeStore, args: dict[str, Any], operation: str) -> Node:
        reference = _text(args.get("node"))
        if reference is None:
            raise NodeError(f"'node' is required for {operation}: the node's id or exact title.")
        node = await asyncio.to_thread(store.find, reference)
        if node is None:
            raise NodeError(
                f"No node with the id or title {reference!r}; call operation 'list' to see them."
            )
        return node

    async def _create(self, store: NodeStore, args: dict[str, Any], ctx: Any) -> ToolResult:
        type_name = node_type(args.get("type"))
        spec = _json_value(args.get("spec"))
        if spec is None or spec == {}:
            return ToolResult(
                False,
                "",
                f"'spec' is missing. Call this tool with operation 'guide' and type "
                f"'{type_name}' first, then create the node with a spec in that grammar.",
            )
        node = await asyncio.to_thread(
            store.create,
            type=type_name,
            title=str(args.get("title") or ""),
            spec=spec,
            language=_language(ctx, args),
        )
        track = _text(args.get("track"))
        refresh_error = ""
        if track is not None:
            try:
                node = await refresh.start_refresh(
                    store, node.id, track=track, every_minutes=args.get("every_minutes")
                )
            except RuntimeError as exc:
                # The node exists either way; the person hears that it will not refresh.
                refresh_error = str(exc)
                log.warning("node %s: refresh not scheduled: %s", node.id, exc)
        # Written synchronously, so the job is already done; the ledger lists the node.
        job_id = jobs.start(
            "artifact", ctx=ctx, title=node.title, target=f"node:{node.id}",
            meta={"node_id": node.id},
        )
        jobs.finish(
            job_id,
            "done" if not refresh_error else "blocked",
            summary=f"Node of type {node.type}."
            + (f" It cannot refresh yet: {refresh_error}" if refresh_error else ""),
            result_ref=f"artifact:{node.visual_id}",
        )
        shown = await post_card(session_of(ctx), page_card(node.title, node.visual_id, node_type=node.type))
        made = f"Created the {node.type} node '{node.title}' (node id {node.id})."
        if refresh_error:
            made += (
                f" Its refresh could not be scheduled ({refresh_error}), so it is paused: "
                "tell the person it will not update by itself yet; they can resume it on "
                "the node's page, or you can call 'keep_current' again later."
            )
        elif node.refreshing:
            made += f" It refreshes every {node.every_minutes} minutes."
        where = (
            "Its card is in the chat and shows the node"
            if shown
            else "It is in the Nodes section (no card could be posted)"
        )
        return ToolResult(
            True,
            jobs.with_job_id(
                f"{made} {where}. Answer briefly; do not repeat its content.",
                job_id, ctx,
            ),
        )

    async def _update(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        spec = _json_value(args.get("spec"))
        changes = _json_value(args.get("changes"))
        title = _text(args.get("title"))
        note = _text(args.get("note"))
        has_content = spec is not None or changes is not None
        if note is None and has_content and node.note:
            # Content that was read again retires the line an earlier refresh left.
            note = ""
        updated = await asyncio.to_thread(
            store.update, node.id, title=title, spec=spec, changes=changes, note=note
        )
        revised = updated.version != node.version
        if revised and not _called_in_background(ctx):
            # A person's own revision: the chat shows the fresh page. A refresh run
            # stays out of the conversation; the page itself shows its update.
            await post_card(session_of(ctx), page_card(updated.title, updated.visual_id, node_type=updated.type))
        if not revised:
            what = (
                f"the note was recorded, its content is unchanged (version {updated.version})"
                if note
                else f"its content is the same as before (version {updated.version})"
            )
            return ToolResult(True, f"Node '{updated.title}': {what}.")
        done: list[str] = []
        if updated.spec != node.spec:
            done.append(
                f"{len(changes)} edit(s) applied"
                if isinstance(changes, list)
                else "its content was rewritten"
            )
        if updated.title != node.title:
            done.append(f"renamed from '{node.title}'")
        return ToolResult(
            True,
            f"Node '{updated.title}' is now version {updated.version}: {', '.join(done)}.",
        )

    async def _get(self, node: Node) -> ToolResult:
        fields = _summary(node, await refresh.refresh_live(node))
        fields.update(language=node.language, track=node.track, note=node.note, spec=node.spec)
        text = json.dumps(fields, ensure_ascii=False)
        if len(text) > MAX_GET_CHARS:
            return ToolResult(
                True,
                f"The node's JSON is {len(text)} characters long; these are the first "
                f"{MAX_GET_CHARS}:\n{text[:MAX_GET_CHARS]}",
            )
        return ToolResult(True, text)

    async def _list(self, store: NodeStore) -> ToolResult:
        nodes = await asyncio.to_thread(store.list_nodes)
        return ToolResult(True, [_summary(n, await refresh.refresh_live(n)) for n in nodes])

    async def _revert(self, store: NodeStore, node: Node, ctx: Any) -> ToolResult:
        restored = await asyncio.to_thread(store.revert, node.id)
        if not _called_in_background(ctx):
            await post_card(session_of(ctx), page_card(restored.title, restored.visual_id, node_type=restored.type))
        return ToolResult(
            True,
            f"Node '{restored.title}' has its earlier content again "
            f"(now version {restored.version}).",
        )

    async def _keep_current(
        self, store: NodeStore, node: Node, args: dict[str, Any]
    ) -> ToolResult:
        live = await refresh.start_refresh(
            store, node.id, track=_text(args.get("track")), every_minutes=args.get("every_minutes")
        )
        return ToolResult(
            True,
            f"Node '{live.title}' is kept current: it refreshes every "
            f"{live.every_minutes} minutes.",
        )

    async def _stop(self, store: NodeStore, node: Node) -> ToolResult:
        stopped = await refresh.stop_refresh(store, node.id)
        return ToolResult(
            True, f"Node '{stopped.title}' no longer refreshes; it keeps its content."
        )


__all__ = ["MAX_GET_CHARS", "TYPE_LINES", "NodeTool"]
