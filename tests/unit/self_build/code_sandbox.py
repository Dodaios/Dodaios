"""Sandbox repositories for the code builder's tests: a bare "GitHub" remote whose
path holds ``github.com/<owner>/<name>`` (so the origin parser reads it as that
repository) and a clone the person works in. Nothing reaches the network."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from dodaios.self_build.code.github import Issue

ISSUE_BODY = "Add a mul(a, b) function next to add in calc.py, with a test for it."


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout.strip()


def sandbox(tmp_path: Path, owner: str = "me", name: str = "proj") -> Path:
    """A bare "GitHub" remote (its path holds github.com/<owner>/<name>) and a clone."""
    remote = tmp_path / "github.com" / owner / f"{name}.git"
    remote.mkdir(parents=True)
    git(remote, "init", "--bare", "--initial-branch=main")
    work = tmp_path / "work" / name
    work.mkdir(parents=True)
    git(work, "init", "--initial-branch=main")
    git(work, "config", "user.name", "Test Person")
    git(work, "config", "user.email", "person@example.com")
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (work / "tests").mkdir()
    (work / "tests" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8"
    )
    (work / "pyproject.toml").write_text(
        '[project]\nname = "proj"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        encoding="utf-8",
    )
    (work / "AGENTS.md").write_text("Use type hints in new code.\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-m", "initial")
    git(work, "remote", "add", "origin", remote.as_posix())
    git(work, "push", "-u", "origin", "main")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    git(work, "remote", "set-head", "origin", "main")
    return work


def make_issue(number: int = 1, **overrides: Any) -> Issue:
    values: dict[str, Any] = {
        "number": number,
        "title": "Add a mul function",
        "body": ISSUE_BODY,
        "url": f"https://github.com/me/proj/issues/{number}",
        "author": "me",
        "labels": ("agent",),
        "updated_at": "2026-10-19T10:00:00Z",
    }
    values.update(overrides)
    return Issue(**values)
