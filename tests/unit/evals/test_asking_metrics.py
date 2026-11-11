"""Value-of-information asking in the agent score: needless and should-have-asked rates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dodaios.evals.agent_score import build_report, format_table
from dodaios.evals.agent_score.asking import ask_report
from dodaios.evals.agent_score.turns import Turn
from dodaios.trust.ask_log import AskLog, is_needless_signal

T0 = 1_760_000_000_000
MIN = 60_000


def _turn(ts: int, nxt: str = "", nxt_ts: int = 0, session: str = "lead") -> Turn:
    return Turn(
        session, ts, text="do it", status="done", next_text=nxt, next_ts_ms=nxt_ts or ts + MIN
    )


def _row(ts: int, decision: str, **kw: Any) -> dict[str, Any]:
    return {
        "ts_ms": ts,
        "session_id": "lead",
        "question": "Which room?",
        "decision": decision,
        "reason": "r",
        "needless": "",
        **kw,
    }


def test_needless_phrases_in_three_languages() -> None:
    assert is_needless_signal("You already knew that, just do it")
    assert is_needless_signal("Das habe ich dir schon gesagt")  # i18n-allow: DE matcher
    assert is_needless_signal("mach einfach")
    assert is_needless_signal("ya lo sabes")
    assert not is_needless_signal("The big room, please")


def test_needless_rate_counts_logged_labels_and_the_owners_next_message() -> None:
    turns = [_turn(T0, "just do it next time", T0 + 2 * MIN), _turn(T0 + 10 * MIN)]
    rows = [
        _row(T0 + MIN, "ask"),  # the next message says so
        _row(T0 + 11 * MIN, "ask", needless="in_memory"),  # labelled when answered
        _row(T0 + 12 * MIN, "ask"),  # a fair question
    ]
    report = ask_report(rows, turns)
    assert report["asked"] == 3 and report["needless"] == 2
    assert report["needless_rate"] == 2 / 3


def test_should_have_asked_when_the_owner_corrects_an_assumption() -> None:
    turns = [
        _turn(T0, "No, I meant the small room", T0 + 2 * MIN),
        _turn(T0 + 10 * MIN, "thanks", T0 + 11 * MIN),
        _turn(T0 + 20 * MIN, "undo that", T0 + 21 * MIN),
    ]
    rows = [
        _row(T0 + MIN, "act_with_assumption"),
        _row(T0 + 10 * MIN + 1000, "act_with_assumption"),
        _row(T0 + 20 * MIN + 1000, "trimmed"),
        _row(T0 + 30 * MIN, "answer_from_memory"),
    ]
    report = ask_report(rows, turns)
    assert report["acted_with_assumption"] == 3 and report["should_have_asked"] == 2
    assert report["should_have_asked_rate"] == 2 / 3
    assert report["answered_from_memory"] == 1


def test_a_late_reply_is_not_about_the_assumption() -> None:
    turns = [_turn(T0, "no, that is wrong", T0 + 5 * 3600 * 1000)]
    report = ask_report([_row(T0 + MIN, "act_with_assumption")], turns)
    assert report["should_have_asked"] == 0


def test_no_rows_gives_no_rates() -> None:
    report = ask_report([], [_turn(T0)])
    assert report["needless_rate"] is None and report["should_have_asked_rate"] is None
    assert report["questions_per_turn"] == 0


def test_the_report_carries_the_component_and_the_table_prints_it(tmp_path: Path) -> None:
    log = AskLog(tmp_path / "ask.db")
    log.record(question="Which room?", decision="ask", needless="in_memory", ts_ms=T0)
    log.record(question="Which font?", decision="act_with_assumption", ts_ms=T0 + 1)
    report = build_report(tmp_path / "missing.db", tmp_path / "none", asks=log)
    assert report["asking"]["asked"] == 1 and report["asking"]["needless"] == 1
    assert "needless questions: 1" in format_table(report)
    assert build_report(tmp_path / "missing.db", tmp_path / "none")["asking"] is None
    log.close()
