"""Mermaid flowcharts as whiteboard diagrams.

A model knows Mermaid's flowchart syntax well and writes it compactly, so
``mermaid`` is the shortest way for it to put a process, an architecture or a
decision tree on a board. This module reads the ``flowchart``/``graph``
subset into the same diagram structure the ``diagram`` action takes
(:mod:`dodaios.nodes.board.convert`), which lays it out and draws it with the
board's own elements: nothing of Mermaid runs, no markup is produced, and a
diagram drawn this way is edited like anything else on the board.

Read: the direction (``TD``/``TB``/``LR``/``RL``/``BT``), node shapes
(``[ ]`` box, ``( )`` and ``([ ])`` rounded, ``{ }`` diamond, ``(( ))``
circle, ``[[ ]]``, ``[( )]``, ``{{ }}``, ``>  ]``, ``[/ /]`` drawn as boxes),
quoted labels, ``<br>`` line breaks, edges ``-->``, ``---``, ``-.->``,
``==>``, ``<-->``, ``--o``, ``--x``, labels as ``--text-->`` or
``-->|text|``, chains (``A --> B --> C``), ``&`` (``A & B --> C``) and
``subgraph … end`` (a frame; a nested subgraph joins its outermost one,
because the editor's frames do not nest). ``classDef``, ``class``, ``style``,
``linkStyle``, ``click``, ``direction`` inside a subgraph and ``%%`` comments
are skipped. Any other diagram kind is refused with a sentence naming the
kinds that work, so the model can switch to the ``diagram`` action.
"""

from __future__ import annotations

import re
from typing import Any, Final

from dodaios.nodes.types import NodeError

MAX_SOURCE_CHARS: Final[int] = 20_000
MAX_NODES: Final[int] = 300
MAX_EDGES: Final[int] = 600
MAX_LABEL_CHARS: Final[int] = 200

_HEADER_RE: Final = re.compile(r"^(flowchart|graph)(?:\s+(TD|TB|BT|LR|RL))?\s*;?\s*$", re.I)
_OTHER_KINDS: Final[tuple[str, ...]] = (
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "timeline",
    "gitGraph",
    "quadrantChart",
    "requirementDiagram",
    "C4Context",
    "sankey",
    "xychart",
    "block",
    "packet",
    "kanban",
    "architecture",
)
_SKIPPED: Final = re.compile(
    r"^(classDef|class|style|linkStyle|click|direction|accTitle|accDescr)\b", re.I
)
_ID_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")

#: Openers, longest first, with their closers and the board shape they become.
_SHAPES: Final[tuple[tuple[str, str, str], ...]] = (
    ("(((", ")))", "circle"),
    ("([", "])", "rounded"),
    ("[[", "]]", "box"),
    ("[(", ")]", "box"),
    ("((", "))", "circle"),
    ("{{", "}}", "box"),
    ("[/", "/]", "box"),
    ("[\\", "\\]", "box"),
    (">", "]", "box"),
    ("[", "]", "box"),
    ("(", ")", "rounded"),
    ("{", "}", "diamond"),
)

#: An edge with its text inside the stroke: ``A -- text --> B``.
_TEXT_EDGE: Final = re.compile(
    r"\s*(?P<back><)?(?P<open>--|==|-\.)(?![->.=])\s*"
    r"(?P<text>\"[^\"]*\"|[^|\"]+?)\s*"
    r"(?P<close>-{2,}>|={2,}>|\.-+>|\.-+|-{3,}|={3,}|-{2,}[ox]|={2,}[ox])"
)
#: A plain edge operator.
_EDGE: Final = re.compile(
    r"\s*(?P<op><?-{2,}>|<?={2,}>|<?-\.+->|-\.+-[ox]?|-{3,}|={3,}|-{2,}[ox]|={2,}[ox]|~{3,})"
)
_PIPE_LABEL: Final = re.compile(r"\s*\|(?P<label>[^|]*)\|")


def _label(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = (
        text.replace("#quot;", '"').replace("#amp;", "&").replace("#lt;", "<").replace("#gt;", ">")
    )
    text = text.replace("`", "")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)[:MAX_LABEL_CHARS]


def _strip_comment(line: str) -> str:
    """The line without a ``%%`` comment (outside a quoted label)."""
    quoted = False
    for at, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif not quoted and line.startswith("%%", at):
            return line[:at]
    return line


