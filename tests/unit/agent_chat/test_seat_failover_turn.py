"""A thread turn its seat's usage limit cut off carries on on the next seat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import runner_cli
from dodaios.agentic_ide import seat_switch
from dodaios.society import remote

LIMIT = "Claude AI usage limit reached|1900000000"


def _handle(events: list[dict[str, Any]]) -> Any:
    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    return SimpleNamespace(turn_id="t1", session=SimpleNamespace(), emit=emit)


@pytest.fixture(autouse=True)
def _local(monkeypatch: pytest.MonkeyPatch) -> None:
    async def here(_session: Any) -> None:
        return None

    monkeypatch.setattr(remote, "placement_for_session", here)
    monkeypatch.setattr(seat_switch, "_label", lambda account_id: account_id.upper())


def _run(
    monkeypatch: pytest.MonkeyPatch,
    outcome: runner_cli._Outcome,
    *,
    target: str | None,
    started_work: bool,
    runner: str = "claude-cli",
) -> tuple[runner_cli._Outcome, list[tuple[str, str | None]], list[dict[str, Any]], list[str]]:
    asked: list[str] = []

    async def fail_over(platform: str, account_id: str, *, error: str = "") -> str | None:
        asked.append(f"{platform}:{account_id}")
        return target

    monkeypatch.setattr(seat_switch, "fail_over", fail_over)
    runs: list[tuple[str, str | None]] = []

    async def run_again(prompt: str, conversation: str | None) -> runner_cli._Outcome:
        runs.append((prompt, conversation))
        return runner_cli._Outcome("done", None, {"output_tokens": 5}, None, conversation)

    events: list[dict[str, Any]] = []
    result = asyncio.run(
        runner_cli._continue_on_next_seat(
            _handle(events),
            outcome,
            runner,
            {"claude": "seat-a"},
            started_work=started_work,
            run_again=run_again,
            user_text="fix the bug",
            resume="conv-1",
        )
    )
    return result, runs, events, asked


def test_a_turn_cut_off_mid_work_continues_its_conversation_on_the_next_seat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = runner_cli._Outcome("error", LIMIT, {"output_tokens": 7}, None, "conv-2")

    result, runs, events, asked = _run(monkeypatch, refused, target="seat-b", started_work=True)

    assert asked == ["claude:seat-a"]
    assert runs == [(seat_switch.CONTINUE_PROMPT, "conv-2")]
    assert (result.status, result.error, result.vendor_session) == ("done", None, "conv-2")
    assert result.usage == {"output_tokens": 12}
    notice = events[0]["payload"]
    assert notice["kind"] == runner_cli.SEAT_SWITCH_NOTICE_KIND
    assert (notice["from_label"], notice["to_label"]) == ("SEAT-A", "SEAT-B")


def test_a_turn_refused_before_it_started_sends_the_message_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = runner_cli._Outcome("error", LIMIT, {}, None, None)

    _result, runs, _events, _asked = _run(monkeypatch, refused, target="seat-b", started_work=False)

    assert runs == [("fix the bug", "conv-1")]


@pytest.mark.parametrize(
    ("error", "target", "runner"),
    [
        ("Something else broke", "seat-b", "claude-cli"),  # not a usage limit
        (LIMIT, None, "claude-cli"),  # no other seat with budget
        (LIMIT, "seat-b", "agy-cli"),  # its conversation cannot follow a seat
    ],
)
def test_otherwise_the_refusal_stands(
    monkeypatch: pytest.MonkeyPatch, error: str, target: str | None, runner: str
) -> None:
    refused = runner_cli._Outcome("error", error, {}, None, "conv-2")

    result, runs, events, _asked = _run(
        monkeypatch, refused, target=target, started_work=True, runner=runner
    )

    assert result is refused
    assert runs == []
    assert events == []


def test_the_seat_a_turn_runs_on_is_remembered_and_watched() -> None:
    seat_switch.reset()
    seats: dict[str, str] = {}
    token = runner_cli._TURN_SEATS.set(seats)
    try:
        runner_cli._note_turn_seat("codex", "codex:x")
    finally:
        runner_cli._TURN_SEATS.reset(token)
    runner_cli._note_turn_seat("codex", "codex:y")  # model discovery: not a turn

    assert seats == {"codex": "codex:x"}
    assert seat_switch._outside_seats() == {"codex": {"codex:x"}}
    seat_switch.reset()
