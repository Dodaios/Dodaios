"""The check every brief passes: what it finds, and what it leaves alone."""

from __future__ import annotations

from dodaios.briefs import BriefDraft, Order, Recipient, lint, profiles, repo_facts
from dodaios.briefs.model import SEVERITY_NOTE, SEVERITY_REVISE

GOOD = BriefDraft(
    task=(
        "Uploads to the sync server fail about one time in five on a slow connection, and "
        "the person loses notes when that happens. The log line is `UploadError: timed out "
        "after 10s` (sync/client.py). Make uploads survive a slow connection without losing "
        "or duplicating a note."
    ),
    criteria=(
        "A test that simulates a timeout fails before the change and passes after it; "
        "`python scripts/done_gate.py` says DONE."
    ),
)


def _order(draft: BriefDraft, *, said: str = "", folder: str = "", **recipient) -> Order:
    return Order(
        writer="lead",
        draft=draft,
        recipient=Recipient(folder=folder, **recipient),
        person_words=said,
    )


def _codes(findings, severity=SEVERITY_REVISE) -> set[str]:
    return {f.code for f in findings if f.severity == severity}


def test_a_good_brief_has_nothing_to_revise(project):
    facts = repo_facts.lookup(project, GOOD.task)
    found = lint.check(_order(GOOD, said="fix the upload", folder=str(project)), facts=facts)
    assert _codes(found) == set()


def test_a_path_that_is_not_on_disk_is_named_with_the_nearest_real_one(project):
    draft = BriefDraft(task="Fix the timeout in sync/clients.py.", criteria=GOOD.criteria)
    facts = repo_facts.lookup(project, draft.task)
    found = lint.check(_order(draft, folder=str(project)), facts=facts)
    missing = next(f for f in found if f.code == "path_not_found")
    assert "sync/clients.py" in missing.message
    assert "sync/client.py" in missing.message


def test_a_file_the_agent_is_asked_to_create_is_not_a_missing_path(project):
    draft = BriefDraft(
        task="Fix the upload in sync/client.py and create docs/sync.md that explains it.",
        criteria=GOOD.criteria,
    )
    facts = repo_facts.lookup(project, draft.task)
    found = lint.check(_order(draft, folder=str(project)), facts=facts)
    assert "path_not_found" not in _codes(found)


def test_a_procedure_is_found_and_a_list_of_requirements_is_not():
    script = BriefDraft(
        task="Fix the upload.\n1. Open sync/client.py.\n2. Run `pytest tests`.\n3. Then commit.",
        criteria=GOOD.criteria,
    )
    wants = BriefDraft(
        task=(
            "Fix the upload.\n1. A note is never lost.\n2. A note is never duplicated.\n"
            "3. The person sees when an upload is retried."
        ),
        criteria=GOOD.criteria,
    )
    assert "step_script" in _codes(lint.check(_order(script)))
    assert "step_script" not in _codes(lint.check(_order(wants)))


def test_a_suspicion_must_be_called_one():
    guess = BriefDraft(
        task="Fix the upload. The cause is most likely the retry loop.", criteria=GOOD.criteria
    )
    labelled = BriefDraft(
        task="Fix the upload. Unverified hypothesis: the retry loop is probably the cause.",
        criteria=GOOD.criteria,
    )
    assert "guess_as_fact" in _codes(lint.check(_order(guess)))
    assert "guess_as_fact" not in _codes(lint.check(_order(labelled)))


def test_a_change_needs_a_done_that_belongs_to_it():
    none = BriefDraft(task="Fix the upload so that no note is lost.")
    generic = BriefDraft(task=none.task, criteria="Tests and typecheck pass.")
    assert "no_done" in _codes(lint.check(_order(none)))
    assert "generic_done" in _codes(lint.check(_order(generic)))
    assert not {"no_done", "generic_done"} & _codes(lint.check(_order(GOOD)))


def test_a_question_needs_no_done():
    draft = BriefDraft(task="Explain how the upload retries work; change nothing.")
    assert "no_done" not in _codes(lint.check(_order(draft)))


def test_shouting_reasoning_requests_and_open_words_are_found():
    draft = BriefDraft(
        task=(
            "Fix the upload and make it better. IMPORTANT: do NOT break anything. NEVER skip "
            "tests. Explain your reasoning step by step."
        ),
        criteria=GOOD.criteria,
    )
    codes = _codes(lint.check(_order(draft)))
    assert {"shouting", "reasoning_request", "left_open"} <= codes


def test_a_git_brake_is_the_persons_to_set():
    draft = BriefDraft(task="Fix the upload. Do not merge.", criteria=GOOD.criteria)
    unasked = lint.check(_order(draft, said="please fix the upload"))
    asked = lint.check(_order(draft, said="fix the upload but do not merge, I approve it myself"))
    assert "git_brake" in _codes(unasked)
    assert "git_brake" not in _codes(asked) | _codes(asked, SEVERITY_NOTE)


def test_without_the_persons_words_a_git_brake_is_only_noted():
    draft = BriefDraft(task="Fix the upload. Do not merge.", criteria=GOOD.criteria)
    found = lint.check(_order(draft))
    assert "git_brake" in _codes(found, SEVERITY_NOTE)
    assert "git_brake" not in _codes(found)


