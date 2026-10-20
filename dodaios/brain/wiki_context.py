"""Wiki context injector for the brain system prompt.

Performs a fast, latency-bounded vault search before each brain turn and
prepends the surviving snippets to the system prompt as a framed personal-memory
section.  If the relevance gate declines the turn, if the search exceeds the
latency budget, if no useful keywords can be extracted from the user text, or if
nothing retrieved is relevant enough, the original system prompt is returned
unchanged.

Relevance contract (``dodaios.brain.wiki_relevance``):
    Retrieval has no null element — a keyword search always returns a ranked
    list, and "best match" never means "good match".  Injecting whatever came
    back is what welds unrelated personal facts onto general-knowledge answers.
    Three gates, in order:

    1. BEFORE searching, ``should_consult_memory`` skips only fragments too
       short to mean anything. Every other turn searches (retrieval-first —
       the vault query is local and single-digit milliseconds); the verdict
       instead grades HOW STRICT gate 2 must be: recollection / planning /
       personal turns keep the standard coverage bar, world-shaped and
       anchor-less turns must clear the strict bar before anything rides
       along. The 2026-08-04 recall audit found the old refuse-to-search
       default produced two full live days without one injected turn.
    2. AFTER searching, ``relevant_hits`` drops hits that merely share a common
       word with the question (strict verdicts: hits must cover nearly the
       whole question).
    3. AT injection, ``frame_context_block`` states that the notes may be
       irrelevant and that the model must ignore them if so.

    When the gates decline a turn the knowledge is not lost: the router brain
    holds the ``wiki-recall`` tool and can look something up deliberately.

Semantic search (optional, off unless the user switched it on):
    The word search finds a page by the words it shares with the question. A
    question phrased differently from the note, or asked in another language,
    shares none. With semantic search active the injector also asks for pages
    that MEAN something close to the whole question and appends the ones the
    word search did not already bring. The two legs are independent: the word
    search runs exactly as it does without semantic search, a slow or broken
    semantic leg costs the turn nothing but its own hits, and a turn with no
    personal anchor (the strict verdict) gets no semantic hits at all, because
    for this kind of search a "nearest page" exists for every question.

Latency contract:
    The whole ``maybe_inject`` coroutine must complete in <= ``latency_budget_ms``
    milliseconds.  It uses ``asyncio.wait_for`` to enforce this.  A slow vault
    (cold filesystem, network FS, etc.) therefore cannot block the voice path.
    The relevance gate itself is regex-only and IO-free (AP-9/AP-11).

Fallback contract:
    When ``search`` is ``None`` (Agent B not yet merged) the injector silently
    does nothing.  Pass ``search=None`` from the factory; every
    ``maybe_inject`` call returns the prompt unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dodaios.memory.wiki.search import VaultSearch

from dodaios.brain.wiki_relevance import (
    DEFAULT_MIN_COVERAGE,
    DEFAULT_MIN_RELATIVE_SCORE,
    DEFAULT_STRICT_MIN_COVERAGE,
    fold_text,
    frame_context_block,
    relevant_hits,
    should_consult_memory,
)
from dodaios.brain.wiki_relevance_vocab import STOPWORDS
from dodaios.memory.wiki.telemetry import telemetry

log = logging.getLogger(__name__)

#: Similarity a page must reach to ride along on a turn nobody asked it into.
#: Measured on a real vault with the multilingual model: questions about the
#: user's own notes score 0.45 to 0.65 against the right page, while unrelated
#: questions with a personal ring ("tell me a joke") stay below 0.40.
SEMANTIC_MIN_SCORE = 0.42

#: A further semantic hit must come close to the best one of the same turn.
SEMANTIC_RELATIVE_FLOOR = 0.85

#: Pages the semantic leg may add to one turn.
SEMANTIC_MAX_HITS = 3

# Tokenize on whitespace and common punctuation
_TOKEN_RE = re.compile(r"[^\w\s]|\s+", re.UNICODE)


def _extract_keywords(
    text: str,
    *,
    min_length: int = 3,
    max_keywords: int = 4,
) -> list[str]:
    """Extract up to ``max_keywords`` meaningful keywords from an utterance.

    Strategy:
    1. Tokenize on whitespace + punctuation.
    2. Drop tokens shorter than ``min_length``. Three is the floor the
       2026-08-11 recall audit set: short given names ("Joy", "Uwe") and
       initialisms ("BMW") are exactly the tokens a memory question hangs
       on, and the old floor of four made them structurally unsearchable.
    3. Drop tokens that are in the stopword list (case-insensitive).
    4. Prefer tokens that are capitalized mid-sentence (proper nouns in
       English; nouns in general in German — both are the searchable
       content words), but include lowercase tokens too if there are not
       enough capitalized ones. All-lowercase STT output simply keeps
       source order.
    5. Return up to ``max_keywords`` tokens, capitalized ones first.
    """
    raw_tokens = _TOKEN_RE.sub(" ", text).split()

    # Filter by length and stopwords. The stopword register is PRE-FOLDED
    # ("fuer", "ueber"), so the token must be folded the  # i18n-allow: folded stopword forms
    # same way before the lookup — comparing ``tok.lower()`` let every real
    # umlaut spelling through as a junk keyword.  # i18n-allow: folded stopword forms
    candidates: list[str] = []
    for tok in raw_tokens:
        if len(tok) < min_length:
            continue
        if fold_text(tok) in STOPWORDS:
            continue
        candidates.append(tok)

    if not candidates:
        return []

    # Prefer proper nouns (capitalized, not first word of utterance)
    first_word = raw_tokens[0] if raw_tokens else ""
    proper_nouns = [
        t for t in candidates
        if t[0].isupper() and t != first_word
    ]
    others = [t for t in candidates if t not in proper_nouns]

    # Merge: proper nouns first, then others; deduplicate (preserve order)
    seen: set[str] = set()
    ordered: list[str] = []
    for t in proper_nouns + others:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(t)

    return ordered[:max_keywords]


class WikiContextInjector:
    """Latency-bounded wiki-snippet injector for the system prompt.

    Construction is cheap; one instance is reused for the lifetime of the
    BrainManager.  The injector is a no-op when ``search`` is ``None`` (used
    when Agent B's work is not yet merged — fallback path).

    Usage::

        injector = WikiContextInjector(search=vault_search)
        augmented = await injector.maybe_inject(
            user_text="When was Harald born?",
            system_prompt=base_prompt,
        )

    Log line (INFO, exactly one per call)::

        WikiContextInjector injected=True hits=2 latency_ms=14
    """

    def __init__(
        self,
        *,
        search: VaultSearch | None,
        semantic_search: Callable[[], Any] | None = None,
        max_chars: int = 12_000,
        latency_budget_ms: int = 150,
        min_keyword_length: int = 4,
        relevance_gate: bool = True,
        min_coverage: float = DEFAULT_MIN_COVERAGE,
        strict_min_coverage: float = DEFAULT_STRICT_MIN_COVERAGE,
        min_relative_score: float = DEFAULT_MIN_RELATIVE_SCORE,
    ) -> None:
        # 150 ms (was 80): the vault leg opens its SQLite connection lazily
        # INSIDE the budget, so the first qualifying turn of a process paid
        # the open+schema check against 80 ms and logged reason=timeout.
        # The factory warms the connection in the background at boot; the
        # wider budget covers the cold path when that race is lost, and is
        # far below anything audible next to a multi-second brain call.
        self._search = search
        # A provider, not an instance: the user can switch semantic search on
        # or off while the app runs, and the injector must follow without
        # being rebuilt. It returns ``None`` while the feature is off.
        self._semantic_search = semantic_search
        self._max_chars = max_chars
        self._latency_budget_ms = latency_budget_ms
        self._min_keyword_length = min_keyword_length
        # Escape hatch: ``relevance_gate=False`` restores the pre-gate
        # behaviour (search every turn, inject every hit). Kept so a user who
        # believes the gate is too strict can prove it from config rather than
        # by patching code — the defaults stay on.
        self._relevance_gate = relevance_gate
        self._min_coverage = min_coverage
        self._strict_min_coverage = strict_min_coverage
        self._min_relative_score = min_relative_score

    def _miss(self, t0: float, reason: str) -> None:
        """Record one skipped injection: telemetry + the single INFO line."""
        telemetry.inc("wiki_context_misses")
        # Per-reason counter so "which gate eats the injections" is a
        # /api/wiki/telemetry read instead of a log grep (2026-08-11 audit:
        # the aggregate counter could not distinguish no_hits from a strict
        # gate discard). Reasons are the stable slugs of MemoryVerdict plus
        # this module's own literals — bounded vocabulary, safe as names.
        telemetry.inc(f"wiki_context_miss_{reason}")
        log.info(
            "WikiContextInjector injected=False hits=0 latency_ms=%d reason=%s",
            int((time.monotonic() - t0) * 1000),
            reason,
        )

    async def maybe_inject(
        self,
        *,
        user_text: str,
        system_prompt: str,
    ) -> str:
        """Return system_prompt unchanged on any of:

        * no memory at all (``search is None``)
        * no extractable keywords from ``user_text``
        * the retrieval exceeds its latency budget
        * retrieval returns zero hits
        * nothing survives the relevance gates

        Otherwise returns::

            system_prompt + "\\n\\n## Wiki context\\n" + merged_snippets

        with up to ``max_chars`` of merged snippets, each prefixed by its
        page title.

        Logs exactly one line per call at INFO::

            WikiContextInjector injected=<bool> hits=<n> latency_ms=<int> …
        """
        t0 = time.monotonic()

        # Fast-path: no memory available at all (Agent B not merged yet)
        if self._search is None:
            self._miss(t0, "no_search")
            return system_prompt

        # Gate 1 (pre-retrieval): retrieval-first — only fragments too short
        # to mean anything skip the search. The verdict's job is grading gate
        # 2: a recollection/planning/personal turn keeps the standard
        # coverage bar, a world-shaped or anchor-less turn must clear the
        # strict one. Regex-only either way (AP-9).
        strict = False
        verdict_reason = "gate_off"
        if self._relevance_gate:
            verdict = should_consult_memory(user_text)
            if not verdict.consult:
                self._miss(t0, verdict.reason)
                return system_prompt
            strict = verdict.strict
            verdict_reason = verdict.reason

        # Extract keywords
        keywords = _extract_keywords(
            user_text,
            min_length=self._min_keyword_length,
        )
        semantic = self._semantic_for_turn(strict)
        if not keywords and semantic is None:
            self._miss(t0, "no_keywords")
            return system_prompt

        query = " ".join(keywords)
        budget_ms = self._latency_budget_ms
        # Started before the word search is awaited so both run side by side
        # inside the one budget. It embeds the whole question, not keywords.
        semantic_task = (
            asyncio.ensure_future(_run_semantic(semantic, user_text))
            if semantic is not None
            else None
        )

        try:
            hits: list = []
            miss_reason = "no_keywords"
            if keywords:
                # Run search with a strict latency budget
                try:
                    retrieval = _run_search(self._search, query)
                    hits = await asyncio.wait_for(
                        retrieval,
                        timeout=budget_ms / 1000.0,
                    )
                except TimeoutError:
                    log.warning(
                        "WikiContextInjector timed out after %dms (budget=%dms) — "
                        "skipping wiki context for this turn",
                        int((time.monotonic() - t0) * 1000),
                        budget_ms,
                    )
                    self._miss(t0, "timeout")
                    return system_prompt
                except Exception:  # noqa: BLE001
                    log.warning(
                        "WikiContextInjector search raised unexpectedly — "
                        "skipping wiki context",
                        exc_info=True,
                    )
                    self._miss(t0, "search_error")
                    return system_prompt

                miss_reason = "no_hits"
                # Gate 2 (post-retrieval): the index matches on ANY query term, so
                # a page sharing one common word arrives looking just like one
                # that is on topic. Coverage + a within-call relative floor
                # separate them.
                if hits and self._relevance_gate:
                    hits = relevant_hits(
                        hits,
                        query,
                        min_coverage=self._strict_min_coverage
                        if strict
                        else self._min_coverage,
                        min_relative_score=self._min_relative_score,
                    )
                    if not hits:
                        miss_reason = (
                            "no_relevant_hits_strict" if strict else "no_relevant_hits"
                        )

            semantic_hits = await self._semantic_hits(semantic_task, t0, hits)
        finally:
            # Every way out, a cancelled turn included: the lookup must not
            # outlive the turn that asked for it. A finished one ignores this.
            _abandon(semantic_task)
        hits = [*hits, *semantic_hits]
        if not hits:
            self._miss(t0, miss_reason)
            return system_prompt

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Build the context block, capped at max_chars
        context_parts: list[str] = []
        chars_used = 0
        hits_included = 0
        for hit in hits:
            # A page found through a frontmatter alias (the language bridge)
            # has no body snippet by contract — fall back to its leading text
            # so the entry carries content instead of just a bare title.
            text = hit.snippet or getattr(hit, "preview", "") or ""
            title = hit.title or ""
            entry = f"**{title}**: {text}"
            if chars_used + len(entry) + 1 > self._max_chars:
                # Try trimming to fit the remaining budget
                remaining = self._max_chars - chars_used - len(f"**{title}**: ") - 1
                if remaining >= 40:  # only worth including if enough chars remain
                    entry = f"**{title}**: {text[:remaining]}…"
                else:
                    break
            context_parts.append(entry)
            chars_used += len(entry) + 1  # +1 for the newline
            hits_included += 1

        if not context_parts:
            self._miss(t0, "empty_block")
            return system_prompt

        # Gate 3 (at injection): the block carries its own usage contract, so
        # the model knows the notes are a guess and is explicitly allowed to
        # ignore them. A bare context block reads as an instruction to use it.
        augmented = system_prompt + "\n\n" + frame_context_block(context_parts)

        telemetry.inc("wiki_context_hits")
        if semantic_hits:
            telemetry.inc("wiki_context_semantic_hits")
        log.info(
            "WikiContextInjector injected=True hits=%d latency_ms=%d "
            "verdict=%s mode=%s semantic=%d",
            hits_included,
            latency_ms,
            verdict_reason,
            "strict" if strict else "standard",
            len(semantic_hits),
        )
        return augmented

    def _semantic_for_turn(self, strict: bool) -> Any | None:
        """The semantic search to ask this turn, or ``None``.

        A strict verdict means the turn carries no personal anchor. The word
        search may still answer it when a page covers nearly the whole
        question; a similarity score cannot make that distinction, so the
        semantic leg stays out of such turns.
        """
        if self._semantic_search is None or strict:
            return None
        try:
            semantic = self._semantic_search()
        except Exception:  # noqa: BLE001 - an optional engine never breaks a turn
            log.debug("Semantic wiki search is unavailable this turn", exc_info=True)
            return None
        # The two engines must look at the same vault, or a hit would name a
        # page the word search's vault does not have.
        own_root = getattr(self._search, "_root", None)
        other_root = getattr(semantic, "vault_root", None)
        if own_root is not None and other_root is not None and own_root != other_root:
            return None
        return semantic

    async def _semantic_hits(
        self, task: asyncio.Future | None, t0: float, lexical_hits: list
    ) -> list:
        """Semantic hits for pages the word search did not already bring."""
        if task is None:
            return []
        remaining = self._latency_budget_ms / 1000.0 - (time.monotonic() - t0)
        try:
            found = await asyncio.wait_for(task, timeout=max(remaining, 0.005))
        except TimeoutError:
            log.debug("Semantic wiki search missed the turn's budget; skipped")
            return []
        except Exception:  # noqa: BLE001 - the word search result stands on its own
            log.debug("Semantic wiki search failed this turn", exc_info=True)
            return []
        if not found:
            return []
        floor = found[0].score * SEMANTIC_RELATIVE_FLOOR
        # Path objects, not strings: on Windows the same page can arrive in two
        # spellings that differ only in case.
        taken = {getattr(hit, "path", None) for hit in lexical_hits}
        extra: list = []
        for hit in found:
            if hit.score < floor or hit.path in taken:
                continue
            taken.add(hit.path)
            extra.append(hit)
        return extra


async def _run_search(search: VaultSearch, query: str) -> list:
    """Thin async wrapper around VaultSearch.search.

    VaultSearch.search is a synchronous method (file-walking + grep).
    We run it in the default executor to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search.search, query)


async def _run_semantic(search: Any, text: str) -> list:
    """Ask the semantic engine without ever waiting for its model."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: search.search(text, k=SEMANTIC_MAX_HITS, min_score=SEMANTIC_MIN_SCORE),
    )


def _abandon(task: asyncio.Future | None) -> None:
    """Stop waiting for a semantic lookup whose turn already ended."""
    if task is not None:
        task.cancel()
