"""The trigger intake: stage 1, then the model on candidates, then the accept mode.

Accept modes: ``off`` drops everything, ``observe`` (the default) decides but
never acts or writes to the person and only records "would have done X because
policy Y", ``auto`` carries decisions out. The owner can promote one policy to
``auto`` while the install keeps observing.

Everything that touches the outside world is injected, so the rules here stay
testable and the seat can only be one the caller proved may run in the
background (a subscription or a local model, never a metered key).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from .event import AGENT_SCOPE_PREFIX, TriggerEvent
from .filter import CANDIDATE, Stage1, _listed
from .policy import Verdict, build_prompt, parse
from .settings import Policy, TriggerSettings
from .subscriptions import (
    Subscription,
    SubscriptionStore,
    delivery_text,
    make_mandate,
    mandate_problem,
)

log = logging.getLogger(__name__)

META_SETTINGS: Final[str] = "lead.triggers.settings"
META_STATE: Final[str] = "lead.triggers.state"
DELIVERED: Final[str] = "delivered"
AGENT_MAIL_POLICY_ID: Final[str] = "agent-mail"
AGENT_MAIL_POLICY_TEXT: Final[str] = (
    "Mail an allow-listed sender wrote to your own address is a request to you: do what it asks."
)
BATCH: Final[int] = 25
MAX_PENDING: Final[int] = 200
MAX_LOG: Final[int] = 200
MAX_NOTES: Final[int] = 50
PENDING_TTL_S: Final[float] = 24 * 3600.0
NOTICE_TTL_S: Final[float] = 24 * 3600.0

#: ``(prompt) -> model text``, or ``None`` while no subscription / local seat can answer.
Seat = Callable[[str], Awaitable[str | None]]
#: ``(event, policy, reason) -> job reference`` through the existing delegation path.
Starter = Callable[[TriggerEvent, Policy, str], Awaitable[str]]
#: ``(decision record) -> None``: writes the person one notice.
Notifier = Callable[[dict[str, Any]], Awaitable[None]]
#: ``(subscription, event, message) -> outcome``: hands the event to the owning job through the
#: kind's own message path. Outcomes: ``delivered``, ``gone`` (the job ended), ``unsupported``,
#: ``busy``, ``failed``. No model is involved.
Deliverer = Callable[[Subscription, TriggerEvent, str], Awaitable[str]]
#: ``(subscription) -> True`` while the owner's stop hold blocks work for this job.
HoldCheck = Callable[[Subscription], bool]


class MetaStore(Protocol):
    async def get_meta(self, key: str, default: str = "") -> str: ...
    async def set_meta(self, key: str, value: str) -> None: ...


def _summary(event: TriggerEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "source": event.source,
        "scope": event.scope,
        "sender": event.sender,
        "thread_key": event.thread_key,
        "summary": event.summary,
        "raw_ref": event.raw_ref,
    }


class TriggerService:
    def __init__(
        self,
        store: MetaStore,
        *,
        seat: Seat,
        starter: Starter,
        notifier: Notifier,
        quiet: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.time,
        batch_window_s: float = 3.0,
        retry_s: float = 300.0,
        subscriptions: SubscriptionStore | None = None,
        deliverer: Deliverer | None = None,
        hold: HoldCheck = lambda _sub: False,
        preparer: Any | None = None,
    ) -> None:
        self._store = store
        #: The lead's own mail address as of the last settings read (for sync callers).
        self.agent_address = ""
        self._seat, self._starter, self._notifier = seat, starter, notifier
        self._quiet, self._clock = quiet, clock
        self._batch_window_s, self._retry_s = batch_window_s, retry_s
        self._subs, self._deliverer, self._hold = subscriptions, deliverer, hold
        self._preparer = preparer
        self._stage1 = Stage1(clock)
        self._state: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task[None] | None = None

    @property
    def preparer(self) -> Any | None:
        return self._preparer

    # ------------------------------------------------------------ persistence

    async def settings(self) -> TriggerSettings:
        try:
            raw = await self._store.get_meta(META_SETTINGS, "")
            settings = TriggerSettings.from_dict(json.loads(raw))
        except ValueError:  # nothing saved yet, or unreadable: the defaults
            settings = TriggerSettings()
        self.agent_address = settings.agent_address
        return settings

    async def save_settings(self, settings: TriggerSettings) -> TriggerSettings:
        encoded = json.dumps(settings.to_dict(), ensure_ascii=False)
        await self._store.set_meta(META_SETTINGS, encoded)
        self.agent_address = settings.agent_address
        return settings

    async def _load(self) -> dict[str, Any]:
        if self._state is None:
            try:
                raw = json.loads(await self._store.get_meta(META_STATE, ""))
            except ValueError:  # a fresh install has no state yet
                raw = {}
            raw = raw if isinstance(raw, dict) else {}
            self._state = {
                "counts": dict(raw.get("counts") or {}),
                "pending": list(raw.get("pending") or []),
                "log": list(raw.get("log") or []),
                "notes": list(raw.get("notes") or []),
                "held": list(raw.get("held") or []),
                "notified": dict(raw.get("notified") or {}),
                "agent_seen": list(raw.get("agent_seen") or []),
            }
        return self._state

    async def _save(self) -> None:
        if self._state is not None:
            await self._store.set_meta(META_STATE, json.dumps(self._state, ensure_ascii=False))

    def _count(self, state: dict[str, Any], key: str) -> None:
        state["counts"][key] = int(state["counts"].get(key, 0)) + 1

    # ----------------------------------------------------------------- intake

    async def submit(self, event: TriggerEvent, settings: TriggerSettings | None = None) -> str:
        """Stage 1 for one event; returns ``candidate`` or the reason it was dropped."""
        settings = settings or await self.settings()
        async with self._lock:
            state = await self._load()
            if settings.accept == "off":
                return "off"
            self._count(state, "received")
            owners = self._subs.for_thread(event.source, event.thread_key) if self._subs else []
            verdict = self._stage1.verdict(event, settings, thread_owned=bool(owners))
            if verdict != CANDIDATE:
                self._count(state, f"dropped_{verdict}")
                await self._save()
                return verdict
            if owners and await self._deliver(state, settings, event, owners):
                await self._save()
                return DELIVERED
            self._count(state, "candidates")
            state["pending"].append({"event": event.to_dict(), "queued_at": self._clock()})
            if len(state["pending"]) > MAX_PENDING:
                del state["pending"][0]
                self._count(state, "dropped_overflow")
            await self._save()
        self._arm(self._batch_window_s)
        return CANDIDATE

    async def submit_agent_mail(self, event: TriggerEvent) -> str:
        """Mail that reached the lead's own address.

        From an allow-listed sender it is a request: observing records "would
        have done", ``auto`` starts one lead routine (billing hold and approvals
        apply). From anyone else it is an ordinary candidate, whatever the mail
        source mode says (only ``ignore`` still drops it), so the owner's rules
        decide.
        """
        settings = await self.settings()
        if settings.accept == "off":
            return "off"
        scope = f"{AGENT_SCOPE_PREFIX}{settings.agent_address}"
        if not settings.agent_address or event.scope != scope:
            return "not_agent_mail"
        allowed = settings.agent_senders or settings.self_senders
        if not (event.sender and _listed(event.sender, allowed)):
            rule = settings.rule(event.source)
            if rule.mode == "ignore":
                return await self.submit(event)
            forced = dataclasses.replace(rule, mode="candidate", senders=(), scopes=())
            sources = {**settings.sources, event.source: forced}
            return await self.submit(event, dataclasses.replace(settings, sources=sources))
        async with self._lock:
            state = await self._load()
            self._count(state, "received")
            seen = state.setdefault("agent_seen", [])
            if event.event_id in seen:
                self._count(state, "dropped_duplicate")
                await self._save()
                return "duplicate"
            seen.append(event.event_id)
            del seen[:-500]
            policy = Policy(AGENT_MAIL_POLICY_ID, AGENT_MAIL_POLICY_TEXT, ("mail",), True)
            record: dict[str, Any] = {
                "id": f"d{int(self._clock() * 1000)}{len(state['log'])}",
                "at": self._clock(),
                "action": "act",
                "policy_id": policy.id,
                "policy_text": policy.text,
                "reason": "an allow-listed sender wrote to the assistant's own address",
                "event": _summary(event),
                "mode": "auto" if settings.accept == "auto" else "observe",
                "outcome": "would_have",
            }
            if settings.accept == "auto":
                await self._carry_out(state, Verdict(event, "act", policy.id, record["reason"]),
                                      policy, record)
            self._count(state, "decided_act")
            state["log"].append(record)
            del state["log"][:-MAX_LOG]
            await self._save()
        return "request"

    def _arm(self, delay: float) -> None:
        if self._timer is not None and not self._timer.done():
            return
        try:
            self._timer = asyncio.get_running_loop().create_task(self._run_later(delay))
        except RuntimeError:  # no running loop (sync caller): the next pass picks it up
            self._timer = None

    async def _run_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            waiting = await self.process()
        except Exception:  # noqa: BLE001 - a failed pass retries; intake must not die
            log.warning("lead triggers: pass failed", exc_info=True)
            waiting = True
        if waiting:
            self._timer = None
            self._arm(self._retry_s)

    async def close(self) -> None:
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
            await asyncio.gather(self._timer, return_exceptions=True)
        if self._preparer is not None:
            await self._preparer.close()

    # ---------------------------------------------------------------- stage 2

    async def process(self) -> bool:
        """Decide the waiting candidates, batched. True while anything still waits."""
        settings = await self.settings()
        if self._preparer is not None:
            try:
                await self._preparer.expire()
            except Exception:  # noqa: BLE001 - expiry is housekeeping; the pass goes on
                log.debug("lead triggers: expiry failed", exc_info=True)
        async with self._lock:
            state = await self._load()
            await self._flush_held(state)
            now = self._clock()
            fresh = [p for p in state["pending"] if now - float(p["queued_at"]) < PENDING_TTL_S]
            for _ in range(len(state["pending"]) - len(fresh)):
                self._count(state, "dropped_expired")
            state["pending"] = fresh
            if settings.accept == "off":
                state["pending"] = []
            while state["pending"] and settings.policies:
                batch = state["pending"][:BATCH]
                events = [TriggerEvent.from_dict(p["event"]) for p in batch]
                try:
                    answer = await self._seat(build_prompt(settings.policies, events))
                except Exception:  # noqa: BLE001 - a seat failure waits, never falls back to a key
                    log.info("lead triggers: seat failed, candidates wait", exc_info=True)
                    answer = None
                if answer is None:
                    break
                del state["pending"][: len(batch)]
                for verdict in parse(answer, settings.policies, events):
                    await self._apply(state, settings, verdict)
            if not settings.policies and settings.accept != "off":
                # Candidates without a policy have nothing to match; they are counted, not kept.
                for _ in state["pending"]:
                    self._count(state, "dropped_no_policy")
                state["pending"] = []
            await self._save()
            return bool(state["pending"] or state["held"])

    async def _apply(
        self, state: dict[str, Any], settings: TriggerSettings, verdict: Verdict
    ) -> None:
        self._count(state, "lead_decisions")
        if verdict.action == "ignore":
            self._count(state, "model_ignored")
            return
        policy = settings.policy(verdict.policy_id)
        assert policy is not None  # parse() only keeps verdicts that cite a known policy
        live = settings.accept == "auto" or (settings.accept == "observe" and policy.auto)
        record: dict[str, Any] = {
            "id": f"d{int(self._clock() * 1000)}{len(state['log'])}",
            "at": self._clock(),
            "action": verdict.action,
            "policy_id": policy.id,
            "policy_text": policy.text,
            "reason": verdict.reason,
            "event": _summary(verdict.event),
            "mode": "auto" if live else "observe",
            "outcome": "would_have",
        }
        if live:
            await self._carry_out(state, verdict, policy, record)
        self._count(state, f"decided_{verdict.action}")
        state["log"].append(record)
        del state["log"][:-MAX_LOG]

    async def _carry_out(
        self, state: dict[str, Any], verdict: Verdict, policy: Policy, record: dict[str, Any]
    ) -> None:
        if verdict.action == "note":
            state["notes"].append(
                {"policy_id": policy.id, "summary": verdict.event.summary, "reason": verdict.reason,
                 "sender": verdict.event.sender, "source": verdict.event.source}
            )
            del state["notes"][:-MAX_NOTES]
            record["outcome"] = "noted"
        elif verdict.action == "act":
            # The owner's stop on this trigger policy (or on everything) holds:
            # the decision is recorded, no job starts.
            if self._policy_held(policy.id):
                record["outcome"] = "held_by_owner"
                return
            try:
                job = await self._starter(verdict.event, policy, verdict.reason)
                record["job"] = job
                record["outcome"] = "started"
                self.subscribe(
                    verdict.event, str(job), kind="routine", target=str(job),
                    mandate=make_mandate(verdict.event, origin="trigger", policy_id=policy.id),
                )
            except Exception as exc:  # noqa: BLE001 - recorded; the next event is unaffected
                log.warning("lead triggers: job did not start", exc_info=True)
                record["outcome"], record["error"] = "failed", str(exc)[:200]
        elif verdict.action == "prepare":
            await self._start_prepare(verdict, policy, record)
        else:  # ask
            event = verdict.event
            key = f"{policy.id}:{event.source}:{event.thread_key or event.event_id}"
            if self._notified_recently(state, key):
                record["outcome"] = "duplicate_notice"
            elif self._quiet():
                state["held"].append({"key": key, "record": dict(record)})
                record["outcome"] = "held"
            else:
                await self._notify(state, key, record)

    @staticmethod
    def _policy_held(policy_id: str) -> bool:
        """The owner's stop covers this policy, all triggers (``trigger:*``) or everything."""
        from dodaios.safety.stop_hold import stop_holds

        holds = stop_holds()
        return holds.blocking(trigger="*") is not None or holds.blocking(trigger=policy_id) is not None

    async def _start_prepare(
        self, verdict: Verdict, policy: Policy, record: dict[str, Any]
    ) -> None:
        """Work in advance: runs in the background, result kept for the owner, nothing pushed."""
        if self._policy_held(policy.id):
            record["outcome"] = "held_by_owner"
            return
        if self._preparer is None:
            record["outcome"] = "prepare_unavailable"
            return
        record_id = record["id"]

        async def done(outcome: str) -> None:
            await self._finish_prepare(record_id, outcome)

        try:
            record["outcome"] = await self._preparer.start(
                verdict.event, policy.id, verdict.reason, done
            )
        except Exception as exc:  # noqa: BLE001 - recorded; the next event is unaffected
            log.warning("lead triggers: preparation did not start", exc_info=True)
            record["outcome"], record["error"] = "failed", str(exc)[:200]

    async def _finish_prepare(self, record_id: str, outcome: str) -> None:
        """The background work ended: the decision log shows how (a silent end is only counted)."""
        async with self._lock:
            state = await self._load()
            self._count(state, outcome)
            for entry in state["log"]:
                if entry["id"] == record_id:
                    entry["outcome"] = outcome
            await self._save()

    def _notified_recently(self, state: dict[str, Any], key: str) -> bool:
        now = self._clock()
        state["notified"] = {k: t for k, t in state["notified"].items() if now - t < NOTICE_TTL_S}
        return key in state["notified"]

    async def _notify(self, state: dict[str, Any], key: str, record: dict[str, Any]) -> None:
        try:
            await self._notifier(record)
            record["outcome"] = "asked"
            state["notified"][key] = self._clock()
        except Exception:  # noqa: BLE001 - the decision stays in the log, the notice is lost
            log.warning("lead triggers: notice not written", exc_info=True)
            record["outcome"] = "failed"

    async def _flush_held(self, state: dict[str, Any]) -> None:
        if not state["held"] or self._quiet():
            return
        held, state["held"] = state["held"], []
        for item in held:
            if self._notified_recently(state, item["key"]):
                continue
            await self._notify(state, item["key"], item["record"])
            for entry in state["log"]:
                if entry["id"] == item["record"]["id"]:
                    entry["outcome"] = item["record"]["outcome"]

    # ---------------------------------------------------------- subscriptions

    def subscribe(
        self,
        event: TriggerEvent,
        job_id: str,
        *,
        kind: str = "",
        target: str = "",
        mandate: dict[str, Any] | None = None,
    ) -> bool:
        """A job that started from ``event`` follows the event's thread from now on.

        The mandate is written once, here; a later call for the same job and thread keeps it.
        """
        if self._subs is None or not event.thread_key or not job_id:
            return False
        return self._subs.subscribe(
            event.source, event.thread_key, job_id, kind=kind, target=target,
            mandate=mandate or make_mandate(event, origin="lead"),
        )

    def unsubscribe(self, job_id: str, source: str = "", thread_key: str = "") -> int:
        """Stop delivering to a job (all its threads when none is named). Rows dropped."""
        return self._subs.unsubscribe(job_id, source, thread_key) if self._subs else 0

    def job_ended(self, job_id: str) -> int:
        """The job finished: nothing is delivered to it any more."""
        return self.unsubscribe(job_id)

    async def _deliver(
        self,
        state: dict[str, Any],
        settings: TriggerSettings,
        event: TriggerEvent,
        owners: list[Subscription],
    ) -> bool:
        """Hand the event to every owning job, by code. True when at least one took it."""
        if self._deliverer is None or self._subs is None:
            return False
        taken: list[str] = []
        for sub in owners:
            if self._hold(sub):
                self._count(state, "delivery_held")
                self._count(state, "held_by_owner")
                continue
            problem = mandate_problem(sub.mandate, event, settings)
            if problem:
                self._count(state, f"delivery_blocked_{problem}")
                continue
            try:
                outcome = await self._deliverer(sub, event, delivery_text(event, sub))
            except Exception:  # noqa: BLE001 - a failed hand-over goes to the lead instead
                log.warning("lead triggers: direct delivery failed", exc_info=True)
                outcome = "failed"
            if outcome == "gone":
                self._subs.unsubscribe(sub.job_id, sub.source, sub.thread_key)
                self._count(state, "subscription_ended")
            elif outcome == DELIVERED:
                self._subs.record_delivery(event, sub.job_id)
                self._count(state, "direct_deliveries")
                taken.append(sub.job_id)
            else:
                self._count(state, f"delivery_{outcome}")
        if taken:
            state["log"].append({
                "id": f"d{int(self._clock() * 1000)}{len(state['log'])}",
                "at": self._clock(), "action": "deliver", "policy_id": "", "policy_text": "",
                "reason": "the thread belongs to a running job", "event": _summary(event),
                "mode": "code", "outcome": DELIVERED, "jobs": taken,
            })
            del state["log"][:-MAX_LOG]
        return bool(taken)

    async def handback(
        self, event_id: str, reason: str = "", job_id: str = "", unsubscribe: bool = False
    ) -> str:
        """A job returns an event it was handed: the lead sees it as a normal candidate.

        Returns ``handed_back``, or ``unknown_event`` when that event was never delivered to
        the job. The event skips subscriptions (it cannot bounce back to its owner).
        """
        found = self._subs.delivery(event_id, job_id) if self._subs else None
        if found is None:
            return "unknown_event"
        owner, event = found
        async with self._lock:
            state = await self._load()
            state["pending"].append({
                "event": event.to_dict(), "queued_at": self._clock(),
                "handed_back_by": owner, "handback_reason": " ".join(reason.split())[:200],
            })
            del state["pending"][:-MAX_PENDING]
            self._count(state, "handed_back")
            await self._save()
        if unsubscribe and self._subs:
            self._subs.unsubscribe(owner, event.source, event.thread_key)
        self._arm(self._batch_window_s)
        return "handed_back"

    # ------------------------------------------------------------------ views

    async def view(self) -> dict[str, Any]:
        """What the app shows: settings, drop counts, waiting count and the decision log."""
        settings = await self.settings()
        async with self._lock:
            state = await self._load()
            prepared = self._preparer.items.stats() if self._preparer is not None else None
            return {
                "prepared": prepared,
                "settings": settings.to_dict(),
                "counts": dict(state["counts"]),
                "waiting": len(state["pending"]),
                "log": list(reversed(state["log"])),
                "notes": len(state["notes"]),
                "delivery": {
                    "direct": int(state["counts"].get("direct_deliveries", 0)),
                    "lead_decisions": int(state["counts"].get("lead_decisions", 0)),
                    "handed_back": int(state["counts"].get("handed_back", 0)),
                },
            }

    async def promote(self, policy_id: str) -> TriggerSettings | None:
        """Let one policy act while the install keeps observing; ``None`` for an unknown id."""
        settings = await self.settings()
        policy = settings.policy(policy_id)
        if policy is None:
            return None
        policies = tuple(Policy(p.id, p.text, p.sources, True) if p.id == policy_id else p
                         for p in settings.policies)
        return await self.save_settings(dataclasses.replace(settings, policies=policies))

    async def take_notes(self) -> list[dict[str, Any]]:
        """The notes for the next brief; they are handed out once."""
        async with self._lock:
            state = await self._load()
            notes, state["notes"] = state["notes"], []
            if notes:
                await self._save()
            return notes
