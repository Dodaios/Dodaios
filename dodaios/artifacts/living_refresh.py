"""The refresh half of a living page: one tagged lead routine per page.

A living page (:mod:`.living`) stays current because the lead runs a routine
on its schedule: read the sources the page names, then hand the complete,
current rows back through the ``living_page`` tool (operation ``update``).
The routine is an ordinary lead routine created through the society routines
API (``society/routines.py``), the same way the morning brief is
(``agent_chat/proactive.py``), tagged :data:`TAG_PREFIX` + page id so the
page and its routine find each other.

Like every unattended run it never bills a provider API key: the routine
runner holds a run whose seat would (``routine_runner._hold_unattended_run_off_keys``).
Nothing here touches routine delivery.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.artifacts.living import LivingPage, LivingPageError, LivingPageStore

log = logging.getLogger(__name__)

#: Tag on the refresh routine: ``living-page:<page id>``.
TAG_PREFIX: Final[str] = "living-page:"
_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "cancelled", "failed", "interrupted"})


def tag_for(page_id: str) -> str:
    return f"{TAG_PREFIX}{page_id}"


def refresh_prompt(page: LivingPage) -> str:
    """The routine's standing instruction for one page (English, model-facing)."""
    columns = ", ".join(page.columns)
    return (
        f'Refresh the living page "{page.title}" (page id {page.id}). It tracks: {page.track}\n\n'
        "Read the current state from the person's connected apps and sources. Then call the "
        "living_page tool exactly once with operation \"update\", page_id "
        f'"{page.id}" and the COMPLETE current list of rows (columns: {columns}; an optional '
        '"link" field per row holds its web address). Leave out items that are finished or '
        "gone only when the page's purpose says so. If no source could be read, call it with "
        "operation \"update\", the page_id and a short 'note' saying why, and no rows.\n"
        "Read only: do not send, change, book or delete anything. Your reply is one short "
        "sentence."
    )


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


def _services() -> tuple[Any, Any, Any]:
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("The agent society is not running")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise RuntimeError("The task scheduler is unavailable")
    return runtime, task_store, scheduler


async def _lead(runtime: Any) -> Any:
    from dodaios.society.roster import LEAD_AGENT_ID

    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RuntimeError("The assistant's agent record is missing")
    return lead


async def _routine_rows(task_store: Any, page_id: str) -> list[dict[str, Any]]:
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import _tags_of, is_agent_routine

    tag = tag_for(page_id)
    return [
        row
        for row in await task_store.list(limit=1000)
        if is_agent_routine(row, LEAD_AGENT_ID)
        and tag in _tags_of(row)
        and row.get("state") not in _TERMINAL
    ]


async def _delete_routines(runtime: Any, task_store: Any, scheduler: Any, page_id: str) -> int:
    from dodaios.society.routines import manage_routine

    lead = await _lead(runtime)
    removed = 0
    for row in await _routine_rows(task_store, page_id):
        await manage_routine(
            lead, {"task_id": str(row["id"]), "operation": "delete"}, task_store, scheduler
        )
        removed += 1
    return removed


async def start_refresh(store: LivingPageStore, page_id: str) -> LivingPage:
    """Schedule (or re-schedule) the page's refresh routine and mark it live.

    Raises ``LivingPageError`` for an unknown page, ``RuntimeError`` when the
    society runtime or its scheduler is not running.
    """
    from dodaios.society.routines import build_task_spec, create_routine

    page = store.get(page_id)
    if page is None:
        raise LivingPageError(f"No living page with id {page_id!r}.")
    runtime, task_store, scheduler = _services()
    await _delete_routines(runtime, task_store, scheduler, page_id)
    lead = await _lead(runtime)
    spec = build_task_spec(
        lead,
        title=f"Living page: {page.title}",
        prompt=refresh_prompt(page),
        schedule={"kind": "every", "interval_seconds": page.every_minutes * 60},
    )
    spec = spec.model_copy(update={"tags": (*spec.tags, tag_for(page.id))})
    task_id = await create_routine(task_store, scheduler, spec)
    log.info("living page %s: refresh every %d min (task %s)", page.id, page.every_minutes, task_id)
    return store.set_refresh(page.id, refreshing=True, task_id=task_id)


async def stop_refresh(store: LivingPageStore, page_id: str) -> LivingPage:
    """Delete the page's refresh routine; the page keeps its last rows.

    A page whose society runtime is down is still marked stopped: the person
    asked for it to stop, and a routine that comes back finds no live page.
    """
    page = store.get(page_id)
    if page is None:
        raise LivingPageError(f"No living page with id {page_id!r}.")
    try:
        runtime, task_store, scheduler = _services()
        await _delete_routines(runtime, task_store, scheduler, page_id)
    except RuntimeError:
        log.warning("living page %s: routine not reachable while stopping", page_id)
    return store.set_refresh(page.id, refreshing=False, task_id="")


async def refresh_live(page: LivingPage) -> bool:
    """Whether the page's refresh routine still exists and is not paused.

    The Automations section can delete or pause the routine behind the page's
    back; the page then reads as stopped instead of claiming a refresh.
    """
    if not page.refreshing:
        return False
    try:
        _, task_store, _ = _services()
    except RuntimeError:  # society down: the page's own record is all there is
        return page.refreshing
    rows = await _routine_rows(task_store, page.id)
    return any(row.get("state") != "paused" for row in rows)


async def page_state(store: LivingPageStore, page: LivingPage) -> dict[str, Any]:
    """The page as the UI reads it, with its refresh checked against the routine."""
    data = page.to_dict()
    data["refreshing"] = await refresh_live(page)
    return data


__all__ = [
    "TAG_PREFIX",
    "page_state",
    "refresh_live",
    "refresh_prompt",
    "start_refresh",
    "stop_refresh",
    "tag_for",
]
