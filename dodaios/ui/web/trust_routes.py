"""HTTP API of the trust layer (``dodaios/trust``).

* ``GET    /api/trust/rules``                 standing rules: the person's own
                                              (``rules``), the agents' (``agent_rules``),
                                              and the hard limits no rule lifts.
* ``DELETE /api/trust/rules/{rule_id}``       revoke one of the person's rules.
* ``DELETE /api/trust/agent-rules/{agent_id}``  ``?pattern=`` drop one agent rule.
* ``GET    /api/trust/undo``                  the undo ledger (recent entries).
* ``POST   /api/trust/undo/{undo_id}``        run the inverse of one action.
* ``GET    /api/trust/audit``                 every gateway action, newest first
                                              (``day``, ``tool``, ``origin``, ``outcome``,
                                              ``limit``, ``before``); read-only by design.
* ``GET    /api/trust/audit/export``          ``?format=csv|json`` plus the same filters.
* ``GET    /api/trust/calibration``           how well the lead's stated confidence matched
                                              what happened (``weeks``): Brier score and a
                                              reliability table, overall, per tool class,
                                              per seat and per week.
* ``GET    /api/trust/receipts/{id}``         the receipt of one action.
* ``GET    /api/trust/privacy``               what the assistant knows and where it goes.
* ``GET    /api/trust/recipients``            who has been written to from here.
* ``DELETE /api/trust/recipients``            ``?recipient=`` forget one.

Sync handlers are plain ``def`` so FastAPI runs them off the event loop; the
two that reach the roster or the tool executor await.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from dodaios.trust.audit import audit_log
from dodaios.trust.hard_limits import HARD_LIMITS
from dodaios.trust.recipients import known_recipients
from dodaios.trust.rules import trust_rules
from dodaios.trust.undo import undo_ledger

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trust", tags=["trust"])


# ------------------------------------------------------------ rules


async def _agent_rules() -> list[dict[str, Any]]:
    """Every society agent's ``always_allow`` rule as one row."""
    try:
        from dodaios.society.approvals import rule_text
        from dodaios.society.runtime import current_runtime
    except Exception:  # noqa: BLE001 — no society, no agent rules
        log.debug("trust rules: society unavailable", exc_info=True)
        return []
    rt = current_runtime()
    if rt is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        agents = await rt.roster.list()
    except Exception:  # noqa: BLE001 — a roster that cannot be read lists nothing
        log.warning("trust rules: roster unavailable", exc_info=True)
        return []
    for agent in agents:
        rules = getattr(agent, "approval_rules", None) or {}
        for pattern in rules.get("always_allow", []) or []:
            parts = str(pattern).split(":")
            app = parts[1] if len(parts) > 1 else parts[0]
            verb = parts[2] if len(parts) > 2 and parts[2] != "*" else ""
            rows.append(
                {
                    "agent_id": agent.agent_id,
                    "agent": getattr(agent, "title", "") or agent.agent_id,
                    "pattern": str(pattern),
                    "app": app,
                    "verb": verb,
                    "label": rule_text("always_allow", app, verb),
                }
            )
    return rows


@router.get("/rules")
async def list_rules() -> dict[str, Any]:
    return {
        "rules": trust_rules().items(),
        "agent_rules": await _agent_rules(),
        "hard_limits": list(HARD_LIMITS),
    }


def _chat_service(request: Request) -> Any | None:
    svc = getattr(request.app.state, "agent_chat", None)
    return svc if svc is not None and hasattr(svc, "forget_standing_rule") else None


@router.delete("/rules/{rule_id}")
def revoke_rule(rule_id: str, request: Request) -> dict[str, Any]:
    rule = trust_rules().revoke(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="no such rule")
    svc = _chat_service(request)
    if svc is not None:
        try:
            svc.forget_standing_rule(rule)
        except Exception:  # noqa: BLE001 — the stored rule is gone either way
            log.warning("trust rules: the chat could not forget %s", rule_id, exc_info=True)
    return {"ok": True, "rule": rule}


@router.delete("/agent-rules/{agent_id}")
async def revoke_agent_rule(
    agent_id: str, pattern: str = Query(min_length=1, max_length=200)
) -> dict[str, Any]:
    from dodaios.society.runtime import current_runtime

    rt = current_runtime()
    if rt is None:
        raise HTTPException(status_code=503, detail="the society is not running")
    agent = await rt.roster.resolve(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="no such agent")
    rules = {
        "require_approval": list(agent.approval_rules.get("require_approval", [])),
        "always_allow": [p for p in agent.approval_rules.get("always_allow", []) if p != pattern],
    }
    if rules["always_allow"] == list(agent.approval_rules.get("always_allow", [])):
        raise HTTPException(status_code=404, detail="no such rule on this agent")
    updated = await rt.roster.update(agent.agent_id, {"approval_rules": rules})
    rt.cache_agent(updated)
    return {"ok": True, "agent_id": agent.agent_id, "pattern": pattern}


