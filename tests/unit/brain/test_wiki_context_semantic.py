"""The turn injector's optional semantic leg.

The word search must behave exactly as it does without semantic search, and a
slow, busy or broken semantic engine may cost a turn nothing but its own hits.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from dodaios.brain.wiki_context import SEMANTIC_MIN_SCORE, WikiContextInjector

BASE_PROMPT = "You are the assistant."
PERSONAL = "What approach do I prefer when validating new connections?"
WORLD = "What is the capital of Australia?"


@dataclass(frozen=True)
class Hit:
    title: str
    snippet: str
    score: float
    path: Path = Path("page.md")
    frontmatter: str = ""
    preview: str = ""


class WordSearch:
    def __init__(self, hits: list[Hit] | None = None) -> None:
        self._hits = hits or []
        self.queries: list[str] = []

    def search(self, query: str, *, k: int = 5) -> list[Hit]:
        self.queries.append(query)
        return list(self._hits[:k])


class MeaningSearch:
    def __init__(self, hits: list[Hit] | None = None, *, delay_s: float = 0.0) -> None:
        self._hits = hits or []
        self._delay_s = delay_s
        self.fail = False
        self.calls: list[tuple[str, int, float]] = []

    def search(self, query: str, *, k: int = 5, min_score: float = 0.0) -> list[Hit]:
        self.calls.append((query, k, min_score))
        if self._delay_s:
            time.sleep(self._delay_s)
        if self.fail:
            raise RuntimeError("native session died")
        return [hit for hit in self._hits if hit.score >= min_score][:k]


STEP_BY_STEP = Hit(
    title="Working style",
    snippet="Tests integrations one concrete step at a time.",
    score=0.61,
    path=Path("concepts/working-style.md"),
)


def _injector(words: WordSearch, meaning: Any, **kwargs: Any) -> WikiContextInjector:
    return WikiContextInjector(
        search=words,  # type: ignore[arg-type]
        semantic_search=(lambda: meaning),
        latency_budget_ms=kwargs.pop("latency_budget_ms", 500),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_a_paraphrased_question_finds_the_note_the_word_search_missed() -> None:
    meaning = MeaningSearch([STEP_BY_STEP])
    result = await _injector(WordSearch(), meaning).maybe_inject(
        user_text=PERSONAL, system_prompt=BASE_PROMPT
    )

    assert "one concrete step at a time" in result
    assert result.startswith(BASE_PROMPT)
    [(query, _k, min_score)] = meaning.calls
    assert query == PERSONAL, "the whole question is embedded, not its keywords"
    assert min_score == SEMANTIC_MIN_SCORE


@pytest.mark.asyncio
async def test_a_question_without_a_personal_anchor_gets_no_semantic_hits() -> None:
    meaning = MeaningSearch([STEP_BY_STEP])
    result = await _injector(WordSearch(), meaning).maybe_inject(
        user_text=WORLD, system_prompt=BASE_PROMPT
    )

    assert result == BASE_PROMPT
    assert meaning.calls == [], "a nearest page exists for every question; it is not asked"


@pytest.mark.asyncio
async def test_switched_off_the_injector_behaves_as_before() -> None:
    words = WordSearch()
    off = WikiContextInjector(
        search=words,  # type: ignore[arg-type]
        semantic_search=lambda: None,
        latency_budget_ms=500,
    )
    assert await off.maybe_inject(user_text=PERSONAL, system_prompt=BASE_PROMPT) == BASE_PROMPT
    assert len(words.queries) == 1, "the word search still ran"


@pytest.mark.asyncio
async def test_word_hits_come_first_and_a_page_is_not_repeated() -> None:
    by_words = Hit(
        title="Connections",
        snippet="approach prefer validating connections: one step at a time",
        score=0.9,
        path=Path("concepts/working-style.md"),
    )
    other = Hit(
        title="Review habits",
        snippet="Reviews every integration before it ships.",
        score=0.58,
        path=Path("concepts/review.md"),
    )
    meaning = MeaningSearch([STEP_BY_STEP, other])

    result = await _injector(WordSearch([by_words]), meaning).maybe_inject(
        user_text=PERSONAL, system_prompt=BASE_PROMPT
    )

    assert result.index("Connections") < result.index("Review habits")
    assert "Working style" not in result, "same page as the word hit"


@pytest.mark.asyncio
async def test_a_distant_second_page_does_not_ride_along() -> None:
    weak = Hit(title="Trip", snippet="Flight to Paris.", score=0.43, path=Path("trip.md"))
    result = await _injector(WordSearch(), MeaningSearch([STEP_BY_STEP, weak])).maybe_inject(
        user_text=PERSONAL, system_prompt=BASE_PROMPT
    )
    assert "Working style" in result
    assert "Trip" not in result


@pytest.mark.asyncio
async def test_a_slow_semantic_engine_does_not_cost_the_turn_its_word_hits() -> None:
    by_words = Hit(
        title="Connections",
        snippet="approach prefer validating connections: one step at a time",
        score=0.9,
        path=Path("concepts/connections.md"),
    )
    slow = MeaningSearch([STEP_BY_STEP], delay_s=0.6)
    injector = _injector(WordSearch([by_words]), slow, latency_budget_ms=150)

    started = time.monotonic()
    result = await injector.maybe_inject(user_text=PERSONAL, system_prompt=BASE_PROMPT)
    elapsed = time.monotonic() - started

    assert "Connections" in result
    assert "Working style" not in result
    assert elapsed < 0.45, "the turn did not wait for the semantic engine"


@pytest.mark.asyncio
async def test_a_failing_semantic_engine_leaves_the_word_search_result_standing() -> None:
    by_words = Hit(
        title="Connections",
        snippet="approach prefer validating connections: one step at a time",
        score=0.9,
        path=Path("concepts/connections.md"),
    )
    broken = MeaningSearch([STEP_BY_STEP])
    broken.fail = True

    result = await _injector(WordSearch([by_words]), broken).maybe_inject(
        user_text=PERSONAL, system_prompt=BASE_PROMPT
    )

    assert "Connections" in result


@pytest.mark.asyncio
async def test_a_provider_that_raises_is_treated_as_switched_off() -> None:
    def provider() -> Any:
        raise RuntimeError("registry not ready")

    injector = WikiContextInjector(
        search=WordSearch(),  # type: ignore[arg-type]
        semantic_search=provider,
        latency_budget_ms=500,
    )
    assert await injector.maybe_inject(user_text=PERSONAL, system_prompt=BASE_PROMPT) == BASE_PROMPT


@pytest.mark.asyncio
async def test_a_semantic_engine_for_another_vault_is_not_asked() -> None:
    words = WordSearch()
    words._root = Path("vault-a")  # type: ignore[attr-defined]
    meaning = MeaningSearch([STEP_BY_STEP])
    meaning.vault_root = Path("vault-b")  # type: ignore[attr-defined]

    result = await _injector(words, meaning).maybe_inject(
        user_text=PERSONAL, system_prompt=BASE_PROMPT
    )

    assert result == BASE_PROMPT
    assert meaning.calls == []


@pytest.mark.asyncio
async def test_a_cancelled_turn_does_not_leave_the_semantic_lookup_running() -> None:
    import asyncio

    class SlowWords(WordSearch):
        def search(self, query: str, *, k: int = 5) -> list[Hit]:
            time.sleep(0.3)
            return []

    injector = _injector(SlowWords(), MeaningSearch([STEP_BY_STEP], delay_s=0.3))
    before = {task for task in asyncio.all_tasks() if not task.done()}

    turn = asyncio.ensure_future(
        injector.maybe_inject(user_text=PERSONAL, system_prompt=BASE_PROMPT)
    )
    await asyncio.sleep(0.05)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn
    await asyncio.sleep(0)

    left = {task for task in asyncio.all_tasks() if not task.done()} - before
    left.discard(asyncio.current_task())
    assert left == set(), "no lookup task outlives the cancelled turn"
