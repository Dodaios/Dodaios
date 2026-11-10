"""The phone chat contract: short, one question, routed by the owner's choice."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from dodaios.channels.base import ChannelMessage
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.channels.output_contract import STYLE_BLOCK, WORD_CAP, enforce, words
from dodaios.core.bus import EventBus
from dodaios.notify.settings import PHONE_DEFAULTS, NotifySettings, load_settings, save_settings

from .test_chat_bridge import _Manager, _ReplyChannel

LONG = " ".join(f"Sentence number {i} explains one more detail of the plan." for i in range(40))


def test_a_short_answer_is_sent_as_it_is() -> None:
    out = enforce("Lisbon, in June.")
    assert out.text == "Lisbon, in June." and out.shortened is False


def test_a_long_answer_becomes_a_summary_with_a_pointer() -> None:
    out = enforce(LONG)
    assert out.shortened is True
    assert words(out.text) <= WORD_CAP
    assert out.text.startswith("Sentence number 0 explains")
    assert out.text.splitlines()[-1] == "Full answer in the app."
    # Whole sentences only, never cut mid-sentence.
    body = out.text.splitlines()[0]
    assert body.endswith("plan.")


def test_the_pointer_follows_the_owner_language() -> None:
    out = enforce(LONG, language="de")
    assert "App" in out.text.splitlines()[-1]


def test_links_and_code_stay_intact() -> None:
    link = "https://example.com/a/very/long/path.with.dots/and?query=1&b=2"
    text = f"The report is ready at {link}. " + LONG
    out = enforce(text)
    assert link in out.text
    code = "```py\nprint('x')\n```"
    out = enforce(f"Run this: {code} Then check it. " + LONG)
    assert code in out.text or "print" not in out.text  # whole block or none, never half


def test_an_overlong_single_sentence_is_cut_at_a_clause_or_word() -> None:
    sentence = ", ".join(f"clause {i} of a very long run-on sentence" for i in range(40)) + "."
    out = enforce(sentence)
    assert words(out.text) <= WORD_CAP and out.text.endswith("Full answer in the app.")


def test_only_one_question_is_asked() -> None:
    out = enforce("Done with the draft. Which day works? And which room? Also, who joins?")
    assert out.text.count("?") == 1
    assert out.text.startswith("Done with the draft.")
    assert out.text.rstrip().endswith("Which day works?")


def test_the_style_block_states_the_contract() -> None:
    assert str(WORD_CAP) in STYLE_BLOCK
    assert "one question" in STYLE_BLOCK
    assert "progress" in STYLE_BLOCK.lower()


def test_routing_defaults_are_decisions_results_failures_only() -> None:
    settings = NotifySettings()
    assert [k for k in PHONE_DEFAULTS if settings.phone_allows(k)] == [
        "decisions", "results", "failures",
    ]
    assert not settings.phone_allows("progress") and not settings.phone_allows("brief")
    assert not settings.phone_allows("unknown_kind")


def test_routing_is_owner_editable_and_survives_a_round_trip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    save_settings({"phone": {"progress": True, "failures": False, "bogus": True}}, path)
    saved = load_settings(path)
    assert saved.phone_allows("progress") and not saved.phone_allows("failures")
    assert "bogus" not in saved.to_dict()["phone"]
    assert NotifySettings.from_dict(saved.to_dict()) == saved


async def _owner_turn(monkeypatch, answer: str, allowed: set[str], on_card=None):
    from dodaios.agent_chat import lead

    async def fake_answer(svc, text, *, source, report=None, on_card=None, **_kw):
        if on_card is not None and cards:
            for card in cards:
                await on_card(card)
        return answer

    cards = on_card or []
    monkeypatch.setattr(lead, "answer_in_lead", fake_answer)
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=EventBus(),
        manager=_Manager(channel),
        get_chat_service=lambda: object(),
        phone_allows=lambda kind: kind in allowed,
    )
    bridge.start()
    meta = {"telegram_chat_id": 12345, "friend_id": None}
    await channel.queue.put(
        ChannelMessage(session_id=uuid4(), kind="text", content="plan the trip", metadata=meta)
    )
    await asyncio.sleep(0.2)
    await bridge.stop()
    return channel


@pytest.mark.asyncio
async def test_a_long_lead_answer_reaches_the_phone_capped(monkeypatch) -> None:
    channel = await _owner_turn(monkeypatch, LONG, {"results"})
    assert len(channel.sent) == 1
    assert words(channel.sent[0].content) <= WORD_CAP
    assert "Full answer in the app." in channel.sent[0].content


@pytest.mark.asyncio
async def test_results_switched_off_send_nothing(monkeypatch) -> None:
    channel = await _owner_turn(monkeypatch, "All done.", {"decisions", "failures"})
    assert channel.sent == []


@pytest.mark.asyncio
async def test_progress_chatter_is_never_sent(monkeypatch) -> None:
    channel = await _owner_turn(monkeypatch, "", set(PHONE_DEFAULTS) - {"failures"})
    assert channel.sent == []  # the empty answer's failure line is off; nothing else exists


@pytest.mark.asyncio
async def test_a_repeated_decision_card_is_one_message(monkeypatch) -> None:
    from dodaios.agent_chat.lead import LeadCard

    card = LeadCard("approval", "Send the mail to Max", [])
    channel = await _owner_turn(monkeypatch, "Done.", {"decisions", "results"}, [card, card])
    texts = [m.content for m in channel.sent]
    assert sum("Send the mail to Max" in t for t in texts) == 1
    assert "Done." in texts


@pytest.mark.asyncio
async def test_decisions_off_keep_the_card_in_the_app(monkeypatch) -> None:
    from dodaios.agent_chat.lead import LeadCard

    card = LeadCard("approval", "Send the mail to Max", [])
    channel = await _owner_turn(monkeypatch, "Done.", {"results"}, [card])
    assert [m.content for m in channel.sent] == ["Done."]
