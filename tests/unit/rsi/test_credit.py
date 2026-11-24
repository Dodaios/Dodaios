"""A learned note's track in the person's requests: shown or not, and how those went.

``docs/self-improvement.md``, "A note's track in your requests". Observation
only: counts from the recorded lead turns and the chat record, a share only
from the minimum on, read at most every ten minutes, nothing for a forgotten note.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi import adopt, credit, lead_turns, overview
from dodaios.rsi import night as nights
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.lead_turns import LeadTurn
from dodaios.self_change import SelfChangeRegistry

HOUR = 3600 * 1000
MINUTE = 60 * 1000
NOTE = "The calendar tool needs the date as 2026-03-14, not as 14 March."
OTHER = "The mail search works with from: and not with sender: in the query."
#: Ten days ago: inside the record's 90 days, and every request old enough to know.
T0 = int(time.time() * 1000) - 10 * 24 * HOUR


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(credit, "_cache", {})
    monkeypatch.setattr(credit, "_scanned", {})
    yield
    for found in list(lead_turns._OPEN.values()):  # noqa: SLF001
        found.close()
    lead_turns._OPEN.clear()  # noqa: SLF001


@dataclass
class Req:
    """One request of the person's, as both records hold it."""

    #: Note texts the lead was given, as list lines of the always-on block.
    shows: tuple[str, ...] = ()
    status: str = "done"
    #: The person's next message, five minutes later (else the next request comes an hour later).
    then: str = ""
    undo_call: bool = False
    continuation: bool = False
    #: The note came up in the recall for the message (with its date after it).
    recalled: bool = False
    #: The system prompt and message as recorded, instead of the built ones.
    system: str | None = None
    message: str = "hello"


def _system(req: Req) -> str:
    if req.system is not None:
        return req.system
    lines = [f"- {text}" for text in req.shows]
    if req.recalled:
        lines = [f"{line} (since 2026-11-20)" for line in lines]
    return "You are the lead.\n\n## Memory\n" + "\n".join(lines)


