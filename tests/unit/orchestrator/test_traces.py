"""The causal trace tree: span propagation, trusted provenance, assembly, rollup."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from dodaios.core.chat_turn import ChatTurn, current_chat_turn, mcp_span_ref, origin_of
from dodaios.core.protocols import ExecutionContext
from dodaios.orchestrator import jobs, traces
from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool
from dodaios.plugins.tool.job_tools import TraceExplainTool
from dodaios.society.delegation_wait import ledger_job_id
from dodaios.society.runtime import SocietyRuntime
from tests.unit.society.test_lead_card import FakeChat


@pytest.fixture(autouse=True)
def store():
    s = traces.TraceStore(":memory:")
    traces.set_store(s)
    try:
        yield s
    finally:
        traces.set_store(None)
        s.close()


@pytest.fixture
async def rt(tmp_path):
    chat = FakeChat(tmp_path / "chat.db")
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, chat_service=lambda: chat)
    await runtime.ensure_started()
    try:
        yield runtime
    finally:
        await runtime.close()


def _ctx(**config):
    return ExecutionContext(
        trace_id=uuid4(), user_utterance="x", config={"output_language": "en", **config},
        memory_read=None,
    )


def _turn(turn_id="t1", *, direct=True, parent="", origin="", session="lead-1"):
    return ChatTurn(
        session, turn_id, "do it", direct, "tr", span_id=turn_id, parent_span_id=parent,
        origin=origin,
    )


# ------------------------------------------------------------------- origin prefix


def test_origin_prefix_follows_the_real_origin() -> None:
    assert origin_of(None) == "voice"
    assert origin_of(_turn()) == "chat"
    assert origin_of(_turn(direct=False)) == "agent"
    assert origin_of(_turn(origin="routine")) == "routine"
    assert origin_of(_turn(origin="trigger")) == "trigger"
    token = current_chat_turn.set(_turn(origin="routine"))
    try:
        assert traces.trace_prefix() == "routine"
    finally:
        current_chat_turn.reset(token)
    assert traces.trace_prefix() == "voice"


async def test_delegation_trace_id_is_not_always_voice(rt) -> None:
    rt.scheduler.detach()
    await rt.roster.create(name="Scout", title="Research", description="Research")
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    token = current_chat_turn.set(_turn())
    try:
        typed = await tool.execute({"agent": "Scout", "task": "Audit the repo"}, _ctx())
    finally:
        current_chat_turn.reset(token)
    spoken = await tool.execute({"agent": "Scout", "task": "Audit the docs"}, _ctx())
    assert typed.output["trace_id"].startswith("chat:")
    assert spoken.output["trace_id"].startswith("voice:")


# ------------------------------------------------------------ propagation and trust


async def test_spans_flow_lead_turn_to_assignment_to_agent_turn_to_job(rt, store) -> None:
    rt.scheduler.detach()
    await rt.roster.create(name="Scout", title="Research", description="Research")
    lead = _turn("lead-turn")
    traces.open_turn(lead, title="audit the repo")
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    token = current_chat_turn.set(lead)
    try:
        result = await tool.execute(
            {"agent": "Scout", "task": "Audit the repo", "reply_policy": "always"}, _ctx()
        )
    finally:
        current_chat_turn.reset(token)
    assignment_id = result.output["assignment_id"]
    envelope = (await rt.store.events_for_trace(result.output["trace_id"]))[0]
    assert envelope.payload["parent_span_id"] == "lead-turn"
    assert envelope.payload["root_span_id"] == "lead-turn"

    job = jobs.get_ledger().get(ledger_job_id(envelope))
    assert (job.span_id, job.parent_span_id, job.root_span_id) == (
        assignment_id, "lead-turn", "lead-turn",
    )

    # The agent turn the assignment starts names the assignment event as its parent.
    agent = _turn("agent-turn", direct=False, parent=assignment_id, session="society:scout")
    traces.open_turn(agent, title="Audit the repo", provider="p", model="m")
    traces.close_turn(
        "agent-turn",
        {"status": "done", "cost_usd": 0.5, "usage": {"input_tokens": 10, "output_tokens": 4}},
    )
    # A mission the agent starts inside its turn hangs from the agent turn.
    token = current_chat_turn.set(agent)
    try:
        mission = jobs.start("mission", title="Build it")
    finally:
        current_chat_turn.reset(token)
    row = jobs.get_ledger().get(mission)
    assert (row.parent_span_id, row.root_span_id) == ("agent-turn", "lead-turn")
    assert traces.resolve_root(mission) == "lead-turn"
    assert traces.resolve_root("agent-turn") == "lead-turn"
    assert traces.resolve_root(assignment_id) == "lead-turn"

    tree = traces.build_tree("lead-turn")
    chain = [tree["id"]]
    node = tree
    while node["children"]:
        node = node["children"][0]
        chain.append(node["id"])
    assert chain == ["lead-turn", assignment_id, "agent-turn", mission]


async def test_a_tool_argument_cannot_forge_a_parent(rt) -> None:
    rt.scheduler.detach()
    await rt.roster.create(name="Scout", title="Research", description="Research")
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    token = current_chat_turn.set(_turn("real-turn"))
    try:
        result = await tool.execute(
            {
                "agent": "Scout", "task": "Audit", "parent_span_id": "forged",
                "span_id": "forged", "root_span_id": "forged",
            },
            _ctx(parent_span_id="forged"),
        )
    finally:
        current_chat_turn.reset(token)
    envelope = (await rt.store.events_for_trace(result.output["trace_id"]))[0]
    assert envelope.payload["parent_span_id"] == "real-turn"
    assert envelope.payload["root_span_id"] == "real-turn"


def test_the_mcp_header_names_the_span_but_a_turn_in_flight_wins() -> None:
    from dodaios.ui.web.mcp_server_routes import span_ref

    def scope(value: bytes):
        return {"headers": [(b"x-jarvis-span", value)]}

    assert span_ref(scope(b"turn-1")) == "turn-1"
    assert span_ref(scope(b"bad value; drop")) is None
    assert span_ref({"headers": []}) is None

    token = mcp_span_ref.set("from-header")
    try:
        assert traces.current_span() == "from-header"
        turn_token = current_chat_turn.set(_turn("live-turn"))
        try:
            assert traces.current_span() == "live-turn"
        finally:
            current_chat_turn.reset(turn_token)
        started = jobs.start("routine", title="via header")
        assert jobs.get_ledger().get(started).parent_span_id == "from-header"
    finally:
        mcp_span_ref.reset(token)


def test_the_harness_puts_the_turn_span_next_to_the_session_header(monkeypatch) -> None:
    from dodaios.agent_chat import dodaios_harness as h

    monkeypatch.setattr(h, "endpoint", lambda: "http://127.0.0.1:1/mcp")
    monkeypatch.setattr(h, "control_key", lambda: "k")
    token = current_chat_turn.set(_turn("turn-9", session="sess"))
    try:
        config = json.loads(h.mcp_config_json("sess"))
        headers = next(iter(config["mcpServers"].values()))["headers"]
        assert headers[h.HEADER_NAME] == "sess"
        assert headers[h.SPAN_HEADER_NAME] == "turn-9"
        other = json.loads(h.mcp_config_json("another"))
        assert h.SPAN_HEADER_NAME not in next(iter(other["mcpServers"].values()))["headers"]
    finally:
        current_chat_turn.reset(token)


# ------------------------------------------------------------- assembly and rollup


def _seed(store):
    ledger = jobs.get_ledger()
    store.open_span("root", session_id="s", title="lead asks", provider="x", model="m1")
    ledger.create(
        "society_assignment", job_id="job_a", span_id="asg", parent_span_id="root",
        root_span_id="root", target="agent-1", title="Scout: audit",
    )
    store.open_span(
        "agent", parent_span_id="asg", root_span_id="root", session_id="a", title="audit",
        provider="p", model="m2",
    )
    store.close_span("agent", status="done", cost_usd=0.25, tokens_in=100, tokens_out=40)
    ledger.create(
        "mission", job_id="job_m", span_id="job_m", parent_span_id="agent", root_span_id="root",
        title="build",
    )
    ledger.update("job_m", state="failed", error="boom", cost_usd=0.5)
    store.close_span("root", status="done", cost_usd=0.1)
    return ledger


def test_tree_assembly_timing_cost_and_rollup(store) -> None:
    _seed(store)
    tree = traces.build_tree("root")
    assert tree["node_count"] == 4
    asg = tree["children"][0]
    agent = asg["children"][0]
    mission = agent["children"][0]
    assert (asg["kind"], agent["kind"], mission["kind"]) == (
        "society_assignment", "turn", "mission",
    )
    assert agent["seat"] == {"provider": "p", "model": "m2"}
    assert agent["tokens"] == {"in": 100, "out": 40}
    assert mission["status"] == "failed" and mission["error"] == "boom"
    # Own cost plus children: the assignment job adds nothing of its own.
    assert agent["cost_total_usd"] == pytest.approx(0.75)
    assert tree["cost_total_usd"] == pytest.approx(0.85)
    assert tree["tokens_total"] == 140
    assert tree["span_ms"] >= 0 and mission["duration_ms"] is not None
    assert tree["critical_path"][0] == "root"
    public = traces.public(tree)
    assert "_end_ms" not in public and "_live" not in public


def test_an_orphan_hangs_from_the_root_and_an_unknown_anchor_gets_a_stub(store) -> None:
    ledger = jobs.get_ledger()
    ledger.create("mission", job_id="j1", span_id="j1", parent_span_id="gone", root_span_id="gone")
    tree = traces.build_tree("gone")
    assert tree["kind"] == "unknown" and [c["id"] for c in tree["children"]] == ["j1"]
    assert traces.build_tree("nothing-here") is None


def test_the_tree_is_bounded(store) -> None:
    store.open_span("big")
    for i in range(30):
        store.open_span(f"c{i}", parent_span_id="big", root_span_id="big")
    tree = traces.build_tree("big", max_nodes=10)
    assert tree["truncated"] is True and tree["node_count"] == 10


def test_listing_roots_per_session(store) -> None:
    _seed(store)
    roots = traces.list_roots("s")
    assert [r["root"] for r in roots] == ["root"] and roots[0]["nodes"] == 3


def test_a_running_span_from_an_earlier_boot_reads_as_interrupted(store) -> None:
    store.open_span("old", session_id="s")
    store._conn.execute("UPDATE spans SET boot_id = 'older'")  # noqa: SLF001
    assert traces.build_tree("old")["status"] == "interrupted"


async def test_trace_explain_reads_the_tree_without_a_model(store) -> None:
    _seed(store)
    tool = TraceExplainTool()
    result = await tool.execute({"job_id": "job_m"}, _ctx())
    assert result.success and result.output["root"] == "root"
    summary = result.output["summary"]
    assert "Trace root" in summary and "failed" in summary and "boom" in summary
    assert "Costliest" in summary and "Longest chain" in summary
    by_turn = await tool.execute({"id": "agent"}, _ctx())
    assert by_turn.success and "Asked about agent" in by_turn.output["summary"]
    assert not (await tool.execute({"id": "nope"}, _ctx())).success
    assert not (await tool.execute({}, _ctx())).success


def test_the_http_routes_return_the_tree_and_the_roots(store) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web.traces_routes import router

    _seed(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/api/traces/job_m").json()
    assert body["root"] == "root" and body["tree"]["children"][0]["id"] == "asg"
    assert client.get("/api/traces/nothing").status_code == 404
    listed = client.get("/api/traces", params={"session": "s"}).json()
    assert listed["roots"][0]["root"] == "root"
    assert client.get("/api/traces").status_code == 400


def test_close_turn_maps_a_turn_finished_payload(store) -> None:
    traces.open_turn(_turn("t9"), title="hello", provider="p", model="m")
    traces.close_turn(
        "t9", {"status": "error", "error": "no seat", "usage": {}, "cost_usd": 0.01}
    )
    row = store.get("t9")
    assert (row["status"], row["error"], row["cost_usd"]) == ("error", "no seat", 0.01)
    assert row["ended_ms"] is not None
