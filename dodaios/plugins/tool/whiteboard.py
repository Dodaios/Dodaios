"""``whiteboard`` — the assistant draws on a person's whiteboards.

A whiteboard is a node (:mod:`dodaios.nodes`) whose content is the scene of
the embedded drawing editor: an infinite canvas the person draws on in the
app, and the assistant draws on through this tool. Several boards are several
nodes; ``create`` makes another.

Why a tool of its own next to ``node``: a board is not edited by rewriting
its spec. The model sends ACTIONS (add a note, connect two boxes, lay out,
put a whole diagram or a Mermaid flowchart on the board), and
:mod:`dodaios.nodes.board.ops` turns them into valid, well placed elements;
``read`` gives the board back with the ids the actions refer to. The full
action reference is long, so it is not in the description the model reads
every turn: ``guide`` hands it out once.

The person may be drawing on the same board while the assistant edits it:
an edit runs under the node's lock on the scene as it is stored, and every
element it changes gets a higher version, so the editor merges it with the
person's strokes instead of overwriting them.

Router-tier, risk ``monitor``: a call writes one node in the run archive and
posts its card. It never sends anything, never spawns a worker and never
calls a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.nodes.board import ops
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NodeError
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.create_artifact import _called_in_background
from dodaios.plugins.tool.living_page import page_card, post_card, session_of

log = logging.getLogger(__name__)

_OPERATIONS: Final[tuple[str, ...]] = (
    "guide",
    "list",
    "create",
    "read",
    "edit",
    "duplicate",
    "revert",
)
#: How much of a reading ``read`` hands back; more would crowd the turn.
MAX_READ_CHARS: Final[int] = 60_000
DEFAULT_TITLE: Final[str] = "Whiteboard"

GUIDE: Final[str] = """\
Whiteboard actions. 'create' and 'edit' take "actions": a list run in order, all or nothing \
(an error names the action index and changes nothing). Each action is {"do": NAME, ...}.

Ids: give things short ids ("id": "api") and refer to them in later actions of the same \
call; without an id one is made (note-1, box-2; a diagram arrow is "from:to"). 'read' lists \
every id. An id may also be the exact label of one thing.

Position (add, diagram, mermaid; move): leave it out and the board finds a free place right \
of the content (several adds in one call flow in rows), or say "near"/"right_of"/"left_of"/\
"below"/"above": ID (optional "gap"), or "inside": FRAME_ID, or exact "x","y" (pixels, \
y grows downwards). Nothing new overlaps what is there.

