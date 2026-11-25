"""Scratch folders in the temp directory belong to this user only.

On Linux the temp directory is shared by every account. Conversation
exports and the settings file handed to a coding CLI used to go into a fixed
folder name there, which another account could read or prepare in advance.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from dodaios.core.private_tmp import private_temp_folder

posix_only = pytest.mark.skipif(os.name == "nt", reason="the temp directory is per user here")


@pytest.fixture
def shared_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def test_folder_is_created_and_reused(shared_tmp: Path) -> None:
    first = private_temp_folder("dodaios-test-scratch")
    second = private_temp_folder("dodaios-test-scratch")

    assert first == second
    assert first.is_dir()
    assert first.parent == shared_tmp


@posix_only
def test_folder_is_named_for_the_user_and_owner_only(shared_tmp: Path) -> None:
    folder = private_temp_folder("dodaios-test-scratch")

    assert folder.name == f"dodaios-test-scratch-{os.getuid()}"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@posix_only
def test_a_too_open_folder_is_closed_again(shared_tmp: Path) -> None:
    loose = shared_tmp / f"dodaios-test-scratch-{os.getuid()}"
    loose.mkdir(mode=0o777)
    os.chmod(loose, 0o777)  # noqa: S103 - the too-open state under test

    folder = private_temp_folder("dodaios-test-scratch")

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


@posix_only
def test_a_link_someone_prepared_is_refused(shared_tmp: Path) -> None:
    elsewhere = shared_tmp / "elsewhere"
    elsewhere.mkdir()
    (shared_tmp / f"dodaios-test-scratch-{os.getuid()}").symlink_to(elsewhere)

    with pytest.raises(OSError, match="someone else"):
        private_temp_folder("dodaios-test-scratch")


@posix_only
def test_a_folder_of_another_account_is_refused(
    shared_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = os.getuid()
    (shared_tmp / f"dodaios-test-scratch-{mine + 1}").mkdir()
    # The folder exists and is a directory, but its owner is not "us".
    monkeypatch.setattr(os, "getuid", lambda: mine + 1)

    with pytest.raises(OSError, match="someone else"):
        private_temp_folder("dodaios-test-scratch")


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the shared temp directory")
def test_cli_flag_file_lands_in_the_private_folder(
    shared_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.agent_chat import runner_cli

    monkeypatch.setattr(runner_cli, "_is_batch", lambda _path: True)

    value = runner_cli._json_flag_value(["claude.cmd"], '{"hooks": "Bash|Read"}')

    path = Path(value)
    assert path.parent.name == f"dodaios-claude-flags-{os.getuid()}"
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.read_text(encoding="utf-8") == '{"hooks": "Bash|Read"}'
