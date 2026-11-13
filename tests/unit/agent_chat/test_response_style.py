"""Human-facing chat runners share the reporting policy; voice keeps spoken rules."""

from pathlib import Path

import pytest

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat.runner_api import system_prompt
from dodaios.brain.manager import _WRITTEN_CHAT_STYLE
from dodaios.brain.persona_loader import load_compact_persona_prompt, load_persona_prompt
from dodaios.core.response_style import (
    CONVERSATIONAL_RESPONSE_STYLE,
    CONVERSATIONAL_TURN_REMINDER,
)


def test_api_and_main_chat_receive_the_same_reporting_policy(tmp_path: Path) -> None:
    prompt = system_prompt(cwd=tmp_path, assistant_name="Assistant")
    assert CONVERSATIONAL_RESPONSE_STYLE in prompt
    assert CONVERSATIONAL_RESPONSE_STYLE in _WRITTEN_CHAT_STYLE


def test_fresh_and_resumed_defaults_are_short_and_keep_requested_content_whole() -> None:
    assert CONVERSATIONAL_TURN_REMINDER in CONVERSATIONAL_RESPONSE_STYLE
    for policy in (CONVERSATIONAL_RESPONSE_STYLE, CONVERSATIONAL_TURN_REMINDER):
        # One length, as a number the model can hold itself to.
        assert "at most about 500 characters" in policy
        assert "is not technical" in policy
        assert "Go longer only when they ask for detail" in policy
        assert "(code, a text, data, a list they want); that stays complete" in policy
        assert "anything you already told them" in policy
        assert "Follow explicit user preferences" in policy
        # A failure is one sentence, not a complete evidence dump.
        assert "failure evidence" not in policy


def test_reply_style_keeps_the_person_oriented_without_a_persona() -> None:
    # State first, a line before the first tool call, concrete outcome, plain words.
    for phrase in (
        "reads only your messages",
        "Open with the answer or the state",
        "Before your first tool call",
        "concrete numbers, times and names",
        "No headings",
    ):
        assert phrase in CONVERSATIONAL_RESPONSE_STYLE, phrase
    # A general style: no persona, name or flirt register leaks in.
    for leak in ("Jenny", "flirt", "Discord"):
        assert leak not in CONVERSATIONAL_RESPONSE_STYLE


async def test_cli_without_brain_layers_still_receives_the_shared_default(monkeypatch) -> None:
    monkeypatch.setattr(dodaios_harness, "_brain", lambda: None)
    prompt = await dodaios_harness.identity_prompt(user_text="Hello", history=[], resume=None)
    assert CONVERSATIONAL_TURN_REMINDER in prompt
    assert "think longer and go deeper" not in prompt
    assert "Frontier-lab style" not in prompt


def test_plan_mode_keeps_its_read_only_contract(tmp_path: Path) -> None:
    prompt = system_prompt(cwd=tmp_path, assistant_name="Assistant", plan=True)
    assert CONVERSATIONAL_RESPONSE_STYLE in prompt
    assert "PLAN MODE is on" in prompt
    assert "you have no tools that change anything" in prompt


def test_both_voice_personas_include_reporting_without_losing_spoken_rules() -> None:
    for prompt in (load_persona_prompt(), load_compact_persona_prompt()):
        assert "REPORTING RESULTS" in prompt
        assert "SPOKEN" in prompt
        assert "spell every number" in prompt


@pytest.mark.parametrize("briefed", [True, False])
def test_society_api_turn_carries_the_reply_policy_exactly_once(briefed: bool) -> None:
    from types import SimpleNamespace

    from dodaios.brain.manager import _TURN_OVERRIDE, BrainManager
    from dodaios.brain.turn_override import TurnOverride

    briefing = "## How to reply to the person\n" + CONVERSATIONAL_RESPONSE_STYLE
    manager = BrainManager.__new__(BrainManager)
    manager._config = SimpleNamespace(performance=SimpleNamespace(cache_optimized_prompt=True))
    manager._render_live_tool_block = lambda: "TOOLS"
    manager._reply_language_directive = lambda: "LANGUAGE"
    token = _TURN_OVERRIDE.set(
        TurnOverride(
            provider="test",
            system_extra=briefing if briefed else "## Agent\nScout",
            tool_context={"tool_origin": "society"},
        )
    )
    try:
        prompt = manager._build_system_prompt()
    finally:
        _TURN_OVERRIDE.reset(token)
    assert prompt.count(CONVERSATIONAL_RESPONSE_STYLE) == 1
    assert "WRITTEN CHAT STYLE" in prompt


# ---- charts in a written answer ------------------------------------------------


def test_the_assistant_learns_the_chart_block_on_both_seats() -> None:
    from dodaios.core.response_style import CHART_FENCE, CHART_GUIDANCE

    assert f"`{CHART_FENCE}`" in CHART_GUIDANCE
    # The CLI seat's preamble and the brain's written style: the assistant's own chat.
    assert CHART_GUIDANCE in dodaios_harness.SYSTEM_PREAMBLE
    assert CHART_GUIDANCE in _WRITTEN_CHAT_STYLE
    # A coding thread acts as in a terminal, and a voice never reads a chart aloud.
    assert CHART_GUIDANCE not in dodaios_harness.CODING_PREAMBLE
    for prompt in (load_persona_prompt(), load_compact_persona_prompt()):
        assert CHART_GUIDANCE not in prompt
    for phrase in (
        "never from memory or an estimate",
        "No chart for a single number",
        "The text must make sense without the chart",
    ):
        assert phrase in CHART_GUIDANCE, phrase


def test_the_chart_example_in_the_prompt_is_a_chart_the_chat_can_draw() -> None:
    import json

    from dodaios.core.response_style import CHART_GUIDANCE

    start = CHART_GUIDANCE.index("{")
    example, _end = json.JSONDecoder().raw_decode(CHART_GUIDANCE[start:])
    assert example["type"] in {"line", "area", "column", "bar"}
    assert len(example["x"]) >= 3
    assert all(len(series["data"]) == len(example["x"]) for series in example["series"])
    assert {"title", "unit", "note", "value", "delta"} <= set(example)


def test_the_chart_fence_name_is_the_one_the_chat_draws() -> None:
    import re

    from dodaios.core.response_style import CHART_FENCE

    root = Path(__file__).resolve().parents[3]
    source = (root / "dodaios/ui/web/frontend/src/lib/chartSpec.ts").read_text(encoding="utf-8")
    match = re.search(r'export const CHART_FENCE = "([^"]+)"', source)
    assert match is not None and match.group(1) == CHART_FENCE


def test_a_surface_that_cannot_draw_gets_the_reply_without_its_charts() -> None:
    from dodaios.core.response_style import without_charts

    spec = '{"type": "line", "x": ["a", "b"], "series": [{"name": "s", "data": [1, 2]}]}'
    block = f"```chart\n{spec}\n```"
    assert without_charts(f"It rose to 142.\n\n{block}\n\nShall I watch it?") == (
        "It rose to 142.\n\nShall I watch it?"
    )
    # A block cut off before its closing fence goes too; other code stays.
    assert without_charts('It rose.\n\n```chart\n{"type": "li') == "It rose."
    code = "Run this:\n\n```bash\nls\n```"
    assert without_charts(code) == code
    plain = "A chart of the course would help."
    assert without_charts(plain) == plain
    assert without_charts("") == ""
