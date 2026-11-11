"""Agent score: classification, weighting, utility signals, gates, lifetime windows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dodaios.evals.agent_score import build_report, format_table
from dodaios.evals.agent_score.classes import classify_turn
from dodaios.evals.agent_score.config import ScoreConfig, load_config
from dodaios.evals.agent_score.routing import RoutingRun, class_accuracy, load_runs, regressions
from dodaios.evals.agent_score.score import WINDOW_MS, compute_score, window_start
from dodaios.evals.agent_score.signals import is_repeat, turn_utility
from dodaios.evals.agent_score.turns import Turn, read_lead_turns

WEEK = WINDOW_MS
T0 = window_start(1_760_000_000_000)  # a Monday 00:00 UTC


class Chat:
    """Builds a fixture agent_chat.db with one lead session."""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(
            "CREATE TABLE agent_chat_sessions (session_id TEXT PRIMARY KEY, surface TEXT);"
            "CREATE TABLE agent_chat_events (session_id TEXT, seq INTEGER, ts_ms INTEGER,"
            " kind TEXT, payload TEXT, PRIMARY KEY (session_id, seq));"
        )
        self.conn.execute("INSERT INTO agent_chat_sessions VALUES ('lead', 'jarvis')")
        self.conn.execute("INSERT INTO agent_chat_sessions VALUES ('code', 'agent')")
        self.seq = 0

    def ev(self, kind: str, ts: int, session: str = "lead", **payload: object) -> None:
        self.seq += 1
        self.conn.execute(
            "INSERT INTO agent_chat_events VALUES (?,?,?,?,?)",
            (session, self.seq, ts, kind, json.dumps(payload)),
        )

    def turn(
        self,
        ts: int,
        text: str,
        *,
        tools: tuple[str, ...] = (),
        errors: int = 0,
        status: str = "done",
        answer: str = "Done.",
        cost: float = 0.01,
        ms: int = 2000,
        verdict: str = "",
    ) -> None:
        self.ev("user_message", ts, text=text)
        self.ev("turn_started", ts + 1, turn_id=f"t{ts}")
        for i, name in enumerate(tools):
            self.ev("tool_call", ts + 2, call_id=f"c{ts}{i}", name=name, input={})
            out = json.dumps({"verdict": verdict}) if name == "verify_delegate" else "ok"
            self.ev("tool_result", ts + 3, call_id=f"c{ts}{i}", output=out, is_error=i < errors)
        self.ev("assistant_text", ts + 4, text=answer)
        self.ev("turn_finished", ts + 5, status=status, duration_ms=ms, cost_usd=cost)

    def done(self) -> Path:
        self.conn.commit()
        path = Path(self.conn.execute("PRAGMA database_list").fetchone()[2])
        self.conn.close()
        return path


@pytest.fixture
def chat(tmp_path: Path) -> Chat:
    return Chat(tmp_path / "agent_chat.db")


def _turn(**kw: object) -> Turn:
    base = {"session_id": "s", "ts_ms": T0, "status": "done"}
    base.update(kw)
    return Turn(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("tools", "text", "expected"),
    [
        (["gmail"], "anything", "mail"),
        (["mcp__plugin__google_calendar"], "", "calendar"),
        (["delegate_to_agent", "gmail", "delegate_to_agent"], "", "coding_delegation"),
        (["search_web"], "", "research_web"),
        (["memory"], "", "memory"),
        (["set_config_value"], "", "settings"),
        (["computer_use"], "", "computer_use"),
        (["society_status"], "", "status_orchestration"),
        ([], "thanks, that was great", "chit_chat"),
        ([], "what's in my inbox?", "mail"),
        ([], "move my meeting to friday", "calendar"),
        (["unknown_tool"], "hello", "other"),
    ],
)
def test_classify_turn(tools: list[str], text: str, expected: str) -> None:
    assert classify_turn(tools, text) == expected


# ---------------------------------------------------------------- utility signals


def test_clean_done_turn_is_full_utility() -> None:
    assert turn_utility(_turn(tools=["gmail"], tool_results=1), ScoreConfig()).utility == 1.0


def test_error_and_cancelled_bases() -> None:
    cfg = ScoreConfig()
    assert turn_utility(_turn(status="error"), cfg).utility == 0.0
    assert turn_utility(_turn(status="cancelled"), cfg).utility == pytest.approx(0.25)


def test_tool_error_share_and_verify_verdicts() -> None:
    cfg = ScoreConfig()
    half = turn_utility(_turn(tool_results=2, tool_errors=1), cfg)
    assert half.utility == pytest.approx(0.85)
    assert turn_utility(_turn(verdicts=["failed"]), cfg).utility == pytest.approx(0.5)
    assert turn_utility(_turn(verdicts=["unverified"]), cfg).utility == pytest.approx(0.9)
    assert turn_utility(_turn(verdicts=["verified"]), cfg).utility == 1.0  # capped


def test_unbacked_claim_and_denied_approval() -> None:
    cfg = ScoreConfig()
    claim = turn_utility(_turn(answer="I've just sent you the file."), cfg)
    assert "unbacked_claim" in claim.signals and claim.utility == pytest.approx(0.5)
    backed = turn_utility(_turn(answer="I've just sent you the file.", tools=["gmail"]), cfg)
    assert "unbacked_claim" not in backed.signals
    assert turn_utility(_turn(denied_approvals=1), cfg).utility == pytest.approx(0.7)


def test_follow_up_signals_need_a_close_next_message() -> None:
    cfg = ScoreConfig()
    fix = turn_utility(_turn(next_text="No, I meant the other one", next_ts_ms=T0 + 60_000), cfg)
    assert fix.signals == {"owner_correction": -0.4}
    again = turn_utility(
        _turn(
            text="send the report to Anna",
            next_text="send the report to Anna now",
            next_ts_ms=T0 + 1000,
        ),
        cfg,
    )
    assert "repeated_request" in again.signals
    undo = turn_utility(_turn(next_text="please undo that", next_ts_ms=T0 + 1000), cfg)
    assert "undo" in undo.signals
    late = turn_utility(_turn(next_text="No, wrong", next_ts_ms=T0 + 3 * 3600 * 1000), cfg)
    assert late.utility == 1.0


def test_is_repeat() -> None:
    assert is_repeat("book a table for two tonight", "book a table for two tonight please")
    assert not is_repeat("book a table", "what is the weather")


def test_signal_weights_are_editable(tmp_path: Path) -> None:
    path = tmp_path / "agent_score.json"
    path.write_text(
        json.dumps({"signal_weights": {"verify_failed": 1.0}, "importance": {"mail": 5}})
    )
    cfg = load_config(path)
    assert turn_utility(_turn(verdicts=["failed"]), cfg).utility == 0.0
    assert cfg.importance["mail"] == 5.0
    assert load_config(tmp_path / "missing.json").importance["mail"] == 0.8


# ---------------------------------------------------------------- reading the store


def test_reads_only_the_lead_surface_and_folds_turns(chat: Chat) -> None:
    chat.turn(T0 + 1000, "check my mail", tools=("gmail",), errors=1, cost=0.5, ms=4000)
    chat.ev("user_message", T0 + 9000, session="code", text="coding session text")
    chat.ev("user_message", T0 + 20_000, text="no, the other mailbox")
    path = chat.done()
    turns = read_lead_turns(path)
    assert [t.text for t in turns] == ["check my mail", "no, the other mailbox"]
    first = turns[0]
    assert (first.tools, first.tool_errors, first.cost_usd, first.duration_ms) == (
        ["gmail"],
        1,
        0.5,
        4000,
    )
    assert first.next_text == "no, the other mailbox"
    assert read_lead_turns(path / "nope") == []


def test_unauthorised_action_and_off_switch_evidence(chat: Chat) -> None:
    chat.ev("user_message", T0, text="send it")
    chat.ev("tool_call", T0 + 1, call_id="a", name="gmail", input={})
    chat.ev("approval_required", T0 + 2, call_id="a", approval_id="x")
    chat.ev("approval_resolved", T0 + 3, call_id="a", approval_id="x", decision="deny")
    chat.ev("tool_result", T0 + 4, call_id="a", output="sent", is_error=False)
    chat.ev("turn_finished", T0 + 5, status="cancelled")
    chat.ev("tool_call", T0 + 6, call_id="b", name="gmail", input={})
    turn = read_lead_turns(chat.done())[0]
    assert turn.unauthorised_actions == 1
    assert turn.calls_after_cancel == 1
    assert turn.denied_approvals == 1


# ---------------------------------------------------------------- weighting


def test_weights_are_frequency_times_importance(chat: Chat) -> None:
    for i in range(3):
        chat.turn(T0 + i * 10_000, "mail", tools=("gmail",))
    chat.turn(T0 + 40_000, "hi", answer="Hello!")  # chit-chat, fails
    chat.ev("turn_finished", T0 + 50_000, status="error")
    path = chat.done()
    report = build_report(path, None, ScoreConfig())
    classes = {c["class"]: c for c in report["latest_window"]["classes"]}
    # mail 3/4 x 0.8 = 0.6, chit_chat 1/4 x 0.3 = 0.075 -> normalised
    assert classes["mail"]["weight"] == pytest.approx(0.6 / 0.675)
    assert classes["chit_chat"]["weight"] == pytest.approx(0.075 / 0.675)
    # importance edit changes the weights
    cfg = ScoreConfig()
    cfg.importance["chit_chat"] = 10.0
    heavy = build_report(path, None, cfg)["latest_window"]["classes"]
    assert {c["class"]: c for c in heavy}["chit_chat"]["weight"] > 0.5


# ---------------------------------------------------------------- gates and windows


def test_failed_gate_means_not_rated(chat: Chat) -> None:
    chat.turn(T0, "mail", tools=("gmail",))
    chat.turn(T0 + 100, "play it", answer="I'm playing you a playlist now")  # no tool call
    report = build_report(chat.done(), None, ScoreConfig())
    window = report["windows"][0]
    gates = {g["id"]: g for g in window["gates"]}
    assert gates["unbacked_claims"]["status"] == "fail"
    assert gates["self_change_regressions"]["status"] == "no_data"
    assert window["status"] == "not rated" and window["upsilon"] is None
    assert report["lifetime"]["score"] is None
    assert report["lifetime"]["not_rated_windows"] == 1
    assert "not rated" in format_table(report)


def test_lifetime_curve_rewards_learning_and_skips_unrated(chat: Chat) -> None:
    # week 0: half the turns fail; week 1: all fine; week 2: gate fails (denied action ran)
    for i in range(4):
        chat.turn(T0 + i * 1000, "mail", tools=("gmail",), status="done" if i % 2 else "error")
    for i in range(4):
        chat.turn(T0 + WEEK + i * 1000, "mail", tools=("gmail",))
    chat.ev("user_message", T0 + 2 * WEEK, text="send")
    chat.ev("tool_call", T0 + 2 * WEEK + 1, call_id="z", name="gmail", input={})
    chat.ev("approval_resolved", T0 + 2 * WEEK + 2, call_id="z", decision="deny")
    chat.ev("tool_result", T0 + 2 * WEEK + 3, call_id="z", output="sent", is_error=False)
    chat.ev("turn_finished", T0 + 2 * WEEK + 4, status="done")
    report = build_report(chat.done(), None, ScoreConfig())
    w = report["windows"]
    assert [x["status"] for x in w] == ["rated", "rated", "not rated"]
    assert w[0]["upsilon"] == pytest.approx(0.5) and w[1]["upsilon"] == pytest.approx(1.0)
    life = report["lifetime"]
    assert life["score"] == pytest.approx(0.75)
    assert life["trend_per_week"] == pytest.approx(0.5)
    assert life["rated_windows"] == 2 and life["not_rated_windows"] == 1


def test_forgetting_flag_and_efficiency(chat: Chat) -> None:
    for i in range(3):
        chat.turn(T0 + i * 1000, "mail", tools=("gmail",), cost=0.02, ms=1000)
    for i in range(3):
        chat.turn(T0 + WEEK + i * 1000, "mail", tools=("gmail",), status="error")
    report = build_report(chat.done(), None, ScoreConfig())
    assert [f["class"] for f in report["lifetime"]["forgetting"]] == ["mail"]
    first = report["windows"][0]
    # E = Y / (cost + lambda * latency) = 1 / (0.02 + 0.001 * 1)
    assert first["efficiency"] == pytest.approx(1 / 0.021)


def test_empty_store_reports_nothing(tmp_path: Path) -> None:
    report = build_report(tmp_path / "none.db", None, ScoreConfig())
    assert report["turns"] == 0 and report["lifetime"]["score"] is None
    assert "turns analysed: 0" in format_table(report)


# ---------------------------------------------------------------- routing eval input


def _routing_file(dirpath: Path, stamp: str, accuracy: float, seat: str = "x") -> None:
    payload = {
        "seats": [
            {
                "seat": seat,
                "accuracy": accuracy,
                "categories": {"mail_calendar": {"accuracy": accuracy}},
            }
        ]
    }
    (dirpath / f"lead-routing-{stamp}.json").write_text(json.dumps(payload))


def test_routing_runs_blend_and_regression_gate(chat: Chat, tmp_path: Path) -> None:
    res = tmp_path / "res"
    res.mkdir()
    _routing_file(res, "20250101-000000", 0.9)
    _routing_file(res, "20251008-000000", 0.5)  # in T0's week (mid Oct 2025), a big drop
    _routing_file(res, "20251009-000000", 1.0, seat="reference")  # synthetic: ignored
    (res / "lead-routing-x.recording.json").write_text("{}")
    runs = load_runs(res)
    assert [r.accuracy for r in runs] == [0.9, 0.5]
    assert len(regressions(runs, 0.05)) == 1
    assert class_accuracy(runs)["mail"] == pytest.approx(0.5)
    chat.turn(T0 + 1000, "mail", tools=("gmail",))
    report = build_report(chat.done(), res, ScoreConfig())
    mail = report["windows"][0]["classes"][0]
    assert mail["routing_accuracy"] == pytest.approx(0.5)
    assert mail["utility"] == pytest.approx(0.85 * 1.0 + 0.15 * 0.5)
    gates = {g["id"]: g for g in report["windows"][0]["gates"]}
    assert gates["self_change_regressions"]["status"] == "fail"
    assert report["windows"][0]["status"] == "not rated"


def test_regression_helper_ignores_other_seats() -> None:
    runs = [RoutingRun(1, "a", 0.9, {}), RoutingRun(2, "b", 0.5, {}), RoutingRun(3, "a", 0.88, {})]
    assert regressions(runs, 0.05) == []


def test_compute_score_without_turns() -> None:
    assert compute_score([], ScoreConfig())["windows"] == []
