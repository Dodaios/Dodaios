"""Project briefs, test-command detection, triage and the intake store."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

from dodaios.self_build.code import brief as brief_mod
from dodaios.self_build.code import commands, triage
from dodaios.self_build.code.github import PullRef, Viewer
from dodaios.self_build.code.store import CodeStore

from .code_sandbox import make_issue, sandbox


@pytest.fixture
def store(tmp_path: Path) -> CodeStore:
    book = CodeStore(tmp_path / "self_build_code.db")
    yield book
    book.close()


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(commands, "_python", lambda folder: sys.executable)
    return sandbox(tmp_path)


def test_brief_rebuilds_only_the_parts_that_changed(store: CodeStore, work: Path) -> None:
    brief, rebuilt = brief_mod.refresh(store, work, repo="me/proj")
    assert set(rebuilt) == set(brief_mod.LOCAL_PARTS)
    assert brief.test_commands[0][1:3] == ["-m", "pytest"]
    assert brief.default_branch == "main"
    assert "AGENTS.md" in brief.parts["conventions"]["files"]
    assert brief.parts["activity"]["mine"] == ["initial"]
    _, rebuilt = brief_mod.refresh(store, work, repo="me/proj")
    assert rebuilt == []
    (work / "AGENTS.md").write_text("Use type hints. Keep it short.\n", encoding="utf-8")
    _, rebuilt = brief_mod.refresh(store, work, repo="me/proj")
    assert rebuilt == ["conventions"]
    text = brief_mod.load(store, work).render()
    assert "Keep it short." in text and "Tests:" in text


def test_triage_rules() -> None:
    fit = triage.triage(make_issue(), login="me", profile={}, has_tests=True)
    assert fit.fit and fit.signal == "labelled agent"
    unlabelled = make_issue(labels=(), title="Add a mul function to calc")
    assert not triage.triage(unlabelled, login="me", profile={}, has_tests=True).fit
    merged = {"merged": [{"number": 7, "title": "Add a sub function to calc", "labels": []}]}
    like = triage.triage(unlabelled, login="me", profile=merged, has_tests=True)
    assert like.fit and like.signal == "like #7"
    assert not triage.triage(make_issue(), login="me", profile={}, has_tests=False).fit
    pulls = [PullRef(number=3, title="Add mul (#1)")]
    assert not triage.triage(make_issue(), login="me", profile={}, pulls=pulls, has_tests=True).fit
    closed = {"closed": [{"number": 1}, {"number": 2}]}
    assert not triage.triage(make_issue(), login="me", profile=closed, has_tests=True).fit
    assert not triage.triage(
        replace(make_issue(), state="CLOSED"), login="me", profile={}, has_tests=True
    ).fit


def test_test_commands_come_from_the_project_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert commands.detect(empty)["test"] == []
    node = tmp_path / "node"
    node.mkdir()
    (node / "package.json").write_text('{"scripts": {"test": "vitest run"}}', encoding="utf-8")
    (node / "package-lock.json").write_text("{}", encoding="utf-8")
    found = commands.detect(node)
    assert found["test"] == [["npm", "test", "--silent"]]
    assert found["setup"] == [["npm", "ci"]]
    (node / "package.json").write_text(
        '{"scripts": {"test": "echo \\"Error: no test specified\\" && exit 1"}}', encoding="utf-8"
    )
    assert commands.detect(node)["test"] == []
    rust = tmp_path / "rust"
    rust.mkdir()
    (rust / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (rust / ".github" / "workflows").mkdir(parents=True)
    (rust / ".github" / "workflows" / "ci.yml").write_text(
        "jobs:\n  t:\n    steps:\n      - run: cargo test --all\n", encoding="utf-8"
    )
    found = commands.detect(rust)
    assert found["test"] == [["cargo", "test", "--quiet"]]
    assert found["ci"] == ["ci.yml: cargo test --all"]


def test_outcomes_fold_into_the_brief(store: CodeStore, work: Path) -> None:
    brief_mod.refresh(store, work, repo="me/proj")
    store.add_to_profile("Me/Proj", "merged", {"number": 3, "title": "a", "changed": True})
    store.add_to_profile("me/proj", "lessons", {"number": 4, "lesson": "tests were slow"})
    profile = store.profile("me/proj")
    brief_mod.note_outcomes(store, work, profile)
    stored = brief_mod.load(store, work)
    assert stored.parts["outcomes"]["changed"] == ["#3 a"]
    text = stored.render()
    assert "tests were slow" in text and "#3 a" in text
    # A refresh of the local parts keeps what the loop learned.
    (work / "AGENTS.md").write_text("New rules.\n", encoding="utf-8")
    again, _ = brief_mod.refresh(store, work, repo="me/proj")
    assert again.parts["outcomes"]["lessons"] == ["tests were slow"]


def test_store_remembers_issues_and_polls(store: CodeStore) -> None:
    assert store.issue("me/proj", 1) is None
    store.put_issue("Me/Proj", 1, updated_at="t1", verdict="unfit", reason="assigned", issue={})
    assert store.issue("me/proj", 1)["verdict"] == "unfit"
    assert store.last_poll("me/proj") == 0
    store.set_poll("me/proj", 123)
    assert store.last_poll("ME/PROJ") == 123


def test_only_the_persons_own_accounts_count_as_owners() -> None:
    who = Viewer(login="Me", admin_orgs=frozenset({"my-org"}))
    assert who.owns("me/proj") and who.owns("My-Org/site")
    assert not who.owns("someone/lib") and not who.owns("")
