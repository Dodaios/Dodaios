"""The loop: collect finished turns, keep what matters, cheaply and reliably.

What it costs:

* nothing for an ordinary turn. A deterministic filter
  (:mod:`dodaios.memory.learning.signals`) marks the few turns in which the
  user talks about themselves, a preference, a correction or a plan; a
  conversation without such a turn is never shown to a model;
* nothing for "remember that X": an explicit request with its content is
  saved at once in the user's own words, without a model, so it can never be
  lost to a provider failure;
* one small model call per conversation that did hold a signal, when the
  call ends (``VoiceSessionEnded``), after ``idle_review_seconds`` of quiet,
  or after ``review_every_turns`` turns in a very long conversation. A bare
  "remember that" (pointing at something said before) is reviewed at once.

Voice turns arrive as ``VoiceTurnCompleted`` (every voice engine publishes it).
Typed turns on Jarvis' own chat arrive through the chat surface's completion
hook (:meth:`JarvisLearningLoop.chat_turn_completed`). Society agents have
their own loop and never feed this one.

Turns stay pending until a review has really looked at them: a failed or
cancelled review hands them back, and a failing reviewer is retried after a
growing pause, never on every turn. The reviewer asks the Jarvis lead's
provider, on its subscription when one is signed in (``review.seat_choices``),
so after four failed reviews in a row the turns are dropped with one log line,
unless the cause is a configuration fault (a spent usage limit, a rejected key,
a signed-out login): then the turns stay pending, and ONE written notice
(``memory_health``) tells the person which seat stopped and how to fix it.
Every review and merge call leaves a ``review`` line in the learning ledger
naming its seat, its billing mode and how it ended (``answered``, ``failed``,
``dropped``). Nothing here runs on the voice path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.memory.learning.notebook import JarvisNotebook
from dodaios.memory.learning.review import Proposal, Turn, build_prompt, excerpt, validate
from dodaios.memory.learning.signals import has_signal, is_correction

log = logging.getLogger(__name__)

Reviewer = Callable[[str], Awaitable[list[dict[str, Any]] | None]]

#: Turns kept per conversation (enough for any review window).
_KEEP_TURNS: Final[int] = 40
#: Signal turns shown to one review; a conversation rarely has more.
_MAX_SIGNAL_TURNS: Final[int] = 8
#: Conversations tracked at once; the least recently active one goes beyond this.
_MAX_CONVERSATIONS: Final[int] = 32
#: Pause after a failed review, doubled per consecutive failure up to the cap.
_BACKOFF_S: Final[float] = 60.0
_BACKOFF_CAP_S: Final[float] = 3_600.0
#: Consecutive failed reviews (the first plus three retries after the pause)
#: after which the turns are dropped. The reviewer asks only the Jarvis
#: provider's seats, so a seat that keeps failing must not keep its turns forever.
_MAX_FAILURES: Final[int] = 4
#: Memory upkeep: first run after boot settles, then an hourly check whether
#: the daily tidy-up is due (the pass itself runs at most once a day).
_UPKEEP_FIRST_DELAY_S: Final[float] = 120.0
_UPKEEP_INTERVAL_S: Final[float] = 3_600.0
#: How often queued conversation episodes are picked up.
_UPKEEP_TICK_S: Final[float] = 600.0


_TRACE_NOTE_CHARS: Final[int] = 100
_TRACE_MAX_CHARS: Final[int] = 400


def tool_trace(events: list[dict[str, Any]]) -> str:
    """A factual line about a turn that is worth a lesson, else ``""``.

    Two cases, found without a model: a tool failed and a later tool call
    succeeded (the assistant worked around the failure), and the owner denied
    an approval. The review judges whether any of it is reusable.
    """
    names: dict[str, str] = {}
    results: list[tuple[str, bool, str]] = []
    denied: list[str] = []
    asked: dict[str, str] = {}
    for event in events:
        payload = event.get("payload") or {}
        kind = event.get("kind")
        call_id = str(payload.get("call_id") or "")
        if kind == "tool_call" and call_id:
            names[call_id] = str(payload.get("name") or "tool")
        elif kind == "tool_result":
            note = " ".join(str(payload.get("output") or "").split())[:_TRACE_NOTE_CHARS]
            results.append((names.get(call_id, "tool"), bool(payload.get("is_error")), note))
        elif kind == "approval_required":
            asked[str(payload.get("approval_id") or "")] = str(payload.get("name") or "tool")
        elif kind == "approval_resolved" and payload.get("decision") == "deny":
            denied.append(asked.get(str(payload.get("approval_id") or ""), "an action"))
    parts: list[str] = []
    first_failure = next((i for i, (_, failed, _) in enumerate(results) if failed), None)
    if first_failure is not None and results and not results[-1][1]:
        failed = [f"{name} ({note})" for name, bad, note in results if bad]
        worked = [name for name, bad, _ in results[first_failure:] if not bad]
        parts.append(f"failed: {'; '.join(failed[:3])}; then worked: {', '.join(worked[:3])}")
    if denied:
        parts.append(f"the owner denied approval for: {', '.join(denied[:3])}")
    return " | ".join(parts)[:_TRACE_MAX_CHARS]


def _seat_of(reviewer: Any) -> dict[str, str]:
    """Seat, runner and billing of the reviewer's last call, for the ledger."""
    fields = getattr(getattr(reviewer, "last_choice", None), "ledger_fields", None)
    return fields() if callable(fields) else {}


