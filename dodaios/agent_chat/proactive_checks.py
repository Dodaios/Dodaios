"""The lead's "needs you" checks: it comes to the person only when something matters.

One recurring lead routine (``society/routines.py``), tagged
:data:`CHECK_TAG`, runs every few hours inside waking hours and looks, read
only, at what the person connected: mail, calendar, their agents and the
memories falling due. It writes into the one conversation ONLY when
something is worth saying. A run that finds nothing answers with
:data:`NOTHING` and the delivery drops it (:func:`quiet_result`, called by
the society runtime before it posts a lead notice); such runs post no start
card either (:data:`QUIET_TAG`, honoured by ``routine_runner``).

The checks follow the proactivity settings (``proactive_settings.py``):
level ``off`` removes the routine, the topics decide what it looks at, the
interval how often. Like every unattended run it never bills an API key:
the routine is pinned to the subscription seat the front page runs on when
there is one, and the runner's billing hold applies either way.

Open loops (``open_loops.py``) and the previous result (:data:`ADAPTIVE_TAG`)
join the prompt at run time through :func:`run_context`.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.agent_chat.proactive_settings import (
    ProactiveSettings,
    level_sentence,
    load_settings,
    save_settings,
    topic_sentences,
)

log = logging.getLogger(__name__)

CHECK_TAG: Final[str] = "lead-check:needs-you"
#: A lead routine that posts no start card; an empty / sentinel result is dropped.
QUIET_TAG: Final[str] = "lead-quiet"
#: A lead routine whose previous result is handed to its next run.
ADAPTIVE_TAG: Final[str] = "lead-adaptive"
CHECK_TITLE: Final[str] = "Needs you"
#: The exact reply of a check with nothing worth saying.
NOTHING: Final[str] = "NOTHING_TO_REPORT"
#: How much of the previous result the next run sees.
_LAST_RESULT_CHARS: Final[int] = 1500

_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "cancelled", "failed", "interrupted"})


def check_prompt(settings: ProactiveSettings) -> str:
    """The standing prompt of the check routine for these settings."""
    topics = topic_sentences(settings)
    looked_at = "; ".join(topics) if topics else "the user's calendar"
    return (
        "Quietly check whether anything needs the user right now. Look, read only, "
        f"at: {looked_at}. {level_sentence(settings)} "
        "If something is worth saying, write it in a few short lines, most urgent "
        "first, each with what it is and what the user could do; no headings, no "
        "greeting. Open loops listed below are asked back once, in one friendly "
        f"question each. If nothing is worth saying, reply with exactly {NOTHING} "
        "and nothing else. Never send, change, book, delete or schedule anything."
    )


def cron_expression(settings: ProactiveSettings) -> str:
    """Top of the hour, every ``interval_hours`` from ``from_hour`` to ``to_hour``."""
    return f"0 {settings.from_hour}-{settings.to_hour}/{settings.interval_hours} * * *"


def runs_per_day(settings: ProactiveSettings) -> int:
    """How many checks the schedule fires on one day."""
    return len(range(settings.from_hour, settings.to_hour + 1, settings.interval_hours))


def quiet_result(payload: dict[str, Any]) -> bool:
    """Whether a lead routine's result notice says nothing and must not be posted.

    True for a finished routine result whose text is empty or is the
    :data:`NOTHING` sentinel (with at most a little decoration around it: a
    full stop, quotes, markdown). Failures and skips keep showing.
    """
    if payload.get("kind") != "society_result" or payload.get("source") != "routine":
        return False
    if str(payload.get("status") or "") not in ("done", ""):
        return False
    text = str(payload.get("text") or "").strip()
    if not text:
        return True
    if NOTHING not in text.upper():
        return False
    rest = text.upper().replace(NOTHING, "")
    return len("".join(ch for ch in rest if ch.isalnum())) < 24


async def run_context(task_store: Any, task_id: str, tags: tuple[str, ...]) -> str:
    """Extra prompt text for a lead routine run: the previous result and the open loops.

    Read at run time, so a check always sees the loops that fell due since
    it was scheduled. Marks the loops it hands over as asked, so none is
    asked twice. Best effort: a store without the reader yields "".
    """
    parts: list[str] = []
    if ADAPTIVE_TAG in tags:
        previous = await _previous_result(task_store, task_id)
        if previous:
            parts.append(
                "Your previous result, for context only (do not repeat what is "
                "unchanged; say what is new or different, and drop what resolved):\n"
                + previous
            )
    if CHECK_TAG in tags:
        from dodaios.agent_chat.open_loops import due_loops, mark_asked

        loops = due_loops()
        if loops:
            parts.append(
                "Open loops the user mentioned and that are now due; ask back once "
                "each, in one short question (did it happen?):\n"
                + "\n".join(f"- {loop.text}" for loop in loops)
            )
            mark_asked([loop.id for loop in loops])
    return "\n\n".join(parts)


async def _previous_result(task_store: Any, task_id: str) -> str:
    reader = getattr(task_store, "latest_agent_results", None)
    if reader is None:
        return ""
    try:
        results = await reader([task_id], max_chars=_LAST_RESULT_CHARS)
    except Exception:  # noqa: BLE001 — the run goes on without its history
        log.warning("lead routine: previous result unreadable for %s", task_id, exc_info=True)
        return ""
    text = str(results.get(task_id) or "").strip()
    probe = {"kind": "society_result", "source": "routine", "text": text}
    return "" if quiet_result(probe) else text


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


async def _check_row(task_store: Any) -> dict[str, Any] | None:
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import _tags_of, is_agent_routine

    for row in await task_store.list(limit=1000):
        if (
            is_agent_routine(row, LEAD_AGENT_ID)
            and CHECK_TAG in _tags_of(row)
            and row.get("state") not in _TERMINAL
        ):
            return row
    return None


async def _seat_for_checks(runtime: Any, lead: Any) -> dict[str, str]:
    """The seat the checks are pinned to: the front page's subscription seat
    when there is one, else the lead's own (the runner's billing hold still
    applies to that one)."""
    from dodaios.society.routine_runner import _subscription_seat

    try:
        subscription = await _subscription_seat(runtime.config())
    except Exception:  # noqa: BLE001 — no readable subscription seat: the lead's own
        log.debug("lead checks: subscription seat unreadable", exc_info=True)
        subscription = None
    if subscription is None:
        return {}
    provider, model, effort = subscription
    return {"provider": provider, "model": model, "effort": effort}


def _billed(provider: str, account_id: str) -> bool:
    if not provider:
        return False
    from dodaios.society.routine_runner import _billed_via_api

    try:
        return _billed_via_api(provider, account_id)
    except Exception:  # noqa: BLE001 — unknown seat: say it may bill
        return True


async def checks_state() -> dict[str, Any]:
    """Settings plus the check routine's live state, for the panel.

    ``{"available", "settings", "checks": {"enabled", "task_id", "next_run_ns",
    "last_run_ns", "runs_per_day", "provider", "model", "billed_via_key"}}``.
    """
    runtime = _runtime()
    task_store = runtime.task_services()[0] if runtime is not None else None
    settings = await load_settings(getattr(runtime, "store", None))
    checks: dict[str, Any] = {
        "enabled": False,
        "task_id": "",
        "next_run_ns": None,
        "last_run_ns": None,
        "runs_per_day": runs_per_day(settings),
        "provider": "",
        "model": "",
        "billed_via_key": False,
    }
    if task_store is None:
        return {"available": False, "settings": settings.to_dict(), "checks": checks}
    row = await _check_row(task_store)
    if row is not None:
        from dodaios.society.routines import routine_seat

        spec = await task_store.get_spec(str(row["id"]))
        seat = routine_seat(spec) if spec is not None else {}
        checks.update(
            enabled=row.get("state") != "paused",
            task_id=str(row["id"]),
            next_run_ns=row.get("due_at_ns"),
            last_run_ns=row.get("started_at_ns") or row.get("last_run_ns"),
            provider=seat.get("provider", ""),
            model=seat.get("model", ""),
            billed_via_key=_billed(seat.get("provider", ""), seat.get("account_id", "")),
        )
    return {"available": True, "settings": settings.to_dict(), "checks": checks}


async def apply_settings(settings: ProactiveSettings) -> dict[str, Any]:
    """Save ``settings`` and make the routines match them.

    Level ``off`` removes the check routine; any other level creates or
    rebuilds it with the new prompt and rhythm. A morning brief that exists
    is rebuilt too, so its prompt follows the topics. Raises ``ValueError``
    on a bad zone and ``RuntimeError`` when the society or scheduler is
    not running.
    """
    from zoneinfo import ZoneInfo

    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import build_task_spec, create_routine, manage_routine

    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("The agent society is not running")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise RuntimeError("The task scheduler is unavailable")
    if settings.enabled:
        try:
            ZoneInfo(settings.timezone)
        except Exception as exc:  # noqa: BLE001 — any lookup failure is a bad zone
            raise ValueError("timezone must be an IANA zone such as Europe/Berlin") from exc
    await save_settings(settings, runtime.store)
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RuntimeError("The assistant's agent record is missing")
    existing = await _check_row(task_store)
    if existing is not None:
        await manage_routine(
            lead, {"task_id": str(existing["id"]), "operation": "delete"}, task_store, scheduler
        )
    if settings.enabled:
        spec = build_task_spec(
            lead,
            title=CHECK_TITLE,
            prompt=check_prompt(settings),
            schedule={
                "kind": "cron",
                "expression": cron_expression(settings),
                "timezone": settings.timezone,
            },
            **await _seat_for_checks(runtime, lead),
        )
        spec = spec.model_copy(update={"tags": (*spec.tags, CHECK_TAG, QUIET_TAG, ADAPTIVE_TAG)})
        await create_routine(task_store, scheduler, spec)
        log.info(
            "lead checks: every %sh from %s to %s (%s), level %s",
            settings.interval_hours, settings.from_hour, settings.to_hour,
            settings.timezone, settings.level,
        )
    else:
        log.info("lead checks: off")
    await _rebuild_brief()
    return await checks_state()


async def _rebuild_brief() -> None:
    """The brief's prompt follows the topics: rebuild it in place when it exists."""
    from dodaios.agent_chat.proactive import brief_state, set_brief

    state = await brief_state()
    if not state.get("task_id"):
        return
    try:
        await set_brief(
            enabled=bool(state.get("enabled")),
            local_time=str(state.get("time") or ""),
            timezone=str(state.get("timezone") or ""),
        )
    except (ValueError, RuntimeError):
        # The brief keeps its old prompt; the next brief change rewrites it.
        log.warning("lead checks: the brief was not rebuilt for the new topics", exc_info=True)


__all__ = [
    "ADAPTIVE_TAG",
    "CHECK_TAG",
    "CHECK_TITLE",
    "NOTHING",
    "QUIET_TAG",
    "apply_settings",
    "check_prompt",
    "checks_state",
    "cron_expression",
    "quiet_result",
    "run_context",
    "runs_per_day",
]
