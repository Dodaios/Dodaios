"""Router-tier society tools: ``delegate-to-agent`` and ``society-status``.

The voice front door of the agent society (MASTERPLAN §3.2, agent-definition
§4.1). Both tools answer inside the 5-second voice budget:

* ``delegate-to-agent`` appends ONE ``ASSIGN`` envelope to the society board
  on behalf of Jarvis (the lead) and returns a spoken acknowledgement at
  once. The scheduler — trusted Python — decides whether and how the target
  starts working; the tool never spawns anything itself and never waits for
  completion. Completions re-enter voice through the existing announcement
  path. Risk ``monitor``: a dispatch like ``spawn-worker``, never in a worker
  set (AP-5/AP-14).
* ``society-status`` reads the roster and the last events — no model call,
  no spend — and answers "what is Scout doing?" (risk ``safe``).

Both reach the runtime through a lazy resolver (AD-OC1): the society is
built on first use by the server, after the brain exists.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, Final

from dodaios.core.agent_brief import AGENT_BRIEF_RULE
from dodaios.core.delegation import origin_metadata
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.i18n import catalog as i18n_catalog
from dodaios.society.agent_names import AgentLookup, coding_pane_hint, lookup_agent
from dodaios.society.communication import REPLY_POLICY_SCHEMA, select_reply_policy
from dodaios.society.display_name import display_name

log = logging.getLogger(__name__)

RuntimeResolver = Callable[[], Any | None]

_ACK: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.ack")
_QUIET_ACK: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.quiet_ack")
_ERROR_ACK: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.error_ack")
_QUEUED: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.queued")
_NO_AGENT: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.no_agent")
_ASK_AGENT: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.ask_agent")
_OR: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.or")
_AVAILABLE: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.available")
_NO_FIT: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.no_fit")
_REFUSED: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.refused")
_NOT_READY: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.not_ready")
_STATUS_IDLE: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.status_idle")
_STATUS_WORKING: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.status_working")
_STATUS_LAST: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.status_last")
_ROSTER: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.roster")
_EMPTY_ROSTER: Final[dict[str, str]] = i18n_catalog.table("tools.delegate.empty_roster")


def _lang(args: dict[str, Any], ctx: Any) -> str:
    """The turn's output language: ``ctx.config["output_language"]`` as the
    tool-use loop stamps it (decided once per turn by ``turn_language.py``),
    else a ``turn_language`` argument, else the ambient answer language. This
    layer never re-derives a language from the utterance."""
    config = getattr(ctx, "config", None) or {}
    value = (
        str(
            (config.get("output_language") if isinstance(config, dict) else "")
            or args.get("turn_language")
            or ""
        )
        .strip()
        .lower()
    )
    if not value:
        try:
            from dodaios.voice.action_phrases import resolve_ambient_language

            value = resolve_ambient_language()
        except Exception:  # noqa: BLE001 — a spoken fallback beats a crash on the voice path
            value = "en"
    return value if value in _ACK else "en"


class DelegateToAgentTool:
    """Hand a task to a named society agent; acknowledge at once."""

    name: str = "delegate_to_agent"
    risk_tier: str = "monitor"
    description: str = (
        "Hand a task to one of the user's named agents (their agent society, listed on your "
        "team card): 'let Scout research X', 'Mailbox, answer the invoice mail', 'give that "
        "to the team'. Use when a background task fits the persistent team; leave `agent` "
        "empty to let the lead pick the agent whose hands fit the task. The agent works in "
        "the background; you acknowledge now and its result follows reply_policy. "
        "Stay available for conversation while it runs; completion is delivered asynchronously. "
        "Never for inventory/status questions or tasks the user wants done right here. "
        "Not for coding panes in the Agentic IDE (T1, or a named Claude Code / Codex "
        "session): those go through workspace-orchestrate. Pass the agent's name as heard; "
        "the app matches misheard names and, when unsure, returns needs_clarification with "
        "a question to ask before calling again. "
        "Turn the user's intent into an actionable brief: objective, known target, relevant "
        "context, scope, constraints and completion evidence. Do not merely paraphrase or "
        "invent facts. Include context and completion_criteria so the agent can act independently. "
        "Select reply_policy=always for requested findings, on_error for work without a "
        "requested success report, none only for explicit silence. Report the acknowledgement "
        "and state exactly. Keep the "
        "returned assignment_id and trace_id for society_status; never speak those ids."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": (
                    "The agent's name as the user said it; empty when the user did not "
                    "name one (the best-fitting agent is picked from the task)."
                ),
            },
            "task": {
                "type": "string",
                "description": (
                    "An actionable objective and scope faithful to the user's intent, "
                    "not just a paraphrase. " + AGENT_BRIEF_RULE
                ),
            },
            "reply_policy": REPLY_POLICY_SCHEMA,
            "context": {
                "type": "string",
                "description": "Relevant prior decisions, constraints and facts; omit secrets.",
            },
            "completion_criteria": {
                "type": "string",
                "description": "Required output and the evidence needed to establish completion.",
            },
            "refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relevant file, wiki or conversation references.",
            },
        },
        "required": ["task"],
    }
    is_action_tool: bool = True

    def __init__(self, *, runtime_resolver: RuntimeResolver) -> None:
        self._resolve = runtime_resolver

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        lang = _lang(args, ctx)
        target_key = str(args.get("agent") or "").strip()
        task = str(args.get("task") or "").strip()
        if not task:
            return ToolResult(success=False, output=_NOT_READY[lang], error="task required")
        runtime = await self._runtime()
        if runtime is None:
            return ToolResult(success=False, output=_NOT_READY[lang], error="society unavailable")
        match_info = None
        if target_key:
            found = await lookup_agent(runtime, target_key, context=task, surface=self.name)
            if found.agent is None:
                return await _unresolved(found, lang)
            target, match_info = found.agent, found.match_info()
        else:
            target = runtime.pick_agent(task)
        if target is None:
            return ToolResult(success=False, output=_NO_FIT[lang], error="no_agent_fits")
        from dodaios.society.delegation_wait import ledger_job_id
        from dodaios.society.events import MsgType

        try:
            policy = select_reply_policy(args.get("reply_policy"), MsgType.ASSIGN)
        except (TypeError, ValueError) as exc:  # Invalid policy returns a failed tool result.
            return ToolResult(success=False, output=None, error=str(exc))
        context = str(args.get("context") or "").strip()
        criteria = str(args.get("completion_criteria") or "").strip()
        brief = task
        if context:
            brief += "\n\nRelevant context:\n" + context
        if criteria:
            brief += "\n\nCompletion criteria:\n" + criteria
        refs = args.get("refs") or []
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            return ToolResult(success=False, output=None, error="refs must be a list of strings")
        if len(brief) > 20_000 or len(refs) > 20:
            return ToolResult(success=False, output=None, error="assignment context exceeds limit")
        env = await runtime.say(
            from_agent=runtime.lead_id,
            to_agent=target.agent_id,
            text=brief,
            trace_id=f"voice:{ctx.trace_id.hex[:12]}",
            msg_type=MsgType.ASSIGN,
            payload={
                "text": brief, "refs": refs, "reply_policy": policy,
                **origin_metadata(language=lang),
            },
        )
        # The scheduler answered synchronously on the same trace: a CLAIM
        # means the agent took it, a VETO says why not — say so, no waiting.
        outcome = None
        for event in await runtime.store.events_for_trace(env.trace_id):
            if event.parent_event_id == env.event_id and event.msg_type in (
                MsgType.CLAIM,
                MsgType.VETO,
            ):
                outcome = event
                break
        tracking = {
            "agent_id": target.agent_id,
            "agent_name": display_name(target),
            "assignment_id": env.event_id,
            # The handle for job_status / await_jobs.
            "job_id": ledger_job_id(env),
            "trace_id": env.trace_id,
            "reply_policy": policy,
            # Said differently than it is spelled: the reply names the agent
            # that was actually reached, so the user hears who got the task.
            **({"name_match": match_info} if match_info else {}),
        }
        if outcome is not None and outcome.msg_type is MsgType.VETO:
            reason = str(outcome.payload.get("text") or outcome.payload.get("reason") or "")
            return ToolResult(
                success=False,
                output={
                    **tracking,
                    "state": "refused",
                    "acknowledgement": _REFUSED[lang].format(
                        name=display_name(target), reason=reason
                    ),
                },
                error=str(outcome.payload.get("reason") or "vetoed"),
            )
        ack = _ACK if policy == "always" else _ERROR_ACK if policy == "on_error" else _QUIET_ACK
        return ToolResult(
            success=True,
            output={
                **tracking,
                "state": "running" if outcome is not None else "recorded",
                "acknowledgement": (ack if outcome is not None else _QUEUED)[lang].format(
                    name=display_name(target),
                ),
            },
            artifacts=(
                f"agent:{target.agent_id}",
                f"assignment:{env.event_id}",
                f"trace:{env.trace_id}",
            ),
        )

    async def _runtime(self) -> Any | None:
        try:
            runtime = self._resolve()
            if runtime is not None:
                prepare = getattr(runtime, "prepare_context", None)
                if callable(prepare):
                    if not await prepare():
                        return None
                else:
                    await runtime.ensure_started()
        except Exception:  # noqa: BLE001 — a missing society is a spoken "not ready"
            log.warning("delegate_to_agent: society runtime unavailable", exc_info=True)
            return None
        return runtime


def _join(names: list[str], lang: str) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + _OR[lang] + names[-1]


async def _unresolved(found: AgentLookup, lang: str) -> ToolResult:
    """The honest answer for a name no agent clearly carries: ask, or list who exists.

    Never a silent "unknown": a close name becomes a question, and a name that
    is no Jarvis agent but a coding pane in the Agentic IDE says so, because
    the two kinds of agent are reached through different tools.
    """
    if found.decision == "ask" and found.candidates:
        names = [display_name(a) for a in found.candidates]
        return ToolResult(
            success=False,
            output={
                "status": "needs_clarification",
                "heard": found.heard,
                "candidates": names,
                "question": _ASK_AGENT[lang].format(names=_join(names, lang)),
                "next_step": "Ask the user this question; call again with the confirmed name.",
            },
            error="target_ambiguous",
        )
    reply = _NO_AGENT[lang].format(target=found.heard)
    names = found.available_names()
    roster = _AVAILABLE[lang].format(names=", ".join(names)) if names else _EMPTY_ROSTER[lang]
    reply += " " + roster
    hint = await asyncio.to_thread(coding_pane_hint, found.heard)
    if hint:
        panes = ", ".join(f"{p['agent']} ({p['workspace']})" for p in hint["panes"])
        reply += (
            f" Note: '{found.heard}' matches a coding pane in the Agentic IDE ({panes}), not a "
            "Dodaios agent - reach it with workspace-orchestrate (resolve, then send)."
        )
    return ToolResult(success=False, output=reply, error="target_unknown")


async def _status_target(runtime: Any, target_key: str, lang: str) -> Any:
    """The agent a status question names, or the ``ToolResult`` that explains why not."""
    found = await lookup_agent(runtime, target_key, surface="society_status")
    if found.agent is not None:
        return found.agent
    return await _unresolved(found, lang)


# How much of an agent's newest note the team board repeats.
_BOARD_NOTE_CHARS = 200


_STATUS_MODES: Final[frozenset[str]] = frozenset({"summary", "agent", "assignment", "events"})
_EVENT_TEXT_CHARS = 600


def _page_limit(value: Any, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):  # a missing or non-numeric limit means the default page size
        return default
    return max(1, min(number, 100))


def _event_row(event: Any) -> dict[str, Any]:
    """One board event as a compact row: who, what, when and the start of its text."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    row: dict[str, Any] = {
        "seq": event.seq,
        "type": str(event.msg_type),
        "from": event.from_agent,
        "to": event.to_agent,
        "trace_id": event.trace_id,
        "ts_ms": event.ts_ms,
    }
    if payload.get("status"):
        row["status"] = str(payload["status"])
    text = " ".join(event.text.split())
    if text:
        row["text"] = text[:_EVENT_TEXT_CHARS] + ("…" if len(text) > _EVENT_TEXT_CHARS else "")
    return row


