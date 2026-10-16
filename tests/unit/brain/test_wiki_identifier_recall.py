"""Recall of pages named by a multi-token identifier ("Orion Deck 7").

A question naming a project with a short initialism or a number lost exactly
those tokens to the keyword length floor, and meta words ("memory", "answer
in one word") filled the keyword slots and the coverage denominator. The
correct page ranked first lexically and the relevance gate still dropped it.

These tests drive the real injector over a real FTS5 index of a fixture
vault, so extraction, the MATCH expression, the gate and reindexing are all
exercised together.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.brain.wiki_context import WikiContextInjector, _extract_keywords
from jarvis.brain.wiki_relevance import relevant_hits
from jarvis.memory.wiki import fts_index
from jarvis.memory.wiki.search import VaultSearch

BASE_PROMPT = "You are Personal Jarvis."

DE_META_QUESTION = (
    "Laut meinem Gedächtnis: antworte mit einem Wort, "  # i18n-allow: German test input
    "welche Sprache nutzt Lisbon?"  # i18n-allow: German test input
)
DE_IDENTIFIER_QUESTION = (
    "Welche Programmiersprache bevorzuge ich "  # i18n-allow: German test input
    "laut Gedächtnis für QX Orion 7?"  # i18n-allow: German test input
)
DE_META_WORDS = {
    "gedächtnis",  # i18n-allow: German test input
    "antworte",
    "wort",
    "laut",
}  # i18n-allow: German user input under test

PAGES = {
    "QX-Orion-7-Setup.md": (
        "---\ntype: project\n---\n# QX Orion 7 setup\n"
        "The QX Orion 7 codebase is written in Rust. Builds run nightly.\n"
    ),
    "Garden.md": (
        "---\ntype: concept\n---\n# Garden\n"
        "Tomatoes are watered every morning; the orion lily blooms in June.\n"
    ),
    "Kestrel-Runbook.md": "# Pager duty\nEscalate after fifteen minutes of silence.\n",
    "Travel.md": "---\ntype: concept\n---\n# Travel\nThe next trip goes to Lisbon by train.\n",
}


@pytest.fixture
def vault(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    root = tmp_path / "vault"
    root.mkdir()
    for rel, body in PAGES.items():
        (root / rel).write_text(body, encoding="utf-8")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    fts_index.ensure_schema(conn)
    fts_index.index_vault(root, conn)
    return root, conn


def _injector(root: Path, conn: sqlite3.Connection) -> WikiContextInjector:
    return WikiContextInjector(
        search=VaultSearch(root, conn=conn), latency_budget_ms=2000, min_keyword_length=3
    )


async def _ask(root: Path, conn: sqlite3.Connection, text: str) -> str:
    return await _injector(root, conn).maybe_inject(user_text=text, system_prompt=BASE_PROMPT)


def test_identifier_run_survives_the_length_floor() -> None:
    keywords = _extract_keywords("Which language does my QX Orion 7 project use?", min_length=3)
    assert keywords[0] == "QX-Orion-7"
    assert "Orion" not in keywords


def test_a_single_capitalized_word_is_no_identifier() -> None:
    assert not any("-" in k for k in _extract_keywords("Where is Lisbon station?", min_length=3))


def test_meta_words_take_no_keyword_slot() -> None:
    keywords = _extract_keywords(
        DE_META_QUESTION,
        min_length=3,
    )
    assert {k.lower() for k in keywords}.isdisjoint(DE_META_WORDS)


def test_identifier_in_hit_passes_coverage() -> None:
    class Hit:
        title, snippet, frontmatter, score = "QX Orion 7 setup", "written in Rust", "", 1.0

    # Only the identifier matches; the other content words are in another language.
    hit = Hit()
    assert relevant_hits([hit], "QX-Orion-7 Programmiersprache bevorzugt") == [hit]


def test_identifier_must_match_whole() -> None:
    class Hit:
        title, snippet, frontmatter, score = "Garden", "the orion lily blooms", "", 1.0

    assert relevant_hits([Hit()], "QX-Orion-7 Programmiersprache bevorzugt") == []


@pytest.mark.asyncio
async def test_exact_identifier_question_in_another_language(vault) -> None:
    root, conn = vault
    result = await _ask(root, conn, DE_IDENTIFIER_QUESTION)
    assert "Rust" in result


@pytest.mark.asyncio
async def test_filename_question(vault) -> None:
    root, conn = vault
    assert "Rust" in await _ask(root, conn, "What does my QX-Orion-7-Setup note say?")


@pytest.mark.asyncio
async def test_paraphrase_in_page_language(vault) -> None:
    root, conn = vault
    assert "Rust" in await _ask(root, conn, "Which language is my Orion codebase written in?")


@pytest.mark.asyncio
async def test_unrelated_question_injects_nothing(vault) -> None:
    root, conn = vault
    assert await _ask(root, conn, "What is the tallest tower in the world?") == BASE_PROMPT


@pytest.mark.asyncio
async def test_update_and_delete_reach_the_index(vault) -> None:
    root, conn = vault
    page = root / "QX-Orion-7-Setup.md"
    page.write_text(
        "---\ntype: project\n---\n# QX Orion 7 setup\nThe QX Orion 7 codebase moved to Zig.\n",
        encoding="utf-8",
    )
    fts_index.upsert_page(conn, root, page)
    result = await _ask(root, conn, "Which language does my QX Orion 7 project use?")
    assert "Zig" in result and "Rust" not in result

    fts_index.remove_page(conn, root, page)
    page.unlink()
    result = await _ask(root, conn, "Which language does my QX Orion 7 project use?")
    assert "Zig" not in result


@pytest.mark.asyncio
async def test_word_only_in_the_filename_is_found(vault) -> None:
    root, conn = vault
    assert "fifteen minutes" in await _ask(root, conn, "What does my Kestrel runbook say?")


LONG_PAGE = (
    "# Vega Loom 4 bootstrap\n"
    "Vega Loom 4 is the second iteration of the loom tooling.\n"
    + "".join(f"Setup step {n}: copy the template folder and check the paths.\n" for n in range(12))
    + "Vega Loom 4 code is preferred in Kotlin across all modules.\n"
)


@pytest.fixture
def long_vault(vault) -> tuple[Path, sqlite3.Connection]:
    root, conn = vault
    page = root / "Vega-Loom-4-Bootstrap.md"
    page.write_text(LONG_PAGE, encoding="utf-8")
    fts_index.upsert_page(conn, root, page)
    return root, conn


def test_excerpt_carries_the_deep_matching_line(long_vault) -> None:
    root, conn = long_vault
    hits = VaultSearch(root, conn=conn).search("Vega-Loom-4 Programmiersprache", k=5)
    assert hits and hits[0].path.name == "Vega-Loom-4-Bootstrap.md"
    snippet = hits[0].snippet
    assert "Kotlin" in snippet
    assert "Setup step" not in snippet
    assert len(snippet) <= 600


@pytest.mark.asyncio
async def test_injection_carries_the_answer_line_not_the_page_start(long_vault) -> None:
    root, conn = long_vault
    result = await _ask(
        root,
        conn,
        "Welche Programmiersprache ist laut Gedächtnis "  # i18n-allow: German test input
        "für Vega Loom 4 bevorzugt?",  # i18n-allow: German test input
    )
    assert "Kotlin" in result
    assert "Setup step" not in result
