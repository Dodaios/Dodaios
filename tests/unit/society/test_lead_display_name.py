"""The lead is shown, spoken and sent under the name the user gave the assistant.

The roster row keeps its seeded name (id, session and workspace derive from
it); ``dodaios.society.display_name`` is the one read-time override. These tests
walk the surfaces that put an agent's name in front of a person or a model.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import typeahead
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME
from dodaios.mcp.agents import tools as mcp_tools
from dodaios.mcp.agents.context import EcosystemUnavailable, resolve_agent
from dodaios.society.agent_names import lookup_agent, lookup_in, resolve_shown
from dodaios.society.agent_tools import MessageAgentTool
from dodaios.society.chat_binding import frame_assignment, make_deliver_hook
from dodaios.society.display_name import (
    display_name,
    display_row,
    lead_display_name,
    names_the_lead,
)
from dodaios.society.events import MsgType, SocietyEnvelope
from dodaios.society.lead_card import render_lead_card
from dodaios.society.routines import _routine_prompt
from dodaios.society.runtime import SocietyRuntime, _agent_frame
from dodaios.society.surface import build_briefing, society_system_extra
from dodaios.ui.web.society_routes import router
from tests.fakes.meeting_chat import MeetingChatFake

STORED = "Jarvis"
CTX = SimpleNamespace(trace_id=uuid4(), user_utterance="", config={})
FRONTEND = Path(__file__).resolve().parents[3] / "dodaios/ui/web/frontend/src/lib"


class Chat:
    """The agent-chat seam the society delivers into, without a model behind it."""

    receive_message = AgentChatService.receive_message
    message_status = AgentChatService.message_status

    def __init__(self, store: AgentChatStore) -> None:
        self.store = store
        self.sent: list[tuple[str, str]] = []

    async def _emit(self, session_id, event):
        self.store.append_event(session_id, event)

    def is_running(self, _session_id: str) -> bool:
        return False

    def running_session_ids(self) -> list[str]:
        return []

    def pending_approvals(self, _session_id: str) -> list[str]:
        return []

    def subscribe(self, _session_id: str) -> asyncio.Queue:
        return asyncio.Queue()

    def unsubscribe(self, _session_id: str, _queue: asyncio.Queue) -> None:
        return None

    async def send(self, session_id: str, text: str, attachments=None, *, incoming=None) -> str:
        self.sent.append((session_id, text))
        return "turn-1"


def _config(tmp_path: Path, phrase: str) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(data_dir=str(tmp_path / "data")),
        trigger=SimpleNamespace(wake_word=SimpleNamespace(phrase=phrase)),
    )


@pytest.fixture
async def world(tmp_path: Path):
    cfg = _config(tmp_path, "Hey Athena")
    svc = Chat(AgentChatStore(tmp_path / "agent_chat.db"))
    rt = SocietyRuntime(
        tmp_path, seed_starter_team=False, cfg=lambda: cfg, chat_service=lambda: svc
    )
    await rt.ensure_started()
    await rt.roster.create(name="Scout", title="Research", provider="openai")
    try:
        yield rt, svc, cfg
    finally:
        await rt.close()
        svc.store.close()


async def _stored_rows(rt: SocietyRuntime) -> bytes:
    cur = await rt.store.conn.execute("SELECT * FROM society_agents ORDER BY agent_id")
    rows = await cur.fetchall()
    await cur.close()
    return repr([tuple(row) for row in rows]).encode()


async def test_only_the_lead_wears_the_wake_word_name(world):
    rt, _, cfg = world
    lead, scout = await rt.roster.get("jarvis"), await rt.roster.get("scout")
    assert lead.name == STORED
    assert display_name(lead, cfg) == display_name(lead) == rt.display_name(lead) == "Athena"
    assert display_row(lead, cfg) == {**lead.to_dict(), "name": "Athena"}
    # A teammate keeps its stored name, even when the wake word says the same.
    assert display_row(scout, cfg) == scout.to_dict()
    cfg.trigger.wake_word.phrase = "Hey Scout"
    assert display_name(scout, cfg) == "Scout" and scout.to_dict()["name"] == "Scout"


async def test_without_a_wake_word_the_lead_has_the_neutral_name(world):
    rt, _, cfg = world
    lead = await rt.roster.get("jarvis")
    cfg.trigger.wake_word.phrase = ""
    assert display_name(lead, cfg) == display_name(lead) == DEFAULT_ASSISTANT_NAME
    # No config at all (a bare runtime, a headless route) is the same answer.
    assert display_name(lead, None) == lead_display_name(None) == DEFAULT_ASSISTANT_NAME
    assert DEFAULT_ASSISTANT_NAME != STORED


def test_the_neutral_name_is_the_frontend_default():
    cache = (FRONTEND / "assistantNameCache.ts").read_text(encoding="utf-8")
    neutral = re.search(r'export const NEUTRAL_ASSISTANT_NAME = "([^"]+)";', cache)
    assert neutral is not None and neutral.group(1) == DEFAULT_ASSISTANT_NAME
    # The frontend twin falls back to that name for the lead, as display_name does.
    twin = (FRONTEND / "societyDisplayName.ts").read_text(encoding="utf-8")
    assert re.search(
        r'if \(agent\.tier === "lead"\) \{\s*const trimmed = \(assistantName \|\| ""\)\.trim\(\);'
        r"\s*return trimmed \|\| NEUTRAL_ASSISTANT_NAME;\s*\}\s*return agent\.name;",
        twin,
    )


async def test_a_changed_wake_word_shows_on_the_next_read_without_a_write(world):
    rt, svc, cfg = world
    before = await _stored_rows(rt)
    scout = await rt.roster.get("scout")
    deliver = make_deliver_hook(lambda: svc, lambda: cfg)
    for phrase, shown in (("Hey Athena", "Athena"), ("george", "George"), ("", "Assistant")):
        cfg.trigger.wake_word.phrase = phrase
        roster = await rt.roster.list()
        assert f"- {shown} — Lead (lead)" in build_briefing(scout, [], roster, config=cfg)
        assert (await lookup_agent(rt, shown)).agent.agent_id == "jarvis"
        assert [s.label for s in typeahead.teammates("scout")] == [shown]
        env = SocietyEnvelope(
            msg_type=MsgType.SAY,
            from_agent="jarvis",
            to_agent="scout",
            trace_id="t",
            payload={"text": "Hi"},
        )
        await deliver(scout, env)
        assert svc.sent[-1][1].startswith(f"[say from {shown}]\n")
    assert await _stored_rows(rt) == before
    assert (await rt.roster.get("jarvis")).name == STORED


async def test_the_seat_prompt_never_names_the_stored_lead(world):
    rt, _, cfg = world
    scout = await rt.roster.get("scout")
    briefing = await society_system_extra(cfg, None, SimpleNamespace(session_id="society:scout"))
    assert "## Teammates\n- Athena — Lead (lead)" in briefing
    assert "ask Athena or an orchestrator" in briefing
    assert STORED not in briefing
    # The lead's own seat (a meeting turn) reads its displayed name too.
    lead = await rt.roster.get("jarvis")
    own = build_briefing(lead, [], await rt.roster.list(), config=cfg)
    assert own.startswith("## You are Athena — Lead") and STORED not in own
    for prompt in (_agent_frame(scout, "Find it.", cfg), _routine_prompt(scout, "Check mail.")):
        assert STORED not in prompt
    assert "led by Athena." in _agent_frame(scout, "Find it.", cfg)


def test_the_lead_card_defaults_to_the_neutral_name():
    assert render_lead_card([], []) == ""  # nothing to lead, no card
    card = render_lead_card([], [], terminals=["T1"])
    assert f"You are {DEFAULT_ASSISTANT_NAME}, the lead" in card and STORED not in card


async def test_a_message_from_the_lead_is_framed_and_recorded_under_its_shown_name(world):
    rt, svc, cfg = world
    scout = await rt.roster.get("scout")
    env = SocietyEnvelope(
        msg_type=MsgType.SAY,
        from_agent="jarvis",
        to_agent="scout",
        trace_id="t",
        payload={"text": "Hello"},
    )
    await make_deliver_hook(lambda: svc, lambda: cfg)(scout, env)
    session_id, prompt = svc.sent[0]
    assert session_id == "society:scout"
    assert prompt.startswith("[say from Athena]\nHello\n")
    # The id the reply is routed by is untouched.
    assert f"Message id: {env.event_id}; sender id: jarvis" in prompt
    receipt = next(
        e["payload"] for e in svc.store.list_events(session_id) if e["kind"] == "agent_message"
    )
    assert receipt["sender_name"] == "Athena" and receipt["sender_id"] == "jarvis"


def test_an_assignment_keeps_the_sender_id_and_adds_the_shown_name():
    env = SocietyEnvelope(
        msg_type=MsgType.ASSIGN,
        from_agent="jarvis",
        to_agent="scout",
        trace_id="t",
        payload={"text": "Find the note."},
    )
    framed = frame_assignment(env, "Athena")
    # The chat reads the id back from the header to draw the delegation card.
    assert framed.splitlines()[:2] == ["[assignment from jarvis]", "Find the note."]
    ids = f"Message id: {env.event_id}; sender id: jarvis"
    assert f"{ids}; sender name: Athena" in framed.splitlines()
    for same in ("", "jarvis"):
        assert ids in frame_assignment(env, same).splitlines()


async def test_the_lead_resolves_by_its_stored_and_by_its_shown_name(world):
    rt, _, _ = world
    for ref in ("Athena", "athena", " ATHENA ", STORED, "jarvis"):
        found = await lookup_agent(rt, ref)
        assert found.agent is not None and found.agent.agent_id == "jarvis", ref
        assert (await resolve_shown(rt, ref)).agent_id == "jarvis"
        assert (await resolve_agent(rt, ref)).agent_id == "jarvis"
    assert (await lookup_agent(rt, "Athena")).match_info() is None  # exact, nothing to explain
    assert (await lookup_agent(rt, "Scout")).agent.agent_id == "scout"
    assert await resolve_shown(rt, "Nobody") is None
    with pytest.raises(EcosystemUnavailable) as unknown:
        await resolve_agent(rt, "Nobody")
    assert "Athena, Scout" in str(unknown.value) and STORED not in str(unknown.value)


async def test_a_teammate_reaches_the_lead_by_the_name_it_reads(world):
    rt, _, _ = world
    tool = MessageAgentTool(rt, "scout")
    result = await tool.execute({"target": "Athena", "text": "The report is ready."}, CTX)
    assert result.success, result.error
    assert result.output["target"] == "Athena"
    sent = await rt.store.get_event(result.output["message_id"])
    assert sent.from_agent == "scout" and sent.to_agent == "jarvis"
    # A near miss is matched against the shown name as well.
    close = await lookup_agent(rt, "Atena", include_lead=True)
    assert close.agent is not None and close.agent.agent_id == "jarvis"
    assert close.match_info()["matched"] == "Athena"
    missed = await tool.execute({"target": "Nobody", "text": "Hello?"}, CTX)
    assert missed.output["available"] == ["Athena", "Scout"]


async def test_a_teammate_named_like_the_wake_word_keeps_its_name(world):
    """The collision rule: a stored name of a live agent wins over the shown lead name."""
    rt, _, cfg = world
    twin, _ = await rt.roster.create(name="Athena", title="Archivist")
    lead = await rt.roster.get("jarvis")
    assert twin.agent_id == "athena"
    assert display_name(twin, cfg) == display_name(lead, cfg) == "Athena"
    for ref in ("Athena", "athena"):
        assert (await lookup_agent(rt, ref)).agent.agent_id == "athena"
        assert (await resolve_shown(rt, ref)).agent_id == "athena"
    # The lead stays reachable by what the roster stores for it.
    for ref in (STORED, "jarvis"):
        assert (await lookup_agent(rt, ref)).agent.agent_id == "jarvis"
    # A near miss is not ambiguous either: the shown lead name is no candidate here.
    agents = await rt.roster.list()
    close = lookup_in(agents, "Atena", aliases={}, include_lead=True)
    assert close.decision == "act" and close.agent.agent_id == "athena"
    # Once the teammate is gone, the name means the lead again.
    await rt.roster.archive("athena")
    assert (await lookup_agent(rt, "Athena")).agent.agent_id == "jarvis"
    assert (await resolve_shown(rt, "Athena")).agent_id == "jarvis"


def test_a_name_matches_the_lead_only_as_a_whole(tmp_path: Path):
    cfg = _config(tmp_path, "Hey Mary Ann")
    assert lead_display_name(cfg) == "Mary Ann"
    for ref in ("Mary Ann", "mary-ann", "MARY  ANN"):
        assert names_the_lead(ref, cfg), ref
    for ref in ("", "Mary", "Ann", "Maryann2", STORED):
        assert not names_the_lead(ref, cfg), ref


async def test_the_mcp_surface_lists_the_lead_under_its_shown_name(world):
    rt, _, _ = world
    lead, scout = await rt.roster.get("jarvis"), await rt.roster.get("scout")
    assert mcp_tools._agent_row(rt, lead)["name"] == "Athena"  # noqa: SLF001
    assert mcp_tools._agent_row(rt, scout) == scout.to_dict()  # noqa: SLF001


def test_the_rest_surface_shows_the_lead_under_its_shown_name(tmp_path: Path):
    cfg = _config(tmp_path, "Hey Athena")
    svc = Chat(AgentChatStore(tmp_path / "agent_chat.db"))
    runtime = SocietyRuntime(
        tmp_path, seed_starter_team=False, cfg=lambda: cfg, chat_service=lambda: svc
    )
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    app.state.config = cfg
    with TestClient(app) as c:

        def lead() -> dict:
            agents = c.get("/api/society/agents").json()["agents"]
            return next(a for a in agents if a["tier"] == "lead")

        assert lead()["name"] == "Athena" and lead()["agent_id"] == "jarvis"
        assert c.get("/api/society/agents/jarvis").json()["agent"]["name"] == "Athena"
        # Creating under the stored name adopts the lead; the answer is still its shown name.
        adopted = c.post("/api/society/agents", json={"name": STORED}).json()
        assert adopted["created"] is False and adopted["agent"]["name"] == "Athena"

        scout = c.post("/api/society/agents", json={"name": "Scout"}).json()["agent"]
        assert scout["name"] == "Scout"
        svc.store.create_session(
            session_id="society:scout:with:jarvis", surface="society", provider="openai",
            model="", effort="", cwd=str(tmp_path), permission_mode="bypass", title="",
        )
        chats = c.get("/api/society/agents/scout/conversations").json()["conversations"]
        assert [(row["counterpart_id"], row["counterpart_name"]) for row in chats] == [
            ("jarvis", "Athena")
        ]
        assert c.get("/api/society/agents/jarvis/conversations").json()["conversations"][0][
            "counterpart_name"
        ] == "Scout"

        cfg.trigger.wake_word.phrase = ""
        assert lead()["name"] == DEFAULT_ASSISTANT_NAME
        app.state.config = None
        assert lead()["name"] == DEFAULT_ASSISTANT_NAME
    svc.store.close()


async def test_a_meeting_without_a_wake_word_uses_the_neutral_name(tmp_path: Path):
    svc = MeetingChatFake(AgentChatStore(tmp_path / "chat.db"))
    cfg = _config(tmp_path, "")
    rt = SocietyRuntime(tmp_path, chat_service=lambda: svc, cfg=lambda: cfg)
    await rt.ensure_started()
    try:
        await rt.roster.create(name="Scout", provider="ollama", model="fake")
        await rt.roster.update("jarvis", {"provider": "ollama", "model": "fake"})
        await rt.store.create_chat_group("team", "Team", ["jarvis", "scout"])
        await rt.meetings.start("team", "Plan the week")
        await asyncio.gather(*rt.meetings._tasks.values())  # noqa: SLF001
        assert f"these agents: {DEFAULT_ASSISTANT_NAME}, Scout" in svc.sent[0][1]
        assert STORED not in svc.sent[0][1] and STORED not in svc.sent[1][1]
    finally:
        await rt.close()
        svc.store.close()
