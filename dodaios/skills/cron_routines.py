"""Scheduled skills run as lead routines.

A skill whose frontmatter has a ``schedule`` trigger (a cron expression) is
kept in step with ONE recurring lead routine (``society/routines.py``), tagged
:data:`TAG_PREFIX` + the skill's name. The routine runs through
``society/routine_runner.py`` like the morning brief and the "needs you"
checks, so a scheduled skill shares everything they have:

* the background billing hold: once a subscription is connected an unattended
  run never bills a per-token API key, it waits for its next occurrence;
* the routine is pinned to the subscription seat the front page runs on
  (:func:`~dodaios.agent_chat.proactive_checks._seat_for_checks`);
* the result is a written entry in the one lead conversation, and a run that
  has nothing to report answers with the quiet sentinel, which posts nothing;
* a failed or skipped run is a written notice, never spoken: Dodaios never
  speaks uncalled.

The skill file stays the source of truth: :func:`sync_skill_routines` creates
the routine for a skill that gained a schedule, rewrites it when the cron
expression or the skill's instructions changed, and removes it when the skill
lost its schedule, was disabled or deleted. The same pass migrates the
schedules owners already had: their cron skills keep firing at the same wall
clock times, now through the routine path. A routine the owner paused in the
Automations section stays paused.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any, Final

from dodaios.agent_chat.proactive_checks import NOTHING, QUIET_TAG

log = logging.getLogger(__name__)

#: Tag on the routine of one scheduled skill: ``skill-cron:<name>:<index>``.
TAG_PREFIX: Final[str] = "skill-cron:"
#: Seconds between two reconcile passes (skills reload from disk at any time).
SYNC_INTERVAL_S: Final[float] = 120.0
#: Seconds after society start before the first pass.
FIRST_PASS_DELAY_S: Final[float] = 20.0
_TERMINAL: Final[frozenset[str]] = frozenset({"completed", "cancelled", "failed", "interrupted"})


def tag_for(skill_name: str, index: int = 0) -> str:
    return f"{TAG_PREFIX}{skill_name}:{index}"


def skill_prompt(skill: Any) -> str:
    """The routine's standing instruction: the skill's own instructions, run now."""
    name = skill.name
    body = str(getattr(skill, "body", "") or "").strip()
    return (
        f"It is time for the '{name}' skill. Carry out its instructions now, then report "
        "the result in a few short lines, most important first; no greeting.\n"
        f"If the skill finds nothing the user needs to hear, reply with exactly {NOTHING} "
        "and nothing else.\n\n"
        f"Skill '{name}' instructions:\n{body}"
    )


def _matchable(skill: Any) -> bool:
    from dodaios.skills.schema import SkillLifecycleState

    fm = getattr(skill, "frontmatter", None)
    if fm is None or getattr(skill, "state", None) not in (
        SkillLifecycleState.ACTIVE, SkillLifecycleState.VALIDATED,
    ):
        return False
    return fm.risk_policy.default_tier != "block"


def desired_schedules(skills: Iterable[Any]) -> dict[str, tuple[Any, str]]:
    """``{tag: (skill, cron expression)}`` for every skill that should run on a clock."""
    wanted: dict[str, tuple[Any, str]] = {}
    for skill in skills:
        if not _matchable(skill):
            continue
        crons = [t.cron for t in skill.frontmatter.triggers if t.type == "schedule" and t.cron]
        for index, cron in enumerate(crons):
            wanted[tag_for(skill.name, index)] = (skill, cron)
    return wanted


async def _zone(runtime: Any) -> str:
    """The person's IANA zone: what their UI reported, else the saved proactive zone."""
    from dodaios.agent_chat.proactive_settings import load_settings
    from dodaios.tasks.context import turn_timezone

    zone = turn_timezone()
    if zone:
        return zone
    settings = await load_settings(getattr(runtime, "store", None))
    return settings.timezone


def _skill_tag(tags: Iterable[str]) -> str:
    return next((t for t in tags if t.startswith(TAG_PREFIX)), "")


