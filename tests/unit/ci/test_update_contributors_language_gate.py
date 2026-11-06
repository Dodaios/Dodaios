"""The contributor avatar wall must never trip the output-language gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update_contributors = _load(
    "update_contributors_under_test", REPO_ROOT / "scripts" / "ci" / "update_contributors.py"
)
check_no_new_german = _load(
    "check_no_new_german_under_test", REPO_ROOT / "scripts" / "ci" / "check_no_new_german.py"
)


def _person(login: str) -> dict:
    return {"login": login, "avatar_url": f"https://avatars.example/{login}?v=4"}


def test_german_looking_login_passes_the_language_gate() -> None:
    # A real contributor login that reads as German.
    logins = ["dannyward630", "ANO3457", "Idee-Wird-App", "Uddoo"]  # i18n-allow
    block = update_contributors.render([_person(login) for login in logins])

    added = [("README.md", n, line) for n, line in enumerate(block.splitlines(), start=1)]
    assert check_no_new_german.find_violations(added, []) == []


def test_every_row_carries_the_escape_marker() -> None:
    people = [_person(f"user{i}") for i in range(update_contributors.PER_ROW * 2 + 1)]
    rows = update_contributors.render(people).splitlines()

    assert len(rows) == 3
    assert all(row.endswith("<!-- i18n-allow -->") for row in rows)


def test_user_cell_keeps_the_avatar_markup() -> None:
    block = update_contributors.render(
        [{"login": "octocat", "avatar_url": "https://avatars.example/octocat?v=4"}]
    )

    assert block == (
        '<a href="https://github.com/octocat">'
        '<img src="https://avatars.example/octocat?v=4&s=48" '
        'width="48" height="48" alt="octocat"></a> <!-- i18n-allow -->'
    )


def test_wall_includes_pull_authors_and_unlinked_names_without_emails() -> None:
    commits = [
        {
            "login": "rubenluetke10-beep",
            "avatar_url": "https://avatars.example/r?v=4",
            "type": "User",
            "contributions": 100,
        },
        {
            "login": "dependabot[bot]",
            "type": "Bot",
            "contributions": 20,
            "avatar_url": "https://avatars.example/bot",
        },
        {
            "login": "claude",
            "type": "User",
            "contributions": 2,
            "avatar_url": "https://avatars.example/claude",
        },
        {
            "type": "Anonymous",
            "name": "Joana Lütke",  # i18n-allow
            "email": "secret@joanas-mbp.fritz.box",
            "contributions": 14,
        },
        {
            "type": "Anonymous",
            "name": "Dennis Heide de Ramirez",
            "email": "one@local",
            "contributions": 6,
        },
        {
            "type": "Anonymous",
            "name": "Dennis Heide de Ramirez",
            "email": "two@local",
            "contributions": 2,
        },
    ]
    pull_authors = [
        {
            "login": "PilarJ",
            "avatar_url": "https://avatars.example/p?v=4",
            "type": "User",
            "contributions": 3,
            "git_names": ["Jakub Pilař"],
        },
        {
            "login": "dennisheidederamirez-coder",
            "avatar_url": "https://avatars.example/d?v=4",
            "type": "User",
            "contributions": 1,
            "git_names": ["Dennis Heide de Ramirez"],
        },
        {
            "login": "app/dependabot",
            "type": "Bot",
            "contributions": 9,
            "git_names": [],
        },
    ]

    people = update_contributors.combine(commits, pull_authors)
    shown = [person.get("login") or person.get("name") for person in people]

    assert shown == [
        "rubenluetke10-beep",
        "Joana Lütke",  # i18n-allow
        "dennisheidederamirez-coder",
        "PilarJ",
    ]
    assert people[2]["contributions"] == 8

    block = update_contributors.render(people)
    assert "secret@joanas-mbp" not in block
    assert "one@local" not in block
    assert "claude" not in block
    assert "dependabot" not in block
    assert "Commits not linked to a GitHub account: " in block
    assert "Joana Lütke" in block  # i18n-allow
    assert "PilarJ" in block
    added = [("README.md", n, line) for n, line in enumerate(block.splitlines(), start=1)]
    assert check_no_new_german.find_violations(added, []) == []