def _statements(source: str) -> list[tuple[int, str]]:
    """``(line number, statement)`` pairs; ``;`` outside quotes splits a line."""
    out: list[tuple[int, str]] = []
    for number, raw in enumerate(source.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        part, quoted = "", False
        for char in line:
            if char == '"':
                quoted = not quoted
            if char == ";" and not quoted:
                if part.strip():
                    out.append((number, part.strip()))
                part = ""
                continue
            part += char
        if part.strip():
            out.append((number, part.strip()))
    return out


class _Parser:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.edges: list[dict[str, Any]] = []
        self.groups: list[dict[str, Any]] = []
        self.group_of: dict[str, str] = {}
        self.stack: list[dict[str, Any]] = []

    def node(self, node_id: str, label: str | None, shape: str | None) -> None:
        known = self.nodes.get(node_id)
        if known is None:
            if len(self.nodes) >= MAX_NODES:
                raise NodeError(f"The flowchart has more than {MAX_NODES} nodes; split it up.")
            known = {"id": node_id, "label": node_id, "shape": "box"}
            self.nodes[node_id] = known
            self.order.append(node_id)
        if label is not None:
            known["label"] = label or node_id
        if shape is not None:
            known["shape"] = shape
        if self.stack and node_id not in self.group_of and node_id not in self._group_ids():
            outermost = self.stack[0]
            self.group_of[node_id] = outermost["id"]
            outermost["nodes"].append(node_id)

    def _group_ids(self) -> set[str]:
        return {group["id"] for group in self.groups}

    def subgraph(self, rest: str, number: int) -> None:
        rest = rest.strip()
        match = re.match(r"^([A-Za-z0-9_][\w.\-]*)\s*\[(.*)\]\s*$", rest)
        if match:
            group_id, label = match.group(1), _label(match.group(2))
        elif rest.startswith('"'):
            label = _label(rest)
            group_id = (
                re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_")[:40]
                or f"group{len(self.groups) + 1}"
            )
        elif rest and _ID_RE.fullmatch(rest):
            group_id, label = rest, rest
        elif rest:
            label = _label(rest)
            group_id = (
                re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_")[:40]
                or f"group{len(self.groups) + 1}"
            )
        else:
            group_id, label = f"group{len(self.groups) + 1}", ""
        group: dict[str, Any] = {"id": group_id, "label": label, "nodes": []}
        if not self.stack:
            self.groups.append(group)
        else:
            # Frames do not nest in the editor: an inner subgraph's nodes join
            # the outermost one, and its id still names that frame in edges.
            group = {
                "id": group_id,
                "label": label,
                "nodes": self.stack[0]["nodes"],
                "alias": self.stack[0]["id"],
            }
        self.stack.append(group)

    def end(self, number: int) -> None:
        if not self.stack:
            raise NodeError(f"Line {number}: 'end' without a 'subgraph' before it.")
        closed = self.stack.pop()
        if "alias" in closed:
            self.aliases[closed["id"]] = closed["alias"]

    aliases: dict[str, str]

    def node_ref(self, text: str, at: int, number: int) -> tuple[str, str | None, str | None, int]:
        """One node reference at ``at``: its id, label and shape (``None`` when not
        given) and where it ends."""
        while at < len(text) and text[at] == " ":
            at += 1
        match = _ID_RE.match(text, at)
        if not match:
            snippet = text[at : at + 20] or "the end of the line"
            raise NodeError(f"Line {number}: expected a node id at {snippet!r}.")
        node_id = match.group(0)
        at = match.end()
        # An id that runs into an edge (``A--B``) loses the dashes it swallowed.
        while node_id.endswith(("-", ".")) and len(node_id) > 1:
            node_id = node_id[:-1]
            at -= 1
        label: str | None = None
        shape: str | None = None
        for opener, closer, name in _SHAPES:
            if text.startswith(opener, at):
                start = at + len(opener)
                if start < len(text) and text[start] == '"':
                    quote_end = text.find('"', start + 1)
                    if quote_end < 0:
                        raise NodeError(f"Line {number}: a label's closing quote is missing.")
                    end = text.find(closer, quote_end + 1)
                else:
                    end = text.find(closer, start)
                if end < 0:
                    raise NodeError(
                        f"Line {number}: the shape of node {node_id!r} opens with {opener!r} "
                        f"but never closes with {closer!r}."
                    )
                label = _label(text[start:end])
                shape = name
                at = end + len(closer)
                break
        if text.startswith(":::", at):
            match = _ID_RE.match(text, at + 3)
            at = match.end() if match else at + 3
        return node_id, label, shape, at

    def group_refs(
        self, text: str, at: int, number: int
    ) -> tuple[list[tuple[str, str | None, str | None]], int]:
        refs: list[tuple[str, str | None, str | None]] = []
        while True:
            node_id, label, shape, at = self.node_ref(text, at, number)
            refs.append((node_id, label, shape))
            match = re.match(r"\s*&\s*", text[at:])
            if not match:
                return refs, at
            at += match.end()

    def statement(self, number: int, text: str) -> None:
        refs, at = self.group_refs(text, 0, number)
        for node_id, label, shape in refs:
            self.node(node_id, label, shape)
        while at < len(text):
            edge = self._edge(text, at, number)
            if edge is None:
                rest = text[at:].strip()
                raise NodeError(
                    f"Line {number}: cannot read {rest[:30]!r}; expected an edge like '-->'."
                )
            props, at = edge
            targets, at = self.group_refs(text, at, number)
            for node_id, label, shape in targets:
                self.node(node_id, label, shape)
            if props is not None:
                for source, _, _ in refs:
                    for target, _, _ in targets:
                        if len(self.edges) >= MAX_EDGES:
                            raise NodeError(f"The flowchart has more than {MAX_EDGES} edges.")
                        self.edges.append({"from": source, "to": target, **props})
            refs = targets

    def _edge(self, text: str, at: int, number: int) -> tuple[dict[str, Any] | None, int] | None:
        label = ""
        match = _TEXT_EDGE.match(text, at)
        if match:
            op = (match.group("back") or "") + match.group("open") + match.group("close")
            label = _label(match.group("text"))
            at = match.end()
        else:
            match = _EDGE.match(text, at)
            if not match:
                return None
            op = match.group("op")
            at = match.end()
        pipe = _PIPE_LABEL.match(text, at)
        if pipe:
            label = _label(pipe.group("label"))
            at = pipe.end()
        if op.startswith("~"):
            return None, at  # an invisible link only keeps two nodes close
        props: dict[str, Any] = {}
        if label:
            props["label"] = label
        if "." in op:
            props["style"] = "dashed"
        elif "=" in op:
            props["style"] = "bold"
        start = "arrow" if op.startswith("<") else None
        if op.endswith(">"):
            end: str | None = "arrow"
        elif op.endswith("o"):
            end = "circle"
        elif op.endswith("x"):
            end = "bar"
        else:
            end = None
        if start == "arrow" and end == "arrow":
            props["arrow"] = "both"
        elif end is None and start is None:
            props["arrow"] = "none"
        elif end not in (None, "arrow"):
            props["end"] = end
        return props, at


def parse(source: Any) -> dict[str, Any]:
    """The flowchart in ``source`` as a diagram: ``nodes``, ``edges``, ``groups``, ``direction``."""
    if not isinstance(source, str) or not source.strip():
        raise NodeError(
            "'source' must be the text of a Mermaid flowchart, starting with 'flowchart LR'."
        )
    if len(source) > MAX_SOURCE_CHARS:
        raise NodeError(
            f"The Mermaid source is longer than {MAX_SOURCE_CHARS} characters; split it."
        )
    text = source.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    statements = _statements(text)
    if not statements:
        raise NodeError("The Mermaid source is empty.")
    first_number, first = statements[0]
    header = _HEADER_RE.match(first)
    if not header:
        kind = first.split()[0] if first.split() else first
        if any(kind.lower().startswith(other.lower()) for other in _OTHER_KINDS):
            raise NodeError(
                f"Mermaid '{kind}' diagrams are not drawn on a whiteboard; only flowcharts "
                "('flowchart TD/LR' or 'graph TD/LR') are. For other structures use the "
                "'diagram' action with nodes, edges and groups."
            )
        raise NodeError(
            "A Mermaid flowchart starts with 'flowchart' or 'graph' and a direction "
            "(TD, TB, LR, RL or BT), e.g. 'flowchart LR'."
        )
    direction = (header.group(2) or "TB").upper()
    direction = "TB" if direction == "TD" else direction
    parser = _Parser()
    parser.aliases = {}
    for number, statement in statements[1:]:
        lowered = statement.lower()
        if lowered.startswith("subgraph"):
            parser.subgraph(statement[len("subgraph") :], number)
            continue
        if lowered == "end":
            parser.end(number)
            continue
        if _SKIPPED.match(statement):
            continue
        parser.statement(number, statement)
    if parser.stack:
        raise NodeError(
            f"The subgraph '{parser.stack[-1]['label'] or parser.stack[-1]['id']}' has no 'end'."
        )
    if not parser.nodes:
        raise NodeError("The flowchart has no nodes.")
    groups = [g for g in parser.groups if g["nodes"]]
    group_ids = {g["id"] for g in groups}
    edges: list[dict[str, Any]] = []
    for edge in parser.edges:
        start = parser.aliases.get(edge["from"], edge["from"])
        end = parser.aliases.get(edge["to"], edge["to"])
        edges.append({**edge, "from": start, "to": end})
    nodes = [parser.nodes[node_id] for node_id in parser.order if node_id not in group_ids]
    return {
        "direction": direction,
        "nodes": nodes,
        "edges": edges,
        "groups": [
            {
                "id": g["id"],
                "label": g["label"],
                "nodes": [n for n in dict.fromkeys(g["nodes"]) if n not in group_ids],
            }
            for g in groups
        ],
    }


__all__ = ["MAX_EDGES", "MAX_NODES", "MAX_SOURCE_CHARS", "parse"]
