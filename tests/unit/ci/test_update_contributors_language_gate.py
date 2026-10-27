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
