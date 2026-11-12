"""``standing_task`` reaches an unattended lead routine run, on a brain seat and a CLI seat.

A standing-task run is a lead routine: its chat is ``society:<lead>:routine:<task>:<run>``
on the society surface, whose tools come from ``society_tools`` and not from the tool
gateway's lead set. The run must be able to report without an approval card, in a chat
whose permission mode is ``ask``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_chat.approval_bridge import ChatApprovalBridge, ChatGrant, approval_ref
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.protocols import ChatTurn, current_chat_turn
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.reversibility import autonomy_origin
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.society.runtime import SocietyRuntime
from dodaios.society.surface import (
    society_system_extra,
    society_tool_filter,
    society_tools,
    tools_for_cli_session,
)
from tests.fakes.fake_standing_tasks import FakeStandingService, install

RUN = f"society:{LEAD_AGENT_ID}:routine:task-1:0123abcd"


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description="x.", risk_tier="monitor", schema={})


LIVE = {"gmail": _tool("gmail"), "search-web": _tool("search-web")}


@pytest.fixture
async def rt(tmp_path: Path):
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, brain_tools=lambda: LIVE)
    await runtime.ensure_started()
    try:
        yield runtime
    finally:
        await runtime.close()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeStandingService:
    return install(monkeypatch)


def _cfg(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(wiki=SimpleNamespace(vault_root=str(tmp_path / "vault")))


def _run_chat(
    rt: SocietyRuntime, tmp_path: Path, session_id: str = RUN, *, override: str = ""
) -> SimpleNamespace:
    """The run's chat as the routine runner creates it for a watch or prepare task.

    ``override`` is the stance the chat store holds for this chat; with ``ask`` the
    society gate turns every tier above ``safe`` into a card.
    """
    session = SimpleNamespace(
        session_id=session_id, surface="society", permission_mode="ask", cwd=str(tmp_path)
    )
    store = SimpleNamespace(
        get_session=lambda sid: session if sid == session.session_id else None,
        permission_override=lambda _sid: override,
    )
    rt._get_chat = lambda: SimpleNamespace(store=store)  # noqa: SLF001 - live store seam
    return session


async def test_only_the_leads_society_chats_get_the_tool(rt: SocietyRuntime, tmp_path: Path):
    await rt.roster.create(name="Scout")
    cfg = _cfg(tmp_path)
    lead_run = society_tools(cfg, None, SimpleNamespace(session_id=RUN))
    scout = society_tools(cfg, None, SimpleNamespace(session_id="society:scout"))
    scout_run = society_tools(
        cfg, None, SimpleNamespace(session_id="society:scout:routine:task-9:ffff")
    )
    assert "standing_task" in lead_run
    assert "standing_task" not in scout and "standing_task" not in scout_run


async def test_the_brain_seat_keeps_it_through_the_filter_whatever_the_grants(
    rt: SocietyRuntime, tmp_path: Path
):
    # An allow-list that names nothing: a granted plugin tool would be dropped here.
    await rt.roster.update(LEAD_AGENT_ID, {"grant_mode": "allowlist", "grants": []})
    cfg = _cfg(tmp_path)
    session = _run_chat(rt, tmp_path)
    await society_system_extra(cfg, None, session)  # fills the cache the filter reads
    select = society_tool_filter(session)
    assert select is not None
    picked = select({**LIVE, **society_tools(cfg, None, session)})
    assert "standing_task" in picked and "gmail" not in picked
    gated = picked["standing_task"]
    # What a run must call without a card stays ``safe`` through the gate.
    for action in ("report", "note", "propose", "status"):
        assert gated.risk_tier_for_args({"action": action}) == "safe", action


async def test_the_cli_seat_lists_it_for_the_run_and_not_for_another_agent(
    rt: SocietyRuntime, tmp_path: Path
):
    await rt.roster.create(name="Scout")
    brain = SimpleNamespace(_config=_cfg(tmp_path))
    session = _run_chat(rt, tmp_path)
    await society_system_extra(brain._config, None, session)
    for_run = await tools_for_cli_session(RUN, dict(LIVE), brain)
    assert for_run is not None and "standing_task" in for_run

    other = _run_chat(rt, tmp_path, "society:scout")
    await society_system_extra(brain._config, None, other)
    for_scout = await tools_for_cli_session("society:scout", dict(LIVE), brain)
    assert for_scout is not None and "standing_task" not in for_scout


async def test_a_run_reports_through_the_executor_without_a_card(
    rt: SocietyRuntime, tmp_path: Path, service: FakeStandingService
):
    """The whole path of one report: filter, gate, executor, tool, service."""
    service.add("st_1", task_id="task-1")
    cfg = _cfg(tmp_path)
    session = _run_chat(rt, tmp_path, override="ask")
    await society_system_extra(cfg, None, session)
    select = society_tool_filter(session)
    assert select is not None
    tool = select(society_tools(cfg, None, session))["standing_task"]
    assert tool.risk_tier_for_args({"action": "pause"}) == "ask"

    bus = EventBus()
    executor = ToolExecutor(bus, RiskTierEvaluator(SafetyConfig()), ApprovalWorkflow(bus))
    cards: list[str] = []

    async def card(_call_id: str, name: str, _args: dict, _summary: str) -> str:
        cards.append(name)
        return "deny"

    ref = approval_ref(session.session_id)
    ChatApprovalBridge(bus).arm(
        ref,
        ChatGrant(
            session_id=session.session_id, turn_id="turn-1", stance="ask",
            always_allowed=set(), ask=card,
        ),
    )
    snapshot = {"approval_surface": "interactive", "approval_ref": ref, "approval_timeout_s": 5}
    turn = ChatTurn(session.session_id, "turn-1", "Scheduled routine", False, "t", origin="routine")
    token = current_chat_turn.set(turn)
    try:
        with autonomy_origin("routine", task_id="task-1", agent_id=LEAD_AGENT_ID):
            result = await executor.execute(
                tool,
                {
                    "action": "report", "standing_id": "st_1", "outcome": "quiet",
                    "summary": "No change since yesterday.", "next_check_min": 360,
                },
                config_snapshot=snapshot,
            )
            # The same run may not start a task of its own: that becomes a proposal.
            started = await executor.execute(
                tool,
                {"action": "propose", "title": "Inbox", "goal": "Tell me when a customer writes."},
                config_snapshot=snapshot,
            )
            assert cards == []
            # The card is live in this chat: a change that is not a report asks first.
            paused = await executor.execute(
                tool, {"action": "pause", "standing_id": "st_1"}, config_snapshot=snapshot
            )
    finally:
        current_chat_turn.reset(token)
    assert result.success, result.error
    assert started.success and started.output["state"] == "proposed"
    assert cards == ["standing_task"] and not paused.success
    assert not service.called("pause")
    (report,) = service.called("report")
    assert report["session_id"] == RUN and report["next_check_min"] == 360
    assert result.output["pace"] == "every 6 hours"
