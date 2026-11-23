"""Where the pipeline meets the rest of the app: settings, the runner, the lead's continuation."""

from __future__ import annotations

from types import SimpleNamespace

from dodaios.agent_chat import delegation_wait
from dodaios.agent_chat.service import _opened_by
from dodaios.briefs import settings
from dodaios.core.config import BriefsConfig, JarvisConfig


def test_the_config_section_has_the_shipped_defaults():
    section = JarvisConfig().briefs
    assert isinstance(section, BriefsConfig)
    assert section.check == "revise"
    assert section.auto_effort and section.standing_rules and section.lead_answers_questions
    assert section.acceptance and section.record


def test_settings_follow_the_config_and_survive_a_broken_section():
    try:
        got = settings.configure(SimpleNamespace(briefs=BriefsConfig(check="note", record=False)))
        assert (got.check, got.record, got.auto_effort) == ("note", False, True)
        loud = SimpleNamespace(briefs=SimpleNamespace(check="loud"))
        assert settings.configure(loud).check == "revise"
        assert settings.configure(SimpleNamespace()).check == "revise"
    finally:
        settings.reset()


def test_who_opened_a_thread_is_the_same_on_its_first_and_later_turns(briefs_on):
    lead = {"agent_id": "jarvis", "name": "Nova"}
    fresh = SimpleNamespace(surface="agent", started_by="")
    assert _opened_by(fresh, lead, []) == "jarvis"
    later = SimpleNamespace(surface="agent", started_by="jarvis")
    assert _opened_by(later, None, [{"kind": "user_message"}]) == "jarvis"
    # A thread the person opened stays theirs, also when the lead writes into it later.
    theirs = SimpleNamespace(surface="agent", started_by="")
    assert _opened_by(theirs, lead, [{"kind": "user_message"}]) == ""
    assert _opened_by(SimpleNamespace(surface="jarvis", started_by=""), lead, []) == ""


def test_who_opened_a_thread_is_nobody_with_the_rules_switched_off():
    # The test suite's default: standing rules off.
    assert _opened_by(SimpleNamespace(surface="agent", started_by="jarvis"), None, []) == ""


def test_the_continuation_tells_the_lead_what_to_do_with_a_question_and_a_check():
    plain = delegation_wait.continuation_prompt(
        [{"status": "completed", "report": "done"}], "fix it"
    )
    assert delegation_wait.AGENT_ASKS not in plain
    assert delegation_wait.DONE_WHEN_CHECKED not in plain
    asked = delegation_wait.continuation_prompt(
        [{"status": "needs_input", "report": "It asks", "question": {"thread": "thread:x"}}],
        "fix it",
    )
    assert delegation_wait.AGENT_ASKS in asked and "action respond" in asked
    checked = delegation_wait.continuation_prompt(
        [{"status": "completed", "report": "done", "done_when_check": "0 of 1 confirmed"}],
        "fix it",
    )
    assert delegation_wait.DONE_WHEN_CHECKED in checked
    assert delegation_wait.is_continuation_prompt(checked)


def test_a_composed_brief_counts_as_delivered_only_once_a_pane_took_it(briefs_on):
    from dodaios.briefs import handoff
    from dodaios.briefs import log as brief_log

    said = "im notes-app fehlt eine Funktion, die den Postausgang leert"  # i18n-allow
    text = handoff.composed(
        "Add clear_outbox() to sync/client.py: it empties the outbox without sending.\n\n"
        "Done when: `python -m pytest -q` is green.",
        utterance=said, folder="", recipient_name="Claude Code", session="T1",
    )
    store = brief_log.get_log()
    [row] = store.rows()
    assert not row["sent_ms"] and row["deliveries"] == []
    # Another text (a typed prompt, a different brief) records nothing.
    handoff.note_composed_sent("hello", "job_other", thread_id="pane:x")
    assert store.delivery("job_other") is None
    # The pane took the composed text, tidied by the composer afterwards.
    tidied = "  " + text.replace("\n\n", "\n") + "  "
    handoff.note_composed_sent(tidied, "job_pane", thread_id="pane:h1")
    delivery = store.delivery("job_pane")
    assert delivery is not None and delivery["thread_id"] == "pane:h1"
    [row] = store.rows()
    assert row["sent_ms"]
    # Recorded once: a second send of the same text is no second delivery.
    handoff.note_composed_sent(text, "job_again", thread_id="pane:h1")
    assert store.delivery("job_again") is None
