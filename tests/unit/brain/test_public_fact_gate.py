"""Search mandate for public-fact turns answered by an on-device model.

Live 2026-10-28 on the BC-250: the local Qwen3 1.7B model answered "tu as pas
vu un accident" and "regarde ce qui s'est passe avec le train aujourd'hui"
without any tool call, typed "[used tool search_web]" as text and invented a
story about luxury wagons. The same question to Claude ran a real search.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from dodaios.brain.manager import BrainManager
from dodaios.brain.public_fact_gate import (
    PUBLIC_FACT_DIRECTIVE,
    PUBLIC_FACT_DOMAIN,
    public_fact_answer_unverified,
    public_fact_search_directive,
    public_fact_unfulfilled_answer,
)
from dodaios.brain.streaming import StreamingAggregate
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import BrainDelta, BrainRequest

LOCAL = frozenset({"local-openai", "ollama"})
TOOLS = ("search_web", "wiki_recall")


def _directive(text: str, provider: str = "local-openai", **kwargs: object) -> str | None:
    return public_fact_search_directive(
        text, provider=provider, tool_names=TOOLS, local_providers=LOCAL, **kwargs
    )


# --- the decision -----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "tu as pas vu un accident",  # i18n-allow: live 2026-10-28 utterance
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        "quelle est la terniere tragedie en espagne",  # i18n-allow: live, with its typo
        "quel est le résultat des élections en israel",  # i18n-allow: live utterance
        "what is the latest news about the Madrid trains?",
    ],
)
def test_local_model_public_fact_turns_must_search(text: str) -> None:
    assert _directive(text) == PUBLIC_FACT_DIRECTIVE


@pytest.mark.parametrize(
    "text",
    [
        "raconte-moi une histoire",  # i18n-allow: French speech input under test
        "il est quelle heure ?",  # i18n-allow: French speech input under test
        "qui es-tu ?",  # i18n-allow: French speech input under test
        "quel est ton nom ?",  # i18n-allow: French speech input under test
        "combien font 12 fois 7 ?",  # i18n-allow: French speech input under test
        "Ça marche, on s'arrête au Mcdo",  # i18n-allow: French speech input under test
        "who are you?",
    ],
)
def test_chat_self_clock_and_maths_never_search(text: str) -> None:
    assert _directive(text) is None


def test_hosted_providers_keep_their_own_judgement() -> None:
    assert _directive("tu as pas vu un accident", provider="claude-cli") is None  # i18n-allow
    assert _directive("tu as pas vu un accident", provider="claude-api") is None  # i18n-allow


def test_no_mandate_without_a_live_search_tool() -> None:
    assert (
        public_fact_search_directive(
            "tu as pas vu un accident",  # i18n-allow: live utterance
            provider="local-openai",
            tool_names=("wiki_recall",),
            local_providers=LOCAL,
        )
        is None
    )


def test_directive_asks_for_a_question_when_the_request_is_vague() -> None:
    assert "clarifying question" in PUBLIC_FACT_DIRECTIVE
    assert "[used tool" in PUBLIC_FACT_DIRECTIVE  # forbids typing the marker


# --- the backstop -----------------------------------------------------------


_INVENTED = (
    "[used tool search_web]\nAujourd'hui, le train a été remplacé par des wagons "  # i18n-allow
    "de luxe sur la ligne de Madrid à Barcelone."  # i18n-allow: live invented answer
)


def test_an_unsearched_claim_is_replaced_even_without_figures() -> None:
    assert public_fact_answer_unverified(
        "Deux trains se sont percutés près de Tolède.", executed=set()  # i18n-allow
    )
    assert public_fact_answer_unverified(_INVENTED, executed=set())


def test_a_short_clarifying_question_is_kept() -> None:
    question = "Tu penses à quel accident, et où ?"  # i18n-allow: French clarifying question
    assert not public_fact_answer_unverified(question, executed=set())


def test_a_searched_answer_is_kept() -> None:
    assert not public_fact_answer_unverified(_INVENTED, executed={"search_web"})


def test_unfulfilled_phrase_speaks_the_turn_language() -> None:
    fr = public_fact_unfulfilled_answer("fr")
    assert "recherche" in fr and "inventer" in fr  # i18n-allow: French phrase checks
    assert public_fact_unfulfilled_answer("fr-FR") == fr
    assert "web search" in public_fact_unfulfilled_answer("xx")


# --- the whole brain turn ---------------------------------------------------


class _FakeBrain:
    name = "local-openai"
    context_window = 8192
    supports_tools = True
    supports_vision = False

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        yield BrainDelta(content="ok")
        yield BrainDelta(finish_reason="stop")


class _ScriptedDispatcher:
    def __init__(self, text: str, executed: set[str]) -> None:
        self._text = text
        self._executed = executed

    async def dispatch(self, user_text, *, images=(), history=None, **_kwargs):
        agg = StreamingAggregate()
        agg.text = self._text
        agg.finish_reason = "stop"
        agg.executed_tool_names = set(self._executed)
        return agg


def _manager(primary: str, reply: str, executed: set[str]) -> BrainManager:
    cfg = JarvisConfig()
    cfg.brain.primary = primary
    cfg.brain.reply_language = "fr"
    tools = {"search_web": object()}
    m = BrainManager(config=cfg, bus=EventBus(), tools=tools)
    m._build_fallback_chain = lambda _l: [(primary, "model")]  # type: ignore[method-assign]
    m._get_brain = lambda _n, _mo: _FakeBrain()  # type: ignore[method-assign]
    m._build_dispatcher = (  # type: ignore[method-assign]
        lambda _b, *, tools_override=None: _ScriptedDispatcher(reply, executed)
    )
    return m


@pytest.mark.asyncio
async def test_local_turn_with_invented_search_is_replaced_in_french() -> None:
    m = _manager("local-openai", _INVENTED, executed=set())
    out = await m.generate(
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        trace_id=uuid4(),
        use_history=False,
    )
    assert m._evidence_required_tool == "search_web"
    assert m._evidence_required_domain == PUBLIC_FACT_DOMAIN
    assert "wagons" not in out
    assert out == public_fact_unfulfilled_answer("fr")


@pytest.mark.asyncio
async def test_local_turn_that_really_searched_is_kept() -> None:
    real = "Selon Le Monde, deux trains sont entrés en collision à Los Yébenes."  # i18n-allow
    m = _manager("local-openai", real, executed={"search_web"})
    out = await m.generate(
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        trace_id=uuid4(),
        use_history=False,
    )
    assert out == real


@pytest.mark.asyncio
async def test_hosted_provider_turn_is_untouched() -> None:
    reply = "Deux trains se sont percutés ce matin."  # i18n-allow: French reply fixture
    m = _manager("claude-api", reply, executed=set())
    out = await m.generate(
        "tu as pas vu un accident",  # i18n-allow: live utterance
        trace_id=uuid4(),
        use_history=False,
    )
    assert m._evidence_required_tool != "search_web"
    assert out == reply
