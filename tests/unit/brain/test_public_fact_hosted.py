"""A hosted model that cannot call tools gets the search run for it.

BC-250 2026-10-29: "Recherche les dernières actualités de la mission Artemis
deux et cite tes sources" reached the print-mode Claude CLI (brain.primary =
claude-cli), which has no tools in this path. No search ran and the answer was
"Je ne peux pas faire de recherche en direct ici". The system-run search of
the on-device path was reserved for local providers, and the CLI prompt kept
none of the system prompt where search results would have been.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from dodaios.brain.app_control import LOCAL_PROVIDERS
from dodaios.brain.manager import BrainManager
from dodaios.brain.public_fact_gate import (
    extract_public_fact_evidence,
    hosted_fresh_fact_query,
    public_fact_evidence_directive,
)
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import BrainDelta, BrainMessage, BrainRequest

from tests.unit.brain.test_public_fact_gate import _Gateway, _ScriptedDispatcher

ARTEMIS = "Recherche les dernières actualités de la mission Artemis deux et Cite Source"  # i18n-allow: live transcript


@pytest.mark.parametrize(
    "text",
    [
        ARTEMIS,
        "Que s'est-il passé en Espagne hier",  # i18n-allow: live transcript
        "Quoi de neuf aujourd'hui sur Artemis II ?",  # i18n-allow: French fixture
        "Recherche les informations sur une collision ferroviaire récente en Espagne",  # i18n-allow
    ],
)
def test_fresh_public_facts_are_searched_for_a_tool_less_hosted_model(text: str) -> None:
    query = hosted_fresh_fact_query(text, provider="claude-cli", local_providers=LOCAL_PROVIDERS)
    assert query


@pytest.mark.parametrize(
    "text",
    [
        "Quelle est la capitale de la Suisse",  # i18n-allow: live transcript
        "Explique simplement le rôle d'un disjoncteur différentiel",  # i18n-allow: live
        "Raconte-moi une longue histoire de science-fiction",  # i18n-allow: live transcript
        "Quel est le modèle que tu utilises actuellement",  # i18n-allow: live transcript
        "combien font 12 fois 7",  # i18n-allow: French fixture
    ],
)
def test_evergreen_self_and_story_turns_are_left_to_the_hosted_model(text: str) -> None:
    assert hosted_fresh_fact_query(text, provider="claude-cli", local_providers=LOCAL_PROVIDERS) is None


def test_local_providers_keep_their_own_stricter_path() -> None:
    assert hosted_fresh_fact_query(ARTEMIS, provider="local-openai", local_providers=LOCAL_PROVIDERS) is None


def test_a_vague_event_without_context_is_not_searched() -> None:
    assert (
        hosted_fresh_fact_query(
            "tu as vu l'accident aujourd'hui ?",  # i18n-allow: French fixture
            provider="claude-cli",
            local_providers=LOCAL_PROVIDERS,
        )
        is None
    )


def test_the_evidence_block_survives_inside_a_larger_system_prompt() -> None:
    block = public_fact_evidence_directive('{"results": [{"title": "NASA"}]}')
    system = f"You are Jarvis.\n\n{block}\n\nUSER STANDING INSTRUCTIONS: be brief."
    assert extract_public_fact_evidence(system) == block
    assert extract_public_fact_evidence("You are Jarvis.") == ""


# --- the whole brain turn ---------------------------------------------------


class _ToolLessBrain:
    name = "claude-cli"
    context_window = 200_000
    supports_tools = False
    supports_vision = False

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(content="ok")
        yield BrainDelta(finish_reason="stop")


def _manager(reply: str, *, brain: object | None = None) -> BrainManager:
    cfg = JarvisConfig()
    cfg.brain.primary = "claude-cli"
    cfg.brain.reply_language = "fr"
    m = BrainManager(config=cfg, bus=EventBus(), tools={"search_web": object()})
    m._build_fallback_chain = lambda _l: [("claude-cli", "")]  # type: ignore[method-assign]
    m._get_brain = lambda _n, _mo: brain or _ToolLessBrain()  # type: ignore[method-assign]
    m._build_dispatcher = (  # type: ignore[method-assign]
        lambda _b, *, tools_override=None: _ScriptedDispatcher(reply, set())
    )
    return m


@pytest.mark.asyncio
async def test_claude_cli_news_turn_gets_real_search_results(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    answer = "Selon la NASA, Artemis II a ramené son équipage le 10 avril."  # i18n-allow
    m = _manager(answer)
    out = await m.generate(ARTEMIS, trace_id=uuid4(), use_history=False)

    assert gateway.calls, "the system called search_web through the tool gateway"
    assert gateway.calls[0][0] == "search_web"
    assert "Web search results" in m._evidence_directive
    assert not m._evidence_required_tool, "a hosted model is not second-guessed"
    assert out == answer


@pytest.mark.asyncio
async def test_claude_cli_evergreen_turn_runs_no_search(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    m = _manager("Berne est la ville fédérale.")  # i18n-allow: French fixture
    await m.generate("Quelle est la capitale de la Suisse", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert not gateway.calls


@pytest.mark.asyncio
async def test_a_failed_search_leaves_the_hosted_answer_alone(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: _Gateway(fail=True))
    honest = "Je n'ai pas pu vérifier l'actualité pour le moment."  # i18n-allow: French fixture
    m = _manager(honest)
    out = await m.generate(ARTEMIS, trace_id=uuid4(), use_history=False)
    assert out == honest
    assert not m._evidence_directive


@pytest.mark.asyncio
async def test_a_hosted_model_with_tools_keeps_its_own_judgement(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    class _ToolBrain(_ToolLessBrain):
        name = "claude-api"
        supports_tools = True

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    m = _manager("ok", brain=_ToolBrain())
    await m.generate(ARTEMIS, trace_id=uuid4(), use_history=False)
    assert not gateway.calls


def _recording_manager(created: list[str]) -> BrainManager:
    """The configured primary differs from the brain the chain really uses."""
    m = _manager("Berne est la ville fédérale.")  # i18n-allow: French fixture
    m._build_fallback_chain = lambda _l: [("chain-brain", "")]  # type: ignore[method-assign]

    def _get_brain(name: str, _model: str | None) -> _ToolLessBrain:
        created.append(name)
        return _ToolLessBrain()

    m._get_brain = _get_brain  # type: ignore[method-assign]
    return m


@pytest.mark.asyncio
async def test_a_turn_with_nothing_to_search_never_probes_the_primary(monkeypatch) -> None:
    # Full unit run 2026-10-29: the capability probe ran before the cheap
    # fresh-fact check, so every turn built the configured primary brain ahead
    # of the fallback chain (test_blind_provider_is_skipped_for_a_screen_turn).
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    created: list[str] = []
    m = _recording_manager(created)
    await m.generate("Quelle est la capitale de la Suisse", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert created and set(created) == {"chain-brain"}, created
    assert not gateway.calls


@pytest.mark.asyncio
async def test_a_fresh_fact_turn_still_probes_and_searches(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    created: list[str] = []
    m = _recording_manager(created)
    await m.generate(ARTEMIS, trace_id=uuid4(), use_history=False)
    assert created[0] == "claude-cli", "the tool-less primary is probed for a news turn"
    assert gateway.calls and gateway.calls[0][0] == "search_web"


# --- the print-mode CLI prompt ----------------------------------------------


def test_the_cli_prompt_carries_the_search_results() -> None:
    from dodaios.plugins.brain.claude_cli import ClaudeCliBrain

    block = public_fact_evidence_directive('{"results": [{"title": "Artemis II splashdown"}]}')
    req = BrainRequest(
        messages=(BrainMessage(role="user", content=ARTEMIS),),
        system=f"You are Jarvis.\n\n{block}\n\nReply in French.",
    )
    _argv, prompt = ClaudeCliBrain().build_invocation(req)
    assert "Artemis II splashdown" in prompt
    assert "A web search was already run" in prompt
    assert prompt.rstrip().endswith("Assistant:")


def test_the_cli_prompt_is_unchanged_without_results() -> None:
    from dodaios.plugins.brain.claude_cli import ClaudeCliBrain

    req = BrainRequest(
        messages=(BrainMessage(role="user", content="Bonjour"),),  # i18n-allow: French fixture
        system="You are Jarvis.",
    )
    _argv, prompt = ClaudeCliBrain().build_invocation(req)
    assert "Web search results" not in prompt
