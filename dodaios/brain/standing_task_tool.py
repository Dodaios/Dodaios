"""``standing_task``: the lead looks after something for the owner, with no end date.

A standing task is an ongoing responsibility (a campaign, an inbox, a launch, numbers
someone checks by hand). Unlike a routine it carries working notes from run to run, sets
its own pace after each run, has an autonomy level with limits the owner wrote, and can
exist as a proposal the owner accepts with one click or one word. The store, the backing
routine and the run prompt live in :mod:`dodaios.standing_tasks`; this tool is the lead's
hand on them. See ``docs/standing-tasks.md``.

Who may do what is decided from trusted provenance, never from an argument:

* ``take_on``, ``accept``, raising autonomy and changing ``limits`` need the owner's own
  message in the lead's chat (``current_chat_turn`` with ``direct_user``) and an exact
  quote from it, the rule ``society_propose_change`` uses for ``apply``. A ``take_on``
  without that is not refused: it is stored as a proposal for the owner to accept.
* ``resume``, ``run_now`` and ``end`` need the owner's own message too (no quote): a run
  nobody started must not undo a pause or start work that bills as a manual start.
* ``report`` is accepted only from the run of that task's own backing routine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult, current_chat_turn
from dodaios.standing_tasks.models import (
    AUTONOMY,
    MAX_INTERVAL_MIN,
    MIN_INTERVAL_MIN,
    StandingError,
)
from dodaios.standing_tasks.work_order import REPORTABLE, pace

log = logging.getLogger(__name__)

_READS: Final[frozenset[str]] = frozenset({"list", "status"})
_ACTIONS: Final[tuple[str, ...]] = (
    "take_on", "propose", "accept", "decline", "list", "status", "update",
    "pause", "resume", "end", "run_now", "report", "note",
)
#: What a run nobody started must be able to call without an approval card: these write
#: Dodaios' own record of a task and start nothing (the tier ``society_propose_change``
#: gives a proposal). A standing-task run of level watch or prepare is an ask-mode chat,
#: where any higher tier would wait for a click nobody is there to give.
_NO_CARD: Final[frozenset[str]] = frozenset({*_READS, "report", "note", "propose"})
#: What only the owner's own message starts (no quote needed): see the module docstring.
_OWNER_ONLY: Final[frozenset[str]] = frozenset({"resume", "run_now", "end"})
#: Fields ``update`` may carry besides the id.
_UPDATE_FIELDS: Final[tuple[str, ...]] = ("title", "goal", "how", "autonomy", "limits")
#: A quote shorter than this must be the owner's whole message ("ja", "ok", "yes").
_SHORT_QUOTE_CHARS: Final[int] = 4
#: A list answer names at most this many tasks and quotes this much of each notes text.
_LIST_LIMIT: Final[int] = 50
_LIST_NOTES_CHARS: Final[int] = 400
_STATUS_RUNS: Final[int] = 10

_UNAVAILABLE: Final[str] = "Standing tasks are unavailable"
_NOT_OWNER_NOTE: Final[str] = (
    "Not started. This call did not carry the owner's own request from their current "
    "message, so it is stored as a proposal. Tell the owner in one sentence what you "
    "would look after and wait for their yes; then call accept with their words."
)
_UNATTENDED_NOTE: Final[str] = (
    "Not started. A run nobody started cannot take on a standing task, so it is stored as "
    "a proposal and shown to the owner in their conversation. Do not start the work."
)
_PROPOSED_NOTE: Final[str] = (
    "Proposed, not started. The owner sees it in their conversation. Mention it in one "
    "sentence; when they say yes, call accept with their words."
)
_ALREADY_NOTE: Final[str] = (
    "Nothing new was stored: a standing task with this title already exists, and this is "
    "it. Use update to change it."
)
_ACT_NEEDS_LIMITS: Final[str] = (
    "autonomy act needs limits: what may be changed without asking, in the owner's words. "
    "Ask the owner for them, or use prepare."
)


def _rank(autonomy: str) -> int:
    return AUTONOMY.index(autonomy) if autonomy in AUTONOMY else -1


def _iso(ms: Any) -> str | None:
    try:
        value = int(ms or 0)
    except (TypeError, ValueError):  # not a timestamp: the view shows no time
        return None
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _view(task: Any, *, brief: bool = False) -> dict[str, Any]:
    """The stored task as the model reads it: state, pace and the next run in words."""
    data = dict(task.to_dict())
    data["pace"] = pace(task.interval_min)
    data["next_run"] = _iso(data.get("next_run_ms"))
    data["last_run"] = _iso(data.get("last_run_ms"))
    notes = str(data.get("notes") or "")
    if brief and len(notes) > _LIST_NOTES_CHARS:
        data["notes"] = notes[: _LIST_NOTES_CHARS - 1].rstrip() + "…"
    return data


def _noted(task: Any, note: str) -> dict[str, Any]:
    """A proposal read back with what to do next; the service may answer with the task
    that already exists under this title, which is no new proposal."""
    proposed = str(getattr(task, "state", "")) == "proposed"
    return {**_view(task), "note": note if proposed else _ALREADY_NOTE}


def _text(args: dict[str, Any], key: str) -> str:
    return str(args.get(key) or "").strip()


def _minutes(args: dict[str, Any], key: str) -> int | None:
    """An interval argument as whole minutes; ``None`` when it was not given."""
    raw = args.get(key)
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise StandingError("invalid", f"{key} must be a whole number of minutes.")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise StandingError("invalid", f"{key} must be a whole number of minutes.") from None


def _run_task_id(turn: Any) -> str:
    """The routine task id of the unattended run this call belongs to, or ``""``.

    Read from what the app itself set: the run's chat is
    ``<owner chat>:routine:<task id>:<run>`` (``society.routine_runner``), and the runner
    wraps the turn in ``autonomy_origin(task_id=...)``. The second does not cross the MCP
    boundary of a CLI seat; the first does (``agent_chat.tool_context``). A turn the owner
    typed is never a run.
    """
    if turn is not None and getattr(turn, "direct_user", False):
        return ""
    if turn is not None:
        from dodaios.society.routine_runner import ROUTINE_SESSION_MARKER

        _, marker, tail = str(getattr(turn, "session_id", "") or "").partition(
            ROUTINE_SESSION_MARKER
        )
        task_id = tail.rpartition(":")[0] if marker else ""
        if task_id:
            return task_id
    from dodaios.safety.reversibility import origin_refs

    return str(origin_refs().get("task_id") or "")


def _gateway_lead_session(session_id: str) -> bool:
    """Whether ``session_id`` is one of the lead's chats, asked of the running app."""
    from dodaios.core import runtime_refs

    check = getattr(runtime_refs.get_supervisor_tool_gateway(), "is_lead_session", None)
    try:
        return bool(check(session_id)) if callable(check) else False
    except Exception:  # noqa: BLE001 - an unknown session is not the lead's chat
        return False