# ------------------------------------------------------------ undo


async def _run_inverse(tool_name: str, args: dict[str, Any], entry: dict[str, Any]) -> Any:
    """Run an inverse through the live tool executor (audited like any call)."""
    from dodaios.core.protocols import SupervisorToolRequest
    from dodaios.core.runtime_refs import get_supervisor_tool_gateway

    gateway = get_supervisor_tool_gateway()
    if gateway is None:
        raise RuntimeError("the tools are not ready yet")
    request = SupervisorToolRequest(
        trace_id=uuid.uuid4(),
        origin="trust-undo",
        user_utterance="",
        rationale=f"undo: {entry.get('label') or entry.get('tool')}",
        config_snapshot={
            "undo_of": entry.get("id"),
            # An undo must not wait for a card: its inverses are reversible,
            # unprompted actions; one that would ask fails fast and says so.
            "approval_surface": "unattended",
        },
    )
    return await gateway.execute(tool_name, args, request)


@router.get("/undo")
def list_undo() -> dict[str, Any]:
    return {"entries": undo_ledger().items()}


@router.post("/undo/{undo_id}")
async def run_undo(undo_id: str) -> dict[str, Any]:
    ledger = undo_ledger()
    if ledger.get(undo_id) is None:
        raise HTTPException(status_code=404, detail="nothing to undo under that id")
    if getattr(ledger, "_runner", None) is None:
        ledger.set_runner(_run_inverse)
    entry = await ledger.undo(undo_id)
    return {"ok": entry.get("state") == "undone", "entry": entry}


# ------------------------------------------------------------ audit
# Read-only on purpose: the log is written by the tool executor alone, and no
# route here (or tool anywhere) edits or deletes a row.


@router.get("/audit")
def list_audit(
    day: str = Query("", max_length=10),
    tool: str = Query("", max_length=200),
    origin: str = Query("", max_length=20),
    outcome: str = Query("", max_length=30),
    limit: int = Query(200, ge=1, le=5000),
    before: int = Query(0, ge=0),
) -> dict[str, Any]:
    log_ = audit_log()
    page = log_.query(
        day=day, tool=tool, origin=origin, outcome=outcome, limit=limit, before_seq=before
    )
    return {**page, **log_.facets(), "chain": log_.verify()}


@router.get("/audit/export")
def export_audit(
    format: str = Query("json", pattern="^(csv|json)$"),  # noqa: A002 — the query name is the API
    day: str = Query("", max_length=10),
    tool: str = Query("", max_length=200),
    origin: str = Query("", max_length=20),
    outcome: str = Query("", max_length=30),
) -> Response:
    media, body = audit_log().export(format, day=day, tool=tool, origin=origin, outcome=outcome)
    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="dodaios-audit.{format}"'},
    )


@router.get("/calibration")
def calibration(weeks: int = Query(default=26, ge=1, le=520)) -> dict[str, Any]:
    from dodaios.trust.calibration import audit_report

    since = int((time.time() - weeks * 7 * 86400) * 1000)
    return audit_report(audit_log(), since)


@router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: str) -> dict[str, Any]:
    row = audit_log().get(receipt_id)
    if row is None or not row.get("receipt"):
        raise HTTPException(status_code=404, detail="no receipt under that id")
    return {"receipt": row["receipt"], "action": {k: v for k, v in row.items() if k != "receipt"}}


# ------------------------------------------------------------ privacy


@router.get("/privacy")
def privacy_overview(request: Request) -> dict[str, Any]:
    from dodaios.trust.privacy import overview

    cfg = getattr(request.app.state, "cfg", None) or getattr(request.app.state, "config", None)
    return overview(cfg)


@router.get("/recipients")
def list_recipients() -> dict[str, Any]:
    return {"recipients": known_recipients().items()}


@router.delete("/recipients")
def forget_recipient(recipient: str = Query(min_length=1, max_length=320)) -> dict[str, Any]:
    if not known_recipients().forget(recipient):
        raise HTTPException(status_code=404, detail="not a known recipient")
    return {"ok": True}


__all__ = ["router"]
