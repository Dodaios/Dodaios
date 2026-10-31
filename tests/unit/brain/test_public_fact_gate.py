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


# --- the system-run search ----------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from dodaios.brain.public_fact_gate import (  # noqa: E402
    prefetch_public_fact_evidence,
    search_has_evidence,
)

_RESULTS = {
    "status": "ok",
    "query": "train Espagne",
    "results": [{
        "title": "Collision ferroviaire de Los Yébenes",  # i18n-allow: real 2026-10-28 result
        "snippet": "Deux trains sont entrés en collision le 28 octobre 2026.",  # i18n-allow
        "url": "https://fr.wikipedia.org/wiki/Collision_ferroviaire_de_Los_Yébenes",
    }],
}


class _Gateway:
    def __init__(self, output=None, *, tools=("search_web",), delay=0.0, fail=False):
        self.output = _RESULTS if output is None else output
        self.tools = tools
        self.delay = delay
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def catalog(self):
        return [SimpleNamespace(name=name) for name in self.tools]

    async def execute(self, name, args, request):
        import asyncio

        self.calls.append((name, args))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("backend down")
        return SimpleNamespace(success=True, output=self.output)


@pytest.mark.asyncio
async def test_prefetch_returns_the_results_as_text() -> None:
    gateway = _Gateway()
    text = await prefetch_public_fact_evidence("train Espagne", gateway=gateway)
    assert text is not None and "Los Yébenes" in text
    assert gateway.calls == [("search_web", {"query": "train Espagne", "max_results": 5})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gateway",
    [
        _Gateway(tools=("wiki_recall",)),
        _Gateway(output={"status": "ok", "results": []}),
        _Gateway(fail=True),
        _Gateway(delay=0.5),
    ],
    ids=["no-search-tool", "no-results", "failure", "timeout"],
)
async def test_prefetch_degrades_to_none(gateway: _Gateway) -> None:
    assert await prefetch_public_fact_evidence("q", gateway=gateway, timeout_s=0.1) is None


def test_evidence_test_matches_the_realtime_rule() -> None:
    assert search_has_evidence(_RESULTS)
    assert not search_has_evidence({"status": "error", "results": [{"a": 1}]})
    assert not search_has_evidence("text")


@pytest.mark.asyncio
async def test_local_turn_answers_from_the_system_search(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    grounded = "Selon Wikipédia, deux trains sont entrés en collision à Los Yébenes."  # i18n-allow
    m = _manager("local-openai", grounded, executed=set())  # the model itself called no tool
    out = await m.generate(
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        trace_id=uuid4(),
        use_history=False,
    )
    assert gateway.calls, "the system ran the search"
    assert "Los Yébenes" in m._evidence_directive
    assert "untrusted data" in m._evidence_directive
    assert out == grounded


@pytest.mark.asyncio
async def test_system_search_does_not_excuse_an_unbacked_action(monkeypatch) -> None:
    from dodaios.brain.action_honesty import action_not_started_phrase
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    claimed = "I have opened Chrome for you."
    m = _manager("local-openai", claimed, executed=set())
    out = await m.generate(
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        trace_id=uuid4(),
        use_history=False,
    )
    assert gateway.calls, "the system ran the search"
    assert "opened Chrome" not in out
    assert out == action_not_started_phrase("fr")


@pytest.mark.asyncio
async def test_failed_system_search_keeps_the_honest_backstop(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: _Gateway(fail=True))
    m = _manager("local-openai", _INVENTED, executed=set())
    out = await m.generate(
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: live
        trace_id=uuid4(),
        use_history=False,
    )
    assert out == public_fact_unfulfilled_answer("fr")


# --- vague questions ------------------------------------------------------------

from dodaios.brain.public_fact_gate import (  # noqa: E402
    public_fact_clarifying_question,
    public_fact_search_query,
)
from dodaios.core.protocols import BrainMessage  # noqa: E402


def test_a_question_with_a_subject_is_searched_as_asked() -> None:
    text = "quelle est la terniere tragedie en espagne"  # i18n-allow: live, with its typo
    assert public_fact_search_query(text) == text


def test_a_generic_event_borrows_its_subject_from_the_last_turns() -> None:
    query = public_fact_search_query(
        "tu as pas vu un accident",  # i18n-allow: live utterance
        ("et en espagne", "regarde ce qui s'est passé avec le train aujourd'hui"),  # i18n-allow
    )
    assert query == "accident espagne train"


def test_a_generic_event_without_context_is_too_vague_to_search() -> None:
    assert public_fact_search_query("tu as pas vu un accident") is None  # i18n-allow: live
    assert public_fact_search_query("did you see an accident?") is None


@pytest.mark.asyncio
async def test_vague_question_gets_a_question_not_a_claim(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    m = _manager("local-openai", "Aucun accident n'a été signalé aujourd'hui.", set())  # i18n-allow
    out = await m.generate("tu as pas vu un accident", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert not gateway.calls, "nothing to search for"
    assert out == public_fact_clarifying_question("fr")


@pytest.mark.asyncio
async def test_vague_question_is_asked_back_in_the_conversation_language(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: _Gateway())
    m = _manager("local-openai", "What was the accident about?", set())  # live: English
    out = await m.generate("tu as pas vu un accident", trace_id=uuid4(), use_history=False)  # i18n-allow
    assert out == public_fact_clarifying_question("fr")


class _FlakyGateway(_Gateway):
    """Empty page first, results second: the free backend's real behaviour."""

    async def execute(self, name, args, request):
        self.calls.append((name, args))
        output = {"status": "empty", "results": []} if len(self.calls) == 1 else _RESULTS
        return SimpleNamespace(success=True, output=output)


@pytest.mark.asyncio
async def test_prefetch_retries_an_empty_page_once() -> None:
    gateway = _FlakyGateway()
    text = await prefetch_public_fact_evidence("train Espagne", gateway=gateway)
    assert text is not None and len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_vague_follow_up_searches_with_the_conversation_subject(monkeypatch) -> None:
    from dodaios.core import runtime_refs

    gateway = _Gateway()
    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: gateway)
    grounded = "Selon Wikipédia, deux trains sont entrés en collision à Los Yébenes."  # i18n-allow
    m = _manager("local-openai", grounded, set())
    history = [
        BrainMessage(role="user", content="regarde ce qui s'est passé avec le train aujourd'hui"),  # i18n-allow
        BrainMessage(role="assistant", content="Je regarde."),  # i18n-allow
        BrainMessage(role="user", content="et en espagne"),  # i18n-allow
        BrainMessage(role="assistant", content="D'accord."),  # i18n-allow
    ]
    out = await m.generate(
        "tu as pas vu un accident", trace_id=uuid4(), use_history=False,  # i18n-allow
        history_override=history,
    )
    assert gateway.calls[0][1]["query"] == "accident espagne train"
    assert out == grounded