async def _status_summary(runtime: Any, lang: str) -> ToolResult:
    """One line per agent: id, name, seat, busy or idle, state of its last result."""
    from dodaios.society.events import MsgType

    rows = []
    for agent in await runtime.roster.list():
        if agent.agent_id == runtime.lead_id:
            continue
        recent = await runtime.store.events_for_agent(agent.agent_id, limit=20)
        last = next(
            (
                e
                for e in reversed(recent)
                if e.msg_type is MsgType.RESULT and e.from_agent == agent.agent_id
            ),
            None,
        )
        seat = "/".join(part for part in (agent.provider, agent.model) if part) or "default"
        row: dict[str, Any] = {
            "id": agent.agent_id,
            "name": display_name(agent),
            "seat": seat,
            "state": "busy" if runtime.scheduler.active_runs(agent.agent_id) > 0 else "idle",
            "last_result": str(last.payload.get("status") or "finished") if last else None,
        }
        if str(agent.state) != "active":
            row["roster_state"] = str(agent.state)
        rows.append(row)
    if not rows:
        return ToolResult(success=True, output=_EMPTY_ROSTER[lang])
    return ToolResult(
        success=True,
        output={
            "agents": rows,
            "total": len(rows),
            "next": (
                "Pass agent (mode=agent) for one agent in detail, mode=events for the "
                "recorded events, assignment_id for one assignment."
            ),
        },
    )


