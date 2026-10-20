"""Unit tests for ``dodaios.memory.wiki.prompt`` (Instance D)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.memory.wiki.prompt import (
    build_consolidator_prompt,
    build_system_prompt,
    build_user_prompt,
    compute_vault_summary,
    resolve_user_entity_slug,
    select_top_slugs,
)

# ---------------------------------------------------------------------
# Small in-memory VaultIndex fake — only ``pages_by_type`` is used.
# ---------------------------------------------------------------------


class _Page:
    """Minimal duck-typed page with a slug + page_type."""

    def __init__(self, slug: str, page_type: str) -> None:
        self.slug = slug
        self.page_type = page_type


class _FakeVault:
    """In-memory ``VaultIndex`` substitute for prompt tests."""

    def __init__(self, pages_by_type: dict[str, list[_Page]] | None = None) -> None:
        self._pages = pages_by_type or {}

    def pages_by_type(self, page_type: str) -> list[Any]:
        return list(self._pages.get(page_type, []))


# ---------------------------------------------------------------------
# select_top_slugs
# ---------------------------------------------------------------------


def test_select_top_slugs_empty_source_returns_empty() -> None:
    """A blank source contributes no tokens, so the shortlist is empty."""

    result = select_top_slugs("", ["ruben-luetke", "awareness-layer"])
    assert result == []


def test_select_top_slugs_zero_overlap_returns_empty() -> None:
    """When no candidate slug shares a token with the source, drop them all."""

    result = select_top_slugs("Phase B1 wiki curator", ["unrelated-thing"])
    assert result == []


def test_select_top_slugs_ranks_by_overlap_then_alpha() -> None:
    """Higher overlap wins; ties break alphabetically for deterministic output."""

    source = "ruben pushes the awareness layer for the jarvis-agent bridge"
    candidates = [
        "ruben-luetke",
        "awareness-layer",
        "jarvis-agent-bridge",
        "phase-6",
        "kontrollierer",
    ]
    ranked = select_top_slugs(source, candidates)
    assert "awareness-layer" in ranked
    assert "jarvis-agent-bridge" in ranked
    assert "ruben-luetke" in ranked
    assert "kontrollierer" not in ranked


def test_select_top_slugs_respects_limit() -> None:
    """The hard cap is honoured even when many candidates score."""

    source = " ".join(f"slug{i}" for i in range(30))
    candidates = [f"slug{i}" for i in range(30)]
    result = select_top_slugs(source, candidates, limit=10)
    assert len(result) == 10


def test_select_top_slugs_ignores_stopwords() -> None:
    """Common DE/EN function words don't dominate the ranking."""

    source = "der und die das the and the jarvis-agent bridge"  # i18n-allow: German/English stopword mix, content under test
    candidates = ["der-thing", "jarvis-agent-bridge"]
    result = select_top_slugs(source, candidates)
    assert result and result[0] == "jarvis-agent-bridge"


# ---------------------------------------------------------------------
# compute_vault_summary
# ---------------------------------------------------------------------


def test_compute_vault_summary_empty_vault() -> None:
    """An empty vault yields zero counts and an empty recent-log list."""

    vault = _FakeVault()
    summary = compute_vault_summary(vault)
    assert summary["counts"] == {
        "entity": 0,
        "concept": 0,
        "project": 0,
        "session": 0,
    }
    assert all(slugs == [] for slugs in summary["latest"].values())
    assert summary["recent_log"] == []


def test_compute_vault_summary_counts_and_samples(tmp_path: Path) -> None:
    """Page counts match; ``latest`` is alphabetical and capped at 5 slugs."""

    vault = _FakeVault({
        "entity": [_Page(f"e-{i:02d}", "entity") for i in range(7)],
        "concept": [_Page("awareness-layer", "concept")],
    })
    summary = compute_vault_summary(vault)
    assert summary["counts"]["entity"] == 7
    assert summary["counts"]["concept"] == 1
    assert summary["latest"]["entity"] == ["e-00", "e-01", "e-02", "e-03", "e-04"]
    assert summary["latest"]["concept"] == ["awareness-layer"]


def test_compute_vault_summary_reads_recent_log_entries(tmp_path: Path) -> None:
    """Three most recent ``## [...]`` headings are returned in chronological order."""

    log = tmp_path / "log.md"
    log.write_text(
        "# Wiki Log\n\n"
        "## [2026-05-11 18:00] create | first\n\n- a\n\n"
        "## [2026-05-11 18:30] update | second\n\n- b\n\n"
        "## [2026-05-11 19:00] update | third\n\n- c\n\n"
        "## [2026-05-11 19:30] update | fourth\n\n- d\n",
        encoding="utf-8",
    )
    summary = compute_vault_summary(_FakeVault(), log_path=log)
    assert len(summary["recent_log"]) == 3
    assert summary["recent_log"][-1].startswith("[2026-05-11 19:30]")


