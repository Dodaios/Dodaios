"""What is read from the repository and what is remembered of the person's words."""

from __future__ import annotations

import subprocess

from dodaios.briefs import BriefDraft, Order, Recipient, glossary, kit, repo_facts


def test_starting_points_come_from_what_stands_in_the_files(project):
    facts = repo_facts.lookup(project, "the upload of a note times out on a slow connection")
    assert facts.known and facts.content_match
    assert facts.starting_points[0].path == "sync/client.py"
    assert "slow connection" in facts.starting_points[0].lines


def test_the_projects_own_checks_come_first_then_its_manifests(project):
    facts = repo_facts.lookup(project, "anything")
    assert facts.checks[0] == "python scripts/done_gate.py"
    assert "python -m pytest -q -x -p no:cacheprovider" in facts.checks
    assert "npm run typecheck (in ui)" in facts.checks
    assert facts.frontend_roots == ["ui"]


def test_a_check_command_may_start_with_a_path_to_its_interpreter(project):
    (project / "AGENTS.md").write_text(
        "You are done when `/opt/app/.venv/bin/python -m pytest -q` passes.\n", encoding="utf-8"
    )
    assert repo_facts.house_checks(project)[0] == "/opt/app/.venv/bin/python -m pytest -q"
    from dodaios.briefs import done

    [point] = done.criteria_of("x", "`/opt/app/.venv/bin/python -m pytest -q` passes.")
    assert point.kind == "command"


def test_a_folder_that_does_not_exist_gives_no_facts_and_no_error(tmp_path):
    facts = repo_facts.lookup(tmp_path / "nowhere", "fix it")
    assert not facts.known and facts.starting_points == [] and facts.checks == []
    assert repo_facts.lookup("", "fix it").folder == ""


def test_path_checks_know_bare_names_and_suggest_the_nearest_real_path(project):
    facts = repo_facts.lookup(project, "upload")
    assert repo_facts.path_exists(facts, "sync/client.py")
    assert repo_facts.path_exists(facts, "client.py")
    assert repo_facts.path_exists(facts, "@ui/src/ReminderRail.tsx")
    assert not repo_facts.path_exists(facts, "sync/clients.py")
    assert repo_facts.nearest(facts, "src/ReminderRail.tsx") == ["ui/src/ReminderRail.tsx"]
    assert repo_facts.nearest(facts, "sync/clients.py") == ["sync/client.py"]


def test_a_git_repository_is_searched_with_git(project):
    subprocess.run(["git", "init", "-q", str(project)], check=True)  # noqa: S603, S607
    subprocess.run(["git", "-C", str(project), "add", "-A"], check=True)  # noqa: S603, S607
    facts = repo_facts.lookup(project, "the upload times out on a slow connection")
    assert facts.starting_points and facts.starting_points[0].path == "sync/client.py"


def test_the_glossary_remembers_a_word_per_project_and_finds_it_misheard(briefs_on, project):
    rail = "the left rail, ui/src/ReminderRail.tsx"
    assert glossary.learn(project, "Seitenleiste", rail)  # i18n-allow
    assert glossary.learn(project, "Dodaios", "the app itself")
    found = glossary.lookup(project, "die seitenleiste sieht komisch aus")  # i18n-allow
    assert [e.said for e in found] == ["Seitenleiste"]  # i18n-allow
    misheard = glossary.lookup(project, "bei Todaios stimmt was nicht")  # i18n-allow
    assert [e.said for e in misheard] == ["Dodaios"]
    assert glossary.lookup(project, "nothing of the kind") == []
    assert glossary.entries(project)[0].hits == 1


def test_a_known_word_gets_its_new_meaning_and_can_be_forgotten(briefs_on, project):
    glossary.learn(project, "Seitenleiste", "the left rail")  # i18n-allow
    glossary.learn(project, "seitenleiste", "the options rail")  # i18n-allow
    assert [e.means for e in glossary.entries(project)] == ["the options rail"]
    listed = glossary.all_projects()
    assert listed[0]["entries"][0]["means"] == "the options rail"
    assert glossary.forget_in_project(listed[0]["project"], "Seitenleiste") is True  # i18n-allow
    assert glossary.entries(project) == [] and glossary.all_projects() == []
    assert glossary.learn(project, "", "x") is None


def test_the_glossary_file_is_named_by_a_hash_never_by_the_project(briefs_on, project):
    glossary.learn(project, "wake thing", "the wake word detector")
    path = glossary.store_path(project)
    assert path.exists() and len(path.stem) == 24
    assert "notes-app" not in path.name


def test_the_kit_holds_what_a_writer_needs_before_it_writes(briefs_on, project):
    glossary.learn(project, "Hochladen", "upload() in sync/client.py")  # i18n-allow
    order = Order(
        writer="lead",
        draft=BriefDraft(task="the upload of a note breaks on a slow connection"),
        recipient=Recipient(cli="codex", folder=str(project)),
        person_words="das Hochladen ist kaputt, irgendwie",  # i18n-allow
    )
    made = kit.build(order, with_draft=False).as_dict()
    assert made["kind_of_work"] == "implement" or made["kind_of_work"] == "neutral"
    assert made["starting_points"][0]["path"] == "sync/client.py"
    assert made["their_words_mean"] == [
        {"said": "Hochladen", "means": "upload() in sync/client.py"}  # i18n-allow
    ]
    assert {row["said"] for row in made["their_words_leave_open"]} >= {"kaputt"}  # i18n-allow
    assert made["make_precise"][0]["field"] == "a defect"
    assert made["open_points"][0]["question_for_the_person"] == "What should happen instead?"
    assert "Codex" in made["recipient"]["recipient"]
    assert made["effort"]["level"] in ("medium", "high")
    assert "standing rules" in made["agent_already_knows"]


def test_a_look_up_never_waits_for_a_slow_file_index(project, monkeypatch):
    from dodaios.agentic_ide import file_index

    # The first listing of a very large folder: started, not there yet.
    monkeypatch.setattr(file_index, "cached_index", lambda root: None)
    monkeypatch.setattr(file_index, "prime_index", lambda root: None)
    monkeypatch.setattr(repo_facts, "_INDEX_WAIT_S", 0.1)
    facts = repo_facts.lookup(project, "the upload times out")
    assert facts.known is False and facts.starting_points == []
    # What the project's own files say needs no index.
    assert facts.checks[0] == "python scripts/done_gate.py"
