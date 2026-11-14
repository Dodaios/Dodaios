"""People credited in Co-authored-by trailers reach the contributor wall."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_spec = importlib.util.spec_from_file_location(
    "update_contributors_coauthors_under_test",
    REPO_ROOT / "scripts" / "ci" / "update_contributors.py",
)
assert _spec is not None and _spec.loader is not None
update_contributors = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_contributors)

US, RS, GS = "\x1f", "\x1e", "\x1d"


def _record(sha: str, *trailers: str) -> str:
    return sha + US + RS.join(trailers) + GS


def test_trailers_credit_people_not_ai_agents_or_bots() -> None:
    log = "".join(
        [
            _record(
                "a" * 40,
                "Claude Opus 5.5 <noreply@anthropic.com>",
                "Yannis <132681092+YannisG23@users.noreply.github.com>",
            ),
            _record("b" * 40, "Claude <noreply@anthropic.com>", "Cursor <cursoragent@cursor.com>"),
            _record(
                "c" * 40,
                "merge-train[bot] <41898282+github-actions[bot]@users.noreply.github.com>",
                "Florent <Florent@Example.org>",
                "Florent <florent@example.org>",
            ),
            _record("d" * 40),
        ]
    )

    assert update_contributors.coauthored_commits(log) == {
        "a" * 40: ["132681092+yannisg23@users.noreply.github.com"],
        "c" * 40: ["florent@example.org"],
    }


def test_only_resolved_co_authors_are_credited_and_the_git_author_is_not() -> None:
    commits = {
        "a" * 40: ["132681092+yannisg23@users.noreply.github.com", "unclaimed@example.org"],
        "c" * 40: ["florent@example.org", "noreply@anthropic.com"],
        "e" * 40: ["132681092+yannisg23@users.noreply.github.com"],
    }
    maintainer = {
        "email": "1+maintainer@users.noreply.github.com",
        "user": {"login": "maintainer", "avatarUrl": "https://avatars.example/m"},
    }
    resolved = {
        "a" * 40: [
            maintainer,
            {
                "email": "132681092+YannisG23@users.noreply.github.com",
                "user": {"login": "YannisG23", "avatarUrl": "https://avatars.example/y"},
            },
            {"email": "unclaimed@example.org", "user": None},
        ],
        "c" * 40: [
            maintainer,
            {
                "email": "Florent@Example.org",
                "user": {"login": "florent-dev", "avatarUrl": "https://avatars.example/f"},
            },
            {
                "email": "noreply@anthropic.com",
                "user": {"login": "claude", "avatarUrl": "https://avatars.example/c"},
            },
        ],
        "e" * 40: [
            maintainer,
            {
                "email": "132681092+yannisg23@users.noreply.github.com",
                "user": {"login": "YannisG23", "avatarUrl": "https://avatars.example/y"},
            },
        ],
    }

    credited = update_contributors.credit_coauthors(commits, resolved)

    assert sorted((p["login"], p["contributions"]) for p in credited) == [
        ("YannisG23", 2),
        ("florent-dev", 1),
    ]
    assert all(p["avatar_url"] for p in credited)


def test_co_authors_join_the_wall_and_add_to_what_others_counted() -> None:
    commits = [
        {
            "login": "maintainer",
            "avatar_url": "https://avatars.example/m?v=4",
            "type": "User",
            "contributions": 900,
        },
        {
            "login": "PilarJ",
            "avatar_url": "https://avatars.example/p?v=4",
            "type": "User",
            "contributions": 4,
        },
    ]
    pull_authors = [
        {
            "login": "Uddoo",
            "avatar_url": "https://avatars.example/u?v=4",
            "type": "User",
            "contributions": 1,
            "git_names": [],
        },
    ]
    coauthors = [
        {
            "login": "PilarJ",
            "avatar_url": "https://avatars.example/p?v=4",
            "type": "User",
            "contributions": 2,
        },
        {
            "login": "YannisG23",
            "avatar_url": "https://avatars.example/y?v=4",
            "type": "User",
            "contributions": 1,
        },
        {
            "login": "claude",
            "avatar_url": "https://avatars.example/c",
            "type": "User",
            "contributions": 40,
        },
    ]

    people = update_contributors.combine(commits, pull_authors, coauthors)

    assert [(p["login"], p["contributions"]) for p in people] == [
        ("maintainer", 900),
        ("PilarJ", 6),
        ("Uddoo", 1),
        ("YannisG23", 1),
    ]
    block = update_contributors.render(people)
    assert 'alt="YannisG23"' in block and "claude" not in block


def test_a_shallow_clone_is_refused_instead_of_undercounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(update_contributors, "_git", lambda *args: "true\n")

    with pytest.raises(SystemExit, match="complete clone"):
        update_contributors.fetch_coauthor_credits()
