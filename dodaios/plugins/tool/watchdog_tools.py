"""``watchdog_status`` and ``watchdog_act``: the lead's handle on the watchdog.

The watchdog (:mod:`dodaios.orchestrator.watchdog`) checks every few minutes for
work that is stuck or drifting, repairs what is safe and reversible, and writes ONE
notice for the rest. These two tools answer "what is stuck, what did you repair
today?" and run the one-click actions a notice offers.

* ``watchdog_status`` is read-only and returns a bounded summary.
* ``watchdog_act`` performs one action a finding offers (nudge a turn, stop a turn,
  close a turn nothing runs, re-queue interrupted work, mark work interrupted,
  dismiss) or changes the watchdog's two switches. Each is reversible or merely
  records the person's decision; nothing here deletes anything.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator.watchdog import checks, supervisor
from dodaios.orchestrator.watchdog.store import WatchdogStore

log = logging.getLogger(__name__)

_DAY_MS: Final[int] = 24 * 3600 * 1000
_OPEN_MAX: Final[int] = 10
_LOG_MAX: Final[int] = 15
_ACTIONS: Final[tuple[str, ...]] = (
    checks.ACT_NUDGE, checks.ACT_STOP_TURN, checks.ACT_CLOSE_TURN, checks.ACT_REQUEUE,
    checks.ACT_MARK_INTERRUPTED, checks.ACT_DISMISS, "set_judge", "set_checks",
)


def _store() -> tuple[WatchdogStore, bool]:
    """The running watchdog's store, else the file on disk (``running`` is False)."""
    running = supervisor.current()
    if running is not None:
        return running.store, True
    from dodaios.core.config import DATA_DIR

    return WatchdogStore(Path(DATA_DIR) / supervisor.STORE_FILE), False


def _row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["key"], "kind": row["kind"], "title": row["title"],
        "evidence": row["evidence"], "actions": row["actions"],
        "since_min": max(1, (int(time.time() * 1000) - int(row["first_ms"])) // 60000),
        "told": bool(row["notified_ms"]),
    }
    if row.get("repair_result"):
        out["repair"] = row["repair_result"]
    if row.get("judge_note"):
        out["judge"] = row["judge_note"]
    return out


class WatchdogStatusTool:
    name: str = "watchdog_status"
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "What the watchdog found: work that looks stuck or is going in circles (silent "
        "turns, jobs with no progress, repeated identical tool calls, tasks claimed and "
        "never reported, routines that did not run, failing provider seats), what it "
        "repaired on its own in the last 24 hours, and when the app was down. Read-only "
        "and bounded. Use it when asked 'what is stuck?' or 'what did you repair today?'."
    )
    schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        store, running = _store()
        try:
            now = int(time.time() * 1000)
            events = store.events_since(now - _DAY_MS, 200)
            repaired = [e["detail"] for e in events if e["event"] == "repaired"][:_LOG_MAX]
            opened = store.open_findings(_OPEN_MAX + 1)
            watchdog = supervisor.current()
            output: dict[str, Any] = {
                "running": running,
                "settings": store.settings(),
                "open": [_row(r) for r in opened[:_OPEN_MAX]],
                "open_more": len(opened) > _OPEN_MAX,
                "repaired_last_24h": repaired,
                "recent_log": [
                    {"event": e["event"], "kind": e["kind"], "detail": e["detail"],
                     "age_min": max(0, (now - e["ts_ms"]) // 60000)}
                    for e in events[:_LOG_MAX]
                ],
            }
            if watchdog is not None and watchdog.last_scan_ms:
                output["last_scan_min_ago"] = max(0, (now - watchdog.last_scan_ms) // 60000)
            if not opened:
                output["summary"] = "Nothing looks stuck."
            return ToolResult(True, output)
        except Exception as exc:  # noqa: BLE001
            log.warning("watchdog_status: unavailable", exc_info=True)
            return ToolResult(False, "", f"The watchdog is unavailable: {exc}")
        finally:
            if not running:
                store.close()


class WatchdogActTool:
    name: str = "watchdog_act"
    risk_tier: str = "monitor"
    is_action_tool: bool = True
    description: str = (
        "Run one action a watchdog finding offers. 'id' is the finding id from the "
        "notice or watchdog_status; 'action' must be one of the actions listed on that "
        "finding: nudge (ask a silent turn for a status), stop_turn, close_turn (a turn "
        "nothing runs any more), requeue (run interrupted work again, once), "
        "mark_interrupted (give up on stuck work), dismiss. Also "
        "set_judge / set_checks with 'enabled' to switch the optional progress judge "
        "(subscription or local models only, off by default) or the checks themselves."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "id": {"type": "string", "description": "Finding id (not for set_*)."},
            "enabled": {"type": "boolean", "description": "For set_judge / set_checks."},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        action = str((args or {}).get("action") or "").strip()
        if action not in _ACTIONS:
            return ToolResult(False, "", f"'action' must be one of: {', '.join(_ACTIONS)}.")
        watchdog = supervisor.current()
        if watchdog is None:
            return ToolResult(False, "", "The watchdog is not running.")
        store = watchdog.store
        if action in ("set_judge", "set_checks"):
            if not isinstance((args or {}).get("enabled"), bool):
                return ToolResult(False, "", "'enabled' must be true or false.")
            name = "judge" if action == "set_judge" else "checks"
            settings = store.save_settings(**{name: args["enabled"]})
            store.log("settings", detail=f"{name}={args['enabled']}")
            return ToolResult(True, {"settings": settings})
        key = str(args.get("id") or "").strip()
        row = store.get(key)
        if row is None:
            return ToolResult(False, "", "Unknown finding id.")
        if action not in row["actions"]:
            return ToolResult(False, "", f"That finding does not offer '{action}'.")
        try:
            done = await _perform(watchdog, action, row)
        except Exception as exc:  # noqa: BLE001
            log.warning("watchdog_act: %s failed", action, exc_info=True)
            return ToolResult(False, "", f"The action failed: {exc}")
        outcome = "ok" if done else "no effect"
        store.log("action", key=key, kind=row["kind"], detail=f"{action}: {outcome}")
        if done and action != checks.ACT_DISMISS:
            store.dismiss(key)
        return ToolResult(True, {"action": action, "done": bool(done)})


async def _perform(watchdog: supervisor.Watchdog, action: str, row: dict[str, Any]) -> bool:
    if action == checks.ACT_DISMISS:
        return watchdog.store.dismiss(row["key"])
    actions = watchdog.actions
    job_id = str((row.get("evidence") or {}).get("job_id") or "")
    if action == checks.ACT_NUDGE:
        return bool(await actions.nudge(row["open_ref"]))
    if action == checks.ACT_STOP_TURN:
        return bool(await actions.stop_turn(row["open_ref"]))
    if action == checks.ACT_CLOSE_TURN:
        return bool(await actions.close_turn(row["open_ref"]))
    if action == checks.ACT_REQUEUE:
        return bool(await actions.requeue(job_id))
    if action == checks.ACT_MARK_INTERRUPTED:
        return bool(await actions.mark_interrupted(job_id))
    return False


__all__ = ["WatchdogActTool", "WatchdogStatusTool"]
