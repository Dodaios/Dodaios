"""Small edits to a node's spec, so a revision does not resend the whole node.

"Change the title of slide three" is one value at one place. The assistant
names the place with a path (``/slides/2/title``, the JSON Pointer form) and
says what happens there:

* ``set``     put ``value`` at the path (replace what is there; on a list
              index past the end, or the index ``-``, append)
* ``insert``  put ``value`` into the list BEFORE the index (``-`` appends)
* ``remove``  take the key or the list item away
* ``move``    take the list item at the path and put it at index ``to`` of
              the same list (the index it has afterwards)
* ``replace`` in the TEXT at the path, put ``value`` where ``find`` stands;
              ``find`` must occur exactly once, so an edit to a long text
              (a document's Markdown, a design's CSS) names its place and
              does not resend the text
* ``append``  add ``value`` to the end of the text at the path, or to the end
              of the list there

List indices count from 0. Pure functions on plain JSON data. The result is
validated by the type's own ``normalize`` afterwards, so an edit can never
leave a spec the renderer does not understand.
"""

from __future__ import annotations

import copy
from typing import Any, Final

from dodaios.nodes.types import NodeError

MAX_CHANGES: Final[int] = 200
_OPS: Final[tuple[str, ...]] = ("set", "insert", "remove", "move", "replace", "append")
#: Ops that edit the value AT the path instead of putting one there.
_IN_PLACE: Final[frozenset[str]] = frozenset({"replace", "append"})


def _tokens(path: Any) -> list[str]:
    text = str(path or "").strip()
    if not text.startswith("/"):
        raise NodeError(
            f"A change's 'path' must start with '/', e.g. '/slides/0/title' (got {text!r})."
        )
    return [part.replace("~1", "/").replace("~0", "~") for part in text[1:].split("/")]


def _index(part: str, size: int, *, path: str, allow_end: bool) -> int:
    token = part
    if part == "-" and allow_end:
        return size
    try:
        index = int(token)
    except ValueError:
        raise NodeError(f"'{path}': {token!r} is not a list index.") from None
    if index < 0:
        index += size
    limit = size if allow_end else size - 1
    if not 0 <= index <= limit:
        raise NodeError(f"'{path}': index {token} is outside the list (it has {size} items).")
    return index


def _parent(root: Any, tokens: list[str], path: str) -> Any:
    """Walk to the container that holds the last token."""
    node = root
    for depth, token in enumerate(tokens[:-1]):
        where = "/" + "/".join(tokens[: depth + 1])
        if isinstance(node, dict):
            if token not in node:
                raise NodeError(f"'{path}': nothing at '{where}'.")
            node = node[token]
        elif isinstance(node, list):
            node = node[_index(token, len(node), path=path, allow_end=False)]
        else:
            held = "/" + "/".join(tokens[:depth])
            raise NodeError(f"'{path}': '{held}' is a single value, not a list or an object.")
    return node


def _apply_one(root: dict[str, Any], change: Any) -> None:
    if not isinstance(change, dict):
        raise NodeError("Each change is an object: {\"op\": ..., \"path\": ..., \"value\": ...}.")
    op = str(change.get("op") or "set").strip().lower()
    if op not in _OPS:
        raise NodeError(f"A change's 'op' must be one of: {', '.join(_OPS)}.")
    path = str(change.get("path") or "")
    tokens = _tokens(path)
    if tokens == [""]:
        raise NodeError("A change cannot replace the whole spec; send 'spec' instead.")
    parent = _parent(root, tokens, path)
    last = tokens[-1]
    value = copy.deepcopy(change.get("value"))
    if op in _IN_PLACE:
        _edit_in_place(parent, last, op, change, value, path)
        return

    if isinstance(parent, dict):
        if op == "set":
            parent[last] = value
        elif op == "remove":
            if last not in parent:
                raise NodeError(f"'{path}': nothing there to remove.")
            del parent[last]
        else:
            raise NodeError(f"'{path}': '{op}' needs a list, and this is an object.")
        return

    if not isinstance(parent, list):
        raise NodeError(f"'{path}': its parent is a single value, not a list or an object.")
    size = len(parent)
    if op == "set":
        index = _index(last, size, path=path, allow_end=True)
        if index == size:
            parent.append(value)
        else:
            parent[index] = value
    elif op == "insert":
        parent.insert(_index(last, size, path=path, allow_end=True), value)
    elif op == "remove":
        del parent[_index(last, size, path=path, allow_end=False)]
    else:  # move
        index = _index(last, size, path=path, allow_end=False)
        target = _index(str(change.get("to", "")), size, path=path, allow_end=False)
        parent.insert(target, parent.pop(index))


def _edit_in_place(
    parent: Any, last: str, op: str, change: dict[str, Any], value: Any, path: str
) -> None:
    """``replace`` and ``append``: change the text (or list) that is at the path."""
    if isinstance(parent, dict):
        if last not in parent:
            raise NodeError(f"'{path}': nothing there; '{op}' edits a value that exists.")
        key: Any = last
    elif isinstance(parent, list):
        key = _index(last, len(parent), path=path, allow_end=False)
    else:
        raise NodeError(f"'{path}': its parent is a single value, not a list or an object.")
    current = parent[key]
    if op == "append":
        if isinstance(current, list):
            current.append(value)
        elif isinstance(current, str):
            parent[key] = current + str(value if value is not None else "")
        else:
            raise NodeError(f"'{path}': 'append' needs a text or a list there.")
        return
    if not isinstance(current, str):
        raise NodeError(f"'{path}': 'replace' needs a text there; use 'set' for other values.")
    find = change.get("find")
    if not isinstance(find, str) or not find:
        raise NodeError(f"'{path}': 'replace' needs 'find', the exact text to replace.")
    found = current.count(find)
    if found == 0:
        raise NodeError(
            f"'{path}': the text of 'find' is not there. Read the node with 'get' and copy "
            "the passage exactly."
        )
    if found > 1 and not change.get("all"):
        raise NodeError(
            f"'{path}': the text of 'find' occurs {found} times; make it longer so it is "
            "unique, or add \"all\": true."
        )
    parent[key] = current.replace(find, str(value if value is not None else ""))


def apply_changes(spec: dict[str, Any], changes: Any) -> dict[str, Any]:
    """A copy of ``spec`` with ``changes`` applied in order.

    Raises:
        NodeError: a change is malformed or points at nothing. Nothing is
            applied then; the caller keeps the spec it had.
    """
    if not isinstance(changes, list) or not changes:
        raise NodeError("'changes' must be a non-empty list of edits.")
    if len(changes) > MAX_CHANGES:
        raise NodeError(f"At most {MAX_CHANGES} changes at once; send 'spec' for a rewrite.")
    result = copy.deepcopy(spec)
    for change in changes:
        _apply_one(result, change)
    return result


__all__ = ["MAX_CHANGES", "apply_changes"]
