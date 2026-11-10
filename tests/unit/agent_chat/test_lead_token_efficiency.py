"""Lead token efficiency: background compaction, hot-path I/O and the re-read measurement."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import lead_compaction, token_efficiency
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.proactive_checks import NOTHING, skip_reason
from dodaios.agent_chat.proactive_settings import ProactiveSettings
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.agent_chat.surface_kits import kit_for
from dodaios.core.protocols import BrainDelta
from dodaios.costs.aggregate import build_report
from dodaios.costs.model import CostEntry, share_in_tokens
from dodaios.society import conversation
from dodaios.society.conversation import ConversationArchive, prepare_history

TURNS = 2000


def _msg(seq: int, text: str, kind: str = "user_message") -> dict:
    return {"seq": seq, "kind": kind, "payload": {"text": text}}


class _Summarizer:
    context_window = 4096

    def __init__(self) -> None:
        self.calls: list = []

    async def complete(self, request):
        self.calls.append(request)
        yield BrainDelta(content="Summary of the earlier conversation. Source seq 1.")


@pytest.fixture
def archive(tmp_path):
    arc = ConversationArchive(tmp_path / "conv.db")
    yield arc
    arc.close()


def _long_events(n: int) -> list[dict]:
    return [
        _msg(
            i, f"exchange {i} " + "detail " * 60, "assistant_text" if i % 2 == 0 else "user_message"
        )
        for i in range(1, n + 1)
    ]


# --- incremental ingest ----------------------------------------------------


def test_incremental_ingest_only_reads_new_events(archive, monkeypatch):
    events = _long_events(300)
    archive.ingest("s", events, incremental=True)
    seen: list[int] = []
    real = conversation.event_text

    def counting(event):
        seen.append(event["seq"])
        return real(event)

    monkeypatch.setattr(conversation, "event_text", counting)
    archive.ingest("s", _long_events(310), incremental=True)
    assert seen == list(range(301, 311))
    assert len(archive.read("s", after_seq=299, limit=50)) == 11


def test_incremental_ingest_primes_from_the_database(archive, tmp_path):
    archive.ingest("s", _long_events(20))
    fresh = ConversationArchive(tmp_path / "conv.db")
    try:
        fresh.ingest("s", _long_events(25), incremental=True)
        stored = [e["seq"] for e in fresh.read("s", after_seq=19, limit=50)]
        assert stored == [20, 21, 22, 23, 24, 25]
    finally:
        fresh.close()


# --- background compaction ---------------------------------------------------


async def test_background_pass_saves_the_checkpoint_and_the_turn_needs_no_model(archive):
    runtime = SimpleNamespace(conversations=archive)
    session = SimpleNamespace(session_id="lead", surface="society")
    events = _long_events(120)
    seat = _Summarizer()
    # Below the background share of the budget: nothing to do, no model call.
    await prepare_history(
        runtime, session, events[:3], "", seat, compact_at=0.75, compact_only=True
    )
    assert seat.calls == [] and archive.checkpoint("lead") == (0, "")
    # Past it: the pass summarizes and saves, and returns no history.
    out = await prepare_history(
        runtime, session, events, "", seat, window=4096, compact_at=0.75, compact_only=True
    )
    assert out == [] and seat.calls
    through, summary = archive.checkpoint("lead")
    assert through > 1 and summary
    # The next turn reads the checkpoint: zero summary calls on the hot path.
    turn_seat = _Summarizer()
    history = await prepare_history(runtime, session, events, "what now", turn_seat, window=4096)
    assert turn_seat.calls == []
    assert "Summary of the earlier conversation" in str(history[0].content)


def test_key_only_seat_never_compacts_in_the_background(monkeypatch):
    from dodaios.brain import background_policy

    monkeypatch.setattr(background_policy, "keyless_local", lambda _p: False)
    monkeypatch.setattr(background_policy, "subscription_mode", lambda _c=(): False)
    session = SimpleNamespace(provider="openai", model="", session_id="lead")
    assert lead_compaction._pick_seat(session, object(), object()) is None


def test_local_seat_compacts_on_itself(monkeypatch):
    from dodaios.brain import background_policy

    monkeypatch.setattr(background_policy, "keyless_local", lambda _p: True)
    own = object()
    brain = SimpleNamespace(_get_brain=lambda *_a, **_k: own)
    session = SimpleNamespace(provider="ollama", model="m", session_id="lead")
    assert lead_compaction._pick_seat(session, brain, object()) is own


async def test_schedule_after_turn_ignores_other_surfaces(monkeypatch):
    started: list[str] = []

    async def fake_run(_svc, sid):
        started.append(sid)

    monkeypatch.setattr(lead_compaction, "_run", fake_run)
    lead_compaction.schedule_after_turn(object(), SimpleNamespace(surface="agent", session_id="a"))
    lead_compaction.schedule_after_turn(object(), SimpleNamespace(surface="jarvis", session_id="j"))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert started == ["j"]


# --- measurement ---------------------------------------------------------------


def test_context_split_in_tokens_when_usage_is_known():
    turn = [_msg(10, "x" * 400), _msg(11, "y" * 40, "assistant_text")]
    usage = {"input_tokens": 100, "cache_read_input_tokens": 9000, "output_tokens": 30}
    split = token_efficiency.context_split(usage, history_chars=1, turn_events=turn)
    assert split["unit"] == "tokens"
    assert split["fresh"] == 100 + 30  # the 400 new input chars, plus the output
    assert split["reread"] == 9100 - 100
    assert 0.98 < split["reread_share"] < 1


def test_context_split_falls_back_to_characters():
    turn = [_msg(10, "x" * 100), _msg(11, "y" * 100, "assistant_text")]
    split = token_efficiency.context_split({}, history_chars=800, turn_events=turn)
    assert split == {"reread": 800, "fresh": 200, "unit": "chars", "reread_share": 0.8}
    assert token_efficiency.context_split({}, history_chars=0, turn_events=[])["reread_share"] == 0


def test_share_in_tokens_normalises_characters():
    assert share_in_tokens({"reread": 800, "fresh": 200, "unit": "chars"}) == (200, 50)
    assert share_in_tokens({"reread": 8, "fresh": 2, "unit": "tokens"}) == (8, 2)
    assert share_in_tokens("junk") == (0, 0)


def test_costs_report_carries_reread_share_per_agent():
    def entry(agent, reread, fresh):
        return CostEntry(
            ts_ms=1,
            surface="agent-chat",
            role="agent",
            provider="p",
            model="m",
            tokens_in=1,
            tokens_out=1,
            tokens_cached=0,
            cost_usd=0.0,
            price_source="free",
            ref_id="r",
            label="",
            agent=agent,
            reread_tokens=reread,
            fresh_tokens=fresh,
        )

    report = build_report(
        [entry("jarvis", 90, 10), entry("jarvis", 90, 10), entry("mailbox", 0, 0)],
        since_ms=0,
        until_ms=10,
    ).to_dict()
    rows = {row["key"]: row for row in report["by_agent"]}
    assert rows["jarvis"]["reread_share"] == 0.9 and rows["jarvis"]["reread_tokens"] == 180
    assert rows["mailbox"]["reread_share"] == 0.0


# --- routine wakes that find nothing ---------------------------------------


def test_check_without_signals_needs_no_model_call():
    quiet = {"due_loops": 0, "due_deadlines": 0, "waiting_agents": 0, "agent_turns_since": 0}
    settings = ProactiveSettings(level="important")
    assert skip_reason(settings, external_sources=0, **quiet)
    assert not skip_reason(settings, external_sources=2, **quiet)
    assert not skip_reason(settings, external_sources=None, **quiet)
    assert not skip_reason(settings, external_sources=0, **{**quiet, "due_loops": 1})
    assert not skip_reason(settings, external_sources=0, **{**quiet, "waiting_agents": 1})
    assert not skip_reason(settings, external_sources=0, **{**quiet, "agent_turns_since": 3})
    assert not skip_reason(settings, external_sources=0, **{**quiet, "due_deadlines": 1})
    only_mail = ProactiveSettings(level="important", topics=("mail",))
    assert not skip_reason(only_mail, external_sources=1, **quiet)
    assert skip_reason(only_mail, external_sources=0, **{**quiet, "agent_turns_since": 9})
    assert NOTHING


# --- the 2,000-turn lead conversation ------------------------------------------


async def test_long_lead_conversation_send_reads_only_the_tail(tmp_path, monkeypatch):
    from dodaios.agent_chat import runner_api

    monkeypatch.setitem(runner_api.BRAIN_BY_PROVIDER, "fakeprov", ("none", "None"))
    store = AgentChatStore(":memory:")
    svc = AgentChatService(store)
    session = svc.create_session(provider="fakeprov", cwd=str(tmp_path), surface="jarvis")
    sid = session.session_id
    for turn in range(TURNS):
        store.append_event(
            sid, {"kind": "user_message", "payload": {"text": f"question {turn} " + "q" * 80}}
        )
        store.append_event(
            sid, {"kind": "assistant_text", "payload": {"text": f"answer {turn} " + "a" * 160}}
        )
    total = len(store.list_events(sid))
    assert total == 2 * TURNS
    through = total - 40  # the checkpoint sits just before the newest 20 turns
    archive = ConversationArchive(tmp_path / "conv.db")
    archive.ingest(sid, store.list_events(sid, after_seq=0))
    archive.save_checkpoint(sid, through, "Everything up to here, summarized.")
    runtime = SimpleNamespace(
        conversations=archive, browser=SimpleNamespace(live=SimpleNamespace(sessions={}))
    )
    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: runtime)
    monkeypatch.setattr("dodaios.agent_chat.service.session_runner", lambda _s: "brain")
    assert kit_for("jarvis").history_start(session) == through

    reads: list[int] = []
    real = store.list_events

    def spy(session_id, *, after_seq=0, tail=None):
        reads.append(after_seq)
        return real(session_id, after_seq=after_seq, tail=tail)

    monkeypatch.setattr(store, "list_events", spy)
    handed: list = []

    async def runner(handle, _text):
        handed.append(handle.history)
        await handle.emit(
            make_event(
                "turn_finished",
                {"turn_id": handle.turn_id, "status": "done", "duration_ms": 1, "usage": {}},
            )
        )

    started = time.perf_counter()
    await svc.send(sid, "next question", control_runner=runner)
    await svc.wait_turn(sid)
    first_event_s = time.perf_counter() - started

    assert handed and len(handed[0]) == 40, "the turn is handed the tail past the checkpoint"
    assert 0 not in reads, "no read of the whole conversation"
    assert first_event_s < 1.0, f"hot path took {first_event_s:.3f}s"

    # The next brain turn ingests only the new events and needs no summary call.
    seat = _Summarizer()
    await prepare_history(runtime, session, handed[0], "next question", seat, window=200_000)
    assert seat.calls == []
    finished = [e for e in real(sid) if e["kind"] == "turn_finished"][-1]
    context = finished["payload"]["context"]
    assert context["unit"] == "chars" and context["reread"] > context["fresh"] > 0
    assert 0 < context["reread_share"] < 1
    archive.close()
