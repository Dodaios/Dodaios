"""Who is waiting on the person right now, across every agent.

## The gap this closes

An agent that needs the person (a question, a tool approval, a secret, a
configuration proposal) parks a card in its own chat. That card is only seen
by someone who happens to have that chat open: with a dozen agents, the one
waiting is usually not the one on screen, and the work behind it sits still.

This module keeps one live list of everything that waits on the person, tells
the app when the list changes, and decides when a change is worth a
notification. The bell in the Agents section reads the list, the roster shows
each agent's reason, and the window title carries the count.

## Where the list comes from

* **Chat gates** are folded from the very events the chat timeline folds
  (``approval_required`` / ``question_required`` / ``credential_required`` and
  their resolutions), through the service's event listener. One listener sees
  every runner (our brain, the provider API loop, every CLI seat, Hermes and
  OpenClaw over ACP), because each of them ends in ``AgentChatService._emit``.
  After a restart the list is rebuilt from the tail of each chat's log, the
  same way a reopened chat rebuilds its cards.
* **Society items** are read from the society's approvals table: configuration
  proposals and parked unattended approvals. They are the source of truth
  there, so they are never mirrored here.

## When a change becomes a notification

Two transitions, decided here and shown by the app:

* ``needs_input``: an agent's waiting reason appeared or changed;
* ``done``: a turn the person started finished without leaving anything open.

Every notification passes one gate (:class:`AttentionGate`): never for a
routine or other unattended chat, never for a muted agent, never while the
person is looking at that agent, and at most one per agent and kind every
:data:`THROTTLE_S` seconds. Parked unattended approvals are counted but never
announced: background work never asks.

Nothing here is ever spoken. The only output is one app-bus event,
:class:`AgentAttentionChanged`, which the desktop app turns into the badge, an
in-app toast or a desktop notification. No voice path subscribes to it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal, NamedTuple

from dodaios.core.events import Event

log = logging.getLogger(__name__)

#: What an item asks of the person. Mirrors the ``waiting_reason.kind`` the
#: society agent payload carries.
Kind = Literal["question", "approval", "credential", "proposal"]
KINDS: Final[tuple[str, ...]] = ("question", "approval", "credential", "proposal")

#: One notification per agent and transition kind within this window.
THROTTLE_S: Final[float] = 5.0

#: A focus report older than this no longer says the person is looking: the
#: window that sent it may be gone without having said so.
FOCUS_TTL_S: Final[float] = 300.0

#: How long a "done" waits for the card a finished turn may still open (an
#: end-of-turn question or plan card arrives just after ``turn_finished``).
DONE_GRACE_S: Final[float] = 1.5

#: How much of a chat's log is replayed after a restart. Open cards sit at the
#: end of a chat: a later turn closes every card before it.
SEED_TAIL: Final[int] = 400

#: How many chats per surface are replayed after a restart, newest first.
SEED_SESSIONS: Final[int] = 200

#: Longest summary line an item carries (the card holds the rest).
SUMMARY_CHARS: Final[int] = 200

#: The society session prefix (``society:<agent>[...]``).
_SOCIETY_PREFIX: Final[str] = "society:"

#: The front-page chat surface: its gates belong to the lead agent, whose card
#: in the Agents section shows exactly that chat.
_LEAD_SURFACE: Final[str] = "jarvis"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _line(value: Any, limit: int = SUMMARY_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """One thing the person is asked for."""

    kind: str
    session_id: str
    ref_id: str
    summary: str
    since_ms: int
    expires_ms: int | None = None
    agent_id: str = ""
    turn_id: str = ""
    #: An end-of-turn card (a CLI that cannot ask mid-turn): its answer goes
    #: out as the next message and a new turn settles it.
    deferred: bool = False
    #: ``chat`` for a card in a chat, ``queue`` for the society's tables.
    source: str = "chat"
    #: Kind-specific facts the inbox needs to answer in place.
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "ref_id": self.ref_id,
            "summary": self.summary,
            "since_ms": self.since_ms,
            "expires_ms": self.expires_ms,
            "deferred": self.deferred,
            "source": self.source,
            # The full series stays on the card; the inbox needs the current step.
            "detail": {k: v for k, v in self.detail.items() if k != "questions"},
        }

    def reason(self) -> dict[str, Any]:
        """The ``waiting_reason`` shape of the society agent payload."""
        return {
            "kind": self.kind,
            "summary": self.summary,
            "session_id": self.session_id,
            "ref_id": self.ref_id,
        }


class Change(NamedTuple):
    """What one event did to the list."""

    #: ``opened`` | ``closed`` | ``done`` | ``proposal`` | ``recount``.
    what: str
    session_id: str
    item: AttentionItem | None = None


def _question_detail(questions: list[Any], answers: list[Any] | None) -> tuple[str, dict[str, Any]]:
    """The current step's text and what the inbox may offer to answer it."""
    answers = list(answers or [])
    step = next(
        (i for i in range(len(questions)) if i >= len(answers) or answers[i] is None),
        max(0, len(questions) - 1),
    )
    current = questions[step] if step < len(questions) and isinstance(questions[step], dict) else {}
    options = current.get("options") if isinstance(current.get("options"), list) else []
    labels = [_line(o.get("label"), 80) for o in options if isinstance(o, dict)]
    # A question this inbox cannot answer with one tap (several picks, a form)
    # still lists here; it is answered on its card.
    shape = str(current.get("type") or current.get("kind") or "single")
    multi = bool(current.get("multi") or current.get("multi_select") or current.get("multiSelect"))
    # Only a lone question: a series is reviewed and sent as a whole on its card.
    single = shape in ("single", "choice") and not multi and len(questions) == 1
    detail = {
        "question": _line(current.get("question"), 300),
        "options": labels,
        "step": step,
        "count": len(questions),
        "single": bool(single and labels),
    }
    return _line(current.get("question")), detail


