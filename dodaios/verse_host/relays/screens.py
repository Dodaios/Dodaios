"""Screens relay (BW4, contract 5): styled desk-monitor cells of watched panes.

Verse names the desks it wants with ``screens.watch`` (nearest first, at most
8). Each bound pane gets a :class:`StyledScreen` mirror fed from its PTY as a
non-claiming viewer (seeded from the replay bytes). Dirty rows go out at
most ``min(hz, 10)`` times a second, coalesced; the whole screens feed stays
under 200 KB/s by skipping the farthest panes first. A pane without output
sends nothing. When the mirror is not available (attach refused, parser
error) the plain ``ScreenBuffer`` rows go out with ``style: "plain"``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .. import protocol as P
from ..cells_codec import DEFAULT_COLOUR, MAX_COLS, MAX_ROWS, Cell, row_runs
from ..ports import NotFound
from ..styled_screen import StyledScreen
from .base import RelayBase

log = logging.getLogger(__name__)

SAFETY_SNAPSHOT_S = 30.0
TICK_S = 0.05
PLAIN_POLL_S = 0.5


@dataclass
class Watched:
    pane_id: str
    ref: int
    hz: int
    mirror: StyledScreen | None = None
    style: str = "styled"
    at: float | None = None
    last_frame: float = 0.0
    last_snapshot: float = 0.0
    need_snapshot: bool = True
    plain_rows: list[list[Cell]] = field(default_factory=list)
    plain_cols: int = 0
    plain_rows_n: int = 0
    plain_cursor: list[int] = field(default_factory=lambda: [-1, -1])
    plain_dirty: set[int] = field(default_factory=set)
    last_plain_poll: float = 0.0
    output_handler: Any = None
    gone: bool = False


class ScreensRelay(RelayBase):
    topics = ("screens",)

    def __init__(self, session: Any, backend: Any) -> None:
        super().__init__(session, backend)
        self.watched: dict[str, Watched] = {}
        self.budget_bytes_per_s = P.SCREENS_MAX_BYTES_PER_S
        self._window: list[tuple[float, int]] = []
        self.clock = time.monotonic
        self.feed_seconds: list[float] = []
        self.frame_seconds: list[float] = []

    async def start(self) -> None:
        from dodaios.core import events as E

        self.session.hub.command("screens.watch", self._watch)
        self.listen([E.AgenticIdeTerminalsClosed], self._on_closed)
        self.spawn(self._pump())

    async def stop(self) -> None:
        for w in list(self.watched.values()):
            self._unbind(w)
        self.watched.clear()
        await super().stop()

    async def resync(self, topic: str, data: dict[str, Any]) -> None:
        pane_id = data.get("pane_id")
        for w in self.watched.values():
            if pane_id is None or w.pane_id == pane_id:
                w.need_snapshot = True

    # ------------------------------------------------------------------ watch
    async def _watch(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        panes = msg.data.get("panes")
        if not isinstance(panes, list):
            raise P.BridgeError("bad_request", "panes must be a list.")
        wanted: list[tuple[str, int]] = []
        for item in panes:
            if not isinstance(item, dict) or not isinstance(item.get("pane_id"), str):
                raise P.BridgeError("bad_request", "every pane needs a pane_id.")
            hz = item.get("hz", 10)
            if isinstance(hz, bool) or not isinstance(hz, int) or not 1 <= hz <= 10:
                raise P.BridgeError("bad_request", "hz must be 1 to 10.")
            if item["pane_id"] not in (p for p, _ in wanted):
                wanted.append((item["pane_id"], hz))
        limit = P.LIMITS["screens_max_panes"]
        served, dropped = wanted[:limit], [p for p, _ in wanted[limit:]]
        keep = {p for p, _ in served}
        for pane_id in list(self.watched):
            if pane_id not in keep:
                self._unbind(self.watched.pop(pane_id))
        bound, missing = [], []
        ref = 0
        new: dict[str, Watched] = {}
        for pane_id, hz in served:
            w = self.watched.get(pane_id)
            if w is None:
                w = await self._bind(pane_id, hz)
                if w is None:
                    missing.append(pane_id)
                    continue
            ref += 1
            w.ref, w.hz, w.need_snapshot = ref, hz, True
            new[pane_id] = w
            bound.append({"pane_id": pane_id, "ref": ref})
        self.watched = new
        return {"bound": bound, "dropped": dropped, "missing": missing}

    async def _bind(self, pane_id: str, hz: int) -> Watched | None:
        w = Watched(pane_id=pane_id, ref=0, hz=hz)

        async def on_output(text: str) -> None:
            if w.mirror is None or w.gone:
                return
            started = time.perf_counter()
            w.mirror.feed(text)
            self.feed_seconds.append(time.perf_counter() - started)
            if len(self.feed_seconds) > 4096:
                del self.feed_seconds[:2048]
            w.at = time.time()
            if w.mirror.errors:
                self._to_plain(w)

        async def on_exit(_code: int) -> None:
            self._gone(w, "exited")

        w.output_handler = on_output
        w.mirror = StyledScreen(80, 24)
        try:
            size = await self.backend.attach_screen(pane_id, on_output, on_exit)
        except NotFound:
            size = None
            w.mirror = None
            if self.backend.plain_screen(pane_id) is None:
                return None
            w.style = "plain"
            return w
        except Exception:  # noqa: BLE001 - a mirror that cannot start falls back to plain
            log.warning("verse screens: attach failed for %s", pane_id, exc_info=True)
            w.mirror = None
            w.style = "plain"
            if self.backend.plain_screen(pane_id) is None:
                return None
            return w
        if size and w.mirror is not None:
            w.mirror.resize(*size)
        return w

    def _unbind(self, w: Watched) -> None:
        w.gone = True
        if w.output_handler is not None and w.style == "styled":
            self.backend.detach_screen(w.pane_id, w.output_handler)
        self.session.outbox.clear_topic(f"screens:{w.pane_id}")

    def _to_plain(self, w: Watched) -> None:
        if w.style == "plain":
            return
        log.info("verse screens: %s falls back to plain rows", w.pane_id)
        if w.output_handler is not None:
            self.backend.detach_screen(w.pane_id, w.output_handler)
        w.mirror = None
        w.style = "plain"
        w.need_snapshot = True

    def _gone(self, w: Watched, reason: str) -> None:
        if w.gone:
            return
        current = self.watched.get(w.pane_id)
        self._unbind(w)
        if current is w:
            del self.watched[w.pane_id]
        self.session.send("screens.gone", {"pane_id": w.pane_id, "reason": reason})

    async def _on_closed(self, event: Any) -> None:
        workspace = getattr(event, "session_id", "") or getattr(event, "workspace_id", "")
        names = set(getattr(event, "keys", ()) or ()) | set(getattr(event, "names", ()) or ())
        for w in list(self.watched.values()):
            ws, _, key = w.pane_id.partition(":")
            if ws == workspace and (not names or key in names):
                self._gone(w, "closed")

    # ------------------------------------------------------------------ pump
    def _spent(self, now: float) -> int:
        self._window = [(t, n) for t, n in self._window if now - t < 1.0]
        return sum(n for _, n in self._window)

    async def _pump(self) -> None:
        while not self.stopped:
            await asyncio.sleep(TICK_S)
            try:
                await self.flush(self.clock())
            except Exception:  # noqa: BLE001
                log.warning("verse screens: flush failed", exc_info=True)

    async def flush(self, now: float) -> None:
        """One tick: nearest panes first, each at most at its rate, under the byte budget.

        The loop yields after every pane it framed, so building eight busy
        screens never holds the event loop in one piece.
        """
        for w in list(self.watched.values()):
            if w.gone:
                continue
            if w.style == "plain" and now - w.last_plain_poll >= max(PLAIN_POLL_S, 1.0 / w.hz):
                w.last_plain_poll = now
                self._poll_plain(w)
            if now - w.last_snapshot >= SAFETY_SNAPSHOT_S:
                w.need_snapshot = True
            if w.mirror is not None and w.mirror.resized:
                w.mirror.resized = False
                w.need_snapshot = True
            due = now - w.last_frame >= 1.0 / min(w.hz, P.LIMITS["screens_max_hz"])
            if not due:
                continue
            if not w.need_snapshot and not self._has_dirty(w):
                continue
            started = time.perf_counter()
            data = self._frame(w)
            size = self._estimate(data)
            self.frame_seconds.append(time.perf_counter() - started)
            if len(self.frame_seconds) > 4096:
                del self.frame_seconds[:2048]
            if self._spent(now) + size > self.budget_bytes_per_s and not w.need_snapshot:
                # Over budget: this and every farther pane wait for the next tick.
                continue
            self._window.append((now, size))
            w.last_frame = now
            snapshot = data["kind"] == "snapshot"
            if snapshot:
                w.last_snapshot = now
                w.need_snapshot = False
            self.session.send(
                "screens.frame",
                data,
                topic=f"screens:{w.pane_id}",
                key=f"screens:{w.pane_id}",
                delta=not snapshot,
                ref=w.ref,
                feed=True,
            )
            await asyncio.sleep(0)

    @staticmethod
    def _estimate(data: dict[str, Any]) -> int:
        size = 32
        for record in data["rows_changed"]:
            size += 4
            for run in record["runs"]:
                size += 16 + len(run["text"].encode("utf-8"))
        return size

    def _has_dirty(self, w: Watched) -> bool:
        if w.mirror is not None:
            return bool(w.mirror.dirty)
        return bool(w.plain_dirty)

    def _frame(self, w: Watched) -> dict[str, Any]:
        snapshot = w.need_snapshot
        if w.mirror is not None:
            m = w.mirror
            rows = m.snapshot_rows() if snapshot else m.take_dirty()
            if snapshot:
                m.dirty = set()
            cols, nrows, cursor, cut = m.sent_cols, m.sent_rows, m.cursor(), m.cut
        else:
            cols, nrows = max(1, w.plain_cols), max(1, w.plain_rows_n)
            indices = range(nrows) if snapshot else sorted(w.plain_dirty)
            w.plain_dirty = set()
            rows = []
            for r in indices:
                runs = row_runs(w.plain_rows[r], cols) if r < len(w.plain_rows) else []
                if runs or not snapshot:
                    rows.append({"row": r, "runs": runs})
            cursor, cut = w.plain_cursor, False
        data: dict[str, Any] = {
            "pane_id": w.pane_id,
            "kind": "snapshot" if snapshot else "delta",
            "cols": cols,
            "rows": nrows,
            "cursor": cursor,
            "style": w.style,
            "rows_changed": rows,
        }
        if snapshot:
            data.update({"ref": w.ref, "cut": cut, "at": w.at})
        return data

    def _poll_plain(self, w: Watched) -> None:
        shot = self.backend.plain_screen(w.pane_id)
        if shot is None:
            self._gone(w, "not_found")
            return
        cols = max(1, min(int(shot.get("cols") or 80), MAX_COLS))
        nrows = max(1, min(int(shot.get("rows") or 24), MAX_ROWS))
        lines = [str(line)[:cols] for line in shot.get("lines", [])][:nrows]
        grid: list[list[Cell]] = [
            [(ch, DEFAULT_COLOUR, DEFAULT_COLOUR, 0) for ch in line] for line in lines
        ]
        while len(grid) < nrows:
            grid.append([])
        if (cols, nrows) != (w.plain_cols, w.plain_rows_n):
            w.need_snapshot = True
        for r in range(nrows):
            old = w.plain_rows[r] if r < len(w.plain_rows) else []
            if old != grid[r]:
                w.plain_dirty.add(r)
        cursor = shot.get("cursor")
        w.plain_cursor = (
            [int(cursor[0]), int(cursor[1])]
            if isinstance(cursor, list | tuple) and len(cursor) == 2
            else [-1, -1]
        )
        w.plain_rows, w.plain_cols, w.plain_rows_n = grid, cols, nrows
        at = shot.get("at")
        w.at = float(at) if isinstance(at, int | float) else w.at

    # ------------------------------------------------------------------ metrics
    def feed_p99_ms(self) -> float:
        return self._p99(self.feed_seconds)

    def frame_p99_ms(self) -> float:
        return self._p99(self.frame_seconds)

    @staticmethod
    def _p99(samples: list[float]) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))] * 1000.0
