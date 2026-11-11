"""``costs_summary``: what the app spent today and this week, for every lead seat.

A read over the same numbers the Spend & Tokens section shows: totals, then the
split per agent (the lead included) and per provider seat, then the seats that
have a verdict against them right now and, when the subscriptions can be read,
how much of each plan window is left. The lead uses it to answer "what did that
cost" and to pick a seat with headroom before it delegates. It only reads; it
never caps or switches anything (the brain provider is the person's choice).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Final

from dodaios.brain.lead_api import bounded, call_app_api, failure
from dodaios.core.protocols import ExecutionContext, ToolResult

log = logging.getLogger(__name__)

_PERIODS: Final[tuple[str, ...]] = ("today", "week")
_TOP = 10
_HINT = "Ask for one period (period=today or week) or fewer rows (top)."


def _day_start_ms(days_back: int) -> int:
    """Local midnight ``days_back`` days ago, in epoch milliseconds."""
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - timedelta(days=days_back)).timestamp() * 1000)


def _round(value: Any) -> Any:
    return round(value, 4) if isinstance(value, float) else value


def _rows(buckets: Any, top: int, *, named: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in (buckets or [])[:top]:
        if not isinstance(row, dict):
            continue
        item = {
            "key": row.get("key"),
            "cost_usd": _round(row.get("cost_usd")),
            "subscription_usd": _round(row.get("subscription_usd")),
            "tokens": row.get("tokens_total"),
            "calls": row.get("entries"),
        }
        if named:
            item["name"] = row.get("name") or row.get("key")
            item["lead"] = bool(row.get("lead"))
        out.append(item)
    return out


def shape_period(data: Any, top: int) -> dict[str, Any]:
    """One period of ``/api/costs/summary`` as a summary-first answer."""
    data = data if isinstance(data, dict) else {}
    totals = data.get("totals") or {}
    return {
        "totals": {
            "cost_usd": _round(totals.get("cost_usd")),
            "covered_by_subscription_usd": _round(totals.get("subscription_usd")),
            "tokens_total": totals.get("tokens_total"),
            "tokens_in": totals.get("tokens_in"),
            "tokens_out": totals.get("tokens_out"),
            "calls": totals.get("entries"),
            "unpriced_tokens": totals.get("gap_tokens"),
        },
        "by_agent": _rows(data.get("by_agent"), top, named=True),
        "by_seat": _rows(data.get("by_provider"), top),
        "by_model": _rows(data.get("by_model"), top),
        "coding_cli_index_complete": (data.get("index") or {}).get("complete"),
    }


def seat_problems() -> list[dict[str, Any]]:
    """The seats with a verdict against them now (quota, login, model), from the passive record."""
    try:
        from dodaios.brain.seat_health import get_seat_health

        now = time.time()
        return [
            {
                "provider": v.provider,
                "account": v.account or None,
                "kind": v.cls,
                "needs_the_person": v.blocked,
                "reason": v.reason(now=now),
            }
            for v in get_seat_health().troubled()
        ]
    except Exception:  # noqa: BLE001 - the numbers stand without the health line
        log.debug("costs_summary: seat health unavailable", exc_info=True)
        return []


def shape_quota(data: Any) -> list[dict[str, Any]]:
    """Plan windows per subscription: how much is used and when it resets."""
    rows: list[dict[str, Any]] = []
    accounts = data.get("accounts") if isinstance(data, dict) else None
    for account in accounts or []:
        if not isinstance(account, dict):
            continue
        windows = []
        for window in account.get("windows") or []:
            percent = window.get("percent")
            used = float(percent) if isinstance(percent, (int, float)) else None
            windows.append(
                {
                    "window": window.get("scope_label") or window.get("kind"),
                    "used_percent": used,
                    "headroom_percent": None if used is None else round(max(100.0 - used, 0.0), 1),
                    "resets_at": window.get("resets_at"),
                }
            )
        rows.append(
            {
                "platform": account.get("platform"),
                "plan": account.get("plan"),
                "status": account.get("status"),
                "source": account.get("source"),
                "as_of": account.get("as_of"),
                "windows": windows,
            }
        )
    return rows


class CostsSummaryTool:
    name = "costs_summary"
    risk_tier = "safe"
    is_action_tool = False
    description = (
        "What the app spent: today and this week (local days), with the cost and tokens per "
        "agent (the lead included), per provider seat and per model, how much a subscription "
        "covered, and the seats that are in trouble right now (usage limit, login rejected) "
        "with the headroom left in each subscription window. Use it for 'what did that cost', "
        "'how much did the agents use today' and to check a seat has room before you delegate "
        "a long job. Read-only. For a longer range or line items open the Spend & Tokens "
        "section (navigate costs)."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "period": {
                "type": "string",
                "enum": ["both", *_PERIODS],
                "description": "today, week (the last seven local days) or both (default).",
            },
            "top": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": f"Rows per breakdown (default {_TOP}).",
            },
            "quota": {
                "type": "boolean",
                "description": "Also read the subscriptions' plan windows (default true).",
            },
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        period = str(args.get("period") or "both")
        if period not in ("both", *_PERIODS):
            return ToolResult(success=False, output=None, error=f"Unknown period {period!r}.")
        top = min(max(int(args.get("top") or _TOP), 1), 100)
        wanted = _PERIODS if period == "both" else (period,)
        starts = {"today": _day_start_ms(0), "week": _day_start_ms(6)}
        calls = [
            call_app_api(
                "GET",
                "/api/costs/summary",
                query={"since_ms": starts[name], "top": max(top, 12)},
            )
            for name in wanted
        ]
        with_quota = args.get("quota") is not False
        if with_quota:
            calls.append(call_app_api("GET", "/api/agent-accounts/usage"))
        answers = await asyncio.gather(*calls)
        out: dict[str, Any] = {}
        for name, (status, data) in zip(wanted, answers, strict=False):
            if status is None or status >= 400:
                return failure("The cost summary", status, data)
            out[name] = shape_period(data, top)
        problems = seat_problems()
        out["seats_in_trouble"] = problems
        if with_quota:
            status, data = answers[-1]
            if status is not None and status < 400:
                out["subscription_quota"] = shape_quota(data)
            else:
                out["subscription_quota"] = {"unavailable": "The plan windows could not be read."}
        return ToolResult(success=True, output=bounded(out, hint=_HINT))
