"""The code builder's pass: watch open pull requests, take in issues, build one case.

One pass every :data:`TICK_S` (and soon after a proposal is accepted):

1. Nothing at all while ``[self_build].code`` is ``off``, the kill switch is
   on, or GitHub is not connected: no call leaves the machine.
2. Watch the loop's open pull requests (CI, merges, closes; ``watch``).
3. Refresh the briefs of the person's own projects and triage their issues
   (``intake``). Proposals cost no model call.
4. Build at most one ``building`` case, and only while the person is away and
   a subscription coding CLI is free (``seat``, ``idle``). A case can wait for
   that up to :data:`STALE_BUILDING_MS`; then it fails with that reason.

A pass makes git calls and GitHub reads; the only model calls are the one
plan call and the coding run of a build.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Final

from loguru import logger

from .. import policy
from ..ledger import now_ms
from ..records import BuildRecord, Kind, State
from . import builder, intake, planner, seat
from .context import Context
from .github import GitHub, GitHubApi
from .idle import person_idle
from .runner import ThreadRunner
from .store import DB_NAME, CodeStore
from .watch import cleanup, watch

TICK_S: Final[float] = 300.0
FIRST_TICK_S: Final[float] = 120.0
#: A case that found no idle subscription time for this long fails.
STALE_BUILDING_MS: Final[int] = 3 * 86_400_000
#: Archived builds' pull requests are still watched this long (a late merge).
WATCH_ARCHIVED_MS: Final[int] = 30 * 86_400_000
_GITHUB_TTL_S: Final[float] = 600.0


class CodeLoop:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self._task: asyncio.Task[None] | None = None
        self._building: asyncio.Task[None] | None = None
        self._building_id = ""
        self._wake: asyncio.Event | None = None

    # ------------------------------------------------------------ wiring

    def attach(self) -> None:
        service = self.ctx.service
        service.undo.register(Kind.CODE, self.undo)
        service.register_builder(Kind.CODE, self.on_accepted)

    def start(self) -> None:
        if self._task is not None:
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self._run())
        except RuntimeError:  # no loop (CLI, tests): tick() can still be called
            self._task = None

    async def close(self) -> None:
        for task in (self._task, self._building):
            if task is not None and not task.done():
                task.cancel()
        self._task = None

    def kick(self) -> None:
        if self._wake is not None:
            self._wake.set()

    async def _run(self) -> None:
        self._wake = asyncio.Event()
        await asyncio.sleep(FIRST_TICK_S)
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the next pass retries
                logger.opt(exception=True).warning("self-build code: pass failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=TICK_S)
            except TimeoutError:  # the normal end of the wait: time for the next pass
                pass

    # ------------------------------------------------------------ the ledger's hooks

    async def on_accepted(self, record: BuildRecord) -> None:
        """A proposal was accepted: it is ``building`` now and waits for idle time."""
        logger.info("self-build code: {} accepted, waiting for idle time", record.signature)
        self.kick()

    async def undo(self, record: BuildRecord) -> None:
        """Close the loop's pull request and delete its branch and worktree."""
        if self._building_id == record.id and self._building and not self._building.done():
            self._building.cancel()
            try:
                await self._building
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - it is being undone
                logger.debug("self-build code: build {} stopped for undo", record.id)
        current = await asyncio.to_thread(self.ctx.ledger.get, record.id) or record
        await cleanup(self.ctx, current, close_pull=True)

    # ------------------------------------------------------------ one pass

    async def tick(self) -> dict[str, Any]:
        ctx = self.ctx
        cfg = ctx.config()
        if policy.autonomy(cfg, Kind.CODE) == policy.Autonomy.OFF:
            return {"skipped": "off"}
        if policy.paused(ctx.ledger):
            return {"skipped": "paused"}
        if ctx.github() is None:
            return {"skipped": "github not connected"}
        summary: dict[str, Any] = {"watched": await self._watch()}
        who = await intake.viewer(ctx)
        if who is None:
            summary["skipped"] = "github account unknown"
            return summary
        projects = await asyncio.to_thread(intake.owned_projects, ctx, who)
        summary["projects"] = [p.repo for p in projects]
        summary["opened"] = await intake.intake(ctx, projects, who)
        summary["build"] = await self._maybe_build()
        return summary

    async def _watch(self) -> int:
        ctx = self.ctx
        records = await asyncio.to_thread(
            ctx.ledger.list,
            kinds=[Kind.CODE],
            states=[State.PROVING, State.TRIAL, State.ARCHIVED],
            limit=100,
        )
        cutoff = now_ms() - WATCH_ARCHIVED_MS
        seen = 0
        for record in records:
            if record.state == State.ARCHIVED and record.updated_ms < cutoff:
                continue
            try:
                await watch(ctx, record)
                seen += 1
            except Exception:  # noqa: BLE001 - one unreadable pull request must not stop the rest
                logger.opt(exception=True).info("self-build code: watch {} failed", record.id)
        return seen

    async def _maybe_build(self) -> str:
        ctx = self.ctx
        if self._building is not None and not self._building.done():
            return "running"
        waiting = await asyncio.to_thread(
            ctx.ledger.list, kinds=[Kind.CODE], states=[State.BUILDING], limit=20
        )
        if not waiting:
            return "nothing to build"
        record = min(waiting, key=lambda r: r.created_ms)
        stage = str(record.artefact.get("stage") or "")
        if stage == "coding":
            return await self._resume(record)
        if stage:
            # The app stopped between steps: start this case over from nothing.
            await cleanup(ctx, record, close_pull=True)
            record = await asyncio.to_thread(ctx.ledger.attach_artefact, record.id, {}, {})
        if now_ms() - record.updated_ms > STALE_BUILDING_MS:
            await asyncio.to_thread(
                ctx.ledger.set_state,
                record.id,
                State.FAILED,
                "no idle time on a subscription coding CLI for three days",
            )
            return "stale"
        if not await asyncio.to_thread(ctx.idle):
            return "waiting: the person is at the computer"
        chosen, why = await ctx.seat()
        if chosen is None:
            return f"waiting: {why}"
        self._start(record, builder.build(ctx, record, provider=chosen.provider))
        return f"building {record.signature} on {chosen.label}"

    async def _resume(self, record: BuildRecord) -> str:
        session_id = str(record.undo.get("session_id") or "")
        result = await self.ctx.runner.outcome(session_id) if session_id else None
        if session_id and result is None:
            return "coding run still working"
        self._start(record, builder.resume(self.ctx, record, result))
        return f"resuming {record.signature}"

    def _start(self, record: BuildRecord, coro: Any) -> None:
        self._building_id = record.id
        self._building = asyncio.ensure_future(coro)


