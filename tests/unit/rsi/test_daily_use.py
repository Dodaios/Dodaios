"""How daily use went, week by week: what the Self-improvement page shows beside the benchmark."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dodaios.evals.agent_score.score import WINDOW_MS, window_start
from dodaios.rsi import overview

WEEK = WINDOW_MS
T0 = window_start(1_760_000_000_000)  # a Monday 00:00 UTC
#: Requests that share no words, so none reads as the one before asked again.
ASKED = (
    "check my mail", "weather in Lisbon tomorrow", "play some jazz", "remind me at five",
    "open the notes app", "how far away is the moon", "book a table for two",
    "translate this into French",
)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overview, "_daily_cache", {})


def _chat(path: Path, turns: list[tuple[int, str]]) -> Path:
    """A chat record with one lead session; each turn is (time, status).

    Every request is worded differently: the same words twice count as asked again.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE agent_chat_sessions (session_id TEXT PRIMARY KEY, surface TEXT);"
        "CREATE TABLE agent_chat_events (session_id TEXT, seq INTEGER, ts_ms INTEGER,"
        " kind TEXT, payload TEXT, PRIMARY KEY (session_id, seq));"
        "INSERT INTO agent_chat_sessions VALUES ('lead', 'jarvis');"
    )
    seq = 0
    for ts, status in turns:
        for offset, kind, payload in (
            (0, "user_message", {"text": ASKED[(seq // 6) % len(ASKED)]}),
            (1, "turn_started", {"turn_id": f"t{ts}"}),
            (2, "tool_call", {"call_id": f"c{ts}", "name": "gmail", "input": {}}),
            (3, "tool_result", {"call_id": f"c{ts}", "output": "ok", "is_error": False}),
            (4, "assistant_text", {"text": "Done."}),
            (5, "turn_finished", {"status": status, "duration_ms": 2000, "cost_usd": 0.01}),
        ):
            seq += 1
            conn.execute(
                "INSERT INTO agent_chat_events VALUES ('lead', ?, ?, ?, ?)",
                (seq, ts + offset, kind, json.dumps(payload)),
            )
    conn.commit()
    conn.close()
    return path


def test_weeks_of_daily_use_with_their_scores(tmp_path: Path) -> None:
    week0 = [(T0 + i * 1000, "done" if i % 2 else "error") for i in range(4)]
    week1 = [(T0 + WEEK + i * 1000, "done") for i in range(4)]
    path = _chat(tmp_path / "agent_chat.db", week0 + week1)
    found = overview.daily_use(path, now=(T0 + 2 * WEEK - 1000) / 1000)
    assert found is not None and found["turns"] == 8
    weeks = found["weeks"]
    assert [w["start_ms"] for w in weeks] == [T0, T0 + WEEK]
    assert [w["turns"] for w in weeks] == [4, 4]
    assert all(w["rated"] for w in weeks)
    assert weeks[0]["score"] == pytest.approx(0.5) and weeks[1]["score"] == pytest.approx(1.0)


def test_only_the_last_weeks_are_read(tmp_path: Path) -> None:
    old = [(T0 + i * 1000, "error") for i in range(3)]
    recent = [(T0 + 10 * WEEK + i * 1000, "done") for i in range(3)]
    path = _chat(tmp_path / "agent_chat.db", old + recent)
    found = overview.daily_use(path, now=(T0 + 10 * WEEK + 5000) / 1000)
    assert found is not None
    assert [w["start_ms"] for w in found["weeks"]] == [T0 + 10 * WEEK]
    assert found["turns"] == 3


def test_it_reads_the_record_at_most_every_ten_minutes(tmp_path: Path) -> None:
    path = _chat(tmp_path / "agent_chat.db", [(T0, "done")])
    now = (T0 + 1000) / 1000
    first = overview.daily_use(path, now=now)
    _chat(tmp_path / "other.db", [])  # unrelated; the cache is keyed by path
    sqlite3.connect(path).execute("DELETE FROM agent_chat_events").connection.commit()
    assert overview.daily_use(path, now=now + 60) is first
    assert overview.daily_use(path, now=now + 601) is None  # read again: no request left


def test_no_record_or_an_unreadable_one_shows_nothing(tmp_path: Path) -> None:
    assert overview.daily_use(None) is None
    assert overview.daily_use(tmp_path / "missing.db") is None
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a database")
    assert overview.daily_use(broken, now=T0 / 1000) is None
    assert overview.daily_use(_chat(tmp_path / "empty.db", []), now=T0 / 1000) is None