async def sync_skill_routines(runtime: Any, skills: Iterable[Any] | None) -> dict[str, int]:
    """Make the lead's skill routines match the skills' schedules.

    Returns ``{"created", "updated", "removed"}`` counts. Does nothing (and
    says so with zeros) while the society scheduler is down, the skills are
    not loaded yet, or the person's time zone is not known yet: the next pass
    tries again, so a skipped pass never loses a schedule.
    """
    from dodaios.agent_chat.proactive_checks import _seat_for_checks
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import (
        _tags_of,
        build_task_spec,
        create_routine,
        is_agent_routine,
        manage_routine,
    )

    counts = {"created": 0, "updated": 0, "removed": 0}
    if skills is None:
        return counts
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        return counts
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        return counts
    wanted = desired_schedules(skills)
    zone = await _zone(runtime) if wanted else ""
    if wanted and not zone:
        log.info("skill schedules: waiting for the person's time zone")
        return counts

    existing: dict[str, dict[str, Any]] = {}
    stale: list[dict[str, Any]] = []
    for row in await task_store.list(limit=1000):
        if not is_agent_routine(row, LEAD_AGENT_ID) or row.get("state") in _TERMINAL:
            continue
        tag = _skill_tag(_tags_of(row))
        if not tag:
            continue
        if tag in existing or tag not in wanted:
            stale.append(row)
        else:
            existing[tag] = row

    for row in stale:
        try:
            await manage_routine(
                lead, {"task_id": str(row["id"]), "operation": "delete"}, task_store, scheduler
            )
            counts["removed"] += 1
        except Exception:  # noqa: BLE001 — a running routine is retried next pass
            log.info("skill schedules: routine %s not removed yet", row.get("id"), exc_info=True)

    seat: dict[str, str] | None = None
    for tag, (skill, cron) in wanted.items():
        schedule = {"kind": "cron", "expression": cron, "timezone": zone}
        prompt = skill_prompt(skill)
        row = existing.get(tag)
        try:
            if row is None:
                if seat is None:
                    seat = await _seat_for_checks(runtime, lead)
                spec = build_task_spec(
                    lead, title=f"Skill: {skill.name}", prompt=prompt, schedule=schedule, **seat
                )
                spec = spec.model_copy(update={"tags": (*spec.tags, tag, QUIET_TAG)})
                await create_routine(task_store, scheduler, spec)
                counts["created"] += 1
                continue
            old = await task_store.get_spec(str(row["id"]))
            fresh = build_task_spec(lead, title=f"Skill: {skill.name}", prompt=prompt,
                                    schedule=schedule)
            if (
                old is not None
                and old.trigger == fresh.trigger
                and getattr(old.action, "prompt", "") == fresh.action.prompt
            ):
                continue
            await manage_routine(
                lead,
                {"task_id": str(row["id"]), "operation": "update",
                 "title": f"Skill: {skill.name}", "prompt": prompt, "schedule": schedule},
                task_store,
                scheduler,
            )
            counts["updated"] += 1
        except Exception:  # noqa: BLE001 — one bad skill never stops the others
            log.warning("skill schedules: %s not synced", skill.name, exc_info=True)
    if any(counts.values()):
        log.info("skill schedules synced: %s", counts)
    return counts


async def keep_in_sync(runtime: Any, *, interval_s: float = SYNC_INTERVAL_S) -> None:
    """Reconcile shortly after start and then on an interval, for the life of the runtime.

    The first pass waits :data:`FIRST_PASS_DELAY_S` so it never competes with
    society start (skills and the person's time zone load meanwhile).
    """
    await asyncio.sleep(FIRST_PASS_DELAY_S)
    while True:
        try:
            await sync_skill_routines(runtime, runtime._get_skills())  # noqa: SLF001
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the loop outlives one bad pass
            log.warning("skill schedules: pass failed", exc_info=True)
        await asyncio.sleep(interval_s)


__all__ = ["TAG_PREFIX", "desired_schedules", "keep_in_sync", "skill_prompt",
           "sync_skill_routines", "tag_for"]
