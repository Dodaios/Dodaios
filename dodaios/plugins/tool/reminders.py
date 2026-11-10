"""reminders: the assistant's hands on the user's reminders and tasks.

"Remind me Friday at 9 about the taxes" becomes a memory with a due time in
the personal vault (``dodaios/notify/reminders.py``); the sidebar shows it
under "Coming up" and the scheduler delivers it on time as a notice in the
conversation plus a desktop notification. A brain dump ("tomorrow dentist,
buy milk, mail Anna about the offer") is split into separate items and shown
as a list card with an undo per item.

Risk tier: safe; it only writes the local vault and posts a notice.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.notify import reminders

log = logging.getLogger(__name__)

ACTIONS = ("create", "list", "done", "snooze", "capture")


def _vault() -> Any:
    from dodaios.memory.vault.runtime import active

    return active()


def _local(due_at: str | None, zone: Any) -> str:
    if not due_at:
        return ""
    try:
        return datetime.fromisoformat(due_at).astimezone(zone).isoformat(timespec="minutes")
    except ValueError:  # an unreadable stamp is shown as stored rather than hidden
        return due_at


class RemindersTool:
    name: str = "reminders"
    risk_tier: str = "safe"
    description: str = (
        "Set, list, finish or snooze the user's reminders, and turn a list of things "
        "to do into separate tasks. action=create when the user asks to be reminded "
        "of something at a time: pass text (what, without the time words) and when "
        "(an ISO local date-time such as 2026-11-14T09:00, or the time words as said, "
        "e.g. 'Friday at 9', 'in 20 minutes', 'tomorrow evening'); a reminder without "
        "a clear time comes back with needs_time=true, then ask for one. "
        "action=capture when the user lists several things in one go: pass the whole "
        "utterance as text; each item becomes a reminder (if it names a time) or a "
        "task. action=list shows what is coming up; done and snooze take an id from "
        "list. The user sees every change in the app; confirm briefly, never recite "
        "the list back unless asked."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "text": {"type": "string", "description": "What to be reminded of, or the dump."},
            "when": {
                "type": "string",
                "description": "ISO local date-time, or the time words as the user said them.",
            },
            "id": {"type": "string", "description": "Reminder id from list (done, snooze)."},
            "minutes": {
                "type": "integer",
                "minimum": 1,
                "description": "Snooze by this many minutes (default 60) when no 'when' is given.",
            },
            "timezone": {
                "type": "string",
                "description": "The user's IANA zone when known (e.g. Europe/Berlin).",
            },
            "days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        if action not in ACTIONS:
            return ToolResult(success=False, output=None, error=f"action must be one of {ACTIONS}")
        vault = _vault()
        if vault is None:
            return ToolResult(success=False, output=None, error="memory is not running")
        zone = reminders.person_zone(str(args.get("timezone") or "") or None)
        now = datetime.now(zone)
        said = str(getattr(ctx, "user_utterance", "") or "")
        text = str(args.get("text") or "").strip()
        when = str(args.get("when") or "").strip()

        if action == "list":
            days = max(1, min(90, int(args.get("days") or 14)))
            rows = await asyncio.to_thread(reminders.list_due, vault, days=days)
            for row in rows:
                row["due_local"] = _local(row.get("due_at"), zone)
            if not rows:
                return ToolResult(success=True, output="Nothing is coming up.")
            return ToolResult(success=True, output={"items": rows})

        if action == "create":
            if not text and not when and not said:
                return ToolResult(success=False, output=None, error="text is missing")
            due, rest, has_time = reminders.resolve_due(when, now=now, text=text or said)
            rest = rest or text
            if due is None:
                return ToolResult(
                    success=True,
                    output={"needs_time": True, "text": rest, "hint": "ask the user when"},
                )
            if not rest:
                return ToolResult(success=False, output=None, error="text is missing")
            result = await asyncio.to_thread(
                reminders.create_reminder, vault, rest, due, evidence=said, zone=str(zone)
            )
            if result.action == "refused":
                return ToolResult(
                    success=False, output=None, error="not saved: looks like a secret"
                )
            memory = result.memory
            return ToolResult(
                success=True,
                output={
                    "id": memory.id if memory else "",
                    "text": rest,
                    "due_local": due.isoformat(timespec="minutes"),
                    "has_time": has_time,
                    "existing": result.action == "existing",
                },
            )

        if action == "capture":
            dump = text or said
            if not dump:
                return ToolResult(success=False, output=None, error="text is missing")
            rows = await asyncio.to_thread(
                reminders.capture_dump, vault, dump, now=now, evidence=said
            )
            if not rows:
                return ToolResult(success=True, output={"items": [], "note": "nothing to capture"})
            for row in rows:
                row["due_local"] = _local(row.get("due_at"), zone)
            await _post_captured(rows)
            return ToolResult(success=True, output={"items": rows})

        memory_id = str(args.get("id") or "").strip()
        if not memory_id:
            return ToolResult(success=False, output=None, error="id is missing")
        if action == "done":
            ok = await asyncio.to_thread(reminders.mark_done, vault, memory_id)
            if not ok:
                return ToolResult(
                    success=False, output=None, error=f"no open reminder {memory_id!r}"
                )
            return ToolResult(success=True, output="Done.")

        # snooze
        until: datetime | None = None
        if when:
            until, _rest, _has_time = reminders.resolve_due(when, now=now)
        if until is None:
            minutes = int(args.get("minutes") or 60)
            until = now + timedelta(minutes=max(1, minutes))
        moved = await asyncio.to_thread(reminders.snooze, vault, memory_id, until)
        if moved is None:
            return ToolResult(success=False, output=None, error=f"no reminder {memory_id!r}")
        return ToolResult(
            success=True,
            output={
                "id": moved.id,
                "text": moved.text,
                "due_local": until.isoformat(timespec="minutes"),
            },
        )


async def _post_captured(rows: list[dict[str, Any]]) -> None:
    """Show the captured list in the lead conversation (a card with undo per item)."""
    target = reminders.lead_target()
    if target is None:
        return
    svc, session_id = target
    try:
        await reminders.post_notice(
            svc,
            session_id,
            {
                "kind": reminders.NOTICE_CAPTURED,
                "status": "done",
                "text": rows[0]["text"],
                "items": rows,
            },
        )
    except Exception:  # noqa: BLE001 — the items are saved; the card is extra
        log.warning("reminders: captured-list notice not posted", exc_info=True)


__all__ = ["ACTIONS", "RemindersTool"]
