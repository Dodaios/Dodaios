"""Tests for the ``navigate`` router tool.

The tool lets a spoken/typed command move the desktop UI to a sidebar section by
publishing a ``NavigateSidebar`` event (the frontend listener in
``useWebSocket.ts`` already switches the section on it). Contract:

- a canonical section id ("socials") → publishes NavigateSidebar(section="socials"),
- a natural-language alias ("Einstellungen", "social media") → normalized to the id,
- an unknown section → success=False, nothing published,
- the tool's known sections stay in parity with the frontend SECTION_IDS
  (the wire-format enum guard from docs/anti-drift-three-layer.md).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from dodaios.core.events import NavigateSidebar
from dodaios.plugins.tool.navigate import NavigateTool


class RecordingBus:
    """Minimal fake bus that records published events (no unittest.mock)."""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture()
def bus() -> RecordingBus:
    return RecordingBus()


@pytest.fixture()
def tool(bus: RecordingBus) -> NavigateTool:
    return NavigateTool(bus=bus)


async def test_canonical_id_publishes_navigate(tool: NavigateTool, bus: RecordingBus) -> None:
    res = await tool.execute({"section": "socials"}, ctx=None)
    assert res.success is True
    assert len(bus.events) == 1
    ev = bus.events[0]
    assert isinstance(ev, NavigateSidebar)
    assert ev.section == "socials"


@pytest.mark.parametrize(
    "spoken,expected",
    [
        ("Socials", "socials"),
        ("social media", "socials"),
        ("Einstellungen", "settings"),
        ("settings", "settings"),
        ("agenten", "agents"),
        ("sub-agents", "agents"),
        # The retired Automations section: scheduled work lives on agents.
        ("Aufgaben", "agents"),
        ("tasks", "agents"),
        ("notizen", "memory"),
        # The retired Outputs section: its old id and spoken names land on
        # Artifacts, where every run is listed now (2026-08-23).
        ("outputs", "visualization"),
        ("Ausgaben", "visualization"),
        ("ergebnisse", "visualization"),
        # My Pets: the id itself and the phrases that name the app's own pet.
        ("pets", "pets"),
        ("My Pets", "pets"),
        ("desktop pet", "pets"),
        ("Haustier", "pets"),  # i18n-allow: input vocab
        ("meine pets", "pets"),  # i18n-allow: input vocab
        ("mis mascotas", "pets"),  # i18n-allow: input vocab
    ],
)
async def test_alias_normalizes_to_id(
    bus: RecordingBus, tool: NavigateTool, spoken: str, expected: str
) -> None:
    res = await tool.execute({"section": spoken}, ctx=None)
    assert res.success is True, res
    assert isinstance(bus.events[0], NavigateSidebar)
    assert bus.events[0].section == expected


async def test_unknown_section_fails_and_publishes_nothing(
    tool: NavigateTool, bus: RecordingBus
) -> None:
    res = await tool.execute({"section": "weather"}, ctx=None)
    assert res.success is False
    assert bus.events == []


async def test_missing_section_fails(tool: NavigateTool, bus: RecordingBus) -> None:
    res = await tool.execute({}, ctx=None)
    assert res.success is False
    assert bus.events == []


def test_tool_metadata() -> None:
    assert NavigateTool.name == "navigate"
    assert NavigateTool.risk_tier == "safe"
    # The schema enumerates valid sections so the router picks a real one.
    enum = NavigateTool.schema["properties"]["section"]["enum"]
    assert "socials" in enum and "settings" in enum


def test_removed_sections_are_unknown() -> None:
    """Contacts and Local models left the app; neither is a navigable target."""
    for section in ("contacts", "local-models"):
        assert section not in NavigateTool.known_sections()
        assert section not in NavigateTool.schema["properties"]["section"]["enum"]


def test_known_sections_match_frontend_section_ids() -> None:
    """Drift guard: the tool's sections must equal the frontend SECTION_IDS."""
    events_ts = (
        Path(__file__).resolve().parents[4]
        / "dodaios/ui/web/frontend/src/store/events.ts"
    )
    text = events_ts.read_text(encoding="utf-8")
    block = re.search(r"SECTION_IDS\s*=\s*\[(.*?)\]\s*as const", text, re.DOTALL)
    assert block, "could not find SECTION_IDS array in store/events.ts"
    # [a-z0-9_-]+ — underscore added to match "run_inspector" (hyphen-only
    # pattern silently dropped it, so KNOWN had run_inspector but ts_ids didn't).
    ts_ids = set(re.findall(r'"([a-z0-9_-]+)"', block.group(1)))
    assert ts_ids, "no ids parsed from SECTION_IDS"
    assert NavigateTool.known_sections() == ts_ids