def test_compute_vault_summary_missing_log_is_silent(tmp_path: Path) -> None:
    """A non-existent log path degrades to an empty list, no raise."""

    summary = compute_vault_summary(_FakeVault(), log_path=tmp_path / "nope.md")
    assert summary["recent_log"] == []


def test_compute_vault_summary_resilient_to_vault_errors() -> None:
    """A vault that raises on ``pages_by_type`` still yields zero counts."""

    class _BoomVault:
        def pages_by_type(self, page_type: str) -> list[Any]:  # noqa: ARG002
            raise RuntimeError("vault is on fire")

    summary = compute_vault_summary(_BoomVault())
    assert summary["counts"]["entity"] == 0


# ---------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------


def test_build_system_prompt_no_longer_embeds_schema_md() -> None:
    """``schema.md`` is vault documentation; the prompt carries the contract itself."""

    prompt = build_system_prompt(None)
    assert "# Wiki Schema" not in prompt
    assert "Pages: frontmatter type, slug" in prompt


def test_build_system_prompt_appends_output_contract() -> None:
    """The JSON output contract is always part of the system prompt."""

    prompt = build_system_prompt(vault_summary=None)
    assert "Output Contract" in prompt
    assert '"operation"' in prompt
    assert "create" in prompt and "update" in prompt
    assert "[]" in prompt


def test_build_system_prompt_includes_vault_summary_when_provided() -> None:
    """``compute_vault_summary``'s output is rendered into the prompt."""

    vault_summary = {
        "counts": {"entity": 2, "concept": 1, "project": 0, "session": 0},
        "latest": {
            "entity": ["ruben-luetke", "personal-jarvis"],
            "concept": ["awareness-layer"],
            "project": [],
            "session": [],
        },
        "recent_log": ["[2026-05-11 18:00] create | seed"],
    }
    prompt = build_system_prompt(vault_summary=vault_summary)
    assert "Entities: 2" in prompt
    assert "ruben-luetke" in prompt
    assert "Concepts: 1" in prompt
    assert "[2026-05-11 18:00] create | seed" in prompt


def test_build_system_prompt_handles_no_summary() -> None:
    """Passing ``None`` skips the snapshot section but keeps the contract."""

    prompt = build_system_prompt(vault_summary=None)
    assert "Current Vault Snapshot" not in prompt
    assert "Output Contract" in prompt


# ---------------------------------------------------------------------
# build_user_prompt
# ---------------------------------------------------------------------


def test_build_user_prompt_wraps_source_verbatim() -> None:
    """Source content is rendered between explicit BEGIN/END markers."""

    prompt = build_user_prompt(
        "BrainTurnCompleted 2026-05-11 19:42",
        "Ruben fixed BUG-019 in fix/bug-019-tts-silent.",
        top_slugs=["ruben-luetke"],
    )
    assert "Ruben fixed BUG-019 in fix/bug-019-tts-silent." in prompt
    assert "----- BEGIN SOURCE -----" in prompt
    assert "----- END SOURCE -----" in prompt
    assert "BrainTurnCompleted 2026-05-11 19:42" in prompt


def test_build_user_prompt_includes_top_slugs() -> None:
    """The keyword-overlap shortlist is rendered as bullet hints."""

    prompt = build_user_prompt(
        "source-label", "some content", top_slugs=["ruben-luetke", "jarvis-agent-bridge"],
    )
    assert "- ruben-luetke" in prompt
    assert "- jarvis-agent-bridge" in prompt


def test_build_user_prompt_handles_no_top_slugs() -> None:
    """The "no overlap" hint is emitted when the shortlist is empty."""

    prompt = build_user_prompt("source-label", "some content", top_slugs=[])
    assert "no overlap detected" in prompt


def test_build_user_prompt_handles_none_top_slugs() -> None:
    """``None`` is treated like an empty list (no crash on missing list)."""

    prompt = build_user_prompt("source-label", "content")
    assert "no overlap detected" in prompt


def test_build_user_prompt_demands_json_at_end() -> None:
    """The user message ends with the explicit JSON-array directive."""

    prompt = build_user_prompt("label", "content", top_slugs=[])
    assert prompt.rstrip().endswith("Return the JSON array now.")


# ---------------------------------------------------------------------
# Salience filter (B8): the system prompt must teach the LLM which
# inputs to drop ([]) and which to persist. We can't unit-test the LLM
# itself, but we can pin the prompt content so a future refactor
# cannot quietly delete the filter.
# ---------------------------------------------------------------------


