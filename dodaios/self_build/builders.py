"""Build: memories, skills, routines and agents through the paths that exist.

One builder per kind, each registered with :class:`~dodaios.self_build.service.SelfBuild`
together with its undoer. A builder never opens a new back door: a memory is
a notebook entry written by the learning notebook, a skill goes through the
skill creator's writer and the registry's own promote, a routine is a task in
the Automations scheduler owned by the lead, an agent is a roster row. No
agent tool reaches any of this: the builder is a trusted service at the
scheduler's privilege (MASTERPLAN §6.4).

Each build runs the same stages on its ledger record:

``building`` the spec exists (the decide step wrote it; for an accepted card
written without a model, it is written now). ``proving`` the judge
(:mod:`.judge`) checks the spec, with a shadow run for routines and agents
and a read-only run of a skill's steps (:mod:`.sandbox`), each produced on a
subscription or local seat and delivered nowhere.
``trial`` the artefact is created, labelled as self-built and undoable. A
failed proof marks the build ``failed`` and records the lesson, so the same
build is not tried again.

When the trial sweep archives a build, the artefact goes dormant instead of
away (a skill is switched off, a routine paused, an agent paused, a memory
entry taken out of the notebook); keeping it again wakes it up. Undo removes
it.

Every model call runs inside :func:`dodaios.self_build.cost.attributed` and
only on a subscription or a local model (:mod:`.brain`).
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from . import brain, decide, judge, policy
from .cost import attributed
from .ledger import now_ms
from .miner import Need, stems
from .records import BuildRecord, Kind, State, TransitionError
from .signals import SignalStore, TurnRow

log = logging.getLogger(__name__)

#: The kinds this module builds (code changes are built elsewhere).
KINDS: Final[tuple[Kind, ...]] = (Kind.MEMORY, Kind.SKILL, Kind.ROUTINE, Kind.AGENT)
#: What a self-built artefact says about itself (skill tags, author, task tags).
PROVENANCE: Final[str] = "self-built"
AUTHOR: Final[str] = "Dodaios (self-built)"
#: Recent requests of the person the skill replay must not fire on.
_OTHER_REQUESTS: Final[int] = 60
_DAY_MS: Final[int] = 86_400_000
#: Shadow requests an agent must answer before it exists.
_AGENT_SHADOWS: Final[int] = 2
#: Model calls per day for writing specs, shadow runs and skill replays (the
#: decide step has its own budget in loop.py). A routine costs one, an agent
#: two, a skill one per replay (at most :data:`SKILL_REPLAYS`).
DAILY_MODEL_CALLS: Final[int] = 6
#: Past requests a drafted skill's steps are run on before it may go live.
SKILL_REPLAYS: Final[int] = 2

ROUTINE_SHADOW_SYSTEM: Final[str] = (
    "You are running a scheduled routine for your user, as a dry run. Produce the result the "
    "routine asks for now, in the user's language. You have no tools in this run: where a step "
    "needs one, say in one line what you would look up. Never send, post or buy anything."
)


@dataclass
class Env:
    """What the builders reach in the running app; tests pass their own."""

    config: Callable[[], Any]
    data_dir: Path
    bus: Any = None
    notebook: Callable[[], Any] = lambda: None
    skill_registry: Callable[[], Any] = lambda: None
    task_store: Callable[[], Any] = lambda: None
    scheduler: Callable[[], Any] = lambda: None
    society: Callable[[], Awaitable[Any]] | None = None
    #: Skill on/off switch (the Skills view's own preference store).
    set_skill_on: Callable[[str, bool], None] | None = None
    #: A society agent's own skills, active and draft (``society/learning.py``).
    #: Blocking; the loop calls it in a worker thread.
    agent_skills: Callable[[str], list[Any]] = lambda _agent_id: []
    #: The folder of the IDE's per-pane prompt histories; ``None`` reads none.
    pane_history: Callable[[], Path | None] = lambda: None
    #: Runs a drafted skill's steps read-only on one request; ``None`` is
    #: :func:`.sandbox.run` (tests pass their own).
    run_skill: Callable[..., Awaitable[Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Waiting(RuntimeError):
    """The build cannot go on right now (no seat, paused); it stays ``building``."""


# ------------------------------------------------------------------ need (de)serialisation


def need_json(need: Need) -> dict[str, Any]:
    return {
        "signature": need.signature,
        "reasons": list(need.reasons),
        "rungs": [k.value for k in need.rungs],
        "turns": [t.id for t in need.turns],
        "occurrences": need.occurrences,
        "days": need.days,
        "tools": list(need.tools),
        "schedule": dict(need.schedule) if need.schedule else None,
        "cluster": need.cluster,
        "clusters": list(need.clusters),
    }


def need_from(data: dict[str, Any], store: SignalStore) -> Need:
    turns = tuple(store.turns_by_id(int(i) for i in data.get("turns") or []))
    return Need(
        signature=str(data.get("signature") or ""),
        reasons=tuple(str(r) for r in data.get("reasons") or []),
        rungs=tuple(Kind(k) for k in data.get("rungs") or []),
        turns=turns,
        occurrences=int(data.get("occurrences") or len(turns)),
        days=int(data.get("days") or len({t.day for t in turns})),
        tools=tuple(str(t) for t in data.get("tools") or []),
        schedule=dict(data["schedule"]) if data.get("schedule") else None,
        cluster=int(data.get("cluster") or 0),
        clusters=tuple(int(c) for c in data.get("clusters") or []),
    )


# ------------------------------------------------------------------ the builders


class Builders:
    def __init__(self, service: Any, store: SignalStore, env: Env) -> None:
        self.service = service
        self.store = store
        self.env = env
        self._running: set[str] = set()
        self._sleep_locks: dict[str, asyncio.Lock] = {}

    @property
    def ledger(self) -> Any:
        return self.service.ledger

    def register(self) -> None:
        for kind in KINDS:
            self.service.undo.register(kind, self.undo)
            self.service.register_builder(kind, self.build)

    def running(self, build_id: str) -> bool:
        return build_id in self._running

    # ------------------------------------------------------------ entry point

    async def build(self, record: BuildRecord) -> None:
        """Take one ``building`` record to ``trial`` or ``failed``."""
        if record.id in self._running:
            return
        self._running.add(record.id)
        try:
            await self._build(record)
        except Waiting as exc:
            log.info("self_build: %s waits (%s)", record.id, exc)
        finally:
            self._running.discard(record.id)

    async def _build(self, record: BuildRecord) -> None:
        if policy.paused(self.ledger):
            raise Waiting("paused")
        current = await asyncio.to_thread(self.ledger.get, record.id)
        if current is None or current.state != State.BUILDING:
            return
        stored = await asyncio.to_thread(self.store.spec, record.id) or {}
        need = need_from(stored.get("need") or {"signature": record.signature}, self.store)
        spec = stored.get("spec")
        if not isinstance(spec, dict) or not spec:
            spec = await self._write_spec(record, need)
            if spec is None:
                return
            stored["spec"] = spec
            await asyncio.to_thread(
                self.store.put_spec, record.id, record.signature, record.kind.value, stored
            )
        builder = {
            Kind.MEMORY: self._memory,
            Kind.SKILL: self._skill,
            Kind.ROUTINE: self._routine,
            Kind.AGENT: self._agent,
        }[record.kind]
        try:
            await builder(record, need, spec)
        except Waiting:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded as the lesson, never lost
            log.warning("self_build: %s build failed", record.id, exc_info=True)
            await self._fail(record, f"could not build: {type(exc).__name__}: {exc}")

    async def _write_spec(self, record: BuildRecord, need: Need) -> dict[str, Any] | None:
        """An accepted card that was written without a model: write its spec now.

        ``None`` when the model saw nothing to build; the record is then failed.
        """
        cfg = self.env.config()
        if not need.turns:
            await self._fail(record, "the turns this build came from are gone")
            return None
        if not await asyncio.to_thread(self.store.take_daily, "model_calls", DAILY_MODEL_CALLS):
            raise Waiting("today's model budget for self-building is spent")
        lessons = await asyncio.to_thread(self.store.lessons, need.signature)
        prompt = decide.build_prompt(need, (record.kind,), lessons=lessons)
        try:
            with attributed(record.id):
                text = await brain.ask(
                    cfg, decide.SYSTEM_PROMPT, prompt, max_tokens=decide.DECIDE_MAX_TOKENS
                )
        except brain.BackgroundDeferred as exc:
            raise Waiting(str(exc)) from exc
        verdict = decide.parse(text, (record.kind,))
        if verdict.kind is None:
            await self._fail(record, f"no spec: {verdict.why}")
            return None
        return verdict.spec

    # ------------------------------------------------------------ shared stages

    async def _set(self, build_id: str, state: State, note: str) -> BuildRecord:
        return await asyncio.to_thread(self.ledger.set_state, build_id, state, note)

    async def _fail(self, record: BuildRecord, reason: str) -> None:
        current = await asyncio.to_thread(self.ledger.get, record.id)
        if current is None or not current.open:
            return
        if not current.proof:
            await asyncio.to_thread(
                self.ledger.attach_proof, record.id, passed=False, judge=judge.JUDGE, detail=reason
            )
        await asyncio.to_thread(self.store.add_lesson, record.signature, record.kind.value, reason)
        await self._set(record.id, State.FAILED, reason[:300])

    async def _prove(self, record: BuildRecord, proof: judge.Proof) -> bool:
        """Record the judge's verdict; ``True`` when the build may be created.

        Everything that can make a build wait (no seat, no scheduler, no time
        zone, a shadow run) happens before this, while the record is still
        ``building`` and so can be retried.
        """
        current = await asyncio.to_thread(self.ledger.get, record.id)
        if current is None or current.state != State.BUILDING:
            return False  # undone or rejected meanwhile
        if policy.paused(self.ledger):
            raise Waiting("paused")
        await self._set(record.id, State.PROVING, "proving")
        await asyncio.to_thread(
            self.ledger.attach_proof,
            record.id,
            passed=proof.passed,
            judge=proof.judge,
            detail=proof.detail,
        )
        if not proof.passed:
            await self._fail(record, proof.detail)
            return False
        return await self._may_create(record)

    async def _may_create(self, record: BuildRecord) -> bool:
        """Checked right before an artefact is created: still wanted, not paused."""
        current = await asyncio.to_thread(self.ledger.get, record.id)
        if current is None or current.state != State.PROVING:
            return False
        if policy.paused(self.ledger):
            await self._set(record.id, State.FAILED, "paused while it was being built")
            return False
        return True

    async def _live(
        self, record: BuildRecord, artefact: dict[str, Any], undo: dict[str, Any], key: str
    ) -> None:
        await asyncio.to_thread(self.ledger.attach_artefact, record.id, artefact, undo)
        await asyncio.to_thread(self.store.bind_artefact, key, record.id)
        try:
            await self._set(record.id, State.TRIAL, "built, proven, live on trial")
        except TransitionError:
            # Undone while the artefact was being created: remove it again.
            fresh = await asyncio.to_thread(self.ledger.get, record.id)
            log.info("self_build: %s was undone while building; removing it", record.id)
            await self.undo(fresh or record)

    async def _shadow(self, record: BuildRecord, system: str, prompt: str) -> str:
        if not await asyncio.to_thread(self.store.take_daily, "model_calls", DAILY_MODEL_CALLS):
            raise Waiting("today's model budget for self-building is spent")
        try:
            with attributed(record.id):
                return await brain.ask(self.env.config(), system, prompt, max_tokens=900)
        except brain.BackgroundDeferred as exc:
            raise Waiting(str(exc)) from exc

    # ------------------------------------------------------------ memory

    async def _memory(self, record: BuildRecord, need: Need, spec: dict[str, Any]) -> None:
        notebook = self.env.notebook()
        if notebook is None:
            await self._fail(record, "the assistant's notebook is switched off")
            return
        said = [t.text for t in need.turns]
        entries = await asyncio.to_thread(notebook.entries)
        proof = judge.memory(spec, said=said, entries=entries)
        if not await self._prove(record, proof):
            return
        target = str(spec.get("target") or "memory").strip().lower()
        text = " ".join(str(spec.get("text") or "").split())
        change = await asyncio.to_thread(
            notebook.apply,
            target=target,
            operation="add",
            text=text,
            importance=int(spec.get("importance") or 7),
            origin="self_build",
            evidence=str(spec.get("evidence") or ""),
            source=f"self_build:{record.id}",
        )
        if change is None:
            await self._fail(record, "the notebook already says this")
            return
        entry_id = await asyncio.to_thread(_entry_id, notebook, target, text)
        payload = {
            "type": "memory",
            "id": await asyncio.to_thread(_memory_path, notebook, target),
            "target": target,
            "entry_id": entry_id,
            "text": text,
        }
        await self._live(record, payload, payload, f"memory:{target}:{entry_id}")

    # ------------------------------------------------------------ skill

    async def _skill(self, record: BuildRecord, need: Need, spec: dict[str, Any]) -> None:
        from dodaios.skills.authoring.service import SkillAuthoringError, slugify
        from dodaios.skills.creator_service import SkillCreatorService

        registry = self.env.skill_registry()
        if registry is None:
            await self._fail(record, "the skill registry is not running")
            return
        draft = skill_draft(spec, need)
        if not draft["name"]:
            await self._fail(record, "the skill has no usable name")
            return
        scratch = self.env.data_dir / "self_build" / "proof" / record.id
        try:
            candidate = await asyncio.to_thread(self._candidate, scratch, draft)
            installed = await asyncio.to_thread(registry.list_active)
            others = await asyncio.to_thread(self._other_requests, need)
            proof = await asyncio.to_thread(
                judge.skill,
                candidate,
                said=[t.text for t in need.turns],
                others=others,
                installed=list(installed),
                tools_seen={tool for t in need.turns for tool in t.tools},
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch, True)
        if proof.passed:
            # Routing and form hold; now the steps themselves, read-only, on
            # requests the person made (may wait for a seat or the budget).
            runs, accepted = await self._execute_skill(record, need, draft)
            execution = judge.skill_execution(runs, accepted=accepted)
            proof = judge.Proof(
                execution.passed, proof.judge, f"{proof.detail}; {execution.detail}"
            )
        if not await self._prove(record, proof):
            return
        creator = SkillCreatorService(registry=registry, bus=self.env.bus)
        skill = None
        base = draft["name"]
        for attempt in range(1, 6):
            draft["name"] = base if attempt == 1 else f"{base}-{attempt}"
            try:
                skill = await creator.commit(draft)
                break
            except SkillAuthoringError as exc:
                if exc.status != 409:
                    raise
        if skill is None:
            await self._fail(record, "no free skill name")
            return
        slug = slugify(skill.name) or skill.path.parent.name
        # ADR-0043: a skill made by this trusted builder that passed the
        # replay above goes live on trial. Agent- and chat-made skills still
        # land as drafts and wait for the person's activation (AP-SM6).
        try:
            promoted = await asyncio.to_thread(registry.promote, skill.path.parent.name)
        except Exception:
            # Never leave a half-made skill behind: the draft goes too.
            await asyncio.to_thread(self._remove_skill, record.id, {"path": str(skill.path.parent)})
            raise
        payload = {
            "type": "skill",
            "id": promoted.name,
            "name": promoted.name,
            "slug": slug,
            "path": str(promoted.path.parent),
        }
        await self._live(record, payload, payload, f"skill:{promoted.name}")

    async def _execute_skill(
        self, record: BuildRecord, need: Need, draft: dict[str, Any]
    ) -> tuple[list[Any], list[tuple[str, ...]]]:
        """Run the draft's steps read-only on up to :data:`SKILL_REPLAYS` past requests.

        Each run takes one unit of the daily build budget. Without a seat or
        budget for the first run the build waits (it stays ``building``).
        """
        from . import sandbox

        replays = await asyncio.to_thread(self._replays, need)
        tools = tuple(
            dict.fromkeys(
                [*draft["requires_tools"], *(t for turn in need.turns for t in turn.tools)]
            )
        )
        runner = self.env.run_skill or sandbox.run
        runs: list[Any] = []
        accepted: list[tuple[str, ...]] = []
        for turn in replays:
            if not await asyncio.to_thread(self.store.take_daily, "model_calls", DAILY_MODEL_CALLS):
                if runs:
                    break
                raise Waiting("today's model budget for self-building is spent")
            try:
                with attributed(record.id):
                    result = await runner(
                        self.env.config(),
                        skill_name=draft["name"],
                        skill_body=draft["body"],
                        request=turn.text,
                        tools=tools,
                    )
            except brain.BackgroundDeferred as exc:
                raise Waiting(str(exc)) from exc
            runs.append(result)
            accepted.append(turn.tools)
        return runs, accepted

    def _replays(self, need: Need) -> list[TurnRow]:
        """The requests to run a skill on: ones the person accepted, newest first.

        Accepted means answered (not failed), not itself a correction, and not
        corrected by the person's next turn in that conversation. A need made
        only of failures replays its newest failures: the steps must do better.
        """
        from .loop import CORRECTION_WINDOW_MS

        turns = sorted(need.turns, key=lambda t: t.ts_ms, reverse=True)
        accepted: list[TurnRow] = []
        for turn in turns:
            if turn.failed or turn.correction:
                continue
            after = self.store.turns_in(
                turn.conversation,
                since_ms=turn.ts_ms + 1,
                until_ms=turn.ts_ms + CORRECTION_WINDOW_MS,
            )
            if any(t.correction for t in after):
                continue
            accepted.append(turn)
        pool = accepted or turns
        picked: list[TurnRow] = []
        for turn in pool:  # different days first: two replays of one morning say less
            if all(turn.day != p.day for p in picked):
                picked.append(turn)
            if len(picked) == SKILL_REPLAYS:
                return picked
        for turn in pool:
            if turn not in picked and len(picked) < SKILL_REPLAYS:
                picked.append(turn)
        return picked

    def _candidate(self, scratch: Path, draft: dict[str, Any]) -> Any:
        """The skill as it would load, parsed from a scratch copy (live state)."""
        from dodaios.skills.authoring.service import SkillCreateRequest, render_skill_md, slugify
        from dodaios.skills.loader import parse_skill

        folder = scratch / (slugify(draft["name"]) or "skill")
        folder.mkdir(parents=True, exist_ok=True)
        request = SkillCreateRequest(
            name=draft["name"],
            description=draft["description"],
            category=draft["category"],
            tags=tuple(draft["tags"]),
            triggers=tuple(draft["triggers"]),
            requires_tools=tuple(draft["requires_tools"]),
            risk_policy=draft["risk_policy"],
            body=draft["body"],
            author=AUTHOR,
            state="active",
        )
        path = folder / "SKILL.md"
        path.write_text(render_skill_md(request), encoding="utf-8")
        return parse_skill(path)

    def _other_requests(self, need: Need) -> list[str]:
        """The person's recent requests that are NOT this need (replay negatives)."""
        own = {t.id for t in need.turns}
        clusters = {need.cluster, *need.clusters} - {0}
        since = now_ms() - 28 * _DAY_MS
        rows = [
            t
            for t in self.store.recent_turns(since_ms=since, limit=400)
            if t.id not in own and t.cluster not in clusters
        ]
        return [t.text for t in rows[:_OTHER_REQUESTS]]

    # ------------------------------------------------------------ routine

    async def _routine(self, record: BuildRecord, need: Need, spec: dict[str, Any]) -> None:
        from dodaios.society.roster import LEAD_AGENT_ID
        from dodaios.society.routines import (
            MAX_ROUTINES_PER_AGENT,
            build_task_spec,
            count_routines,
            create_routine,
        )

        store, scheduler = self.env.task_store(), self.env.scheduler()
        runtime = await self.env.society() if self.env.society is not None else None
        if store is None or runtime is None:
            raise Waiting("the scheduler or the society is not running yet")
        lead = await runtime.roster.get(LEAD_AGENT_ID)
        if lead is None:
            raise Waiting("the lead is not in the roster yet")
        provider = await asyncio.to_thread(brain.provider_for_runs, self.env.config())
        if not provider:
            raise Waiting("no subscription or local model to run the routine on")
        from .clock import person_zone_name

        schedule = dict(spec.get("schedule") or need.schedule or {})
        schedule.pop("habit", None)
        # The zone the UI reported, else this computer's (logged by clock.py).
        zone = await asyncio.to_thread(person_zone_name)
        if not zone:
            raise Waiting("no time zone can be named for the person yet")
        schedule["timezone"] = zone
        spec = {**spec, "schedule": schedule}
        shadow = await self._shadow(record, ROUTINE_SHADOW_SYSTEM, str(spec.get("prompt") or ""))
        word_stems: frozenset[str] = frozenset()
        for turn in need.turns:
            word_stems |= turn.stems
        proof = judge.routine(
            spec,
            asked=[(t.weekday, t.minute) for t in need.turns],
            stems=word_stems,
            shadow=shadow,
        )
        if not await self._prove(record, proof):
            return
        if await count_routines(store, lead.agent_id) >= MAX_ROUTINES_PER_AGENT:
            await self._fail(record, "the lead's routine cap is reached")
            return
        task = build_task_spec(
            lead,
            title=str(spec.get("title") or record.title)[:120],
            prompt=str(spec.get("prompt") or ""),
            schedule=schedule,
            plugin_grants=[],
            announce_on_success=None,
            provider=provider,
            model="",
            effort="",
            account_id="",
        )
        task = task.model_copy(update={"tags": (*task.tags, PROVENANCE)})
        task_id = await create_routine(store, scheduler, task)
        payload = {
            "type": "routine",
            "id": task_id,
            "task_id": task_id,
            "agent_id": lead.agent_id,
        }
        await self._live(record, payload, payload, f"task:{task_id}")

    # ------------------------------------------------------------ agent

    async def _agent(self, record: BuildRecord, need: Need, spec: dict[str, Any]) -> None:
        runtime = await self.env.society() if self.env.society is not None else None
        if runtime is None:
            raise Waiting("the society is not running yet")
        provider = await asyncio.to_thread(brain.provider_for_runs, self.env.config())
        if not provider:
            raise Waiting("no subscription or local model to seat the agent on")
        taken = [a.name for a in await runtime.roster.list(include_archived=False)]
        description = str(spec.get("description") or "")
        shadows = [
            await self._shadow(record, description, turn.text)
            for turn in list(need.turns)[-_AGENT_SHADOWS:]
        ]
        tools_seen = {tool for t in need.turns for tool in t.tools}
        proof = judge.agent(spec, taken=taken, tools_seen=tools_seen, shadows=shadows)
        if not await self._prove(record, proof):
            return
        focus = [str(t) for t in spec.get("focus") or [] if str(t) in tools_seen]
        agent, created = await runtime.roster.create(
            name=str(spec.get("name") or ""),
            title=str(spec.get("title") or "")[:120],
            description=description,
            focus=focus,
            provider=provider,
            # Made on the loop's initiative: it asks before it acts, until the
            # person chooses otherwise on its card.
            approval_mode="ask",
        )
        if not created:
            await self._fail(record, f"the name {agent.name!r} belongs to an existing agent")
            return
        payload = {
            "type": "agent",
            "id": agent.agent_id,
            "agent_id": agent.agent_id,
            "name": agent.name,
        }
        await self._live(record, payload, payload, f"agent:{agent.agent_id}")

    # ------------------------------------------------------------ undo, dormant, restore

    async def undo(self, record: BuildRecord) -> None:
        """Remove what the build created (the registered undoer for every kind here)."""
        payload = dict(record.undo or record.artefact)
        kind = str(payload.get("type") or record.kind.value)
        if kind == "memory":
            await asyncio.to_thread(self._remove_memory, payload)
        elif kind == "skill":
            await asyncio.to_thread(self._remove_skill, record.id, payload)
        elif kind == "routine":
            await self._remove_routine(payload)
        elif kind == "agent":
            runtime = await self.env.society() if self.env.society is not None else None
            if runtime is not None and payload.get("agent_id"):
                await runtime.roster.archive(str(payload["agent_id"]))
        await asyncio.to_thread(self.store.unbind_build, record.id)

    async def dormant(self, record: BuildRecord) -> None:
        """An archived build stops working but stays restorable."""
        await self._sleep(record, True)

    async def restore(self, record: BuildRecord) -> None:
        await self._sleep(record, False)

    async def _sleep(self, record: BuildRecord, sleeping: bool) -> None:
        flag = f"dormant:{record.id}"
        lock = self._sleep_locks.setdefault(record.id, asyncio.Lock())
        async with lock:
            if (await asyncio.to_thread(self.store.get_meta, flag) == "1") == sleeping:
                return
            try:
                await self._switch(record, sleeping)
            except Exception:  # noqa: BLE001 - not applied; maintenance tries again
                log.warning(
                    "self_build: could not %s %s",
                    "archive" if sleeping else "restore",
                    record.id,
                    exc_info=True,
                )
                return
            await asyncio.to_thread(self.store.set_meta, flag, "1" if sleeping else "0")

    def sleeping(self, build_id: str) -> bool:
        return self.store.get_meta(f"dormant:{build_id}") == "1"

    async def _switch(self, record: BuildRecord, sleeping: bool) -> None:
        payload = dict(record.artefact)
        kind = str(payload.get("type") or "")
        if kind == "memory":
            if sleeping:
                await asyncio.to_thread(self._remove_memory, payload)
            else:
                await asyncio.to_thread(self._readd_memory, record, payload)
        elif kind == "skill" and payload.get("name"):
            await asyncio.to_thread(self._switch_skill, str(payload["name"]), not sleeping)
        elif kind == "routine" and payload.get("task_id"):
            scheduler = self.env.scheduler()
            if scheduler is None:
                raise Waiting("the scheduler is not running")
            task_id = str(payload["task_id"])
            await (scheduler.pause(task_id) if sleeping else scheduler.resume(task_id))
        elif kind == "agent" and payload.get("agent_id"):
            from dodaios.society.events import AgentState

            runtime = await self.env.society() if self.env.society is not None else None
            if runtime is None:
                raise Waiting("the society is not running")
            state = AgentState.PAUSED if sleeping else AgentState.ACTIVE
            await runtime.roster.update(str(payload["agent_id"]), {"state": state})

    def _remove_memory(self, payload: dict[str, Any]) -> None:
        notebook = self.env.notebook()
        if notebook is None:
            return
        target = str(payload.get("target") or "memory")
        text = str(payload.get("text") or "")
        entry_id = _entry_id(notebook, target, text) or str(payload.get("entry_id") or "")
        current = {e.id: e.text for e in notebook.entries().get(target, [])}
        if entry_id not in current:
            return  # already gone
        if current[entry_id] != text:
            log.info("self_build: memory entry %s was edited by the person; kept", entry_id)
            return
        notebook.apply(
            target=target,
            operation="remove",
            entry_id=entry_id,
            expected=text,
            source="self_build: undone",
        )

    def _readd_memory(self, record: BuildRecord, payload: dict[str, Any]) -> None:
        notebook = self.env.notebook()
        if notebook is None:
            return
        notebook.apply(
            target=str(payload.get("target") or "memory"),
            operation="add",
            text=str(payload.get("text") or ""),
            origin="self_build",
            source=f"self_build:{record.id} restored",
        )

    def _remove_skill(self, build_id: str, payload: dict[str, Any]) -> None:
        folder = Path(str(payload.get("path") or ""))
        registry = self.env.skill_registry()
        if folder.is_dir() and (folder / "SKILL.md").is_file():
            # Moved aside, never deleted: an undone build is still inspectable.
            keep = self.env.data_dir / "self_build" / "removed" / build_id
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(keep, ignore_errors=True)
            shutil.move(str(folder), str(keep))
        if registry is not None:
            registry.reload_sync()

    def _switch_skill(self, name: str, on: bool) -> None:
        if self.env.set_skill_on is not None:
            self.env.set_skill_on(name, on)
        else:
            from dodaios.skills.prefs import set_state

            set_state(name, on)
        registry = self.env.skill_registry()
        if registry is not None:
            registry.reload_sync()

    async def _remove_routine(self, payload: dict[str, Any]) -> None:
        task_id = str(payload.get("task_id") or "")
        store, scheduler = self.env.task_store(), self.env.scheduler()
        if not task_id or store is None:
            return
        if scheduler is not None:
            try:
                await scheduler.cancel_task(task_id)
            except (KeyError, ValueError):
                log.info("self_build: routine %s was already gone", task_id)
        await store.delete(task_id)


