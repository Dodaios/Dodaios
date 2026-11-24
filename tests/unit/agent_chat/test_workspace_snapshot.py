"""A snapshot of a checkout sees every edit, also one git could take for unchanged."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from dodaios.agent_chat.team.workspace import GitWorkspace

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(folder), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def test_a_same_size_edit_in_the_second_of_the_index_is_seen(tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    target = folder / "other.py"
    target.write_text("X = 1\n", encoding="utf-8")
    # The file and the index carry the same time stamp, a while ago: the
    # index was written in the second the file was last changed.
    past = time.time_ns() - 30 * 1_000_000_000
    os.utime(target, ns=(past, past))
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "first")
    committed = _git(folder, "rev-parse", "HEAD^{tree}")
    index = folder / ".git" / "index"

    # An agent overwrites the file with text of the same size, in that same
    # second: by size and time stamp it looks unchanged, and only git's
    # re-read of entries as new as the index itself ("racily clean") finds it.
    target.write_text("X = 3\n", encoding="utf-8")
    os.utime(target, ns=(past, past))
    os.utime(index, ns=(past, past))

    tree = GitWorkspace().snapshot(str(folder))
    assert tree and tree != committed
    assert _git(folder, "diff", "--name-only", committed, tree) == "other.py"
    # The person's own index is left as it was.
    assert index.stat().st_mtime_ns == past
