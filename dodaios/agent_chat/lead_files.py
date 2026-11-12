"""The files the assistant handed over in its conversation.

When the assistant makes a file for the person outside a mission (a
spreadsheet in its chat workspace, a document on the Desktop), nothing but
its own message says so: "The file is ready: [name](/path/to/name)". That
link is the record. This module reads the newest messages of the
conversation and returns the files they link, newest file first, for the
front page's panel (``GET /api/agent-chat/lead/files``).

Only a link with a full local path counts, and only while that exact file
exists. A program or a script is left out: the panel opens a row with the
same route a chat link uses, and that route refuses them
(``platform.open_path``). Files a mission made are not listed here; they are
the outputs' own (``/api/outputs``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from dodaios.platform.open_path import ChatOpenRejected, chat_link_path, prepare_chat_open

#: A Markdown link or image: ``[label](target)`` or ``[label](<target with spaces>)``.
_LINK = re.compile(r"\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\s]+)[^)\n]*\)")
#: How many of the newest messages are read, so the cost does not grow with
#: an endless conversation.
SCAN_MESSAGES = 300


def linked_paths(text: str) -> list[str]:
    """The full local paths a message links, in the order it names them."""
    out: list[str] = []
    for target in _LINK.findall(text or ""):
        native = chat_link_path(target)
        if native is not None and native not in out:
            out.append(native)
    return out


def _existing_file(native: str) -> Path | None:
    """The exact file a link names, when a chat link may open it."""
    try:
        target = prepare_chat_open(native)
    except ChatOpenRejected:  # no file a chat link may open: it is simply not listed
        return None
    # A link whose file is gone must not turn into a file of the same name
    # found elsewhere: the row would open something the message never named.
    wanted = Path(native).expanduser()
    try:
        same = target.is_file() and target.resolve() == wanted.resolve()
    except OSError:  # the file went away while it was looked at: not listed
        return None
    return target if same else None


def handed_over(messages: list[tuple[int, str]], *, limit: int = 30) -> list[dict[str, Any]]:
    """The files ``messages`` link, the newest file first.

    ``messages`` are ``(ts_ms, text)`` of the assistant's own messages. A
    file linked more than once is listed once. Reads the filesystem: call it
    off the event loop.
    """
    seen: set[str] = set()
    files: list[dict[str, Any]] = []
    for ts_ms, text in messages:
        for native in linked_paths(text):
            target = _existing_file(native)
            if target is None or str(target) in seen:
                continue
            seen.add(str(target))
            try:
                stat = target.stat()
            except OSError:  # removed between the check and the read: not listed
                continue
            files.append(
                {
                    "path": str(target),
                    "name": target.name,
                    "size": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                    "linked_ms": int(ts_ms),
                }
            )
    files.sort(key=lambda row: row["mtime"], reverse=True)
    return files[: max(0, int(limit))]
