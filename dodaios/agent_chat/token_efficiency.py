"""How much of a turn's input was re-read context versus new work.

An always-on agent wakes many times a day, and every wake re-reads the whole
conversation. This module records, per turn, the split between

* **re-read** context: the conversation history, the catch-up block and the
  system prompt the model had to read again, and
* **new work**: the person's message, tool results and the model's output.

The split rides on ``turn_finished`` as ``payload["context"]`` and the costs
panel rolls it up per agent as ``reread_share``. It is a measurement only:
nothing here shortens, drops or caps context.

When the runner reported token usage the split is in tokens (the input side
minus an estimate of the new input, the cached reads counted as re-read).
Otherwise it falls back to characters of the history versus characters of the
turn's own events, and says so in ``unit``.
"""

from __future__ import annotations

from typing import Any, Final, NamedTuple

#: Characters per token for converting a character split into token terms.
CHARS_PER_TOKEN: Final[int] = 4

_IN_KEYS: Final[tuple[str, ...]] = ("input_tokens", "prompt_tokens")
_CACHED_KEYS: Final[tuple[str, ...]] = (
    "cache_read_input_tokens",
    "cached_input_tokens",
    "cache_read_tokens",
    "cache_hit_tokens",
)
_OUT_KEYS: Final[tuple[str, ...]] = ("output_tokens", "completion_tokens")
_MAX_OPEN_TURNS: Final[int] = 256


class TurnBasis(NamedTuple):
    """What a turn started from: the history it re-reads."""

    after_seq: int
    history_chars: int


_open: dict[str, TurnBasis] = {}


def _text_len(event: dict[str, Any]) -> int:
    payload = event.get("payload") or {}
    kind = event.get("kind")
    if kind in {"user_message", "assistant_text"}:
        return len(str(payload.get("text") or ""))
    if kind == "tool_result":
        return len(str(payload.get("output") or ""))
    if kind == "agent_message":
        return len(str(payload.get("prompt") or payload.get("text") or ""))
    return 0


def note_turn_start(turn_id: str, history: list[dict[str, Any]], *, start_seq: int = 0) -> None:
    """Remember the history a turn begins with (called once per turn)."""
    if not turn_id:
        return
    after = max((int(e.get("seq") or 0) for e in history), default=start_seq)
    while len(_open) >= _MAX_OPEN_TURNS:
        _open.pop(next(iter(_open)))
    _open[turn_id] = TurnBasis(after, sum(_text_len(e) for e in history))


def take_basis(turn_id: str) -> TurnBasis | None:
    return _open.pop(turn_id, None)


def _sum(usage: dict[str, Any], keys: tuple[str, ...]) -> int:
    total = 0
    for key in keys:
        try:
            total += max(0, int(usage.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return total


def context_split(
    usage: dict[str, Any] | None,
    *,
    history_chars: int,
    turn_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """``{"reread", "fresh", "unit", "reread_share"}`` for one finished turn.

    ``turn_events`` are the events the turn itself produced (the person's
    message, tool results, answer); ``history_chars`` is what it started from.
    """
    usage = usage if isinstance(usage, dict) else {}
    new_in_chars = sum(
        _text_len(e) for e in turn_events if e.get("kind") in {"user_message", "tool_result"}
    )
    out_chars = sum(_text_len(e) for e in turn_events if e.get("kind") == "assistant_text")
    tokens_in = _sum(usage, _IN_KEYS) + _sum(usage, _CACHED_KEYS)
    tokens_out = _sum(usage, _OUT_KEYS)
    if tokens_in > 0:
        fresh_in = min(tokens_in, new_in_chars // CHARS_PER_TOKEN)
        reread = tokens_in - fresh_in
        fresh = fresh_in + (tokens_out or out_chars // CHARS_PER_TOKEN)
        unit = "tokens"
    else:
        reread = max(0, int(history_chars))
        fresh = new_in_chars + out_chars
        unit = "chars"
    total = reread + fresh
    return {
        "reread": reread,
        "fresh": fresh,
        "unit": unit,
        "reread_share": round(reread / total, 4) if total > 0 else 0.0,
    }


def annotate_turn_finished(store: Any, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """``event`` with ``payload["context"]`` added; the event itself on any failure."""
    payload = event.get("payload")
    if not isinstance(payload, dict) or "context" in payload:
        return event
    basis = take_basis(str(payload.get("turn_id") or ""))
    if basis is None:
        return event
    try:
        turn_events = store.list_events(session_id, after_seq=basis.after_seq)
        context = context_split(
            payload.get("usage"), history_chars=basis.history_chars, turn_events=turn_events
        )
    except Exception:  # noqa: BLE001 - a measurement never blocks the turn's end
        return event
    return {**event, "payload": {**payload, "context": context}}