def _records(
    folder: Path, reqs: list[Req], *, start: int = T0, first: int = 0
) -> tuple[Path, Path]:
    """``lead_turns.db`` and ``agent_chat.db`` side by side, one lead session.

    Each request is worded with words of its own, so none reads as the one
    before asked again; a ``then`` message is the person's next request.
    ``first`` numbers the requests on from an earlier call on the same folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    chat = folder / "agent_chat.db"
    conn = sqlite3.connect(chat)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS agent_chat_sessions (session_id TEXT PRIMARY KEY,"
        " surface TEXT);"
        "CREATE TABLE IF NOT EXISTS agent_chat_events (session_id TEXT, seq INTEGER,"
        " ts_ms INTEGER, kind TEXT, payload TEXT, PRIMARY KEY (session_id, seq));"
        "INSERT OR IGNORE INTO agent_chat_sessions VALUES ('lead', 'jarvis');"
    )
    store = lead_turns.store(folder / lead_turns.DB_NAME)
    seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM agent_chat_events").fetchone()[0])
    ts = start

    def event(at: int, kind: str, payload: dict) -> None:
        nonlocal seq
        seq += 1
        conn.execute(
            "INSERT INTO agent_chat_events VALUES ('lead', ?, ?, ?, ?)",
            (seq, at, kind, json.dumps(payload)),
        )

    for index, req in enumerate(reqs, start=first):
        turn = f"t{index}"
        event(ts, "user_message", {"text": f"request{index} alpha{index} beta{index}"})
        event(ts + 1, "turn_started", {"turn_id": turn})
        if req.undo_call:
            event(ts + 2, "tool_call", {"call_id": "c", "name": "x", "input": {"undo_of": "y"}})
        event(ts + 3, "turn_finished", {"status": req.status})
        store.append(
            LeadTurn(
                session_id="lead",
                turn_id=turn,
                cli="claude-cli",
                model="m",
                effort="high",
                system=_system(req),
                message=req.message,
                tools_digest="t",
                first_kind="text",
                continuation=req.continuation,
                ts_ms=ts + 1,
            )
        )
        if req.then:
            ts += 5 * MINUTE
            event(ts, "user_message", {"text": req.then})
        ts += HOUR
    conn.commit()
    conn.close()
    return folder / lead_turns.DB_NAME, chat


def _note(text: str = NOTE, change_id: str = "c1", since_ms: int = T0 - 1) -> credit.Note:
    return credit.Note(change_id, text, since_ms)


# ------------------------------------------------------------------ shown


def test_a_note_is_shown_where_its_line_is_in_what_the_lead_got() -> None:
    assert credit.shown_in(NOTE, f"intro\n- {NOTE}\nmore", "")
    assert credit.shown_in(NOTE, "", f"the message\n\n## Recalled\n- {NOTE} (since 2026-11-20)")
    assert credit.shown_in(NOTE, f"- {NOTE}", "") and credit.shown_in(NOTE, "", f"- {NOTE}")
    # Not the note's exact line: reworded, cut short, inside other words, or not a list line.
    assert not credit.shown_in(NOTE, f"- {NOTE[:-1]}", "")
    assert not credit.shown_in(NOTE, f"- {NOTE} And more.", "")
    assert not credit.shown_in(NOTE, f"He said: {NOTE}", "")
    assert not credit.shown_in(NOTE, NOTE, "")


def test_it_matches_what_the_memory_blocks_really_render(tmp_path: Path, monkeypatch) -> None:
    vault = MemoryVault(tmp_path / "vault.db")
    try:
        vault.remember(
            "The calendar   tool needs the date as 2026-03-14,\nnot as 14 March.",
            "procedural",
            origin="inferred",
            valid_from="2026-11-20T09:00:00+00:00",
            source={"note": "how_to", "trigger": "calendar date format"},
        )
        (memory,) = [m for m in vault.list() if m.kind == "procedural"]
        # In the always-on block, as a line of its own.
        always_on = vault_runtime.prompt_block(vault=vault)
        assert credit.shown_in(memory.text, f"identity\n\n{always_on}\n\nmore", "")
        # Recalled for the message (the always-on block has no room for it): its date follows.
        monkeypatch.setitem(vault_runtime._budgets, "full", 0)  # noqa: SLF001
        query = "which date format does the calendar tool need"
        recalled = vault_runtime.turn_block(query, vault=vault)
        assert "(since 2026-11-20)" in recalled
        assert credit.shown_in(memory.text, "identity", f"message\n\n{recalled}")
        assert not credit.shown_in(memory.text, "identity without memory", "message")
    finally:
        vault.close()


def test_shown_and_not_shown_are_counted_from_the_recorded_prompts(tmp_path: Path) -> None:
    reqs = (
        [Req(shows=(NOTE,))] * 3
        + [Req(shows=(NOTE,), recalled=True)] * 2
        + [Req(system="no memory here", message=f"hi\n\n- {NOTE}")]  # in the message
        + [Req(shows=(OTHER,))] * 4
        + [Req()] * 2
    )
    lead, chat = _records(tmp_path, reqs)
    notes = [_note(NOTE, "c1"), _note(OTHER, "c2")]
    found = credit.track(notes, lead, chat)
    assert (found["c1"]["shown"], found["c1"]["other"]) == (6, 6)
    assert (found["c2"]["shown"], found["c2"]["other"]) == (4, 8)
    assert found["c1"]["since_ms"] == T0 + 1  # the oldest record, later than the note


def test_only_requests_since_the_note_came_into_effect_count(tmp_path: Path) -> None:
    lead, chat = _records(tmp_path, [Req(shows=(NOTE,))] * 4 + [Req()] * 4)
    found = credit.track([_note(since_ms=T0 + 2 * HOUR)], lead, chat)["c1"]
    assert (found["shown"], found["other"], found["since_ms"]) == (2, 4, T0 + 2 * HOUR)


# ------------------------------------------------------------------ how it went


def test_how_a_request_went_comes_from_what_the_person_did_next(tmp_path: Path) -> None:
    reqs = [
        Req(),  # went through: done, and the next request is a new one an hour later
        Req(then="no, that is wrong"),  # corrected
        Req(),
        Req(then="request3 alpha3 beta3"),  # the same asked again
        Req(then="please undo that"),  # undone
        Req(undo_call=True),  # an undo call in the turn
        Req(status="error"),
        Req(status="cancelled"),
        Req(continuation=True),  # carried a running task on: no request of the person's
        Req(),
    ]
    lead, chat = _records(tmp_path, reqs)
    from dodaios.evals.agent_score.turns import read_lead_turns

    went = credit.outcomes(read_lead_turns(chat), now_ms=int(time.time() * 1000))
    assert went[("lead", "t0")] is True and went[("lead", "t2")] is True
    for index in (1, 3, 4, 5, 6, 7):
        assert went[("lead", f"t{index}")] is False, index
    # Each follow-up message is a request of its own; the last one is still open.
    assert went[("lead", "t9")] is True


def test_a_request_too_new_to_know_is_not_counted(tmp_path: Path) -> None:
    now_ms = int(time.time() * 1000)
    lead, chat = _records(tmp_path, [Req(shows=(NOTE,))] * 2, start=now_ms - HOUR - 10 * MINUTE)
    found = credit.track([_note(since_ms=now_ms - 2 * HOUR)], lead, chat, now=now_ms / 1000)
    assert found["c1"]["shown"] == 1  # the second came ten minutes ago


def test_a_share_is_given_only_from_the_minimum_on(tmp_path: Path) -> None:
    low = credit.MIN_REQUESTS - 1
    reqs = [Req(shows=(NOTE,), status="error" if i < 3 else "done") for i in range(low)]
    reqs += [Req(status="error" if i < 6 else "done") for i in range(credit.MIN_REQUESTS + 10)]
    lead, chat = _records(tmp_path / "few", reqs)
    found = credit.track([_note()], lead, chat)["c1"]
    assert found["min_requests"] == credit.MIN_REQUESTS == 30
    assert found["shown"] == low and found["shown_share"] is None
    assert found["shown_through"] is None  # a count of 26 of 29 would be a share too
    assert found["other"] == 40 and found["other_through"] == 34
    assert found["other_share"] == pytest.approx(34 / 40)

    reqs = [Req(shows=(NOTE,), status="error" if i < 3 else "done") for i in range(30)]
    lead, chat = _records(tmp_path / "enough", reqs)
    found = credit.track([_note()], lead, chat)["c1"]
    assert (found["shown"], found["shown_through"]) == (30, 27)
    assert found["shown_share"] == pytest.approx(0.9)
    assert (found["other"], found["other_share"], found["other_through"]) == (0, None, None)


# ------------------------------------------------------------------ cache and privacy


def test_it_reads_the_records_at_most_every_ten_minutes(tmp_path: Path, monkeypatch) -> None:
    lead, chat = _records(tmp_path, [Req(shows=(NOTE,))] * 3)
    read: list[int] = []
    real = lead_turns.LeadTurnStore.turn

    def spy(self, seq: int):
        read.append(seq)
        return real(self, seq)

    monkeypatch.setattr(lead_turns.LeadTurnStore, "turn", spy)
    now = time.time()
    first = credit.track([_note()], lead, chat, now=now)
    assert first["c1"]["shown"] == 3 and len(read) == 3
    _records(tmp_path, [Req(shows=(NOTE,))], start=T0 + 5 * HOUR, first=3)
    assert credit.track([_note()], lead, chat, now=now + 60) is first
    # After ten minutes it reads again; a row's text is read once for the same notes.
    again = credit.track([_note()], lead, chat, now=now + credit.TTL_S + 1)
    assert again["c1"]["shown"] == 4 and len(read) == 4
    # A note that comes (or goes) is counted at once, and every row is read again for it.
    both = credit.track([_note(), _note(OTHER, "c2")], lead, chat, now=now + credit.TTL_S + 2)
    assert set(both) == {"c1", "c2"} and both["c2"]["other"] == 4 and len(read) == 8


def test_without_both_records_there_is_no_track(tmp_path: Path) -> None:
    lead, chat = _records(tmp_path, [Req(shows=(NOTE,))])
    assert credit.track([], lead, chat) == {}
    assert credit.track([_note()], None, chat) == {}
    assert credit.track([_note()], lead, tmp_path / "missing.db") == {}
    assert credit.track([_note()], tmp_path / "missing.db", chat) == {}
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "agent_chat.db").write_bytes(b"this is not a database")
    (broken / lead_turns.DB_NAME).write_bytes(b"neither is this")
    assert credit.track([_note()], broken / lead_turns.DB_NAME, broken / "agent_chat.db") == {}


# ------------------------------------------------------------------ on the page


#: When the notes of the page's tests were written: a day before the records start.
WRITTEN = datetime.fromtimestamp((T0 - 24 * HOUR) / 1000, tz=UTC).isoformat(timespec="seconds")


@pytest.fixture
def home(tmp_path: Path):
    vault = MemoryVault(tmp_path / "vault.db", clock=lambda: WRITTEN)
    for text in (NOTE, OTHER):
        vault.remember(
            text,
            "procedural",
            origin="inferred",
            source={"note": "how_to", "trigger": "calling a tool that failed before"},
        )
    registry = SelfChangeRegistry(tmp_path)
    vault_runtime.set_active(vault)
    adopt.how_tos(registry, vault)
    night = nights.Night(registry, BenchStore(tmp_path / "bench.db"), lambda: {})
    yield tmp_path, vault, night
    night.bench.close()
    vault_runtime.set_active(None)
    registry.close()


def test_the_page_gets_each_notes_track_and_none_for_a_forgotten_note(home) -> None:
    path, vault, night = home
    reqs = [Req(shows=(NOTE,))] * 2 + [Req(shows=(NOTE, OTHER))] + [Req()]
    _, chat = _records(path / "data", reqs)
    stack = overview.build(night, chat_db=chat)["stack"]
    tracks = {row["text"]: row["track"] for row in stack}
    # Counted from when the note was written, not from the night the registry took it in.
    assert all(row["since_ms"] > T0 for row in stack)
    assert tracks[NOTE]["since_ms"] == T0 + 1  # the oldest record, a day after the note
    assert tracks[NOTE]["shown"] == 3 and tracks[NOTE]["other"] == 1
    assert tracks[OTHER]["shown"] == 1 and tracks[OTHER]["other"] == 3
    assert tracks[NOTE]["shown_share"] is None  # 3 requests are too few for a share
    # Counts only: no words of the note or of the requests.
    assert NOTE not in json.dumps(tracks[NOTE]) and "alpha" not in json.dumps(tracks[NOTE])

    (gone,) = [m.id for m in vault.list() if m.text == NOTE]
    vault.forget(gone)
    rows = {row["id"]: row for row in overview.build(night, chat_db=chat)["stack"]}
    forgotten = next(row for row in rows.values() if not row["text"])
    assert forgotten["track"] is None
    assert any(row["track"] and row["track"]["shown"] == 1 for row in rows.values())


def test_without_a_chat_record_a_note_has_no_track(home) -> None:
    _, _, night = home
    assert all(row["track"] is None for row in overview.build(night)["stack"])
