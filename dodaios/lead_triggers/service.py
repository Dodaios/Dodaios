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
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from .event import TriggerEvent
from .filter import CANDIDATE, Stage1
from .policy import Verdict, build_prompt, parse
from .settings import Policy, TriggerSettings

log = logging.getLogger(__name__)

META_SETTINGS: Final[str] = "lead.triggers.settings"
META_STATE: Final[str] = "lead.triggers.state"
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
    ) -> None:
        self._store = store
        self._seat, self._starter, self._notifier = seat, starter, notifier
        self._quiet, self._clock = quiet, clock
        self._batch_window_s, self._retry_s = batch_window_s, retry_s
        self._stage1 = Stage1(clock)
        self._state: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ persistence

    async def settings(self) -> TriggerSettings:
        try:
            raw = await self._store.get_meta(META_SETTINGS, "")
            return TriggerSettings.from_dict(json.loads(raw))
        except ValueError:  # nothing saved yet, or unreadable: the defaults
            return TriggerSettings()

    async def save_settings(self, settings: TriggerSettings) -> TriggerSettings:
        encoded = json.dumps(settings.to_dict(), ensure_ascii=False)
        await self._store.set_meta(META_SETTINGS, encoded)
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
            }
        return self._state

    async def _save(self) -> None:
        if self._state is not None:
            await self._store.set_meta(META_STATE, json.dumps(self._state, ensure_ascii=False))

    def _count(self, state: dict[str, Any], key: str) -> None:
        state["counts"][key] = int(state["counts"].get(key, 0)) + 1

    # ----------------------------------------------------------------- intake

    async def submit(self, event: TriggerEvent) -> str:
        """Stage 1 for one event; returns ``candidate`` or the reason it was dropped."""
        settings = await self.settings()
        async with self._lock:
            state = await self._load()
            if settings.accept == "off":
                return "off"
            self._count(state, "received")
            verdict = self._stage1.verdict(event, settings)
            if verdict != CANDIDATE:
                self._count(state, f"dropped_{verdict}")
                await self._save()
                return verdict
            self._count(state, "candidates")
            state["pending"].append({"event": event.to_dict(), "queued_at": self._clock()})
            if len(state["pending"]) > MAX_PENDING:
                del state["pending"][0]
                self._count(state, "dropped_overflow")
            await self._save()
        self._arm(self._batch_window_s)
        return CANDIDATE

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

    # ---------------------------------------------------------------- stage 2

    async def process(self) -> bool:
        """Decide the waiting candidates, batched. True while anything still waits."""
        settings = await self.settings()
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
            from dodaios.safety.stop_hold import stop_holds

            if stop_holds().blocking(trigger=policy.id) is not None:
                record["outcome"] = "held_by_owner"
                return
            try:
                record["job"] = await self._starter(verdict.event, policy, verdict.reason)
                record["outcome"] = "started"
            except Exception as exc:  # noqa: BLE001 - recorded; the next event is unaffected
                log.warning("lead triggers: job did not start", exc_info=True)
                record["outcome"], record["error"] = "failed", str(exc)[:200]
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

    # ------------------------------------------------------------------ views

    async def view(self) -> dict[str, Any]:
        """What the app shows: settings, drop counts, waiting count and the decision log."""
        settings = await self.settings()
        async with self._lock:
            state = await self._load()
            return {
                "settings": settings.to_dict(),
                "counts": dict(state["counts"]),
                "waiting": len(state["pending"]),
                "log": list(reversed(state["log"])),
                "notes": len(state["notes"]),
            }

    async def promote(self, policy_id: str) -> TriggerSettings | None:
        """Let one policy act while the install keeps observing; ``None`` for an unknown id."""
        settings = await self.settings()
        policy = settings.policy(policy_id)
        if policy is None:
            return None
        policies = tuple(Policy(p.id, p.text, p.sources, True) if p.id == policy_id else p
                         for p in settings.policies)
        return await self.save_settings(TriggerSettings(
            settings.accept, settings.sources, policies, settings.self_senders,
            settings.rate_per_minute, settings.dedupe_window_s))

    async def take_notes(self) -> list[dict[str, Any]]:
        """The notes for the next brief; they are handed out once."""
        async with self._lock:
            state = await self._load()
            notes, state["notes"] = state["notes"], []
            if notes:
                await self._save()
            return notes
