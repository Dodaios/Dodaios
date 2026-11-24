"""The self-building loop's one entry point inside the running app.

Built once at boot (:func:`start`), cheap: it opens ``self_build.db`` and
nothing else. Observers and builders reach it through :func:`current`; the
REST routes through ``app.state.self_build``.

Builders plug in per kind:

* ``register_builder(kind, fn)``: the kind can be built here; the status lists
  it. The loop that admits a build hands it to its builder itself.
* ``undo.register(kind, fn)``: removes what the builder created.

The person is never asked to approve a build or to keep one: a build goes
live on trial when it can be undone, and :meth:`SelfBuild.sweep` keeps or
archives a finished trial from its use. What the person has is the kill
switch (:meth:`SelfBuild.set_paused`) and undo (:meth:`SelfBuild.undo_build`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from . import policy
from .ledger import DB_NAME, BuildLedger, now_ms
from .records import LIVE_STATES, BuildRecord, Kind, State, TransitionError
from .undo import UndoRegistry

log = logging.getLogger(__name__)

Builder = Callable[[BuildRecord], Awaitable[None]]
Publish = Callable[[Any], Awaitable[None]]

_current: SelfBuild | None = None

#: The note an old proposal is archived with (:meth:`SelfBuild.retire_proposals`).
RETIRED_NOTE: Final[str] = (
    "archived: no longer asked. The loop builds what it can undo and measure on its own"
)


class SelfBuild:
    def __init__(
        self,
        data_dir: Path,
        config: Callable[[], Any],
        *,
        publish: Publish | None = None,
    ) -> None:
        self._config = config
        self._publish = publish
        self._loop: asyncio.AbstractEventLoop | None = None
        self._builders: dict[Kind, Builder] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._sweeper: asyncio.Task[None] | None = None
        self.undo = UndoRegistry()
        #: The code builder's pass (``code/loop.py``), once installed.
        self.code_loop: Any = None
        self.ledger = BuildLedger(Path(data_dir) / DB_NAME, on_change=self._changed)

    # ------------------------------------------------------------ wiring

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def config(self) -> Any:
        return self._config()

    def register_builder(self, kind: Kind, builder: Builder) -> None:
        self._builders[Kind(kind)] = builder

    def can_build(self, kind: Kind) -> bool:
        return Kind(kind) in self._builders

    # ------------------------------------------------------------ the gate

    def admit(self, kind: Kind, signature: str) -> policy.Admission:
        return policy.admit(
            self.ledger, self.config(), kind, signature, undoable=self.undo.has(kind)
        )

    def status(self) -> dict[str, Any]:
        """What the loop may do right now, as it really is.

        ``autonomy`` is the fixed level per kind (``full``: built on trial and
        kept or archived by use; ``watch``: nothing new is opened, open work is
        watched to its end). ``builders`` are the kinds something here can build.
        """
        cfg = self.config()
        return {
            "paused": policy.paused(self.ledger),
            "silent": policy.silent(self.ledger, cfg),
            "autonomy": {kind.value: policy.autonomy(kind).value for kind in Kind},
            "builders": sorted(kind.value for kind in self._builders),
            "code": self.code_loop.state() if self.code_loop is not None else {},
        }

    # ------------------------------------------------------------ person's actions

    async def undo_build(self, build_id: str, note: str = "") -> BuildRecord:
        return await self.undo.undo(self.ledger, build_id, note)

    def set_paused(self, value: bool) -> None:
        policy.set_paused(self.ledger, value)

    # ------------------------------------------------------------ proposals of old

    def retire_proposals(self) -> list[BuildRecord]:
        """Archive every case an older version left waiting for the person's OK.

        Called once, when the service starts (:func:`start`). Nothing opens as a
        proposal any more, so a later start finds none. The record stays
        (archived, never deleted), and the need can come back as a build on
        trial. Blocking (SQLite).
        """
        retired: list[BuildRecord] = []
        for record in self.ledger.list(states=[State.PROPOSED], limit=500):
            try:
                retired.append(self.ledger.set_state(record.id, State.ARCHIVED, RETIRED_NOTE))
            except (KeyError, TransitionError):  # moved meanwhile: nothing left to retire
                continue
        if retired:
            log.info("self_build: archived %d proposal(s) that waited for an OK", len(retired))
        return retired

    # ------------------------------------------------------------ trials

    async def sweep(self) -> list[BuildRecord]:
        """Settle trials that are over, for every kind, from their use alone: a
        used trial is kept, an unused one archived (restorable, never deleted)."""
        if policy.paused(self.ledger):
            return []
        cfg = self.config()
        settled: list[BuildRecord] = []
        trials = await asyncio.to_thread(self.ledger.list, states=[State.TRIAL], limit=500)
        for record in trials:
            if not policy.trial_over(record, cfg):
                continue
            verdict = policy.settle(record)
            note = (
                "kept: used and accepted"
                if verdict == State.KEPT
                else "archived: not used enough"
            )
            settled.append(
                await asyncio.to_thread(self.ledger.set_state, record.id, verdict, note)
            )
        return settled

    def start_sweeper(self, interval_s: float = 3_600.0) -> None:
        """Settle finished trials once an hour; no model is ever asked."""
        if self._sweeper is not None:
            return

        async def loop() -> None:
            while True:
                await asyncio.sleep(interval_s)
                try:
                    await self.sweep()
                except Exception:  # noqa: BLE001 — the next pass retries
                    log.warning("self_build: sweep failed", exc_info=True)

        try:
            self._sweeper = asyncio.get_running_loop().create_task(loop())
        except RuntimeError:  # no loop yet (tests, CLI): sweep() can still be called
            self._sweeper = None

    def digest(self, since_ms: int) -> dict[str, Any]:
        """What happened since ``since_ms``, for the daily card."""
        rows = [r for r in self.ledger.list(limit=500) if r.updated_ms >= since_ms]
        by_state: dict[str, int] = {}
        for record in rows:
            by_state[record.state.value] = by_state.get(record.state.value, 0) + 1
        return {
            "since_ms": since_ms,
            "until_ms": now_ms(),
            "counts": by_state,
            "live": sum(1 for r in self.ledger.list(states=LIVE_STATES, limit=500)),
            "items": [r.to_json() for r in rows[:20]],
        }

    def provenance(self, artefact_type: str | None = None) -> dict[str, dict[str, Any]]:
        """Which artefacts a build created, keyed by ``"<type>:<id>"``.

        The "built by Dodaios" badge on agents, skills and routines joins on
        this. Only builds whose artefact still exists count: on trial, kept or
        archived (archived artefacts are kept, so the badge still links back).
        """
        wanted = (artefact_type or "").strip().lower()
        out: dict[str, dict[str, Any]] = {}
        rows = self.ledger.list(states=LIVE_STATES | {State.ARCHIVED}, limit=500)
        for record in rows:
            kind = str(record.artefact.get("type") or "").strip().lower()
            ident = str(record.artefact.get("id") or "").strip()
            if not kind or not ident or (wanted and kind != wanted):
                continue
            # Newest change first: the first row for an id is the current one.
            out.setdefault(
                f"{kind}:{ident}",
                {
                    "build_id": record.id,
                    "type": kind,
                    "id": ident,
                    "state": record.state.value,
                    "title": record.title,
                },
            )
        return out

    # ------------------------------------------------------------ plumbing

    def spawn(self, coro: Awaitable[None], label: str) -> None:
        async def run() -> None:
            try:
                await coro
            except Exception:  # noqa: BLE001 — one failed build must not stop the loop
                log.warning("self_build: %s failed", label, exc_info=True)

        task = asyncio.ensure_future(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _changed(self, record: BuildRecord) -> None:
        publish, loop = self._publish, self._loop
        if publish is None or loop is None or loop.is_closed():
            return
        from dodaios.core.events import SelfBuildChanged

        event = SelfBuildChanged(
            build_id=record.id,
            kind=record.kind.value,
            state=record.state.value,
            title=record.title,
            source_layer="self_build",
        )

        def fire() -> None:
            self.spawn(publish(event), "publish")

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:  # called from a worker thread: hop onto the bound loop
            running = None
        if running is loop:
            fire()
        else:
            loop.call_soon_threadsafe(fire)


def start(
    data_dir: Path, config: Callable[[], Any], *, publish: Publish | None = None
) -> SelfBuild:
    """Open the ledger for this process (idempotent)."""
    global _current
    if _current is None:
        _current = SelfBuild(data_dir, config, publish=publish)
        _current.retire_proposals()
    try:
        _current.bind_loop(asyncio.get_running_loop())
    except RuntimeError:  # started outside a loop: events stay off until bind_loop
        pass
    return _current


def current() -> SelfBuild | None:
    return _current


def reset_for_tests() -> None:
    global _current
    if _current is not None:
        _current.ledger.close()
    _current = None