@dataclass
class _Conversation:
    turns: list[Turn] = field(default_factory=list)
    #: Parallel to ``turns``: did the signal filter pick this turn?
    signals: list[bool] = field(default_factory=list)
    unreviewed: int = 0
    timer: asyncio.TimerHandle | None = None
    last_seen: float = 0.0
    failures: int = 0
    retry_at: float = 0.0
    reviewing: bool = False

    def picked(self) -> list[int]:
        """Indices of the unreviewed turns the signal filter picked."""
        start = len(self.turns) - self.unreviewed
        return [i for i in range(start, len(self.turns)) if self.signals[i]]


class JarvisLearningLoop:
    """See the module docstring."""

    def __init__(
        self,
        notebook: JarvisNotebook,
        reviewer: Reviewer,
        *,
        review_every_turns: int = 30,
        idle_review_seconds: float = 300.0,
        compactor: Reviewer | None = None,
        vault_reviewer: Reviewer | None = None,
        upkeep_reviewer: Reviewer | None = None,
        episode_reviewer: Reviewer | None = None,
    ) -> None:
        self.notebook = notebook
        self._reviewer = reviewer
        #: Reviews write into the memory vault (ADR-0044) while one runs.
        self._vault_reviewer = vault_reviewer
        #: Merges near-duplicate memories once a day (vault.consolidate).
        self._upkeep_reviewer = upkeep_reviewer
        #: Turns compacted conversation summaries into episodes (vault.episodes).
        self._episode_reviewer = episode_reviewer
        self._compactor = compactor
        self._every = max(1, int(review_every_turns))
        self._idle_s = max(0.0, float(idle_review_seconds))
        self._conversations: dict[str, _Conversation] = {}
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._subscriptions: list[tuple[type[Any], Any]] = []
        self._bus: Any = None
        self._stopped = False
        #: Why the latest unanswered review failed (read by ``review``).
        self._last_failure: Any = None
        #: The configuration fault already written up in the conversation
        #: (cause, provider, model); ``None`` after a recovery.
        self._health_key: tuple[str, str, str] | None = None
        #: Model calls made (diagnostics and tests).
        self.review_calls = 0
        self.compact_calls = 0

    # ── wiring ───────────────────────────────────────────────────────────

    def start(self, bus: Any) -> None:
        from dodaios.core.events import VoiceSessionEnded, VoiceTurnCompleted

        if self._bus is not None:
            return
        self._bus = bus
        self._stopped = False
        for event_type, handler in (
            (VoiceTurnCompleted, self._on_voice_turn),
            (VoiceSessionEnded, self._on_voice_ended),
        ):
            bus.subscribe(event_type, handler)
            self._subscriptions.append((event_type, handler))
        self._spawn(self._warm_and_compact(), name="jarvis-learning-warm")
        if self._vault_reviewer is not None:
            self._spawn(self._memory_upkeep(), name="memory-vault-upkeep")

    async def _memory_upkeep(self) -> None:
        """Background vault upkeep: learn once from the old chats, tidy up daily."""
        from dodaios.core.config import DATA_DIR
        from dodaios.memory.vault import backfill, calendar_sync, consolidate, episodes
        from dodaios.memory.vault import runtime as vault_runtime

        await asyncio.sleep(_UPKEEP_FIRST_DELAY_S)
        vault = vault_runtime.active()
        if vault is not None and self._vault_reviewer is not None and not self._stopped:
            await backfill.run_once(vault, self._vault_reviewer, DATA_DIR)
        last_hourly = 0.0
        while not self._stopped:
            vault = vault_runtime.active()
            if vault is not None and self._episode_reviewer is not None:
                await episodes.process(vault, self._episode_reviewer)
            if vault is not None and time.monotonic() - last_hourly >= _UPKEEP_INTERVAL_S:
                last_hourly = time.monotonic()
                if self._upkeep_reviewer is not None:
                    from dodaios.agent_chat.lead import post_memory_tidy

                    await consolidate.run_if_due(vault, self._upkeep_reviewer, post_memory_tidy)
                if not vault_runtime.learning_paused():
                    await calendar_sync.sync(vault)
            await asyncio.sleep(_UPKEEP_TICK_S)

    async def _warm_and_compact(self) -> None:
        await asyncio.to_thread(self.notebook.warm)
        await self.compact()

    async def stop(self, *, timeout_s: float = 5.0) -> None:
        """Detach and let running work finish briefly; explicit requests are already saved."""
        self._stopped = True
        for event_type, handler in self._subscriptions:
            try:
                self._bus.unsubscribe(event_type, handler)
            except Exception:  # noqa: BLE001 — teardown reports, never raises
                log.debug("learning: could not detach %s", event_type.__name__, exc_info=True)
        self._subscriptions.clear()
        self._bus = None
        for conversation in self._conversations.values():
            if conversation.timer is not None:
                conversation.timer.cancel()
                conversation.timer = None
        tasks = tuple(self._tasks)
        if tasks:
            # Let a deterministic save that is already writing finish; a model
            # review still waiting on its provider is cancelled.
            _, pending = await asyncio.wait(tasks, timeout=min(1.0, timeout_s))
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=timeout_s)

    def _spawn(self, work: Awaitable[Any], *, name: str) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._guarded(work), name=name)
        except RuntimeError:  # no event loop (shutdown / sync caller): drop the work cleanly
            if asyncio.iscoroutine(work):
                work.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _guarded(work: Awaitable[Any]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — background learning must never surface
            log.warning("learning: background work failed", exc_info=True)

    # ── inputs ───────────────────────────────────────────────────────────

    @staticmethod
    def _voice_key(event: Any) -> str:
        session = str(getattr(event, "session_id", "") or "").strip()
        return "voice:" + (session or "unknown")

    async def _on_voice_turn(self, event: Any) -> None:
        tools = tuple(str(t) for t in (getattr(event, "tool_calls", ()) or ()))
        self.record(
            self._voice_key(event),
            Turn(
                user=str(getattr(event, "user_text", "") or "").strip(),
                assistant=str(getattr(event, "jarvis_text", "") or "").strip(),
                channel="voice",
                tools=tools,
            ),
        )

    async def _on_voice_ended(self, event: Any) -> None:
        self._schedule(self._voice_key(event), reason="call ended", drop=True, force=True)

    async def chat_turn_completed(self, session: Any, completion: Any) -> None:
        """Jarvis chat surface hook: one typed turn with its tool names."""
        from dodaios.society.memory_intent import user_evidence

        if self._stopped:
            return
        turn = getattr(completion, "turn", None)
        if turn is not None and not getattr(turn, "direct_user", True):
            return  # Routine and agent-injected turns are not the user speaking.
        try:
            events = json.loads(completion.events_json)
        except (TypeError, ValueError):
            log.debug("learning: unreadable chat completion", exc_info=True)
            return
        # What the person typed, never attachments or transport scaffolding:
        # only those words may later serve as evidence.
        messages = [e for e in events if e.get("kind") == "user_message"]
        typed = [user_evidence(e) for e in messages]
        user = typed[-1].strip() if typed else ""
        try:
            seq = int(messages[-1].get("seq") or 0) if messages else 0
        except (TypeError, ValueError):
            seq = 0  # An unnumbered event: the memory links by its quote instead.
        if not user:
            user = user_evidence({"payload": {"text": getattr(turn, "user_text", "")}}).strip()
        answer = "\n".join(
            str((e.get("payload") or {}).get("text") or "")
            for e in events
            if e.get("kind") == "assistant_text"
        ).strip()
        tools = tuple(
            str((e.get("payload") or {}).get("name") or "")
            for e in events
            if e.get("kind") == "tool_call"
        )
        session_id = str(getattr(session, "session_id", "") or "")
        trace = tool_trace(events)
        self.record(
            "chat:" + (session_id or "unknown"),
            Turn(
                user=user,
                assistant=answer,
                channel="chat",
                tools=tuple(t for t in tools if t),
                session_id=session_id,
                turn_id=str(getattr(turn, "turn_id", "") or ""),
                seq=seq,
                trace=trace,
            ),
        )

    def record(self, key: str, turn: Turn) -> None:
        """File one finished turn and fire whichever trigger it completes."""
        if not turn.user or self._stopped:
            return
        from dodaios.society.memory_intent import requested_memory

        conversation = self._conversations.get(key)
        if conversation is None:
            self._make_room()
            conversation = self._conversations[key] = _Conversation()
        conversation.last_seen = time.monotonic()
        request = requested_memory(turn.user)
        if request is not None and "remember" in turn.tools:
            # The conversation model already saved it through the remember tool.
            request = None
        # A self-contained request is saved right here; only a bare "remember
        # that" still needs the model to see what "that" was.
        signal = request == "" or (request is None and (has_signal(turn.user) or bool(turn.trace)))
        if is_correction(turn.user):
            self._spawn(self._count_repeat(turn.user), name="jarvis-learning-repeat")
        conversation.turns.append(turn)
        conversation.signals.append(signal)
        del conversation.turns[:-_KEEP_TURNS]
        del conversation.signals[:-_KEEP_TURNS]
        conversation.unreviewed = min(conversation.unreviewed + 1, _KEEP_TURNS)
        if request == "" and len(conversation.turns) > 1:
            # "Remember that" points at what was said just before: show it too.
            conversation.signals[-2] = True
            conversation.unreviewed = max(conversation.unreviewed, 2)
        if request:
            self._spawn(
                self._remember(turn.user, request, turn.anchor()), name="jarvis-learning-remember"
            )
        if request == "":
            self._schedule(key, reason="remember request", force=True)
        elif conversation.unreviewed >= self._every:
            self._schedule(key, reason=f"{conversation.unreviewed} turns")
        else:
            self._arm_idle(key, conversation)

    async def _count_repeat(self, correction: str) -> None:
        """Count a correction that says a stored lesson again (free, no model)."""
        from dodaios.memory.vault import lessons
        from dodaios.memory.vault import runtime as vault_runtime

        vault = vault_runtime.active()
        if vault is None or vault_runtime.learning_paused():
            return
        repeated = await asyncio.to_thread(lessons.note_repeat, vault, correction)
        if repeated is not None:
            vault_runtime.changed()

    def _make_room(self) -> None:
        """Past the cap, review and forget the least recently active conversation."""
        idle = [key for key, c in self._conversations.items() if not c.reviewing]
        if len(self._conversations) < _MAX_CONVERSATIONS or not idle:
            return
        oldest = min(idle, key=lambda key: self._conversations[key].last_seen)
        self._schedule(oldest, reason="evicted", drop=True, force=True)

    # ── triggers ─────────────────────────────────────────────────────────

    def _arm_idle(self, key: str, conversation: _Conversation, delay: float | None = None) -> None:
        if conversation.timer is not None:
            conversation.timer.cancel()
            conversation.timer = None
        wait = self._idle_s if delay is None else delay
        if not wait or self._stopped:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no event loop: no idle timer to arm, nothing lost
            return
        conversation.timer = loop.call_later(
            wait, lambda: self._schedule(key, reason="quiet conversation", force=True)
        )

    def _schedule(self, key: str, *, reason: str, drop: bool = False, force: bool = False) -> None:
        """Start a background review; ``drop`` forgets the conversation after it.

        A conversation whose unreviewed turns hold no signal is settled here,
        without a task and without a model call. ``force`` ignores the pause
        after a failed review (a call ended, the conversation went quiet).
        """
        conversation = self._conversations.get(key)
        if conversation is None or self._stopped:
            return
        if conversation.timer is not None:
            conversation.timer.cancel()
            conversation.timer = None
        if conversation.unreviewed and not conversation.picked() and not conversation.reviewing:
            conversation.unreviewed = 0  # Nothing worth a model call was said.
        if not conversation.unreviewed:
            if drop and not conversation.reviewing:
                self._conversations.pop(key, None)
            return
        if not force and time.monotonic() < conversation.retry_at:
            self._arm_idle(key, conversation, conversation.retry_at - time.monotonic())
            return
        self._spawn(self._review_then(key, reason, drop), name=f"jarvis-learning-{key[:24]}")

    async def _review_then(self, key: str, reason: str, drop: bool) -> None:
        try:
            await self.review(key, reason=reason)
        finally:
            conversation = self._conversations.get(key)
            if drop and conversation is not None:
                if conversation.unreviewed and not self._stopped:
                    # The review failed; keep the turns until the pause is over.
                    self._arm_idle(
                        key, conversation, max(1.0, conversation.retry_at - time.monotonic())
                    )
                elif not conversation.unreviewed:
                    self._conversations.pop(key, None)

    # ── the review ───────────────────────────────────────────────────────

    async def review(self, key: str, *, reason: str = "manual") -> int:
        """Review the picked turns of ``key``; returns the changes written."""
        async with self._lock:  # One writer; a later review sees the earlier result.
            conversation = self._conversations.get(key)
            if conversation is None or not conversation.unreviewed:
                return 0
            count = conversation.unreviewed
            picked = conversation.picked()[-_MAX_SIGNAL_TURNS:]
            if not picked:
                conversation.unreviewed = 0
                return 0
            said = excerpt(conversation.turns, picked)
            # Where each picked line was said, so a memory links back to it.
            anchors = [
                {"user": conversation.turns[i].user, **conversation.turns[i].anchor()}
                for i in picked
            ]
            conversation.unreviewed = 0
            conversation.reviewing = True
            answered = False
            written = 0
            outcome = "failed"
            self._last_failure = None
            try:
                written, answered = await self._review_said(said, reason, anchors)
            finally:
                conversation.reviewing = False
                if answered:
                    outcome = "answered"
                fault = self._last_failure if not answered else None
                #: Only the person can fix a configuration fault (a spent limit,
                #: a rejected key, a signed-out login), so the turns wait for
                #: that instead of being dropped after a few useless retries.
                waiting_on_person = bool(fault is not None and fault.configuration)
                if (
                    not answered
                    and not waiting_on_person
                    and conversation.failures + 1 >= _MAX_FAILURES
                ):
                    # The seat kept failing: give these turns up (turns that
                    # arrived meanwhile stay) and start the count afresh.
                    outcome = "dropped"
                    log.warning(
                        "learning: dropped %d turn(s) of %s after %d failed reviews; "
                        "only the assistant provider's seats are asked",
                        count,
                        key,
                        conversation.failures + 1,
                    )
                    conversation.failures = 0
                    conversation.retry_at = 0.0
                elif not answered:
                    # Hand the turns back for the next attempt, after a pause.
                    conversation.unreviewed = min(conversation.unreviewed + count, _KEEP_TURNS)
                    conversation.failures += 1
                    conversation.retry_at = time.monotonic() + min(
                        _BACKOFF_CAP_S, _BACKOFF_S * 2 ** min(conversation.failures - 1, 12)
                    )
                else:
                    conversation.failures = 0
                    conversation.retry_at = 0.0
            await asyncio.to_thread(
                self.notebook.note_review,
                source=f"review: {reason}",
                outcome=outcome,
                changes=written,
                seat=_seat_of(self._reviewer),
            )
            await self._note_health(answered, self._last_failure)
            if written:
                log.info("learning: %d notebook change(s) from %s", written, key)
                await self._compact_locked()
                await asyncio.to_thread(self.notebook.warm)
            return written

    async def _note_health(self, answered: bool, failure: Any) -> None:
        """Write ONE notice per configuration fault; reset it on recovery.

        Never spoken, never on every failure: again only when the cause (or
        the seat) changes, or after a review answered and a new fault follows.
        """
        if answered:
            self._health_key = None
            return
        if failure is None or not failure.configuration:
            return
        key = (failure.cause, failure.provider, failure.model)
        if key == self._health_key:
            return
        from dodaios.agent_chat.lead import post_memory_health
        from dodaios.memory.learning.review import health_sentence

        log.warning(
            "learning: reviews stopped on %s/%s (%s); turns are kept until it is fixed",
            failure.provider,
            failure.model or "default model",
            failure.cause,
        )
        if await post_memory_health(
            health_sentence(failure), provider=failure.provider, cause=failure.cause
        ):
            self._health_key = key

    async def _review_said(
        self,
        said: list[dict[str, str]],
        reason: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> tuple[int, bool]:
        """``(changes written, a reviewer answered)``; raises only on I/O faults."""
        from dodaios.memory.vault import runtime as vault_runtime

        vault = vault_runtime.active()
        if vault is not None and self._vault_reviewer is not None:
            return await self._review_into_vault(vault, said, reason, anchors)
        entries = await asyncio.to_thread(self.notebook.entries)
        prompt = build_prompt(said, entries=entries, usage=self.notebook.usage(entries))
        log.info("learning: reviewing %d picked turn(s) (%s)", len(said), reason)
        self.review_calls += 1
        try:
            raw = await self._reviewer(prompt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a provider fault is a failed review, retried later
            log.warning("learning: reviewer failed", exc_info=True)
            raw = None
        if raw is None:
            self._last_failure = getattr(self._reviewer, "last_failure", None)
            return 0, False
        seat = _seat_of(self._reviewer)
        # Evidence may come from the picked turns only: nothing else was shown.
        accepted, rejected = validate(
            raw, user_texts=[row["user"] for row in said], entries=entries
        )
        for why in rejected:
            log.info("learning: rejected a proposal — %s", why)
        written = 0
        for proposal in accepted:
            written += await asyncio.to_thread(self._apply_proposal, proposal, reason, seat)
        return written, True

    async def _review_into_vault(
        self,
        vault: Any,
        said: list[dict[str, str]],
        reason: str,
        anchors: list[dict[str, Any]] | None = None,
    ) -> tuple[int, bool]:
        """One reconcile call: what was said against the nearest stored memories."""
        from dodaios.memory.vault import reconcile
        from dodaios.memory.vault import runtime as vault_runtime

        reviewer = self._vault_reviewer
        if reviewer is None:
            return 0, False
        if vault_runtime.learning_paused():
            # The user paused learning: these turns are dropped, never queued for later.
            log.info("learning: paused by the user; %d turn(s) not reviewed", len(said))
            return 0, True
        shown = await asyncio.to_thread(reconcile.nearest, vault, said)
        prompt = reconcile.build_prompt(said, shown)
        log.info("learning: reconciling %d picked turn(s) with the vault (%s)", len(said), reason)
        self.review_calls += 1
        try:
            raw = await reviewer(prompt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a provider fault is a failed review, retried later
            log.warning("learning: vault reviewer failed", exc_info=True)
            raw = None
        if raw is None:
            self._last_failure = getattr(reviewer, "last_failure", None)
            return 0, False
        ops, rejected = reconcile.validate(
            raw, user_texts=[row["user"] for row in said], shown=shown
        )
        for why in rejected:
            log.info("learning: rejected a vault op — %s", why)
        source = {"via": "review", "reason": reason, **_seat_of(reviewer)}
        receipts: list[dict[str, Any]] = []
        written = await asyncio.to_thread(
            reconcile.apply, vault, ops, source=source, receipts=receipts, anchors=anchors
        )
        if written:
            vault_runtime.changed()
        if receipts:
            from dodaios.agent_chat.lead import post_learned

            await post_learned(receipts)
        return written, True

    def _apply_proposal(self, proposal: Proposal, reason: str, seat: dict[str, str]) -> int:
        return self._write(
            seat=seat,
            target=proposal.target,
            operation=proposal.operation,
            text=proposal.text,
            entry_id=proposal.entry_id,
            importance=proposal.importance,
            origin="review",
            evidence=proposal.evidence,
            source=f"review: {reason}",
            expected=proposal.before if proposal.operation != "add" else None,
        )

    def _write(self, **change: Any) -> int:
        try:
            written = self.notebook.apply(**change)
        except (ValueError, OSError) as exc:  # filelock.Timeout is an OSError subclass too
            log.info("learning: could not apply a %s — %s", change.get("operation"), exc)
            return 0
        return 1 if written is not None else 0

    def _keep_request(self, said: str, content: str, anchor: dict[str, Any] | None = None) -> int:
        """Save an explicit remember request in the user's own words, dated.

        A full notebook never refuses it (it merges later); a request the
        remember tool already saved in this conversation is not filed twice.
        While the memory vault runs, the request goes there instead.
        """
        from dodaios.memory.vault import runtime as vault_runtime

        if vault_runtime.active() is not None:
            try:
                result = vault_runtime.remember_explicitly(
                    content, evidence=said, source="explicit request", anchor=anchor
                )
            except (LookupError, ValueError) as exc:
                log.info("learning: explicit remember request not saved — %s", exc)
                return 0
            return 1 if result.action == "added" else 0
        try:
            change = self.notebook.keep_explicit(content, evidence=said)
        except (ValueError, OSError) as exc:  # filelock.Timeout is an OSError subclass too
            log.info("learning: explicit remember request not saved — %s", exc)
            return 0
        return 1 if change is not None else 0

    async def _remember(
        self, said: str, content: str, anchor: dict[str, Any] | None = None
    ) -> None:
        if await asyncio.to_thread(self._keep_request, said, content, anchor):
            await self.compact()

    # ── compaction ───────────────────────────────────────────────────────

    async def compact(self, *, force: bool = False) -> int:
        """Drop duplicates (free) and merge a notebook past its fill trigger."""
        async with self._lock:
            return await self._compact_locked(force=force)

    async def _compact_locked(self, *, force: bool = False) -> int:
        from dodaios.memory.learning import compact

        changed = 0
        books = await asyncio.to_thread(self.notebook.entries)
        for target, rows in books.items():
            for dropped, kept in compact.duplicates(rows):
                changed += await asyncio.to_thread(
                    self._write,
                    target=target,
                    operation="remove",
                    entry_id=dropped,
                    source=f"compaction: duplicate of {kept}",
                )
        if changed:
            books = await asyncio.to_thread(self.notebook.entries)
        if self._compactor is None:
            return changed
        state = await asyncio.to_thread(self.notebook.read_state)
        now = time.time()
        for target, (used, budget) in self.notebook.usage(books).items():
            last = float(state.get(f"compacted:{target}", 0.0))
            if used < budget * compact.FILL_TRIGGER:
                continue
            if not force and now - last < compact.COOLDOWN_S:
                continue
            state[f"compacted:{target}"] = now
            await asyncio.to_thread(self.notebook.write_state, state)
            changed += await self._merge(target, books[target], used, budget)
        return changed

    async def _merge(self, target: str, rows: list[Any], used: int, budget: int) -> int:
        from dodaios.memory.learning import compact
        from dodaios.memory.learning.notebook import EXPLICIT_ORIGIN

        # What the user asked to remember is theirs: never merged, never
        # expired (its date prefix would otherwise read as a passed deadline).
        rows = [e for e in rows if getattr(e, "origin", "") != EXPLICIT_ORIGIN]
        if len(rows) < 2:
            return 0
        prompt = compact.build_prompt(rows, target=target, used=used, budget=budget)
        self.compact_calls += 1
        log.info("learning: compacting %s (%d/%d chars)", target, used, budget)
        try:
            raw = await self._compactor(prompt) if self._compactor else None
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a failed merge leaves the notebook as it was
            log.warning("learning: compaction failed", exc_info=True)
            raw = None
        seat = _seat_of(self._compactor)
        if not isinstance(raw, dict):
            await asyncio.to_thread(
                self.notebook.note_review,
                source=f"compaction: {target}",
                outcome="failed",
                changes=0,
                seat=seat,
            )
            return 0
        merges, outdated, rejected = compact.validate(raw, rows)
        for why in rejected:
            log.info("learning: rejected a compaction — %s", why)
        texts = {e.id: e.text for e in rows}
        changed = 0
        for merge in merges:
            added = await asyncio.to_thread(
                self._write,
                target=target,
                operation="add",
                text=merge.text,
                importance=merge.importance,
                origin="compaction",
                evidence=", ".join(merge.sources),
                source="compaction: merge",
                enforce_budget=False,
                seat=seat,
            )
            if not added:
                continue  # Keep the sources when the merged entry did not land.
            changed += added
            for source in merge.sources:
                changed += await asyncio.to_thread(
                    self._write,
                    target=target,
                    operation="remove",
                    entry_id=source,
                    expected=texts[source],
                    source="compaction: merged",
                )
        for entry_id in outdated:
            changed += await asyncio.to_thread(
                self._write,
                target=target,
                operation="remove",
                entry_id=entry_id,
                expected=texts[entry_id],
                source="compaction: outdated",
            )
        await asyncio.to_thread(
            self.notebook.note_review,
            source=f"compaction: {target}",
            outcome="answered",
            changes=changed,
            seat=seat,
        )
        return changed

    def pending(self) -> dict[str, int]:
        """Unreviewed turns per conversation (diagnostics and tests)."""
        return {key: c.unreviewed for key, c in self._conversations.items() if c.unreviewed}


# ── the process-wide loop ─────────────────────────────────────────────────

_loop: JarvisLearningLoop | None = None


def current_loop() -> JarvisLearningLoop | None:
    return _loop


def start_learning(config: Any, bus: Any) -> JarvisLearningLoop | None:
    """Wire the loop for this process; ``None`` when it is switched off."""
    global _loop
    from dodaios.memory.learning import compact
    from dodaios.memory.learning import notebook as notebook_module
    from dodaios.memory.learning.review import ModelReviewer
    from dodaios.memory.vault import consolidate, episodes, reconcile

    _connect_write_feedback(bus)
    _open_vault(config)
    cfg = config.memory.learning
    if not cfg.enabled:
        notebook_module.set_active(None)
        return None
    if _loop is not None:
        return _loop
    book = notebook_module.notebook_from_config(config)
    _loop = JarvisLearningLoop(
        book,
        ModelReviewer(config),
        review_every_turns=cfg.review_every_turns,
        idle_review_seconds=cfg.idle_review_seconds,
        compactor=ModelReviewer(
            config,
            system=compact.system_prompt,
            parser=compact.parse,
            max_tokens=compact.COMPACT_MAX_TOKENS,
            caller="learning-compaction",
        ),
        vault_reviewer=ModelReviewer(
            config,
            system=reconcile.system_prompt,
            parser=reconcile.parse,
            max_tokens=reconcile.REVIEW_MAX_TOKENS,
            caller="memory-vault",
        ),
        upkeep_reviewer=ModelReviewer(
            config,
            system=consolidate.system_prompt,
            parser=consolidate.parse,
            max_tokens=consolidate.REVIEW_MAX_TOKENS,
            caller="memory-vault-upkeep",
            allow_metered=False,
        ),
        episode_reviewer=ModelReviewer(
            config,
            system=episodes.system_prompt,
            parser=episodes.parse,
            max_tokens=episodes.REVIEW_MAX_TOKENS,
            caller="memory-vault-episodes",
        ),
    )
    _loop.start(bus)
    notebook_module.set_active(book)
    return _loop


def _open_vault(config: Any) -> None:
    """Open the memory vault (ADR-0044); a fault leaves the notebooks in charge."""
    from dodaios.memory.vault import runtime as vault_runtime

    try:
        vault = vault_runtime.open_from_config(config)
    except Exception:  # noqa: BLE001 — memory must never block the boot
        log.warning("memory vault: could not open it; using the notebooks", exc_info=True)
        return
    if vault is not None:
        log.info("memory vault: %s (%d current memories)", vault.path, vault.stats()["current"])
        threading.Thread(
            target=_import_legacy_once,
            args=(config, vault),
            name="memory-vault-import",
            daemon=True,
        ).start()


def _import_legacy_once(config: Any, vault: Any) -> None:
    """Copy the old wiki, notebooks and profile into a new vault, once (chunk 4)."""
    from dodaios.core.config import DATA_DIR
    from dodaios.memory.vault import legacy_import
    from dodaios.memory.vault import runtime as vault_runtime

    try:
        wiki_root = legacy_import.legacy_wiki_root(config)
    except Exception:  # noqa: BLE001 — no wiki configured: import the other sources only
        log.info("memory vault import: no wiki vault found", exc_info=True)
        wiki_root = None
    try:
        if legacy_import.import_once(vault, wiki_root=wiki_root, data_dir=DATA_DIR):
            vault_runtime.changed()
    except Exception:  # noqa: BLE001 — a failed import is retried on the next boot
        log.warning("memory vault: importing the old memory failed", exc_info=True)


def _connect_write_feedback(bus: Any) -> None:
    """Show Jarvis' memory writes in the UI (``MemoryFileWrite`` on ``bus``).

    Wired even when learning is off: the remember and update_soul tools still
    write memory files then, and the person should see those writes too.
    """
    from dodaios.memory import write_feedback

    try:
        write_feedback.connect(bus)
    except RuntimeError:
        # No running event loop (a synchronous test harness): nothing to show it on.
        log.debug("learning: memory write receipts not wired (no running loop)")


async def stop_learning() -> None:
    global _loop
    from dodaios.memory import write_feedback
    from dodaios.memory.learning import notebook as notebook_module
    from dodaios.memory.vault import runtime as vault_runtime

    loop, _loop = _loop, None
    notebook_module.set_active(None)
    vault_runtime.set_active(None)
    write_feedback.disconnect()
    if loop is not None:
        await loop.stop()
