"""One pass for every brief: sent back once, then let through; assembled per recipient."""

from __future__ import annotations

import asyncio

from dodaios.briefs import (
    BriefDraft,
    Order,
    Recipient,
    assemble,
    gate,
    handoff,
    profiles,
    standing,
)
from dodaios.briefs import log as brief_log

WEAK = BriefDraft(
    task="The upload looks bad, clearly improve it.\n1. Open sync/client.py.\n2. Run `pytest`.\n"
         "3. Then commit.",
)
REVISED = BriefDraft(
    task=(
        "Uploads in sync/client.py time out after 10 s on a slow connection and the note is "
        "lost. Make an upload survive a slow connection without losing the note."
    ),
    criteria="A test that simulates a timeout fails before the change and passes after it.",
)


def _order(draft: BriefDraft, folder: str, said: str = "fix the upload") -> Order:
    return Order(
        writer="lead",
        draft=draft,
        recipient=Recipient(cli="claude", model="claude-fable-5-2", folder=folder),
        person_words=said,
        writer_session="lead-1",
    )


def test_a_brief_with_faults_goes_back_once_with_the_kit(briefs_on, project):
    first = gate.review(_order(WEAK, str(project)))
    assert first.send is False
    reply = first.reply()
    assert reply["status"] == "needs_revision" and reply["success"] is False
    assert {f["code"] for f in reply["fix"]} >= {"step_script", "left_open", "no_done"}
    kit = reply["brief_kit"]
    assert kit["project_checks"][0] == "python scripts/done_gate.py"
    assert any(p["path"] == "sync/client.py" for p in kit["starting_points"])


def test_the_revision_is_sent_as_it_is_and_shares_the_first_attempts_record(briefs_on, project):
    first = gate.review(_order(WEAK, str(project)))
    second = gate.review(_order(REVISED, str(project)))
    assert second.send is True and second.revised is True
    assert second.brief_id == first.brief_id
    row = brief_log.get_log().brief(first.brief_id)
    assert row["sent_back"] == 1
    assert "looks bad" in row["first_draft"] and "survive a slow connection" in row["brief_text"]


def test_a_second_attempt_is_never_sent_back_again(briefs_on, project):
    gate.review(_order(WEAK, str(project)))
    still_weak = BriefDraft(task=WEAK.task + " Please.")
    again = gate.review(_order(still_weak, str(project)))
    assert again.send is True and again.revised is True
    assert again.to_fix()  # recorded, and shown with the receipt
    assert handoff.receipt(again)["check_found"]


def test_only_the_same_conversation_and_folder_make_a_brief_a_revision(
    briefs_on, project, tmp_path
):
    gate.review(_order(WEAK, str(project)))
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    other_folder = gate.review(_order(WEAK, str(elsewhere)))
    assert other_folder.revised is False and other_folder.send is False
    other_writer = Order(
        writer="lead", draft=WEAK, writer_session="lead-2",
        recipient=Recipient(cli="claude", folder=str(project)), person_words="fix the upload",
    )
    assert gate.review(other_writer).revised is False


def test_two_briefs_of_one_batch_are_each_checked_and_take_their_own_revisions(
    briefs_on, project, monkeypatch
):
    # Two agents briefed at once: the second brief is no revision of the first.
    monkeypatch.setattr(gate, "_REVISION_MIN_AGE_S", 30.0)
    one = gate.review(_order(WEAK, str(project)))
    colours = BriefDraft(task="Make the colours of the stylesheet nicer somehow.")
    two = gate.review(_order(colours, str(project)))
    assert not one.send and not two.send
    monkeypatch.setattr(gate, "_REVISION_MIN_AGE_S", 0.0)
    revised_colours = BriefDraft(
        task="The stylesheet uses six greys for borders; reduce them to the two tokens.",
        criteria="A search for hex greys in the stylesheet finds only the two tokens.",
    )
    assert gate.review(_order(revised_colours, str(project))).brief_id == two.brief_id
    assert gate.review(_order(REVISED, str(project))).brief_id == one.brief_id


def test_the_same_brief_again_gets_the_answer_it_got(briefs_on, project):
    first = gate.review(_order(REVISED, str(project)))
    again = gate.review(_order(REVISED, str(project)))
    assert first.send and again is first


def test_note_mode_checks_and_records_but_never_sends_back(briefs_on, project):
    decided = gate.review(_order(WEAK, str(project)), mode=gate.MODE_NOTE)
    assert decided.send is True and decided.to_fix()


def test_prepare_returns_the_kit_and_sends_nothing(briefs_on, project):
    order = _order(BriefDraft(task="the upload breaks on a slow connection"), str(project),
                   said="der upload ist kaputt")  # i18n-allow
    got = gate.prepare(order)
    assert got["status"] == "prepared" and got["nothing_sent"] is True
    kit = got["brief_kit"]
    assert kit["open_points"][0]["open_point"].startswith("what should happen")
    assert kit["recipient"]["recipient"] == profiles.CLAUDE_FABLE.label
    assert brief_log.get_log().rows() == []
    after = gate.review(_order(REVISED, str(project)))
    assert brief_log.get_log().brief(after.brief_id)["prepared"] == 1


