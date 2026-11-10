"""Hand-offs that happen once, however often the call arrives.

A model repeats a call after a timeout, a CLI seat retries an MCP call that
took too long, and a weak model sends the same message twice in one turn. For
a read that is harmless; for ``delegate_to_agent`` and ``message_agent`` it is
a second assignment or a second message. Each such call carries an
idempotency key, ``hash(turn, tool, normalized arguments)``, and the receipt
of the first success is kept in the society store: a repeat returns that
receipt and sends nothing.

A failed first attempt leaves no receipt, so a retry after a failure still
runs. A different turn has a different key, so asking again on purpose in a
later turn works.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.core.protocols import ToolResult, current_chat_turn

__all__ = ["idempotency_key", "run_once"]

log = logging.getLogger(__name__)

_META_PREFIX = "idem:"
_SPACE_RE = re.compile(r"\s+")
_locks: dict[str, asyncio.Lock] = {}


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return _SPACE_RE.sub(" ", value).strip()
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in sorted(value.items(), key=lambda i: str(i[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    return value


def turn_identity(ctx: Any) -> str:
    """The turn a call belongs to: the chat turn when there is one, else the trace."""
    turn = current_chat_turn.get()
    if turn is not None:
        return f"{turn.session_id}:{turn.turn_id}"
    return str(getattr(ctx, "trace_id", "") or "")


def idempotency_key(ctx: Any, tool: str, args: dict[str, Any]) -> str:
    wire = json.dumps(
        [turn_identity(ctx), tool, _normalise(args or {})],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()[:32]


def _encode(result: ToolResult) -> str:
    return json.dumps(
        {"success": result.success, "output": result.output, "artifacts": list(result.artifacts)},
        ensure_ascii=False,
        default=str,
    )


def _decode(raw: str) -> ToolResult | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    output = data.get("output")
    if isinstance(output, dict):
        output = {**output, "idempotent_replay": True, "note": (
            "This exact request already went out in this turn; this is its first receipt. "
            "Nothing was sent again."
        )}
    return ToolResult(
        success=bool(data.get("success")),
        output=output,
        artifacts=tuple(str(a) for a in data.get("artifacts") or ()),
    )


async def run_once(
    store: Any, key: str, run: Callable[[], Awaitable[ToolResult]]
) -> ToolResult:
    """Run ``run`` unless a call with this key already succeeded; then replay its receipt.

    Concurrent calls with one key wait for the first. A store that cannot be
    read or written never blocks the hand-off: the call runs as it did before.
    """
    meta_key = _META_PREFIX + key
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            try:
                cached = await store.get_meta(meta_key)
            except Exception:  # noqa: BLE001 — no receipt book, no deduplication
                log.warning("idempotency: receipt lookup failed", exc_info=True)
                cached = ""
            if cached:
                replay = _decode(cached)
                if replay is not None:
                    log.info("idempotency: replaying the first receipt for %s", key)
                    return replay
            result = await run()
            if result.success:
                try:
                    await store.set_meta(meta_key, _encode(result))
                    await store.conn.commit()
                except Exception:  # noqa: BLE001 — losing the receipt only loses deduplication
                    log.warning("idempotency: receipt write failed", exc_info=True)
            return result
    finally:
        _locks.pop(key, None)
