"""Spend per Dodaios agent (``by_agent`` in the Spend & Tokens read model).

Three claims:

1. Every chat a Dodaios agent runs in (its own chat, a routine run, a direct
   message) is filed under that agent, and the assistant's own chat under the
   lead. Coding threads belong to no agent.
2. The assistant's own work outside chat (voice, missions, background jobs)
   counts for the lead; a gateway call counts for the agent it names.
3. ``by_agent`` and the ``agents`` filter answer the same question.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dodaios.costs import CostSources, build_report, collect_entries
from dodaios.costs.aggregate import filter_entries
from dodaios.costs.model import LEAD_AGENT, society_agent_of

T0 = 1_780_000_000_000

_DDL = """
CREATE TABLE agent_chat_sessions (
    session_id TEXT PRIMARY KEY, title TEXT, provider TEXT, model TEXT,
    created_ms INTEGER, updated_ms INTEGER, surface TEXT
);
CREATE TABLE agent_chat_events (
    session_id TEXT, seq INTEGER, ts_ms INTEGER, kind TEXT, payload TEXT
);
"""


def _turn(session_id: str, seq: int, cost: float) -> tuple:
    return (
        session_id, seq, T0 + seq * 1_000, "turn_finished",
        json.dumps({"status": "done", "cost_usd": cost,
                    "usage": {"input_tokens": 1_000, "output_tokens": 100}}),
    )


def _chat_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_DDL)
    sessions = [
        ("lead-chat", "jarvis"),
        ("society:scout", "society"),
        ("society:scout:routine:r1:run1", "society"),
        ("society:archivist:with:scout", "society"),
        ("code-thread", "agent"),
    ]
    conn.executemany(
        "INSERT INTO agent_chat_sessions VALUES (?,?,?,?,?,?,?)",
        [(sid, sid, "openai", "gpt-5.5", T0, T0, surface) for sid, surface in sessions],
    )
    conn.executemany(
        "INSERT INTO agent_chat_events VALUES (?,?,?,?,?)",
        [
            _turn("lead-chat", 1, 0.10),
            _turn("society:scout", 2, 0.20),
            _turn("society:scout:routine:r1:run1", 3, 0.30),
            _turn("society:archivist:with:scout", 4, 0.40),
            _turn("code-thread", 5, 5.00),
        ],
    )
    conn.commit()
    conn.close()


def test_session_ids_name_their_agent() -> None:
    assert society_agent_of("society:scout") == "scout"
    assert society_agent_of("society:scout:routine:r1:run1") == "scout"
    assert society_agent_of("society:archivist:with:scout") == "archivist"
    assert society_agent_of("chat-1") == ""


def test_chats_are_filed_under_their_agent(tmp_path: Path) -> None:
    db = tmp_path / "agent_chat.db"
    _chat_db(db)
    entries = collect_entries(CostSources(agent_chat_db=db))
    by_ref = {e.ref_id: e.agent for e in entries}
    assert by_ref == {
        "lead-chat": LEAD_AGENT,
        "society:scout": "scout",
        "society:scout:routine:r1:run1": "scout",
        "society:archivist:with:scout": "archivist",
        "code-thread": "",
    }

    report = build_report(entries, since_ms=0, until_ms=T0 * 2).to_dict()
    spend = {row["key"]: round(row["cost_usd"], 2) for row in report["by_agent"]}
    # The coding thread is not an agent's work and is left out, not lumped in.
    assert spend == {"scout": 0.5, "archivist": 0.4, LEAD_AGENT: 0.1}
    # Ranked by cost, like every other breakdown.
    assert [row["key"] for row in report["by_agent"]] == ["scout", "archivist", LEAD_AGENT]


def test_agent_filter_matches_the_breakdown(tmp_path: Path) -> None:
    db = tmp_path / "agent_chat.db"
    _chat_db(db)
    entries = collect_entries(CostSources(agent_chat_db=db))
    only_scout = filter_entries(entries, agents={"scout"})
    assert {e.ref_id for e in only_scout} == {"society:scout", "society:scout:routine:r1:run1"}
    assert round(sum(e.cost_usd for e in only_scout), 2) == 0.5


def test_a_store_without_the_surface_column_still_reads(tmp_path: Path) -> None:
    db = tmp_path / "agent_chat.db"
    conn = sqlite3.connect(db)
    conn.executescript(_DDL.replace(", surface TEXT", ""))
    conn.execute("INSERT INTO agent_chat_sessions VALUES (?,?,?,?,?,?)",
                 ("society:scout", "Scout", "openai", "gpt-5.5", T0, T0))
    conn.execute("INSERT INTO agent_chat_events VALUES (?,?,?,?,?)", _turn("society:scout", 1, 0.2))
    conn.commit()
    conn.close()
    [entry] = collect_entries(CostSources(agent_chat_db=db))
    assert entry.agent == "scout"


def test_background_jobs_are_the_lead_and_gateway_calls_their_agent(tmp_path: Path) -> None:
    from dodaios.costs import ledger

    usage = tmp_path / "llm_usage.db"
    ledger.set_ledger_path(usage)
    try:
        ledger.record_usage(provider="openai", model="gpt-5.5", tokens_in=500,
                            tokens_out=10, caller="dictation", ts_ms=T0)
        with ledger.usage_context("agent-runtime", label=f"{ledger.AGENT_LABEL_PREFIX}scout"):
            ledger.record_usage(provider="openai", model="gpt-5.5", tokens_in=700,
                                tokens_out=10, ts_ms=T0 + 1)
        ledger.flush()
    finally:
        ledger.set_ledger_path(None)

    entries = collect_entries(CostSources(ledger_db=usage))
    assert sorted((e.surface, e.agent) for e in entries) == [
        ("agent-chat", "scout"),
        ("background", LEAD_AGENT),
    ]
    runtime = next(e for e in entries if e.agent == "scout")
    # The row reads as agent work, not as the raw ``agent:<id>`` tag.
    assert runtime.label == "Hermes / OpenClaw agent"