# --- one thing inside a section ---------------------------------------------------


def _targets(bus: RecordingBus, **lookups) -> NavigateTool:
    async def chat(spoken: str) -> dict:
        return lookups.get("chat", {"status": "unavailable"})

    async def workspace(spoken: str) -> dict:
        return lookups.get("workspace", {"status": "unavailable"})

    return NavigateTool(
        bus=bus,
        find_agent=lambda spoken: lookups.get("agent", {"status": "unavailable"}),
        find_chat=chat,
        show_workspace=workspace,
    )


@pytest.mark.asyncio
async def test_a_named_agent_opens_that_agents_chat(bus: RecordingBus) -> None:
    tool = _targets(bus, agent={"status": "found", "id": "agent-7", "name": "Scout"})
    res = await tool.execute({"agent": "  scout "}, None)
    assert res.success and res.output["agent"] == "Scout"
    (event,) = bus.events
    assert isinstance(event, NavigateSidebar)
    assert (event.section, event.target, event.target_id) == ("chats", "agent", "agent-7")


@pytest.mark.asyncio
async def test_a_conversation_title_opens_that_conversation(bus: RecordingBus) -> None:
    tool = _targets(bus, chat={"status": "found", "id": "s-1", "name": "Trip to Lisbon"})
    res = await tool.execute({"chat": "trip to lisbon"}, None)
    assert res.success
    (event,) = bus.events
    assert (event.section, event.target, event.target_id) == ("chats", "chat", "s-1")


@pytest.mark.asyncio
async def test_a_workspace_is_shown_in_the_coding_section(bus: RecordingBus) -> None:
    tool = _targets(bus, workspace={"status": "found", "id": "", "name": "Installer"})
    res = await tool.execute({"workspace": "installer"}, None)
    assert res.success and res.output["workspace"] == "Installer"
    (event,) = bus.events
    assert (event.section, event.target, event.target_id) == ("agentic-ide", "", "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lookup", "says"),
    [
        ({"status": "ask", "candidates": ["Scout", "Scout 2"]}, "More than one agent"),
        ({"status": "unknown", "available": ["Archivist"]}, "Known: Archivist"),
        ({"status": "unavailable"}, "cannot open a agent right now"),
    ],
)
async def test_an_unresolved_target_moves_nothing_and_says_why(
    bus: RecordingBus, lookup: dict, says: str
) -> None:
    res = await _targets(bus, agent=lookup).execute({"agent": "scout"}, None)
    assert res.success is False and says in res.error
    assert bus.events == []


@pytest.mark.asyncio
async def test_two_destinations_at_once_are_refused(bus: RecordingBus) -> None:
    tool = _targets(bus, agent={"status": "found", "id": "a", "name": "Scout"})
    for args in ({"agent": "scout", "section": "settings"}, {"agent": "scout", "chat": "x"}):
        res = await tool.execute(args, None)
        assert res.success is False and "one destination" in res.error
    assert bus.events == []


@pytest.mark.asyncio
async def test_a_plain_section_switch_carries_no_target(tool: NavigateTool, bus) -> None:
    await tool.execute({"section": "settings"}, None)
    (event,) = bus.events
    assert (event.target, event.target_id) == ("", "")
