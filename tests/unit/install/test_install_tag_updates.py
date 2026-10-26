"""Update the real POSIX installer block against shallow local Git remotes."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or BASH is None,
    reason="the POSIX installer requires a usable bash",
)


def _git(directory: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 -- only test-owned repositories and arguments
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _update_block() -> str:
    source = (REPO / "install" / "install.sh").read_text(encoding="utf-8")
    comment = source.index("# The fetch only writes inside .git")
    start = source.index('if [ -d "$INSTALL_DIR/.git" ]; then', comment)
    end = source.index("\n# WAVE 5", start)
    return source[start:end]


def _run_update(directory: Path, checkout: Path, ref: str) -> subprocess.CompletedProcess[str]:
    driver = directory / "update.sh"
    driver.write_text(
        """set -eu
GIT_NET_OPTS=''
GIT_VERBOSITY=--quiet
pretty_git() { "$@"; }
retarget_legacy_origin() { :; }
stop_running_app() { :; }
migrate_install_dir() { :; }
ok() { printf '%s\\n' "$*"; }
note() { printf '%s\\n' "$*"; }
salvage_reclone() { printf 'unexpected salvage\\n' >&2; return 1; }
fetch_payload() { return 1; }
"""
        + _update_block(),
        encoding="utf-8",
    )
    assert BASH is not None
    return subprocess.run(  # noqa: S603 -- extracted installer block, isolated local Git fixtures
        [BASH, str(driver)],
        env={**os.environ, "INSTALL_DIR": str(checkout), "BRANCH": ref},
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize(
    ("initial_ref", "target_ref"),
    [
        ("v1.0.0", "v2.0.0"),
        ("v1.0.0", "main"),
        ("main", "v2.0.0"),
        ("main", "main"),
    ],
)
def test_shallow_checkout_updates_in_place(
    tmp_path: Path, initial_ref: str, target_ref: str
) -> None:
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "config", "user.name", "Installer test")
    _git(remote, "config", "user.email", "installer@example.invalid")
    version = remote / "version.txt"
    version.write_text("one\n", encoding="utf-8")
    _git(remote, "add", "version.txt")
    _git(remote, "commit", "-qm", "first release")
    _git(remote, "tag", "v1.0.0")

    checkout = tmp_path / "install"
    _git(
        tmp_path,
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--branch",
        initial_ref,
        remote.as_uri(),
        str(checkout),
    )
    assert _git(checkout, "rev-parse", "--is-shallow-repository") == "true"
    data = checkout / "data"
    data.mkdir()
    sentinel = data / "user-state.txt"
    sentinel.write_text("keep this state\n", encoding="utf-8")

    version.write_text("two\n", encoding="utf-8")
    _git(remote, "commit", "-qam", "second release")
    _git(remote, "tag", "v2.0.0")
    expected = _git(remote, "rev-parse", target_ref)

    # Repeating the update must remain in place instead of accumulating backups.
    for _ in range(2):
        result = _run_update(tmp_path, checkout, target_ref)
        assert result.returncode == 0, result.stdout + result.stderr
        assert _git(checkout, "rev-parse", "HEAD") == expected
        assert (checkout / "version.txt").read_text(encoding="utf-8") == "two\n"
        assert sentinel.read_text(encoding="utf-8") == "keep this state\n"
        assert "unexpected salvage" not in result.stderr
        assert not list(tmp_path.glob("install.stale-*"))
