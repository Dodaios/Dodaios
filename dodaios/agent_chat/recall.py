"""Stable ids for the lead's objects, short cards in context, and ``recall(id)``.

The lead's context window works like a cache. What it is likely to need next
sits in the window; everything else stays reachable behind an id.

* **Inline.** A report, a trigger notice or a catch-up entry reaches the lead as
  a short card: its id, a summary and the nearest context. A report the lead has
  not answered yet is inlined whole (it is the thing to act on now); once an
  answer follows it, a long report shrinks to a card.
* **Spill.** The rest of a long body stays out of the window and is read on
  demand with ``recall(id)``, page by page (``more`` is the next offset).
* **Chain of recall.** Every card names the ids of its closest relatives, so the
  lead can hop from a message to a thread to a job to its result without a
  search: the ids ARE the reference graph.

Id forms (the lead's own conversation is implied for ``ev:<seq>``):

``ev:<seq>`` / ``ev:<session>:<seq>``  one event of a conversation
``turn:<turn_id>``                     the events of one turn
``thread:<session>``                   a chat thread (the lead's own too)
``job:<id>`` / ``job_<hex>``           a row of the jobs ledger
``trg:<event_id>``                     a trigger event and what was decided
``artifact:<id>``                      a page or deliverable a job produced
``agent:<id>``                         a named agent of the team

Nothing here caps what the model may read: the card sizes only decide what is
pasted up front. The tool's pages and the structural bound are the provider
limits' business.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

#: Notice kinds that carry an agent's report into the conversation.
REPORT_KINDS: Final[frozenset[str]] = frozenset(
    {"society_result", "society_message", "coding_result", "delegation_report"}
)
#: The notice a trigger decision writes for the person.
TRIGGER_NOTICE_KIND: Final[str] = "event_trigger"

#: A report longer than this shrinks to a card once an answer followed it.
SPILL_AT: Final[int] = 2000
#: How much of a spilled body the card still shows.
CARD_HEAD: Final[int] = 700
#: One page of ``recall`` text.
PAGE_CHARS: Final[int] = 4000
#: The structural bound of one ``recall`` answer (valid JSON, see core.bounded_json).
MAX_ANSWER_CHARS: Final[int] = 16_000
#: Cap used before the card existed, kept for a report nobody answered yet.
LEGACY_REPORT_CAP: Final[int] = 6000

_SUMMARY_CHARS: Final[int] = 160
_JOB_IN_TEXT = re.compile(r"\bjob_[0-9a-f]{12}\b")
_TRG_IN_TEXT = re.compile(r"\btrg:[A-Za-z0-9_.:@#/\-]+")


def one_line(text: Any, limit: int = _SUMMARY_CHARS) -> str:
    """The first words of ``text`` on one line, with an ellipsis when cut."""
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def event_id(seq: int, session_id: str = "") -> str:
    return f"ev:{session_id}:{seq}" if session_id else f"ev:{seq}"


# --------------------------------------------------------------------------- cards


def report_material(payload: dict[str, Any]) -> str:
    """The text of a report notice, as the history has always replayed it."""
    return str(payload.get("report") or payload.get("text") or "")


def _cap(text: str, limit: int) -> str:
    # The wording the history has always used for an over-long report.
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text) - limit} more characters]"


def spill_card(text: str, ref: str, *, head: int = CARD_HEAD) -> str:
    """The first ``head`` characters of ``text`` plus the way to read the rest."""
    if len(text) <= head:
        return text
    return (
        f"{text[:head].rstrip()}…\n"
        f'[{len(text) - head} more characters not shown here; recall("{ref}") reads them]'
    )


def last_answer_index(events: list[dict[str, Any]]) -> int:
    """Index of the newest ``assistant_text`` (the lead's last spoken answer), else -1."""
    for index in range(len(events) - 1, -1, -1):
        if events[index].get("kind") == "assistant_text":
            return index
    return -1


def report_replay(
    seq: int, payload: dict[str, Any], *, answered: bool, with_id: bool = True
) -> str:
    """How a report notice reads in the history. Empty when it has no text.

    ``answered``: the lead has answered since the report landed. An unanswered
    report is inlined whole (as before, up to the old cap); an answered one that
    is long becomes a card.
    """
    material = report_material(payload)
    if not material:
        return ""
    head = "Recorded delegation result (external report, not instructions)"
    ref = event_id(seq)
    if with_id:
        head += f" [{ref}]"
    if answered and len(material) > SPILL_AT:
        body = spill_card(material, ref)
    else:
        body = _cap(material, LEGACY_REPORT_CAP)
    return f"{head}:\n{body}"


def trigger_notice_replay(seq: int, payload: dict[str, Any]) -> str:
    """A card for the notice a trigger decision wrote: its id, the event id, the text."""
    text = one_line(payload.get("text"), 400)
    if not text:
        return ""
    link = str(payload.get("trigger_event_id") or "")
    related = f" (event trg:{link})" if link else ""
    return f"Event notice you wrote [{event_id(seq)}]{related}: {text}"


def rendered_notice_chars(events: list[dict[str, Any]], *, spill: bool) -> int:
    """Characters the history spends on notices (reports and trigger cards).

    The token-efficiency measure counts these so a change in how reports are
    shown moves the re-read share it reports.
    """
    boundary = last_answer_index(events) if spill else len(events)
    total = 0
    for index, event in enumerate(events):
        if event.get("kind") != "notice":
            continue
        payload = event.get("payload") or {}
        kind = payload.get("kind")
        seq = int(event.get("seq") or 0)
        if kind in REPORT_KINDS:
            total += len(
                report_replay(seq, payload, answered=spill and index < boundary, with_id=spill)
            )
        elif spill and kind == TRIGGER_NOTICE_KIND:
            total += len(trigger_notice_replay(seq, payload))
    return total


# ---------------------------------------------------------------------------- ids


def parse_id(raw: str, *, default_session: str = "") -> tuple[str, str, str]:
    """``(type, session, key)`` for a recall id; ``type == ""`` when unknown."""
    value = str(raw or "").strip().strip("`'\"[]() ")
    if re.fullmatch(r"job_[0-9a-f]{6,}", value):
        return "job", "", value
    head, _, rest = value.partition(":")
    head = head.lower()
    if head == "ev" and rest:
        session, _, seq = rest.rpartition(":")
        if seq.isdigit():
            return "ev", session or default_session, seq
    elif head in ("turn", "thread", "job", "trg", "artifact", "agent") and rest:
        return head, "", rest
    return "", "", value


@dataclass(slots=True)
class Sources:
    """Where each kind of object is read from. Every part is optional."""

    store: Any = None  # AgentChatStore
    lead_session: str = ""
    ledger: Any = None  # JobLedger
    triggers: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None
    agent: Callable[[str], Awaitable[dict[str, Any] | None]] | None = None


def _ts(ms: int) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


def _page(text: str, offset: int) -> tuple[str, int | None]:
    """One page of ``text`` from ``offset`` and the next offset (``None`` at the end)."""
    offset = max(0, offset)
    chunk = text[offset : offset + PAGE_CHARS]
    end = offset + len(chunk)
    return chunk, (end if end < len(text) else None)


class Recall:
    """Resolves ids to compact cards. ``recall`` never raises for a bad id."""

    def __init__(self, sources: Sources, *, session: str = "") -> None:
        self._s = sources
        #: The conversation a bare ``ev:<seq>`` belongs to.
        self._session = session or sources.lead_session

    # ---------------------------------------------------------------- public

    async def recall(self, raw_id: str, *, more: int = 0) -> dict[str, Any]:
        kind, session, key = parse_id(raw_id, default_session=self._session)
        try:
            if kind == "ev":
                card = await asyncio.to_thread(self._event, session, int(key), more)
            elif kind == "turn":
                card = await asyncio.to_thread(self._turn, self._session, key)
            elif kind == "thread":
                card = await asyncio.to_thread(self._thread, key)
            elif kind == "job":
                card = await asyncio.to_thread(self._job, key.removeprefix("job:"))
            elif kind == "artifact":
                card = await asyncio.to_thread(self._artifact, key)
            elif kind == "trg":
                card = await self._trigger(key)
            elif kind == "agent":
                card = await self._agent(key)
            else:
                return self._unknown(raw_id, "that is not an id this tool knows")
        except Exception:  # noqa: BLE001 - a broken source must not break the turn
            log.warning("recall: %s could not be read", raw_id, exc_info=True)
            return self._unknown(raw_id, "its source could not be read right now")
        return card or self._unknown(raw_id, "nothing with that id exists (any more)")

    @staticmethod
    def _unknown(raw_id: str, why: str) -> dict[str, Any]:
        return {
            "id": str(raw_id),
            "found": False,
            "note": why,
            "id_forms": [
                "ev:<seq>",
                "turn:<id>",
                "thread:<id>",
                "job:<id>",
                "trg:<event id>",
                "artifact:<id>",
                "agent:<id>",
            ],
        }

    # ---------------------------------------------------------------- events

    def _events(self, session: str) -> list[dict[str, Any]]:
        if self._s.store is None or not session:
            return []
        return self._s.store.list_events(session)

    def _event(self, session: str, seq: int, more: int) -> dict[str, Any] | None:
        events = self._events(session)
        index = next((i for i, e in enumerate(events) if int(e.get("seq") or 0) == seq), -1)
        if index < 0:
            return None
        event = events[index]
        payload = event.get("payload") or {}
        kind = str(event.get("kind") or "")
        lead = session == self._s.lead_session
        rid = event_id(seq, "" if session == self._session else session)
        text, who = self._event_text(kind, payload)
        card: dict[str, Any] = {
            "id": rid,
            "type": "event",
            "kind": kind,
            "when": _ts(int(event.get("ts_ms") or 0)),
        }
        if who:
            card["who"] = who
        card["summary"] = one_line(text) or kind
        if kind == "notice":
            card["notice"] = str(payload.get("kind") or "")
            if payload.get("status"):
                card["status"] = str(payload["status"])
            if payload.get("agent_name"):
                card["agent"] = str(payload["agent_name"])
        page, nxt = _page(text, more)
        if page:
            card["text"] = page
        card["chars"] = len(text)
        if nxt is not None:
            card["more"] = nxt
        related: dict[str, Any] = {}
        thread = session if not lead else ""
        related["thread"] = f"thread:{session}" if (thread or session) else ""
        if payload.get("turn_id"):
            related["turn"] = f"turn:{payload['turn_id']}"
        near = self._neighbours(events, index, session == self._session)
        related.update(near)
        related.update(self._links(session, payload, text))
        card["related"] = {k: v for k, v in related.items() if v}
        return card

    @staticmethod
    def _event_text(kind: str, payload: dict[str, Any]) -> tuple[str, str]:
        if kind == "user_message":
            return str(payload.get("text") or ""), "user"
        if kind == "assistant_text":
            return str(payload.get("text") or ""), "assistant"
        if kind == "notice":
            return report_material(payload), "system"
        if kind == "tool_call":
            return f"{payload.get('name', '')} {payload.get('input', '')}", "assistant"
        if kind == "tool_result":
            return str(payload.get("output") or ""), "tool"
        if kind == "agent_message":
            return str(payload.get("prompt") or payload.get("text") or ""), "agent"
        return str(payload.get("text") or payload.get("summary") or ""), ""

    def _neighbours(self, events: list[dict[str, Any]], index: int, local: bool) -> dict[str, str]:
        """Ids of the messages around ``events[index]`` and the one it answers."""
        session = "" if local else self._session
        wanted = {"user_message", "assistant_text", "notice"}

        def ref(i: int) -> str:
            return event_id(int(events[i].get("seq") or 0), session)

        out: dict[str, str] = {}
        prev = next((i for i in range(index - 1, -1, -1) if events[i].get("kind") in wanted), None)
        nxt = next(
            (i for i in range(index + 1, len(events)) if events[i].get("kind") in wanted), None
        )
        if prev is not None:
            out["prev"] = ref(prev)
        if nxt is not None:
            out["next"] = ref(nxt)
        if events[index].get("kind") == "assistant_text":
            asked = next(
                (i for i in range(index - 1, -1, -1) if events[i].get("kind") == "user_message"),
                None,
            )
            if asked is not None:
                out["replied_to"] = ref(asked)
        return out

    def _links(self, session: str, payload: dict[str, Any], text: str) -> dict[str, Any]:
        """Ids an event names: its job, agent, trigger event, thread and result."""
        from dodaios.orchestrator import jobs

        out: dict[str, Any] = {}
        ledger = self._s.ledger
        job_ids: list[str] = []
        assignment = str(payload.get("assignment_id") or "")
        task = str(payload.get("task_id") or "")
        if assignment:
            job_ids.append(jobs.job_id_for("society_assignment", assignment))
        if task:
            from dodaios.agent_chat.parked_work import job_id_for_key

            derived = job_id_for_key(task)
            if derived:
                job_ids.append(derived)
        job_ids += _JOB_IN_TEXT.findall(text)
        if ledger is not None:
            seen: list[str] = []
            for jid in job_ids:
                if jid not in seen and ledger.get(jid) is not None:
                    seen.append(jid)
            if task and not seen:  # a routine's result: the job started for that task id
                seen += [j.id for j in ledger.find(ref=task, limit=3)]
            if seen:
                out["jobs"] = [f"job:{j}" for j in seen[:5]]
        if payload.get("agent_id"):
            out["agent"] = f"agent:{payload['agent_id']}"
        if payload.get("trigger_event_id"):
            out["trigger"] = f"trg:{payload['trigger_event_id']}"
        found = _TRG_IN_TEXT.findall(text)
        if found and "trigger" not in out:
            out["trigger"] = found[0]
        for key in ("thread_id", "session_id", "from_session", "reply_session_id"):
            value = str(payload.get(key) or "")
            if value and value != session:
                out["thread"] = f"thread:{value}"
                break
        return out

    def _turn(self, session: str, turn_id: str) -> dict[str, Any] | None:
        rows = [
            e
            for e in self._events(session)
            if str((e.get("payload") or {}).get("turn_id") or "") == turn_id
        ]
        if not rows:
            return None
        picks = [
            e
            for e in rows
            if e.get("kind")
            in {"user_message", "assistant_text", "notice", "tool_call", "turn_finished"}
        ]
        items = []
        for e in picks[:40]:
            text, _who = self._event_text(str(e.get("kind")), e.get("payload") or {})
            items.append(
                {
                    "id": event_id(int(e["seq"])),
                    "kind": e.get("kind"),
                    "summary": one_line(text, 100),
                }
            )
        finished = next((e for e in rows if e.get("kind") == "turn_finished"), None)
        card: dict[str, Any] = {
            "id": f"turn:{turn_id}",
            "type": "turn",
            "events": items,
            "summary": f"{len(rows)} events",
        }
        if finished is not None:
            card["status"] = str((finished.get("payload") or {}).get("status") or "")
        return card

    # --------------------------------------------------------------- threads

    def _thread(self, session_id: str) -> dict[str, Any] | None:
        store = self._s.store
        if store is None:
            return None
        session = store.get_session(session_id)
        if session is None:
            return None
        events = store.list_events(session_id)
        card: dict[str, Any] = {
            "id": f"thread:{session_id}",
            "type": "thread",
            "summary": one_line(session.title or session.preview, 120) or "untitled thread",
            "surface": session.surface,
            "provider": session.provider,
            "messages": session.message_count,
            "updated": _ts(int(session.updated_ms or 0)),
        }
        last = next((e for e in reversed(events) if e.get("kind") == "assistant_text"), None)
        if last is not None:
            card["last_answer"] = {
                "id": event_id(int(last["seq"]), "" if session_id == self._session else session_id),
                "summary": one_line((last.get("payload") or {}).get("text"), 240),
            }
        related: dict[str, Any] = {}
        owner = store.thread_owner(session_id)
        if owner:
            related["started_by"] = f"thread:{owner['owner_session']}"
            if owner.get("owner_agent"):
                related["agent"] = f"agent:{owner['owner_agent']}"
        if self._s.ledger is not None:
            owned = self._s.ledger.recent(owner_session=session_id, limit=10)
            targeted = self._s.ledger.find(target=f"pane:{session_id}", limit=5)
            related["jobs"] = [f"job:{j.id}" for j in [*owned, *targeted]][:10]
        children = store.thread_owners(session_id)[:10]
        if children:
            related["started"] = [f"thread:{c['session_id']}" for c in children]
        card["related"] = {k: v for k, v in related.items() if v}
        return card

    # ------------------------------------------------------------------ jobs

    def _job(self, job_id: str) -> dict[str, Any] | None:
        if self._s.ledger is None:
            return None
        job = self._s.ledger.get(job_id)
        if job is None:
            return None
        row = job.to_dict()
        card: dict[str, Any] = {
            "id": f"job:{job.id}",
            "type": "job",
            "summary": one_line(f"{job.title} ({job.state})", 200),
            **row,
        }
        card.pop("job_id", None)
        related: dict[str, Any] = {}
        if job.owner_session:
            related["thread"] = f"thread:{job.owner_session}"
        result = self._result_id(job)
        if result:
            related["result"] = result
        if job.kind == "society_assignment" and job.target:
            related["agent"] = f"agent:{job.target}"
        if job.ref and job.ref != result:
            card["ref"] = job.ref
        card["related"] = {k: v for k, v in related.items() if v}
        return card

    def _result_id(self, job: Any) -> str:
        """The id the job's result is read with: an artifact, or the report event."""
        ref = str(job.result_ref or "")
        if ref.startswith("artifact:"):
            return ref
        if ref.startswith("society:"):
            wanted = ref.removeprefix("society:")
            for event in reversed(self._events(self._s.lead_session)):
                payload = event.get("payload") or {}
                if event.get("kind") == "notice" and payload.get("assignment_id") == wanted:
                    return event_id(
                        int(event["seq"]),
                        "" if self._s.lead_session == self._session else self._s.lead_session,
                    )
        return ref

    def _artifact(self, artifact_id: str) -> dict[str, Any] | None:
        if self._s.ledger is None:
            return None
        made_by = self._s.ledger.find(ref=f"artifact:{artifact_id}", limit=3)
        if not made_by:
            return None
        job = made_by[0]
        card = {
            "id": f"artifact:{artifact_id}",
            "type": "artifact",
            "summary": one_line(job.title or job.summary, 160),
            "state": job.state,
            "detail": one_line(job.summary, 400),
            "related": {"job": f"job:{job.id}"},
        }
        if job.owner_session:
            card["related"]["thread"] = f"thread:{job.owner_session}"
        return card

    # --------------------------------------------------------------- trigger

    async def _trigger(self, key: str) -> dict[str, Any] | None:
        if self._s.triggers is None:
            return None
        found = await self._s.triggers(key)
        if not found:
            return None
        event = found["event"]
        decisions = found.get("decisions") or []
        card: dict[str, Any] = {
            "id": f"trg:{key}",
            "type": "trigger_event",
            "summary": one_line(f"{event.get('source')}: {event.get('summary')}", 200),
            "source": event.get("source"),
            "sender": event.get("sender"),
            "scope": event.get("scope"),
            "thread_key": event.get("thread_key"),
            "raw_ref": event.get("raw_ref"),
            "waiting": bool(found.get("waiting")),
            "decisions": [
                {
                    "action": d.get("action"),
                    "policy": one_line(d.get("policy_text"), 100),
                    "reason": one_line(d.get("reason"), 160),
                    "mode": d.get("mode"),
                    "outcome": d.get("outcome"),
                }
                for d in decisions[-3:]
            ],
        }
        related: dict[str, Any] = {}
        events = await asyncio.to_thread(self._events, self._s.lead_session)
        job_refs = [str(d["job"]) for d in decisions if d.get("job")]
        decision_ids = {str(d.get("id")) for d in decisions}
        for event_row in reversed(events):
            payload = event_row.get("payload") or {}
            if event_row.get("kind") != "notice":
                continue
            if payload.get("decision_id") in decision_ids and "notice" not in related:
                related["notice"] = event_id(int(event_row["seq"]))
            if str(payload.get("task_id") or "") in job_refs and "result" not in related:
                related["result"] = event_id(int(event_row["seq"]))
        if job_refs and self._s.ledger is not None:
            rows = await asyncio.to_thread(self._s.ledger.find, ref=job_refs[-1], limit=3)
            related["jobs"] = [f"job:{j.id}" for j in rows]
        if found.get("same_thread"):
            related["same_thread"] = [f"trg:{e}" for e in found["same_thread"]]
        card["related"] = {k: v for k, v in related.items() if v}
        return card

    # ---------------------------------------------------------------- agents

    async def _agent(self, agent_id: str) -> dict[str, Any] | None:
        if self._s.agent is None:
            return None
        found = await self._s.agent(agent_id)
        if not found:
            return None
        card: dict[str, Any] = {
            "id": f"agent:{found['agent_id']}",
            "type": "agent",
            "summary": one_line(
                f"{found.get('name')}: {found.get('title') or found.get('description')}", 160
            ),
            "state": found.get("state"),
            "provider": found.get("provider"),
            "model": found.get("model"),
        }
        related: dict[str, Any] = {}
        if found.get("session_id"):
            related["thread"] = f"thread:{found['session_id']}"
        if self._s.ledger is not None:
            rows = await asyncio.to_thread(
                self._s.ledger.find, target=str(found["agent_id"]), limit=5
            )
            related["jobs"] = [f"job:{j.id}" for j in rows]
        card["related"] = {k: v for k, v in related.items() if v}
        return card


# ----------------------------------------------------------------------- live wiring


def is_lead_session(session_id: str) -> bool:
    """True when ``session_id`` is the lead's conversation in the running app."""
    if not session_id:
        return False
    try:
        from dodaios.agent_chat import lead
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
        return bool(svc is not None and lead.is_lead(svc, session_id))
    except Exception:  # noqa: BLE001 - no society loaded: not the lead
        return False


def live_sources() -> Sources | None:
    """The running app's sources, or ``None`` while the society is not loaded."""
    from dodaios.agent_chat import lead
    from dodaios.orchestrator import jobs
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    svc = runtime.chat_service() if runtime is not None else None
    if svc is None:
        return None

    async def triggers(event_key: str) -> dict[str, Any] | None:
        from dodaios.lead_triggers import wiring

        service = wiring.get_service()
        return await service.lookup(event_key) if service is not None else None

    async def agent(agent_id: str) -> dict[str, Any] | None:
        record = await runtime.roster.get(agent_id)
        if record is None:
            return None
        return {
            "agent_id": record.agent_id,
            "name": record.name,
            "title": record.title,
            "description": record.description,
            "state": str(record.state),
            "provider": record.provider,
            "model": record.model,
            "session_id": getattr(record, "session_id", ""),
        }

    try:
        ledger = jobs.get_ledger()
    except Exception:  # noqa: BLE001 - jobs are optional context
        ledger = None
    return Sources(
        store=svc.store,
        lead_session=lead.lead_session_id(svc) or "",
        ledger=ledger,
        triggers=triggers,
        agent=agent,
    )