Style keys (add, update, style, diagram nodes, edges): "color" (palette name: black, gray, \
red, pink, grape, violet, indigo, blue, cyan, teal, green, lime, yellow, orange, bronze; \
sets stroke and fill), "fill", "stroke" (palette name, "blue-1" for a shade 0-4, \
"light blue", hex, or "none"), "fill_style" (solid|hachure|cross-hatch|zigzag), \
"stroke_width" (thin|bold|extra or px), "stroke_style" (solid|dashed|dotted), "roughness" \
(0 clean, 1 sketchy, 2 rough), "opacity" (0-100), "font" (hand|normal|code), "size" \
(s|m|l|xl or px; default m = 20), "align" (left|center|right), "text_color", "rounded" \
(true|false), "link" (https:// or mailto:), "locked", "angle" (degrees).

Defaults that look good: boxes blue, decisions (diamond) yellow, start/end (ellipse) green, \
notes yellow sticky boxes, one size per kind, 20 px grid. A colour should mean one thing \
across a board (a team, a state), not decorate.

Actions:
- add: one thing, or "items": [...] for several. "type": box | rect (sharp) | rounded | \
ellipse | circle | diamond | note (sticky) | text | frame | arrow | line | freedraw | image. \
"label" (or "text"), "w","h" (else sized to the label), style keys. text: "size" l/xl for \
headings. frame: "name", "w","h", or "children": [ids] to wrap them. arrow/line: "from","to" \
(ids, bound at both ends) or "points": [[x,y],...]; "label", "style" (solid|dashed|dotted|\
bold), "arrow" (end|start|both|none). freedraw: "points". image: "file" (an uploaded \
picture's id).
  {"do":"add","type":"note","id":"n1","label":"Ask legal","near":"api"}
  {"do":"add","items":[{"type":"note","label":"Idea A"},{"type":"note","label":"Idea B"}]}
- connect: "from","to" (an id or a list: fans out) or "chain": [a,b,c]; "label", "style", \
"arrow", "color".  {"do":"connect","from":"api","to":"db","label":"reads"}
- update: "id"/"ids" plus any of "label"/"text"/"name", style keys, "x","y", "w","h", \
"from"/"to" (re-attach an arrow), "link", "locked".  {"do":"update","id":"n1","label":"Done"}
- style: "ids" plus style keys only.  {"do":"style","ids":["a","b"],"color":"red"}
- delete: "ids"; arrows on a deleted shape go too ("keep_arrows": true keeps them); a \
frame takes its contents ("keep_contents": true keeps them).
- move: "ids" plus "by": [dx,dy], "to": [x,y] (top-left), or "right_of"/"below"/"near": ID. \
Arrows follow; labels and a frame's contents move along.
- resize: "ids" plus "w","h" or "scale".
- align: "ids", "to": left|center|right|top|middle|bottom.
- distribute: "ids" (3+), "axis": horizontal|vertical, optional "gap".
- layout: "kind": flow|tree|mindmap|grid; "ids" (default: everything not in a frame) or \
"frame": ID (tidies that frame and fits it); "direction" LR|RL|TB|BT; "root" (tree, \
mindmap); "columns" (grid); "gap". Uses the arrows between the things.
  {"do":"layout","kind":"tree","direction":"TB","root":"ceo"}
- group / ungroup: "ids" (ungroup also takes "group": GROUP_ID).
- frame: "ids" to wrap in a new frame ("name", optional "frame_id"), or "into": FRAME_ID.
- diagram: "nodes": [{"id","label","type","color",...} or "label"], "edges": [{"from","to",\
"label","style","arrow"}], "groups": [{"id","label","nodes":[ids]}] (each a frame), \
"direction", "layout" (flow default|tree|mindmap|grid), "root", "title"; laid out and \
placed as one block. Its ids are kept (renamed with -2 when already on the board; the \
report says so).
  {"do":"diagram","direction":"LR","nodes":[{"id":"a","label":"Sign up"},{"id":"b",\
"label":"Verified?","type":"diamond"},{"id":"c","label":"Welcome","type":"ellipse"}],\
"edges":[{"from":"a","to":"b"},{"from":"b","to":"c","label":"yes"}]}
- mermaid: "source": a Mermaid flowchart ("flowchart LR" / "graph TD": shapes [ ] ( ) ([ ]) \
{ } (( )), edges --> --- -.-> ==> with |labels|, chains, &, subgraph ... end as frames). \
Other Mermaid kinds are refused: use diagram.
  {"do":"mermaid","source":"flowchart LR\\n  A[Idea] --> B{Worth it?}\\n  B -->|yes| C([Build])"}
- order: "ids", "to": front|back|forward|backward.
- lock / unlock: "ids" (default: everything).
- clear: removes everything.   background: "color".   grid: "on": true|false.

Good boards: one idea per note, a few words per box; build a process or structure with \
one diagram or mermaid action rather than many adds; put related things in a frame; after \
adding several loose things, 'layout' them. 'read' (optionally "query" or "ids", "raw": \
true for the full element JSON) before editing a board you did not just make."""


def _language(ctx: Any, args: dict[str, Any]) -> str:
    config = getattr(ctx, "config", None)
    stamped = str(config.get("output_language") or "") if isinstance(config, dict) else ""
    return (stamped or str(args.get("language") or "") or "en").strip().lower()[:8]


def _json_value(value: Any) -> Any:
    """``value``, parsed when a caller sent an object or a list as JSON text."""
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:  # not JSON after all: the check below says what is needed
            return value
    return value


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _summary(node: Node) -> dict[str, Any]:
    elements = node.spec.get("elements") if isinstance(node.spec, dict) else None
    live = [e for e in elements or [] if isinstance(e, dict) and not e.get("isDeleted")]
    return {
        "id": node.id,
        "title": node.title,
        "version": node.version,
        "updated_at": datetime.fromtimestamp(node.updated_at)
        .astimezone()
        .isoformat(timespec="seconds"),
        "elements": sum(1 for e in live if not (e.get("type") == "text" and e.get("containerId"))),
    }


def _actions_of(args: dict[str, Any]) -> list[dict[str, Any]]:
    """The actions of a call: ``actions`` plus the ``mermaid``/``diagram`` shortcuts."""
    actions: list[dict[str, Any]] = []
    mermaid = _text(args.get("mermaid"))
    if mermaid is not None:
        actions.append({"do": "mermaid", "source": mermaid})
    diagram = _json_value(args.get("diagram"))
    if diagram is not None:
        if not isinstance(diagram, dict):
            raise NodeError("'diagram' must be an object with 'nodes' (and 'edges', 'groups').")
        actions.append({"do": "diagram", "diagram": diagram})
    given = _json_value(args.get("actions"))
    if given is not None:
        if isinstance(given, dict):
            given = [given]
        if not isinstance(given, list):
            raise NodeError('\'actions\' must be a list of objects like {"do": "add", ...}.')
        actions.extend(given)
    return actions


class WhiteboardTool:
    """Create, read, edit, list, copy and revert the person's whiteboards."""

    name: str = "whiteboard"
    risk_tier: str = "monitor"
    description: str = (
        "Draw on a WHITEBOARD: an infinite canvas the person also draws on (a node of type "
        "whiteboard; several boards are several nodes). 'create' makes one (title, optional "
        "'mermaid' flowchart, 'diagram' or 'actions'); 'edit' changes one with 'actions' "
        '({"do": add | connect | update | delete | move | layout | diagram | mermaid | '
        "frame | align | style | ...}); 'read' lists what is on it with ids; 'list' shows the "
        "boards; 'duplicate' and 'revert' as named. Call 'guide' once before your first "
        "edit: it has every action and its fields. Do not place things by hand unless asked: "
        "the board lays them out on a grid and never overlaps what is there."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(_OPERATIONS)},
            "board": {
                "type": "string",
                "description": "read, edit, duplicate, revert: the board's node id or exact title.",
            },
            "title": {"type": "string", "description": "create, duplicate: the board's title."},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"do": {"type": "string", "enum": list(ops.ACTIONS)}},
                    "required": ["do"],
                },
                "description": "create, edit: the actions, run in order, all or none (see guide).",
            },
            "mermaid": {
                "type": "string",
                "description": "create, edit: a Mermaid flowchart to draw (a mermaid action).",
            },
            "diagram": {
                "type": "object",
                "description": "create, edit: {nodes, edges, groups, direction} (see guide).",
            },
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "read: only these elements.",
            },
            "query": {
                "type": "string",
                "description": "read: only elements whose id or label holds this.",
            },
            "raw": {"type": "boolean", "description": "read: the full element JSON instead."},
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
            return ToolResult(False, "", f"'operation' must be one of {', '.join(_OPERATIONS)}.")
        store = self._nodes()
        try:
            if operation == "guide":
                return ToolResult(True, GUIDE)
            if operation == "list":
                return await self._list(store)
            if operation == "create":
                return await self._create(store, args, ctx)
            node = await self._find(store, args, operation)
            if operation == "read":
                return self._read(node, args)
            if operation == "edit":
                return await self._edit(store, node, args, ctx)
            if operation == "duplicate":
                return await self._duplicate(store, node, args, ctx)
            return await self._revert(store, node, ctx)
        except NodeError as exc:  # the model's call to fix; the error says how
            return ToolResult(False, "", str(exc))
        except OSError as exc:
            log.warning("whiteboard %s: archive not writable", operation, exc_info=True)
            return ToolResult(False, "", f"The board could not be saved: {exc}")

    # ---------------------------------------------------------- operations

    async def _find(self, store: NodeStore, args: dict[str, Any], operation: str) -> Node:
        reference = _text(args.get("board") or args.get("node"))
        if reference is None:
            raise NodeError(f"'board' is required for {operation}: the board's id or exact title.")
        node = await asyncio.to_thread(store.find, reference)
        if node is None:
            raise NodeError(
                f"No board with the id or title {reference!r}; call operation 'list' to see them."
            )
        if node.type != "whiteboard":
            raise NodeError(
                f"'{node.title}' is a {node.type} node, not a whiteboard; the node tool changes it."
            )
        return node

    async def _list(self, store: NodeStore) -> ToolResult:
        nodes = await asyncio.to_thread(store.list_nodes)
        boards = [_summary(n) for n in nodes if n.type == "whiteboard"]
        if not boards:
            return ToolResult(True, "There are no whiteboards yet; 'create' makes one.")
        return ToolResult(True, boards)

    async def _create(self, store: NodeStore, args: dict[str, Any], ctx: Any) -> ToolResult:
        from dodaios.nodes.board.scene import empty_scene

        actions = _actions_of(args)
        title = _text(args.get("title")) or DEFAULT_TITLE
        scene = empty_scene()
        report: list[str] = []
        if actions:
            scene, report = await asyncio.to_thread(ops.apply_actions, scene, actions)
        node = await asyncio.to_thread(
            store.create, type="whiteboard", title=title, spec=scene, language=_language(ctx, args)
        )
        job_id = jobs.start(
            "artifact",
            ctx=ctx,
            title=node.title,
            target=f"node:{node.id}",
            meta={"node_id": node.id},
        )
        jobs.finish(job_id, "done", summary="Whiteboard.", result_ref=f"artifact:{node.visual_id}")
        shown = await post_card(
            session_of(ctx), page_card(node.title, node.visual_id, node_type=node.type)
        )
        where = (
            "Its card is in the chat"
            if shown
            else "It is in the Nodes section (no card could be posted)"
        )
        lines = "\n".join(report)
        text = (
            f"Created the whiteboard '{node.title}' (board id {node.id}, version {node.version}). "
            f"{where}; the person can draw on it too."
            + (f"\n{lines}" if lines else "")
            + "\nAnswer briefly; do not describe the board element by element."
        )
        return ToolResult(True, jobs.with_job_id(text, job_id, ctx))

    def _read(self, node: Node, args: dict[str, Any]) -> ToolResult:
        ids = _json_value(args.get("ids"))
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
            raise NodeError("'ids' must be a list of element ids.")
        reading = ops.describe(
            node.spec, ids=ids, raw=bool(args.get("raw")), query=_text(args.get("query"))
        )
        payload = {"board": node.id, "title": node.title, "version": node.version, **reading}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text) > MAX_READ_CHARS:
            return ToolResult(
                True,
                f"The reading is {len(text)} characters long; these are the first {MAX_READ_CHARS} "
                f"(narrow it with 'query' or 'ids'):\n{text[:MAX_READ_CHARS]}",
            )
        return ToolResult(True, text)

    async def _edit(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        actions = _actions_of(args)
        if not actions:
            raise NodeError(
                "'edit' needs 'actions' (or 'mermaid' / 'diagram'); call 'guide' for the reference."
            )
        title = _text(args.get("title"))

        def run() -> tuple[Node, list[str]]:
            # Under the node's lock, on the scene as stored now: a save from the
            # editor cannot land between this read and the write.
            with store.locked(node.id):
                _, scene = store.scene_of(node.id)
                new_scene, report = ops.apply_actions(scene, actions)
                return store.update(node.id, spec=new_scene, title=title), report

        updated, report = await asyncio.to_thread(run)
        if not _called_in_background(ctx):
            await post_card(
                session_of(ctx), page_card(updated.title, updated.visual_id, node_type=updated.type)
            )
        return ToolResult(
            True,
            f"Board '{updated.title}' is now version {updated.version}.\n" + "\n".join(report),
        )

    async def _duplicate(
        self, store: NodeStore, node: Node, args: dict[str, Any], ctx: Any
    ) -> ToolResult:
        title = _text(args.get("title")) or f"{node.title} (copy)"
        copy = await asyncio.to_thread(store.duplicate, node.id, title=title)
        await post_card(session_of(ctx), page_card(copy.title, copy.visual_id, node_type=copy.type))
        return ToolResult(
            True, f"Copied '{node.title}' to the new board '{copy.title}' (board id {copy.id})."
        )

    async def _revert(self, store: NodeStore, node: Node, ctx: Any) -> ToolResult:
        restored = await asyncio.to_thread(store.revert, node.id)
        if not _called_in_background(ctx):
            await post_card(
                session_of(ctx),
                page_card(restored.title, restored.visual_id, node_type=restored.type),
            )
        return ToolResult(
            True,
            f"Board '{restored.title}' has its earlier content again "
            f"(now version {restored.version}).",
        )


__all__ = ["GUIDE", "MAX_READ_CHARS", "WhiteboardTool"]