async def _status_events(
    runtime: Any, args: dict[str, Any], target_key: str, lang: str
) -> ToolResult:
    """One page of recorded board events, newest first, with a cursor to older ones."""
    agent_id = None
    if target_key:
        target = await _status_target(runtime, target_key, lang)
        if isinstance(target, ToolResult):
            return target
        agent_id = target.agent_id
    before = None
    cursor = str(args.get("cursor") or "").strip()
    if cursor:
        if not cursor.isdigit():
            return ToolResult(success=False, output=None, error="invalid cursor")
        before = int(cursor)
    limit = _page_limit(args.get("limit"), default=20)
    page = await runtime.store.events_page(agent_id=agent_id, before_seq=before, limit=limit + 1)
    more = len(page) > limit
    page = page[:limit]
    return ToolResult(
        success=True,
        output={
            "events": [_event_row(e) for e in page],
            "next_cursor": str(page[-1].seq) if more and page else None,
        },
    )


class SocietyStatusTool:
    """What an agent (or the whole team) is doing — read-only, no model call."""

    name: str = "society_status"
    risk_tier: str = "safe"
    description: str = (
        "Answer 'what is <agent> doing?', 'is Scout done?', 'who is on the team?' from the "
        "agent society's board. Read-only. By default it returns a summary: one line per "
        "agent (id, name, seat, busy or idle, state of its last result), small enough to "
        "read in full. Go deeper only when you need to: mode=agent (with agent) gives one "
        "agent's responsibilities, capabilities, state and recorded activity/cost statistics "
        "(observations, not quality scores; details=true with agent is the same); "
        "mode=assignment (with assignment_id) gives one assignment with its task and result; "
        "mode=events pages through the recorded events, newest first (agent optional; pass "
        "the returned next_cursor as cursor for older ones). Pass the agent's name for a "
        "one-sentence status. Set board=true for one short row per agent: working or idle, "
        "and its newest note. If prior tool ids are no longer in context, use agent + "
        "latest_assignment=true to retrieve the newest assignment you sent that agent from "
        "the stored board, including its task and result. This means newest assignment, "
        "not an arbitrary recent event. If 'that task' could mean an older task or several "
        "agents, clarify the agent/task first."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "An agent's name; omit for the team."},
            "mode": {
                "type": "string",
                "enum": ["summary", "agent", "assignment", "events"],
                "description": (
                    "summary (default): one line per agent. agent: one agent in detail. "
                    "assignment: one assignment. events: recorded events, paged."
                ),
            },
            "details": {
                "type": "boolean",
                "description": "With agent: the same as mode=agent. Without: the summary.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": (
                    "mode=events: events per page (default 20); "
                    "mode=agent: events shown (default 10)."
                ),
            },
            "cursor": {
                "type": "string",
                "description": "mode=events: the next_cursor of the previous page.",
            },
            "board": {
                "type": "boolean",
                "description": "One short row per agent: working or idle, and its newest note.",
            },
            "assignment_id": {"type": "string", "description": "Assignment event id."},
            "trace_id": {"type": "string", "description": "Optional expected assignment trace."},
            "latest_assignment": {
                "type": "boolean",
                "description": (
                    "With agent: inspect the newest assignment you sent. "
                    "Do not combine with assignment_id."
                ),
            },
        },
    }

    def __init__(self, *, runtime_resolver: RuntimeResolver) -> None:
        self._resolve = runtime_resolver

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        lang = _lang(args, ctx)
        try:
            from dodaios.society.events import MsgType

            runtime = self._resolve()
            if runtime is not None:
                prepare = getattr(runtime, "prepare_context", None)
                if callable(prepare):
                    if not await prepare():
                        runtime = None
                else:
                    await runtime.ensure_started()
        except Exception:  # noqa: BLE001 — see DelegateToAgentTool._runtime
            log.warning("society_status: runtime resolver failed", exc_info=True)
            runtime = None
        if runtime is None:
            return ToolResult(success=False, output=_NOT_READY[lang], error="society unavailable")
        assignment_id = str(args.get("assignment_id") or "").strip()
        trace_id = str(args.get("trace_id") or "").strip()
        target_key = str(args.get("agent") or "").strip()
        latest_assignment = args.get("latest_assignment") is True
        if str(args.get("mode") or "").strip().lower() == "assignment" and not (
            assignment_id or trace_id or latest_assignment
        ):
            return ToolResult(success=False, output=None, error="assignment_id required")
        if assignment_id or trace_id or latest_assignment:
            if latest_assignment and assignment_id:
                return ToolResult(
                    success=False, output=None, error="choose assignment_id or latest_assignment"
                )
            if latest_assignment:
                if not target_key:
                    return ToolResult(success=False, output=None, error="agent required")
                target = await _status_target(runtime, target_key, lang)
                if isinstance(target, ToolResult):
                    return target
                assignment = await runtime.store.latest_assignment_for_agent(
                    target.agent_id,
                    from_agent=runtime.lead_id,
                )
            elif assignment_id:
                assignment = await runtime.store.get_event(assignment_id)
            else:
                return ToolResult(success=False, output=None, error="assignment_id required")
            if assignment is None or assignment.msg_type is not MsgType.ASSIGN:
                return ToolResult(success=False, output=None, error="assignment_unknown")
            if trace_id and trace_id != assignment.trace_id:
                return ToolResult(success=False, output=None, error="assignment_trace_mismatch")
            assignment_id, trace_id = assignment.event_id, assignment.trace_id
            events = await runtime.store.events_for_trace(trace_id)
            related = [
                e
                for e in events
                if e.parent_event_id == assignment_id
                and e.msg_type in (MsgType.CLAIM, MsgType.RESULT, MsgType.VETO)
            ]
            # The fallback mission runner's bridge publishes its terminal result
            # on mission:<run_id>, without the original assignment parent. Follow
            # only the scheduler's matching claim and verify both run and owner;
            # another mission or agent must never complete this assignment.
            run_ids = {
                str(event.payload["run_id"])
                for event in related
                if event.msg_type is MsgType.CLAIM
                and event.from_agent == assignment.to_agent
                and event.payload.get("run_id")
            }
            for run_id in run_ids:
                if run_id.startswith("turn:"):
                    continue
                mission_events = await runtime.store.events_for_trace(f"mission:{run_id}")
                related.extend(
                    event
                    for event in mission_events
                    if event.msg_type is MsgType.RESULT
                    and event.from_agent == assignment.to_agent
                    and event.payload.get("run_id") == run_id
                )
            related.sort(key=lambda event: event.seq or 0)
            last = related[-1] if related else None
            state = "recorded"
            if last is not None:
                state = {
                    MsgType.CLAIM: "running",
                    MsgType.VETO: "refused",
                    MsgType.RESULT: str(last.payload.get("status") or "finished"),
                }[last.msg_type]
            return ToolResult(
                success=True,
                output={
                    "assignment_id": assignment_id,
                    "trace_id": trace_id,
                    "state": state,
                    "assignment": assignment.model_dump(mode="json"),
                    "events": [e.model_dump(mode="json") for e in related],
                },
            )
        mode = str(args.get("mode") or "").strip().lower()
        if mode and mode not in _STATUS_MODES:
            return ToolResult(
                success=False, output=None, error=f"mode must be one of {sorted(_STATUS_MODES)}"
            )
        if mode == "events":
            return await _status_events(runtime, args, target_key, lang)
        if mode == "agent" or (args.get("details") is True and target_key):
            if not target_key:
                return ToolResult(success=False, output=None, error="agent required")
            target = await _status_target(runtime, target_key, lang)
            if isinstance(target, ToolResult):
                return target
            limit = _page_limit(args.get("limit"), default=10)
            recent = await runtime.store.events_for_agent(target.agent_id, limit=limit)
            return ToolResult(
                success=True,
                output={
                    "agents": [
                        {
                            "agent": target.to_dict(),
                            "active_runs": runtime.scheduler.active_runs(target.agent_id),
                            "stats": await runtime.store.agent_stats(target.agent_id),
                            "recent_events": [_event_row(e) for e in reversed(recent)],
                        }
                    ],
                    "measurement_note": (
                        "Runs count recorded RESULT events and finished chat turns, once "
                        "each and including failures; costs are recorded costs only. No "
                        "independent quality rating is available. Recent events are newest "
                        "first; mode=events pages further back."
                    ),
                },
            )
        if args.get("board") is True:
            rows = []
            for agent in await runtime.roster.list():
                if agent.agent_id == runtime.lead_id:
                    continue
                running = runtime.scheduler.active_runs(agent.agent_id)
                recent = await runtime.store.events_for_agent(agent.agent_id, limit=10)
                note = next((e.text for e in reversed(recent) if e.text), "")
                # What it was asked to do says more than "took the task".
                task = next(
                    (e.text for e in reversed(recent) if e.msg_type is MsgType.ASSIGN and e.text),
                    "",
                ) if running > 0 else ""
                rows.append(
                    {
                        "agent": display_name(agent),
                        "state": "working" if running > 0 else "idle",
                        **({"runs": running} if running > 1 else {}),
                        **({"task": " ".join(task.split())[:_BOARD_NOTE_CHARS]} if task else {}),
                        **({"latest": " ".join(note.split())[:_BOARD_NOTE_CHARS]} if note else {}),
                    }
                )
            return ToolResult(success=True, output={"agents": rows})
        if not target_key:
            return await _status_summary(runtime, lang)
        target = await _status_target(runtime, target_key, lang)
        if isinstance(target, ToolResult):
            return target
        if runtime.scheduler.active_runs(target.agent_id) > 0:
            events = await runtime.store.events_for_agent(target.agent_id, limit=5)
            text = next((e.text for e in reversed(events) if e.text), "")
            return ToolResult(
                success=True,
                output=_STATUS_WORKING[lang].format(name=display_name(target), text=text),
            )
        events = await runtime.store.events_for_agent(target.agent_id, limit=1)
        if not events:
            return ToolResult(
                success=True, output=_STATUS_IDLE[lang].format(name=display_name(target))
            )
        last = events[-1]
        return ToolResult(
            success=True,
            output=_STATUS_LAST[lang].format(
                name=display_name(target), kind=str(last.msg_type).lower(), text=last.text[:200]
            ),
        )
