"""The coding-agent launch sequence, shared by every launcher (contract 11, 14).

The web Verse's launcher panel ran this in the browser: open a terminal,
start it, wait for it to come up, hand it the brief. The Unreal Verse's
``launcher.start`` needs the same sequence, so it lives here and both
callers share it. One batch runs at a time across every caller (single
flight: a second start answers busy); ``cancel`` stops starting further
panes, panes already open stay.

The steps are injected (``LaunchSteps``) so the sequence is testable without
a PTY; ``dodaios.verse_host.ports.AppBackend`` supplies the live ones.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

START_TIMEOUT_S = 30.0
START_POLL_S = 0.6
MAX_PER_BATCH = 8


class LaunchBusy(RuntimeError):
    """Another batch is running."""


class LaunchSteps(Protocol):
    async def open_terminal(self, workspace_id: str | None, agent: str) -> tuple[str, str]: ...
    async def start_terminal(self, name: str, workspace_id: str) -> None: ...
    async def list_panes(self) -> list[dict[str, Any]]: ...
    async def prompt_terminal(self, name: str, text: str, workspace_id: str) -> bool | None: ...


@dataclass
class LaunchedPane:
    workspace_id: str
    name: str
    submitted: bool | None = None

    @property
    def pane_id(self) -> str:
        return f"{self.workspace_id}:{self.name}"


@dataclass
class Batch:
    cancelled: bool = False
    remaining: int = 0
    opened: list[LaunchedPane] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)


class LaunchSequence:
    """Single-flight batch launcher."""

    def __init__(
        self,
        steps: LaunchSteps,
        *,
        start_timeout_s: float = START_TIMEOUT_S,
        poll_s: float = START_POLL_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.steps = steps
        self.start_timeout_s = start_timeout_s
        self.poll_s = poll_s
        self._sleep = sleep
        self.running: Batch | None = None

    @property
    def busy(self) -> bool:
        return self.running is not None

    def cancel(self) -> int:
        """Stop the running batch; returns how many panes it will not start."""
        batch = self.running
        if batch is None:
            return 0
        batch.cancelled = True
        return batch.remaining

    async def _wait_live(self, workspace_id: str, name: str, batch: Batch) -> bool:
        deadline = time.monotonic() + self.start_timeout_s
        while time.monotonic() < deadline and not batch.cancelled:
            try:
                for row in await self.steps.list_panes():
                    if row.get("workspace_id") == workspace_id and name in (
                        row.get("name"),
                        row.get("key"),
                    ):
                        status = row.get("status")
                        if status == "live":
                            return True
                        if status != "pending":
                            return False
            except Exception:  # noqa: BLE001 - a failed poll is retried
                log.warning("launch sequence: pane poll failed", exc_info=True)
            await self._sleep(self.poll_s + random.random() * 0.3)  # noqa: S311
        return False

    async def run(
        self, workspace_id: str | None, agents: list[tuple[str, int]], brief: str
    ) -> list[LaunchedPane]:
        """Open ``count`` panes per agent; brief each once it is live. Raises LaunchBusy."""
        if self.running is not None:
            raise LaunchBusy("A launch batch is already running.")
        batch = Batch()
        plan = [agent for agent, count in agents for _ in range(max(0, count))][:MAX_PER_BATCH]
        batch.remaining = len(plan)
        self.running = batch
        brief = brief.strip()
        try:
            for agent in plan:
                if batch.cancelled:
                    break
                ws, name = await self.steps.open_terminal(workspace_id, agent)
                batch.remaining -= 1
                pane = LaunchedPane(ws, name)
                batch.opened.append(pane)
                if not brief or batch.cancelled:
                    continue
                try:
                    await self.steps.start_terminal(name, ws)
                except Exception:  # noqa: BLE001 - the pane may start on its own
                    log.warning("launch sequence: start of %s failed", name, exc_info=True)
                if await self._wait_live(ws, name, batch) and not batch.cancelled:
                    pane.submitted = await self.steps.prompt_terminal(name, brief, ws)
        finally:
            self.running = None
        return batch.opened


_shared: LaunchSequence | None = None


def shared_sequence(steps: LaunchSteps) -> LaunchSequence:
    """The process-wide sequence, so every caller shares one single flight."""
    global _shared
    if _shared is None or _shared.steps is not steps:
        if _shared is not None and _shared.busy:
            return _shared
        _shared = LaunchSequence(steps)
    return _shared
