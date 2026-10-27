"""The one-liner installs the newest published release unless a ref is named.

A release tag carries the frontend bundle built from its own sources, so main
no longer has to track one. main stays the fallback when no release can be
looked up. The release API is faked by a local HTTP server, so nothing here
touches the network.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = ROOT / "install" / "install.sh"
INSTALL_PS1 = ROOT / "install" / "install.ps1"
REPO_URL = "https://github.com/Example/Product.git"


def _find_bash() -> str | None:
    git = shutil.which("git")
    if git:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe", "../usr/bin/bash.exe"):
            candidate = (Path(git).parent / rel).resolve()
            if candidate.exists():
                return str(candidate)
    bash = shutil.which("bash")
    if bash and not any(part in bash.lower() for part in ("windowsapps", "system32")):
        return bash
    return None


BASH = _find_bash()
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_curl = pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell on this host")


def _block(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    body = text.split("# --- install-ref begin", 1)[1].split("# --- install-ref end", 1)[0]
    return body.split("\n", 1)[1]


@contextlib.contextmanager
def _fake_api(tmp_path: Path, tag: str | None) -> Iterator[str]:
    """Serve ``/repos/Example/Product/releases/latest`` on a local port.

    HTTP, not file://: PowerShell 7's Invoke-RestMethod reads http(s) only.
    """
    root = tmp_path / "api"
    latest = root / "repos" / "Example" / "Product" / "releases" / "latest"
    latest.parent.mkdir(parents=True)
    if tag is not None:
        # The API pretty-prints, one key per line, like this.
        latest.write_text(json.dumps({"tag_name": tag, "draft": False}, indent=2), "utf-8")
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    import os

    return subprocess.run(  # noqa: S603 - test-controlled command
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env={**os.environ, **env},
        creationflags=NO_WINDOW_CREATIONFLAGS,
        check=False,
    )


def _sh(tmp_path: Path, *, ref: str, tag: str | None, repo: str = REPO_URL) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "ref.sh"
    script.write_text(
        "set -euo pipefail\n"
        + _block(INSTALL_SH)
        + '\nresolve_install_ref\nprintf "%s\\n%s\\n" "$BRANCH" "$(ref_archive_path)"\n',
        encoding="utf-8",
        newline="\n",
    )
    with _fake_api(tmp_path, tag) as api:
        result = _run(
            [str(BASH), str(script)],
            {"BRANCH": ref, "REPO_URL": repo, "INSTALLER_TEST_RELEASE_API": api},
        )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


@needs_bash
@needs_curl
def test_sh_installs_the_newest_release_by_default(tmp_path: Path) -> None:
    assert _sh(tmp_path, ref="", tag="v4.2.0") == ["v4.2.0", "refs/tags/v4.2.0"]


@needs_bash
@needs_curl
@pytest.mark.parametrize("tag", [None, "nightly", "v4.2"])
def test_sh_falls_back_to_main_without_a_stable_release(tmp_path: Path, tag) -> None:
    assert _sh(tmp_path, ref="", tag=tag) == ["main", "refs/heads/main"]


@needs_bash
def test_sh_keeps_an_explicit_ref_and_ignores_foreign_hosts(tmp_path: Path) -> None:
    assert _sh(tmp_path, ref="feature/x", tag="v4.2.0") == ["feature/x", "refs/heads/feature/x"]
    foreign = "https://example.org/p.git"
    assert _sh(tmp_path / "b", ref="", tag="v4.2.0", repo=foreign)[0] == "main"


def _ps(tmp_path: Path, *, ref: str, tag: str | None) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "ref.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"$Branch = '{ref}'\n$RepoUrl = '{REPO_URL}'\n"
        + _block(INSTALL_PS1)
        + "\n$Branch = Resolve-InstallRef\nWrite-Output $Branch\n"
        + "Write-Output (Get-RefArchivePath)\n",
        encoding="utf-8",
    )
    with _fake_api(tmp_path, tag) as api:
        result = _run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            {"INSTALLER_TEST_RELEASE_API": api},
        )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


@needs_powershell
def test_ps1_installs_the_newest_release_by_default(tmp_path: Path) -> None:
    assert _ps(tmp_path, ref="", tag="v4.2.0") == ["v4.2.0", "refs/tags/v4.2.0"]


@needs_powershell
def test_ps1_falls_back_to_main_and_keeps_an_explicit_ref(tmp_path: Path) -> None:
    assert _ps(tmp_path / "a", ref="", tag=None) == ["main", "refs/heads/main"]
    assert _ps(tmp_path / "b", ref="feature/x", tag="v4.2.0")[0] == "feature/x"


def test_both_installers_resolve_the_ref_before_fetching() -> None:
    sh = INSTALL_SH.read_text(encoding="utf-8")
    assert re.search(r'^BRANCH="\$\{JARVIS_INSTALL_REF:-\}"$', sh, re.M)
    assert sh.index("\nresolve_install_ref\n") < sh.index('if [ -d "$INSTALL_DIR/.git" ]; then')
    ps1 = INSTALL_PS1.read_text(encoding="utf-8")
    assert "$Branch = Resolve-InstallRef" in ps1
    assert ps1.index("$Branch = Resolve-InstallRef") < ps1.index(
        "if (Test-Path (Join-Path $InstallDir '.git')) {"
    )
    # An update run lands on what it fetched, a tag or a branch alike.
    assert "& git reset --quiet --hard FETCH_HEAD" in ps1
    assert 'reset --hard "origin/$Branch"' not in ps1