# ------------------------------------------------------------------ helpers


def _memory_path(notebook: Any, target: str) -> str:
    """The notebook file an entry lives in, relative to the vault (the badge's join key)."""
    path = Path(notebook.paths()[target])
    vault = Path(getattr(notebook, "_vault", path.parent))
    try:
        return path.relative_to(vault).as_posix()
    except ValueError:  # a notebook outside the vault: its full path is the key
        return path.as_posix()


def _entry_id(notebook: Any, target: str, text: str) -> str:
    for entry in notebook.entries().get(target, []):
        if entry.text == text:
            return str(entry.id)
    return ""


_PHRASE_WORD: Final = re.compile(r"[^\W_]+", re.UNICODE)


def voice_pattern(phrase: str) -> str:
    """A trigger regex that matches the phrase's words in order, any spacing."""
    words = _PHRASE_WORD.findall(phrase or "")
    if not words:
        return ""
    gap = chr(92) + "W+"
    edge = chr(92) + "b"
    return edge + gap.join(re.escape(w.casefold()) for w in words) + edge


def skill_draft(spec: dict[str, Any], need: Need) -> dict[str, Any]:
    """The creator draft for a self-built skill: voice triggers from the person's words."""
    tools_seen = {tool for t in need.turns for tool in t.tools}
    triggers: list[dict[str, Any]] = []
    for phrase in list(spec.get("triggers") or [])[:3]:
        pattern = voice_pattern(str(phrase))
        if pattern and len(pattern) <= 200 and len(stems(str(phrase))) >= 1:
            triggers.append({"type": "voice", "pattern": pattern})
    return {
        "name": " ".join(str(spec.get("name") or "").split())[:80],
        "description": " ".join(str(spec.get("description") or "").split())[:400],
        "category": "general",
        "tags": [PROVENANCE],
        "triggers": triggers,
        "requires_tools": [
            str(t) for t in spec.get("requires_tools") or [] if str(t) in tools_seen
        ],
        "risk_policy": {"default_tier": "ask"},
        "body": str(spec.get("body") or "").strip(),
    }


def evidence_turns(record: BuildRecord, store: SignalStore) -> list[TurnRow]:
    ids = []
    for line in record.evidence:
        head = line.split(" ", 1)[0]
        if head.startswith("turn:") and head[5:].isdigit():
            ids.append(int(head[5:]))
    return store.turns_by_id(ids)
