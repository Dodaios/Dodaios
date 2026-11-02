"""Envelope, close codes, error codes and limits of ``verse.bridge/1``.

Everything here is frozen by ``contracts/bridge-protocol.md`` sections 1, 2
and 8. The codec is deliberately strict on the envelope (a frame that is not
an object with a string ``type`` is malformed) and lenient on payloads
(unknown fields and unknown types are ignored, contract section 2).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Final

PROTOCOL: Final = "verse.bridge/1"
SUPPORTED_PROTOCOLS: Final = (PROTOCOL,)
PATH: Final = "/api/verse/bridge"

# Close codes (contract section 1).
CLOSE_BAD_HELLO: Final = 4400
CLOSE_TOKEN: Final = 4401
CLOSE_PEER: Final = 4403
CLOSE_REPLACED: Final = 4409
CLOSE_PROTOCOL: Final = 4426
CLOSE_TOO_BIG: Final = 1009
CLOSE_TRY_LATER: Final = 1013

HELLO_TIMEOUT_S: Final = 5.0
DEAD_LINK_S: Final = 5.0
MAX_FRAME_BYTES: Final = 1 << 20

# Reply error codes (contract section 2).
ERROR_CODES: Final = (
    "bad_request",
    "not_found",
    "conflict",
    "busy",
    "unavailable",
    "rate_limited",
    "internal",
)

#: Feature names announced in ``welcome.features``; a topic outside this set
#: answers ``unavailable``.
BASE_FEATURES: Final = (
    "roster",
    "panes",
    "screens",
    "chat_tails",
    "meetings",
    "groups",
    "progression",
    "companion",
    "lifecycle",
    "panel",
)

#: Topics that answer ``subscribe`` with a snapshot (schema ``x-subscribed-topics``).
SNAPSHOT_TOPICS: Final = ("roster", "groups", "meetings", "progression", "companion")
#: Topics a subscription accepts without sending anything (fixture README).
SILENT_TOPICS: Final = ("panes", "duel_stats", "lifecycle", "panel")

LIMITS: Final = {
    "screens_max_panes": 8,
    "screens_max_rows": 60,
    "screens_max_cols": 240,
    "screens_max_hz": 10,
    "chat_tails_max_agents": 6,
    "chat_tail_lines": 12,
}

SCREENS_MAX_BYTES_PER_S: Final = 200 * 1024

#: Verse frames that carry no ``id`` and get no reply (fixture README).
NOTICES: Final = frozenset(
    {
        "hello",
        "ping",
        "log",
        "lifecycle.state",
        "lifecycle.ready",
        "lifecycle.bye",
        "window.state",
        "panel.stream_state",
        "focus.return_to_app",
    }
)

DUTY_STATUSES: Final = ("working", "waiting", "idle", "paused", "error")
LIFECYCLE_STATES: Final = ("booting", "visible", "panel", "dormant", "exiting")


class BridgeError(Exception):
    """A command failed; becomes ``reply {ok: false, error: {code, message}}``."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ERROR_CODES:
            code = "internal"
        super().__init__(message)
        self.code = code
        self.message = message


class MalformedFrame(ValueError):
    """Text that is not a ``verse.bridge/1`` JSON frame."""


@dataclass(frozen=True, slots=True)
class Inbound:
    """One parsed Verse -> server frame."""

    type: str
    data: dict[str, Any]
    id: str | None
    ts: float | None
    raw: dict[str, Any]


def now() -> float:
    return time.time()


def parse(text: str | bytes) -> Inbound:
    """Parse one Verse frame. Raises :class:`MalformedFrame` on a bad envelope."""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedFrame("frame is not UTF-8") from exc
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise MalformedFrame(f"frame is not JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise MalformedFrame("frame is not a JSON object")
    type_ = obj.get("type")
    if not isinstance(type_, str) or not type_:
        raise MalformedFrame("frame has no type")
    data = obj.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise MalformedFrame("data is not an object")
    rid = obj.get("id")
    if rid is not None and not isinstance(rid, str):
        raise MalformedFrame("id is not a string")
    ts = obj.get("ts")
    if ts is not None and (isinstance(ts, bool) or not isinstance(ts, int | float)):
        raise MalformedFrame("ts is not a number")
    return Inbound(type=type_, data=data, id=rid, ts=float(ts) if ts is not None else None, raw=obj)


def frame(
    type_: str,
    seq: int,
    data: dict[str, Any],
    *,
    base: int | None = None,
    re: str | None = None,
    ts: float | None = None,
) -> dict[str, Any]:
    """A server -> Verse frame in envelope order ``type, seq, base, re, ts, data``."""
    out: dict[str, Any] = {"type": type_, "seq": seq}
    if base is not None:
        out["base"] = base
    if re is not None:
        out["re"] = re
    out["ts"] = round(now() if ts is None else ts, 3)
    out["data"] = data
    return out


def encode(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def ok(result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"ok": True, "result": result if result is not None else {}}


def error(code: str, message: str) -> dict[str, Any]:
    if code not in ERROR_CODES:
        code = "internal"
    return {"ok": False, "error": {"code": code, "message": message}}


def welcome_reason_unsupported() -> str:
    """Close reason for ``4426``: ``welcome``-shaped text naming the supported versions."""
    return encode({"type": "welcome", "data": {"protocols": list(SUPPORTED_PROTOCOLS)}})
