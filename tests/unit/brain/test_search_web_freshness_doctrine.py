"""Regression guard: the router answers evergreen knowledge DIRECTLY and reserves
``search_web`` for genuinely fresh / volatile facts (or an explicit search
request) — the "Frische-Grenze" mandate.

Live forensic 2026-06-20: a plain knowledge question — "Kannst du mir sagen,
was ich alles beachten muss, wenn ich auswandern moechte?" — made the  # i18n-allow
router LLM fire ``search_web`` THREE
times (proven from sessions.db voice_events: 3x ``ActionProposed search_web``,
``jarvis_text`` empty) instead of just answering. The Run-Inspector labels a
``search_web`` call "Recherche"; the user read that as an unwanted
sub-agent / research spawn for a trivial question.

The deterministic force-spawn gate behaved correctly (it did NOT spawn — that
path is covered by ``test_routing.py``). The over-eager choice came from the
router prompt + the ``search_web`` tool description, which both told the model
to search for ANY "Wissensfrage / was ist X / erklaer mir X".

Mandate ("Frische-Grenze"): evergreen / general knowledge is answered from the
model's own knowledge; ``search_web`` fires only for fresh / volatile facts
(news, prices, weather, "aktuell / heute / neueste") or an explicit search
request.
"""
from __future__ import annotations

from dodaios.plugins.tool.search_web import SearchWebTool


def test_search_web_description_reserved_for_fresh_facts() -> None:
    """The tool's own function declaration must scope it to fresh facts.

    This is the highest-leverage lever — the LLM sees ``SearchWebTool.description``
    on every turn as the search_web function declaration, independent of which
    system-prompt path (capability block vs. fallback) is active.
    """
    desc = SearchWebTool.description.lower()
    # The fresh / volatile doctrine must be present.
    assert "fresh" in desc, (
        "search_web description must restrict the tool to current/fresh facts"
    )
    # The evergreen carve-out must be present so the model answers general
    # knowledge directly instead of searching it.
    assert "evergreen" in desc or "allgemeinwissen" in desc, (
        "search_web description must tell the model NOT to search evergreen "
        "knowledge it can answer directly"
    )
    # The old over-eager evergreen triggers must be gone — these turned a plain
    # "explain X" / "what is X" question into a web search (emigration forensic).
    assert "erklär mir x" not in desc and "erklaer mir x" not in desc, (  # i18n-allow
        "search_web description still advertises evergreen 'explain X' as a "
        "primary trigger — that is the over-eager research bug"
    )


def test_core_contract_answers_evergreen_knowledge_directly() -> None:
    """The routing doctrine must answer evergreen knowledge directly."""
    from dodaios.brain.manager import _CORE_CONTRACT

    low = _CORE_CONTRACT.lower()
    assert "evergreen" in low, (
        "core contract is missing the evergreen-knowledge-answered-directly doctrine"
    )
    assert "fresh" in low, "core contract must reserve search_web for fresh facts"
    # search_web must STILL be advertised for genuinely fresh queries (news) —
    # never regress to the 'spawn a worker / never search' extreme.
    assert "search_web" in low and "news" in low