def test_read_only_is_not_added_to_a_request_for_a_change():
    draft = BriefDraft(task="Look into the upload. Report only; change nothing.")
    found = lint.check(_order(draft, said="fix the upload, it is broken"))
    assert "read_only_added" in _codes(found)
    wanted = lint.check(_order(draft, said="only analyse the upload, change nothing"))
    assert "read_only_added" not in _codes(wanted)


def test_a_pointer_into_the_conversation_is_found():
    draft = BriefDraft(task="Fix the bug we talked about, as discussed.", criteria=GOOD.criteria)
    assert "conversation_pointer" in _codes(lint.check(_order(draft)))


def test_a_follow_up_is_not_held_to_a_first_orders_rules(project):
    draft = BriefDraft(task="Thanks. As discussed, please also fix the typo in the label.")
    facts = repo_facts.lookup(project, draft.task)
    found = lint.check(
        _order(draft, folder=str(project), first_order=False), facts=facts
    )
    assert _codes(found) == set()


def test_a_plan_request_is_a_fault_only_for_a_model_that_stops_on_it():
    draft = BriefDraft(
        task="Fix the upload. First write a plan, then share status updates.",
        criteria=GOOD.criteria,
    )
    assert "plan_request" in _codes(lint.check(_order(draft), profiles=[profiles.CODEX]))
    assert "plan_request" not in _codes(lint.check(_order(draft), profiles=[profiles.GEMINI]))


def test_a_brief_without_a_starting_point_is_sent_back_when_the_repository_has_one(project):
    draft = BriefDraft(
        task="The upload of a note times out on a slow connection. Make it survive that.",
        criteria=GOOD.criteria,
    )
    facts = repo_facts.lookup(project, draft.task)
    found = lint.check(_order(draft, said="fix the upload", folder=str(project)), facts=facts)
    assert "no_starting_point" in _codes(found)
    unknown = BriefDraft(task=draft.task + " Starting point unknown.", criteria=GOOD.criteria)
    again = lint.check(_order(unknown, said="fix the upload", folder=str(project)), facts=facts)
    assert "no_starting_point" not in _codes(again)


def test_repeating_a_standing_rule_is_only_noted():
    draft = BriefDraft(
        task="Fix the upload in sync/client.py. Report back in short, plain German.",
        criteria=GOOD.criteria,
    )
    found = lint.check(_order(draft), standing=True)
    assert "standing_repeated" in _codes(found, SEVERITY_NOTE)


def test_looking_into_something_includes_the_fix_unless_the_person_limits_it():
    draft = BriefDraft(task="Investigate the upload.")
    fix_it = "schau dir den upload an und fix das"  # i18n-allow
    only_look = "untersuche nur, warum der upload hängt"  # i18n-allow
    assert lint.kind_of(_order(draft, said=fix_it)) == "implement"
    assert lint.kind_of(_order(draft, said=only_look)) != "implement"


def test_a_brief_for_a_coding_agent_is_written_in_english_unless_they_wish_otherwise():
    german = BriefDraft(
        task=(
            "Mach den Upload der Notizen robust, damit keine Notiz "  # i18n-allow
            "mehr verloren geht. Die Funktion upload wirft bei einem "  # i18n-allow
            "Timeout einen Fehler und die Notiz ist weg."  # i18n-allow
        ),
        criteria=(
            "Ein neuer Test zeigt, dass die Notiz nach einem "  # i18n-allow
            "Timeout nicht verloren ist."  # i18n-allow
        ),
    )
    assert "not_english" in _codes(lint.check(_order(german)))
    wished = Order(
        writer="lead", draft=german, recipient=Recipient(),
        wishes="Schreib die Prompts auf Deutsch",  # i18n-allow
    )
    assert "not_english" not in _codes(lint.check(wished))
    quoting = BriefDraft(
        task=(
            "Uploads lose the note on a timeout. The person said: "
            '"der Upload ist kaputt und die Notizen sind danach weg". '  # i18n-allow
            "Make an upload in sync/client.py survive a timeout."
        ),
        criteria=GOOD.criteria,
    )
    assert "not_english" not in _codes(lint.check(_order(quoting)))
    assert "not_english" not in _codes(lint.check(_order(GOOD)))


def test_a_german_request_that_ends_on_its_verb_is_still_a_change():
    said = "der upload ist kaputt schick einen agenten los der das robust macht"  # i18n-allow
    assert lint.kind_of(_order(BriefDraft(task="Look at the upload."), said=said)) == "implement"


def test_a_path_into_a_folder_whose_name_has_a_space_is_found(tmp_path):
    from dodaios.briefs import repo_facts

    folder = tmp_path / "Personal Notes"
    (folder / "sync").mkdir(parents=True)
    (folder / "sync" / "client.py").write_text("x = 1\n", encoding="utf-8")
    facts = repo_facts.lookup(str(folder), "client", kind="implement")
    def codes(task: str) -> list[str]:
        order = _order(
            BriefDraft(task=task, criteria="`python -m pytest -q` is green."),
            said="setz x auf 2", folder=str(folder),  # i18n-allow: what the person said
        )
        return [f.code for f in lint.check(order, facts=facts)]

    for named in (f"{folder}/sync/client.py", f"`{folder}/sync/client.py`"):
        found = codes(f"Set `x` in {named} to 2, because the export reads it.")
        assert "path_not_found" not in found and "no_starting_point" not in found, (named, found)
    assert "path_not_found" in codes(f"Set `x` in {folder}/sync/missing.py to 2.")
