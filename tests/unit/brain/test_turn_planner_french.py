"""French coverage of the shared turn planner.

The planner's vocabularies spoke English, German and Spanish only, so no French
news or "today" question was ever graded a fresh public fact, and a local model
answered them from memory (live 2026-10-28: a train collision in Spain became an
invented story about luxury wagons). French must behave like English: fresh
public facts ground on search_web; clock, date, chit-chat and the person's own
past never do.
"""
from __future__ import annotations

import pytest

from dodaios.brain.turn_planner import plan_turn

TOOLS = ("search_web",)


@pytest.mark.parametrize(
    "text",
    [
        "quelle est la dernière tragédie en Espagne ?",  # i18n-allow: French speech input under test
        "regarde ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: French
        "quelles sont les dernières nouvelles ?",  # i18n-allow: French speech input under test
        "quel temps fait-il aujourd'hui à Lyon ?",  # i18n-allow: French speech input under test
        "Quelle est la météo demain ?",  # i18n-allow: French speech input under test
        "dis-moi l'actualité de ce soir",  # i18n-allow: French speech input under test
    ],
)
def test_fresh_french_public_facts_ground_on_search(text: str) -> None:
    plan = plan_turn(text, tool_names=TOOLS)
    assert plan.requires_public_fact_grounding
    assert "search_web" in plan.required_capabilities


@pytest.mark.parametrize(
    "text",
    [
        "comment ça va aujourd'hui ?",  # i18n-allow: French speech input under test
        "raconte-moi une histoire",  # i18n-allow: French speech input under test
        "il est quelle heure ?",  # i18n-allow: French speech input under test
        "quelle heure est-il ?",  # i18n-allow: French speech input under test
        "on est quel jour aujourd'hui ?",  # i18n-allow: French speech input under test
        "quelle est la date d'aujourd'hui ?",  # i18n-allow: French speech input under test
        "qu'est-ce que je t'ai dit la dernière fois ?",  # i18n-allow: French speech input
        "tu as vu mes clés aujourd'hui ?",  # i18n-allow: French speech input under test
        "Ça marche, on s'arrête au Mcdo",  # i18n-allow: French speech input under test
    ],
)
def test_french_chat_clock_and_private_turns_never_ground(text: str) -> None:
    assert not plan_turn(text, tool_names=TOOLS).requires_public_fact_grounding


def test_french_matches_english_parity_for_a_fresh_question() -> None:
    english = plan_turn("what happened with the train today", tool_names=TOOLS)
    french = plan_turn(
        "qu'est-ce qui s'est passé avec le train aujourd'hui",  # i18n-allow: French
        tool_names=TOOLS,
    )
    assert english.requires_public_fact_grounding
    assert french.requires_public_fact_grounding


@pytest.mark.parametrize(
    "text",
    [
        "tu as pas vu un accident",  # i18n-allow: the live 2026-10-28 utterance
        "que s'est il passé en espagne avec le train",  # i18n-allow: French speech input
        "quel est le résultat des élections en israel",  # i18n-allow: French speech input
    ],
)
def test_french_public_fact_shapes_ground_when_the_model_requires_it(text: str) -> None:
    assert not plan_turn(text, tool_names=TOOLS).requires_public_fact_grounding
    plan = plan_turn(text, tool_names=TOOLS, requires_public_fact_grounding=True)
    assert plan.requires_public_fact_grounding
