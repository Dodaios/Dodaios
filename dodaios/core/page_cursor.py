"""Opaque keyset cursors for newest-first list endpoints.

A cursor names the last row a page returned as ``(created, id)``. The next
page is everything strictly older, so rows inserted meanwhile never shift it.
"""

from __future__ import annotations

import base64
import json


def encode_cursor(created: int, row_id: str) -> str:
    raw = json.dumps([int(created), str(row_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    """The ``(created, id)`` a cursor names; ``ValueError`` when it is not one."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, row_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return int(created), str(row_id)
    except Exception as exc:  # noqa: BLE001 - any malformed token is one error
        raise ValueError("invalid cursor") from exc