def test_system_prompt_states_the_applied_checks() -> None:
    """The deterministic checks the model cannot know are stated as facts."""
    from dodaios.memory.wiki.curator_llm import _MAX_UPDATES_PER_INGEST

    prompt = build_system_prompt(vault_summary=None)
    assert f"At most {_MAX_UPDATES_PER_INGEST} updates apply" in prompt
    assert "becomes plain text" in prompt
    assert "<!-- contact-mirror:start -->" in prompt


def test_system_prompt_has_no_maintainer_specific_user_target() -> None:
    """Generic curator guidance never bakes in one maintainer's profile slug."""
    prompt = build_system_prompt(vault_summary=None)
    assert "entities/ruben.md" not in prompt.lower()
    assert 'exact subject slug is ["user"]' in prompt


# ---------------------------------------------------------------------
# Stage-2 user-entity binding
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("", "user"),
        (None, "user"),
        ("../../private", "user"),
        ("Owner-Profile", "owner-profile"),
    ],
)
def test_resolve_user_entity_slug_is_safe_and_neutral(
    configured: object,
    expected: str,
) -> None:
    assert resolve_user_entity_slug(configured) == expected


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("", "user"), ("owner-profile", "owner-profile")],
)
def test_consolidator_prompt_binds_exact_user_subject_and_page(
    configured: str,
    expected: str,
) -> None:
    candidate = SimpleNamespace(
        id=1,
        fact="The speaker prefers dark mode.",
        kind="preference",
        subjects=(expected,),
    )

    system, user = build_consolidator_prompt(
        [candidate],
        {},
        user_entity_slug=configured,
    )

    assert f'subject slug ["{expected}"]' in user
    assert f"profile page entities/{expected}.md" in user
    assert "never infer a name" in user
    assert "ruben" not in f"{system}\n{user}".lower()


def test_consolidator_prompt_rechecks_question_derived_user_claims() -> None:
    candidate = SimpleNamespace(
        id=7,
        fact="The user is interested in Vitamin D.",
        kind="preference",
        subjects=("user",),
        evidence_turn_id="vitamin-turn",
        evidence_excerpt=(
            "Evidence user turn [vitamin-turn]: "
            "What are the benefits of Vitamin D?"
        ),
    )

    system, user = build_consolidator_prompt([candidate], {})

    assert "asserts or confirms it" in system
    assert "Vitamin D" not in system
    assert "What are the benefits of Vitamin D?" in user
    # Rows without basis metadata render the explicit/3 defaults.
    assert "basis=explicit salience=3" in user


def test_consolidator_prompt_renders_the_validator_flags_per_candidate() -> None:
    place = SimpleNamespace(
        id=9,
        fact="The user lives in San Francisco.",
        kind="place",
        subjects=("user", "san-francisco"),
    )
    plan = SimpleNamespace(
        id=8,
        fact="The user plans to travel to San Francisco tomorrow.",
        kind="plan",
        subjects=("user",),
    )

    system, user = build_consolidator_prompt(
        [place, plan],
        {},
        row_flags={
            9: "persist_requested=no required_page=entities/san-francisco.md",
            8: "persist_requested=yes required_page=-",
        },
    )

    assert (
        "candidate_id=9 kind=place subjects=[user, san-francisco] basis=explicit "
        "salience=3 persist_requested=no required_page=entities/san-francisco.md"
    ) in user
    assert "persist_requested=yes required_page=-" in user
    assert "required_page=<path>" in system
    assert "unsupported by user evidence" in system


def test_consolidator_prompt_without_flags_keeps_the_plain_candidate_line() -> None:
    row = SimpleNamespace(id=3, fact="f", kind="preference", subjects=("user",))
    _system, user = build_consolidator_prompt([row], {})
    assert "persist_requested" not in user
    assert "basis=explicit salience=3\n" in user


# ---------------------------------------------------------------------
# Integration-style assertion: round-trip through everything once.
# ---------------------------------------------------------------------


def test_build_full_prompt_roundtrip_smoke() -> None:
    """One full pipeline: vault → summary → system prompt + user prompt."""

    vault = _FakeVault({
        "entity": [_Page("ruben-luetke", "entity"), _Page("personal-jarvis", "entity")],
        "concept": [_Page("awareness-layer", "concept")],
    })
    summary = compute_vault_summary(vault)
    system_prompt = build_system_prompt(summary)
    top_slugs = select_top_slugs("Ruben pushed the awareness layer", [
        "ruben-luetke", "awareness-layer", "personal-jarvis",
    ])
    user_prompt = build_user_prompt(
        "BrainTurnCompleted", "Ruben pushed the awareness layer", top_slugs,
    )

    assert "Entities: 2" in system_prompt
    assert "Concepts: 1" in system_prompt
    assert "ruben-luetke" in user_prompt
    assert "awareness-layer" in user_prompt
