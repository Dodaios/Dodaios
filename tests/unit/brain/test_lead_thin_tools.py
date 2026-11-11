"""``team_thread``, ``costs_summary`` and ``artifacts``: thin, bounded, honest wrappers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.brain import artifacts_tool, costs_summary_tool, team_thread_tool
from dodaios.brain.artifacts_tool import ArtifactsTool
from dodaios.brain.costs_summary_tool import CostsSummaryTool
from dodaios.brain.team_thread_tool import TeamThreadTool
from dodaios.core.protocols import ExecutionContext


def _ctx(**config: Any) -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), user_utterance="", config=config, memory_read=None)


class _Api:
    """A stand-in for the app: records each call and answers from a table."""

    def __init__(self, answers: dict[tuple[str, str], tuple[int | None, Any]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str, dict[str, Any] | None, Any]] = []

    async def __call__(self, method: str, path: str, *, query=None, body=None):
        self.calls.append((method, path, query, body))
        return self.answers.get((method, path), (404, {"detail": "unknown route"}))


def _install(monkeypatch: pytest.MonkeyPatch, module: Any, api: _Api) -> _Api:
    monkeypatch.setattr(module, "call_app_api", api)
    return api


# ---------------------------------------------------------------- team_thread


def test_team_thread_start_asks_and_reads_do_not() -> None:
    tool = TeamThreadTool()
    assert tool.risk_tier == "ask"
    assert tool.risk_tier_for_args({"action": "start"}) == "ask"
    for action in ("seats", "list", "status"):
        assert tool.risk_tier_for_args({"action": action}) == "safe"
        assert tool.read_only_for_args({"action": action})
    for action in ("answer", "pause", "resume", "accept", "stop"):
        assert tool.risk_tier_for_args({"action": action}) == "monitor"
    assert not tool.read_only_for_args({"action": "start"})


async def test_team_thread_start_posts_the_task_and_returns_the_job_id(monkeypatch) -> None:
    started = {
        "team_id": "t1",
        "title": "Plan",
        "task": "plan the migration",
        "state": "running",
        "phase": "planning",
        "members": [{"name": "Claude", "provider": "claude", "state": "active"}],
        "entries": [{"seq": 1, "kind": "user", "author": "user", "payload": {"text": "go"}}],
        "job_id": "job-7",
    }
    api = _install(
        monkeypatch, team_thread_tool, _Api({("POST", "/api/team-threads"): (201, started)})
    )
    result = await TeamThreadTool().execute(
        {"action": "start", "task": "plan the migration", "cwd": "C:/proj", "mode": "peers"},
        _ctx(),
    )
    assert result.success
    assert result.output["job_id"] == "job-7"
    assert "job_status" in result.output["next"]
    assert result.output["members"][0]["name"] == "Claude"
    assert api.calls[0][3] == {"task": "plan the migration", "cwd": "C:/proj", "mode": "peers"}


async def test_team_thread_start_uses_the_chats_folder_and_needs_a_task(monkeypatch) -> None:
    api = _install(monkeypatch, team_thread_tool, _Api({("POST", "/api/team-threads"): (201, {})}))
    missing = await TeamThreadTool().execute({"action": "start"}, _ctx())
    assert not missing.success and "task" in (missing.error or "")
    await TeamThreadTool().execute({"action": "start", "task": "x"}, _ctx(cwd="C:/chatdir"))
    assert api.calls[0][3]["cwd"] == "C:/chatdir"


async def test_team_thread_refusal_is_an_honest_error_never_an_empty_success(monkeypatch) -> None:
    _install(
        monkeypatch,
        team_thread_tool,
        _Api({("POST", "/api/team-threads"): (409, {"detail": "Codex is not connected."})}),
    )
    result = await TeamThreadTool().execute({"action": "start", "task": "x"}, _ctx())
    assert not result.success
    assert "409" in result.error and "Codex is not connected." in result.error


async def test_team_thread_status_is_summary_first_with_a_tail_and_paging(monkeypatch) -> None:
    entries = [
        {
            "seq": n,
            "kind": "message",
            "author": "claude",
            "phase": "planning",
            "payload": {"text": f"entry {n} " + "x" * 5000},
        }
        for n in range(1, 31)
    ]
    snapshot = {
        "team_id": "t1",
        "state": "needs_input",
        "reason": "disagreement",
        "task": "t" * 3000,
        "members": [],
        "entries": entries,
    }
    api = _install(
        monkeypatch, team_thread_tool, _Api({("GET", "/api/team-threads/t1"): (200, snapshot)})
    )
    result = await TeamThreadTool().execute(
        {"action": "status", "team_id": "t1", "tail": 3}, _ctx()
    )
    assert result.success
    out = result.output
    assert out["state"] == "needs_input"
    assert [e["seq"] for e in out["entries"]] == [28, 29, 30]
    assert out["entries_total"] == 30 and "after" in out["more"]
    assert len(out["entries"][0]["text"]) < 1_600
    assert len(out["task"]) < 700
    paged = await TeamThreadTool().execute(
        {"action": "status", "team_id": "t1", "after": 10, "tail": 2}, _ctx()
    )
    assert api.calls[-1][2] == {"after": 10}
    assert [e["seq"] for e in paged.output["entries"]] == [1, 2]
    json.dumps(result.output)  # plain data


async def test_team_thread_answer_and_controls_post_to_the_thread(monkeypatch) -> None:
    api = _install(
        monkeypatch,
        team_thread_tool,
        _Api(
            {
                ("POST", "/api/team-threads/t1/message"): (
                    200,
                    {"team_id": "t1", "state": "running"},
                ),
                ("POST", "/api/team-threads/t1/stop"): (
                    200,
                    {"team_id": "t1", "state": "stopped"},
                ),
            }
        ),
    )
    answered = await TeamThreadTool().execute(
        {"action": "answer", "team_id": "t1", "text": "take plan B"}, _ctx()
    )
    assert answered.success and api.calls[0][3] == {"text": "take plan B"}
    stopped = await TeamThreadTool().execute({"action": "stop", "team_id": "t1"}, _ctx())
    assert stopped.output["state"] == "stopped"
    for args in ({"action": "answer", "team_id": "t1"}, {"action": "status"}):
        assert not (await TeamThreadTool().execute(args, _ctx())).success


async def test_team_thread_seats_and_list_are_trimmed(monkeypatch) -> None:
    seats_answer = {
        "seats": [
            {
                "provider": "claude",
                "label": "Claude Code",
                "ready": True,
                "secret": "no",
                "model_options": [1, 2, 3],
            }
        ],
        "default": [{"provider": "claude", "model": ""}],
        "min_members": 2,
        "max_members": 6,
    }
    threads_answer = {
        "threads": [
            {
                "team_id": "t1",
                "title": "A",
                "state": "done",
                "members": [{"name": "Claude"}],
                "cwd": "C:/x",
            }
        ]
    }
    _install(
        monkeypatch,
        team_thread_tool,
        _Api(
            {
                ("GET", "/api/team-threads/seats"): (200, seats_answer),
                ("GET", "/api/team-threads"): (200, threads_answer),
            }
        ),
    )
    seats = await TeamThreadTool().execute({"action": "seats"}, _ctx())
    assert seats.output["seats"] == [{"provider": "claude", "label": "Claude Code", "ready": True}]
    listed = await TeamThreadTool().execute({"action": "list"}, _ctx())
    assert listed.output["threads"][0]["members"] == ["Claude"]
    assert "cwd" not in listed.output["threads"][0]


# --------------------------------------------------------------- costs_summary


def _period(cost: float) -> dict[str, Any]:
    bucket = {"cost_usd": cost, "subscription_usd": 0.5, "tokens_total": 1000, "entries": 3}
    return {
        "totals": {
            "cost_usd": cost,
            "subscription_usd": 0.5,
            "tokens_total": 1000,
            "tokens_in": 600,
            "tokens_out": 400,
            "entries": 3,
            "gap_tokens": 0,
        },
        "by_agent": [
            {**bucket, "key": "jarvis", "name": "", "lead": True},
            {**bucket, "key": "a1", "name": "Scout", "lead": False},
        ],
        "by_provider": [{**bucket, "key": "claude"}],
        "by_model": [{**bucket, "key": "opus"}],
        "index": {"complete": True},
    }


async def test_costs_summary_reports_today_week_seats_and_quota(monkeypatch) -> None:
    usage = {
        "accounts": [
            {
                "platform": "claude",
                "plan": "Max",
                "status": "ok",
                "source": "live",
                "as_of": 1.0,
                "windows": [
                    {"kind": "five_hour", "percent": 80.0, "resets_at": 5, "scope_label": "5 h"}
                ],
            }
        ]
    }
    api = _Api(
        {
            ("GET", "/api/costs/summary"): (200, _period(1.25)),
            ("GET", "/api/agent-accounts/usage"): (200, usage),
        }
    )
    _install(monkeypatch, costs_summary_tool, api)
    monkeypatch.setattr(
        costs_summary_tool,
        "seat_problems",
        lambda: [{"provider": "codex", "kind": "quota", "reason": "usage limit reached"}],
    )
    result = await CostsSummaryTool().execute({}, _ctx())
    assert result.success
    out = result.output
    assert out["today"]["totals"]["cost_usd"] == 1.25
    assert out["week"]["by_agent"][0]["lead"] is True
    assert out["week"]["by_agent"][1]["name"] == "Scout"
    assert out["seats_in_trouble"][0]["provider"] == "codex"
    window = out["subscription_quota"][0]["windows"][0]
    assert window["headroom_percent"] == 20.0
    since = [c[2]["since_ms"] for c in api.calls if c[1] == "/api/costs/summary"]
    assert since[0] > since[1], "today starts after the week's first day"


async def test_costs_summary_single_period_without_quota_and_a_failed_read(monkeypatch) -> None:
    api = _install(
        monkeypatch, costs_summary_tool, _Api({("GET", "/api/costs/summary"): (200, _period(2.0))})
    )
    monkeypatch.setattr(costs_summary_tool, "seat_problems", lambda: [])
    one = await CostsSummaryTool().execute({"period": "today", "quota": False}, _ctx())
    assert set(one.output) == {"today", "seats_in_trouble"}
    assert [c[1] for c in api.calls] == ["/api/costs/summary"]
    bad = await CostsSummaryTool().execute({"period": "month"}, _ctx())
    assert not bad.success
    _install(monkeypatch, costs_summary_tool, _Api({}))
    down = await CostsSummaryTool().execute({"quota": False}, _ctx())
    assert not down.success and "404" in down.error


async def test_costs_summary_survives_an_unreadable_quota(monkeypatch) -> None:
    _install(
        monkeypatch,
        costs_summary_tool,
        _Api(
            {
                ("GET", "/api/costs/summary"): (200, _period(1.0)),
                ("GET", "/api/agent-accounts/usage"): (500, {"detail": "boom"}),
            }
        ),
    )
    monkeypatch.setattr(costs_summary_tool, "seat_problems", lambda: [])
    result = await CostsSummaryTool().execute({"period": "today"}, _ctx())
    assert result.success
    assert "unavailable" in result.output["subscription_quota"]


def test_seat_problems_reads_the_passive_seat_record() -> None:
    from dodaios.brain import seat_health

    health = seat_health.SeatHealth()
    health.record_failure("codex", "acct", "You have hit your usage limit. Try again in 2 hours.")
    seat_health.set_seat_health(health)
    try:
        rows = costs_summary_tool.seat_problems()
    finally:
        seat_health.set_seat_health(None)
    assert rows and rows[0]["provider"] == "codex" and rows[0]["kind"] == "quota"
    assert "usage limit" in rows[0]["reason"]


# ------------------------------------------------------------------- artifacts


async def test_artifacts_list_pages_and_trims(monkeypatch) -> None:
    sessions = [
        {
            "slug": f"s{n}",
            "utterance": "u" * 400,
            "status": "done",
            "summary": "s",
            "artifact_count": n,
            "mission_id": f"m{n}",
            "internal": "x",
        }
        for n in range(30)
    ]
    api = _install(
        monkeypatch, artifacts_tool, _Api({("GET", "/api/outputs"): (200, {"sessions": sessions})})
    )
    result = await ArtifactsTool().execute({"action": "list", "limit": 10}, _ctx())
    out = result.output
    assert [o["slug"] for o in out["outputs"]] == [f"s{n}" for n in range(10)]
    assert out["total"] == 30 and out["next_offset"] == 10
    assert len(out["outputs"][0]["request"]) <= 161 and "internal" not in out["outputs"][0]
    second = await ArtifactsTool().execute({"action": "list", "limit": 10, "offset": 25}, _ctx())
    assert [o["slug"] for o in second.output["outputs"]] == [f"s{n}" for n in range(25, 30)]
    assert "next_offset" not in second.output
    assert api.calls[0][:2] == ("GET", "/api/outputs")


async def test_artifacts_files_and_read_are_bounded_and_say_when_cut(monkeypatch) -> None:
    files = {
        "files": [
            {
                "path": "tasks/t/artifacts/files/a.md",
                "title": None,
                "size": 9,
                "is_text": True,
                "mtime": 1.0,
                "preview": "SECRET PREVIEW",
            }
        ]
    }
    raw = {
        "path": "tasks/t/artifacts/files/a.md",
        "size": 99_000,
        "text": "w" * 40_000,
        "truncated": False,
    }
    api = _install(
        monkeypatch,
        artifacts_tool,
        _Api(
            {
                ("GET", "/api/outputs/s1/artifacts"): (200, files),
                ("GET", "/api/outputs/s1/files/tasks/t/artifacts/files/a.md/raw"): (200, raw),
            }
        ),
    )
    listed = await ArtifactsTool().execute({"action": "files", "slug": "s1"}, _ctx())
    assert "preview" not in json.dumps(listed.output)
    read = await ArtifactsTool().execute(
        {"action": "read", "slug": "s1", "path": "tasks/t/artifacts/files/a.md"}, _ctx()
    )
    assert read.success and read.output["truncated"] is True
    assert len(read.output["text"]) <= 16_000 and "first 16000" in read.output["note"]
    assert api.calls[-1][1].endswith("/raw")
    for args in ({"action": "files"}, {"action": "read", "slug": "s1"}, {"action": "nope"}):
        assert not (await ArtifactsTool().execute(args, _ctx())).success


async def test_artifacts_living_pages_list_and_read_one(monkeypatch) -> None:
    pages = {
        "pages": [
            {
                "slug": "p1",
                "title": "Prices",
                "track": "t" * 400,
                "every_minutes": 60,
                "refreshing": True,
                "rows": [{"a": 1}, {"a": 2}],
                "updated_at": 5,
                "html": "NO",
            }
        ]
    }
    one = {
        "id": "abc",
        "title": "Prices",
        "track": "t",
        "columns": ["a"],
        "rows": [{"a": 1}],
        "every_minutes": 60,
        "refreshing": True,
        "slug": "p1",
        "extra": {"x": 1},
    }
    api = _install(
        monkeypatch,
        artifacts_tool,
        _Api(
            {
                ("GET", "/api/living-pages"): (200, pages),
                ("GET", "/api/living-pages/by-slug/p1"): (200, one),
            }
        ),
    )
    listed = await ArtifactsTool().execute({"action": "living"}, _ctx())
    assert listed.output["pages"][0]["rows"] == 2 and "html" not in listed.output["pages"][0]
    detail = await ArtifactsTool().execute({"action": "living", "slug": "p1"}, _ctx())
    assert detail.output["rows"] == [{"a": 1}] and "extra" not in detail.output
    assert api.calls[-1][1] == "/api/living-pages/by-slug/p1"


def test_the_three_tools_are_in_the_lead_set_and_read_only_where_promised() -> None:
    from dodaios.brain.tool_gateway import BrainSupervisorToolGateway

    gateway = BrainSupervisorToolGateway(SimpleNamespace(_tools={}))
    lead = gateway.lead_extra_tools()
    assert {"team_thread", "costs_summary", "artifacts"} <= set(lead)
    assert lead["costs_summary"].risk_tier == "safe" and lead["artifacts"].risk_tier == "safe"
    assert not lead["costs_summary"].is_action_tool
