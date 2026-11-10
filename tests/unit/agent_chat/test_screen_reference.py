""""What's this?" in the lead conversation resolves against the screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.agent_chat import screen_reference
from dodaios.agent_chat.screen_reference import (
    away_from_screen,
    refers_to_screen,
    screen_context_block,
)
from dodaios.screen_context.turn import TurnScreenContext


@pytest.mark.parametrize(
    "text",
    [
        "what's this?",
        "What is that?",
        "turn this mail into a calendar event and a task, and draft the reply",
        "summarize this",
        "translate that for me",
        "reply to this message politely",
        "keep a page that tracks the parcels in this list",
        "was ist das?",  # i18n-allow: German input sample
        "fass das mal zusammen",  # i18n-allow: German input sample
        "mach aus dieser Mail einen Termin",  # i18n-allow: German input sample
        "übersetz das",  # i18n-allow: German input sample
        "resume esto",
        "convierte este correo en un evento",  # i18n-allow: Spanish input sample
        "o que é isto?",  # i18n-allow: Portuguese input sample
    ],
)
def test_deictic_messages_point_at_the_screen(text: str) -> None:
    assert refers_to_screen(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "how are you?",
        "add milk to my shopping list",
        "this is great, thanks",
        "that was a good idea",
        "remind me tomorrow at 9",
        "click this button",
        "what's the weather in Berlin?",
        "this " * 80,
    ],
)
def test_ordinary_messages_do_not(text: str) -> None:
    assert not refers_to_screen(text)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    async def fake_turn(utterance, **kwargs):
        calls.append({"utterance": utterance, **kwargs})
        return TurnScreenContext(
            status="captured",
            image=b"\x89PNG\r\n\x1a\nfake",
            mime="image/png",
            note="<SCREEN_EVIDENCE>Mail from Anna</SCREEN_EVIDENCE>",
        )

    monkeypatch.setattr("dodaios.screen_context.turn.screen_context_for_turn", fake_turn)
    monkeypatch.setattr(screen_reference, "_switch_on", lambda: True)
    return calls


async def test_a_deictic_turn_carries_one_capture(tmp_path: Path, captured) -> None:
    block = await screen_context_block(
        "turn this mail into an event", session_id="lead-1", cwd=str(tmp_path), locale="en"
    )
    assert len(captured) == 1 and captured[0]["force"] is True
    assert captured[0]["allow_pending_appshot"] is False
    assert "Screen Context is on" in block
    assert "<SCREEN_EVIDENCE>Mail from Anna</SCREEN_EVIDENCE>" in block
    assert "saved in this chat's folder as" in block
    saved = await asyncio.to_thread(lambda: list(tmp_path.rglob("*.png")))
    assert len(saved) == 1


async def test_nothing_is_captured_without_a_deictic(tmp_path: Path, captured) -> None:
    assert await screen_context_block("hello there", session_id="s", cwd=str(tmp_path)) == ""
    assert captured == []


async def test_the_switch_off_means_no_look(
    tmp_path: Path, captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screen_reference, "_switch_on", lambda: False)
    assert await screen_context_block("what's this?", session_id="s", cwd=str(tmp_path)) == ""
    assert captured == []


async def test_a_message_from_away_never_looks(tmp_path: Path, captured) -> None:
    with away_from_screen():
        block = await screen_context_block("what's this?", session_id="s", cwd=str(tmp_path))
    assert block == "" and captured == []


async def test_a_privacy_refusal_is_said_and_a_failure_is_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screen_reference, "_switch_on", lambda: True)

    async def refused(utterance, **kwargs):
        return TurnScreenContext(status="refused", message="That window is on the denylist.")

    monkeypatch.setattr("dodaios.screen_context.turn.screen_context_for_turn", refused)
    block = await screen_context_block("what's this?", session_id="s", cwd=str(tmp_path))
    assert "denylist" in block

    async def broken(utterance, **kwargs):
        raise RuntimeError("no display")

    monkeypatch.setattr("dodaios.screen_context.turn.screen_context_for_turn", broken)
    assert await screen_context_block("what's this?", session_id="s", cwd=str(tmp_path)) == ""
