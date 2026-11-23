"""Every fixed text Dodaios hands to a model, rendered with a neutral fixture.

One entry per text. ``tests/unit/model_texts/test_model_text_snapshots.py``
compares each to ``tests/snapshots/model_texts/<name>.txt``, so a change to what a
model reads shows up as a diff in the pull request, and a growth of more than 10 %
fails until the summary is regenerated on purpose.
"""
from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: A neutral stand-in for a person's standing brief wishes.
FIXTURE_WISHES = "Write briefs in English.\nName the project folder in every brief."


def _lead_system_prompt() -> str:
    """The lead's system prompt layers (soul, persona, doctrine, ecosystem map) for a lead turn."""
    from dodaios.brain.lead_doctrine import LEAD_TURN
    from dodaios.brain.manager import BrainManager
    from dodaios.core.config import load_config

    manager = BrainManager.__new__(BrainManager)
    manager._soul = None
    manager._user_profile = None
    manager._people = None
    manager._core_memory = None
    manager._system_prompt_extra = ""
    manager._memory_context_suffix = ""
    manager._reply_language = "auto"
    cfg = load_config()
    cfg.performance.cache_optimized_prompt = False
    manager._config = cfg
    token = LEAD_TURN.set(True)
    try:
        return manager._build_system_prompt()
    finally:
        LEAD_TURN.reset(token)


def _harness():
    return importlib.import_module("dodaios.agent_chat.dodaios_harness")


def _lead_message_lines() -> str:
    """The lines on every lead message, in the order the CLI runner appends them."""
    h = _harness()
    return h.EFFORT_LINE + h.FIRST_LINE + h.REPLY_SHAPE_LINE + h.brief_line() + h.QUESTION_CARD_LINE


def _brief_line_with_wishes() -> str:
    from dodaios.core.brief_wishes import wishes_line

    return _harness().BRIEF_LINE + wishes_line(FIXTURE_WISHES)


def _wishes_prompt_block() -> str:
    from dodaios.core.brief_wishes import prompt_block

    return prompt_block(FIXTURE_WISHES)


def _delegation_brief_texts() -> str:
    from dodaios.core import agent_brief

    return "\n\n".join(
        f"[{name}]\n{getattr(agent_brief, name)}"
        for name in ("SHIP_DEFAULT", "REAL_LIMITS", "AGENT_BRIEF_RULE")
    )


def _node_texts() -> str:
    from dodaios.plugins.tool import node

    return f"[WORK_METHOD]\n{node.WORK_METHOD}\n\n[BUILD_IN_STEPS]\n{node.BUILD_IN_STEPS}"


def _lead_catalog() -> list[dict]:
    from tests.eval.lead_routing import build_lead_catalog

    return build_lead_catalog().offered()


def _tool_descriptions() -> str:
    return "\n\n".join(f"{t['name']}\n{t['description']}" for t in _lead_catalog())


def _tool_schemas() -> str:
    return "\n".join(
        f"{t['name']} {json.dumps(t['input_schema'], sort_keys=True, ensure_ascii=False)}"
        for t in _lead_catalog()
    )


def _text(module: str, attr: str) -> Callable[[], str]:
    def render() -> str:
        return str(getattr(importlib.import_module(module), attr))

    return render


def _file(rel: str) -> Callable[[], str]:
    return lambda: (REPO / rel).read_text(encoding="utf-8")


H = "dodaios.agent_chat.dodaios_harness"

#: name -> renderer. The name is the snapshot file name.
TEXTS: dict[str, Callable[[], str]] = {
    # The lead's system prompt and the blocks inside it.
    "lead_system_prompt": _lead_system_prompt,
    "lead_doctrine": _text("dodaios.brain.lead_doctrine", "LEAD_DOCTRINE"),
    "lead_persona": _file("dodaios/brain/DODAIOS_PERSONA.md"),
    # What the CLI seat gets beside that prompt.
    "chat_system_preamble": _text(H, "SYSTEM_PREAMBLE"),
    "chat_coding_preamble": _text(H, "CODING_PREAMBLE"),
    "chat_society_preamble": _text(H, "SOCIETY_PREAMBLE"),
    # Per-message lines on every lead message.
    "lead_message_lines": _lead_message_lines,
    "line_effort": _text(H, "EFFORT_LINE"),
    "line_first": _text(H, "FIRST_LINE"),
    "line_reply_shape": _text(H, "REPLY_SHAPE_LINE"),
    "line_brief": _text(H, "BRIEF_LINE"),
    "line_brief_with_wishes": _brief_line_with_wishes,
    "line_question_card": _text(H, "QUESTION_CARD_LINE"),
    "line_secret_field": _text(H, "SECRET_FIELD_LINE"),
    # Agent briefs.
    "agent_brief_rule": _delegation_brief_texts,
    "agent_brief_skill": _file("dodaios/skills/builtin/agent-brief/SKILL.md"),
    "agent_brief_wishes_block": _wishes_prompt_block,
    # Node guides.
    "node_method": _node_texts,
    # The lead's tool catalog.
    "lead_tool_descriptions": _tool_descriptions,
    "lead_tool_schemas": _tool_schemas,
}
