"""Chat-template tool markup a local server returned as text is recovered.

A Qwen / Hermes model behind a server that does not parse tool calls (llama.cpp
without ``--jinja``, an unknown LM Studio template) writes
``<tool_call>{"name": ..., "arguments": ...}</tool_call>``; Mistral writes
``[TOOL_CALLS][...]``. Before this fix the recovery only knew JSON envelopes
with a ``type`` wrapper, the voice scrubber then removed the tag, and the
person got an empty reply while nothing ran.

The tag is a template token, so it is a strong signal — but it carries no
``type``, so the gate is different: only a tool OFFERED this round may run,
and markup inside a code fence is documentation.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.brain.tool_call_recovery import (
    extract_leaked_tool_calls,
    extract_tagged_tool_calls,
)

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "open_app",
        "description": "",
        "input_schema": {"type": "object", "properties": {"app": {"type": "string"}}},
    },
    {
        "name": "set_volume",
        "description": "",
        "input_schema": {"type": "object", "properties": {"level": {"type": "integer"}}},
    },
]


def _calls(text: str, tools: Any = _TOOLS) -> list[tuple[str, dict[str, Any]]]:
    return [(c["name"], c["input"]) for c in extract_tagged_tool_calls(text, tools)[0]]


_QWEN = '{"name": "open_app", "arguments": {"app": "spotify"}}'


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("object arguments", f"<tool_call>{_QWEN}</tool_call>"),
        (
            "arguments as a JSON string",
            '<tool_call>{"name": "open_app", '
            '"arguments": "{\\"app\\": \\"spotify\\"}"}</tool_call>',
        ),
        ("newlines inside the tag", f"<tool_call>\n{_QWEN}\n</tool_call>"),
        ("prose before", f"Opening it.\n<tool_call>{_QWEN}</tool_call>"),
        ("missing close tag at the end", f"<tool_call>{_QWEN}"),
        ("OpenAI function wrapper", f'<tool_call>{{"type": "function", "function": {_QWEN}}}'
                                    "</tool_call>"),
        (
            "Qwen3-Coder XML",
            "<tool_call>\n<function=open_app>\n<parameter=app>\nspotify\n</parameter>\n</function>\n</tool_call>",
        ),
        ("Mistral array", '[TOOL_CALLS][{"name": "open_app", "arguments": {"app": "spotify"}}]'),
        ("Mistral v11 name[ARGS]", '[TOOL_CALLS]open_app[ARGS]{"app": "spotify"}'),
    ],
)
def test_template_markup_is_recovered(label: str, text: str) -> None:
    assert _calls(text) == [("open_app", {"app": "spotify"})], label


def test_several_tagged_calls_all_run_in_order() -> None:
    text = (
        '<tool_call>{"name": "open_app", "arguments": {"app": "spotify"}}</tool_call>\n'
        '<tool_call>{"name": "set_volume", "arguments": {"level": 30}}</tool_call>'
    )
    assert _calls(text) == [("open_app", {"app": "spotify"}), ("set_volume", {"level": 30})]


def test_xml_parameters_are_typed_by_the_schema() -> None:
    text = (
        "<tool_call><function=set_volume><parameter=level>30</parameter></function></tool_call>"
        "<tool_call><function=open_app><parameter=app>42</parameter></function></tool_call>"
    )
    # An integer field decodes; a string field keeps "42" as text.
    assert _calls(text) == [("set_volume", {"level": 30}), ("open_app", {"app": "42"})]


def test_a_tool_that_was_not_offered_never_runs_and_is_hidden() -> None:
    text = 'Sure. <tool_call>{"name": "delete_everything", "arguments": {}}</tool_call>'
    calls, remaining = extract_tagged_tool_calls(text, _TOOLS)
    assert calls == []
    assert remaining == "Sure."


def test_markup_in_a_code_fence_is_an_example() -> None:
    text = '```\n<tool_call>{"name": "open_app", "arguments": {"app": "x"}}</tool_call>\n```'
    calls, remaining = extract_tagged_tool_calls(text, _TOOLS)
    assert calls == []
    assert remaining == text


def test_a_tag_around_prose_is_left_alone() -> None:
    text = "Qwen writes calls between <tool_call> and </tool_call> tags."
    assert extract_tagged_tool_calls(text, _TOOLS) == ([], text)


def test_malformed_arguments_run_nothing() -> None:
    assert _calls('<tool_call>{"name": "open_app", "arguments": "{broken"}</tool_call>') == []


def test_without_offered_tools_nothing_runs() -> None:
    assert _calls('<tool_call>{"name": "open_app", "arguments": {}}</tool_call>', tools=[]) == []


def test_loop_entry_point_recovers_tags_only_with_offered_tools() -> None:
    text = '<tool_call>{"name": "open_app", "arguments": {"app": "spotify"}}</tool_call>'
    assert [c["name"] for c in extract_leaked_tool_calls(text, _TOOLS)] == ["open_app"]
    # Callers that pass no tool list keep the old, envelope-only behaviour.
    assert extract_leaked_tool_calls(text) == []
