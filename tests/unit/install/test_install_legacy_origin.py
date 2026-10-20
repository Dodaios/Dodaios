"""A re-run quick installer points a pre-rename checkout at the current repository.

The in-app updater identifies a managed install by its stored ``origin``. A
checkout cloned before the GitHub rename keeps the old address, so the shell
installers rewrite it before they fetch. Runs the REAL blocks extracted from
``install/install.sh`` and ``install/install.ps1`` against a real git checkout,
so the shipped logic cannot drift from what is tested.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.core.branding import (
    DEFAULT_OFFICIAL_REPO_SLUG,
    LEGACY_OFFICIAL_REPO_SLUGS,
    OFFICIAL_REPO_GIT_URL,
)
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

REPO = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO / "install" / "install.sh"
INSTALL_PS1 = REPO / "install" / "install.ps1"

BLOCK_BEGIN = "# --- retarget-legacy-origin begin"
BLOCK_END = "# --- retarget-legacy-origin end"

LEGACY_SLUG = LEGACY_OFFICIAL_REPO_SLUGS[0]
LEGACY_URL = f"https://github.com/{LEGACY_SLUG}.git"
CURRENT_URL = f"https://github.com/{DEFAULT_OFFICIAL_REPO_SLUG}.git"
OVERRIDES = ["JARVIS_INSTALL_REPO", "JARVIS_OFFICIAL_REPO_SLUG"]

SH_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
note() { printf 'NOTE|%s\\n' "$*"; }
source "$BLOCK_FILE"
"""

