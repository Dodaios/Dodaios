"""Close the work a previous process left claimed but never reported.

A society agent takes an assignment with a CLAIM and ends it with a RESULT
written by the watcher of its chat turn. When the app restarts mid-turn the
watcher dies with it: the CLAIM stays open for good, every reader of the board
keeps waiting for a RESULT that cannot come, and the person never learns the
task stopped. This sweep runs once while the runtime starts (nothing of the
new process is running yet) and gives each such CLAIM a RESULT with
``status="interrupted"``. A task the lead handed out also gets one written
notice in the lead's conversation, so the person can send it again.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Final

from .events import MsgType, SocietyEnvelope
from .roster import conversation_session_id

log = logging.getLogger(__name__)

__all__ = ["INTERRUPTED", "sweep_interrupted_runs", "sweep_open_jobs"]

#: ``RESULT.status`` of a task that stopped because the app did.
INTERRUPTED: Final[str] = "interrupted"
#: Only a task this recent is announced in the chat; older ones are just closed.
_ANNOUNCE_WITHIN_S: Final[float] = 24 * 3600.0

_OPEN_CLAIMS = (
    "SELECT seq, event_id, msg_type, from_agent, to_agent, trace_id, parent_event_id, "
    "ts_ms, cost_usd, payload_json FROM society_events c "
    "WHERE c.msg_type = 'CLAIM' "
    "AND json_extract(c.payload_json, '$.run_id') LIKE 'turn:%' "
    "AND NOT EXISTS (SELECT 1 FROM society_events r WHERE r.msg_type = 'RESULT' "
    "  AND r.trace_id = c.trace_id AND r.parent_event_id = c.parent_event_id "
    "  AND json_extract(r.payload_json, '$.run_id') = json_extract(c.payload_json, '$.run_id')) "
    "ORDER BY c.seq"
)


async def sweep_interrupted_runs(runtime: Any) -> int:
    """Write ``RESULT status=interrupted`` for every chat-turn CLAIM without a RESULT.

    A claim whose chat has a live turn is left alone. Returns how many were
    closed. Never raises: a board that cannot be swept simply keeps its claims.
    """
    try:
        cur = await runtime.store.conn.execute(_OPEN_CLAIMS)
        rows = await cur.fetchall()
        await cur.close()
    except Exception:  # noqa: BLE001 - the sweep is housekeeping, never a start blocker
        log.warning("society: open claims could not be listed", exc_info=True)
        return 0
    from .store import _row_to_envelope

    svc = runtime.chat_service()
    closed = 0
    for row in rows:
        claim = _row_to_envelope(row)
        try:
            if await _close(runtime, svc, claim):
                closed += 1
        except Exception:  # noqa: BLE001 - one bad row must not strand the rest
            log.warning("society: claim %s not closed", claim.event_id, exc_info=True)
    if closed:
        log.info("society: closed %d task(s) a restart left claimed", closed)
    return closed


async def _close(runtime: Any, svc: Any | None, claim: SocietyEnvelope) -> bool:
    requester = claim.to_agent or "user"
    session_id = conversation_session_id(claim.from_agent, requester)
    running = getattr(svc, "is_running", None)
    if callable(running) and running(session_id):
        return False  # a live turn owns it; its watcher writes the RESULT
    run_id = str(claim.payload.get("run_id") or "")
    agent = await runtime.roster.get(claim.from_agent)
    name = _name(agent, claim.from_agent)
    summary = f"{name}'s task stopped when the app restarted."
    await runtime.store.append_and_publish(
        SocietyEnvelope(
            msg_type=MsgType.RESULT,
            from_agent=claim.from_agent,
            to_agent=claim.to_agent if claim.to_agent != "user" else None,
            trace_id=claim.trace_id,
            parent_event_id=claim.parent_event_id,
            payload={
                "run_id": run_id,
                "status": INTERRUPTED,
                "done": summary,
                "output": [f"chat:{session_id}"],
                "evidence": [],
                "open": ["Stopped when the app restarted; it was not finished."],
                "next_owner": None,
                "text": summary,
            },
        )
    )
    recent = time.time() - claim.ts_ms / 1000 <= _ANNOUNCE_WITHIN_S
    if svc is not None and recent and claim.to_agent == runtime.lead_id:
        await _announce(svc, claim, name)
    return True


def _name(agent: Any | None, fallback: str) -> str:
    if agent is None:
        return fallback
    from .display_name import display_name

    return display_name(agent)


async def _announce(svc: Any, claim: SocietyEnvelope, name: str) -> None:
    """One written line in the lead's conversation; nothing is spoken."""
    from dodaios.agent_chat.lead import lead_session_id

    lead_sid = lead_session_id(svc)
    if not lead_sid or svc.store.get_session(lead_sid) is None:
        return
    try:
        await asyncio.wait_for(
            svc.post_notice(
                lead_sid,
                {
                    "kind": "agent_task_interrupted",
                    "agent_name": name,
                    "text": f"{name}'s task stopped when the app restarted. Send it again?",
                },
            ),
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - the RESULT is written; the notice is a projection
        log.warning("society: interrupted-task notice not posted", exc_info=True)


async def sweep_open_jobs() -> int:
    """Apply the jobs ledger's rule to jobs a previous boot left open.

    Each is read once (:func:`dodaios.orchestrator.jobs.refresh`): work whose
    evidence is durable goes on from its record, work that died with the
    process becomes ``interrupted``. Returns how many are settled afterwards
    that were open before. Never raises.
    """
    import importlib

    from dodaios.orchestrator import jobs

    try:
        for module in ("dodaios.society.delegation_wait", "dodaios.orchestrator.mission_jobs"):
            importlib.import_module(module)  # registers the rehydrators
        ledger = jobs.get_ledger()
        stale = [
            job for job in await asyncio.to_thread(ledger.recent, limit=500, open_only=True)
            if job.boot_id != jobs.BOOT_ID
        ]
    except Exception:  # noqa: BLE001 - housekeeping, never a start blocker
        log.warning("jobs: open jobs of the last boot could not be listed", exc_info=True)
        return 0
    settled = 0
    for job in stale:
        try:
            if (await jobs.refresh(job)).settled:
                settled += 1
        except Exception:  # noqa: BLE001 - one job must not strand the rest
            log.warning("jobs: %s not swept", job.id, exc_info=True)
    if settled:
        log.info("jobs: settled %d job(s) a restart left open", settled)
    return settled