# ------------------------------------------------------------------ install


def _projects() -> list[Any]:
    from dodaios.agentic_ide import library

    return list(library.list_projects())


async def _seat() -> tuple[seat.Seat | None, str]:
    installed = await seat.installed_clis()
    return await asyncio.to_thread(seat.choose, installed)


def _cached_github() -> Any:
    """``GitHubApi.connect`` reused for minutes (it may ask ``gh`` for a token)."""
    cache: dict[str, Any] = {"at": 0.0, "api": None}

    def get() -> GitHub | None:
        if time.monotonic() - cache["at"] > _GITHUB_TTL_S:
            cache["api"] = GitHubApi.connect()
            cache["at"] = time.monotonic()
        return cache["api"]

    return get


def _chat_from(state: Any) -> Any:
    """The agent-chat service on ``app.state``, built on first use like its routes do."""

    def get() -> Any:
        service = getattr(state, "agent_chat", None)
        if service is not None:
            return service
        factory = getattr(state, "agent_chat_factory", None)
        if factory is None:
            raise RuntimeError("this app has no agent chat service")
        service = factory()
        state.agent_chat = service
        return service

    return get


def install(service: Any, app_state: Any = None) -> CodeLoop:
    """Register the code builder with the self-building service and start its pass."""
    import dodaios

    store = CodeStore(Path(service.ledger.path).parent / DB_NAME)
    ctx = Context(
        service=service,
        store=store,
        github=_cached_github(),
        runner=ThreadRunner(_chat_from(app_state) if app_state is not None else None),
        seat=_seat,
        idle=person_idle,
        projects=_projects,
        plan=planner.plan,
        dodaios_root=Path(dodaios.__file__).resolve().parent.parent,
    )
    loop = CodeLoop(ctx)
    loop.attach()
    loop.start()
    return loop
