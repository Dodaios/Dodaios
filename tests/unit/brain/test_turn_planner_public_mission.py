"""A named public mission is news, not the assistant's own missions.

BC-250 2026-10-29: "Recherche les dernières actualités de la mission Artemis
II et cite tes sources" never searched. The word "mission" graded the turn as
a question about Dodaios agent missions (TurnReason.MISSION), which is private
evidence and switches public-fact grounding off, so even the on-device model
was never handed a search.
"""
from __future__ import annotations

import pytest

from dodaios.brain.turn_planner import TurnReason, plan_turn

TOOLS = ("search_web",)


@pytest.mark.parametrize(
    "utterance",
    [
        "Recherche les dernières actualités de la mission Artemis II et cite tes sources",  # i18n-allow: French speech-input fixture
        "Recherche les dernières actualités de la mission Artemis deux et Cite Source",  # i18n-allow: live transcript
        "Quelles sont les dernières actualités de la mission Artemis II ?",  # i18n-allow: French speech-input fixture
        "Donne-moi les dernières actualités de la mission Artemis II",  # i18n-allow: French speech-input fixture
        "Recherche les nouvelles récentes de la mission Artemis II",  # i18n-allow: French speech-input fixture
        "Cherche ce qui s'est passé aujourd'hui avec la mission Artemis II",  # i18n-allow: French fixture
        "Quoi de neuf aujourd'hui sur la mission spatiale Artemis ?",  # i18n-allow: French speech-input fixture
        "Was sind die neuesten Nachrichten zur Artemis-II-Mission?",  # i18n-allow: German speech-input fixture
        "What's the latest news on the Artemis II mission?",
    ],
)
def test_news_about_a_named_public_mission_is_a_fresh_public_fact(utterance: str) -> None:
    plan = plan_turn(utterance, tool_names=TOOLS)
    assert TurnReason.MISSION not in plan.reasons
    assert plan.requires_public_fact_grounding


@pytest.mark.parametrize(
    "utterance",
    [
        "Quel est l'état de ma mission ?",  # i18n-allow: French speech-input fixture
        "Où en est la mission que je t'ai confiée ?",  # i18n-allow: French speech-input fixture
        "Lance une mission pour trier mes fichiers",  # i18n-allow: French speech-input fixture
        "Was macht die Mission gerade?",  # i18n-allow: German speech-input fixture
        "Woran arbeitet der Agent?",  # i18n-allow: German speech-input fixture
        "How is my mission going?",
    ],
)
def test_the_assistants_own_missions_still_route_as_missions(utterance: str) -> None:
    plan = plan_turn(utterance, tool_names=TOOLS)
    assert TurnReason.MISSION in plan.reasons
    assert not plan.requires_public_fact_grounding


def test_a_follow_up_after_a_named_mission_does_not_inherit_a_mission() -> None:
    plan = plan_turn(
        "et aujourd'hui ?",  # i18n-allow: French speech-input fixture
        tool_names=TOOLS,
        context=("Quelles sont les dernières actualités de la mission Artemis II ?",),  # i18n-allow
    )
    assert TurnReason.MISSION not in plan.reasons


@pytest.mark.parametrize(
    "utterance",
    [
        "Donne-moi les dernières actualités sur Artemis II",  # i18n-allow: French speech-input fixture
        "Donnez-moi les nouvelles récentes de la NASA",  # i18n-allow: French speech-input fixture
    ],
)
def test_a_french_give_me_request_for_the_latest_news_searches(utterance: str) -> None:
    """ "Donne-moi" asks for information like "dis-moi" already does."""
    assert plan_turn(utterance, tool_names=TOOLS).requires_public_fact_grounding


@pytest.mark.parametrize(
    "utterance",
    [
        "Donne-moi un conseil pour bien dormir",  # i18n-allow: French speech-input fixture
        "Explique simplement le rôle d'un disjoncteur différentiel",  # i18n-allow: French fixture
        "Quelle est la capitale de la Suisse",  # i18n-allow: French speech-input fixture
    ],
)
def test_evergreen_requests_are_not_graded_fresh(utterance: str) -> None:
    """Without a freshness word nothing is fresh; grounding of evergreen facts
    stays a decision of the active model (requires_public_fact_grounding)."""
    assert not plan_turn(utterance, tool_names=TOOLS).requires_public_fact_grounding


@pytest.mark.parametrize(
    "utterance",
    [
        "Que s'est-il passé en Espagne hier",  # i18n-allow: live transcript 2026-10-29
        "Qu'est-ce qui est arrivé à la NASA hier soir ?",  # i18n-allow: French fixture
    ],
)
def test_french_yesterday_events_are_fresh(utterance: str) -> None:
    assert plan_turn(utterance, tool_names=TOOLS).requires_public_fact_grounding


def test_german_hier_means_here_and_stays_local() -> None:
    plan = plan_turn("Was ist hier los?", tool_names=TOOLS)  # i18n-allow: German fixture
    assert TurnReason.CURRENT_DATA not in plan.reasons