class AttentionBoard:
    """Open cards per chat, folded from the chat events. Pure: no I/O, no clock.

    The rules match the timeline reducer (``reduce.ts``), so the list and the
    cards on screen never disagree: a resolution closes its card, a new turn
    settles every end-of-turn card before it, and a finished turn closes any
    mid-turn card it left behind.
    """

    def __init__(self) -> None:
        self._open: dict[tuple[str, str], AttentionItem] = {}
        #: Chats whose next turn the person started by typing.
        self._typed: set[str] = set()
        #: Running turns the person started (by chat).
        self._person_turns: dict[str, str] = {}
        #: Chats that have been seen live (a restart replay never overrides them).
        self.live_sessions: set[str] = set()

    # ------------------------------------------------------------------ read

    def items(self) -> list[AttentionItem]:
        return sorted(self._open.values(), key=lambda item: item.since_ms)

    def open_in(self, session_id: str) -> list[AttentionItem]:
        return [item for (sid, _), item in self._open.items() if sid == session_id]

    # ----------------------------------------------------------------- write

    def seed(self, session_id: str, events: Iterable[dict[str, Any]]) -> None:
        """Rebuild one chat's open cards from its log (after a restart)."""
        if session_id in self.live_sessions:
            return
        for event in events:
            self._fold(session_id, event)
        # A replay says nothing about who started the turn that is running now.
        self._typed.discard(session_id)
        self._person_turns.pop(session_id, None)

    def observe(self, session_id: str, event: dict[str, Any]) -> list[Change]:
        """Fold one live event; returns what it changed."""
        self.live_sessions.add(session_id)
        return self._fold(session_id, event)

    def _open_item(self, item: AttentionItem) -> list[Change]:
        self._open[(item.session_id, item.ref_id)] = item
        return [Change("opened", item.session_id, item)]

    def _close(self, session_id: str, ref_id: str) -> list[Change]:
        item = self._open.pop((session_id, ref_id), None)
        return [Change("closed", session_id, item)] if item is not None else []

    def _fold(self, session_id: str, event: dict[str, Any]) -> list[Change]:
        kind = str(event.get("kind") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        assert isinstance(payload, dict)
        ts = int(event.get("ts_ms") or 0) or _now_ms()
        turn_id = str(payload.get("turn_id") or "")

        if kind == "approval_required":
            ref = str(payload.get("approval_id") or "")
            if not ref:
                return []
            tool = _line(payload.get("name"), 120)
            return self._open_item(AttentionItem(
                kind="approval", session_id=session_id, ref_id=ref,
                summary=_line(payload.get("summary")) or tool, since_ms=ts, turn_id=turn_id,
                detail={"tool": tool},
            ))
        if kind == "approval_resolved":
            return self._close(session_id, str(payload.get("approval_id") or ""))

        if kind == "question_required":
            ref = str(payload.get("question_id") or "")
            raw = payload.get("questions")
            questions = raw if isinstance(raw, list) else []
            if not ref or not questions:
                return []
            summary, detail = _question_detail(questions, None)
            expires = int(payload.get("expires_ms") or 0) or None
            return self._open_item(AttentionItem(
                kind="question", session_id=session_id, ref_id=ref, summary=summary,
                since_ms=ts, expires_ms=expires, turn_id=turn_id,
                deferred=bool(payload.get("deferred")),
                detail={**detail, "asker": _line(payload.get("asker"), 80), "questions": questions},
            ))
        if kind == "question_progress":
            key = (session_id, str(payload.get("question_id") or ""))
            item = self._open.get(key)
            if item is None:
                return []
            questions = item.detail.get("questions") or []
            answers = payload.get("answers") if isinstance(payload.get("answers"), list) else None
            summary, detail = _question_detail(questions, answers)
            expires = int(payload.get("expires_ms") or 0) or item.expires_ms
            self._open[key] = replace(
                item, summary=summary or item.summary, expires_ms=expires,
                detail={**item.detail, **detail},
            )
            return []
        if kind == "question_resolved":
            return self._close(session_id, str(payload.get("question_id") or ""))

        if kind == "credential_required":
            ref = str(payload.get("request_id") or "")
            if not ref:
                return []
            label = _line(payload.get("label"), 120) or _line(payload.get("env"), 120)
            return self._open_item(AttentionItem(
                kind="credential", session_id=session_id, ref_id=ref, summary=label,
                since_ms=ts, turn_id=turn_id, detail={"label": label},
            ))
        if kind == "credential_resolved":
            return self._close(session_id, str(payload.get("request_id") or ""))

        if kind == "user_message":
            # An agent writing on the person's behalf (``author``) is not the
            # person starting work.
            if not payload.get("author"):
                self._typed.add(session_id)
            return []
        if kind == "turn_started":
            changes: list[Change] = []
            for item in self.open_in(session_id):
                if item.kind == "question" and item.deferred:
                    changes += self._close(session_id, item.ref_id)
            if session_id in self._typed:
                self._typed.discard(session_id)
                self._person_turns[session_id] = turn_id
            else:
                self._person_turns.pop(session_id, None)
            return changes
        if kind == "turn_finished":
            changes = []
            for item in self.open_in(session_id):
                stale = item.kind in ("question", "approval") and not item.deferred
                if stale and (not turn_id or item.turn_id == turn_id):
                    changes += self._close(session_id, item.ref_id)
            by_person = self._person_turns.pop(session_id, None)
            finished = str(payload.get("status") or "") == "done"
            if finished and by_person is not None and not self.open_in(session_id):
                changes.append(Change("done", session_id))
            return changes

        if kind == "notice":
            notice = str(payload.get("kind") or "")
            if notice == "proposal" and str(payload.get("status") or "pending") == "pending":
                item = AttentionItem(
                    kind="proposal", session_id=session_id,
                    ref_id=str(payload.get("proposal_id") or ""),
                    summary=_line(payload.get("summary") or payload.get("text")), since_ms=ts,
                    agent_id=str(payload.get("agent_id") or ""), source="queue",
                )
                return [Change("proposal", session_id, item)]
            if notice in ("proposal_resolved", "approval_cleared"):
                return [Change("recount", session_id)]
        return []


# ---------------------------------------------------------------------- gate


@dataclass(slots=True)
class Focus:
    """What the person is looking at, as the app last reported it."""

    agent_id: str = ""
    session_id: str = ""
    app_focused: bool = False
    muted: frozenset[str] = frozenset()
    at: float = 0.0


class AttentionGate:
    """Decides whether a transition may become a notification.

    Returns the reason it was held back, or ``None`` to let it through. Pure
    apart from the injected clock, so every rule is unit-tested.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        throttle_s: float = THROTTLE_S,
        focus_ttl_s: float = FOCUS_TTL_S,
    ) -> None:
        self._clock = clock
        self._throttle_s = throttle_s
        self._focus_ttl_s = focus_ttl_s
        self._last: dict[tuple[str, str], float] = {}
        self.focus = Focus()

    def report_focus(
        self,
        *,
        agent_id: str = "",
        session_id: str = "",
        app_focused: bool = False,
        muted: Iterable[str] = (),
    ) -> None:
        self.focus = Focus(
            agent_id=agent_id or "",
            session_id=session_id or "",
            app_focused=bool(app_focused),
            muted=frozenset(m for m in muted if m),
            at=self._clock(),
        )

    def looking_at(self, agent_id: str) -> bool:
        focus = self.focus
        fresh = focus.at > 0 and self._clock() - focus.at <= self._focus_ttl_s
        return fresh and focus.app_focused and bool(agent_id) and focus.agent_id == agent_id

    def verdict(self, *, agent_id: str, transition: str, session_id: str) -> str | None:
        if not agent_id:
            return "no_agent"
        if _unattended(session_id):
            return "unattended"
        if agent_id in self.focus.muted:
            return "muted"
        if self.looking_at(agent_id):
            return "looking"
        key = (agent_id, transition)
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self._throttle_s:
            return "throttled"
        self._last[key] = now
        return None


def _unattended(session_id: str) -> bool:
    """A routine run's own chat: nobody watches it, so it never notifies."""
    from dodaios.society.routine_runner import is_routine_session

    return is_routine_session(session_id)


# ---------------------------------------------------------------------- event


@dataclass(frozen=True, slots=True)
class AgentAttentionChanged(Event):
    """The list of things waiting on the person changed.

    ``count`` is the whole list's length (the badge). When the change is worth
    telling, ``transition`` says which (``needs_input`` | ``done``) with the
    agent and card it is about; otherwise it is empty and clients only refresh
    their list. Shown as a badge, an in-app toast or a desktop notification;
    never spoken.
    """

    count: int = 0
    transition: str = ""
    agent_id: str = ""
    agent_name: str = ""
    session_id: str = ""
    kind: str = ""
    ref_id: str = ""
    summary: str = ""


# ------------------------------------------------------------------- service

Publisher = Callable[[Any], Awaitable[None]]


class Attention:
    """The live list for one chat service, plus its notifier."""

    def __init__(
        self,
        service: Any,
        *,
        publish: Publisher | None = None,
        society: Callable[[], Any] | None = None,
        gate: AttentionGate | None = None,
    ) -> None:
        self.service = service
        self.board = AttentionBoard()
        self.gate = gate or AttentionGate()
        self._publish = publish
        self._society = society or (lambda: None)
        self._agents: dict[str, str | None] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._seeded = False
        self._seed_lock: asyncio.Lock | None = None
        self.done_grace_s = DONE_GRACE_S

    # ----------------------------------------------------------- listening

    def listener(self, session_id: str, event: dict[str, Any]) -> None:
        """The service's event listener: records, then schedules the rest."""
        changes = self.board.observe(session_id, event)
        if not changes:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # emitted off the loop: the list is already updated
            return
        task = loop.create_task(self._after(changes), name="agent-attention")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _after(self, changes: list[Change]) -> None:
        try:
            await self.ensure_seeded()
            note: dict[str, Any] = {}
            for change in changes:
                if change.what != "done":
                    note = await self._transition(change) or note
            await self._emit(len(await self.items()), note)
            done = [change for change in changes if change.what == "done"]
            if not done:
                return
            # A turn that ends by asking (an end-of-turn card) is not finished
            # news: that card's own notice tells it instead.
            await asyncio.sleep(self.done_grace_s)
            for change in done:
                if self.board.open_in(change.session_id):
                    continue
                told = await self._transition(change)
                if told:
                    await self._emit(len(await self.items()), told)
        except Exception:  # noqa: BLE001 — a notifier must never break the chat it watches
            log.warning("agent attention: could not publish a change", exc_info=True)

    async def _transition(self, change: Change) -> dict[str, Any] | None:
        if change.what not in ("opened", "proposal", "done"):
            return None
        agent_id = (change.item.agent_id if change.item else "") or await self.agent_for(
            change.session_id
        ) or ""
        transition = "done" if change.what == "done" else "needs_input"
        if transition == "done" and change.session_id != f"{_SOCIETY_PREFIX}{agent_id}":
            # "Finished" is news only for an agent's own chat. The front-page
            # chat (typed or mirrored from a voice call) and agent-to-agent
            # conversations finish under the person's eyes or without them.
            return None
        held = self.gate.verdict(
            agent_id=agent_id, transition=transition, session_id=change.session_id
        )
        if held is not None:
            log.debug("agent attention: %s for %s held (%s)", transition, agent_id, held)
            return None
        item = change.item
        return {
            "transition": transition,
            "agent_id": agent_id,
            "agent_name": self._agent_name(agent_id),
            "session_id": change.session_id,
            "kind": item.kind if item else "",
            "ref_id": item.ref_id if item else "",
            "summary": item.summary if item else "",
        }

    async def _emit(self, count: int, note: dict[str, Any]) -> None:
        if self._publish is None:
            return
        await self._publish(
            AgentAttentionChanged(count=count, source_layer="agent_chat.attention", **note)
        )

    async def refresh(self) -> None:
        """Tell clients the list may have changed (a society item was decided)."""
        await self._emit(len(await self.items()), {})

    # ------------------------------------------------------------- reading

    async def ensure_seeded(self) -> None:
        """Rebuild open cards from the logs once (after a restart)."""
        if self._seeded:
            return
        if self._seed_lock is None:
            self._seed_lock = asyncio.Lock()
        async with self._seed_lock:
            if self._seeded:
                return
            try:
                logs = await asyncio.to_thread(self._read_logs)
            except Exception:  # noqa: BLE001 — without a replay the list fills from live events
                log.warning("agent attention: could not replay chat logs", exc_info=True)
                logs = []
            for session_id, surface, events in logs:
                self._agents.setdefault(session_id, self._agent_from(session_id, surface))
                self.board.seed(session_id, events)
            self._seeded = True

    def _read_logs(self) -> list[tuple[str, str, list[dict[str, Any]]]]:
        store = getattr(self.service, "store", None)
        if store is None:
            return []
        out: list[tuple[str, str, list[dict[str, Any]]]] = []
        for surface in ("society", _LEAD_SURFACE):
            for session in store.list_sessions(SEED_SESSIONS, surface=surface):
                sid = session.session_id
                if _unattended(sid):
                    continue
                out.append((sid, surface, store.list_events(sid, tail=SEED_TAIL)))
        return out

    @staticmethod
    def _agent_from(session_id: str, surface: str) -> str | None:
        if session_id.startswith(_SOCIETY_PREFIX):
            from dodaios.society.surface import agent_id_of

            return agent_id_of(session_id)
        if surface == _LEAD_SURFACE:
            from dodaios.society.roster import LEAD_AGENT_ID

            return LEAD_AGENT_ID
        return None

    async def agent_for(self, session_id: str) -> str | None:
        """The agent a chat belongs to; ``None`` for chats outside the Agents section."""
        if session_id in self._agents:
            return self._agents[session_id]
        surface = ""
        if not session_id.startswith(_SOCIETY_PREFIX):
            store = getattr(self.service, "store", None)
            session = await asyncio.to_thread(store.get_session, session_id) if store else None
            surface = str(getattr(session, "surface", "") or "")
        agent_id = self._agent_from(session_id, surface)
        self._agents[session_id] = agent_id
        return agent_id

    def _agent_name(self, agent_id: str) -> str:
        rt = self._society()
        cached = getattr(rt, "cached_agent", None)
        agent = cached(agent_id) if callable(cached) else None
        if agent is None:
            return ""
        from dodaios.society.display_name import display_name

        try:
            return display_name(agent)
        except Exception:  # noqa: BLE001 — the name is cosmetic
            return str(getattr(agent, "name", "") or "")

    async def chat_items(self) -> list[AttentionItem]:
        await self.ensure_seeded()
        out: list[AttentionItem] = []
        for item in self.board.items():
            agent_id = await self.agent_for(item.session_id)
            if agent_id:
                out.append(replace(item, agent_id=agent_id))
        return out

    async def society_items(self) -> list[AttentionItem]:
        """Proposals and parked unattended approvals; empty until the society is up."""
        rt = self._society()
        approvals = getattr(rt, "approvals", None)
        # A runtime built on first use exists before its store opens; reading
        # it then raised "SocietyStore: call open() before use".
        if approvals is None or not getattr(rt, "started", True):
            return []
        from dodaios.society.proposals import kind_of

        out: list[AttentionItem] = []
        for row in await approvals.pending():
            proposal = kind_of(row.capability) is not None
            session_id = str(row.action.get("session_id") or "") if proposal else ""
            out.append(AttentionItem(
                kind="proposal" if proposal else "approval",
                session_id=session_id or f"{_SOCIETY_PREFIX}{row.agent_id}",
                ref_id=row.id,
                summary=_line(row.summary) or row.capability,
                since_ms=int(row.created_ms or 0),
                expires_ms=int(row.expires_ms or 0) or None,
                agent_id=row.agent_id,
                source="queue",
                detail={
                    "capability": row.capability,
                    "parked": str(row.state) == "blocked",
                    **({"proposal_kind": kind_of(row.capability)} if proposal else {}),
                },
            ))
        return out

    async def items(self) -> list[AttentionItem]:
        """Everything that waits on the person, oldest first."""
        chat = await self.chat_items()
        try:
            queued = await self.society_items()
        except Exception:  # noqa: BLE001 — the chat list stands on its own
            log.warning("agent attention: society items unavailable", exc_info=True)
            queued = []
        return sorted(chat + queued, key=lambda item: item.since_ms)

    async def waiting_reasons(self) -> dict[str, dict[str, Any]]:
        """Per agent: the reason it waits, the newest live card first."""
        reasons: dict[str, tuple[tuple[int, int], AttentionItem]] = {}
        for item in await self.items():
            # A card blocking a chat outranks a queued proposal; newer outranks older.
            rank = (1 if item.source == "chat" else 0, item.since_ms)
            current = reasons.get(item.agent_id)
            if current is None or rank > current[0]:
                reasons[item.agent_id] = (rank, item)
        return {agent_id: item.reason() for agent_id, (_, item) in reasons.items()}


# ------------------------------------------------------------------ wiring


def install(
    service: Any,
    *,
    publish: Publisher | None = None,
    society: Callable[[], Any] | None = None,
) -> Attention:
    """Attach the attention list to ``service`` (idempotent)."""
    existing = getattr(service, "attention", None)
    if isinstance(existing, Attention):
        return existing
    attention = Attention(service, publish=publish, society=society)
    service.add_event_listener(attention.listener)
    service.attention = attention
    return attention


def attention_of(service: Any) -> Attention | None:
    found = getattr(service, "attention", None)
    return found if isinstance(found, Attention) else None


async def waiting_reasons(state: Any) -> dict[str, dict[str, Any]]:
    """``waiting_reason`` per agent for the roster payload; empty when no chat runs yet."""
    attention = attention_of(getattr(state, "agent_chat", None))
    if attention is None:
        return {}
    try:
        return await attention.waiting_reasons()
    except Exception:  # noqa: BLE001 — the roster must load without it
        log.warning("agent attention: waiting reasons unavailable", exc_info=True)
        return {}
