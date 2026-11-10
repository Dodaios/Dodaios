"""The ``living_page`` and ``show_result_card`` tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.artifacts import living_refresh
from dodaios.artifacts.living import LivingPageStore
from dodaios.plugins.tool import living_page as living_tool
from dodaios.plugins.tool.living_page import LivingPageTool, session_of
from dodaios.plugins.tool.result_card import ResultCardTool, normalize_items


def _ctx(session: str = "lead-1") -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "output_language": "de"},
        memory_read=None,
    )


@pytest.fixture
def cards(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    posted: list[tuple[str, dict]] = []

    async def fake_post(session_id: str, payload: dict) -> bool:
        posted.append((session_id, payload))
        return True

    monkeypatch.setattr(living_tool, "post_card", fake_post)
    monkeypatch.setattr("dodaios.plugins.tool.result_card.post_card", fake_post)
    return posted


@pytest.fixture
def refresh(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def start(store, page_id):
        calls.append(f"start:{page_id}")
        return store.set_refresh(page_id, refreshing=True, task_id="task-9")

    async def stop(store, page_id):
        calls.append(f"stop:{page_id}")
        return store.set_refresh(page_id, refreshing=False)

    monkeypatch.setattr(living_refresh, "start_refresh", start)
    monkeypatch.setattr(living_refresh, "stop_refresh", stop)
    return calls


async def test_create_builds_the_page_schedules_it_and_shows_a_card(
    tmp_path: Path, cards, refresh
) -> None:
    store = LivingPageStore(root=tmp_path)
    tool = LivingPageTool(store=store)
    result = await tool.execute(
        {
            "operation": "create",
            "title": "Bewerbungen",
            "track": "My job applications from Gmail replies.",
            "columns": ["Company", "Stage"],
            "rows": [{"Company": "Acme", "Stage": "Interview"}],
            "every_minutes": 120,
        },
        _ctx(),
    )
    assert result.success, result.error
    page = store.list_pages()[0]
    assert page.refreshing and page.every_minutes == 120 and page.language == "de"
    assert page.id in result.output and "120 minutes" in result.output
    assert refresh == [f"start:{page.id}"]
    session, card = cards[0]
    assert session == "lead-1" and card["kind"] == "chain_result"
    assert card["items"][0]["artifact"] == page.visual_id


async def test_create_without_the_scheduler_still_keeps_the_page(
    tmp_path: Path, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(store, page_id):
        raise RuntimeError("The agent society is not running")

    monkeypatch.setattr(living_refresh, "start_refresh", down)
    store = LivingPageStore(root=tmp_path)
    result = await LivingPageTool(store=store).execute(
        {"operation": "create", "title": "Stocks", "track": "x", "columns": ["Ticker"]}, _ctx()
    )
    assert result.success and "cannot refresh yet" in result.output
    assert not store.list_pages()[0].refreshing


async def test_update_stop_resume_and_list(tmp_path: Path, cards, refresh) -> None:
    store = LivingPageStore(root=tmp_path)
    page = store.create(title="Parcels", track="x", columns=["Parcel"])
    tool = LivingPageTool(store=store)

    updated = await tool.execute(
        {"operation": "update", "page_id": page.id, "rows": [{"Parcel": "Lamp"}]}, _ctx()
    )
    assert updated.success and "1 rows" in updated.output
    assert store.get(page.id).rows == ({"Parcel": "Lamp"},)

    noted = await tool.execute(
        {"operation": "update", "page_id": page.id, "note": "Gmail is not connected"}, _ctx()
    )
    assert noted.success and store.get(page.id).rows == ({"Parcel": "Lamp"},)

    assert (await tool.execute({"operation": "stop", "page_id": page.id}, _ctx())).success
    resumed = await tool.execute(
        {"operation": "resume", "page_id": page.id, "every_minutes": 30}, _ctx()
    )
    assert resumed.success and store.get(page.id).every_minutes == 30
    assert refresh == [f"stop:{page.id}", f"start:{page.id}"]

    listed = await tool.execute({"operation": "list"}, _ctx())
    assert listed.output[0]["page_id"] == page.id
    # Only a create posts a card; a refresh run stays out of the conversation.
    assert cards == []


async def test_bad_calls_say_what_to_fix(tmp_path: Path) -> None:
    tool = LivingPageTool(store=LivingPageStore(root=tmp_path))
    assert not (await tool.execute({"operation": "explode"}, _ctx())).success
    missing = await tool.execute({"operation": "update"}, _ctx())
    assert not missing.success and "page_id" in missing.error
    unknown = await tool.execute({"operation": "update", "page_id": "0123456789ab"}, _ctx())
    assert not unknown.success


def test_session_of_reads_the_chat_approval_reference() -> None:
    assert session_of(_ctx("abc")) == "abc"
    assert session_of(SimpleNamespace(config={"approval_ref": "society:x"})) == ""
    assert session_of(SimpleNamespace(config=None)) == ""


def test_result_items_keep_known_fields_and_safe_links() -> None:
    items = normalize_items(
        [
            {"kind": "event", "label": "Dentist", "url": "https://cal.example/e/1"},
            {"kind": "draft", "label": "Reply to Anna", "state": "draft"},
            {"kind": "weird", "label": "Thing", "state": "exploded", "url": "javascript:x"},
            {"kind": "task"},
            "junk",
        ]
    )
    assert [i["label"] for i in items] == ["Dentist", "Reply to Anna", "Thing"]
    assert items[0]["state"] == "created" and items[0]["url"].startswith("https://")
    assert items[2]["kind"] == "other" and items[2]["state"] == "created"
    assert "url" not in items[2]


async def test_result_card_posts_one_card_into_the_calling_chat(cards) -> None:
    result = await ResultCardTool().execute(
        {
            "title": "Mail from Anna",
            "items": [
                {"kind": "event", "label": "Lunch, Fri 12:30", "url": "https://cal.example/1"},
                {"kind": "draft", "label": "Reply to Anna", "state": "waiting"},
            ],
        },
        _ctx("lead-7"),
    )
    assert result.success and "1 part(s) wait" in result.output
    session, card = cards[0]
    assert session == "lead-7"
    assert card == {
        "kind": "chain_result",
        "text": "Mail from Anna",
        "items": [
            {
                "kind": "event",
                "label": "Lunch, Fri 12:30",
                "state": "created",
                "url": "https://cal.example/1",
            },
            {"kind": "draft", "label": "Reply to Anna", "state": "waiting"},
        ],
    }
    assert not (await ResultCardTool().execute({"items": []}, _ctx())).success


def test_tools_are_router_reachable_and_never_spawn() -> None:
    from dodaios.brain.factory import ROUTER_TOOLS
    from dodaios.society.capabilities import capability_id_for_tool

    assert {"living-page", "show-result-card"} <= ROUTER_TOOLS
    # The lead's refresh routine (a society seat) may hold the page tool.
    assert capability_id_for_tool("living_page") == "plugin:living_page"
    assert LivingPageTool.risk_tier == "monitor" and ResultCardTool.risk_tier == "safe"
