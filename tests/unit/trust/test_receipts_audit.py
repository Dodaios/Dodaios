"""Action receipts and the owner's audit log, through the real executor."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from dodaios.agent_chat.turn_verify import verify_answer
from dodaios.brain.loop_control import ToolRecord, VerifyRequest
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.events import ActionExecuted
from dodaios.core.protocols import ExecutionContext, ToolResult, current_trigger_path
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.trust.audit import AuditLog, audit_log
from dodaios.trust.recipients import known_recipients


class _Tool:
    def __init__(self, name: str, output: Any, *, risk_tier: str = "monitor", ok: bool = True):
        self.name = name
        self.risk_tier = risk_tier
        self.description = name
        self.schema = {"type": "object", "properties": {}}
        self._output = output
        self._ok = ok

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        return ToolResult(success=self._ok, output=self._output, error=None if self._ok else "boom")


def _stack(**safety: Any) -> tuple[EventBus, ToolExecutor]:
    bus = EventBus()
    executor = ToolExecutor(
        bus,
        RiskTierEvaluator(SafetyConfig(**safety)),
        ApprovalWorkflow(bus, timeout_s=0.3),
        default_timeout_s=0.3,
    )
    return bus, executor


async def _run(
    executor: ToolExecutor, tool: _Tool, args: dict[str, Any], **cfg: Any
) -> ToolResult:
    return await executor.execute(
        tool, args, config_snapshot={"approval_surface": "unattended", **cfg}, trace_id=uuid4()
    )


# ------------------------------------------------------------------ receipts


@pytest.mark.asyncio
async def test_sent_mail_receipt_has_message_id_and_thread_link() -> None:
    _, executor = _stack()
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1", "threadId": "t-9"})
    result = await _run(
        executor, tool, {"action": "send_message", "to": "ada@example.com", "body": "hi"}
    )
    assert result.success
    receipt = result.receipt
    assert receipt and receipt["state"] == "backed" and receipt["kind"] == "mail_sent"
    assert receipt["evidence"]["message_id"] == "m-1"
    assert receipt["links"] == ["https://mail.google.com/mail/u/0/#all/t-9"]


@pytest.mark.asyncio
async def test_calendar_event_receipt_has_event_id_and_link() -> None:
    _, executor = _stack()
    tool = _Tool("google_calendar", {"id": "ev1", "htmlLink": "https://calendar.example/ev1"})
    result = await _run(executor, tool, {"action": "create_event", "summary": "Lunch"})
    assert result.receipt["kind"] == "calendar_event"
    assert result.receipt["evidence"]["event_id"] == "ev1"
    assert result.receipt["links"] == ["https://calendar.example/ev1"]


@pytest.mark.asyncio
async def test_file_write_receipt_has_path_size_and_hash(tmp_path: Path) -> None:
    _, executor = _stack()
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    tool = _Tool("Write", "Created note.txt (5 chars)")
    result = await _run(
        executor, tool, {"file_path": "note.txt", "content": "hello"}, cwd=str(tmp_path)
    )
    evidence = result.receipt["evidence"]
    assert result.receipt["kind"] == "file_write"
    assert evidence["size"] == 5
    assert evidence["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert evidence["matches_content"] is True


@pytest.mark.asyncio
async def test_file_write_without_a_file_on_disk_has_no_evidence(tmp_path: Path) -> None:
    _, executor = _stack()
    tool = _Tool("Write", "Created ghost.txt", risk_tier="monitor")
    result = await _run(executor, tool, {"file_path": "ghost.txt"}, cwd=str(tmp_path))
    assert result.receipt["state"] == "none"
    assert result.receipt["summary"] == "no external evidence"


@pytest.mark.asyncio
async def test_shell_receipt_has_exit_code_and_command() -> None:
    _, executor = _stack()
    tool = _Tool("run_shell", {"exit_code": 0, "stdout": "ok", "stderr": ""})
    result = await _run(executor, tool, {"command": "echo ok"})
    assert result.receipt["kind"] == "shell"
    assert result.receipt["evidence"] == {"command": "echo ok", "exit_code": 0}


@pytest.mark.asyncio
async def test_github_pull_request_url_from_a_shell_command_and_from_a_github_tool() -> None:
    _, executor = _stack()
    shell = _Tool(
        "run_shell",
        {"exit_code": 0, "stdout": "https://github.com/acme/app/pull/12\n", "stderr": ""},
    )
    via_shell = await _run(executor, shell, {"command": "gh pr create --fill"})
    assert via_shell.receipt["kind"] == "pull_request_or_issue"
    assert via_shell.receipt["links"] == ["https://github.com/acme/app/pull/12"]

    mcp = _Tool("mcp__github__create_issue", {"html_url": "https://github.com/acme/app/issues/3"})
    via_mcp = await _run(executor, mcp, {"title": "Bug"})
    assert via_mcp.receipt["links"] == ["https://github.com/acme/app/issues/3"]


@pytest.mark.asyncio
async def test_channel_message_receipt_has_the_message_id() -> None:
    _, executor = _stack()
    known_recipients().remember(["#ops"])
    tool = _Tool("slack", {"posted": True, "channel_id": "C1", "ts": "1699.01"})
    result = await _run(executor, tool, {"action": "post_message", "channel": "#ops", "text": "x"})
    assert result.receipt["kind"] == "channel_message"
    assert result.receipt["evidence"]["message_id"] == "1699.01"


@pytest.mark.asyncio
async def test_delegation_receipt_has_the_job_id() -> None:
    _, executor = _stack()
    tool = _Tool(
        "delegate_to_agent", {"job_id": "job-7", "assignment_id": "as-1", "state": "running"}
    )
    result = await _run(executor, tool, {"task": "x"})
    assert result.receipt["kind"] == "job"
    assert result.receipt["evidence"]["job_id"] == "job-7"
    text_job = _Tool("spawn_worker", "On it.\n(job_id: job-42; check it with job_status)")
    assert (await _run(executor, text_job, {})).receipt["evidence"]["job_id"] == "job-42"


@pytest.mark.asyncio
async def test_a_tool_without_evidence_gets_a_none_receipt_and_a_read_has_no_receipt() -> None:
    bus, executor = _stack()
    seen: list[ActionExecuted] = []

    async def on(event: ActionExecuted) -> None:
        seen.append(event)

    bus.subscribe(ActionExecuted, on)
    odd = await _run(executor, _Tool("mystery_writer", "done"), {})
    assert odd.receipt["state"] == "none" and odd.receipt["summary"] == "no external evidence"
    read = await _run(executor, _Tool("search_web", "results", risk_tier="safe"), {})
    assert read.receipt["state"] == "read"
    assert seen[0].receipt_state == "none" and seen[0].receipt_id
    assert seen[1].receipt_id == "" and seen[1].receipt_state == ""


@pytest.mark.asyncio
async def test_a_failed_call_gets_no_receipt() -> None:
    _, executor = _stack()
    result = await _run(executor, _Tool("gmail", None, ok=False), {"action": "send_message"})
    assert not result.success and result.receipt is None


@pytest.mark.asyncio
async def test_a_tool_can_supply_its_own_evidence() -> None:
    from dodaios.trust.receipts import Evidence

    class _Own(_Tool):
        def receipt_evidence(self, args: dict[str, Any], result: Any, cfg: dict[str, Any]):
            return Evidence("custom", "Custom proof", {"ref": "r1"}, ("https://x.example/r1",))

    _, executor = _stack()
    result = await _run(executor, _Own("own_tool", "ok"), {})
    assert result.receipt["kind"] == "custom" and result.receipt["evidence"] == {"ref": "r1"}


# --------------------------------------------------------- claim check + receipts


def _req(answer: str, *log: ToolRecord) -> VerifyRequest:
    return VerifyRequest(user_text="do it", answer=answer, tool_log=tuple(log))


async def _no_model(_s: str, _u: str) -> str:
    raise AssertionError("no model")


@pytest.mark.asyncio
async def test_sent_claim_needs_a_send_receipt_with_evidence() -> None:
    backed = ToolRecord("gmail", ok=True, receipt="backed")
    assert (await verify_answer(_req("I sent the email.", backed), _no_model)).accepted

    unproven = ToolRecord("gmail", ok=True, receipt="none")
    out = await verify_answer(_req("I sent the email.", unproven), _no_model)
    assert not out.accepted and "sent" in out.detail

    only_read = ToolRecord("gmail", ok=True, receipt="read")
    assert not (await verify_answer(_req("I sent the email.", only_read), _no_model)).accepted

    legacy = ToolRecord("gmail", ok=True)
    assert (await verify_answer(_req("I sent the email.", legacy), _no_model)).accepted


# ----------------------------------------------------------------------- audit


@pytest.mark.asyncio
async def test_every_call_leaves_an_audit_row_with_the_receipt() -> None:
    _, executor = _stack()
    known_recipients().remember(["ada@example.com"])
    await _run(
        executor,
        _Tool("gmail", {"id": "m-1", "threadId": "t-9"}),
        {"action": "send_message", "to": "ada@example.com"},
        tool_origin="agent-chat",
        approval_ref="agent-chat:sess1",
    )
    rows = audit_log().query()["entries"]
    assert len(rows) == 1
    row = rows[0]
    assert row["tool"] == "gmail" and row["action"] == "send_message"
    assert row["origin"] == "owner" and "sess1" in row["origin_detail"]
    assert row["session_id"] == "sess1"
    assert row["approval"] == "auto_tier" and row["outcome"] == "executed"
    assert row["effect"] == "outbound"
    assert row["receipt"]["evidence"]["message_id"] == "m-1"


@pytest.mark.asyncio
async def test_routine_and_trigger_origins_come_from_the_trusted_run_context() -> None:
    _, executor = _stack()
    token = current_trigger_path.set(("task:nightly",))
    try:
        await _run(executor, _Tool("run_shell", {"exit_code": 0}), {"command": "a"})
    finally:
        current_trigger_path.reset(token)
    token = current_trigger_path.set(("task:upstream", "task:child"))
    try:
        await _run(executor, _Tool("run_shell", {"exit_code": 0}), {"command": "b"})
    finally:
        current_trigger_path.reset(token)
    await _run(
        executor,
        _Tool("run_shell", {"exit_code": 0}),
        {"command": "c"},
        tool_origin="mission_worker",
        mission_id="m9",
    )
    by_command = {r["args_preview"]: r for r in audit_log().query()["entries"]}
    origins = sorted((r["origin"], r["origin_detail"]) for r in by_command.values())
    assert ("routine", "task:nightly") in origins
    assert ("trigger", "task:upstream > task:child") in origins
    assert any(o == "agent" and "mission_id=m9" in d for o, d in origins)
    assert {r["origin"] for r in audit_log().query(origin="routine")["entries"]} == {"routine"}


@pytest.mark.asyncio
async def test_refused_and_blocked_calls_are_audited_too() -> None:
    _, executor = _stack(approval_mode="ask")
    # An ask-tier call with nobody to ask: the owner sees that it never ran.
    await _run(executor, _Tool("risky", "x", risk_tier="ask"), {})
    # Plan mode permits reads only.
    await _run(executor, _Tool("writer", "x"), {}, chat_read_only=True)
    outcomes = {r["tool"]: r["outcome"] for r in audit_log().query()["entries"]}
    assert outcomes == {"risky": "unavailable", "writer": "denied"}
    assert all(r["receipt"] is None for r in audit_log().query()["entries"])


@pytest.mark.asyncio
async def test_a_whitelisted_call_is_an_always_rule_approval() -> None:
    from dodaios.core.config import SafetyWhitelistConfig

    _, executor = _stack(
        approval_mode="ask", whitelist=SafetyWhitelistConfig(commands=["git status*"])
    )
    tool = _Tool("run_shell", {"exit_code": 0}, risk_tier="ask")
    tool.whitelist_command_arg = "command"  # type: ignore[attr-defined]
    await _run(executor, tool, {"command": "git status"})
    (row,) = audit_log().query()["entries"]
    assert row["approval"] == "always_rule" and row["outcome"] == "executed"


def test_the_agent_cannot_write_the_audit(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.db")
    log.record({"tool": "gmail", "origin": "owner", "outcome": "executed"})
    log.record({"tool": "run_shell", "origin": "agent", "outcome": "failed"})
    conn = sqlite3.connect(str(tmp_path / "a.db"))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit SET outcome = 'executed'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM audit")
    # Even with the triggers dropped behind the log's back, the chain shows it.
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit SET outcome = 'executed' WHERE seq = 2")
    conn.commit()
    conn.close()
    verdict = log.verify()
    assert verdict["ok"] is False and verdict["broken_at"] == 2


def test_no_route_or_tool_writes_the_audit() -> None:
    from dodaios.ui.web.trust_routes import router

    for route in router.routes:
        if "/audit" in route.path or "/receipts" in route.path:
            assert route.methods == {"GET"}, route.path
    # No registered tool exposes the audit log: nothing in the tool tree names it.
    tools_dir = Path(__file__).resolve().parents[3] / "dodaios" / "plugins" / "tool"
    for source in tools_dir.glob("*.py"):
        assert "trust.audit" not in source.read_text(encoding="utf-8"), source.name


@pytest.mark.asyncio
async def test_query_filters_and_export(tmp_path: Path) -> None:
    _, executor = _stack()
    known_recipients().remember(["ada@example.com"])
    await _run(
        executor,
        _Tool("gmail", {"id": "m-1", "threadId": "t-9"}),
        {"action": "send_message", "to": "ada@example.com"},
    )
    token = current_trigger_path.set(("task:t1",))
    try:
        await _run(executor, _Tool("run_shell", {"exit_code": 0}), {"command": "ls"})
    finally:
        current_trigger_path.reset(token)
    log = audit_log()
    assert len(log.query()["entries"]) == 2
    assert [r["tool"] for r in log.query(tool="GMAIL")["entries"]] == ["gmail"]
    assert [r["tool"] for r in log.query(origin="routine")["entries"]] == ["run_shell"]
    day = log.query()["entries"][0]["day"]
    assert len(log.query(day=day)["entries"]) == 2 and not log.query(day="1999-01-01")["entries"]
    page = log.query(limit=1)
    assert len(page["entries"]) == 1 and page["next_before"]
    assert len(log.query(limit=1, before_seq=page["next_before"])["entries"]) == 1

    media, body = log.export("json", origin="owner")
    assert media == "application/json"
    rows = json.loads(body)
    assert [r["tool"] for r in rows] == ["gmail"] and rows[0]["receipt"]["state"] == "backed"
    media, csv_body = log.export("csv")
    lines = csv_body.strip().splitlines()
    assert media.startswith("text/csv") and len(lines) == 3
    assert "receipt_summary" in lines[0] and "Mail sent (message m-1)" in csv_body
    assert log.facets()["tools"] == ["gmail", "run_shell"]
    assert log.verify() == {"ok": True, "rows": 2, "broken_at": None}


@pytest.mark.asyncio
async def test_audit_routes_serve_the_list_the_export_and_a_receipt() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web.trust_routes import router

    _, executor = _stack()
    result = await _run(executor, _Tool("run_shell", {"exit_code": 0}), {"command": "ls"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/api/trust/audit").json()
    assert body["entries"][0]["tool"] == "run_shell" and body["chain"]["ok"] is True
    assert client.get("/api/trust/audit/export?format=csv").headers["content-disposition"]
    receipt = client.get(f"/api/trust/receipts/{result.receipt['id']}").json()
    assert receipt["receipt"]["kind"] == "shell"
    assert client.get("/api/trust/receipts/nope").status_code == 404
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/trust/audit").status_code == 405