class StandingTaskTool:
    name = "standing_task"
    risk_tier = "monitor"
    is_action_tool = False
    #: Every action changes Dodaios' own record of a task and can be taken back, so a
    #: run nobody started may report without an approval (``safety.reversibility``).
    #: What such a run must not do is refused here, in words, not by a card.
    reversibility = "reversible"
    description = (
        "Standing tasks: something the owner wants looked after over time, with no end date "
        "(a campaign, an inbox, a launch, numbers they check by hand). Use this, not a "
        "routine, when the work needs judgement, memory of the last state and its own pace; "
        "a fixed report on a fixed schedule is a routine; a goal with an end is a project. "
        "actions: take_on (title, goal, how, autonomy, limits, check_every_min, request_quote "
        "= the owner's exact words asking for it in their current message; without them it "
        "is stored as a proposal), propose (same fields + reason: suggest one, from any "
        "turn; the owner accepts with one click or one word), accept (standing_id, "
        "request_quote = their yes in their current message), decline, list, status "
        "(standing_id: the task and its last runs), update (standing_id + the fields to "
        "change; raising autonomy or changing limits needs request_quote), pause, resume, "
        "end, run_now, note (standing_id, text: add to the working notes), report (only "
        "inside a run of that task: standing_id, outcome, summary, notes = the full working "
        "notes for the next run, actions[] = what you did, next_check_min = when to look "
        "again). autonomy: watch reads and tells the owner what changed or needs them; "
        "prepare (default) also gets the next step ready and changes nothing outside "
        "Dodaios; act may make changes that stay inside limits (the owner's words, "
        "required), anything else is prepared and asked. Approvals still apply. Every "
        "answer reads back the stored task: state, pace, next run."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "standing_id": {"type": "string", "description": "The task, e.g. st_1a2b3c4d."},
            "title": {"type": "string", "description": "A short name, e.g. Meta ads campaign."},
            "goal": {
                "type": "string",
                "description": "What looking after it means, in the owner's terms.",
            },
            "how": {
                "type": "string",
                "description": "Where to look and with what: accounts, tools, agents, files.",
            },
            "autonomy": {"type": "string", "enum": list(AUTONOMY)},
            "limits": {
                "type": "string",
                "description": (
                    "act: what may be changed without asking, in the owner's words "
                    "(e.g. pause ads above 4 EUR per lead; budget changes up to 10 percent)."
                ),
            },
            "check_every_min": {
                "type": "integer",
                "minimum": MIN_INTERVAL_MIN,
                "maximum": MAX_INTERVAL_MIN,
                "description": "The starting pace in minutes; each run adjusts it.",
            },
            "request_quote": {
                "type": "string",
                "description": (
                    "take_on/accept/update: an exact quote from the owner's current message "
                    "that asks for this."
                ),
            },
            "reason": {
                "type": "string",
                "description": "propose: one sentence on why this would help the owner.",
            },
            "outcome": {"type": "string", "enum": list(REPORTABLE)},
            "summary": {
                "type": "string",
                "description": "report: one or two sentences on what this run found or did.",
            },
            "notes": {
                "type": "string",
                "description": "report: the working notes the next run starts from.",
            },
            "actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "report: what this run did or prepared, one short line each.",
            },
            "next_check_min": {
                "type": "integer",
                "minimum": MIN_INTERVAL_MIN,
                "maximum": MAX_INTERVAL_MIN,
                "description": "report: minutes until the next run; omit to keep the pace.",
            },
            "text": {"type": "string", "description": "note: the line to add."},
            "include_ended": {"type": "boolean", "description": "list: ended ones too."},
        },
        "required": ["action"],
    }

    def __init__(self, *, lead_session: Callable[[str], bool] | None = None) -> None:
        self._lead_session = lead_session or _gateway_lead_session

    # ------------------------------------------------------------ executor hooks

    def risk_tier_for_args(self, args: dict[str, Any]) -> str:
        return "safe" if args.get("action") in _NO_CARD else "monitor"

    def read_only_for_args(self, args: dict[str, Any]) -> bool:
        return args.get("action") in _READS

    def describe_args(self, args: dict[str, Any]) -> dict[str, str]:
        action = str(args.get("action") or "")
        out = {"level": "read" if action in _READS else "modify"}
        if args.get("title") or args.get("goal"):
            out["task"] = str(args.get("title") or args.get("goal"))[:240]
        elif args.get("standing_id"):
            out["task"] = str(args["standing_id"])
        return out

    # ------------------------------------------------------------------ provenance

    def _owner_turn(self, ctx: Any) -> Any | None:
        """The owner's own message in the lead's chat that this call answers, or ``None``."""
        from dodaios.safety.reversibility import unattended_origin

        turn = current_chat_turn.get()
        if turn is None or not turn.direct_user or turn.origin not in ("", "chat"):
            return None
        if unattended_origin(getattr(ctx, "config", None)):
            return None
        return turn if self._lead_session(turn.session_id) else None

    @staticmethod
    def _quoted(turn: Any, args: dict[str, Any]) -> bool:
        """Whether ``request_quote`` is the owner's own words from this message."""
        quote = _text(args, "request_quote")
        said = str(getattr(turn, "user_text", "") or "")
        if not quote or quote not in said:
            return False
        return len(quote) >= _SHORT_QUOTE_CHARS or quote == said.strip()

    # --------------------------------------------------------------------- execute

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        action = str(args.get("action") or "")
        if action not in _ACTIONS:
            return ToolResult(False, "", f"'action' must be one of: {', '.join(_ACTIONS)}.")
        try:
            from dodaios.standing_tasks import service

            return ToolResult(True, await self._run(service, action, args, ctx))
        except StandingError as exc:  # a refusal the model reads in the tool result
            return ToolResult(False, {"code": exc.code}, _failure(exc))
        except Exception as exc:  # noqa: BLE001 - the store is a courtesy surface
            log.warning("standing_task tool: %s failed", action, exc_info=True)
            return ToolResult(False, {"code": "unavailable"}, f"{_UNAVAILABLE}: {exc}")

    async def _run(self, service: Any, action: str, args: dict[str, Any], ctx: Any) -> Any:
        if action == "list" or (action == "status" and not _text(args, "standing_id")):
            tasks = await service.list_tasks(include_ended=bool(args.get("include_ended")))
            return {"tasks": [_view(task, brief=True) for task in tasks[:_LIST_LIMIT]]}
        owner = self._owner_turn(ctx)
        if action == "take_on":
            return await self._take_on(service, args, owner)
        if action == "propose":
            task = await service.propose(**_fields(args), reason=_text(args, "reason"))
            return _noted(task, _PROPOSED_NOTE)
        sid = _text(args, "standing_id")
        if not sid:
            raise StandingError("invalid", f"{action} needs a standing_id (see action list).")
        if action == "status":
            task = await _existing(service, sid)
            runs = await service.runs_of(sid, limit=_STATUS_RUNS)
            return {"task": _view(task), "runs": [run.to_dict() for run in runs]}
        if action == "accept":
            if owner is None or not self._quoted(owner, args):
                raise StandingError(
                    "state",
                    "accept needs the owner's yes in their current message, quoted in "
                    "request_quote. Nothing started; the proposal stays open.",
                )
            return _view(await service.accept(sid, origin_session=owner.session_id))
        if action == "decline":
            return _view(await service.decline(sid))
        if action == "update":
            return await self._update(service, sid, args, owner)
        if action == "pause":
            return _view(await service.pause(sid))
        if action in _OWNER_ONLY:
            if owner is None:
                raise StandingError(
                    "state",
                    f"{action} needs the owner's own message in this conversation. Nothing "
                    "changed; say what you would do and let them decide.",
                )
            call = {"resume": service.resume, "run_now": service.run_now, "end": service.end}
            return _view(await call[action](sid))
        if action == "note":
            text = _text(args, "text")
            if not text:
                raise StandingError("invalid", "note needs text.")
            return _view(await service.add_note(sid, text))
        return await self._report(service, sid, args)

    async def _take_on(self, service: Any, args: dict[str, Any], owner: Any) -> Any:
        fields = _fields(args)
        if owner is not None and self._quoted(owner, args):
            from dodaios.tasks.context import client_timezone

            task = await service.take_on(
                **fields,
                origin="owner",
                origin_session=owner.session_id,
                timezone=client_timezone.get() or "",
            )
            return _view(task)
        reason = _text(args, "reason") or (
            "The assistant suggests looking after this; the owner has not asked for it "
            "in so many words."
        )
        task = await service.propose(**fields, reason=reason)
        turn = current_chat_turn.get()
        typed = turn is not None and turn.direct_user
        return _noted(task, _NOT_OWNER_NOTE if typed else _UNATTENDED_NOTE)

    async def _update(self, service: Any, sid: str, args: dict[str, Any], owner: Any) -> Any:
        task = await _existing(service, sid)
        # An empty string is a field the model left out, never "clear this field".
        changes: dict[str, Any] = {
            key: _text(args, key) for key in _UPDATE_FIELDS if _text(args, key)
        }
        interval = _minutes(args, "check_every_min")
        if interval is not None:
            changes["interval_min"] = interval
        if not changes:
            raise StandingError(
                "invalid",
                "update needs at least one of: title, goal, how, autonomy, limits, "
                "check_every_min.",
            )
        autonomy = changes.get("autonomy")
        if autonomy is not None and autonomy not in AUTONOMY:
            raise StandingError("invalid", f"autonomy must be one of: {', '.join(AUTONOMY)}.")
        widens = autonomy is not None and _rank(autonomy) > _rank(str(task.autonomy))
        relimits = "limits" in changes and changes["limits"] != str(task.limits or "").strip()
        if (widens or relimits) and (owner is None or not self._quoted(owner, args)):
            raise StandingError(
                "state",
                "Raising autonomy or changing limits needs the owner's request in their "
                "current message, quoted in request_quote. Nothing changed; ask them.",
            )
        limits = changes["limits"] if "limits" in changes else str(task.limits or "").strip()
        if (autonomy or str(task.autonomy)) == "act" and not limits:
            raise StandingError("invalid", _ACT_NEEDS_LIMITS)
        return _view(await service.update(sid, **changes))

    @staticmethod
    async def _report(service: Any, sid: str, args: dict[str, Any]) -> Any:
        turn = current_chat_turn.get()
        task = await _existing(service, sid)
        run_task = _run_task_id(turn)
        backing = str(getattr(task, "task_id", "") or "")
        if not run_task or not backing or run_task != backing:
            raise StandingError(
                "state",
                "report is only for a run of this standing task itself. Nothing was "
                "recorded. Use note to add to its working notes, or run_now to start a run.",
            )
        outcome = _text(args, "outcome")
        if outcome not in REPORTABLE:
            # ``failed`` and ``skipped`` are the app's own words for a run, never a model's.
            raise StandingError(
                "invalid", f"outcome must be one of: {', '.join(REPORTABLE)}."
            )
        summary = _text(args, "summary")
        if not summary and outcome != "quiet":
            raise StandingError("invalid", "report needs a summary of one or two sentences.")
        raw_actions = args.get("actions")
        if isinstance(raw_actions, str):
            raw_actions = [raw_actions]
        done = tuple(str(item).strip() for item in (raw_actions or ()) if str(item).strip())
        notes = args.get("notes")
        updated = await service.report(
            sid,
            outcome=outcome,
            summary=summary,
            notes=None if notes is None else str(notes),
            actions=done,
            next_check_min=_minutes(args, "next_check_min"),
            session_id=str(getattr(turn, "session_id", "") or ""),
        )
        return _view(updated)