def test_assembly_adds_the_persons_words_and_orders_parts_for_the_recipient(briefs_on, project):
    order = _order(
        BriefDraft(task="Make uploads survive.", context="Log: timed out.", criteria="Test x."),
        str(project), said="mach den upload robust",  # i18n-allow
    )
    for_claude = assemble.assemble(order, profiles.CLAUDE, kind="implement")
    assert for_claude.index("Make uploads survive.") < for_claude.index("Context:")
    assert "> mach den upload robust" in for_claude  # i18n-allow
    assert profiles.GPT.closing not in for_claude
    for_gemini = assemble.assemble(order, profiles.GEMINI, kind="implement")
    assert for_gemini.index("Context:") < for_gemini.index("Make uploads survive.")
    for_gpt = assemble.assemble(order, profiles.GPT, kind="implement")
    assert for_gpt.rstrip().endswith(profiles.GPT.closing)
    asked = assemble.assemble(order, profiles.GPT, kind="question")
    assert profiles.GPT.closing not in asked


def test_the_persons_words_are_not_added_twice_or_when_too_long(briefs_on, project):
    quoted = _order(BriefDraft(task='They said: "fix the upload". Do it.'), str(project))
    assert assemble.quote_of(quoted) == ""
    long_order = _order(BriefDraft(task="Do it."), str(project), said="wort " * 400)
    assert assemble.quote_of(long_order) == ""


def test_standing_rules_are_one_command_line_safe_paragraph():
    rules = standing.WORK_ORDER_RULES
    assert "\n" not in rules and "%" not in rules and '"' not in rules
    assert rules.startswith(standing.MARK)
    assert "not watching" in rules and "done-when" in rules


def test_standing_rules_join_the_system_prompt_of_a_thread_an_agent_opened():
    class Handle:
        opened_by = "jarvis"

    argv = ["claude", "--append-system-prompt", "PREAMBLE"]
    standing.tell_claude_code(argv, Handle())
    standing.tell_claude_code(argv, Handle())
    assert argv[2].startswith("PREAMBLE ") and argv[2].count(standing.MARK) == 1

    class Person:
        opened_by = ""

    untouched = ["claude", "--append-system-prompt", "PREAMBLE"]
    standing.tell_claude_code(untouched, Person())
    assert untouched[2] == "PREAMBLE"
    identity = ["claude", "--append-system-prompt-file", "identity.md"]
    standing.tell_claude_code(identity, Handle())
    assert "--append-system-prompt" not in identity


def test_a_cli_without_a_system_prompt_gets_the_rules_once_per_conversation():
    class Handle:
        opened_by = "jarvis"

    first = standing.for_first_message("Do the work.", Handle(), new_conversation=True)
    assert first.startswith(standing.MARK) and first.endswith("Do the work.")
    assert standing.for_first_message(first, Handle(), new_conversation=True) == first
    assert standing.for_first_message("Next.", Handle(), new_conversation=False) == "Next."
    assert standing.for_first_message("/compact", Handle(), new_conversation=True) == "/compact"


def test_a_delivery_keeps_the_brief_whole_under_a_transport_limit(briefs_on, project):
    decided = gate.review(_order(REVISED, str(project)), mode=gate.MODE_NOTE)
    full = handoff.delivery_for(decided, cli="claude", rules_in_message=True)
    assert standing.MARK in full.text and "> fix the upload" in full.text
    tight = handoff.delivery_for(
        decided, cli="claude", rules_in_message=True, max_chars=len(REVISED.text()) + 80
    )
    assert REVISED.task in tight.text and standing.MARK not in tight.text
    assert full.family == "claude" and full.ticket.criteria


def test_off_means_a_brief_goes_out_as_written():
    assert handoff.enabled() is False  # the default of the test suite
    assert handoff.composed("## Task\nFix it", utterance="fix es") == "## Task\nFix it"


def test_a_composed_brief_is_checked_on_wording_and_carries_the_sentence(briefs_on, project):
    sent = handoff.composed(
        "## Task\nMake uploads survive a slow connection.",
        utterance="mach den upload robust",  # i18n-allow
        folder=str(project), recipient_name="Claude Code", session="T2",
    )
    assert sent.startswith("## Task") and "> mach den upload robust" in sent  # i18n-allow
    rows = brief_log.get_log().rows()
    assert rows[0]["writer"] == "composer" and rows[0]["sent_back"] == 0


async def test_a_hand_off_does_not_wait_for_a_repository_that_cannot_be_read(
    briefs_on, project, monkeypatch
):
    import time

    from dodaios.briefs import repo_facts

    slow_calls = []

    def slow_lookup(folder, text, **kwargs):
        if folder:
            slow_calls.append(folder)
            time.sleep(1.0)
        return repo_facts.RepoFacts(folder=str(folder or ""))

    monkeypatch.setattr(repo_facts, "lookup", slow_lookup)
    monkeypatch.setattr(handoff, "PASS_DEADLINE_S", 0.2)
    started = time.monotonic()
    decision = await handoff.check(
        {"prompt": WEAK.task, "_person_words": "fix the upload"},
        [Recipient(cli="claude", folder=str(project))],
    )
    # Checked on its wording alone, well before the slow read would have ended.
    assert slow_calls and time.monotonic() - started < 0.9
    assert decision.send is False
    assert {f.code for f in decision.to_fix()} >= {"step_script", "left_open", "no_done"}
    # The slow pass ends later and leaves nothing behind: one order on record,
    # one brief waiting for its revision.
    await asyncio.sleep(1.2)
    assert len(brief_log.get_log().rows()) == 1
    revised = await handoff.check(
        {"prompt": REVISED.text(), "_person_words": "fix the upload"},
        [Recipient(cli="claude", folder=str(project))],
    )
    assert revised.send is True and revised.revised is True
    after = await handoff.check(
        {"prompt": WEAK.task + " Again.", "_person_words": "fix the upload"},
        [Recipient(cli="claude", folder=str(project))],
    )
    assert after.revised is False
