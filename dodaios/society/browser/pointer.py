"""Read-only visualization of the agent's mouse commands to Chrome.

A click is shown as the arrow travelling to the button and then pressing.
So that the page reacts when the arrow arrives, not before, a move to a new
point is announced first and sent after the glide the viewer draws for it.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

log = logging.getLogger(__name__)

#: Moves this close to where the arrow already is need no glide.
_STILL_PX = 3.0
#: A frame reaches the viewer this much after the page changed; the press may
#: go out that much before the arrow lands and still be seen after it.
_FRAME_LEAD_S = 0.06


def glide_seconds(distance_px: float) -> float:
    """How long the viewer's arrow travels; keep in step with ``glideDurationMs``
    in ``frontend/src/components/society/card/agentCursorMotion.ts``."""
    if not math.isfinite(distance_px) or distance_px < 1:
        return 0.0
    return min(0.65, max(0.28, 0.24 + distance_px * 0.0003))


class PointerTracker:
    def __init__(
        self, generation: str, emit: Any, enabled: Any, project: Any, *, sleep: Any = None
    ) -> None:
        self.generation = generation
        self.emit = emit
        self.enabled = enabled
        self.project = project
        self.sleep = sleep or asyncio.sleep
        self.click_id = 0
        self.click = (0.0, 0.0)
        self.shown: tuple[float, float] | None = None

    async def _aim(self, params: dict) -> None:
        """Show the arrow travelling to the next point and wait until it lands."""
        try:
            x, y = float(params["x"]), float(params["y"])
            if not math.isfinite(x) or not math.isfinite(y):
                return
            x, y, width, height = self.project(x, y)
        except Exception:
            log.debug("Browser pointer aim unavailable", exc_info=True)
            return
        previous = self.shown
        if previous is None:
            return  # The arrow appears where the first event lands; nothing to travel.
        distance = math.hypot(x - previous[0], y - previous[1])
        if distance <= _STILL_PX:
            return
        self.shown = (x, y)
        self.emit(
            "pointer",
            visible=True,
            generation=self.generation,
            x=x,
            y=y,
            width=width,
            height=height,
            click_id=self.click_id,
            click_x=self.click[0],
            click_y=self.click[1],
        )
        await self.sleep(max(0.0, glide_seconds(distance) - _FRAME_LEAD_S))

    def wrap(self, send: Any) -> Any:
        async def observed(method: str, params: Any = None, session_id: str | None = None) -> Any:
            if (
                method == "Input.dispatchMouseEvent"
                and isinstance(params, dict)
                and params.get("type") in {"mouseMoved", "mousePressed"}
                and self.enabled()
            ):
                await self._aim(params)
            result = await send(method=method, params=params, session_id=session_id)
            if self.enabled() and method == "Input.dispatchMouseEvent" and isinstance(params, dict):
                try:
                    kind = params.get("type")
                    if kind not in {"mouseMoved", "mousePressed", "mouseWheel"}:
                        return result
                    x, y = float(params["x"]), float(params["y"])
                    if not math.isfinite(x) or not math.isfinite(y):
                        return result
                    x, y, width, height = self.project(x, y)
                    if kind == "mousePressed":
                        self.click_id += 1
                        self.click = (x, y)
                    self.shown = (x, y)
                    self.emit(
                        "pointer",
                        visible=True,
                        generation=self.generation,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        click_id=self.click_id,
                        click_x=self.click[0],
                        click_y=self.click[1],
                    )
                except Exception:
                    # Visualization must never turn a successful browser action into failure.
                    log.debug("Browser pointer visualization unavailable", exc_info=True)
            return result

        return observed

    def clear(self) -> None:
        self.click_id = 0
        self.click = (0.0, 0.0)
        self.shown = None
        self.emit("pointer", visible=False, generation=self.generation)

    def window(self, x: float, y: float, width: int, height: int, *, clicked: bool) -> None:
        """Visualize an approved native input only after its dispatch succeeds."""
        if not self.enabled():
            return
        if clicked:
            self.click_id += 1
            self.click = (x, y)
        self.shown = (x, y)
        self.emit(
            "pointer",
            visible=True,
            native_window=True,
            generation=self.generation,
            x=x,
            y=y,
            width=width,
            height=height,
            click_id=self.click_id,
            click_x=self.click[0],
            click_y=self.click[1],
        )
