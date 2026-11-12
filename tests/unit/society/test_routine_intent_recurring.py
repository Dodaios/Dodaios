"""Recurring work is recognised without the word "routine", and a request that
names a skill keeps its skill meaning (live 2026-09-29: "every day at 8"
ended as an inactive draft skill)."""

from __future__ import annotations

import pytest

from dodaios.society.routine_intent import (
    hands_over_ongoing_work,
    requests_recurring_work,
    wants_agent_routine,
)

ROUTINE_REQUESTS = [
    "Erstelle einen Agenten, der mir jeden Tag um 8 Uhr ein Morgenbriefing gibt",  # i18n-allow
    "gib mir jeden Morgen um acht ein Briefing",  # i18n-allow
    "Kannst du mir täglich meine wichtigsten Gmails zusammenfassen",  # i18n-allow
    "every day at 8 give me a morning briefing",
    "Remind me every Monday to pay rent",
    "dame un resumen cada mañana a las ocho",  # i18n-allow
    "Erstelle eine Routine für den Gmail Agenten",  # i18n-allow
    "dá-me um resumo todas as manhãs às oito",  # i18n-allow
    "Lembra-me todas as segundas de pagar a renda",  # i18n-allow
    "podes resumir os meus emails todos os dias",  # i18n-allow
]

NOT_ROUTINE = [
    "Ich gehe jeden Morgen joggen",  # i18n-allow
    "How do I get a report every day?",
    "Wie kann ich jeden Tag um 8 ein Briefing bekommen?",  # i18n-allow
    "Was steht heute im Kalender?",  # i18n-allow
    "Erstelle einen Skill, der mir jeden Morgen um 6 die Mails vorliest",  # i18n-allow
    "Eu corro todas as manhãs",  # i18n-allow
    "Como posso receber um relatório todos os dias?",  # i18n-allow
]


@pytest.mark.parametrize("text", ROUTINE_REQUESTS)
def test_scheduled_requests_belong_to_an_agent_routine(text: str) -> None:
    assert wants_agent_routine(text)


@pytest.mark.parametrize("text", NOT_ROUTINE)
def test_habits_questions_and_skill_requests_are_not_routines(text: str) -> None:
    assert not wants_agent_routine(text)


#: Something handed over to be looked after. A pace in the sentence does not make it a
#: routine: the assistant may take it on as a standing task (``standing_task``).
LOOK_AFTER = [
    "Please look after my Meta ads campaign and check it daily",
    "Can you keep an eye on my inbox every day?",
    "Please take care of my hiring pipeline, look at it every morning",
    "Kümmere dich bitte täglich um meine Meta-Kampagne",  # i18n-allow
    "Bitte kümmere dich ab jetzt jeden Tag um meine Meta-Kampagne",  # i18n-allow
    "Behalte bitte täglich meinen Server im Auge",  # i18n-allow
    "ocúpate de mi campaña cada día por favor",  # i18n-allow
    "toma conta da minha campanha todos os dias por favor",  # i18n-allow
]

#: The same words with a time of day, or with the word "routine", stay a routine.
LOOK_AFTER_ON_A_CLOCK = [
    "Please look after my inbox every day at 8",
    "Bitte kümmere dich jeden Morgen um 8 Uhr um mein Postfach",  # i18n-allow
    "Create a routine that looks after my inbox every day",
    "Please send me the campaign numbers every evening",
]


@pytest.mark.parametrize("text", LOOK_AFTER)
def test_a_look_after_request_is_not_forced_into_a_routine(text: str) -> None:
    assert requests_recurring_work(text)  # the pace alone used to mandate a routine
    assert hands_over_ongoing_work(text)
    assert not wants_agent_routine(text)


@pytest.mark.parametrize(
    "text",
    [
        "look after my Meta ads campaign",
        "kümmere dich um meine Meta-Kampagne",  # i18n-allow
        "behalte die Kampagne im Auge",  # i18n-allow
    ],
)
def test_a_look_after_request_without_a_pace_was_never_a_routine(text: str) -> None:
    assert hands_over_ongoing_work(text)
    assert not wants_agent_routine(text)


@pytest.mark.parametrize("text", LOOK_AFTER_ON_A_CLOCK)
def test_a_fixed_time_or_the_word_routine_keeps_it_a_routine(text: str) -> None:
    assert wants_agent_routine(text)


def test_recurrence_needs_a_request_not_a_description() -> None:
    assert requests_recurring_work("Please send me the news every evening")
    assert not requests_recurring_work("The newsletter arrives every evening")
