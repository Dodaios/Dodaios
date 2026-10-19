"""The self-building loop for memories, skills, routines and agents.

Wiring (all event-driven; nothing here runs on a timer that wakes a model):

* **Observe.** Finished voice turns (``VoiceTurnCompleted``) and the person's
  own typed turns in the Jarvis chat and in agent chats (the chat surfaces'
  completion hooks) go to the :class:`~.miner.Miner`. Turns an agent or a
  routine started are dropped. Each turn costs one SQLite insert.
* **Gate.** A need that crossed its threshold is checked without a model:
  an open build, a rejected or archived one, a recent "build nothing", earlier
  failed proofs, an installed skill that already serves it, and
  :func:`~.policy.admit` for every candidate kind. Most needs stop here.
* **Decide.** Needs that pass wait until the person has been quiet for
  :data:`QUIET_S` (or a call ends), then get at most one model call each on a
  subscription or local seat, :data:`DECIDE_PER_DAY` at most per day. With no
  such seat a plain proposal is written from the counts instead.
* **Build** through :class:`~.builders.Builders`; **prove** in :mod:`.judge`.
* **Measure.** Uses are recorded from what really happens: a self-built skill
  fires (``SkillInvoked``) and is or is not corrected in the next turn, a
  self-built routine runs (``TaskCompleted``) or the person still asks by
  hand, the person talks to a self-built agent, a self-built memory's topic
  comes up with or without a correction. The service's hourly sweep settles
  trials; kept builds unused for :data:`RETIRE_DAYS` are archived here.

The kill switch (``POST /api/self-build/pause``), ``[self_build].enabled`` and
the per-kind autonomy are read on every event, so pausing stops observation,
building and measuring at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable
from typing import Any, Final

from dodaios.costs.ledger import usage_context

from . import brain, decide, judge, policy
from .builders import KINDS, Builders, Env, need_json
from .decide import Verdict
from .ledger import now_ms
from .miner import Miner, Need, Observation
from .records import BuildRecord, Kind, Outcome, State, caller_for
from .signals import SignalStore, TurnRow

log = logging.getLogger(__name__)

_DAY_MS: Final[int] = 86_400_000
#: Needs are decided after this much quiet: never while the person is busy.
QUIET_S: Final[float] = 90.0
#: Model calls the decide step may make per day, whatever crosses.
DECIDE_PER_DAY: Final[int] = 4
#: A "build nothing" verdict holds this long, unless the need doubles.
NOTHING_HOLD_DAYS: Final[int] = 30
#: A need whose builds failed their proof this often is left alone.
MAX_LESSONS: Final[int] = 2
#: A kept build nobody used for this long is archived (restorable).
RETIRE_DAYS: Final[int] = 30
#: A build stuck in ``building`` (no seat, paused) is retried after this long.
RETRY_MS: Final[int] = 10 * 60_000
#: Maintenance (prune, retire, retry) runs at most this often.
MAINTAIN_EVERY_S: Final[float] = 30 * 60.0
#: A correction this soon after a self-built skill fired counts against it.
CORRECTION_WINDOW_MS: Final[int] = 120_000
#: A routine run counts against a manual request made this soon after it.
ROUTINE_REACH_MS: Final[int] = 24 * 3_600_000
#: Turn statuses that mean the assistant answered.
_DONE: Final[frozenset[str]] = frozenset({"done", "ok", "completed"})

_current: SelfBuildLoop | None = None


class SelfBuildLoop:
    def __init__(self, service: Any, store: SignalStore, *, builders: Builders) -> None:
        self.service = service
        self.store = store
        self.builders = builders
        self.miner = Miner(store)
        self._queue: dict[str, Need] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._subscriptions: list[tuple[type[Any], Any]] = []
        self._bus: Any = None
        self._maintained = 0.0
        #: The last self-built skill that fired: ``(build id, ms, conversation)``;
        #: the conversation is filled in by the turn that fired it, so the
        #: person's NEXT turn there is the one judged for a correction.
        self._last_skill: tuple[str, int, str | None] | None = None
        #: ``(build id, conversation)`` already counted, one use per conversation.
        self._counted: set[tuple[str, str]] = set()
        #: Model calls made by the decide step (diagnostics and tests).
        self.decide_calls = 0

    @property
    def ledger(self) -> Any:
        return self.service.ledger

    # ------------------------------------------------------------ wiring

    def start(self, bus: Any) -> None:
        from dodaios.core.events import (
            SelfBuildChanged,
            TaskCompleted,
            TaskFailed,
            VoiceSessionEnded,
            VoiceTurnCompleted,
        )
        from dodaios.skills.schema import SkillInvoked

        if self._bus is not None or bus is None:
            return
        self._bus = bus
        for event_type, handler in (
            (VoiceTurnCompleted, self._on_voice_turn),
            (VoiceSessionEnded, self._on_voice_ended),
            (SkillInvoked, self._on_skill_invoked),
            (TaskCompleted, self._on_task_completed),
            (TaskFailed, self._on_task_failed),
            (SelfBuildChanged, self._on_build_changed),
        ):
            bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))

    async def stop(self) -> None:
        for event_type, handler in self._subscriptions:
            try:
                self._bus.unsubscribe(event_type, handler)
            except Exception:  # noqa: BLE001 - teardown reports, never raises
                log.debug("self_build: could not detach %s", event_type.__name__, exc_info=True)
        self._subscriptions.clear()
        self._bus = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        for task in tuple(self._tasks):
            task.cancel()

    def _spawn(self, work: Awaitable[Any], name: str) -> None:
        async def guarded() -> None:
            try:
                await work
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - background work must never surface
                log.warning("self_build: %s failed", name, exc_info=True)

        try:
            task = asyncio.get_running_loop().create_task(guarded(), name=f"self-build-{name}")
        except RuntimeError:  # no running loop: drop the work cleanly
            if asyncio.iscoroutine(work):
                work.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for background work started so far (tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    def _active(self) -> bool:
        cfg = policy.section(self.service.config())
        return bool(cfg is not None and cfg.enabled) and not policy.paused(self.ledger)

    # ------------------------------------------------------------ inputs

    async def _on_voice_turn(self, event: Any) -> None:
        # Off the voice path: the bus awaits typed handlers.
        session = str(getattr(event, "session_id", "") or "unknown")
        self._spawn(
            self.observe(
                Observation(
                    text=str(getattr(event, "user_text", "") or ""),
                    channel="voice",
                    conversation=f"voice:{session}",
                    tools=tuple(str(t) for t in getattr(event, "tool_calls", ()) or ()),
                    lang=str(getattr(event, "user_lang", "") or ""),
                    ref=f"voice:{session}/{getattr(event, 'turn_id', '')}",
                )
            ),
            "observe",
        )

    async def _on_voice_ended(self, _event: Any) -> None:
        # A call that ended is the quiet moment the decide step waits for.
        if self._queue:
            self._spawn(self.run_queue(), "decide")

    async def chat_turn_completed(self, session: Any, completion: Any, *, surface: str) -> None:
        """A chat surface's completion hook: one typed turn of the person."""
        from dodaios.society.memory_intent import user_evidence

        turn = getattr(completion, "turn", None)
        if turn is None or not getattr(turn, "direct_user", True):
            return  # agent- and routine-started turns are not the person speaking
        try:
            events = json.loads(completion.events_json)
        except (TypeError, ValueError):  # an unreadable completion holds nothing to count
            return
        typed = [user_evidence(e) for e in events if e.get("kind") == "user_message"]
        text = typed[-1] if typed else user_evidence({"payload": {"text": turn.user_text}})
        tools = tuple(
            str((e.get("payload") or {}).get("name") or "")
            for e in events
            if e.get("kind") == "tool_call"
        )
        finished = [e for e in events if e.get("kind") == "turn_finished"]
        status = str((finished[-1].get("payload") or {}).get("status") or "") if finished else ""
        errors = any(
            e.get("kind") == "tool_result" and (e.get("payload") or {}).get("is_error")
            for e in events
        )
        agent_id = ""
        if surface == "society":
            from dodaios.society.surface import agent_id_of

            agent_id = agent_id_of(str(session.session_id)) or ""
        self._spawn(
            self.observe(
                Observation(
                    text=text,
                    channel="agent" if agent_id else "chat",
                    conversation=f"chat:{session.session_id}",
                    tools=tuple(t for t in tools if t),
                    failed=(bool(status) and status not in _DONE) or errors,
                    agent_id=agent_id,
                    ref=f"chat:{session.session_id}/{getattr(turn, 'turn_id', '')}",
                )
            ),
            "observe",
        )

    async def observe(self, obs: Observation) -> None:
        """File one turn, count its uses and queue the needs it completes."""
        if not obs.text.strip() or not self._active():
            return
        from dodaios.memory.learning.signals import is_correction
        from dodaios.society.memory_intent import requested_memory

        if requested_memory(obs.text) is not None:
            return  # "remember that ..." belongs to the learning loop
        stamp = obs.ts_ms or now_ms()
        if not obs.ts_ms:
            obs = Observation(**{**_fields(obs), "ts_ms": stamp})
        correction = is_correction(obs.text)
        if obs.agent_id:
            # An agent chat only counts uses: each agent learns its own skills
            # (society/learning.py), and the loop's rungs serve the work the
            # person does with the assistant itself.
            build = await asyncio.to_thread(self.store.build_for, f"agent:{obs.agent_id}")
            await self._record(build, Outcome.CORRECTED if correction else Outcome.USED)
            return
        row, needs = await asyncio.to_thread(self.miner.observe, obs, correction=correction)
        if row is not None:
            await self._count_uses(row)
        for need in needs:
            if await asyncio.to_thread(self._worth_deciding, need):
                self._queue[need.signature] = need
        if self._queue:
            self._arm()
        if time.monotonic() - self._maintained >= MAINTAIN_EVERY_S:
            self._spawn(self.maintain(), "maintain")

    def _arm(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop: the queue waits for the next event
            return
        self._timer = loop.call_later(QUIET_S, lambda: self._spawn(self.run_queue(), "decide"))

    # ------------------------------------------------------------ gate

    def _worth_deciding(self, need: Need, *, now: int | None = None) -> bool:
        """Every check that costs no model call. Blocking (SQLite)."""
        stamp = now if now is not None else now_ms()
        cfg = policy.section(self.service.config())
        if cfg is None or self.ledger.open_for(need.signature) is not None:
            return False
        if self.ledger.rejections(need.signature) >= cfg.max_rejections:
            return False
        before = self.ledger.ever_for(need.signature)
        if any(r.state in (State.KEPT, State.ARCHIVED) for r in before):
            return False  # built before: kept, or archived because nobody used it
        lessons = self.store.lessons(need.signature)
        if len(lessons) >= MAX_LESSONS:
            return False
        hold = NOTHING_HOLD_DAYS * _DAY_MS
        if before and before[-1].state in (State.REJECTED, State.UNDONE):
            if stamp - before[-1].updated_ms < hold:
                return False  # the person said no: not again this month
        last = self.store.decision(need.signature)
        if last is not None:
            ts, verdict, occurrences = last
            if verdict in ("nothing", "served") and stamp - ts < hold:
                if need.occurrences < 2 * occurrences:
                    return False  # held for a month unless the need has doubled
        return bool(self._rungs(need, lessons))

    def _rungs(self, need: Need, lessons: list[tuple[str, str]]) -> tuple[Kind, ...]:
        failed = {kind for kind, _ in lessons}
        allowed: list[Kind] = []
        for kind in need.rungs:
            if kind.value in failed or kind not in KINDS:
                continue
            if self.service.admit(kind, need.signature).start is None:
                continue
            allowed.append(kind)
        return tuple(allowed)

    # ------------------------------------------------------------ decide

    async def run_queue(self) -> list[BuildRecord]:
        """Decide the queued needs (one model call each at most)."""
        opened: list[BuildRecord] = []
        async with self._lock:
            self._timer = None
            while self._queue:
                _, need = self._queue.popitem()
                if not self._active():
                    self._queue.clear()
                    break
                try:
                    record = await self.decide(need)
                except Exception:  # noqa: BLE001 - one need must not hold up the others
                    log.warning("self_build: deciding %s failed", need.signature, exc_info=True)
                    continue
                if record is not None:
                    opened.append(record)
        return opened

    async def decide(self, need: Need) -> BuildRecord | None:
        if not await asyncio.to_thread(self._worth_deciding, need):
            return None
        lessons = await asyncio.to_thread(self.store.lessons, need.signature)
        allowed = await asyncio.to_thread(self._rungs, need, lessons)
        if Kind.SKILL in allowed:
            served = await asyncio.to_thread(self._served, need)
            if served:
                allowed = tuple(k for k in allowed if k != Kind.SKILL)
                if not allowed:
                    await asyncio.to_thread(
                        self.store.record_decision,
                        need.signature,
                        "served",
                        need.occurrences,
                        f"the skill {served!r} already does this",
                    )
                    return None
        if not allowed:
            return None
        verdict = await self._verdict(need, allowed, lessons)
        if verdict is None:
            return None  # the daily decide budget is spent; the need comes back
        if verdict.kind is None:
            await asyncio.to_thread(
                self.store.record_decision,
                need.signature,
                "nothing",
                need.occurrences,
                verdict.why,
            )
            log.info("self_build: nothing to build for %s (%s)", need.signature, verdict.why)
            return None
        admission = self.service.admit(verdict.kind, need.signature)
        if admission.start is None:
            return None
        start = State.PROPOSED if verdict.deterministic else admission.start
        record = await asyncio.to_thread(
            self.ledger.open_case,
            verdict.kind,
            need.signature,
            verdict.title,
            case=_case_text(verdict, need, admission.reason),
            evidence=[t.evidence() for t in need.turns],
            state=start,
        )
        await asyncio.to_thread(
            self.store.put_spec,
            record.id,
            need.signature,
            verdict.kind.value,
            {"need": need_json(need), "spec": verdict.spec or None},
        )
        await asyncio.to_thread(
            self.store.record_decision, need.signature, verdict.kind.value, need.occurrences
        )
        log.info(
            "self_build: opened %s %s for %s (%s)",
            record.state.value,
            record.kind.value,
            need.signature,
            admission.reason,
        )
        if record.state == State.BUILDING:
            self.service.spawn(self.builders.build(record), f"build {record.id}")
        return record

    async def _verdict(
        self, need: Need, allowed: tuple[Kind, ...], lessons: list[tuple[str, str]]
    ) -> Verdict | None:
        config = self.service.config()
        if not await asyncio.to_thread(brain.available, config):
            return decide.fallback(need, allowed)
        if not await asyncio.to_thread(self.store.take_daily, "decide", DECIDE_PER_DAY):
            return None
        skills = await asyncio.to_thread(self._skill_names)
        prompt = decide.build_prompt(need, allowed, lessons=lessons, skills=skills)
        self.decide_calls += 1
        try:
            with usage_context(caller_for("decide")):
                text = await brain.ask(
                    config, decide.SYSTEM_PROMPT, prompt, max_tokens=decide.DECIDE_MAX_TOKENS
                )
        except brain.BackgroundDeferred:  # no seat after all: propose from the counts
            return decide.fallback(need, allowed)
        return decide.parse(text, allowed)

    def _installed_skills(self) -> list[Any]:
        registry = self.builders.env.skill_registry()
        if registry is None:
            return []
        try:
            return list(registry.list_active())
        except Exception:  # noqa: BLE001 - no registry view means nothing installed
            return []

    def _skill_names(self) -> list[str]:
        return [str(s.name) for s in self._installed_skills()]

    def _served(self, need: Need) -> str | None:
        return judge.served_by(self._installed_skills(), [t.text for t in need.turns])

    # ------------------------------------------------------------ measure

    async def _record(self, build_id: str | None, outcome: Outcome) -> None:
        if not build_id:
            return
        record = await asyncio.to_thread(self.ledger.get, build_id)
        if record is None or record.state not in (State.TRIAL, State.KEPT):
            return
        await asyncio.to_thread(self.ledger.record_use, build_id, outcome)

    async def _count_uses(self, row: TurnRow) -> None:
        last = self._last_skill
        if last is not None:
            build, fired_at, conversation = last
            if abs(row.ts_ms - fired_at) > CORRECTION_WINDOW_MS:
                self._last_skill = None
            elif conversation is None:
                # The turn that fired the skill: the person's reply comes next.
                self._last_skill = (build, row.ts_ms, row.conversation)
            elif conversation == row.conversation:
                self._last_skill = None
                if row.correction:
                    await self._record(build, Outcome.CORRECTED)
        cluster = await asyncio.to_thread(self.store.cluster, row.cluster)
        if cluster is None:
            return
        for record in await asyncio.to_thread(self._live_for, cluster.signature):
            if record.kind == Kind.ROUTINE:
                # The person still asked by hand although the routine ran: it did not help.
                ran = int(self.store.get_meta(f"ran:{record.id}", "0") or 0)
                if ran and row.ts_ms - ran <= ROUTINE_REACH_MS:
                    await self._record(record.id, Outcome.CORRECTED)
            elif record.kind == Kind.MEMORY:
                key = (record.id, row.conversation)
                if row.correction:
                    await self._record(record.id, Outcome.CORRECTED)
                elif key not in self._counted:
                    if len(self._counted) >= 5_000:
                        self._counted.clear()
                    self._counted.add(key)
                    await self._record(record.id, Outcome.USED)

    def _live_for(self, signature: str) -> list[BuildRecord]:
        return [r for r in self.ledger.ever_for(signature) if r.state in (State.TRIAL, State.KEPT)]

    # Bus handlers hand their work to a task: the bus awaits typed handlers,
    # and a skill run or a routine run must not wait on the loop's SQLite.

    async def _on_skill_invoked(self, event: Any) -> None:
        self._spawn(self._skill_invoked(event), "skill-use")

    async def _skill_invoked(self, event: Any) -> None:
        if not self._active() or str(getattr(event, "source", "")) == "cron":
            return  # a scheduled run is not the person using it
        name = str(getattr(event, "skill_name", "") or "")
        build = await asyncio.to_thread(self.store.build_for, f"skill:{name}")
        if build:
            self._last_skill = (build, now_ms(), None)
            await self._record(build, Outcome.USED)

    async def _on_task_completed(self, event: Any) -> None:
        self._spawn(self._task_done(str(event.task_id), ok=True), "routine-use")

    async def _on_task_failed(self, event: Any) -> None:
        if not getattr(event, "will_retry", False):
            self._spawn(self._task_done(str(event.task_id), ok=False), "routine-use")

    async def _task_done(self, task_id: str, *, ok: bool) -> None:
        if not self._active():
            return
        build = await asyncio.to_thread(self.store.build_for, f"task:{task_id}")
        if not build:
            return
        if ok:
            await asyncio.to_thread(self.store.set_meta, f"ran:{build}", str(now_ms()))
        await self._record(build, Outcome.USED if ok else Outcome.IGNORED)

    async def _on_build_changed(self, event: Any) -> None:
        if str(getattr(event, "kind", "")) in {k.value for k in KINDS}:
            self._spawn(self._build_changed(str(event.build_id)), "build-changed")

    async def _build_changed(self, build_id: str) -> None:
        """Archived builds go dormant, kept-again ones wake up."""
        record = await asyncio.to_thread(self.ledger.get, build_id)
        if record is None or not record.artefact:
            return
        if record.state == State.ARCHIVED:
            await self.builders.dormant(record)
        elif record.state == State.KEPT:
            await self.builders.restore(record)

    # ------------------------------------------------------------ maintenance

    async def maintain(self, *, now: int | None = None) -> None:
        """Prune old turns, retire unused kept builds, retry waiting ones. No model."""
        self._maintained = time.monotonic()
        if not self._active():
            return
        stamp = now if now is not None else now_ms()
        await asyncio.to_thread(self.store.prune, now=stamp)
        kept = await asyncio.to_thread(self.ledger.list, states=[State.KEPT], kinds=KINDS)
        for record in kept:
            last = max(record.last_used_ms, record.trial_started_ms, record.created_ms)
            if stamp - last >= RETIRE_DAYS * _DAY_MS:
                await asyncio.to_thread(
                    self.ledger.set_state,
                    record.id,
                    State.ARCHIVED,
                    f"archived: unused for {RETIRE_DAYS} days",
                )
        # Archived builds sleep and kept ones are awake, also when an event
        # was missed or applying it failed (a routine that was running).
        settled = await asyncio.to_thread(
            self.ledger.list, states=[State.ARCHIVED, State.KEPT], kinds=KINDS, limit=500
        )
        for record in settled:
            if not record.artefact:
                continue
            asleep = await asyncio.to_thread(self.builders.sleeping, record.id)
            if record.state == State.ARCHIVED and not asleep:
                await self.builders.dormant(record)
            elif record.state == State.KEPT and asleep:
                await self.builders.restore(record)
        waiting = await asyncio.to_thread(self.ledger.list, states=[State.BUILDING], kinds=KINDS)
        for record in waiting:
            if stamp - record.updated_ms >= RETRY_MS and not self.builders.running(record.id):
                self.service.spawn(self.builders.build(record), f"retry {record.id}")


def _fields(obs: Observation) -> dict[str, Any]:
    return {name: getattr(obs, name) for name in Observation.__dataclass_fields__}


def _case_text(verdict: Verdict, need: Need, reason: str) -> str:
    lines = [verdict.case.strip()] if verdict.case.strip() else []
    lines.append(
        f"Signal: {', '.join(need.reasons)}; {need.occurrences} requests on {need.days} days."
    )
    if verdict.deterministic:
        lines.append("Written from the counts alone: no subscription or local model was available.")
    lines.append(f"Admitted: {reason}.")
    return "\n".join(lines)


# ------------------------------------------------------------ process-wide


def current() -> SelfBuildLoop | None:
    return _current


def install(
    service: Any,
    *,
    env: Env,
    bus: Any,
) -> SelfBuildLoop:
    """Register the builders and undoers and start observing (idempotent)."""
    global _current
    if _current is not None:
        return _current
    from .signals import DB_NAME

    store = SignalStore(env.data_dir / DB_NAME)
    builders = Builders(service, store, env)
    builders.register()
    _current = SelfBuildLoop(service, store, builders=builders)
    _current.start(bus)
    return _current


def reset_for_tests() -> None:
    global _current
    if _current is not None:
        _current.store.close()
    _current = None
