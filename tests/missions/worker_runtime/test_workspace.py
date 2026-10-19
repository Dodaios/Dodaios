"""Tests for dodaios.missions.worker_runtime.workspace (the managed AGENTS.md marker)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dodaios.missions.worker_runtime.workspace import (
    _agents_md,
    materialize_worker_contract,
)


def test_agents_md_is_a_short_marker_with_the_mission_id() -> None:
    md = _agents_md("m-abc-123")
    assert "managed by Dodaios" in md
    assert "m-abc-123" in md
    assert len(md) < 300


# --- materialize_worker_contract (CRIT-2 from 2026-05-17 audit) ----------


def _init_git_repo(repo: Path) -> None:
    """Create an empty git repo at ``repo`` and seed it with one commit
    so subsequent ``git worktree add`` calls succeed. Used to give
    ``materialize_worker_contract`` a real worktree fixture to write
    the .git/info/exclude file into."""
    repo.mkdir(parents=True, exist_ok=True)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    import os
    env = {**os.environ, **env}
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "commit", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(  # noqa: S603 - controlled
            cmd, cwd=str(repo), check=True,
            capture_output=True, env=env,
        )


def test_materialize_writes_agents_md_in_worktree(tmp_path: Path) -> None:
    """Worker contract must land in the worktree root itself (not in
    MISSION_STATE_DIR/workspace) so claude --print picks it up via
    --add-dir."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    # Use the repo as a fake worktree -- materialize_worker_contract
    # doesn't care whether the directory is a worktree or the main
    # checkout, only that `git rev-parse --git-dir` works.
    out = materialize_worker_contract(repo, mission_id="m-test-001")
    assert out == repo / "AGENTS.md"
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "m-test-001" in body, "mission id must appear in the file"
    assert "managed by Dodaios" in body


def test_materialize_adds_agents_md_to_local_exclude(tmp_path: Path) -> None:
    """The contract must not pollute the diff -- it goes into
    .git/info/exclude (local-only, per-worktree)."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    materialize_worker_contract(repo, mission_id="m-test-002")
    exclude = repo / ".git" / "info" / "exclude"
    assert exclude.is_file(), f"exclude not written at {exclude}"
    assert "AGENTS.md" in exclude.read_text(encoding="utf-8")


def test_materialize_is_idempotent_no_duplicate_exclude_entries(
    tmp_path: Path,
) -> None:
    """Calling twice (e.g. resumed mission) must not duplicate the
    exclude entry or pollute the file."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    materialize_worker_contract(repo, mission_id="m-a")
    materialize_worker_contract(repo, mission_id="m-b")
    exclude_text = (repo / ".git" / "info" / "exclude").read_text(
        encoding="utf-8"
    )
    occurrences = exclude_text.count("AGENTS.md")
    assert occurrences == 1, (
        f"exclude entry must be deduped, got {occurrences} occurrences"
    )
    # Second call overwrote the AGENTS.md with the new mission id.
    body = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "m-b" in body
    assert "m-a" not in body


def test_materialize_preserves_existing_exclude_entries(tmp_path: Path) -> None:
    """User-authored exclude entries (e.g. local IDE droppings) must
    survive a contract materialisation."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("# user note\n*.swp\n", encoding="utf-8")
    materialize_worker_contract(repo, mission_id="m-keep")
    text = exclude.read_text(encoding="utf-8")
    assert "*.swp" in text
    assert "# user note" in text
    assert "AGENTS.md" in text


def test_materialize_rejects_missing_worktree(tmp_path: Path) -> None:
    """Refuses to write into a path that does not exist -- caller is
    misusing the helper."""
    with pytest.raises(FileNotFoundError):
        materialize_worker_contract(tmp_path / "nope", mission_id="m")


def test_materialize_rejects_empty_mission_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    with pytest.raises(ValueError):
        materialize_worker_contract(repo, mission_id="   ")


def test_materialize_survives_non_git_dir(tmp_path: Path) -> None:
    """If `git rev-parse --git-dir` fails (no .git, broken repo), the
    AGENTS.md still gets written -- the gitignore step is best-effort
    and must not propagate failures up to the mission runtime."""
    plain = tmp_path / "plain"
    plain.mkdir()
    out = materialize_worker_contract(plain, mission_id="m-no-git")
    assert out.is_file()
    assert "m-no-git" in out.read_text(encoding="utf-8")


def test_materialize_writes_lf_utf8_without_bom(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    raw = materialize_worker_contract(plain, mission_id="m-lf").read_bytes()
    assert b"\r\n" not in raw
    assert not raw.startswith(b"\xef\xbb\xbf")
