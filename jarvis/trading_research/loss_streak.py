"""Loss-streak pause rule, isolated and testable. Not connected to any bot or
job.

Definitions:
- a LOSS is a CLOSED trade whose realised result after all fees and funding is strictly below zero;
  a result of exactly zero or above is not a loss and ends the streak;
- after `streak_limit` (3) consecutive losses no new position may be opened for `pause_ms` (24 h),
counted from
  the close time of the third loss;
- the rule never closes or changes existing positions;
- when the pause has elapsed, opening stays blocked until a fresh risk re-check is recorded
(`confirm_recheck`);
- every pause is recorded with its start, end and the three trade ids, and a notification is queued
in the state
  (`outbox`) for a later, separately approved delivery channel; nothing is sent from here.

State is a JSON file written atomically (temp file + rename), so a restart continues the same
streak; trade ids
already counted are ignored, so replaying the same closes after a restart never double-counts.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass

DAY_MS = 86_400_000


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    closed_ms: int
    realised_net: float  # after fees and funding, in account currency


def _empty() -> dict:
    return {
        "version": 1,
        "streak": [],
        "seen": [],
        "last_close_ms": None,
        "pause": None,
        "pauses": [],
        "outbox": [],
    }


class LossStreakGuard:
    def __init__(self, path: str, streak_limit: int = 3, pause_ms: int = DAY_MS):
        if streak_limit < 1 or pause_ms <= 0:
            raise ValueError("streak_limit must be >= 1 and pause_ms > 0")
        self.path, self.limit, self.pause_ms = path, streak_limit, pause_ms
        self.state = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return _empty()
        with open(self.path, encoding="utf-8") as f:
            st = json.load(
                f
            )  # a corrupt file raises: the caller must decide, a silent reset would hide a streak
        if st.get("version") != 1:
            raise ValueError("unknown loss-streak state version")
        return st

    def _save(self) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".loss_streak.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def record_close(self, t: ClosedTrade) -> bool:
        """Register a closed trade. Returns True if this close started a pause. Duplicates are
        ignored.
        """
        st = self.state
        if t.trade_id in st["seen"]:
            return False
        if st["last_close_ms"] is not None and t.closed_ms < st["last_close_ms"]:
            raise ValueError("closes must be recorded in time order")
        st["seen"].append(t.trade_id)
        st["last_close_ms"] = t.closed_ms
        started = False
        if t.realised_net < 0:
            st["streak"].append(t.trade_id)
            if len(st["streak"]) >= self.limit and st["pause"] is None:
                pause = {
                    "start_ms": t.closed_ms,
                    "end_ms": t.closed_ms + self.pause_ms,
                    "trades": list(st["streak"]),
                    "recheck_ms": None,
                    "recheck_note": None,
                }
                st["pause"] = pause
                st["pauses"].append(dict(pause))
                st["outbox"].append(
                    {
                        "kind": "loss_streak_pause",
                        "created_ms": t.closed_ms,
                        "pause_end_ms": pause["end_ms"],
                        "trades": list(st["streak"]),
                        "delivered": False,
                    }
                )
                started = True
        else:
            st["streak"] = []
        self._save()
        return started

    def allows_open(self, now_ms: int) -> tuple[bool, str | None]:
        p = self.state["pause"]
        if p is None:
            return True, None
        if now_ms < p["end_ms"]:
            return False, "loss-streak pause active"
        return False, "loss-streak pause ended: risk re-check pending"

    def confirm_recheck(self, now_ms: int, note: str) -> None:
        """Record the post-pause risk re-check; only allowed after the pause end. Clears the pause
        and the streak.
        """
        p = self.state["pause"]
        if p is None:
            raise ValueError("no pause to re-check")
        if now_ms < p["end_ms"]:
            raise ValueError("the pause has not ended yet")
        if not note.strip():
            raise ValueError("a re-check note is required")
        self.state["pauses"][-1].update(recheck_ms=now_ms, recheck_note=note)
        self.state["pause"] = None
        self.state["streak"] = []
        self._save()

    def pending_notifications(self) -> list[dict]:
        return [n for n in self.state["outbox"] if not n["delivered"]]
