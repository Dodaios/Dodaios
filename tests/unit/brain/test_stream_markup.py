"""``<think>`` reasoning never reaches the chat or the voice.

Local reasoning models (Qwen, DeepSeek-R1 distills) write their thoughts into
``delta.content``. The streamer used to pass every chunk straight on, so the
chat showed the reasoning and TTS read it aloud. These tests pin the filter
that sits in the one OpenAI-compatible streamer every local provider uses.
"""

from __future__ import annotations

import pytest

from dodaios.brain import stream_markup
from dodaios.brain.stream_markup import PREFIX_HOLD_CHARS, StreamMarkupFilter


@pytest.fixture(autouse=True)
def _fresh_habits():
    stream_markup.reset_think_habits()
    yield
    stream_markup.reset_think_habits()


def _run(chunks: list[str], **kwargs) -> str:
    flt = StreamMarkupFilter([], **kwargs)
    return "".join(flt.feed(c) for c in chunks) + flt.finish()


def test_a_think_block_is_removed() -> None:
    assert _run(["<think>The user greets me.</think>\n\nHello!"]) == "Hello!"


def test_tags_split_across_chunks_are_still_removed() -> None:
    chunks = ["<th", "ink>reas", "oning</thi", "nk>", "\n\nHel", "lo!"]
    assert _run(chunks) == "Hello!"


def test_one_character_chunks() -> None:
    text = "Hi. <think>hidden</think>There."
    assert _run(list(text)) == "Hi. There."


def test_unclosed_think_at_the_start_is_never_shown() -> None:
    assert _run(["<think>Let me think about this", " for a long time"]) == ""


def test_stray_closer_is_dropped_and_learned() -> None:
    key = ("http://localhost:8080/v1", "qwen3")
    # Cloud-style call without a prefix hold: the reasoning before the stray
    # closer cannot be known in time, but the tag never shows.
    first = _run(["Okay, the user wants hi.", "</think>", "Hi!"], habit_key=key)
    assert "</think>" not in first and first.endswith("Hi!")
    # From now on this model's replies are held back until the closer.
    assert _run(["Thinking again.", "</think>\n", "Hello."], habit_key=key) == "Hello."


def test_local_provider_holds_the_start_of_an_unknown_model() -> None:
    key = ("http://localhost:1234/v1", "ornith")
    out = _run(["The user asks", " for the time.", "</think>", "It is noon."],
               habit_key=key, hold_unknown_prefix=True)
    assert out == "It is noon."


def test_a_plain_model_is_released_after_its_first_reply() -> None:
    key = ("http://localhost:1234/v1", "plain")
    flt = StreamMarkupFilter([], habit_key=key, hold_unknown_prefix=True)
    assert flt.feed("Hello there.") == ""  # held: habit unknown
    assert flt.finish() == "Hello there."
    # Learned "plain": the next reply streams immediately.
    assert StreamMarkupFilter([], habit_key=key, hold_unknown_prefix=True).feed("Hi") == "Hi"


def test_the_prefix_hold_is_bounded() -> None:
    flt = StreamMarkupFilter([], habit_key=("u", "m"), hold_unknown_prefix=True)
    long = "x" * (PREFIX_HOLD_CHARS + 10)
    assert flt.feed(long) == long


def test_ordinary_angle_brackets_and_brackets_pass_through() -> None:
    text = "If a < b and [x] then <b>bold</b>."
    assert _run([text]) == text


def test_tool_markup_becomes_a_call_not_text() -> None:
    tools = [{"name": "open_app", "input_schema": {}}]
    flt = StreamMarkupFilter(tools)
    out = flt.feed('<think>open it</think>Opening. <tool_call>{"name": "open_app", ')
    out += flt.feed('"arguments": {"app": "spotify"}}</tool_')
    out += flt.feed("call>") + flt.finish()
    assert out == "Opening. "
    assert [(c["name"], c["input"]) for c in flt.calls] == [("open_app", {"app": "spotify"})]
