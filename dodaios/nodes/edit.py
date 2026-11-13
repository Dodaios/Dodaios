"""One value of a node, changed by the person in the page.

In the stage's edit mode the reader writes into the node's page directly
(:mod:`dodaios.nodes.bridge`). Every such change names one place of the spec
(a JSON Pointer, or ``@title`` for the node's name) and brings what was typed.
This module turns that into the store's revision: what was typed becomes the
value the spec holds there (text, a number, a yes/no), and the place must be
one the spec already has a value for, or an empty cell of a row.

The type's own ``normalize`` judges the result, as it does for the
assistant's edits: a value it does not accept is refused, and the node stays
as it was.
"""

from __future__ import annotations

import re
from typing import Any, Final

from dodaios.nodes.bridge import MAX_EDIT_CHARS, TITLE_PATH
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NodeError

#: What a field holds. Text is the default; a number is read in the reader's
#: own notation; a toggle is a yes/no.
KINDS: Final[tuple[str, ...]] = ("text", "number", "toggle")

_DIGITS = re.compile(r"^[+-]?[\d.,'   ]*\d[\d.,'   ]*$")


def read_number(typed: str) -> float | int | None:
    """What was typed as a number, in the notation people use; ``None`` for empty.

    ``"1.234,5"``, ``"1,234.5"``, ``"1234.5"``, ``"40,62"``, ``"1 200"`` and a
    leading or trailing currency or percent sign all read as the number they
    mean. A single separator followed by exactly three digits is a thousands
    mark (``"1.200"`` is 1200), as it is in every locale that writes it so.

    Raises:
        NodeError: what was typed is not a number.
    """
    text = typed.strip().strip("€$£¥%").strip()
    if text == "":
        return None
    if not _DIGITS.match(text):
        raise NodeError(f"{typed!r} is not a number.")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-").replace(" ", "").replace(" ", "").replace(" ", "")
    text = text.replace("'", "")
    marks = [char for char in text if char in ".,"]
    if not marks:
        whole, fraction = text, ""
    elif len(set(marks)) == 2:
        point = text[max(text.rfind("."), text.rfind(","))]
        group = "," if point == "." else "."
        if text.count(point) != 1:
            raise NodeError(f"{typed!r} is not a number.")
        whole, fraction = text.replace(group, "").split(point)
    else:
        mark = marks[0]
        head, _, tail = text.rpartition(mark)
        if len(marks) > 1 or (len(tail) == 3 and head not in ("", "0")):
            # Several of one mark, or one mark before three digits: thousands.
            whole, fraction = text.replace(mark, ""), ""
        else:
            whole, fraction = head, tail
    if not whole.isdigit() and whole != "" or (fraction and not fraction.isdigit()):
        raise NodeError(f"{typed!r} is not a number.")
    if fraction:
        return sign * float(f"{whole or '0'}.{fraction}")
    return sign * int(whole or "0")


def _value(value: Any, kind: str) -> Any:
    if kind == "toggle":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "1"):
            return True
        if text in ("false", "no", "0", ""):
            return False
        raise NodeError(f"{value!r} is not yes or no.")
    if kind == "number":
        if isinstance(value, bool):
            raise NodeError("A number was expected.")
        if isinstance(value, (int, float)):
            return value
        return read_number(str(value))
    text = "" if value is None else str(value)
    if len(text) > MAX_EDIT_CHARS:
        raise NodeError("That text is too long for one field.")
    return text


def _current(spec: Any, path: str) -> tuple[bool, Any]:
    """Whether the spec has a place at ``path``, and the value there.

    A missing key in an object counts as a place (an empty cell of a row);
    a missing index of a list does not (an edit never adds an item).
    """
    if not path.startswith("/") or path == "/":
        raise NodeError(f"{path!r} is not a place in the node.")
    node: Any = spec
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    for depth, part in enumerate(parts):
        last = depth == len(parts) - 1
        if isinstance(node, dict):
            if part not in node:
                if last:
                    return True, None
                raise NodeError(f"Nothing at {path!r} in this node.")
            node = node[part]
        elif isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                raise NodeError(f"Nothing at {path!r} in this node.")
            node = node[int(part)]
        else:
            raise NodeError(f"Nothing at {path!r} in this node.")
    return True, node


def apply_field(store: NodeStore, node: Node, path: str, value: Any, kind: str = "text") -> Node:
    """Save one value the reader typed into ``node``; returns the node as written.

    Raises:
        NodeError: the place does not exist, the value is not of the kind the
            field holds, or the type does not accept it.
    """
    if kind not in KINDS:
        raise NodeError(f"'as' must be one of: {', '.join(KINDS)}.")
    if path == TITLE_PATH:
        title = " ".join(str(value or "").split())
        if not title:
            raise NodeError("A node needs a name.")
        if title == node.title:
            return node
        return store.update(node.id, title=title)
    _, before = _current(node.spec, path)
    if isinstance(before, (dict, list)):
        raise NodeError(f"{path!r} holds more than one value; edit its parts.")
    after = _value(value, kind)
    if after == before or (after in ("", None) and before in ("", None)):
        return node
    return store.update(node.id, changes=[{"op": "set", "path": path, "value": after}])


__all__ = ["KINDS", "apply_field", "read_number"]
