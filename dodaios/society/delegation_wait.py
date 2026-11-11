"""Read correlated replies from the durable board, including very fast jobs."""

from __future__ import annotations

from typing import Any

from dodaios.core.delegated_work import DelegatedWork, register_delegated_work
from dodaios.orchestrator import jobs

from .communication import reply_policy
from .display_name import display_name
from .events import MsgType, SocietyEnvelope
from .roster import conversation_session_id


async def result_for(store: Any, request: SocietyEnvelope) -> dict[str, Any] | None:
    events = await store.events_for_trace(request.trace_id)
    related = [row for row in events if row.parent_event_id == request.event_id]
    claims = [
        row
        for row in related
        if row.msg_type is MsgType.CLAIM and row.from_agent == request.to_agent
    ]
    for claim in claims:
        run_id = str(claim.payload.get("run_id") or "")
        if run_id and not run_id.startswith("turn:"):
            related.extend(
                row
                for row in await store.events_for_trace(f"mission:{run_id}")
                if row.msg_type is MsgType.RESULT
                and row.from_agent == request.to_agent
                and row.payload.get("run_id") == run_id
            )
    for row in reversed(related):
        if row.msg_type is MsgType.VETO and row.from_agent == "scheduler":
            return {"status": "blocked", "report": row.text}
        if row.from_agent != request.to_agent or row.to_agent not in (request.from_agent, None):
            continue
        if row.msg_type is MsgType.RESULT:
            return {
                "status": str(row.payload.get("status") or "unknown"),
                "report": str(row.payload.get("done") or row.text),
                "evidence": row.payload.get("evidence", []),
                "open": row.payload.get("open", []),
            }
        if row.msg_type in (MsgType.QUERY, MsgType.PROPOSE):
            return {"status": "needs_input", "report": row.text}
        if row.msg_type is MsgType.ANSWER and (
            request.msg_type is not MsgType.ASSIGN or row.payload.get("reply_status") == "blocked"
        ):
            return {"status": str(row.payload.get("reply_status") or "done"), "report": row.text}
    return None


def ledger_job_id(request: SocietyEnvelope) -> str | None:
    """The jobs-ledger id of a request, or ``None`` when it is not tracked work.

    An assignment is always a job; a question or note only when its reply is
    awaited. The id depends only on the envelope, so the tool that sent it can
    name the job in its result without a handle on the writer.
    """
    if request.msg_type is MsgType.ASSIGN or (
        request.msg_type in (MsgType.QUERY, MsgType.SAY, MsgType.PROPOSE)
        and reply_policy(request) == "always"
    ):
        return jobs.job_id_for("society_assignment", request.event_id)
    return None


def board_probe(runtime: Any, request: SocietyEnvelope):
    """A read-only probe of one request: its reply on the board, else the agent's progress."""

    async def probe() -> dict[str, Any] | None:
        result = await result_for(runtime.store, request)
        if result is not None:
            return {**result, "result_ref": f"society:{request.event_id}"}
        service = runtime.chat_service()
        if service is None or request.to_agent is None:
            return None
        claims = await runtime.store.events_for_trace(request.trace_id)
        turn_ids = {
            str(row.payload.get("run_id", ""))[5:]
            for row in claims
            if row.msg_type is MsgType.CLAIM
            and row.parent_event_id == request.event_id
            and row.from_agent == request.to_agent
            and str(row.payload.get("run_id", "")).startswith("turn:")
        }
        session_id = conversation_session_id(request.to_agent, request.from_agent)
        progress = [
            row
            for row in service.store.list_events(session_id, tail=64)
            if row.get("payload", {}).get("turn_id") in turn_ids
        ]
        return {"status": "running", "progress": str(progress[-1]["seq"])} if progress else None

    return probe


def _rehydrate(job: jobs.Job):
    """After a restart the board still holds the evidence: read it again.

    A task that died with the process has its RESULT (``interrupted``) from the
    boot sweep (``boot_sweep.py``), so the job ends instead of waiting for ever.
    """
    event_id = str(job.meta.get("event_id") or "")
    if not event_id:
        return None

    async def probe() -> dict[str, Any] | None:
        from dodaios.mcp.agents.context import society

        runtime = await society()
        request = await runtime.store.get_event(event_id)
        if request is None:
            return {"status": "failed", "report": "The assignment record is gone."}
        return await board_probe(runtime, request)()

    return jobs.ledgered(job.id, probe)


jobs.register_rehydrator("society_assignment", _rehydrate)


async def track_request(runtime: Any, request: SocietyEnvelope) -> None:
    job_id = ledger_job_id(request)
    if job_id is None:
        return
    target = await runtime.roster.get(request.to_agent)
    name = display_name(target) if target else str(request.to_agent)
    probe = board_probe(runtime, request)

    session = str(
        request.payload.get("reply_session_id") or request.payload.get("from_session") or ""
    )
    owner = jobs.owner_of()
    jobs.start(
        "society_assignment",
        job_id=job_id,
        target=str(request.to_agent or ""),
        title=f"{name}: {' '.join(str(request.text or '').split())[:100]}",
        owner=owner if owner[0] else (session, ""),
        probe=probe,
        meta={"event_id": request.event_id, "trace_id": request.trace_id},
    )
    if reply_policy(request) != "always":
        return  # Recorded as a job, but the turn does not wait for it.
    wrapped = jobs.probe_for(job_id) or probe
    register_delegated_work(
        DelegatedWork(key="society:" + request.event_id, name=name, probe=wrapped)
    )
