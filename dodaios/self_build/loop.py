"""The self-building loop for memories, skills, routines and agents.

Wiring (all event-driven; nothing here runs on a timer that wakes a model):

* **Observe.** Finished voice turns (``VoiceTurnCompleted``), the person's
  own typed turns in the Jarvis chat and in agent chats (the chat surfaces'
  completion hooks), and the prompts the person typed to coding agents in the
  IDE (``agentic_ide/prompt_history.py`` rows marked ``origin: person``) go
  to the :class:`~.miner.Miner`. Turns an agent or a routine started, and
  prompts the brain or an agent sent to a pane, are dropped. Each turn costs
  one SQLite insert.
* **Gate.** A need that crossed its threshold is checked without a model:
  an open build, a rejected or archived one, a recent "build nothing", earlier
  failed proofs, an installed skill that already serves it, and
  :func:`~.policy.admit` for every candidate kind. Agent chats feed needs by
  one rule: a need seen only in one agent's chat belongs to that agent's own
  learning (``society/learning.py``) and is left to it; a need that spans
  agents, or agents and the assistant, is the loop's, unless one of those
  agents already has a skill that serves it. Most needs stop here.
* **Decide.** Needs that pass wait until the person is not in the middle of
  talking to Dodaios: no turn of theirs, no typing into a pane and no open
  call for :data:`QUIET_S` (:mod:`dodaios.core.presence`; the operating
  system's input idle time is not asked, so work in other programs does not
  hold it up), or until a call ends, and never longer than
  :data:`MAX_WAIT_S` after the first need was queued. Then they get at most
  one model call each on a subscription or local seat, :data:`DECIDE_PER_DAY`
  at most per day. With no such seat a plain proposal is written from the
  counts instead.
* **Build** through :class:`~.builders.Builders`; **prove** in :mod:`.judge`.
* **Measure.** Uses are recorded from what really happens: a self-built skill
  fires (``SkillInvoked``) and is or is not corrected in the next turn, a
  self-built routine runs (``TaskCompleted``) or the person still asks by
  hand, the person talks to a self-built agent, a self-built memory entry
  that was in the prompt is relied on (:func:`.judge.memory_relied`) or
  corrected. The service's hourly sweep settles trials; kept builds unused
  for :data:`RETIRE_DAYS` are archived here.

The kill switch (``POST /api/self-build/pause``), ``[self_build].enabled`` and
the per-kind autonomy are read on every event, so pausing stops observation,
building and measuring at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

from dodaios.costs.ledger import usage_context

from . import brain, decide, judge, policy
from .builders import KINDS, Builders, Env, need_json
from .decide import Verdict
from .ledger import now_ms
from .miner import PANE, WINDOW_DAYS, Miner, Need, Observation
from .records import BuildRecord, Kind, Outcome, State, caller_for
from .signals import SignalStore, TurnRow

log = logging.getLogger(__name__)

_DAY_MS: Final[int] = 86_400_000
#: Needs are decided after this much quiet: never in the middle of a conversation.
#: Quiet means no turn of the person, no pane typing and no open call for this long.
QUIET_S: Final[float] = 90.0
#: A queued need is decided at the latest this long after it was queued, even
#: when the person keeps talking to Dodaios the whole time.
MAX_WAIT_S: Final[float] = 20 * 60.0
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
#: Channels whose prompt carries the assistant's notebook (a memory can be used there).
_NOTEBOOK_CHANNELS: Final[frozenset[str]] = frozenset({"voice", "chat"})

_current: SelfBuildLoop | None = None


class SelfBuildLoop:
    def __init__(
        self,
        service: Any,
        store: SignalStore,
        *,
        builders: Builders,
        idle: Callable[[], float | None] | None = None,
    ) -> None:
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
        #: ``idle() -> seconds | None``: since the person's last activity in
        #: Dodaios (``core/presence.py``); ``None`` when there was none.
        self._idle = idle if idle is not None else _dodaios_idle_s
        #: When the queue last went from empty to waiting (monotonic seconds).
        self._queued_at: float | None = None
        #: The last self-built skill that fired: ``(build id, ms, conversation)``;
        #: the conversation is filled in by the turn that fired it, so the
        #: person's NEXT turn there is the one judged for a correction.
        self._last_skill: tuple[str, int, str | None] | None = None
        #: ``(build id, conversation)`` already counted, one use per conversation.
        self._counted: set[tuple[str, str]] = set()
        #: conversation -> ``(memory build id, ms)`` of the last turn that relied
        #: on a self-built memory: a correction right after it counts against it.
        self._memory_hits: dict[str, tuple[str, int]] = {}
        #: One reader of the IDE's prompt histories at a time.
        self._pane_lock = asyncio.Lock()
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
            VoiceSessionStarted,
            VoiceTurnCompleted,
        )
        from dodaios.skills.schema import SkillInvoked

        if self._bus is not None or bus is None:
            return
        self._bus = bus
        for event_type, handler in (
            (VoiceTurnCompleted, self._on_voice_turn),
            (VoiceSessionStarted, self._on_voice_started),
            (VoiceSessionEnded, self._on_voice_ended),
            (SkillInvoked, self._on_skill_invoked),
            (TaskCompleted, self._on_task_completed),
            (TaskFailed, self._on_task_failed),
            (SelfBuildChanged, self._on_build_changed),
        ):
            bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
        # Pane prompts written while the loop was not running.
        self._spawn(self.ingest_pane_prompts(), "pane-prompts")

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
                    answer=str(getattr(event, "jarvis_text", "") or ""),
                )
            ),
            "observe",
        )

    async def _on_voice_started(self, event: Any) -> None:
        from dodaios.core import presence

        presence.call_started(str(getattr(event, "session_id", "") or ""))

    async def _on_voice_ended(self, event: Any) -> None:
        from dodaios.core import presence

        presence.call_ended(str(getattr(event, "session_id", "") or ""))
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
        answer = "".join(
            str((e.get("payload") or {}).get("text") or "")
            for e in events
            if e.get("kind") == "assistant_text"
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
                    answer=answer[-4000:],
                )
            ),
            "observe",
        )

    async def observe(self, obs: Observation) -> None:
        """File one turn, count its uses and queue the needs it completes."""
        if not obs.text.strip():
            return
        from dodaios.core import presence

        # The person spoke or typed to Dodaios: background work waits for quiet.
        presence.note(presence.TURN, at=obs.ts_ms / 1000 if obs.ts_ms else None)
        if not self._active():
            return
        from dodaios.memory.learning.signals import is_correction
        from dodaios.society.memory_intent import requested_memory

        if requested_memory(obs.text) is not None:
            return  # "remember that ..." belongs to the learning loop
        stamp = obs.ts_ms or now_ms()
        if not obs.ts_ms:
            obs = Observation(**{**_fields(obs), "ts_ms": stamp})
        # A pane prompt corrects a coding agent, not the assistant: no lesson
        # for the assistant's notebook comes from it.
        correction = obs.channel != PANE and is_correction(obs.text)
        if obs.agent_id:
            # A turn in a self-built agent's chat is a use of that agent. The
            # turn is filed too; the gate decides whose need it is.
            build = await asyncio.to_thread(self.store.build_for, f"agent:{obs.agent_id}")
            await self._record(build, Outcome.CORRECTED if correction else Outcome.USED)
        row, needs = await asyncio.to_thread(self.miner.observe, obs, correction=correction)
        if row is not None:
            await self._count_uses(row, obs.answer)
        for need in needs:
            if await asyncio.to_thread(self._worth_deciding, need):
                self._queue[need.signature] = need
        if self._queue:
            self._arm()
        if time.monotonic() - self._maintained >= MAINTAIN_EVERY_S:
            self._spawn(self.maintain(), "maintain")

    def _arm(self) -> None:
        """Look again after :data:`QUIET_S`, never later than the queue's deadline."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no loop: the queue waits for the next event
            return
        now = time.monotonic()
        if self._queued_at is None:
            self._queued_at = now
        left = MAX_WAIT_S - (now - self._queued_at)
        delay = max(0.0, min(QUIET_S, left))
        self._timer = loop.call_later(delay, lambda: self._spawn(self._when_quiet(), "decide"))

    def _busy(self) -> bool:
        """The person is talking to Dodaios: a turn, pane typing or a call within QUIET_S."""
        try:
            idle = self._idle()
        except Exception:  # noqa: BLE001 - an unreadable reading never blocks deciding
            log.debug("self_build: presence reading failed", exc_info=True)
            return False
        return idle is not None and idle < QUIET_S

    async def _when_quiet(self) -> None:
        """Decide once the person is quiet in Dodaios, or the queue waited :data:`MAX_WAIT_S`."""
        self._timer = None
        if not self._queue:
            self._queued_at = None
            return
        waited = time.monotonic() - (self._queued_at or time.monotonic())
        if waited < MAX_WAIT_S and self._busy():
            self._arm()  # mid-conversation: look again after another quiet stretch
            return
        if waited >= MAX_WAIT_S:
            log.info("self_build: deciding after %.0f s of waiting for quiet", waited)
        await self.run_queue()

    # ------------------------------------------------------------ gate

    def _worth_deciding(self, need: Need, *, now: int | None = None) -> bool:
        """Every check that costs no model call. Blocking (SQLite)."""
        stamp = now if now is not None else now_ms()
        cfg = policy.section(self.service.config())
        if cfg is None or self.ledger.open_for(need.signature) is not None:
            return False
        if self.ledger.rejections(need.signature) >= cfg.max_rejections:
            return False
        if owning_agent(need):
            return False  # one agent's own work: its learning pass covers it
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
            if not self._queue:
                self._queued_at = None
        return opened

    async def decide(self, need: Need) -> BuildRecord | None:
        if not await asyncio.to_thread(self._worth_deciding, need):
            return None
        lessons = await asyncio.to_thread(self.store.lessons, need.signature)
        allowed = await asyncio.to_thread(self._rungs, need, lessons)
        if Kind.SKILL in allowed or Kind.AGENT in allowed:
            served = await asyncio.to_thread(self._served, need) if Kind.SKILL in allowed else None
            by_agent = await asyncio.to_thread(self._served_by_agents, need)
            note = ""
            if by_agent is not None:
                # An agent already learned this: neither a global skill nor
                # another agent is built for it.
                allowed = tuple(k for k in allowed if k not in (Kind.SKILL, Kind.AGENT))
                note = f"the agent {by_agent[0]!r} has the skill {by_agent[1]!r} for this"
            elif served:
                allowed = tuple(k for k in allowed if k != Kind.SKILL)
                note = f"the skill {served!r} already does this"
            if note and not allowed:
                await asyncio.to_thread(
                    self.store.record_decision,
                    need.signature,
                    "served",
                    need.occurrences,
                    note,
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

    def _served_by_agents(self, need: Need) -> tuple[str, str] | None:
        """``(agent id, skill name)`` when an agent in the need's chats has a skill for it."""
        agents = sorted({t.agent_id for t in need.turns if t.agent_id})
        if not agents:
            return None
        said = [t.text for t in need.turns]
        core = core_stems(need)
        for agent_id in agents:
            try:
                skills = list(self.builders.env.agent_skills(agent_id))
            except Exception:  # noqa: BLE001 - an unreadable namespace serves nothing
                log.debug("self_build: skills of %s unreadable", agent_id, exc_info=True)
                continue
            name = judge.served_by_agent(skills, said, core)
            if name:
                return agent_id, name
        return None

    # ------------------------------------------------------------ measure

    async def _record(self, build_id: str | None, outcome: Outcome) -> None:
        if not build_id:
            return
        record = await asyncio.to_thread(self.ledger.get, build_id)
        if record is None or record.state not in (State.TRIAL, State.KEPT):
            return
        await asyncio.to_thread(self.ledger.record_use, build_id, outcome)

    async def _count_uses(self, row: TurnRow, answer: str = "") -> None:
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
        await self._count_memories(row, answer, topic=cluster.signature)

    async def _count_memories(self, row: TurnRow, answer: str, *, topic: str) -> None:
        """A self-built memory counts when it was in the prompt and the turn relied on it.

        In the prompt: the entry's text is in the notebook snapshot the
        assistant's prompts carry (an archived or edited entry is not).
        Relied on (:func:`.judge.memory_relied`): the person's words name the
        entry's subject, or the answer carries what only the entry said. At
        most one use per conversation. A correction in a turn about the
        entry, or right after a turn that relied on it, counts against it.
        """
        if row.channel not in _NOTEBOOK_CHANNELS:
            return  # coding agents and society agents do not read this notebook
        last = self._memory_hits.pop(row.conversation, None)
        if last is not None and row.correction and row.ts_ms - last[1] <= CORRECTION_WINDOW_MS:
            await self._record(last[0], Outcome.CORRECTED)
            return
        live = await asyncio.to_thread(self._live_memories)
        if not live:
            return
        snapshot = await asyncio.to_thread(self._notebook_snapshot)
        for record in live:
            entry = str((record.artefact or {}).get("text") or "")
            if not entry or entry not in snapshot:
                continue
            on_topic = record.signature == topic
            if row.correction:
                if on_topic or judge.memory_concerned(entry, said=row.stems):
                    await self._record(record.id, Outcome.CORRECTED)
                continue
            if not judge.memory_relied(entry, said=row.stems, answer=answer, topic=on_topic):
                continue
            self._memory_hits[row.conversation] = (record.id, row.ts_ms)
            key = (record.id, row.conversation)
            if key in self._counted:
                continue
            if len(self._counted) >= 5_000:
                self._counted.clear()
            self._counted.add(key)
            await self._record(record.id, Outcome.USED)

    def _live_memories(self) -> list[BuildRecord]:
        return [
            r
            for r in self.ledger.list(states=[State.TRIAL, State.KEPT], kinds=[Kind.MEMORY])
            if not self.builders.sleeping(r.id)
        ]

    def _notebook_snapshot(self) -> str:
        notebook = self.builders.env.notebook()
        if notebook is None:
            return ""
        try:
            return notebook.snapshot(compact=False) + "\n" + notebook.snapshot(compact=True)
        except Exception:  # noqa: BLE001 - an unreadable notebook injected nothing
            log.debug("self_build: notebook snapshot unreadable", exc_info=True)
            return ""

    # ------------------------------------------------------------ pane prompts

    def pane_prompt_recorded(self, history_id: str) -> None:
        """The IDE stored a prompt the person typed into a pane: read that history."""
        from dodaios.agentic_ide.prompt_history import path_for

        folder = self.builders.env.pane_history()
        if folder is None:
            return
        path = folder / path_for(history_id).name
        self._spawn(self.ingest_pane_prompts([path]), "pane-prompts")

    async def ingest_pane_prompts(self, paths: list[Any] | None = None) -> int:
        """File the person's new pane prompts as turns; ``paths`` ``None`` reads every pane.

        Each history file is read from where the last pass stopped (an offset
        in the signal store), so a prompt is filed once. Only rows marked
        ``origin: person`` count, in the person's own words (``typed`` when the
        prompt was a brief around them). While the loop is paused or off the
        offsets still move: what was typed then is never filed later.
        """
        async with self._pane_lock:
            found = await asyncio.to_thread(self._read_pane_prompts, paths)
        if not found or not self._active():
            return 0
        for obs in sorted(found, key=lambda o: o.ts_ms):
            await self.observe(obs)
        return len(found)

    def _read_pane_prompts(self, paths: list[Any] | None) -> list[Observation]:
        from pathlib import Path

        from dodaios.agentic_ide.prompt_history import PromptHistoryEntry

        if paths is None:
            folder = self.builders.env.pane_history()
            files = sorted(folder.glob("*.jsonl")) if folder is not None and folder.is_dir() else []
        else:
            files = [Path(p) for p in paths]
        cutoff = now_ms() - WINDOW_DAYS * _DAY_MS
        found: list[Observation] = []
        for path in files:
            key = f"pane:{path.name}"
            offset = int(self.store.get_meta(key, "0") or 0)
            try:
                size = path.stat().st_size
                if size < offset:
                    offset = 0  # the file was replaced: read it again
                if size == offset:
                    continue
                with path.open("rb") as handle:
                    handle.seek(offset)
                    data = handle.read()
            except OSError:  # gone or locked: the next pass reads it
                continue
            end = data.rfind(b"\n")
            if end < 0:
                continue  # a line still being written
            chunk = data[: end + 1]
            self.store.set_meta(key, str(offset + len(chunk)))
            for line in chunk.splitlines():
                try:
                    entry = PromptHistoryEntry.from_dict(json.loads(line))
                except (ValueError, UnicodeDecodeError):  # a damaged row says nothing
                    continue
                if entry is None or entry.origin != "person":
                    continue
                if entry.attachments and not entry.typed:
                    continue  # the text holds the dropped files' contents, not the person's
                stamp = int(entry.at * 1000)
                if stamp < cutoff:
                    continue
                found.append(
                    Observation(
                        text=entry.typed or entry.text,
                        channel=PANE,
                        conversation=f"pane:{path.stem[:16]}",
                        ts_ms=stamp,
                        ref=f"pane:{entry.id}",
                    )
                )
        return found

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
        # Turns filed while no zone could be named get their clock now.
        await asyncio.to_thread(self.store.fill_clocks)
        # Pane prompts whose notice was missed (the app was busy or restarting).
        await self.ingest_pane_prompts()
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


def owning_agent(need: Need) -> str:
    """The agent whose chat every turn of the need came from, else ``""``."""
    agents = {t.agent_id for t in need.turns}
    return next(iter(agents)) if len(agents) == 1 else ""


def core_stems(need: Need) -> frozenset[str]:
    """The stems at least half of the need's requests share: what it is about."""
    from collections import Counter

    counts = Counter(stem for t in need.turns for stem in t.stems)
    half = max(1, (len(need.turns) + 1) // 2)
    return frozenset(stem for stem, n in counts.items() if n >= half)


def _dodaios_idle_s() -> float | None:
    from dodaios.core import presence

    return presence.idle_s()


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
