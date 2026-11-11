"""Predict before acting: schema injection, comparison, calibration, low confidence."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.trust import calibration
from dodaios.trust.audit import AuditLog, audit_log
from dodaios.trust.expectations import (
    EXPECT_KEY,
    HIT,
    MISS,
    UNKNOWN,
    Expectation,
    compare,
    inject_expect,
    parse_expect,
    schema_for,
    split_expect,
    tool_class,
)
from dodaios.trust.recipients import known_recipients


class _Tool:
    def __init__(
        self,
        name: str,
        output: Any = None,
        *,
        risk_tier: str = "monitor",
        ok: bool = True,
        schema: dict[str, Any] | None = None,
        read_only: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.name = name
        self.risk_tier = risk_tier
        self.description = name
        self.schema = schema or {"type": "object", "properties": {"to": {"type": "string"}}}
        self.read_only = read_only
        self._output = output
        self._ok = ok
        self.calls: list[dict[str, Any]] = []
        if dry_run:
            self.dry_run_args = lambda args: {**args, "dry_run": True}

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(success=self._ok, output=self._output, error=None if self._ok else "boom")


def _executor() -> ToolExecutor:
    bus = EventBus()
    return ToolExecutor(
        bus,
        RiskTierEvaluator(SafetyConfig()),
        ApprovalWorkflow(bus, timeout_s=0.3),
        default_timeout_s=0.3,
    )


async def _run(executor: ToolExecutor, tool: _Tool, args: dict[str, Any], **cfg: Any) -> ToolResult:
    snapshot = {
        "approval_surface": "interactive",
        "approval_ref": "agent-chat:s1",  # a bound chat: no global bypass answers
        "brain_seat": "seat-a",
        **cfg,
    }
    return await executor.execute(tool, args, config_snapshot=snapshot, trace_id=uuid4())


# ------------------------------------------------------------------- schema


def test_inject_expect_adds_one_property_and_never_changes_the_input() -> None:
    schema = {"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]}
    out = inject_expect(schema)
    assert EXPECT_KEY in out["properties"] and "to" in out["properties"]
    assert out["required"] == ["to"]
    assert EXPECT_KEY not in schema["properties"]
    assert inject_expect(out) is out  # already there


def test_schema_for_adds_expect_to_acting_tools_only() -> None:
    assert EXPECT_KEY in schema_for(_Tool("gmail"))["properties"]
    reader = _Tool("search_web", risk_tier="safe", read_only=True)
    assert EXPECT_KEY not in schema_for(reader)["properties"]
    own = _Tool("x", schema={"type": "object", "properties": {"expect": {"type": "string"}}})
    assert schema_for(own)["properties"]["expect"] == {"type": "string"}


def test_the_loop_and_the_dispatcher_publish_the_injected_schema() -> None:
    from dodaios.brain.dispatcher import BrainDispatcher
    from dodaios.brain.tool_use_loop import ToolUseLoop

    for owner in (ToolUseLoop._tool_schemas, BrainDispatcher.tools_payload):
        assert "schema_for(" in inspect.getsource(owner)


def test_split_expect_strips_it_and_parses_leniently() -> None:
    tool = _Tool("gmail")
    args, expectation = split_expect(
        tool, {"to": "a@b.c", "expect": {"outcome": " mail  sent ", "confidence": "90%"}}
    )
    assert args == {"to": "a@b.c"}
    assert expectation == Expectation("mail sent", 0.9)
    assert split_expect(tool, {"to": "x"}) == ({"to": "x"}, None)
    assert parse_expect({"confidence": 7}) == Expectation("", 1.0)
    assert parse_expect({"outcome": ""}) is None and parse_expect(5) is None
    own = _Tool("x", schema={"type": "object", "properties": {"expect": {"type": "string"}}})
    kept = {"expect": "mine"}
    assert split_expect(own, kept) == (kept, None)


# ------------------------------------------------------------------ compare


def _cmp(outcome: str, tool: str, args: dict[str, Any], ok: bool = True, **kw: Any) -> str:
    return compare(Expectation(outcome, 0.8), tool_name=tool, args=args, succeeded=ok, **kw)


def test_tool_classes() -> None:
    assert tool_class("gmail") == "mail"
    assert tool_class("google_calendar") == "calendar"
    assert tool_class("Write") == "file" and tool_class("run_shell") == "shell"
    assert tool_class("delegate_to_agent") == "delegation" and tool_class("slack") == "message"
    assert tool_class("whatever") == "other"


def test_success_versus_error() -> None:
    assert _cmp("it works", "x", {}, ok=True) == HIT
    assert _cmp("it works", "x", {}, ok=False) == MISS
    assert _cmp("this will fail with an error", "x", {}, ok=False) == HIT
    assert _cmp("this will be refused", "x", {}, ok=True) == MISS
    assert _cmp("runs with no errors", "x", {}, ok=True) == HIT


def test_mail_recipient_must_match() -> None:
    receipt = {"summary": "Mail sent", "evidence": {"to": "ana@example.com"}, "links": []}
    args = {"action": "send_message", "to": "ana@example.com"}
    assert _cmp("mail to Ana@Example.com is sent", "gmail", args, receipt=receipt) == HIT
    assert _cmp("mail to bob@example.com is sent", "gmail", args, receipt=receipt) == MISS


def test_calendar_time_and_date() -> None:
    out = {"id": "e1", "start": {"dateTime": "2026-11-12T14:00:00+01:00"}}
    args = {"action": "create_event"}
    assert _cmp("event on 2026-11-12 at 14:00", "google_calendar", args, output=out) == HIT
    assert _cmp("event at 9:30", "google_calendar", args, output=out) == MISS
    # the call shows no time at all: nothing to compare against
    assert _cmp("event at 14:00", "google_calendar", args, output={"id": "e1"}) == UNKNOWN


def test_file_path_by_full_path_or_name() -> None:
    receipt = {"summary": "File written", "evidence": {"path": "C:\\work\\notes\\todo.md"}}
    args = {"file_path": "C:\\work\\notes\\todo.md"}
    assert _cmp("writes C:/work/notes/todo.md", "Write", args, receipt=receipt) == HIT
    assert _cmp("creates todo.md", "Write", args, receipt=receipt) == HIT
    assert _cmp("creates /tmp/other.md", "Write", args, receipt=receipt) == MISS


def test_shell_exit_code() -> None:
    zero = {"evidence": {"exit_code": 0}}
    one = {"evidence": {"exit_code": 1}}
    assert _cmp("the command succeeds", "run_shell", {}, receipt=zero) == HIT
    assert _cmp("the command succeeds", "run_shell", {}, receipt=one) == MISS
    assert _cmp("exits with code 1", "run_shell", {}, receipt=one) == HIT
    assert _cmp("the command will fail", "run_shell", {}, receipt=one) == HIT
    assert _cmp("the command will fail", "run_shell", {}, receipt=zero) == MISS


def test_a_comparison_that_breaks_is_unknown() -> None:
    assert compare(None, tool_name="x", args={}, succeeded=True) == UNKNOWN  # type: ignore[arg-type]


# -------------------------------------------------------------- calibration


def test_brier_score() -> None:
    assert calibration.brier([]) is None
    assert calibration.brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert calibration.brier([(0.5, 1), (0.5, 0)]) == pytest.approx(0.25)
    assert calibration.brier([(0.9, 0)]) == pytest.approx(0.81)


def test_reliability_table_bins() -> None:
    rows = calibration.reliability([(0.9, 1), (0.95, 0), (0.1, 0), (1.0, 1)], bins=5)
    top = rows[-1]
    assert top["n"] == 3 and top["low"] == 0.8
    assert top["hit_rate"] == pytest.approx(2 / 3)
    assert top["gap"] > 0  # overconfident


def test_report_splits_by_class_and_seat_and_skips_unscorable() -> None:
    day = 86_400_000
    rows = [
        {"confidence": 0.9, "verdict": "hit", "class": "mail", "seat": "a", "ts_ms": day},
        {"confidence": 0.9, "verdict": "miss", "class": "mail", "seat": "b", "ts_ms": day},
        {"confidence": 0.6, "verdict": "unknown", "class": "file", "seat": "a", "ts_ms": day},
        {"confidence": None, "verdict": "hit", "class": "file", "seat": "a", "ts_ms": day},
    ]
    report = calibration.build_report(rows)
    assert report["predictions"] == 4 and report["scored"] == 2
    assert report["unknown"] == 1 and report["unscored"] == 1
    assert report["brier"] == pytest.approx((0.01 + 0.81) / 2)
    assert report["by_class"]["mail"]["scored"] == 2
    assert report["by_seat"]["a"]["brier"] == pytest.approx(0.01)
    assert report["weekly"][0]["scored"] == 2
    assert calibration.build_report([])["brier"] is None


# ----------------------------------------------------------------- executor


@pytest.mark.asyncio
async def test_expect_never_reaches_the_tool_and_the_verdict_is_stored_with_the_audit_row() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1", "threadId": "t-1"})
    args = {
        "action": "send_message",
        "to": "ada@example.com",
        "expect": {"outcome": "mail to ada@example.com is sent", "confidence": 0.9},
    }
    result = await _run(_executor(), tool, args)
    assert result.success
    assert tool.calls == [{"action": "send_message", "to": "ada@example.com"}]
    row = audit_log().query()["entries"][0]
    assert row["prediction"]["verdict"] == HIT
    assert row["prediction"]["confidence"] == 0.9
    assert row["prediction"]["class"] == "mail" and row["prediction"]["seat"] == "seat-a"
    assert audit_log().verify()["ok"] is True
    report = calibration.audit_report(audit_log())
    assert report["scored"] == 1 and report["by_seat"]["seat-a"]["hits"] == 1


@pytest.mark.asyncio
async def test_a_failed_call_is_a_miss_for_a_confident_prediction() -> None:
    tool = _Tool("run_shell", {"exit_code": 0}, ok=False)
    await _run(_executor(), tool, {"command": "x", "expect": {"confidence": 0.95}})
    assert audit_log().query()["entries"][0]["prediction"]["verdict"] == MISS


@pytest.mark.asyncio
async def test_missing_expect_changes_nothing() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1"})
    result = await _run(_executor(), tool, {"action": "send_message", "to": "ada@example.com"})
    assert result.success and tool.calls[0]["to"] == "ada@example.com"
    row = audit_log().query()["entries"][0]
    assert row["prediction"] is None and row["outcome"] == "executed"


@pytest.mark.asyncio
async def test_low_confidence_irreversible_action_asks_once_and_does_not_run() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1"})
    args = {
        "action": "send_message",
        "to": "ada@example.com",
        "expect": {"outcome": "sent", "confidence": 0.2},
    }
    result = await _run(_executor(), tool, args)
    assert not result.success and "approval-timeout" in str(result.error)
    assert tool.calls == []
    row = audit_log().query()["entries"][0]
    assert row["outcome"] == "timeout" and row["prediction"] is None  # no outcome to score


@pytest.mark.asyncio
async def test_confident_irreversible_action_is_not_interrupted() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1"})
    args = {"action": "send_message", "to": "ada@example.com", "expect": {"confidence": 0.8}}
    assert (await _run(_executor(), tool, args)).success


@pytest.mark.asyncio
async def test_low_confidence_on_reversible_work_is_never_interrupted() -> None:
    tool = _Tool("Write", "Created a.txt", risk_tier="monitor")
    args = {"file_path": "a.txt", "content": "x", "expect": {"confidence": 0.1}}
    assert (await _run(_executor(), tool, args)).success  # a modify, not an irreversible effect


@pytest.mark.asyncio
async def test_low_confidence_in_an_unattended_run_is_not_interrupted() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"id": "m-1"})
    args = {"action": "send_message", "to": "ada@example.com", "expect": {"confidence": 0.1}}
    result = await _run(_executor(), tool, args, approval_surface="unattended")
    assert result.success


@pytest.mark.asyncio
async def test_low_confidence_runs_the_dry_run_of_a_tool_that_has_one() -> None:
    known_recipients().remember(["ada@example.com"])
    tool = _Tool("gmail", {"preview": "would send"}, dry_run=True)
    args = {"action": "send_message", "to": "ada@example.com", "expect": {"confidence": 0.3}}
    result = await _run(_executor(), tool, args)
    assert result.success and result.output["dry_run"] is True
    assert result.output["executed"] is False
    assert tool.calls == [{"action": "send_message", "to": "ada@example.com", "dry_run": True}]
    assert audit_log().query()["entries"][0]["prediction"] is None


# -------------------------------------------------------------- audit chain


def test_old_rows_without_a_prediction_still_verify(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.db")
    log.record({"tool": "t", "outcome": "executed"})
    log.record({"tool": "t", "outcome": "executed", "prediction": {"verdict": "hit"}})
    assert log.verify() == {"ok": True, "rows": 2, "broken_at": None}
    assert len(log.predictions()) == 1


def test_a_log_from_before_the_column_is_upgraded(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    log = AuditLog(path)
    log.record({"tool": "t", "outcome": "executed"})
    log.close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE audit DROP COLUMN prediction")
    conn.commit()
    conn.close()
    reopened = AuditLog(path)
    reopened.record({"tool": "t", "outcome": "executed", "prediction": {"verdict": "miss"}})
    assert reopened.verify()["ok"] is True


def test_the_route_and_the_score_report_carry_calibration(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.evals.agent_score import build_report, format_table
    from dodaios.ui.web.trust_routes import router

    audit_log().record(
        {
            "tool": "gmail",
            "outcome": "executed",
            "prediction": {"confidence": 0.8, "verdict": "hit", "class": "mail", "seat": "s"},
        }
    )
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get("/api/trust/calibration").json()
    assert body["scored"] == 1 and body["by_class"]["mail"]["scored"] == 1

    db = tmp_path / "chat.db"
    sqlite3.connect(db).close()
    report = build_report(db, tmp_path, audit=audit_log())
    assert report["calibration"]["scored"] == 1
    assert "Calibration" in format_table(report)
    assert build_report(db, tmp_path)["calibration"] is None