def _fields(args: dict[str, Any]) -> dict[str, Any]:
    """The task fields of ``take_on`` and ``propose``, checked the same way for both."""
    title, goal = _text(args, "title"), _text(args, "goal")
    if not goal:
        raise StandingError("invalid", "A standing task needs a goal: what to look after.")
    autonomy = _text(args, "autonomy") or "prepare"
    if autonomy not in AUTONOMY:
        raise StandingError("invalid", f"autonomy must be one of: {', '.join(AUTONOMY)}.")
    limits = _text(args, "limits")
    if autonomy == "act" and not limits:
        raise StandingError("invalid", _ACT_NEEDS_LIMITS)
    fields: dict[str, Any] = {
        "title": title or goal[:60],
        "goal": goal,
        "how": _text(args, "how"),
        "autonomy": autonomy,
        "limits": limits,
    }
    interval = _minutes(args, "check_every_min")
    if interval is not None:
        fields["interval_min"] = interval
    return fields


async def _existing(service: Any, sid: str) -> Any:
    task = await service.get_task(sid)
    if task is None:
        raise StandingError("not_found", f"No standing task {sid}.")
    return task


def _failure(exc: StandingError) -> str:
    """One readable sentence per error code; the service's own words lead."""
    code, message = exc.code, str(exc.message or "").strip()
    if code == "not_found":
        return f"{message or 'No such standing task.'} Use action list to see the ids."
    if code == "unavailable":
        return f"{_UNAVAILABLE}: {message}" if message else f"{_UNAVAILABLE} right now."
    if code == "limit":
        return message or "The limit of open standing tasks is reached; end or pause one first."
    return message or "The standing task was not changed."


__all__ = ["StandingTaskTool"]
