"""A routine's run history is read from its task steps and, for older runs, its chat."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dodaios.society.routine_history import enrich_from_chat, parse_runs, run_summary_line


def _steps(*events: tuple[float, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"seq": i + 1, "kind": "log", "timestamp_ns": int(at * 1e9), "payload": payload}
        for i, (at, payload) in enumerate(events)
    ]


def test_a_completed_run_carries_its_seat_duration_and_cost() -> None:
    runs = parse_runs(
        "t1",
        _steps(
            (100, {"event": "run_started"}),
            (100, {"event": "routine_chat", "session_id": "society:a:routine:t1:x"}),
            (
                142,
                {
                    "event": "routine_summary",
                    "duration_ms": 41_500,
                    "cost_usd": 0.0123,
                    "provider": "claude-cli",
                    "model": "sonnet",
                    "billed_via_key": False,
                },
            ),
            (142, {"event": "agent_result", "text": "## Inbox\n- **3** new invoices"}),
            (142, {"event": "run_completed", "duration_ms": 42_000}),
        ),
    )
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed" and run.origin == "automatic"
    assert run.duration_ms == 41_500  # the turn's own time wins over the task wrapper
    assert run.cost_usd == 0.0123 and run.billed_via_key is False
    assert run.provider == "claude-cli" and run.model == "sonnet"
    assert run.session_id == "society:a:routine:t1:x"
    assert run.summary == "Inbox"
    assert run.started_ms == 100_000 and run.finished_ms == 142_000


def test_run_now_marks_the_next_run_as_the_persons_own() -> None:
    runs = parse_runs(
        "t1",
        _steps(
            (10, {"event": "run_started"}),
            (11, {"event": "run_completed", "duration_ms": 1000}),
            (20, {"event": "run_now"}),
            (20, {"event": "run_started"}),
            (25, {"event": "error", "message": "RuntimeError: seat offline"}),
        ),
    )
    assert [r.origin for r in runs] == ["automatic", "manual"]
    assert runs[1].status == "failed" and runs[1].error == "RuntimeError: seat offline"
    assert runs[1].duration_ms == 5000


def test_a_skip_keeps_its_reason_code_and_absorbs_the_legacy_error_line() -> None:
    runs = parse_runs(
        "t1",
        _steps(
            (10, {"event": "run_started"}),
            (
                10,
                {
                    "event": "skipped",
                    "code": "api_key_seat",
                    "provider": "gemini",
                    "message": "did not bill",
                },
            ),
            (10, {"event": "error", "message": "did not bill"}),
        ),
    )
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert (runs[0].skip_code, runs[0].skip_provider) == ("api_key_seat", "gemini")


def test_older_records_without_boundaries_stay_visible() -> None:
    runs = parse_runs("t1", _steps((5, {"event": "agent_result", "text": "Old answer"})))
    assert runs[0].status == "legacy" and runs[0].summary == "Old answer"


def test_a_run_cut_off_by_a_new_start_reads_as_interrupted() -> None:
    runs = parse_runs("t1", _steps((1, {"event": "run_started"}), (9, {"event": "run_started"})))
    assert [r.status for r in runs] == ["interrupted", "running"]


def test_an_older_run_reads_cost_and_summary_from_its_own_first_turn() -> None:
    runs = parse_runs(
        "t1",
        _steps(
            (1, {"event": "run_started"}),
            (1, {"event": "routine_chat", "session_id": "s1"}),
            (3, {"event": "run_completed", "duration_ms": 2000}),
        ),
    )
    events = [
        {"kind": "turn_started", "payload": {"turn_id": "a"}},
        {"kind": "assistant_text", "payload": {"turn_id": "a", "text": "Found two new posts."}},
        {
            "kind": "turn_finished",
            "payload": {"turn_id": "a", "cost_usd": 0.5, "duration_ms": 1800},
        },
        # A follow-up the person asked later in the same chat does not count.
        {"kind": "turn_started", "payload": {"turn_id": "b"}},
        {"kind": "turn_finished", "payload": {"turn_id": "b", "cost_usd": 9.0}},
    ]
    store = SimpleNamespace(list_events=lambda session_id: events if session_id == "s1" else [])
    enrich_from_chat(runs[0], store)
    assert runs[0].cost_usd == 0.5
    assert runs[0].summary == "Found two new posts."
    assert runs[0].duration_ms == 2000


def test_a_run_with_a_summary_step_never_reopens_its_chat() -> None:
    # CLI seats often report no cost: the history must not re-read that chat
    # on every poll just because cost_usd stays empty.
    runs = parse_runs(
        "t1",
        _steps(
            (1, {"event": "run_started"}),
            (1, {"event": "routine_chat", "session_id": "s1"}),
            (2, {"event": "routine_summary", "duration_ms": 900, "cost_usd": None}),
            (3, {"event": "run_completed", "duration_ms": 2000}),
        ),
    )

    def explode(session_id: str) -> list[dict[str, Any]]:
        raise AssertionError("the chat was read")

    enrich_from_chat(runs[0], SimpleNamespace(list_events=explode))
    assert runs[0].duration_ms == 900 and runs[0].cost_usd is None
    assert "recorded" not in runs[0].to_dict()


def test_a_missing_chat_store_leaves_the_run_as_parsed() -> None:
    run = parse_runs("t1", _steps((1, {"event": "run_started"})))[0]
    enrich_from_chat(run, None)
    assert run.cost_usd is None


def test_summary_lines_drop_markdown_and_are_capped() -> None:
    assert run_summary_line("---\n> **Done**: all good") == "Done: all good"
    assert len(run_summary_line("x" * 400)) == 160
    assert run_summary_line("") == ""


async def test_the_runner_records_one_summary_step_per_run(monkeypatch) -> None:
    from dodaios.society import routine_runner

    steps: list[tuple[str, str, dict[str, Any]]] = []

    async def append_step(task_id: str, kind: str, payload: dict[str, Any]) -> int:
        steps.append((task_id, kind, payload))
        return len(steps)

    monkeypatch.setattr(routine_runner, "_billed_via_api", lambda provider, account_id="": False)
    await routine_runner._record_run_summary(
        SimpleNamespace(append_step=append_step),
        "t1",
        "s1",
        "turn",
        {"status": "done", "duration_ms": 1234, "cost_usd": 0.5},
        provider="hermes",
        model="m",
        account_id="",
    )
    assert steps == [
        (
            "t1",
            "log",
            {
                "event": "routine_summary",
                "session_id": "s1",
                "turn_id": "turn",
                "status": "done",
                "duration_ms": 1234,
                "cost_usd": 0.5,
                "provider": "hermes",
                "model": "m",
                "billed_via_key": False,
            },
        )
    ]
    run = parse_runs(
        "t1",
        [
            {"seq": 1, "kind": "log", "timestamp_ns": 0, "payload": {"event": "run_started"}},
            {"seq": 2, "kind": "log", "timestamp_ns": 0, "payload": steps[0][2]},
        ],
    )[0]
    assert run.duration_ms == 1234 and run.provider == "hermes"
    # No store (a bare runtime) is not an error.
    await routine_runner._record_run_summary(
        None, "t1", "s1", "turn", {}, provider="x", model="", account_id=""
    )