PS_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
$InstallDir = $env:TEST_INSTALL_DIR
$RepoUrl = $env:TEST_REPO_URL
$LegacyOfficialRepoSlug = $env:TEST_LEGACY_SLUG
. $env:TEST_FUNCTION_FILE
Update-LegacyOrigin
"""

GIT = shutil.which("git")


def _find_bash() -> str | None:
    if GIT:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe", "../usr/bin/bash.exe"):
            cand = (Path(GIT).parent / rel).resolve()
            if cand.exists():
                return str(cand)
    bash = shutil.which("bash")
    if bash and not any(t in bash.lower() for t in ("windowsapps", "system32")):
        return bash
    return None


BASH = _find_bash()
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")
needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="no PowerShell on this host"
)


def _run(
    args: list[str], *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- test-controlled command
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def _checkout(tmp_path: Path, origin: str | None) -> Path:
    root = tmp_path / "install"
    root.mkdir()
    assert _run([GIT, "init", "--quiet", str(root)]).returncode == 0
    if origin is not None:
        added = _run([GIT, "-C", str(root), "remote", "add", "origin", origin])
        assert added.returncode == 0, added.stderr
    return root


def _origin(root: Path) -> str:
    return _run(
        [GIT, "-C", str(root), "config", "--get", "remote.origin.url"]
    ).stdout.strip()


def _sh_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _base_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in OVERRIDES}


def _run_sh(
    tmp_path: Path, root: Path, **overrides: str
) -> subprocess.CompletedProcess[str]:
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert BLOCK_BEGIN in source and BLOCK_END in source, (
        "the retarget-legacy-origin extraction markers vanished from install.sh"
    )
    block = tmp_path / "block.sh"
    block.write_text(
        source.split(BLOCK_BEGIN, 1)[1].split(BLOCK_END, 1)[0],
        encoding="utf-8",
        newline="\n",
    )
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_DRIVER, encoding="utf-8", newline="\n")
    env = _base_env()
    env.update(
        BLOCK_FILE=_sh_path(block),
        INSTALL_DIR=_sh_path(root),
        REPO_URL=CURRENT_URL,
        LEGACY_OFFICIAL_REPO_SLUG=LEGACY_SLUG,
        **overrides,
    )
    return _run([BASH, str(driver)], env=env)


def _run_ps(
    tmp_path: Path, root: Path, **overrides: str
) -> subprocess.CompletedProcess[str]:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(
        r"^function Update-LegacyOrigin \{\r?\n.*?^\}\r?$", source, re.S | re.M
    )
    assert match is not None, "Update-LegacyOrigin vanished from install.ps1"
    function_file = tmp_path / "function.ps1"
    function_file.write_text(match.group(0), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_DRIVER, encoding="utf-8")
    env = _base_env()
    env.update(
        TEST_INSTALL_DIR=str(root),
        TEST_REPO_URL=CURRENT_URL,
        TEST_LEGACY_SLUG=LEGACY_SLUG,
        TEST_FUNCTION_FILE=str(function_file),
        **overrides,
    )
    return _run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(driver),
        ],
        env=env,
    )


def test_installer_projections_match_core_branding() -> None:
    shell = INSTALL_SH.read_text(encoding="utf-8")
    powershell = INSTALL_PS1.read_text(encoding="utf-8")
    assert len(LEGACY_OFFICIAL_REPO_SLUGS) == 1
    assert f'LEGACY_OFFICIAL_REPO_SLUG="{LEGACY_SLUG}"' in shell
    assert f"$LegacyOfficialRepoSlug = '{LEGACY_SLUG}'" in powershell
    assert CURRENT_URL == OFFICIAL_REPO_GIT_URL


LEGACY_FORMS = [
    LEGACY_URL,
    LEGACY_URL.removesuffix(".git"),
    LEGACY_URL.lower(),
    f"git@github.com:{LEGACY_SLUG}.git",
]
UNTOUCHED_FORMS = [
    CURRENT_URL,
    "https://github.com/someone/fork.git",
    f"https://github.com/{LEGACY_SLUG}Evil.git",
    f"https://github.com/evil/{LEGACY_SLUG.split('/')[1]}.git",
]


@needs_git
@needs_bash
@pytest.mark.parametrize("origin", LEGACY_FORMS)
def test_sh_rewrites_a_legacy_origin(tmp_path: Path, origin: str) -> None:
    root = _checkout(tmp_path, origin)
    proc = _run_sh(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == CURRENT_URL
    assert "NOTE|pointed this install at the renamed repository" in proc.stdout


@needs_git
@needs_bash
@pytest.mark.parametrize("origin", UNTOUCHED_FORMS)
def test_sh_leaves_other_origins_alone(tmp_path: Path, origin: str) -> None:
    root = _checkout(tmp_path, origin)
    proc = _run_sh(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == origin
    assert "NOTE|" not in proc.stdout


@needs_git
@needs_bash
@pytest.mark.parametrize("variable", OVERRIDES)
def test_sh_respects_an_explicit_repository_override(
    tmp_path: Path, variable: str
) -> None:
    root = _checkout(tmp_path, LEGACY_URL)
    proc = _run_sh(tmp_path, root, **{variable: "own/repo"})
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == LEGACY_URL


@needs_git
@needs_bash
def test_sh_tolerates_a_checkout_without_origin(tmp_path: Path) -> None:
    root = _checkout(tmp_path, None)
    proc = _run_sh(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == ""


@needs_git
@needs_powershell
@pytest.mark.parametrize("origin", LEGACY_FORMS)
def test_ps1_rewrites_a_legacy_origin(tmp_path: Path, origin: str) -> None:
    root = _checkout(tmp_path, origin)
    proc = _run_ps(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == CURRENT_URL
    assert "NOTE|pointed this install at the renamed repository" in proc.stdout


@needs_git
@needs_powershell
@pytest.mark.parametrize("origin", UNTOUCHED_FORMS)
def test_ps1_leaves_other_origins_alone(tmp_path: Path, origin: str) -> None:
    root = _checkout(tmp_path, origin)
    proc = _run_ps(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == origin
    assert "NOTE|" not in proc.stdout


@needs_git
@needs_powershell
@pytest.mark.parametrize("variable", OVERRIDES)
def test_ps1_respects_an_explicit_repository_override(
    tmp_path: Path, variable: str
) -> None:
    root = _checkout(tmp_path, LEGACY_URL)
    proc = _run_ps(tmp_path, root, **{variable: "own/repo"})
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == LEGACY_URL


@needs_git
@needs_powershell
def test_ps1_tolerates_a_checkout_without_origin(tmp_path: Path) -> None:
    root = _checkout(tmp_path, None)
    proc = _run_ps(tmp_path, root)
    assert proc.returncode == 0, proc.stderr
    assert _origin(root) == ""
